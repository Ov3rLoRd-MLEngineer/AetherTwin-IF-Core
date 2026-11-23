"""Module du Hub : lanceur de Claude Code local, pont MCP avec Hermes, tâches confiées, relais quota.

Commandes (bus, réponse sur `module.dev_launcher.result` avec le même `request_id`) :
    etat             {}                                     services, Claude Code, Hermes, préférences, relais
    modeles          {}                                     modèles Ollama (direct) et OmniRoute (facultatif)
    lancer           {"modele", "route", "contexte", "dossier", "mode": "windows" | "hub", "mcp", "outils_essentiels"}
                     écrit le lancement ; « windows » ouvre Windows Terminal, « hub » renvoie le fichier à ouvrir
                     dans un terminal du Hub (POST /terminals)
    dossiers         {}                                     dossiers où une tâche confiée peut travailler
    confier          {"tache", "dossier"?, "modele"?, "origine"?}   tâche à Claude Code local (sans surveillance)
    suivre           {"id"}  ·  taches {}
    brancher_hermes  {}                                     déclare le pont MCP chez Hermes (config sauvegardée)
    demander_hermes  {"question"}                           question à Hermes (travail)
    test_relais      {}                                     essai d'accusé de réception du relais (travail)
    travail          {"cle"}

Configuration (section `dev_launcher` de `config/local.yaml`), tout est facultatif :
    claude_local_dir: ""          # dossier du Claude Code local (Claude Code installé dans node_modules)
    ancien_lanceur: ""            # dossier de l'ancien lanceur (liste des modèles OmniRoute exportée)
    ollama_url: "http://127.0.0.1:11434"
    omniroute_url: "http://127.0.0.1:20128"
    omniroute_cle_env: "OMNIROUTE_API_KEY"   # nom de la variable qui contient la clé (jamais la clé)
    dossiers_autorises: []        # vide = <claude_local_dir>/travaux
    modele_taches: ""             # vide = un modèle Ollama servi avec au moins 64 k de contexte
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.module_api import Event, Health, Manifest, ModuleBase
from modules.dev_launcher import catalog, hermes_link, launch, relay_check
from modules.dev_launcher.tasks import TaskError, TaskRunner

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "dev_launcher"
DEFAULT_TASK_MODEL = "qwen3-coder:30b-a3b-q4_K_M"
# Le prompt système et les outils de Claude Code occupent ~25 k jetons : sous 64 k, la conversation se
# résume en boucle (« Autocompact is thrashing », observé avec le contexte par défaut d'Ollama, 32 k).
CLAUDE_MIN_CONTEXT = 65536
OLLAMA_DEFAULT_CONTEXT = 32768
PREFERRED = ("coder", "devstral", "codestral")


class Jobs:
    """Travaux en arrière-plan suivis par clé (même forme que ceux du Professeur)."""

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self.now, self.items, self._lock = now, {}, threading.Lock()

    def start(self, key: str, label: str, work: Callable[[], Any]) -> dict[str, Any]:
        with self._lock:
            job = self.items.get(key)
            if job and job["en_cours"]:
                return self.view(key)
            job = {"cle": key, "libelle": label, "en_cours": True, "debut": self.now(), "fin": None,
                   "resultat": None, "erreur": ""}
            self.items[key] = job

        def run() -> None:
            try:
                job["resultat"] = work()
            except Exception as exc:  # noqa: BLE001 — erreur rendue à l'appelant
                job["erreur"] = str(exc) or type(exc).__name__
            job["fin"], job["en_cours"] = self.now(), False

        threading.Thread(target=run, name=f"dev-{key}", daemon=True).start()
        return self.view(key)

    def view(self, key: str) -> dict[str, Any]:
        job = self.items.get(key)
        if job is None:
            raise ValueError("travail inconnu")
        return {**job, "duree": round((job["fin"] or self.now()) - job["debut"], 1)}


class DevLauncherModule(ModuleBase):
    def __init__(self, manifest: Manifest, config: dict[str, Any] | None = None) -> None:
        super().__init__(manifest, config)
        self.jobs = Jobs()
        self.requests = self.errors = 0
        self.data = Path(str(self.config.get("data_dir") or DATA_DIR))
        self._hermes_exe: str | None = None
        self._question = 0
        self.tasks: TaskRunner | None = None

    # -- configuration
    def _cfg(self, key: str, default: str = "") -> str:
        return str(self.config.get(key) or default)

    @property
    def claude_dir(self) -> Path | None:
        value = self._cfg("claude_local_dir")
        return Path(value) if value else None

    def roots(self) -> list[Path]:
        wanted = self.config.get("dossiers_autorises") or []
        roots = [Path(str(p)) for p in wanted if str(p).strip()] if isinstance(wanted, list) else []
        if not roots and self.claude_dir:
            roots = [self.claude_dir / "travaux"]
        return roots

    def served_context(self, model: str) -> int:
        """Contexte servi par Ollama pour ce modèle (`num_ctx` du Modelfile, sinon le défaut d'Ollama)."""
        return catalog.num_ctx(self._cfg("ollama_url", "http://127.0.0.1:11434"), model) or OLLAMA_DEFAULT_CONTEXT

    def task_model(self, wanted: str = "") -> str:
        """Modèle des tâches sans surveillance : demandé, configuré, sinon un modèle servi avec ≥ 64 k."""
        model = wanted or self._cfg("modele_taches", "")
        if model:
            return model
        listed = catalog.ollama_models(self._cfg("ollama_url", "http://127.0.0.1:11434")).get("modeles", [])
        large = [m for m in listed if (m.get("contexte_regle") or 0) >= CLAUDE_MIN_CONTEXT]
        rank = lambda m: next((i for i, word in enumerate(PREFERRED) if word in m["id"].lower()), len(PREFERRED))  # noqa: E731
        large.sort(key=lambda m: (rank(m), m["id"].lower()))
        return large[0]["id"] if large else DEFAULT_TASK_MODEL

    def env_for(self, model: str = "", route: str = "ollama", context: int = 0) -> dict[str, str]:
        model = self.task_model(model) if route == "ollama" else model
        if route == "ollama" and not context:
            context = self.served_context(model)
        return launch.route_env(route, model, context, self._cfg("ollama_url", "http://127.0.0.1:11434"),
                                self._cfg("omniroute_url", "http://127.0.0.1:20128"))

    @staticmethod
    def context_warning(env: dict[str, str]) -> str:
        window = int(env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS") or 0)
        if window >= CLAUDE_MIN_CONTEXT:
            return ""
        return (f"contexte de {window} jetons : Claude Code a besoin d'au moins {CLAUDE_MIN_CONTEXT} (son prompt "
                "et ses outils en prennent ~25 k). Choisir un modèle « -64k » ou en créer un (Modelfile, "
                "PARAMETER num_ctx 65536).")

    def hermes_exe(self) -> str:
        if self._hermes_exe is None:
            from modules.genesis_lab.sources import hermes_exe
            self._hermes_exe = hermes_exe()
        return self._hermes_exe

    # -- cycle de vie
    def start(self) -> None:
        self.tasks = TaskRunner(self.data, self.roots(), lambda: launch.claude_command(self.claude_dir),
                                lambda model: self.env_for(model))

    def stop(self) -> None:
        self.tasks = None

    def health(self) -> Health:
        return Health(ok=True, detail=f"lanceur de Claude Code local ; {self.requests} demandes, {self.errors} erreurs")

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        self.requests += 1
        try:
            reply = {"ok": True, "result": self._run(command, payload)}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.errors += 1
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.publish(Event(f"module.{self.name}.result",
                           {"request_id": payload.get("request_id"), "command": command, **reply}, source=self.name))

    # -- préférences
    def _prefs_path(self) -> Path:
        return self.data / "preferences.json"

    def prefs(self) -> dict[str, Any]:
        try:
            data = json.loads(self._prefs_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def save_prefs(self, values: dict[str, Any]) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        self._prefs_path().write_text(json.dumps({**self.prefs(), **values}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")

    # -- commandes
    def state(self) -> dict[str, Any]:
        ollama = self._cfg("ollama_url", "http://127.0.0.1:11434")
        omni = self._cfg("omniroute_url", "http://127.0.0.1:20128")
        claude = launch.claude_command(self.claude_dir)
        exe = self.hermes_exe()
        return {
            "services": {"ollama": {"url": ollama, "en_ligne": catalog.service_up(ollama + "/api/version")},
                         "omniroute": {"url": omni, "en_ligne": catalog.service_up(omni.rstrip("/") + "/"),
                                       "cle": bool(os.environ.get(self._cfg("omniroute_cle_env",
                                                                            "OMNIROUTE_API_KEY")))}},
            "claude": {"commande": "npx (téléchargé à chaque lancement)" if claude[0] == "npx" else claude[0],
                       "dossier": str(self.claude_dir or ""), "installe": claude[0] != "npx"},
            "windows_terminal": bool(launch.windows_terminal()),
            "hermes": hermes_link.state(exe),
            "dossiers_autorises": [str(r) for r in self.roots()],
            "preferences": self.prefs(),
            "relais": {"essai": relay_check.last_report(self.data / "relais_essai.json"),
                       "etat": relay_check.relay_state(REPO_ROOT)},
        }

    def models(self) -> dict[str, Any]:
        legacy = self._cfg("ancien_lanceur")
        return {"ollama": catalog.ollama_models(self._cfg("ollama_url", "http://127.0.0.1:11434")),
                "omniroute": catalog.omniroute_models(self._cfg("omniroute_url", "http://127.0.0.1:20128"),
                                                      self._cfg("omniroute_cle_env", "OMNIROUTE_API_KEY"),
                                                      Path(legacy) / "liste modèles json.txt" if legacy else None)}

    def launch(self, payload: dict[str, Any]) -> dict[str, Any]:
        model, route = str(payload.get("modele", "")), str(payload.get("route", "ollama"))
        context = int(payload.get("contexte") or 0)
        folder = Path(str(payload.get("dossier") or self.claude_dir or Path.home()))
        if not folder.is_dir():
            raise launch.LaunchError(f"dossier introuvable : {folder}")
        mode = str(payload.get("mode", "windows"))
        if mode not in ("windows", "hub"):
            raise launch.LaunchError("mode inconnu (windows ou hub)")
        env = launch.route_env(route, model, context, self._cfg("ollama_url", "http://127.0.0.1:11434"),
                               self._cfg("omniroute_url", "http://127.0.0.1:20128"))
        mcp = launch.mcp_config(self.data / "mcp_claude.json") if payload.get("mcp", True) else None
        title = f"Claude Code · {model}"
        tools = launch.ESSENTIAL_TOOLS if payload.get("outils_essentiels", True) else ""
        script = launch.batch_script(env, folder, launch.claude_command(self.claude_dir), title, mcp, tools)
        bat = launch.write_launch(self.data / "lancements", script)
        self.save_prefs({"modele": model, "route": route, "contexte": context, "dossier": str(folder), "mode": mode,
                         "mcp": bool(mcp), "outils_essentiels": bool(tools)})
        # Ollama coupe au contexte qu'il sert, quel que soit celui annoncé à Claude Code.
        served = env
        if route == "ollama":
            window = min(int(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"]), self.served_context(model))
            served = {**env, "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(window)}
        warning = {"avertissement": w} if (w := self.context_warning(served)) else {}
        if mode == "hub":
            return {"mode": "hub", "lancement": bat.name, "titre": title, **warning}
        where = launch.open_in_windows_terminal(bat, folder, title)
        return {"mode": "windows", "ouvert": where, "titre": title, **warning}

    def _run(self, command: str, payload: dict[str, Any]) -> Any:
        tasks = self.tasks
        if tasks is None:
            raise ValueError("module non démarré")
        if command == "etat":
            return self.state()
        if command == "modeles":
            return self.models()
        if command == "lancer":
            return self.launch(payload)
        if command == "dossiers":
            return {"dossiers": [str(r) for r in self.roots()]}
        if command == "confier":
            started = tasks.start(str(payload.get("tache", "")), str(payload.get("dossier", "")),
                                  str(payload.get("modele", "")), str(payload.get("origine", "Hub")))
            warning = self.context_warning(self.env_for(started["modele"]))
            return {**started, "avertissement": warning} if warning else started
        if command == "suivre":
            return tasks.view(str(payload.get("id", "")))
        if command == "taches":
            return {"taches": tasks.list()}
        if command == "brancher_hermes":
            result = hermes_link.register(self.hermes_exe())
            return {**result, "hermes": hermes_link.state(self.hermes_exe())}
        if command == "demander_hermes":
            question = str(payload.get("question", "")).strip()
            if not question:
                raise TaskError("question vide")
            from modules.genesis_lab.sources import hermes_verifier
            ask = hermes_verifier(self.hermes_exe())
            if ask is None:
                raise ValueError("Hermes Agent introuvable sur ce PC")
            self._question += 1
            return {"travail": self.jobs.start(f"hermes:{self._question}", "Question à Hermes",
                                               lambda: {"reponse": ask(question[:8000])})}
        if command == "test_relais":
            env = self.env_for(str(payload.get("modele", "")))
            claude = launch.claude_command(self.claude_dir)
            return {"travail": self.jobs.start("relais", "Essai du relais (accusé de réception)",
                                               lambda: relay_check.run_ack_test(
                                                   REPO_ROOT, claude, env, self.data / "relais_essai.json"))}
        if command == "travail":
            return self.jobs.view(str(payload.get("cle", "")))
        raise ValueError(f"commande inconnue : {command!r}")
