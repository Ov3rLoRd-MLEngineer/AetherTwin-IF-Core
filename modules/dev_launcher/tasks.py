"""Tâches confiées à Claude Code local (par Hermes, par le Hub) : exécution sans surveillance, encadrée.

- Dossier de travail : uniquement dans les dossiers autorisés (section `dev_launcher`, `dossiers_autorises` ;
  par défaut `<Claude Code local>/travaux`). Sans dossier précisé, un sous-dossier neuf par tâche.
- Environnement nettoyé : aucune variable dont le nom évoque un secret (clé, jeton, mot de passe) n'est transmise,
  sauf le jeton factice du serveur local.
- Claude Code tourne en `-p` (sans interface), modifications de fichiers acceptées dans le dossier, mais ni
  commandes système, ni web, ni lecture des fichiers sensibles (.env, .bat, clés) ; aucun serveur MCP (pas de
  boucle Hermes -> Claude -> Hermes).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|COOKIE|SESSION", re.I)
TASK_ID = re.compile(r"^[0-9a-f]{12}$")  # secrets.token_hex(6)
# Outils proposés au modèle : les seuls utiles à une tâche de code. Avec les ~20 outils de Claude Code, les
# modèles locaux écrivent leurs appels en texte au lieu de les émettre (observé avec qwen3-coder et devstral).
TOOLS = "Read,Write,Edit,Glob,Grep"
DENY = ["Bash", "WebFetch", "WebSearch", "Read(//**/.env)", "Read(//**/.env.*)", "Read(//**/*.bat)",
        "Read(//**/*.key)", "Read(//**/*.pem)", "Read(//**/settings.json)", "Read(//**/shared.json)",
        "Read(~/.ssh/**)", "Read(~/AppData/**)"]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class TaskError(ValueError):
    """Dossier non autorisé, tâche vide ou inconnue."""


def clean_env(extra: dict[str, str]) -> dict[str, str]:
    """Environnement du processus sans secrets, plus les variables de la route (jeton factice compris)."""
    env = {k: v for k, v in os.environ.items()
           if not SECRET_NAME.search(k) and not k.upper().startswith(("AETHERTWIN_BUS", "CLAUDE", "ANTHROPIC_"))}
    env.update(extra)
    return env


def inside(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    return any(resolved == root.resolve() or root.resolve() in resolved.parents for root in roots)


def brief(task: str, workdir: Path) -> str:
    """Consigne envoyée au modèle : la tâche, précédée de son dossier (sinon il écrit ailleurs, et c'est refusé)."""
    return (f"Ton dossier de travail est {workdir}. Crée et modifie les fichiers uniquement dans ce dossier, avec "
            "des chemins relatifs (par exemple « bonjour.py »). Pas de commande shell : utilise les outils Write, "
            "Edit et Read. Termine par un court résumé de ce que tu as fait.\n\nTâche :\n" + task)


class TaskRunner:
    """Lance, suit et garde la trace des tâches (`<data>/taches/<id>.json` et `.log`)."""

    def __init__(self, data_dir: Path, roots: list[Path], command: Callable[[], list[str]],
                 env: Callable[[str], dict[str, str]], runner: Callable[..., Any] = subprocess.Popen,
                 now: Callable[[], float] = time.time, timeout_s: float = 1800.0) -> None:
        self.dir = Path(data_dir) / "taches"
        self.roots, self.command, self.env, self.runner, self.now = roots, command, env, runner, now
        self.timeout_s = timeout_s
        self._lock = threading.Lock()

    def folder(self, wanted: str, task_id: str) -> Path:
        if not self.roots:
            raise TaskError("aucun dossier autorisé (section dev_launcher, dossiers_autorises)")
        if wanted:
            path = Path(wanted)
            if not path.is_absolute():
                path = self.roots[0] / path
            if not inside(path, self.roots):
                raise TaskError("dossier non autorisé : " + ", ".join(str(r) for r in self.roots))
        else:
            path = self.roots[0] / f"tache_{task_id}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def settings_file(self) -> Path:
        path = self.dir / "permissions.json"
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"permissions": {"deny": DENY}}, indent=1), encoding="utf-8")
        return path

    def _save(self, state: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / f"{state['id']}.json"
        temp = target.with_suffix(f".{threading.get_ident()}.tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        with self._lock:  # remplacement atomique : une lecture ne voit jamais un fichier à moitié écrit
            for attempt in range(20):
                try:
                    os.replace(temp, target)
                    break
                except PermissionError:  # Windows : fichier ouvert en lecture à cet instant
                    if attempt == 19:
                        raise
                    time.sleep(0.02)

    def start(self, task: str, folder: str = "", model: str = "", origin: str = "hub") -> dict[str, Any]:
        task = (task or "").strip()
        if not task:
            raise TaskError("tâche vide")
        task_id = secrets.token_hex(6)
        workdir = self.folder(folder, task_id)
        env = self.env(model)
        cmd = [*self.command(), "-p", "--model", env["ANTHROPIC_MODEL"], "--permission-mode", "acceptEdits",
               "--strict-mcp-config", "--tools", TOOLS, "--settings", str(self.settings_file()),
               "--output-format", "text"]
        state = {"id": task_id, "tache": task[:4000], "dossier": str(workdir), "modele": env["ANTHROPIC_MODEL"],
                 "origine": origin[:40], "debut": self.now(), "fin": None, "etat": "en cours", "code": None}
        self._save(state)
        log_path = self.dir / f"{task_id}.log"

        def run() -> None:
            with open(log_path, "wb") as log:
                try:
                    proc = self.runner(cmd, cwd=str(workdir), env=clean_env(env), stdin=subprocess.PIPE,
                                       stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
                    proc.communicate(brief(task, workdir).encode("utf-8"), timeout=self.timeout_s)
                    state["code"] = proc.returncode
                    state["etat"] = "terminée" if proc.returncode == 0 else "échec"
                except subprocess.TimeoutExpired:
                    proc.kill()
                    state["etat"] = "arrêtée (délai dépassé)"
                except OSError as exc:
                    log.write(f"\nlancement impossible : {exc}\n".encode())
                    state["etat"] = "échec"
            state["fin"] = self.now()
            self._save(state)

        threading.Thread(target=run, name=f"tache-{task_id}", daemon=True).start()
        return self.view(task_id)

    def view(self, task_id: str, tail: int = 6000) -> dict[str, Any]:
        if not TASK_ID.match(task_id or ""):
            raise TaskError("identifiant de tâche invalide")
        try:
            state = json.loads((self.dir / f"{task_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TaskError("tâche inconnue") from exc
        try:
            output = (self.dir / f"{task_id}.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            output = ""
        files = []
        folder = Path(state["dossier"])
        if folder.is_dir():
            files = sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())[:50]
        end = state.get("fin") or self.now()
        return {**state, "duree": round(end - state["debut"], 1), "sortie": output[-tail:], "fichiers": files}

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        items = []
        for path in sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if TASK_ID.match(path.stem):
                view = self.view(path.stem, tail=400)
                items.append(view)
            if len(items) >= limit:
                break
        return items
