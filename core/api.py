"""API HTTP locale du démon (FastAPI). Servie sur 127.0.0.1 uniquement par `core.daemon`.

    GET  /health                   état du Hub, des gardiens et des modes dégradés
    GET  /modules                  registre des modules
    POST /modules/{name}/activate  demande l'activation (Inoue décide)
    POST /modules/{name}/deactivate
    GET  /events                   derniers événements du bus
    GET  /gpu                      mesure des GPU
    POST /ask                      question à l'assistant — indisponible tant que le routeur LLM n'existe pas
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.daemon import Daemon


class AskRequest(BaseModel):
    prompt: str


def create_app(daemon: Daemon) -> FastAPI:
    app = FastAPI(title="AetherTwin (I&F Core)", version="0.1.0", docs_url=None, redoc_url=None)

    def module_or_404(name: str) -> None:
        if name not in daemon.modules:
            raise HTTPException(status_code=404, detail=f"module inconnu : {name}")

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
        raise HTTPException(status_code=503, detail="routeur LLM non disponible (core/llm_router.py : jalon J5)")

    return app
