"""Module du Hub : traduit une page sur commande.

    module.scantrad.cmd.page  {"request_id", "input": "page.png", "series": "demo", "output": "", "no_llm": false}

Réponse sur `module.scantrad.result` : bulles (texte lu, traduction), métriques (temps par étape, VRAM),
chemin de l'image produite. Le module ne charge aucun modèle lui-même : l'OCR et la traduction passent par le
routeur LLM du Hub, qui applique les règles VRAM (d'où `vram_min_gb: 0` dans le manifeste).

Configuration (section `scantrad` de `config/local.yaml`), facultative :

    hub_api: "http://127.0.0.1:5750"
    ocr_model: "qwen2.5vl:7b"
    model: ""            # traduction : vide = modèle par défaut du Hub
    font: ""             # police de réincrustation (chemin .ttf) ; vide = Comic Sans / Arial / police de Pillow
    data_dir: ""         # glossaires et sorties ; vide = data/scantrad
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.scantrad.cli import DEFAULT_DATA, build, read_image, write_image


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
        if event.topic != f"module.{self.name}.cmd.page":
            return
        payload = event.payload
        try:
            source = Path(str(payload["input"]))
            if not source.is_file():
                raise ValueError(f"fichier introuvable : {source}")
            data_dir = Path(self.config.get("data_dir") or DEFAULT_DATA)
            output = Path(str(payload.get("output") or data_dir / "sorties" / f"{source.stem}_fr.png"))
            result = build(self.config, str(payload.get("series", "")), use_llm=not payload.get("no_llm")).run(
                read_image(source))
            write_image(output, result.image)
            self.pages += 1
            self.last_metrics = result.metrics
            reply = {"ok": True, "result": {**result.summary(), "output": str(output)}}
        except (KeyError, ValueError, OSError) as exc:
            self.errors += 1
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"), "command": "page",
                                                           **reply}, source=self.name))
