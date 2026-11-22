"""OCR et traduction par les modèles locaux, **via le Hub** (API compatible OpenAI sur 127.0.0.1).

- OCR : le modèle de vision local (par défaut `qwen2.5vl:7b`, contexte 4096) lit le texte de chaque bulle.
  C'est l'« équivalent local » de manga-ocr, sans PyTorch à installer.
- Traduction : un seul appel par page, avec toutes les bulles numérotées (le contexte aide), le ton, et le
  glossaire de la série (noms des personnages, termes). Réponse attendue en JSON ; repli bulle par bulle.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from modules.scantrad.pipeline import Bubble

Chat = Callable[[list[dict[str, Any]], dict[str, Any]], str]

OCR_PROMPT = ("Transcris exactement le texte japonais écrit dans cette image extraite d'un manga. Le texte peut "
              "être vertical : lis les colonnes de haut en bas, de la droite vers la gauche. Ignore les petits "
              "caractères de lecture (furigana) placés à côté des kanji. Réponds uniquement par le texte transcrit, "
              "sur une ligne, sans traduction, sans commentaire. S'il n'y a pas de texte japonais lisible (dessin, "
              "décor), réponds exactement : AUCUN")
# Mode manuel : la zone a été posée à la main, il y a du texte. Sans l'échappatoire « AUCUN », que le modèle
# choisissait à tort pour un bloc horizontal de trois lignes (essai réel du 22/11).
MANUAL_OCR_PROMPT = ("Transcris exactement le texte japonais de cette image extraite d'un manga. Il peut être "
                     "horizontal, ou vertical (colonnes de haut en bas, de la droite vers la gauche). Ignore les "
                     "furigana. Réponds uniquement par le texte transcrit, sur une ligne, sans traduction ni "
                     "commentaire.")
# Sens connu (mesuré sur l'encre de la zone, voir `manual.is_vertical`) : laissé au choix, le modèle lisait une
# bulle de 4 colonnes ligne par ligne, d'où un texte dans le désordre (essai de Jérémy du 22/11).
MANUAL_OCR_VERTICAL = ("Transcris exactement le texte japonais de cette image extraite d'un manga. Le texte est "
                       "VERTICAL, en plusieurs colonnes : lis chaque colonne de haut en bas, en commençant par la "
                       "colonne la plus à DROITE, puis celle à sa gauche, et ainsi de suite. Ignore les furigana. "
                       "Réponds uniquement par le texte transcrit, sur une ligne, sans traduction ni commentaire.")
MANUAL_OCR_COLUMN = ("Transcris exactement le texte japonais de cette image : une seule colonne verticale, à lire "
                     "de haut en bas. Réponds uniquement par le texte transcrit, sans traduction ni commentaire.")
MANUAL_OCR_HORIZONTAL = ("Transcris exactement le texte japonais de cette image extraite d'un manga. Le texte est "
                         "HORIZONTAL : lis les lignes de gauche à droite, de haut en bas. Ignore les furigana. "
                         "Réponds uniquement par le texte transcrit, sur une ligne, sans traduction ni commentaire.")
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")


def accept_ocr(text: str) -> str:
    """Texte lu, ou "" si le modèle dit qu'il n'y a rien, ou s'il ne rend aucun caractère japonais."""
    text = " ".join(strip_thinking(text).split()).strip("「」『』\"' ")
    if not text or "AUCUN" in text.upper() or not JAPANESE.search(text):
        return ""
    return text


def hub_chat(hub_api: str = "http://127.0.0.1:5750", timeout_s: float = 300.0) -> Chat:
    def chat(messages: list[dict[str, Any]], extra: dict[str, Any]) -> str:
        body = json.dumps({"messages": messages, **extra}).encode("utf-8")
        request = urllib.request.Request(hub_api.rstrip("/") + "/v1/chat/completions", data=body,  # noqa: S310
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 — API locale du Hub
            data = json.loads(response.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"])
    return chat


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def bubble_png(page: np.ndarray, bubble: Bubble, pad: int = 0, min_side: int = 224) -> bytes:
    """Découpe le texte avec une marge (30 % de sa taille : un mot court, découpé au ras, n'est pas reconnu),
    agrandie si elle est petite : le modèle lit mieux."""
    x, y, w, h = bubble.box
    pad = pad or max(12, int(0.3 * max(w, h)))
    y0, x0 = max(0, y - pad), max(0, x - pad)
    crop = page[y0:y + h + pad, x0:x + w + pad].copy()
    # la marge est blanchie au-delà d'une petite bordure : le modèle a de l'espace autour du texte, mais ne voit
    # pas le texte d'une bulle voisine (sinon il le lit, et un faux positif du dessin passe pour une bulle)
    keep = max(4, int(0.12 * min(w, h)))
    inner = np.full(crop.shape[:2], False)
    inner[max(0, y - keep - y0):y + h + keep - y0, max(0, x - keep - x0):x + w + keep - x0] = True
    crop[~inner] = 255
    scale = max(1.0, min_side / max(1, min(crop.shape[:2])))
    if scale > 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    ok, png = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("encodage PNG impossible")
    return png.tobytes()


def make_vision_ocr(chat: Chat, model: str = "qwen2.5vl:7b", num_ctx: int = 4096,
                    prompt: str = OCR_PROMPT) -> Callable[..., str]:
    def read(page: np.ndarray, bubble: Bubble, pad: int) -> str:
        data_uri = "data:image/png;base64," + base64.b64encode(bubble_png(page, bubble, pad)).decode("ascii")
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt},
                                                 {"type": "image_url", "image_url": {"url": data_uri}}]}]
        return accept_ocr(chat(messages, {"model": model, "num_ctx": num_ctx, "temperature": 0}))

    def ocr(page: np.ndarray, bubble: Bubble) -> str:
        """Deux lectures au plus : la seconde, plus large, rattrape les mots courts lus « AUCUN » à tort."""
        return read(page, bubble, 0) or read(page, bubble, max(24, int(0.8 * max(bubble.box[2:]))))
    return ocr


def read_by_columns(column_ocr: Callable[..., str], page: np.ndarray, box: tuple[int, int, int, int]) -> str:
    """Texte vertical de `box` lu colonne par colonne, de droite à gauche, puis recollé ("" si aucune colonne).
    Le modèle de vision mélange l'ordre des colonnes courtes d'une même bulle ; lues une par une, elles sont
    justes (page de Jérémy, 22/11 : 6 zones sur 6)."""
    from modules.scantrad.manual import bubbles_from_boxes, split_columns

    x, y, w, h = box
    parts = [column_ocr(page, bubbles_from_boxes([(x + cx, y + cy, cw, ch)])[0])
             for cx, cy, cw, ch in split_columns(page[y:y + h, x:x + w])]
    return re.sub(r"\s+", "", "".join(parts))


def make_column_aware_ocr(chat: Chat, model: str = "qwen2.5vl:7b") -> Callable[..., str]:
    """OCR du mode automatique : une première lecture décide s'il y a du texte (« AUCUN » écarte les faux positifs
    de la détection) ; un bloc vertical de plusieurs colonnes est ensuite relu colonne par colonne."""
    from modules.scantrad.manual import is_vertical, split_columns

    first = make_vision_ocr(chat, model)
    column = make_vision_ocr(chat, model, prompt=MANUAL_OCR_COLUMN)

    def ocr(page: np.ndarray, bubble: Bubble) -> str:
        text = first(page, bubble)
        if not text:
            return ""
        x, y, w, h = bubble.box  # cadre du texte, élargi un peu : l'encre ne doit pas toucher le bord
        pad = max(6, int(0.05 * max(w, h)))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        box = (x0, y0, min(page.shape[1], x + w + pad) - x0, min(page.shape[0], y + h + pad) - y0)
        crop = page[box[1]:box[1] + box[3], box[0]:box[0] + box[2]]
        if (bubble.vertical or is_vertical(crop)) and len(split_columns(crop)) >= 2:
            return read_by_columns(column, page, box) or text
        return text
    return ocr


@dataclass
class Glossary:
    """Glossaire persistant d'une série : personnages et termes (japonais → français), ton, notes."""

    path: Path
    characters: dict[str, str] = field(default_factory=dict)
    terms: dict[str, str] = field(default_factory=dict)
    tone: str = "naturel, oral, fidèle au registre de chaque personnage"

    @classmethod
    def load(cls, path: Path) -> Glossary:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(path)
        return cls(path, dict(data.get("characters", {})), dict(data.get("terms", {})),
                   str(data.get("tone") or cls.tone))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"characters": self.characters, "terms": self.terms, "tone": self.tone},
                                        ensure_ascii=False, indent=2), encoding="utf-8")

    def relevant(self, texts: list[str]) -> dict[str, str]:
        """Entrées présentes dans la page (on n'encombre pas le prompt avec tout le glossaire)."""
        joined = "".join(texts)
        return {jp: fr for jp, fr in {**self.characters, **self.terms}.items() if jp in joined}


def translation_prompt(texts: list[str], glossary: Glossary | None, target: str = "français") -> str:
    lines = [f"Tu traduis une page de manga du japonais vers le {target}.",
             f"Ton : {glossary.tone if glossary else 'naturel et oral'}.",
             "Les bulles sont dans l'ordre de lecture ; garde la cohérence entre elles.",
             "Traduction courte, qui tient dans une bulle. N'ajoute aucune explication."]
    entries = glossary.relevant(texts) if glossary else {}
    if entries:
        lines.append("Glossaire imposé : " + " ; ".join(f"{jp} = {fr}" for jp, fr in entries.items()) + ".")
    lines.append('Réponds uniquement en JSON : {"1": "…", "2": "…"} avec une entrée par bulle.')
    lines.append("Bulles :")
    lines += [f"{i}. {text}" for i, text in enumerate(texts, start=1)]
    return "\n".join(lines)


def parse_translations(answer: str, count: int) -> list[str] | None:
    match = re.search(r"\{.*\}", strip_thinking(answer), flags=re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    out = [str(data.get(str(i), "")).strip() for i in range(1, count + 1)]
    return out if all(out) else None


def make_translator(chat: Chat, glossary: Glossary | None = None, model: str = "",
                    target: str = "français") -> Callable[[list[str]], list[str]]:
    extra: dict[str, Any] = {"think": False, "temperature": 0.3}
    if model:
        extra["model"] = model

    def translate(texts: list[str]) -> list[str]:
        answer = chat([{"role": "user", "content": translation_prompt(texts, glossary, target)}], extra)
        parsed = parse_translations(answer, len(texts))
        if parsed is not None:
            return parsed
        single = []  # repli : une bulle à la fois, la réponse brute est la traduction
        for text in texts:
            reply = chat([{"role": "user", "content": translation_prompt([text], glossary, target)}], extra)
            one = parse_translations(reply, 1)
            single.append(one[0] if one else strip_thinking(reply).splitlines()[0].strip())
        return single
    return translate
