"""API HTTP locale du démon (FastAPI). Servie sur 127.0.0.1 uniquement par `core.daemon`.

    GET  /health                   état du Hub, des gardiens, du routeur LLM et des modes dégradés
    GET  /modules                  registre des modules
    POST /modules/{name}/activate  demande l'activation (Inoue décide)
    POST /modules/{name}/deactivate
    GET  /events                   derniers événements du bus
    GET  /gpu                      mesure des GPU
    POST /ask                      question à l'assistant local, avec le contexte des modules actifs

Compatibilité OpenAI, pour brancher un client existant sur le Hub sans le modifier (il suffit de lui
donner `http://127.0.0.1:<port>` comme serveur) :

    GET  /v1/models
    POST /v1/chat/completions      (réponse complète, sans diffusion mot à mot)

Toutes les générations passent par `core.llm_router` : règles VRAM appliquées, rien ne part vers le cloud.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.daemon import Daemon
from core.llm_router import LlmError, LlmRefused, openai_to_ollama


class AskRequest(BaseModel):
    prompt: str
    model: str | None = None
    with_context: bool = True


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]]
    stream: bool = False


def create_app(daemon: Daemon) -> FastAPI:
    app = FastAPI(title="AetherTwin (I&F Core)", version="0.1.0", docs_url=None, redoc_url=None)

    def module_or_404(name: str) -> None:
        if name not in daemon.modules:
            raise HTTPException(status_code=404, detail=f"module inconnu : {name}")

    def llm_call(fn: Any) -> dict[str, Any]:
        """Traduit les erreurs du routeur : 409 = refus d'Inoue (VRAM), 503 = Ollama indisponible."""
        try:
            return fn()
        except LlmRefused as exc:
            raise HTTPException(status_code=409, detail=f"VRAM : {exc}") from exc
        except LlmError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, Any]:
        return daemon.status()

    @app.get("/modules")
    def modules() -> list[dict[str, Any]]:
        return daemon.modules_status()

    @app.post("/modules/{name}/activate")
    def activate(name: str) -> dict[str, Any]:
        module_or_404(name)
        decision = daemon.activate(name)
        return {"name": name, "verdict": decision.verdict.value, "granted_gb": decision.granted_gb,
                "reason": decision.reason}

    @app.post("/modules/{name}/deactivate")
    def deactivate(name: str) -> dict[str, Any]:
        module_or_404(name)
        daemon.deactivate(name)
        return {"name": name, "active": False}

    @app.get("/events")
    def events(limit: int = 50) -> list[dict[str, Any]]:
        return [event.to_dict() for event in list(daemon.bus.history)[-max(1, min(limit, 200)):]]

    @app.get("/gpu")
    def gpu() -> dict[str, Any]:
        return daemon.monitor.report()

    @app.post("/ask")
    def ask(request: AskRequest) -> dict[str, Any]:
        result = llm_call(lambda: daemon.ask(request.prompt, request.model, request.with_context))
        return {"answer": result["content"], **{k: v for k, v in result.items() if k != "content"}}

    @app.get("/v1/models")
    def v1_models() -> dict[str, Any]:
        models = llm_call(lambda: {"models": daemon.llm.list_models()})["models"]
        return {"object": "list", "data": [{"id": m["name"], "object": "model", "owned_by": "ollama"} for m in models]}

    @app.post("/v1/chat/completions")
    def v1_chat(request: ChatRequest) -> dict[str, Any]:
        if request.stream:
            raise HTTPException(status_code=400, detail="la diffusion mot à mot (stream) n'est pas prise en charge")
        result = llm_call(lambda: daemon.llm.chat(openai_to_ollama(request.messages), model=request.model))
        return {
            "id": f"chatcmpl-aethertwin-{int(time.time() * 1000)}", "object": "chat.completion",
            "created": int(time.time()), "model": result["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": result["content"]}}],
            "usage": {"prompt_tokens": result.get("prompt_tokens") or 0,
                      "completion_tokens": result.get("completion_tokens") or 0,
                      "total_tokens": (result.get("prompt_tokens") or 0) + (result.get("completion_tokens") or 0)},
        }

    return app
