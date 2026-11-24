"""Serveur MCP minimal (stdio, JSON-RPC ligne par ligne) pour les outils des modules du Hub.

Un module fournit ses `TOOL_SPECS` (schémas « function calling ») et `call_tool(nom, arguments) -> dict` qui ne
lève jamais (erreur → {"ok": False, "error": …}). Aucune écoute réseau : le client (Hermes Agent, Claude Code…)
lance le processus et lui parle par l'entrée et la sortie standard.
"""
from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from typing import Any, TextIO

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


class ToolServer:
    def __init__(self, info: dict[str, str], instructions: str, specs: list[dict[str, Any]],
                 call: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self.info, self.instructions, self.specs, self.call = info, instructions, specs, call

    def tool_list(self) -> list[dict[str, Any]]:
        return [{"name": s["function"]["name"], "description": s["function"]["description"],
                 "inputSchema": s["function"]["parameters"]} for s in self.specs]

    def handle(self, message: Any) -> dict[str, Any] | None:
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
                       "capabilities": {"tools": {"listChanged": False}}, "serverInfo": self.info,
                       "instructions": self.instructions})
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": self.tool_list()})
        if method == "tools/call":
            result = self.call(str(params.get("name")), params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                       "structuredContent": result, "isError": not result.get("ok", False)})
        if method in ("resources/list", "prompts/list"):
            return ok({method.split("/")[0]: []})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Méthode inconnue : {method}"}}

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
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
                    reply = [r for r in (self.handle(m) for m in message) if r is not None] or None
                else:
                    reply = self.handle(message)
            if reply is not None:
                stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                stdout.flush()

    def main(self) -> None:
        protocol_out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n", line_buffering=True)
        sys.stdout = sys.stderr  # le protocole passe par la sortie standard : tout autre affichage va sur stderr
        self.serve(io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8"), protocol_out)
