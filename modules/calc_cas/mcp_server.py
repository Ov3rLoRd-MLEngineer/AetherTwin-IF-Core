"""Serveur MCP (stdio, JSON-RPC ligne par ligne) : les outils du CAS pour Hermes Agent ou tout client MCP local.

    .venv\\Scripts\\python.exe -m modules.calc_cas.mcp_server
    .venv\\Scripts\\python.exe -I modules\\calc_cas\\mcp_server.py      (forme déclarée chez Hermes)

Aucune écoute réseau. Chaque calcul tourne dans le processus de calcul, avec le même délai que le module.
`python_run` tourne dans un second processus à mémoire bornée (bac à sable) ; ses graphiques PNG vont dans
`data/calc_cas/agent_graphiques`.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, TextIO

if __package__ in (None, ""):  # lancé comme script : la racine du dépôt remplace le dossier du script
    sys.path[0] = str(Path(__file__).resolve().parents[2])

from modules.calc_cas.agent import TOOL_SPECS, call_tool  # noqa: E402
from modules.calc_cas.worker import CasRunner  # noqa: E402

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "aethertwin-calc-cas", "version": "0.1.0"}


def tool_list() -> list[dict[str, Any]]:
    return [{"name": s["function"]["name"], "description": s["function"]["description"],
             "inputSchema": s["function"]["parameters"]} for s in TOOL_SPECS]


REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "data" / "calc_cas" / "agent_graphiques"


def handle(runner: Any, message: Any, sandbox: Any = None) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Requête invalide"}}
    method, mid, params = message.get("method"), message.get("id"), message.get("params") or {}
    if mid is None:
        return None

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        wanted = params.get("protocolVersion")
        return ok({"protocolVersion": wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                   "instructions": "Calcul formel exact et local (SymPy). Utilise ces outils plutôt que de calculer "
                                   "de tête. python_run exécute un script Python dans un bac à sable et rend sa "
                                   "sortie réelle : vérifie ton code avec lui au lieu de supposer le résultat."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_list()})
    if method == "tools/call":
        result = call_tool(runner, str(params.get("name")), params.get("arguments") or {}, sandbox=sandbox,
                           out_dir=OUT_DIR)
        return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                   "structuredContent": result, "isError": not result.get("ok", False)})
    if method in ("resources/list", "prompts/list"):
        return ok({method.split("/")[0]: []})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Méthode inconnue : {method}"}}


def serve(stdin: TextIO, stdout: TextIO, runner: Any, sandbox: Any = None) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: Any = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON illisible"}}
        else:
            if isinstance(message, list):
                reply = [r for r in (handle(runner, m, sandbox) for m in message) if r is not None] or None
            else:
                reply = handle(runner, message, sandbox)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


def main() -> None:
    protocol_out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n", line_buffering=True)
    sys.stdout = sys.stderr  # le protocole passe par la sortie standard : tout autre affichage va sur stderr
    runner = CasRunner(timeout_s=10)
    sandbox = CasRunner(timeout_s=10, memory_mb=768)
    try:
        serve(io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8"), protocol_out, runner, sandbox)
    finally:
        runner.stop()
        sandbox.stop()


if __name__ == "__main__":
    main()
