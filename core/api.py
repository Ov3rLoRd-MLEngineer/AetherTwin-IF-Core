"""API HTTP locale du démon (FastAPI). Servie sur 127.0.0.1 uniquement par `core.daemon`.

    GET  /                         tableau de bord (fichiers de `core/web/`)
    POST /modules/{name}/command/{cmd}  commande à un module, réponse attendue par `request_id`
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

import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from core import config
from core.daemon import REPO_ROOT, Daemon
from core.llm_router import LlmError, LlmRefused, openai_to_ollama

WEB_DIR = Path(__file__).resolve().parent / "web"
SCANTRAD_DIR = REPO_ROOT / "data" / "scantrad"
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_UPLOAD = 25 * 1024 * 1024


MANGASTUDIO_DIR = REPO_ROOT / "data" / "mangastudio"
FILE_NAME = re.compile(r"[\w-]+\.(png|jpg|jpeg|webp)")
MEDIA = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


async def save_upload(request: Request, folder: Path) -> Path:
    """Enregistre l'image envoyée (corps brut, PNG/JPEG/WebP, 25 Mo au plus) sous un nom horodaté."""
    suffix = IMAGE_TYPES.get(request.headers.get("content-type", "").split(";")[0].strip().lower())
    if suffix is None:
        raise HTTPException(status_code=415, detail="image PNG, JPEG ou WebP attendue")
    body = await request.body()
    if not body or len(body) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="image vide ou de plus de 25 Mo")
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() // 1000 % 1000000:06d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp}{suffix}"
    path.write_bytes(body)
    return path


def image_file(root: Path, kind: str, filename: str) -> Response:
    """Image servie seulement depuis `<root>/entrees` ou `<root>/sorties`, nom contrôlé."""
    if kind not in ("entrees", "sorties") or not FILE_NAME.fullmatch(filename):
        raise HTTPException(status_code=404, detail="introuvable")
    path = root / kind / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="introuvable")
    return Response(path.read_bytes(), media_type=MEDIA[path.suffix[1:]], headers={"Cache-Control": "no-store"})


def _glossary(series: str) -> Any:
    from modules.scantrad.cli import glossary_for

    try:
        return glossary_for(series, SCANTRAD_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
CSP = ("default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' blob:; connect-src 'self'; "
       "frame-src http://127.0.0.1:5757")  # aperçu de l'overlay OBS (gaming_hud), local lui aussi


def static(filename: str) -> Response:
    """Sert un fichier de `core/web/` (liste fermée d'extensions, aucun chemin hors du dossier)."""
    path = (WEB_DIR / filename).resolve()
    if path.parent != WEB_DIR or path.suffix not in STATIC_TYPES or not path.is_file():
        raise HTTPException(status_code=404, detail="introuvable")
    return Response(path.read_bytes(), media_type=STATIC_TYPES[path.suffix],
                    headers={"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                             "Cache-Control": "no-store"})


class AskRequest(BaseModel):
    prompt: str
    model: str | None = None
    with_context: bool = True


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]]
    stream: bool = False
    temperature: float | None = None
    # Extensions du Hub (ignorées par les clients OpenAI ordinaires) :
    num_ctx: int | None = None  # contexte plus court pour un petit modèle (vision : 4096)
    think: bool | None = None   # désactive le raisonnement des modèles qui en ont un


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

    @app.post("/modules/{name}/command/{command}")
    def module_command(name: str, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        module_or_404(name)
        try:
            return daemon.command(name, command, payload or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc

    @app.post("/modules/{name}/notify/{command}")
    def module_notify(name: str, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        module_or_404(name)
        try:
            daemon.notify(name, command, payload or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"sent": True}

    @app.get("/modules/{name}/state")
    def module_state(name: str) -> dict[str, Any]:
        module_or_404(name)
        return daemon.states.get(name) or {}

    @app.post("/modules/{name}/app/{action}")
    def module_app(name: str, action: str) -> dict[str, Any]:
        module_or_404(name)
        if action == "start":
            try:
                started = daemon.start_app(name)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"running": True, "started": started}
        if action == "stop":
            daemon.stop_app(name)
            return {"running": False}
        raise HTTPException(status_code=404, detail="action inconnue")

    @app.post("/scantrad/translate")
    async def scantrad_translate(request: Request, series: str = "", no_llm: bool = False) -> dict[str, Any]:
        source = await save_upload(request, SCANTRAD_DIR / "entrees")
        output = SCANTRAD_DIR / "sorties" / f"{source.stem}_fr.png"
        reply = await run_in_threadpool(module_call, "scantrad", "page", {
            "input": str(source), "output": str(output), "series": series, "no_llm": no_llm})
        if reply.get("ok"):
            reply["input_url"] = f"/scantrad/files/entrees/{source.name}"
            reply["output_url"] = f"/scantrad/files/sorties/{output.name}"
        return reply

    @app.get("/scantrad/files/{kind}/{filename}")
    def scantrad_file(kind: str, filename: str) -> Response:
        return image_file(SCANTRAD_DIR, kind, filename)

    @app.get("/mangastudio/files/{kind}/{filename}")
    def mangastudio_file(kind: str, filename: str) -> Response:
        return image_file(MANGASTUDIO_DIR, kind, filename)

    @app.post("/mangastudio/upload")
    async def mangastudio_upload(request: Request) -> dict[str, Any]:
        source = await save_upload(request, MANGASTUDIO_DIR / "entrees")
        return {"image": source.name, "url": f"/mangastudio/files/entrees/{source.name}"}

    @app.post("/mangastudio/segment")
    def mangastudio_segment(data: dict[str, Any]) -> dict[str, Any]:
        name = str(data.get("image", ""))
        if not re.fullmatch(r"[\w-]+\.(png|jpg|jpeg|webp)", name) or not (MANGASTUDIO_DIR / "entrees" / name).is_file():
            raise HTTPException(status_code=404, detail="image inconnue : envoie-la d'abord")
        reply = module_call("mangastudio", "segment", {
            "input": str(MANGASTUDIO_DIR / "entrees" / name), "target": str(data.get("target", "hand")),
            "boxes": data.get("boxes") or [], "output_dir": str(MANGASTUDIO_DIR / "sorties")})
        if reply.get("ok"):
            result = reply["result"]
            result["mask_url"] = f"/mangastudio/files/sorties/{Path(result.pop('mask')).name}"
            result["preview_url"] = f"/mangastudio/files/sorties/{Path(result.pop('preview')).name}"
        return reply

    @app.get("/mangastudio/status")
    def mangastudio_status() -> dict[str, Any]:
        from modules.mangastudio.module import status

        return status(config.section("mangastudio"))

    def module_call(name: str, command: str, payload: dict[str, Any], timeout_s: float = 600) -> dict[str, Any]:
        """Commande à un module, lancé à la demande s'il ne tourne pas."""
        module_or_404(name)
        if not daemon.modules[name].running():
            decision = daemon.activate(name)
            if decision.verdict.value != "accordé":
                raise HTTPException(status_code=409, detail=decision.reason)
        try:
            return daemon.command(name, command, payload, timeout_s=timeout_s)
        except (RuntimeError, TimeoutError) as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc

    @app.get("/scantrad/glossary/{series}")
    def glossary_get(series: str) -> dict[str, Any]:
        glossary = _glossary(series)
        return {"series": series, "characters": glossary.characters, "terms": glossary.terms, "tone": glossary.tone}

    @app.put("/scantrad/glossary/{series}")
    def glossary_put(series: str, data: dict[str, Any]) -> dict[str, Any]:
        glossary = _glossary(series)
        for key in ("characters", "terms"):
            value = data.get(key, {})
            if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                      for k, v in value.items()):
                raise HTTPException(status_code=400, detail=f"`{key}` : dictionnaire japonais → français attendu")
            setattr(glossary, key, {k.strip(): v.strip() for k, v in value.items() if k.strip() and v.strip()})
        if isinstance(data.get("tone"), str) and data["tone"].strip():
            glossary.tone = data["tone"].strip()[:300]
        glossary.save()
        return glossary_get(series)

    @app.post("/shutdown")
    def shutdown() -> dict[str, Any]:
        stop = getattr(app.state, "shutdown", None)
        if stop is None:
            raise HTTPException(status_code=503, detail="arrêt à distance indisponible")
        stop()
        return {"stopping": True}

    def knowledge_or_503() -> Any:
        if daemon.knowledge is None:
            raise HTTPException(status_code=503, detail="base de connaissances non configurée")
        return daemon.knowledge

    @app.get("/knowledge")
    def knowledge_state() -> dict[str, Any]:
        return knowledge_or_503().state()

    @app.get("/knowledge/search")
    def knowledge_search(q: str, k: int = 5, tag: str = "") -> dict[str, Any]:
        return knowledge_or_503().search(q, k=max(1, min(k, 20)), tag=tag)

    @app.post("/knowledge/ingest")
    def knowledge_ingest() -> dict[str, Any]:
        started = knowledge_or_503().start_ingestion()
        return {"started": started, "detail": "ingestion lancée en arrière-plan" if started else "déjà en cours"}

    @app.get("/", include_in_schema=False)
    def dashboard() -> Response:
        return static("dashboard.html")

    @app.get("/static/{filename}", include_in_schema=False)
    def static_file(filename: str) -> Response:
        return static(filename)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

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
        if request.num_ctx is not None and not 512 <= request.num_ctx <= 131072:
            raise HTTPException(status_code=400, detail="num_ctx hors bornes (512 à 131072)")
        options = {"temperature": request.temperature} if request.temperature is not None else None
        result = llm_call(lambda: daemon.llm.chat(openai_to_ollama(request.messages), model=request.model,
                                                  num_ctx=request.num_ctx, think=request.think, options=options))
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
