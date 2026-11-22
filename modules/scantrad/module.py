"""Module du Hub : traduit une page sur commande, et réincruste des traductions corrigées à la main.

    module.scantrad.cmd.page       {"request_id", "input": "page.png", "series": "demo", "output": "", "no_llm": false}
    module.scantrad.cmd.retypeset  {"request_id", "output": "…_fr.png", "translations": {"1": "…", "2": "…"}}

Mode manuel (zones posées à la main, voir `manual.py`) :

    module.scantrad.cmd.suggest    {"input"}                        → boîtes de la détection automatique
    module.scantrad.cmd.read       {"input", "boxes": [[x,y,l,h]…]} → texte lu dans chaque boîte, dans l'ordre
    module.scantrad.cmd.translate  {"texts": […], "series"}         → traductions, dans l'ordre
    module.scantrad.cmd.erase      {"input", "boxes", "output"}     → page dont le texte des boîtes est effacé
    module.scantrad.cmd.compose    {"input", "output", "bubbles": [{"box", "source", "translation"}…]}
                                   → page traduite, sur la page gommée (`<nom>_propre.png`) si elle existe

Réponse sur `module.scantrad.result` : bulles (texte lu, traduction), métriques (temps par étape, VRAM),
chemin de l'image produite. À côté de chaque page traduite, deux fichiers de travail :
`<nom>_propre.png` (page sans le texte d'origine) et `<nom>_travail.json` (bulles et zones d'écriture),
qui permettent de corriger une traduction et de réincruster sans relancer l'OCR ni le modèle.

Le module ne charge aucun modèle lui-même : l'OCR et la traduction passent par le routeur LLM du Hub, qui
applique les règles VRAM (d'où `vram_min_gb: 0` dans le manifeste).

Configuration (section `scantrad` de `config/local.yaml`), facultative :

    hub_api: "http://127.0.0.1:5750"
    ocr_model: "qwen2.5vl:7b"
    model: ""            # traduction : vide = modèle par défaut du Hub
    font: ""             # police de réincrustation (chemin .ttf) ; vide = Comic Sans / Arial / police de Pillow
    data_dir: ""         # glossaires et sorties ; vide = data/scantrad
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from core.module_api import Event, Health, ModuleBase
from modules.scantrad import manual
from modules.scantrad.cli import DEFAULT_DATA, build, glossary_for, read_image, write_image
from modules.scantrad.hub_stages import (
    MANUAL_OCR_COLUMN,
    MANUAL_OCR_HORIZONTAL,
    MANUAL_OCR_VERTICAL,
    hub_chat,
    make_translator,
    make_vision_ocr,
)
from modules.scantrad.pipeline import Bubble
from modules.scantrad.typeset import make_typesetter, text_area

MAX_TRANSLATION = 400


def work_paths(output: Path) -> tuple[Path, Path]:
    """Fichiers de travail d'une page traduite : (image nettoyée, description des bulles)."""
    stem = output.stem[:-3] if output.stem.endswith("_fr") else output.stem
    return output.with_name(f"{stem}_propre.png"), output.with_name(f"{stem}_travail.json")


def save_work(output: Path, cleaned: np.ndarray, bubbles: list[Bubble]) -> None:
    clean_path, job_path = work_paths(output)
    write_image(clean_path, cleaned)
    rows = []
    for bubble in bubbles:
        row = bubble.to_dict()
        row["area"] = list(bubble.area or text_area(bubble))  # zone d'écriture figée : plus besoin des masques
        rows.append(row)
    job_path.write_text(json.dumps({"bubbles": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


def retypeset(output: Path, translations: dict[str, str], font: str = "") -> list[dict[str, Any]]:
    """Réincruste des traductions corrigées sur la page nettoyée. Rend les bulles mises à jour."""
    clean_path, job_path = work_paths(output)
    if not clean_path.is_file() or not job_path.is_file():
        raise ValueError("fichiers de travail absents : retraduis la page")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    bubbles = []
    for row in job["bubbles"]:
        text = translations.get(str(row["index"]), row["translation"])
        if not isinstance(text, str) or len(text) > MAX_TRANSLATION:
            raise ValueError(f"traduction de la bulle {row['index']} invalide (texte de {MAX_TRANSLATION} car. max)")
        row["translation"] = " ".join(text.split())
        x, y, w, h = row["box"]
        bubbles.append(Bubble(row["index"], tuple(row["box"]), np.full((h, w), 255, np.uint8),
                              np.zeros((h, w), np.uint8), row["source"], row["translation"],
                              area=tuple(row["area"]), vertical=bool(row.get("vertical"))))
    write_image(output, make_typesetter(font)(read_image(clean_path), bubbles))
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    return job["bubbles"]


MANUAL_COMMANDS = ("suggest", "read", "translate", "erase", "compose")


def compose(source: Path, output: Path, rows: Any, font: str = "", auto_erase: bool = True) -> list[dict[str, Any]]:
    """Page traduite du mode manuel : bulles = boîtes posées à la main ; base = page gommée si elle existe
    (sinon l'original), puis, sauf refus, effacement automatique du texte restant dans les boîtes."""
    page = read_image(source)
    if not isinstance(rows, list):
        raise ValueError("`bubbles` : liste de {box, source, translation}")
    boxes = manual.parse_boxes([r.get("box") if isinstance(r, dict) else None for r in rows], page.shape)
    clean_path, _job_path = work_paths(output)
    cleaned = page
    if clean_path.is_file():
        cleaned = read_image(clean_path)
        if cleaned.shape != page.shape:
            raise ValueError("la page gommée n'a pas la taille de l'original")
    if auto_erase:
        cleaned = manual.erase_in_boxes(cleaned, boxes)
    bubbles = manual.bubbles_from_boxes(boxes)
    for bubble, row in zip(bubbles, rows, strict=True):
        bubble.source = str(row.get("source") or "")[:MAX_TRANSLATION]
        text = row.get("translation") or ""
        if not isinstance(text, str) or len(text) > MAX_TRANSLATION:
            raise ValueError(f"traduction de la bulle {bubble.index} invalide (texte de {MAX_TRANSLATION} car. max)")
        bubble.translation = " ".join(text.split())
        x, y, w, h = bubble.box
        bubble.vertical = manual.is_vertical(page[y:y + h, x:x + w])
        bubble.area = manual.widen_area(cleaned, bubble.box)  # une colonne étroite s'élargit dans sa bulle
    save_work(output, cleaned, bubbles)
    return retypeset(output, {}, font)


class ScantradModule(ModuleBase):
    def start(self) -> None:
        self.pages = 0
        self.errors = 0
        self.last_metrics: dict[str, Any] = {}

    def stop(self) -> None:
        pass

    def health(self) -> Health:
        return Health(ok=True, detail=f"{self.pages} pages traduites, {self.errors} erreurs ; "
                                      f"dernière page : {self.last_metrics.get('total_s', '—')} s")

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        try:
            if command == "page":
                result = self._page(payload)
            elif command == "retypeset":
                output = Path(str(payload["output"]))
                translations = payload.get("translations") or {}
                if not isinstance(translations, dict):
                    raise ValueError("`translations` : dictionnaire {numéro de bulle: texte}")
                result = {"bubbles": retypeset(output, translations, str(self.config.get("font", ""))),
                          "output": str(output)}
            elif command in MANUAL_COMMANDS:
                result = getattr(self, f"_manual_{command}")(payload)
            else:
                raise ValueError(f"commande inconnue : {command!r}")
            reply = {"ok": True, "result": result}
        except (KeyError, ValueError, OSError) as exc:
            self.errors += 1
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"),
                                                           "command": command, **reply}, source=self.name))

    # ---------- mode manuel ----------
    def _source(self, payload: dict[str, Any]) -> Path:
        source = Path(str(payload["input"]))
        if not source.is_file():
            raise ValueError(f"fichier introuvable : {source}")
        return source

    def _chat(self) -> Any:
        return hub_chat(str(self.config.get("hub_api", "http://127.0.0.1:5750")))

    def _manual_suggest(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"boxes": manual.suggest_boxes(read_image(self._source(payload)))}

    def _manual_read(self, payload: dict[str, Any]) -> dict[str, Any]:
        page = read_image(self._source(payload))
        bubbles = manual.bubbles_from_boxes(manual.parse_boxes(payload.get("boxes"), page.shape))
        model = str(self.config.get("ocr_model", "qwen2.5vl:7b"))
        chat = self._chat()
        whole_vertical = make_vision_ocr(chat, model, prompt=MANUAL_OCR_VERTICAL)
        horizontal = make_vision_ocr(chat, model, prompt=MANUAL_OCR_HORIZONTAL)
        one_column = make_vision_ocr(chat, model, prompt=MANUAL_OCR_COLUMN)
        sources, vertical = [], []
        for bubble in bubbles:
            x, y, w, h = bubble.box
            crop = page[y:y + h, x:x + w]
            column = manual.is_vertical(crop)
            vertical.append(column)
            if not column:
                sources.append(horizontal(page, bubble).strip())
                continue
            # texte vertical : chaque colonne lue seule, de droite à gauche, puis recollée
            parts = [one_column(page, manual.bubbles_from_boxes([(x + cx, y + cy, cw, ch)])[0])
                     for cx, cy, cw, ch in manual.split_columns(crop)]
            text = re.sub(r"\s+", "", "".join(parts))
            sources.append(text or whole_vertical(page, bubble).strip())
        return {"sources": sources, "vertical": vertical}

    def _manual_translate(self, payload: dict[str, Any]) -> dict[str, Any]:
        texts = payload.get("texts")
        if not isinstance(texts, list) or not all(isinstance(t, str) and len(t) <= MAX_TRANSLATION for t in texts):
            raise ValueError(f"`texts` : liste de textes ({MAX_TRANSLATION} car. max chacun)")
        series = str(payload.get("series", ""))
        glossary = glossary_for(series, Path(self.config.get("data_dir") or DEFAULT_DATA)) if series else None
        todo = [i for i, text in enumerate(texts) if text.strip()]
        out = [""] * len(texts)
        if todo:
            translate = make_translator(self._chat(), glossary, str(self.config.get("model", "")))
            for i, text in zip(todo, translate([texts[i].strip() for i in todo]), strict=True):
                out[i] = text.strip()
        return {"translations": out}

    def _manual_erase(self, payload: dict[str, Any]) -> dict[str, Any]:
        page = read_image(self._source(payload))
        output = Path(str(payload["output"]))
        write_image(output, manual.erase_in_boxes(page, manual.parse_boxes(payload.get("boxes"), page.shape)))
        return {"output": str(output)}

    def _manual_compose(self, payload: dict[str, Any]) -> dict[str, Any]:
        output = Path(str(payload["output"]))
        bubbles = compose(self._source(payload), output, payload.get("bubbles"), str(self.config.get("font", "")),
                          auto_erase=payload.get("auto_erase") is not False)
        self.pages += 1
        return {"bubbles": bubbles, "output": str(output)}

    def _page(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = Path(str(payload["input"]))
        if not source.is_file():
            raise ValueError(f"fichier introuvable : {source}")
        data_dir = Path(self.config.get("data_dir") or DEFAULT_DATA)
        output = Path(str(payload.get("output") or data_dir / "sorties" / f"{source.stem}_fr.png"))
        result = build(self.config, str(payload.get("series", "")), use_llm=not payload.get("no_llm")).run(
            read_image(source))
        write_image(output, result.image)
        if result.cleaned is not None:
            save_work(output, result.cleaned, result.bubbles)
        self.pages += 1
        self.last_metrics = result.metrics
        return {**result.summary(), "output": str(output)}
