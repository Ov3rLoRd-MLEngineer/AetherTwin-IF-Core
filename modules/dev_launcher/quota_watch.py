"""Veilleur de quota : quand Claude (app de bureau ou Claude Code) atteint sa limite d'usage, Claude Code local prend
le relais dans une fenêtre Windows Terminal, le confirme et demande à Jérémy s'il veut continuer ou attendre.

Le relais complet (`scripts/relay_orchestrator.py`) ne voit que l'agent cloud qu'il lance lui-même. Ce veilleur,
lui, lit les transcriptions que Claude Code écrit pour **toutes** ses sessions (`~/.claude/projects/*/*.jsonl`,
app de bureau comprise) et y repère le message de limite, par exemple :

    {"type": "assistant", "isApiErrorMessage": true, "error": "rate_limit",
     "message": {"content": [{"text": "You've hit your 5-hour limit · resets 7:30pm (Europe/Paris)"}]}}

Seules les lignes écrites **après** le démarrage du veilleur comptent. À la première limite :
1. il écrit la passation (`data/dev_launcher/relais/passation.md`) : heure de retour de Claude, dernière demande
   de Jérémy, état du dépôt ;
2. il ouvre Claude Code local (modèle Ollama servi avec ≥ 64 k de contexte), en mode « demander avant chaque
   action », avec pour premier message : lire la passation et la suivre ;
3. il s'arrête (une seule passation par lancement).

    .venv\\Scripts\\python.exe -m modules.dev_launcher.quota_watch            surveille (Ctrl+C pour arrêter)
    .venv\\Scripts\\python.exe -m modules.dev_launcher.quota_watch --essai    passation tout de suite (essai réel)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RELAY_DIR = REPO_ROOT / "data" / "dev_launcher" / "relais"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
LOCAL_TOOLS = "Read,Write,Edit,Glob,Grep,Bash"
LIMIT_TEXT = re.compile(r"hit your [\w\s-]*limit|usage limit|limit reached|out of (?:extra )?usage", re.I)
RESETS = re.compile(r"resets\s+(?P<when>[^(·]+?)\s*(?:\((?P<tz>[^)]+)\))?\s*$", re.I)
CLOCK = re.compile(r"^(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?$", re.I)
FIRST_MESSAGE = "Lis le fichier data/dev_launcher/relais/passation.md et suis ses consignes."


# ------------------------------------------------------------------ lecture des transcriptions
def _text(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else message
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""


def french_time(when: str) -> str:
    """« 7:30pm » → « 19 h 30 » ; tout autre format est rendu tel quel."""
    match = CLOCK.match(when.strip())
    if not match:
        return when.strip()
    hour, minute = int(match["h"]), int(match["m"] or 0)
    ampm = (match["ampm"] or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return f"{hour} h {minute:02d}"


def parse_limit(record: Any) -> dict[str, str] | None:
    """Message de limite d'usage dans une ligne de transcription, sinon None."""
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return None
    text = _text(record.get("message")).strip()
    is_error = bool(record.get("isApiErrorMessage")) or record.get("error") == "rate_limit"
    if not (is_error and LIMIT_TEXT.search(text)):
        return None
    reset = ""
    match = RESETS.search(text)
    if match:
        reset = french_time(match["when"]) + (f" ({match['tz']})" if match["tz"] else "")
    return {"text": text[:300], "reset": reset, "session": str(record.get("sessionId", "")),
            "cwd": str(record.get("cwd", "")), "timestamp": str(record.get("timestamp", ""))}


def last_user_request(lines: Iterable[str], limit: int = 1500) -> str:
    """Dernier message écrit par l'utilisateur (pas un résultat d'outil ni un rappel système)."""
    found = ""
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "user" or record.get("isMeta"):
            continue
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "tool_result" for p in content):
            continue
        text = _text(message).strip()
        if text and not text.startswith("<"):
            found = text
    return found[:limit]


class Watcher:
    """Lit seulement ce qui s'ajoute aux transcriptions depuis le démarrage."""

    def __init__(self, root: Path = PROJECTS_DIR) -> None:
        self.root = root
        self.offsets: dict[Path, int] = {path: path.stat().st_size for path in self.files()}

    def files(self) -> list[Path]:
        return sorted(self.root.glob("*/*.jsonl")) if self.root.is_dir() else []

    def poll(self) -> tuple[dict[str, str], Path] | None:
        for path in self.files():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            start = self.offsets.get(path, 0)  # fichier apparu après le démarrage : lu depuis le début
            if size <= start:
                self.offsets[path] = size
                continue
            with path.open("rb") as handle:
                handle.seek(start)
                chunk = handle.read(size - start)
            complete = chunk.rfind(b"\n") + 1  # une ligne en cours d'écriture sera relue au tour suivant
            self.offsets[path] = start + complete
            for line in chunk[:complete].decode("utf-8", "replace").splitlines():
                try:
                    info = parse_limit(json.loads(line))
                except ValueError:
                    continue
                if info:
                    return info, path
        return None


# ------------------------------------------------------------------ passation
def _launcher() -> Any:
    """Le module du Hub, sans le démarrer : seulement ses règles de choix du modèle et ses variables."""
    from core.config import section
    from modules.dev_launcher.module import DevLauncherModule

    launcher = DevLauncherModule.__new__(DevLauncherModule)
    launcher.config = section("dev_launcher")
    return launcher


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def handoff_text(info: dict[str, str], request: str, model: str, git_log: str, git_status: str,
                 essai: bool = False) -> str:
    reset = info.get("reset") or "heure inconnue"
    lines = [
        "# Passation : Claude Code local prend le relais",
        "",
        ("**ESSAI DE PASSATION** déclenché à la main pour vérifier le relais : le quota n'est pas réellement atteint."
         if essai else f"Claude (cloud) vient d'atteindre sa limite d'usage : « {info.get('text', '')} »."),
        f"Retour prévu de Claude : **{reset}**.",
        "",
        "## Ta toute première réponse (obligatoire, rien d'autre avant)",
        "",
        "Réponds en français, sans lancer d'outil, en deux parties :",
        f"1. une ligne qui commence exactement par « RELAIS PRIS » : tu es Claude Code local ({model}) et tu prends "
        f"le relais de Claude, dont le quota revient à {reset} ;",
        "2. demande à Jérémy s'il veut que tu **continues** (et sur quoi) ou s'il préfère **attendre** le retour de "
        "Claude.",
        "",
        "Puis **attends sa réponse** : ne modifie rien, ne lance aucune commande avant qu'il ait répondu.",
        "",
        "## S'il te demande de continuer",
        "",
        "- Projet : AetherTwin, dans ce dossier. Lis d'abord `CLAUDE.md`, puis la section « Où on en est » de",
        "  `AGENT_HANDOFF.md` et les lignes « EN COURS » de `PROJECT_STATUS.md`.",
        "- Réponds toujours en français. Ne pousse jamais (`git push` interdit). Ne touche pas au Hub de Jérémy",
        "  (port 5750). Ne modifie pas les documents finaux gelés (README final, HARDWARE_FIT, DEMO_SCRIPT,",
        "  overlord_notes).",
        "- Travaille par petites étapes, lance les tests concernés (`.venv\\Scripts\\python.exe -m pytest …`), et",
        "  commite ton travail avec un message qui commence par `wip(local):` pour que Claude le relise à son retour.",
        "- Ce qui n'est pas fini s'écrit « en cours », jamais « reporté ».",
        "",
        "## Dernière demande de Jérémy dans la session de Claude",
        "",
        "```text",
        request or "(introuvable)",
        "```",
        "",
        "## État du dépôt",
        "",
        "```text",
        git_log or "(journal indisponible)",
        "",
        git_status or "(aucune modification en cours)",
        "```",
        "",
    ]
    return "\n".join(lines)


def open_local(model: str = "", claude_dir: str = "", spawner: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Ouvre Claude Code local dans Windows Terminal, premier message = lire la passation."""
    from modules.dev_launcher import launch

    module = _launcher()
    env = module.env_for(model)
    folder = REPO_ROOT
    command = launch.claude_command(Path(claude_dir) if claude_dir else module.claude_dir)
    script = launch.batch_script(env, folder, command, "Relais AetherTwin", tools=LOCAL_TOOLS, confirm=True,
                                 prompt=FIRST_MESSAGE)
    bat = launch.write_launch(RELAY_DIR / "lancements", script)
    how = launch.open_in_windows_terminal(bat, folder, "Relais AetherTwin", **({"spawner": spawner} if spawner else {}))
    return {"model": env["ANTHROPIC_MODEL"], "bat": str(bat), "how": how}


def hand_over(info: dict[str, str], transcript: Path | None, model: str = "", essai: bool = False,
              opener: Callable[..., dict[str, Any]] = open_local) -> dict[str, Any]:
    request = ""
    if transcript and transcript.is_file():
        request = last_user_request(transcript.read_text(encoding="utf-8", errors="replace").splitlines())
    chosen = _launcher().task_model(model)
    RELAY_DIR.mkdir(parents=True, exist_ok=True)
    (RELAY_DIR / "passation.md").write_text(
        handoff_text(info, request, chosen, _git("log", "--oneline", "-8"), _git("status", "--short"), essai),
        encoding="utf-8")
    opened = opener(chosen)
    record = {"quand": time.strftime("%Y-%m-%d %H:%M:%S"), "essai": essai, "limite": info,
              "transcription": str(transcript or ""), **opened}
    with (RELAY_DIR / "journal.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--essai", action="store_true", help="passation immédiate (essai réel, sans quota atteint)")
    parser.add_argument("--modele", default="", help="modèle Ollama (défaut : servi avec ≥ 64 k de contexte)")
    parser.add_argument("--intervalle", type=float, default=5.0, help="secondes entre deux lectures")
    args = parser.parse_args(argv)
    if args.essai:
        files = Watcher().files()
        newest = max(files, key=lambda p: p.stat().st_mtime) if files else None
        info = {"text": "essai", "reset": "dans quelques heures (essai)", "session": "", "cwd": "", "timestamp": ""}
        print(json.dumps(hand_over(info, newest, args.modele, essai=True), ensure_ascii=False, indent=1))
        return 0
    watcher = Watcher()
    print(f"Veilleur de quota actif sur {len(watcher.files())} transcriptions ({PROJECTS_DIR}).", flush=True)
    try:
        while True:
            hit = watcher.poll()
            if hit:
                info, path = hit
                print(f"Limite détectée : {info['text']} → passation", flush=True)
                print(json.dumps(hand_over(info, path, args.modele), ensure_ascii=False, indent=1), flush=True)
                return 0
            time.sleep(args.intervalle)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
