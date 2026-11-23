"""Lancement de Claude Code local : fichier de lancement (.bat), Windows Terminal ou terminal du Hub.

Le fichier de lancement ne contient aucun secret : le jeton « ollama » est une valeur factice attendue par Ollama
et OmniRoute, et `ANTHROPIC_API_KEY` est vidée (une vraie clé ne doit jamais partir vers un serveur local).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from modules.dev_launcher.catalog import MODEL_ID

BRIDGE = Path(__file__).with_name("bridge_mcp.py")
INHERITED_SESSION_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID",
                          "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                          "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "CLAUDE_EFFORT")

# Outils essentiels (option du lanceur) : avec les ~20 outils de Claude Code, les modèles locaux écrivent souvent
# leurs appels en texte au lieu de les émettre. Les outils MCP (Hermes, Hub) restent disponibles. Avec cette
# option, seuls les serveurs MCP passés au lancement sont chargés (`--strict-mcp-config`) : les serveurs globaux de
# l'utilisateur (ex. un serveur de ~300 outils) remplissaient le contexte et le modèle appelait le mauvais outil.
ESSENTIAL_TOOLS = "Read,Write,Edit,Glob,Grep,Bash"


class LaunchError(ValueError):
    """Modèle, dossier ou mode de lancement refusé."""


def claude_command(claude_dir: Path | None) -> list[str]:
    """Claude Code installé dans le dossier du Claude Code local, sinon celui du PATH, sinon npx."""
    if claude_dir:
        local = Path(claude_dir) / "node_modules" / ".bin" / "claude.cmd"
        if local.is_file():
            return [str(local)]
    found = shutil.which("claude")
    if found:
        return [found]
    return ["npx", "--yes", "@anthropic-ai/claude-code"]


def windows_terminal() -> str:
    found = shutil.which("wt")
    if found:
        return found
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "wt.exe"
    return str(candidate) if os.environ.get("LOCALAPPDATA") and candidate.exists() else ""


def route_env(route: str, model: str, context: int, ollama_url: str, omniroute_url: str) -> dict[str, str]:
    """Variables d'environnement de Claude Code pour la route choisie."""
    if not MODEL_ID.match(model or ""):
        raise LaunchError("identifiant de modèle invalide")
    if route == "ollama":
        base, name = ollama_url.rstrip("/"), model
    elif route == "omniroute":
        base = omniroute_url.rstrip("/")
        base = base if base.endswith("/v1") else base + "/v1"
        name = model
    else:
        raise LaunchError("route inconnue (ollama ou omniroute)")
    window = max(4096, min(int(context or 0) or 32768, 2_000_000))
    return {
        "ANTHROPIC_BASE_URL": base,
        "ANTHROPIC_AUTH_TOKEN": "ollama",  # valeur factice attendue par le serveur local
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": name,
        # Tâches de fond de Claude Code (titres, résumés) : même modèle, sinon il demande un « haiku » inexistant.
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": name, "ANTHROPIC_DEFAULT_SONNET_MODEL": name,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": name,
        # Contexte réel du modèle : sinon Claude Code suppose 200 k et ne résume pas la conversation à temps.
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(window),
        "ANTHROPIC_CONTEXT_LENGTH": str(window),  # lu par OmniRoute
        # Réserve de réponse : par défaut 32 k pour un modèle inconnu, retirés du contexte ; avec 64 k et ~25 k de
        # prompt, Claude Code se croyait plein dès le premier message (« 0 % until auto-compact »).
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(min(8192, window // 8)),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }


def mcp_config(path: Path, role: str = "claude") -> Path:
    """Configuration MCP passée à Claude Code (`--mcp-config`) : le pont vers Hermes et le Hub."""
    python = sys.executable
    if python.lower().endswith("pythonw.exe"):
        python = python[:-5] + ".exe"
    data = {"mcpServers": {"aethertwin": {"command": python, "args": ["-I", str(BRIDGE), role]}}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def _safe(text: str, what: str) -> str:
    if any(ch in text for ch in '"%^&|<>\r\n'):
        raise LaunchError(f"{what} : caractère interdit")
    return text


def batch_script(env: dict[str, str], folder: Path, command: list[str], title: str,
                 mcp: Path | None = None, tools: str = "") -> str:
    """Contenu du .bat : variables, dossier de travail, puis Claude Code."""
    lines = ["@echo off", "chcp 65001 >nul", f"title {_safe(title, 'titre')[:60]}"]
    # Variables d'une session Claude Code qui aurait lancé le Hub : la nouvelle session part d'un état propre.
    lines += [f'set "{name}="' for name in INHERITED_SESSION_VARS]
    lines += [f'set "{key}={_safe(value, key)}"' for key, value in env.items()]
    lines += [f'cd /d "{_safe(str(folder), "dossier")}"',
              "echo Claude Code local : " + _safe(env["ANTHROPIC_MODEL"], "modèle") + " via "
              + env["ANTHROPIC_BASE_URL"]]
    args = " ".join(f'"{_safe(part, "commande")}"' for part in command)
    extra = f' --mcp-config "{_safe(str(mcp), "mcp")}"' if mcp else ""
    extra += f' --tools "{_safe(tools, "outils")}" --strict-mcp-config' if tools else ""
    lines.append(f'call {args} --model "{env["ANTHROPIC_MODEL"]}"{extra}')
    return "\r\n".join(lines) + "\r\n"


def write_launch(launches: Path, script: str, keep: int = 30) -> Path:
    """Écrit le fichier de lancement (dossier du module, ignoré par Git) ; garde les 30 derniers."""
    launches.mkdir(parents=True, exist_ok=True)
    path = launches / f"claude_{time.strftime('%Y%m%d-%H%M%S')}_{time.time_ns() % 1000000:06d}.bat"
    path.write_text(script, encoding="utf-8")
    for old in sorted(launches.glob("claude_*.bat"))[:-keep]:
        old.unlink(missing_ok=True)
    return path


def open_in_windows_terminal(bat: Path, folder: Path, title: str, spawner: Any = subprocess.Popen) -> str:
    """Ouvre le lancement dans Windows Terminal (repli : une console classique)."""
    from core.terminals import child_env

    wt = windows_terminal()
    env = child_env()
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    if wt:
        spawner([wt, "-w", "new", "--title", title[:60], "-d", str(folder), "cmd", "/k", str(bat)],
                cwd=str(folder), env=env, creationflags=flags, close_fds=True)
        return "Windows Terminal"
    spawner(["cmd", "/c", "start", "", "cmd", "/k", str(bat)], cwd=str(folder), env=env, creationflags=flags,
            close_fds=True)
    return "console Windows"
