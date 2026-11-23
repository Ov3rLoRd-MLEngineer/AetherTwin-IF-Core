"""Essai du relais quota : l'agent local reçoit la passation et en accuse réception, sans rien modifier.

Le relais complet (`scripts/relay_orchestrator.py`) bascule sur Claude Code local quand le quota de Claude Code API
est épuisé, puis rend la main avec un résumé à relire. Ici, on provoque une bascule à la main :
1. le prompt de reprise de l'agent local est construit comme dans le relais (lecture de AGENT_HANDOFF.md…) ;
2. Claude Code local le reçoit, **sans droit d'écriture ni de commande**, et répond « RELAIS REÇU » avec la mission
   et la prochaine tâche qu'il reprendrait ;
3. le prompt de retour vers Claude Code API est construit (journal, commits, diff) pour montrer la passation
   retour. Rien n'est commité, aucun fichier n'est modifié.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from modules.dev_launcher.tasks import NO_WINDOW, clean_env

ACK_TASKS = ("ESSAI DU RELAIS SEULEMENT. Ne modifie aucun fichier, ne lance aucune commande, ne fais aucun commit. "
             "Lis le début de AGENT_HANDOFF.md, puis réponds en 6 lignes au plus : la première ligne exactement "
             "« RELAIS REÇU », puis le titre complet de la section « Où on en est » recopié tel quel (avec sa "
             "date), la mission en cours et la prochaine tâche que tu reprendrais si on te le demandait.")
ACK = re.compile(r"RELAIS?\s+RE[ÇC]U", re.I)  # « RELAI REÇU » observé avec qwen3-coder
# Outils de lecture seulement : proposés seuls, les modèles locaux les appellent vraiment (voir tasks.TOOLS).
ACK_TOOLS = "Read,Glob,Grep"
READ_ONLY = ["Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "WebFetch", "WebSearch"]


def load_relay(repo: Path) -> Any:
    path = Path(repo) / "scripts" / "relay_orchestrator.py"
    spec = importlib.util.spec_from_file_location("relay_orchestrator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("scripts/relay_orchestrator.py introuvable")
    if "relay_orchestrator" in sys.modules:
        return sys.modules["relay_orchestrator"]
    module = importlib.util.module_from_spec(spec)
    sys.modules["relay_orchestrator"] = module  # ses dataclasses le cherchent dans sys.modules
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("relay_orchestrator", None)
        raise
    return module


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30, creationflags=NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def run_ack_test(repo: Path, claude: list[str], env: dict[str, str], out: Path,
                 runner: Callable[..., Any] = subprocess.run, timeout_s: float = 900.0,
                 now: Callable[[], float] = time.time) -> dict[str, Any]:
    relay = load_relay(repo)
    prompt = (relay.build_local_prompt(ACK_TASKS) + "\n\nRAPPEL : c'est un essai. Lis AGENT_HANDOFF.md avec "
              "l'outil Read, puis réponds ; ta première ligne est exactement « RELAIS REÇU ».")
    cmd = [*claude, "-p", "--model", env["ANTHROPIC_MODEL"], "--strict-mcp-config", "--output-format", "text",
           "--tools", ACK_TOOLS, "--disallowedTools", *READ_ONLY]
    heading = next((line[3:].strip() for line in (Path(repo) / "AGENT_HANDOFF.md").read_text(
        encoding="utf-8", errors="replace").splitlines() if line.startswith("## Où on en est")), "")
    head_before = _git(repo, "rev-parse", "HEAD")
    status_before = _git(repo, "status", "--porcelain")
    start = now()
    result = runner(cmd, cwd=str(repo), env=clean_env(env), input=prompt.encode("utf-8"), capture_output=True,
                    timeout=timeout_s, creationflags=NO_WINDOW)
    answer = (result.stdout or b"").decode("utf-8", "replace").strip()
    if not answer:
        answer = (result.stderr or b"").decode("utf-8", "replace").strip()[-1500:]
    untouched = _git(repo, "rev-parse", "HEAD") == head_before and _git(repo, "status", "--porcelain") == status_before
    back = relay.build_resume_prompt(relay.DEFAULT_MISSION, relay.tail_text(Path(repo) / relay.CHANGELOG, 1500),
                                     _git(repo, "log", "--oneline", f"{head_before}..HEAD"), "", "")
    report = {"date": now(), "duree": round(now() - start, 1), "modele": env["ANTHROPIC_MODEL"],
              "route": env["ANTHROPIC_BASE_URL"], "code": result.returncode,
              "recu": bool(ACK.search(answer)), "depot_intact": untouched,
              # Preuve de lecture : le titre exact (avec sa date) ne se devine pas.
              "lu": bool(heading) and " ".join(heading.split()) in " ".join(answer.split()), "titre_attendu": heading,
              "reponse_locale": answer[-3000:], "retour_cloud": back[:1800]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def last_report(out: Path) -> dict[str, Any] | None:
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def relay_state(repo: Path) -> dict[str, Any] | None:
    """État du relais complet s'il a tourné (`logs/relay_state.json`)."""
    try:
        data = json.loads((Path(repo) / "logs" / "relay_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {k: data.get(k) for k in ("phase", "t0", "resume_at", "cycles", "cloud_runs", "last_event")}
