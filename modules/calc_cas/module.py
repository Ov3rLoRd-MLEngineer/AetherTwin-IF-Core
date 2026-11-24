"""Module du Hub : calculatrice à calcul formel (CAS), graphes, statistiques, outil pour les agents locaux.

Commandes reçues sur le bus (réponse sur `module.calc_cas.result`, avec le même `request_id`) :

    eval        {"text": "integrate(x^2, x)"}            résultat exact + approché (texte, LaTeX, MathML)
    vars        {}                                        variables et fonctions définies (« a := 3 », « f(x) := … »)
    delete      {"name": "a"}                             supprime une définition
    reset       {}                                        efface variables, fonctions et historique
    history     {}                                        derniers calculs
    render      {"latex": [...]}                          images PNG (base64) de formules, `null` si impossible
    plot        {"curves": [...], "window": {...}}        points des courbes (y, param, polar)
    analyze     {"what": "zeros"|"extrema"|"intersections", "expr", "other"?, "xmin", "xmax"}
    table       {"expr", "start", "step", "count"}       tableau de valeurs
    geometry    {"what", "points": [[x, y], …], "degrees"?}  mesure exacte (distance, angle, aire, cercle…)
                {"what": "figure", "objects": [...], "measure": {...}}  valeur exacte dans une construction
    stats       {"x": [...], "y"?: [...], "freq"?: [...]} statistiques à une / deux variables
    regress     {"x", "y", "model"}                       régression (linear, quadratic, cubic, exponential…)
    tools       {}                                        définitions des outils pour agents (schémas JSON)
    tool        {"name": "cas_compute", "arguments": {...}}   appel d'outil par un agent (session séparée)
    ask         {"question": "…"}                         le modèle local délègue ses calculs au CAS
    examples    {}                                        exemples de démonstration
    settings    {"angle": "rad"|"deg"}                    réglages de la session (renvoie les réglages)
    programs    {}                                        programmes enregistrés + exemples
    program_save   {"name", "code"}  ·  program_delete {"name"}
    program_run    {"code", "inputs": [...], "seed"}       exécution dans le bac à sable (`sandbox.py`)
    hermes      {}  ·  hermes_register {}                  serveur MCP de la calculatrice chez Hermes Agent
    game_run    {"code"}  ·  game_stop {}  ·  game_status {}   mode jeu : le programme dans sa fenêtre (`games.py`)
    emulators   {}  ·  emulator_launch {"emulator", "rom"}  ·  roms_open {}   émulateurs externes installés

Tous les calculs passent par un processus séparé avec délai maximal (`worker.py`) : un calcul pathologique est
interrompu et le module répond quand même. Variables, fonctions et historique sont gardés dans
`data/calc_cas/session.json` (ignoré par Git).

Configuration (section `calc_cas` de `config/local.yaml`), tout est facultatif :

    timeout_s: 10                          # délai maximal d'un calcul
    program_timeout_s: 10                  # délai maximal d'un programme
    program_memory_mb: 768                 # mémoire maximale du processus des programmes
    hub_api: "http://127.0.0.1:5750"       # modèle local du Hub, pour `ask` (vide = désactivé)
    model: ""                              # vide = modèle par défaut du Hub
    session: "data/calc_cas/session.json"
    roms_dir: "data/calc_cas/roms"         # dossier des ROM (fournies par l'utilisateur)
    emulators: {}                          # chemins d'émulateurs non détectés, ex. {dolphin: "D:/Dolphin/Dolphin.exe"}
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.calc_cas import agent, demos, emulators
from modules.calc_cas.worker import CasRunner

REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORY_MAX = 200
PROGRAMS_MAX = 100
PROGRAM_NAME = re.compile(r"^[^\W\d]\w{0,40}$")
GAMES_SCRIPT = REPO_ROOT / "modules" / "calc_cas" / "games.py"
MCP_NAME = "aethertwin_calc"
MCP_SCRIPT = REPO_ROOT / "modules" / "calc_cas" / "mcp_server.py"


def hub_llm(hub_api: str, model: str = "", timeout_s: float = 180.0) -> Callable[[list[dict[str, str]]], str]:
    """Appel du modèle local **par le Hub** (API compatible OpenAI), jamais directement."""
    def call(messages: list[dict[str, str]]) -> str:
        body: dict[str, Any] = {"messages": messages, "think": False, "temperature": 0.2}
        if model:
            body["model"] = model
        request = urllib.request.Request(hub_api.rstrip("/") + "/v1/chat/completions",  # noqa: S310
                                         data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 — API locale du Hub
            return str(json.loads(response.read().decode("utf-8"))["choices"][0]["message"]["content"])
    return call


class CalcCasModule(ModuleBase):
    def start(self) -> None:
        self.save_path = Path(str(self.config.get("session") or REPO_ROOT / "data" / "calc_cas" / "session.json"))
        self.runner = CasRunner(timeout_s=float(self.config.get("timeout_s", 10)))
        hub = str(self.config.get("hub_api", "http://127.0.0.1:5750"))
        self.llm = hub_llm(hub, str(self.config.get("model", ""))) if hub else None
        self.sandbox = CasRunner(timeout_s=float(self.config.get("program_timeout_s", 10)),
                                 memory_mb=int(self.config.get("program_memory_mb", 768)))
        self.history: list[dict[str, Any]] = []
        self.programs: dict[str, str] = {}
        self.game: Any = None
        self.game_stopped = False
        self.data_dir = self.save_path.parent
        self.roms_dir = Path(str(self.config.get("roms_dir") or self.data_dir / "roms"))
        self.load_error = ""
        try:
            if self.save_path.is_file():
                saved = json.loads(self.save_path.read_text(encoding="utf-8"))
                self.history = [h for h in saved.get("history", []) if isinstance(h, dict)][-HISTORY_MAX:]
                defs = saved.get("definitions", {})
                if isinstance(defs, dict):
                    self.runner.definitions["user"] = {str(k): str(v) for k, v in defs.items()}
                settings = saved.get("settings", {})
                if isinstance(settings, dict) and settings.get("angle") in ("rad", "deg"):
                    self.runner.settings["user"] = {"angle": settings["angle"]}
                programs = saved.get("programs", {})
                if isinstance(programs, dict):
                    self.programs = {str(k): str(v) for k, v in programs.items() if PROGRAM_NAME.match(str(k))}
        except (OSError, ValueError, AttributeError) as exc:
            self.load_error = f"session illisible ({exc}) : nouvelle session"
        try:
            self.runner.start()  # import de SymPy en arrière-plan : le premier calcul attendra qu'il soit prêt
        except OSError as exc:
            self.load_error = f"moteur de calcul non lancé : {exc}"

    def stop(self) -> None:
        self.game_stop()
        self._save()
        self.runner.stop()
        self.sandbox.stop()

    def health(self) -> Health:
        if self.runner.broken:
            return Health(ok=True, degraded=True, detail=f"moteur de calcul indisponible ({self.runner.broken})")
        detail = (f"{len(self.history)} calculs, {len(self.runner.definitions.get('user', {}))} définitions"
                  + (f", {self.runner.restarts} calcul(s) interrompu(s)" if self.runner.restarts else ""))
        if self.load_error:
            detail = f"{self.load_error} — {detail}"
        return Health(ok=True, degraded=self.llm is None, detail=detail + ("" if self.llm else " — sans modèle"))

    def _save(self) -> None:
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            self.save_path.write_text(json.dumps({"definitions": self.runner.definitions.get("user", {}),
                                                  "settings": self.runner.settings.get("user", {}),
                                                  "programs": self.programs,
                                                  "history": [{k: v for k, v in h.items() if k != "png"}
                                                              for h in self.history[-HISTORY_MAX:]]},
                                                 ensure_ascii=False,
                                                 indent=1), encoding="utf-8")
        except OSError:
            pass  # sauvegarde impossible (disque) : le calcul reste valable

    # -- mode jeu
    def game_running(self) -> bool:
        return self.game is not None and self.game.poll() is None

    def game_stop(self) -> bool:
        if not self.game_running():
            return False
        self.game_stopped = True
        self.game.terminate()
        try:
            self.game.wait(5)
        except subprocess.TimeoutExpired:
            self.game.kill()
        return True

    def game_run(self, code: str) -> dict[str, Any]:
        from modules.calc_cas.sandbox import MODULES, SandboxError, check_program

        try:  # refus immédiat d'un programme interdit, avant d'ouvrir une fenêtre
            check_program(code, {**MODULES, "jeu": None})
        except SandboxError as exc:
            return {"ok": False, "error": str(exc)}
        self.game_stop()
        self.game_stopped = False
        folder = self.data_dir / "games"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "partie.py").write_text(code, encoding="utf-8")
        python = sys.executable[:-5] + ".exe" if sys.executable.lower().endswith("pythonw.exe") else sys.executable
        log = (folder / "partie.log").open("w", encoding="utf-8")
        env = {**os.environ, "PYGAME_HIDE_SUPPORT_PROMPT": "1", "PYTHONIOENCODING": "utf-8"}
        self.game = subprocess.Popen([python, "-I", str(GAMES_SCRIPT), str(folder / "partie.py")],  # noqa: S603
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log.close()
        return {"ok": True, "running": True}

    def game_status(self) -> dict[str, Any]:
        path = self.data_dir / "games" / "partie.log"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[-4000:] if path.is_file() else ""
        except OSError:
            text = ""
        code = None if self.game is None or self.game_running() else self.game.returncode
        return {"running": self.game_running(), "output": text, "exit_code": code,
                "stopped": self.game_stopped}

    def hermes(self, register: bool = False) -> dict[str, Any]:
        """État du branchement MCP chez Hermes Agent ; `register` le déclare (config.yaml sauvegardée avant)."""
        from modules.dev_launcher import hermes_link
        from modules.genesis_lab.sources import hermes_exe

        exe = hermes_exe()
        result: dict[str, Any] = {}
        if register:
            result = hermes_link.register_server(exe, MCP_NAME, ["-I", str(MCP_SCRIPT)])
        config = hermes_link.hermes_home() / "config.yaml"
        text = config.read_text(encoding="utf-8", errors="replace") if config.is_file() else ""
        return {**result, "installe": bool(exe), "branche": hermes_link.registered(text, MCP_NAME), "nom": MCP_NAME}

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        try:
            reply = {"ok": True, "result": self.run(command, payload)}
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
            reply = {"ok": False, "error": str(exc) or type(exc).__name__}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"),
                                                           "command": command, **reply}, source=self.name))

    def run(self, command: str, payload: dict[str, Any]) -> Any:
        """Exécute une commande (aussi appelée directement par les tests)."""
        if command == "eval":
            text = payload.get("text")
            if not isinstance(text, str):
                raise ValueError("`text` (texte) obligatoire")
            result = self.runner.call("eval", text=text)
            self.history.append(result)
            self.history = self.history[-HISTORY_MAX:]
            self._save()
            return result
        if command == "vars":
            return self.runner.call("vars")
        if command == "delete":
            deleted = self.runner.call("delete", name=str(payload.get("name", "")))
            self._save()
            return deleted
        if command == "reset":
            self.runner.call("reset", target="user")
            self.history = []
            self._save()
            return True
        if command == "history":
            return self.history
        if command == "render":
            latex = payload.get("latex")
            if not isinstance(latex, list):
                raise ValueError("`latex` (liste) obligatoire")
            return self.runner.call("render", latex=[str(t) for t in latex[:50]])
        if command == "plot":
            return self.runner.call("plot", curves=payload.get("curves"), window=payload.get("window"),
                                    samples=int(payload.get("samples", 600)))
        if command == "analyze":
            return self.runner.call("analyze", **{k: payload.get(k) for k in ("what", "expr", "other", "xmin", "xmax")
                                                 if payload.get(k) is not None})
        if command == "table":
            return self.runner.call("table", **{k: payload.get(k) for k in ("expr", "start", "step", "count")
                                               if payload.get(k) is not None})
        if command == "geometry":
            keys = ("what", "points", "degrees", "objects", "measure")
            return self.runner.call("geometry", **{k: payload.get(k) for k in keys if payload.get(k) is not None})
        if command in ("stats", "regress"):
            return self.runner.call(command, **{k: payload.get(k) for k in ("x", "y", "freq", "model")
                                               if payload.get(k) is not None})
        if command == "game_run":
            code = payload.get("code")
            if not isinstance(code, str):
                raise ValueError("`code` (texte) obligatoire")
            return self.game_run(code)
        if command == "game_stop":
            return self.game_stop()
        if command == "game_status":
            return self.game_status()
        if command == "emulators":
            return emulators.catalog(self.roms_dir, self.config.get("emulators") or {})
        if command == "emulator_launch":
            found = emulators.detect(self.config.get("emulators") or {})
            args = emulators.command(str(payload.get("emulator", "")),
                                     emulators.rom_path(self.roms_dir, str(payload.get("rom", ""))), found)
            return {"pid": emulators.launch(args), "emulator": payload.get("emulator")}
        if command == "roms_open":
            self.roms_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(self.roms_dir)  # noqa: S606 — dossier fixe de la configuration
            return str(self.roms_dir)
        if command in ("hermes", "hermes_register"):
            return self.hermes(register=command == "hermes_register")
        if command == "tools":
            return agent.TOOL_SPECS
        if command == "tool":
            return agent.call_tool(self.runner, str(payload.get("name", "")), payload.get("arguments"))
        if command == "ask":
            if self.llm is None:
                raise RuntimeError("aucun modèle local configuré (calc_cas.hub_api)")
            try:
                return agent.ask(str(payload.get("question", "")), self.llm, self.runner)
            except OSError as exc:
                raise RuntimeError(f"modèle local injoignable par le Hub : {exc}") from exc
        if command == "examples":
            return demos.catalog()
        if command == "settings":
            values = {k: payload[k] for k in ("angle",) if k in payload}
            result = self.runner.call("settings", **values)
            self._save()
            return result
        if command == "programs":
            from modules.calc_cas.games_examples import GAMES
            from modules.calc_cas.sandbox import EXAMPLES
            return {"programs": self.programs, "examples": EXAMPLES, "games": GAMES}
        if command == "program_save":
            name, code = str(payload.get("name", "")).strip(), payload.get("code")
            if not PROGRAM_NAME.match(name):
                raise ValueError("nom de programme invalide (lettres, chiffres, « _ », 41 caractères au plus)")
            if not isinstance(code, str) or len(code) > 20_000:
                raise ValueError("programme absent ou trop long (20 000 caractères au plus)")
            if name not in self.programs and len(self.programs) >= PROGRAMS_MAX:
                raise ValueError(f"{PROGRAMS_MAX} programmes au plus : supprimes-en un")
            self.programs[name] = code
            self._save()
            return sorted(self.programs)
        if command == "program_delete":
            deleted = self.programs.pop(str(payload.get("name", "")), None) is not None
            self._save()
            return deleted
        if command == "program_run":
            code = payload.get("code")
            if not isinstance(code, str):
                raise ValueError("`code` (texte) obligatoire")
            inputs = payload.get("inputs") or []
            if not isinstance(inputs, list):
                raise ValueError("`inputs` doit être une liste")
            seed = payload.get("seed")
            return self.sandbox.call("program", code=code, inputs=[str(v) for v in inputs][:200],
                                     seed=int(seed) if isinstance(seed, int | float) else None, session="program")
        raise ValueError(f"commande inconnue : {command!r}")
