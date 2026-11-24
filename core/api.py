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
    POST /v1/audio/speech          texte → WAV (module `voice` : « voice » = profil de voix d'AetherTwin)
    POST /v1/audio/transcriptions  audio (multipart « file », ou corps brut) → {"text"} (Whisper local)

Guides (README du dépôt, lus par `core/web/guide.html`) : GET /guides, GET /guides/{id}.

Toutes les générations passent par `core.llm_router` : règles VRAM appliquées, rien ne part vers le cloud.
"""
from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
import uuid
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core import config
from core.daemon import REPO_ROOT, Daemon
from core.guardians.inoue import Verdict
from core.hardware import system_info as sysinfo
from core.llm_router import LlmError, LlmRefused, openai_to_ollama
from core.strata import StrataError, is_strata
from core.terminals import TerminalError, TerminalManager

WEB_DIR = Path(__file__).resolve().parent / "web"
SCANTRAD_DIR = REPO_ROOT / "data" / "scantrad"
LAUNCHES_DIR = REPO_ROOT / "data" / "dev_launcher" / "lancements"  # écrits par le module dev_launcher
SYSTEM_DIR = REPO_ROOT / "data" / "system"  # lectures des courbes de ventilateurs du BIOS
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_UPLOAD = 25 * 1024 * 1024
MAX_VOICE_AUDIO = 5_500_000
VOICE_TMP_NAME = re.compile(r"[0-9a-f]{32}\.wav")
AUDIO_TYPES = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/webm": "webm",
               "video/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a",
               "audio/x-m4a": "m4a", "audio/flac": "flac"}


GUIDE_FIXED = {"aethertwin": "README.md", "wow_assistant": "modules/gaming_hud/app/README.md"}


def guide_catalog() -> dict[str, tuple[str, Path]]:
    """Guides lisibles depuis l'interface : le README du dépôt, celui de WoW Assistant et ceux des modules.

    Liste fermée calculée côté serveur (identifiant → fichier) : la page ne donne jamais de chemin.
    """
    found: dict[str, Path] = {gid: REPO_ROOT / rel for gid, rel in GUIDE_FIXED.items()}
    for readme in sorted((REPO_ROOT / "modules").glob("*/README.md")):
        if re.fullmatch(r"[a-z][a-z0-9_]*", readme.parent.name):
            found[readme.parent.name] = readme
    catalog: dict[str, tuple[str, Path]] = {}
    for gid, path in found.items():
        if not path.is_file():
            continue
        first = path.read_text(encoding="utf-8", errors="replace").lstrip().splitlines()[:1]
        title = first[0].lstrip("# ").strip() if first and first[0].startswith("#") else gid
        catalog[gid] = (title[:80], path)
    return catalog


def audio_suffix(content_type: str, filename: str = "") -> str:
    kind = AUDIO_TYPES.get(content_type.split(";")[0].strip().lower())
    if kind:
        return kind
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext if ext in AUDIO_TYPES.values() else "bin"


def multipart_fields(content_type: str, body: bytes) -> dict[str, tuple[bytes, str, str]]:
    """Champs d'un formulaire multipart : nom → (contenu, type, nom de fichier). Sans python-multipart."""
    message = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    fields: dict[str, tuple[bytes, str, str]] = {}
    if not message.is_multipart():
        return fields
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            fields[str(name)] = (part.get_payload(decode=True) or b"", part.get_content_type(),
                                 str(part.get_filename() or ""))
    return fields


# Noms sous lesquels on joint le Hub. « testserver » est le nom utilisé par le client de test de FastAPI.
TRUSTED_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
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
       "frame-src 'self' http://127.0.0.1:5757")  # simulations du Professeur ; aperçu de l'overlay OBS (local)
# Page du terminal (cadre du tableau de bord) : xterm.js ajoute ses propres règles de style ; WebSocket locale.
TERM_CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self' ws://127.0.0.1:5750 ws://localhost:5750; frame-ancestors 'self'")
# Simulations du Professeur : pages autonomes, servies dans un cadre isolé (origine opaque, aucun accès réseau).
SIM_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; "
           "sandbox allow-scripts")


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
    history: list[dict[str, Any]] = []  # échanges précédents de la conversation (le démon les borne)
    use_knowledge: bool = False  # joindre les passages pertinents de la base de connaissances (à citer)


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

    @app.middleware("http")
    async def local_only(request: Request, call_next: Any) -> Response:
        """Le Hub écoute sur 127.0.0.1, mais un site ouvert dans le navigateur pourrait quand même lui envoyer
        un formulaire (CSRF) ou passer par un nom de domaine qui pointe sur 127.0.0.1 (« DNS rebinding »).
        Refusés : un hôte qui n'est pas local ; une écriture venue d'une autre origine."""
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in TRUSTED_HOSTS:
            return Response("hôte refusé", status_code=403, media_type="text/plain; charset=utf-8")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                    origin is not None and urlsplit(origin).hostname not in TRUSTED_HOSTS):
                return Response("origine refusée", status_code=403, media_type="text/plain; charset=utf-8")
        return await call_next(request)

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
            return {"running": False, "closed": daemon.stop_app(name)}
        raise HTTPException(status_code=404, detail="action inconnue")

    @app.post("/scantrad/translate")
    async def scantrad_translate(request: Request, series: str = "", no_llm: bool = False, lang: str = "ja",
                                 layout: str = "auto") -> dict[str, Any]:
        source = await save_upload(request, SCANTRAD_DIR / "entrees")
        output = SCANTRAD_DIR / "sorties" / f"{source.stem}_fr.png"
        reply = await run_in_threadpool(module_call, "scantrad", "page", {
            "input": str(source), "output": str(output), "series": series, "no_llm": no_llm, "lang": lang,
            "layout": layout})
        if reply.get("ok"):
            reply["input_url"] = f"/scantrad/files/entrees/{source.name}"
            reply["output_url"] = f"/scantrad/files/sorties/{output.name}"
        return reply

    @app.post("/scantrad/retypeset")
    def scantrad_retypeset(data: dict[str, Any]) -> dict[str, Any]:
        """Traductions corrigées à la main, réincrustées sur la page nettoyée (sans OCR ni modèle)."""
        name = str(data.get("output", ""))
        if not re.fullmatch(r"[\w-]+_fr\.png", name) or not (SCANTRAD_DIR / "sorties" / name).is_file():
            raise HTTPException(status_code=404, detail="page traduite inconnue")
        reply = module_call("scantrad", "retypeset", {"output": str(SCANTRAD_DIR / "sorties" / name),
                                                      "translations": data.get("translations") or {}})
        if reply.get("ok"):
            reply["output_url"] = f"/scantrad/files/sorties/{name}"
        return reply

    # ---------- Scantrad, mode manuel : zones posées à la main, gomme, réincrustation ----------
    def manual_paths(name: str) -> tuple[Path, Path, Path]:
        """(page d'origine, page gommée, page traduite) d'une page envoyée en mode manuel."""
        if not FILE_NAME.fullmatch(name) or not (SCANTRAD_DIR / "entrees" / name).is_file():
            raise HTTPException(status_code=404, detail="page inconnue : envoie-la d'abord")
        source, out = SCANTRAD_DIR / "entrees" / name, SCANTRAD_DIR / "sorties"
        return source, out / f"{source.stem}_propre.png", out / f"{source.stem}_fr.png"

    @app.post("/scantrad/upload")
    async def scantrad_upload(request: Request) -> dict[str, Any]:
        source = await save_upload(request, SCANTRAD_DIR / "entrees")
        return {"image": source.name, "url": f"/scantrad/files/entrees/{source.name}"}

    @app.post("/scantrad/manual/cleaned")
    async def scantrad_cleaned(request: Request, image: str) -> dict[str, Any]:
        """Page gommée dans le navigateur (PNG) : base de la réincrustation."""
        _source, cleaned, _output = manual_paths(image)
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "image/png":
            raise HTTPException(status_code=415, detail="PNG attendu")
        body = await request.body()
        if not body.startswith(b"\x89PNG\r\n\x1a\n") or len(body) > MAX_UPLOAD:
            raise HTTPException(status_code=400, detail="PNG invalide ou de plus de 25 Mo")
        cleaned.parent.mkdir(parents=True, exist_ok=True)
        cleaned.write_bytes(body)
        return {"cleaned_url": f"/scantrad/files/sorties/{cleaned.name}"}

    @app.post("/scantrad/manual/rebuild")
    async def scantrad_rebuild(request: Request, image: str) -> dict[str, Any]:
        """Outil « Reconstruire » : masque PNG (blanc = à redessiner) appliqué à la page gommée (LaMa)."""
        _source, cleaned, _output = manual_paths(image)
        body = await request.body()
        if not body.startswith(b"\x89PNG\r\n\x1a\n") or len(body) > MAX_UPLOAD:
            raise HTTPException(status_code=400, detail="masque PNG invalide ou de plus de 25 Mo")
        mask = cleaned.with_name(cleaned.name.replace("_propre.png", "_masque.png"))
        mask.parent.mkdir(parents=True, exist_ok=True)
        mask.write_bytes(body)
        reply = await run_in_threadpool(module_call, "scantrad", "rebuild", {
            "input": str(_source), "output": str(cleaned), "mask": str(mask)})
        if reply.get("ok"):
            reply["cleaned_url"] = f"/scantrad/files/sorties/{cleaned.name}"
        return reply

    @app.post("/scantrad/manual/{command}")
    async def scantrad_manual(command: str, data: dict[str, Any]) -> dict[str, Any]:
        if command not in ("suggest", "read", "translate", "erase", "compose"):
            raise HTTPException(status_code=404, detail="commande inconnue")
        common = {"lang": str(data.get("lang") or "ja"), "layout": str(data.get("layout") or "auto"),
                  "series": str(data.get("series", ""))}
        if command == "translate":
            payload: dict[str, Any] = {"texts": data.get("texts"), **common}
        else:
            source, cleaned, output = manual_paths(str(data.get("image", "")))
            payload = {"input": str(source), "boxes": data.get("boxes"), "bubbles": data.get("bubbles"),
                       "auto_erase": data.get("auto_erase") is not False, **common,
                       "output": str(cleaned if command == "erase" else output)}
        reply = await run_in_threadpool(module_call, "scantrad", command, payload)
        if reply.get("ok") and command == "erase":
            reply["cleaned_url"] = f"/scantrad/files/sorties/{cleaned.name}"
        if reply.get("ok") and command == "compose":
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

    # ---------- Traduction générale vers le français (texte, image, voix) ----------
    def translate_or_400(fn: Any) -> dict[str, Any]:
        try:
            return llm_call(fn)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/translate/text")
    def translate_text(data: dict[str, Any]) -> dict[str, Any]:
        from core import translate

        return translate_or_400(lambda: translate.translate_text(daemon.llm.chat, str(data.get("text", "")),
                                                                 str(data.get("lang") or "auto")))

    @app.post("/translate/image")
    async def translate_image(request: Request, lang: str = "auto") -> dict[str, Any]:
        from core import translate

        if IMAGE_TYPES.get(request.headers.get("content-type", "").split(";")[0].strip().lower()) is None:
            raise HTTPException(status_code=415, detail="image PNG, JPEG ou WebP attendue")
        body = await request.body()
        if not body or len(body) > MAX_UPLOAD:
            raise HTTPException(status_code=413, detail="image vide ou de plus de 25 Mo")
        model = str(config.section("scantrad").get("ocr_model") or "qwen2.5vl:7b")

        def run() -> dict[str, Any]:
            text = translate.read_image(daemon.llm.chat, body, lang, model)
            return translate.translate_text(daemon.llm.chat, text, lang)
        return await run_in_threadpool(translate_or_400, run)

    @app.get("/translate/voice")
    def translate_voice_status() -> dict[str, Any]:
        from core import translate

        return {"available": translate.voice_available()}

    @app.post("/translate/voice")
    async def translate_voice(request: Request, lang: str = "auto") -> dict[str, Any]:
        from core import translate

        body = await request.body()
        if not body or len(body) > MAX_UPLOAD:
            raise HTTPException(status_code=413, detail="enregistrement vide ou de plus de 25 Mo")

        def run() -> dict[str, Any]:
            try:
                heard = translate.transcribe(body, lang)
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return translate.translate_text(daemon.llm.chat, heard["text"], heard["lang"])
        return await run_in_threadpool(translate_or_400, run)

    @app.post("/mangastudio/detect")
    def mangastudio_detect(data: dict[str, Any]) -> dict[str, Any]:
        """Boîtes proposées par le modèle de vision local (point de départ, à corriger à la main)."""
        from modules.mangastudio import grounding
        from modules.mangastudio.module import read_rgb

        name = str(data.get("image", ""))
        if not FILE_NAME.fullmatch(name) or not (MANGASTUDIO_DIR / "entrees" / name).is_file():
            raise HTTPException(status_code=404, detail="image inconnue : envoie-la d'abord")
        target = str(data.get("target", "hand"))
        if target not in grounding.LABELS:
            raise HTTPException(status_code=400, detail="cible : hand ou foot")
        image = read_rgb(MANGASTUDIO_DIR / "entrees" / name)
        model = str(config.section("mangastudio").get("vision_model") or "qwen2.5vl:7b")
        started = time.perf_counter()
        boxes = llm_call(lambda: {"boxes": grounding.detect(image, target, daemon.llm.chat, model)})["boxes"]
        return {"boxes": boxes, "model": model, "seconds": round(time.perf_counter() - started, 2)}

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

    # -- terminaux (onglet Développement)
    terminals = TerminalManager(LAUNCHES_DIR)
    app.state.terminals = terminals

    def terminal_call(fn: Any) -> Any:
        try:
            return fn()
        except TerminalError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # -- état du PC (Accueil, Inoue) : lecture sans droits administrateur ; actions sur clic, listes fermées
    sampler, sysdata = sysinfo.SystemSampler(), sysinfo.SystemInfo()
    fans_file = SYSTEM_DIR / "ventilateurs_bios.json"

    def system_action(work: Any) -> Any:
        try:
            return work()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/system/live")
    def system_live() -> dict[str, Any]:
        return sampler.read()

    @app.get("/system/info")
    def system_info(refresh: bool = False) -> dict[str, Any]:
        return sysdata.info(refresh)

    @app.get("/system/devices")
    def system_devices(refresh: bool = False) -> dict[str, Any]:
        return sysdata.devices(refresh)

    @app.get("/system/processes")
    def system_processes() -> dict[str, Any]:
        return {"processus": sysinfo.heavy_processes(), "alimentation": sysinfo.power_plans()}

    @app.post("/system/process/stop")
    def system_stop(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        return system_action(lambda: sysinfo.stop_process(int(body.get("pid") or 0), str(body.get("nom", ""))))

    @app.post("/system/power")
    def system_power(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        guid = str((payload or {}).get("guid", ""))
        return {"alimentation": system_action(lambda: sysinfo.set_power_plan(guid))}

    @app.post("/system/open")
    def system_open(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        return {"ouvert": system_action(lambda: sysinfo.open_windows(str(body.get("cible", "")),
                                                                    str(body.get("lecteur", ""))))}

    @app.get("/system/tools")
    def system_tools() -> list[dict[str, Any]]:
        return sysinfo.tools_state()

    @app.post("/system/tools/launch")
    def system_tool_launch(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ouvert": system_action(lambda: sysinfo.launch_tool(str((payload or {}).get("outil", ""))))}

    @app.get("/system/sensors")
    def system_sensors() -> dict[str, Any]:
        return {"lhm": sysinfo.lhm_sensors(), "gpus": sysinfo.nvml_details(),
                "ventilateurs_bios": sysinfo.bios_fans(fans_file)}

    @app.post("/system/fans/read")
    def system_fans_read() -> dict[str, Any]:
        return sysinfo.read_bios_fans(fans_file)

    @app.get("/terminal", include_in_schema=False)
    def terminal_page() -> Response:
        page = static("terminal.html")
        page.headers["Content-Security-Policy"] = TERM_CSP
        return page

    @app.get("/terminals")
    def terminals_list() -> list[dict[str, Any]]:
        return terminals.list()

    @app.post("/terminals")
    def terminals_open(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        return terminal_call(lambda: terminals.open(launch=str(body.get("lancement", "")),
                                                    cwd=str(body.get("dossier", "")),
                                                    title=str(body.get("titre", "")),
                                                    rows=int(body.get("lignes") or 30),
                                                    cols=int(body.get("colonnes") or 110)))

    @app.post("/terminals/{sid}/close")
    def terminals_close(sid: str) -> dict[str, Any]:
        return terminal_call(lambda: terminals.close(sid))

    @app.websocket("/terminals/{sid}/ws")
    async def terminal_ws(websocket: WebSocket, sid: str) -> None:
        # Le contrôle HTTP (local_only) ne s'applique pas aux WebSockets : hôte et origine vérifiés ici.
        host = (websocket.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        origin = websocket.headers.get("origin")
        if host not in TRUSTED_HOSTS or (origin is not None and urlsplit(origin).hostname not in TRUSTED_HOSTS):
            await websocket.close(code=4403)
            return
        try:
            session = terminals.get(sid)
        except TerminalError:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        import asyncio

        loop = asyncio.get_running_loop()
        outbox: asyncio.Queue[str] = asyncio.Queue()

        def listener(text: str) -> None:
            loop.call_soon_threadsafe(outbox.put_nowait, text)

        replay = session.subscribe(listener)
        if replay:
            await websocket.send_text(json.dumps({"t": "o", "d": replay}))

        async def pump_out() -> None:
            while True:
                text = await outbox.get()
                while not outbox.empty() and len(text) < 65536:
                    text += outbox.get_nowait()
                await websocket.send_text(json.dumps({"t": "o", "d": text}))

        sender = asyncio.create_task(pump_out())
        try:
            while True:
                message = json.loads(await websocket.receive_text())
                if message.get("t") == "i":
                    await run_in_threadpool(terminals.write, sid, str(message.get("d", "")))
                elif message.get("t") == "r":
                    await run_in_threadpool(terminals.resize, sid, int(message.get("rows") or 30),
                                            int(message.get("cols") or 110))
        except (WebSocketDisconnect, ValueError, TerminalError):
            pass
        finally:
            sender.cancel()
            session.unsubscribe(listener)

    @app.get("/prof/sims/{sim_id}", include_in_schema=False)
    def professor_sim(sim_id: str) -> Response:
        from modules.genesis_lab.sims import SimError, SimLibrary, with_hub_tools

        profile = Path(str(config.section("genesis_lab").get("profile") or "data/genesis_lab/eleve.json"))
        try:
            path = SimLibrary(profile.parent).path(sim_id)
        except SimError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(with_hub_tools(path.read_bytes()), media_type="text/html; charset=utf-8",
                        headers={"Content-Security-Policy": SIM_CSP, "X-Content-Type-Options": "nosniff",
                                 "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

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

    @app.post("/ask/stream")
    def ask_stream(request: AskRequest) -> StreamingResponse:
        """La réponse arrive au fil de la génération : une ligne JSON par morceau (`{"text": …}`), puis
        `{"done": {"model", "seconds"}}` ou `{"error": …}`. La génération tourne dans un fil dédié (le verrou du
        routeur est pris et rendu par ce même fil)."""
        passages = relevant_passages(request.prompt) if request.use_knowledge else []
        messages, _context = daemon.ask_messages(request.prompt, request.with_context, request.history, passages)

        def lines() -> Any:
            if request.use_knowledge:  # les sources d'abord : l'interface les affiche sous la réponse
                sources = [{"n": i, "title": p["title"], "url": p["url"], "license": p["license"]}
                           for i, p in enumerate(passages, start=1)]
                yield json.dumps({"sources": sources}, ensure_ascii=False) + "\n"
            for kind, value in stream_pieces(messages, request.model):
                yield json.dumps({kind: value}, ensure_ascii=False) + "\n"

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    def relevant_passages(question: str, k: int = 3) -> list[dict[str, Any]]:
        """Passages assez proches de la question, un par page au plus. Base absente ou en erreur : aucun passage
        (l'assistant répond sans).

        Seuils mesurés le 17/11/2026 sur la base réelle (`nomic-embed-text`, 18 pages Wikipédia) : questions
        couvertes 0,70 à 0,81 ; hors sujet (cuisine, football, WoW) 0,55 à 0,61. D'où 0,65 en vecteurs, et pas
        plus de 0,08 sous le meilleur passage. Les préfixes « search_query/search_document » ont été essayés :
        ils ne séparaient pas mieux (hors sujet jusqu'à 0,64)."""
        if daemon.knowledge is None:
            return []
        try:
            hits = daemon.knowledge.search(question, k=k * 2)["hits"]
        except Exception:  # noqa: BLE001 — une recherche ratée ne doit pas empêcher de répondre
            return []
        if not hits:
            return []
        best = max(h["score"] for h in hits)
        kept: list[dict[str, Any]] = []
        for hit in hits:
            threshold = 0.65 if hit["mode"] == "vecteurs" else 0.6
            if hit["score"] >= max(threshold, best - 0.08) and all(k_["url"] != hit["url"] for k_ in kept):
                kept.append(hit)
        return kept[:k]

    def stream_pieces(messages: list[dict[str, Any]], model: str | None, **options: Any) -> Any:
        """(« text », morceau)…, puis (« done », {model, seconds}) ou (« error », message). La génération tourne
        dans un fil dédié : le verrou du routeur est pris et rendu par ce même fil, quel que soit le client."""
        pieces: queue.Queue[tuple[str, Any]] = queue.Queue()

        def worker() -> None:
            started = time.perf_counter()
            try:
                for piece in daemon.llm.chat_stream(messages, model=model, **options):
                    pieces.put(("text", piece))
                pieces.put(("done", {"model": model or daemon.llm.config.default_model,
                                     "seconds": round(time.perf_counter() - started, 2)}))
            except LlmRefused as exc:
                pieces.put(("error", f"VRAM : {exc}"))
            except LlmError as exc:
                pieces.put(("error", str(exc)))

        threading.Thread(target=worker, name="llm-stream", daemon=True).start()
        while True:
            try:
                kind, value = pieces.get(timeout=daemon.llm.config.timeout_s)
            except queue.Empty:
                yield "error", "délai dépassé"
                return
            yield kind, value
            if kind != "text":
                return

    def strata_backend() -> Any:
        strata = daemon.llm.strata
        if strata is None or not strata.config.enabled:
            raise HTTPException(status_code=404, detail="Strata n'est pas activé (section strata de config/local.yaml)")
        return strata

    @app.post("/strata/start")
    def strata_start() -> dict[str, Any]:
        """Démarre le préréglage Strata (clic sur l'Accueil). Les gros modèles d'Ollama sont déchargés avant."""
        strata = strata_backend()
        try:
            for item in daemon.llm.loaded():
                if item["vram_gb"] >= daemon.llm.config.big_model_gb:
                    daemon.llm.unload(item["name"])
        except LlmError:
            pass
        try:
            return strata.start()
        except StrataError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/strata/stop")
    def strata_stop() -> dict[str, Any]:
        """Arrête Strata : toute sa VRAM est rendue, Inoue libère sa place."""
        strata = strata_backend()
        try:
            result = strata.stop()
        except (StrataError, OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(status_code=503, detail=f"arrêt de Strata impossible : {exc}") from exc
        for name in [m for m in daemon.inoue.state()["loaded_llms"] if is_strata(m)]:
            daemon.inoue.confirm_llm_unloaded(name)
        return result

    @app.post("/llm/unload")
    def llm_unload(data: dict[str, Any]) -> dict[str, Any]:
        """Décharge un modèle de la VRAM (ex. avant de lancer un jeu). Seuls les modèles chargés sont acceptés."""
        model = str(data.get("model", ""))
        loaded = [m["name"] for m in llm_call(lambda: {"m": daemon.llm.loaded()})["m"]]
        if model not in loaded:
            raise HTTPException(status_code=404, detail=f"modèle non chargé : {model}")
        llm_call(lambda: daemon.llm.unload(model) or {})
        return {"unloaded": model}

    # -- voix (module `voice`, lancé à la demande)
    def voice_dir() -> Path:
        return REPO_ROOT / str(config.section("voice").get("data_dir") or "data/voice")

    def voice_command(command: str, payload: dict[str, Any], timeout_s: float = 240.0) -> dict[str, Any]:
        if "voice" not in daemon.modules:
            raise HTTPException(status_code=404, detail="module voice absent")
        if not daemon.modules["voice"].running():
            decision = daemon.activate("voice")
            if decision.verdict is not Verdict.GRANTED:
                raise HTTPException(status_code=503, detail=f"voix indisponible : {decision.reason}")
        try:
            reply = daemon.command("voice", command, payload, timeout_s)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        if not reply.get("ok"):
            raise HTTPException(status_code=400, detail=str(reply.get("error") or "erreur de la voix"))
        return reply.get("result") or {}

    @app.get("/voice/settings")
    def voice_settings() -> dict[str, Any]:
        """Profils de voix et réglages (lus directement : la page n'a pas besoin du module pour les afficher)."""
        from modules.voice.profiles import ProfileStore

        return ProfileStore(voice_dir() / "profiles.json").all()

    @app.post("/voice/settings")
    def voice_settings_save(data: dict[str, Any]) -> dict[str, Any]:
        from modules.voice.profiles import ProfileStore

        values = {k: data[k] for k in ("default", "mic", "speak_replies") if k in data}
        try:
            return ProfileStore(voice_dir() / "profiles.json").settings(values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/voice/profiles")
    def voice_profile_save(data: dict[str, Any]) -> dict[str, Any]:
        """Crée ou modifie un profil de voix (synthèse ou micro) ; le studio audio et le module partagent le fichier."""
        from modules.voice.profiles import ProfileStore

        try:
            return ProfileStore(voice_dir() / "profiles.json").save(data)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/voice/profiles/{pid}")
    def voice_profile_delete(pid: str) -> dict[str, Any]:
        from modules.voice.profiles import ProfileStore

        return {"deleted": ProfileStore(voice_dir() / "profiles.json").delete(pid)}

    @app.post("/v1/audio/speech")
    def v1_speech(data: dict[str, Any]) -> Response:
        """Format OpenAI : {input, voice, speed}. `voice` est un profil d'AetherTwin ; inconnu (alloy…) = défaut."""
        text = str(data.get("input") or data.get("text") or "")
        if not text.strip() or len(text) > 8000:
            raise HTTPException(status_code=400, detail="texte vide ou de plus de 8 000 caractères")
        profile = str(data.get("voice") or "")
        profiles = {p["id"] for p in voice_command("profiles", {}).get("profiles", [])}
        payload: dict[str, Any] = {"text": text, "profile": profile if profile in profiles else None, "file": True}
        if data.get("speed") is not None:
            payload["speed"] = data["speed"]
        if isinstance(data.get("effects"), dict):
            payload["effects"] = data["effects"]
        if isinstance(data.get("profile_data"), dict):  # profil non enregistré (essai dans le studio audio)
            payload["profile_data"] = data["profile_data"]
        result = voice_command("speak", payload)
        name = str(result.get("file", ""))
        if not VOICE_TMP_NAME.fullmatch(name):
            raise HTTPException(status_code=500, detail="réponse de la voix inattendue")
        path = voice_dir() / "tmp" / name
        try:
            wav = path.read_bytes()
        finally:
            path.unlink(missing_ok=True)
        return Response(content=wav, media_type="audio/wav",
                        headers={"X-Voice-Profile": str(result.get("profile", "")),
                                 "X-Voice-Engine": str(result.get("engine", "")),
                                 "X-Voice-Fallback": "1" if result.get("note") else "0",
                                 "Cache-Control": "no-store"})

    @app.post("/v1/audio/transcriptions")
    async def v1_transcriptions(request: Request) -> Any:
        """Format OpenAI (multipart : file, language, response_format) ou audio brut (`?language=fr`)."""
        content_type = request.headers.get("content-type", "")
        body = await request.body()
        if not body or len(body) > MAX_VOICE_AUDIO + 100_000:
            raise HTTPException(status_code=413, detail="enregistrement vide ou de plus de 5 Mo")
        language, response_format = request.query_params.get("language", "fr"), "json"
        if content_type.lower().startswith("multipart/form-data"):
            fields = multipart_fields(content_type, body)
            if "file" not in fields:
                raise HTTPException(status_code=400, detail="champ « file » attendu")
            audio, kind, filename = fields["file"]
            suffix = audio_suffix(kind, filename)
            if "language" in fields:
                language = fields["language"][0].decode("utf-8", "replace").strip()
            if "response_format" in fields:
                response_format = fields["response_format"][0].decode("utf-8", "replace").strip()
        else:
            audio, suffix = body, audio_suffix(content_type)
        if not audio or len(audio) > MAX_VOICE_AUDIO:
            raise HTTPException(status_code=413, detail="enregistrement vide ou de plus de 5 Mo")
        if language and not re.fullmatch(r"[a-z]{2,3}", language):
            language = "" if language == "auto" else "fr"
        folder = voice_dir() / "tmp"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.{suffix}"
        (folder / name).write_bytes(audio)
        try:
            result = await run_in_threadpool(voice_command, "transcribe", {"file": name, "language": language or None})
        finally:
            (folder / name).unlink(missing_ok=True)
        if response_format == "text":
            return Response(content=str(result.get("text", "")), media_type="text/plain; charset=utf-8")
        return {"text": result.get("text", ""), "language": result.get("language"),
                "duration": result.get("duration")}

    # -- guides (README du dépôt, en lecture seule, liste fermée)
    @app.get("/guides")
    def guides() -> list[dict[str, str]]:
        return [{"id": gid, "title": title} for gid, (title, _path) in guide_catalog().items()]

    @app.get("/guides/{gid}")
    def guide(gid: str) -> dict[str, str]:
        entry = guide_catalog().get(gid)
        if entry is None:
            raise HTTPException(status_code=404, detail="guide inconnu")
        title, path = entry
        return {"id": gid, "title": title, "markdown": path.read_text(encoding="utf-8", errors="replace")[:400_000]}

    @app.get("/v1/models")
    def v1_models() -> dict[str, Any]:
        models = llm_call(lambda: {"models": daemon.llm.list_models()})["models"]
        return {"object": "list", "data": [{"id": m["name"], "object": "model",
                                            "owned_by": "strata" if is_strata(m["name"]) else "ollama"}
                                           for m in models]}

    @app.post("/v1/chat/completions")
    def v1_chat(request: ChatRequest) -> Any:
        if request.num_ctx is not None and not 512 <= request.num_ctx <= 131072:
            raise HTTPException(status_code=400, detail="num_ctx hors bornes (512 à 131072)")
        options = {"temperature": request.temperature} if request.temperature is not None else None
        if request.stream:  # format OpenAI : événements SSE `data: {chunk}`, puis `data: [DONE]`
            chunk_id, created = f"chatcmpl-aethertwin-{int(time.time() * 1000)}", int(time.time())
            model = request.model or daemon.llm.config.default_model

            def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
                body = {"id": chunk_id, "object": "chat.completion.chunk", "created": created, "model": model,
                        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"

            def events() -> Any:
                yield chunk({"role": "assistant"})
                for kind, value in stream_pieces(openai_to_ollama(request.messages), request.model,
                                                 num_ctx=request.num_ctx, think=request.think, options=options):
                    if kind == "text":
                        yield chunk({"content": value})
                    elif kind == "done":
                        yield chunk({}, "stop")
                    else:
                        yield f"data: {json.dumps({'error': {'message': value}}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")
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
