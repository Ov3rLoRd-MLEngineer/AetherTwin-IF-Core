"""Traduction générale vers le français : texte, image (capture, photo) ou message vocal.

Langues sources : japonais, chinois, coréen, anglais (les mêmes que Scantrad), ou détection automatique.
Tout reste local :
- texte → modèle de langage par défaut du Hub ;
- image → modèle de vision (`qwen2.5vl:7b`) qui transcrit le texte, puis traduction ;
- voix → reconnaissance locale par faster-whisper (facultative : `scripts\\setup.ps1 -Voice`), puis traduction.
"""
from __future__ import annotations

import base64
import io
import re
from collections.abc import Callable
from typing import Any

from modules.scantrad.languages import LANGUAGES, language

MAX_TEXT = 6000
IDIOMS = ("Les formules toutes faites (salutations, politesse, repas, fin de journée…) se rendent par ce qu'un "
          "francophone dirait dans la même situation, pas mot à mot (よろしくお願いします, いただきます, "
          "お疲れ様…). Un nom propre étranger transcrit phonétiquement (katakana, hangul, caractères chinois) "
          "se rend dans sa graphie d'origine probable (ジェルミ → Jérémy, マイケル → Michael).")
Chat = Callable[..., dict[str, Any]]  # LlmRouter.chat

SCRIPTS = [("ko", re.compile(r"[가-힯]")), ("ja", re.compile(r"[぀-ヿ]")), ("zh", re.compile(r"[㐀-鿿]")),
           ("en", re.compile(r"[A-Za-z]"))]


def detect_language(text: str) -> str:
    """Langue devinée à l'écriture : hangul → coréen, kana → japonais, idéogrammes seuls → chinois, latin →
    anglais. Le japonais mêle kana et kanji : les kana décident avant les idéogrammes."""
    for code, pattern in SCRIPTS:
        if pattern.search(text):
            return code
    raise ValueError("langue non reconnue : japonais, chinois, coréen ou anglais attendu")


def translation_messages(text: str, lang: str) -> list[dict[str, str]]:
    """Consigne de traduction. `IDIOMS` : mesuré le 22/11 avec `qwen3-27b` ; sans elle, « ジェルミ » donnait
    « Gelmi » et « いただきます » « Je vous remercie » ; avec elle, « Jérémy » et « Bon appétit »."""
    spec = language(lang)
    return [{"role": "system", "content": (
                f"Tu es un traducteur professionnel du {spec.name} vers le français. Tu traduis fidèlement, dans un "
                "français naturel, en gardant le ton, les noms propres et la mise en forme (retours à la ligne). "
                f"{IDIOMS} Tu ne réponds que par la traduction, sans commentaire ni note.")},
            {"role": "user", "content": text}]


def translate_text(chat: Chat, text: str, lang: str = "auto", model: str | None = None) -> dict[str, Any]:
    text = text.strip()
    if not text or len(text) > MAX_TEXT:
        raise ValueError(f"texte vide ou trop long ({MAX_TEXT} caractères au plus)")
    code = detect_language(text) if lang == "auto" else language(lang).code
    reply = chat(translation_messages(text, code), model=model, think=False, options={"temperature": 0.3})
    translation = re.sub(r"<think>.*?</think>", "", str(reply.get("content", "")), flags=re.S).strip()
    return {"lang": code, "language": LANGUAGES[code].name, "source": text, "translation": translation,
            "model": reply.get("model"), "seconds": reply.get("seconds")}


def image_prompt(lang: str) -> str:
    if lang == "auto":
        which = "tout le texte (japonais, chinois, coréen ou anglais)"
    else:
        spec = language(lang)
        which = f"tout le texte {spec.name}" + (" (vertical : colonnes de droite à gauche)" if spec.vertical else "")
    # pas d'échappatoire « réponds AUCUN » : sur une page de manga entière, le modèle la choisissait à tort
    # (essai réel du 22/11) ; sans elle, il lit tout le texte
    return (f"Transcris exactement {which} visible dans cette image, dans l'ordre de lecture, en gardant les "
            "retours à la ligne. Ne traduis pas, ne commente pas.")


def read_image(chat: Chat, image: bytes, lang: str = "auto", model: str = "qwen2.5vl:7b") -> str:
    """Texte d'une image (PNG, JPEG ou WebP), lu par le modèle de vision. L'image est réduite à ~1,3 Mpx : au-delà,
    le modèle de vision la réduit de toute façon, et la VRAM grimpe."""
    import cv2
    import numpy as np

    picture = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if picture is None:
        raise ValueError("image illisible")
    scale = min(1.0, (1_300_000 / (picture.shape[0] * picture.shape[1])) ** 0.5)
    if scale < 1:
        picture = cv2.resize(picture, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, png = cv2.imencode(".png", picture)
    if not ok:
        raise ValueError("encodage impossible")
    data = base64.b64encode(png.tobytes()).decode("ascii")  # format d'Ollama : image jointe au message
    reply = chat([{"role": "user", "content": image_prompt(lang), "images": [data]}],
                 model=model, num_ctx=8192, options={"temperature": 0})
    text = re.sub(r"<think>.*?</think>", "", str(reply.get("content", "")), flags=re.S).strip()
    if not text or text.upper().startswith("AUCUN"):
        raise ValueError("aucun texte trouvé dans l'image")
    return text


WHISPER_LANGS = {"ja": "ja", "zh": "zh", "ko": "ko", "en": "en"}
_whisper: dict[str, Any] = {}


def voice_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def transcribe(audio: bytes, lang: str = "auto", model_name: str = "small") -> dict[str, str]:
    """Message vocal → texte, sur cette machine (faster-whisper, sur le processeur en int8 : la VRAM reste aux
    modèles de langage). Le modèle est téléchargé au premier usage puis gardé en mémoire."""
    if not voice_available():
        raise RuntimeError("reconnaissance vocale non installée : lance `scripts\\setup.ps1 -Voice`")
    from faster_whisper import WhisperModel

    if model_name not in _whisper:
        _whisper.clear()
        _whisper[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = _whisper[model_name].transcribe(io.BytesIO(audio), language=WHISPER_LANGS.get(lang),
                                                     vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not text:
        raise ValueError("aucune parole reconnue")
    detected = info.language if info.language in WHISPER_LANGS else None
    if lang == "auto" and detected is None:
        raise ValueError(f"langue parlée non prise en charge ({info.language})")
    return {"text": text, "lang": lang if lang != "auto" else detected}
