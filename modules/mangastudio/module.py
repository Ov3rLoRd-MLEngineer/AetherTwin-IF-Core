"""Module du Hub : segmentation main/pied à la demande (retouche locale).

    module.mangastudio.cmd.status   {"request_id"}
    module.mangastudio.cmd.segment  {"request_id", "input": "image.png", "target": "hand"|"foot",
                                     "boxes": [[x1, y1, x2, y2], …], "output_dir": ""}

Réponse sur `module.mangastudio.result`. Le masque (`*_mask.png`, blanc = zone) et un aperçu teinté
(`*_apercu.png`) sont écrits dans `output_dir` (défaut `data/mangastudio/sorties`).

Le modèle SAM monte à 2,8 Go de VRAM (mesuré le 17/11/2026 sur RTX 5080 : 21,8 s au premier appel,
initialisation CUDA comprise, puis 0,17 s par masque) : il est libéré par la commande `unload`, et à l'arrêt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from core.module_api import Event, Health, ModuleBase
from modules.mangastudio.segment import (
    TARGETS,
    check_box,
    combine,
    make_segmenter,
    missing_dependencies,
    overlay,
    weights_path,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def read_rgb(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"image illisible : {path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def write_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if image.ndim == 3 else image
    ok, encoded = cv2.imencode(".png", data)
    if not ok:
        raise ValueError(f"écriture impossible : {path}")
    encoded.tofile(str(path))


def status(settings: dict[str, Any]) -> dict[str, Any]:
    missing = missing_dependencies()
    models = {}
    for target, name in TARGETS.items():
        weights = weights_path(target, settings)
        models[target] = {"model": name, "weights": weights.name, "present": weights.is_file(),
                          "ready": not missing and weights.is_file()}
    return {"missing_dependencies": missing, "models": models,
            "simulation": any(not m["ready"] for m in models.values())}


class MangaStudioModule(ModuleBase):
    def start(self) -> None:
        self.segmenters: dict[str, Any] = {}
        self.requests = 0

    def stop(self) -> None:
        for segmenter in self.segmenters.values():
            segmenter.unload()
        self.segmenters = {}

    def health(self) -> Health:
        state = status(self.config)
        ready = [m["model"] for m in state["models"].values() if m["ready"]]
        detail = (f"modèles prêts : {', '.join(ready)}" if ready else "mode simulation (GrabCut)")
        if state["missing_dependencies"]:
            detail += f" — dépendances absentes : {', '.join(state['missing_dependencies'])}"
        return Health(ok=True, degraded=not ready, detail=f"{detail} ; {self.requests} demandes")

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        try:
            result = self._run(command, payload)
            reply = {"ok": True, "result": result}
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"),
                                                           "command": command, **reply}, source=self.name))

    def _run(self, command: str, payload: dict[str, Any]) -> Any:
        if command == "status":
            return status(self.config)
        if command == "unload":
            self.stop()
            self.segmenters = {}
            return {"unloaded": True}
        if command != "segment":
            raise ValueError(f"commande inconnue : {command!r}")
        self.requests += 1
        target = str(payload.get("target", "hand"))
        source = Path(str(payload["input"]))
        image = read_rgb(source)
        height, width = image.shape[:2]
        boxes = [check_box(box, width, height) for box in payload.get("boxes") or []]
        if not boxes:
            raise ValueError("au moins une boîte est nécessaire")
        device = str(payload.get("device") or "")  # carte choisie par Inoue (« cuda:N »), sinon réglage local
        settings = {**self.config, "device": device} if device else self.config
        if target in self.segmenters and getattr(self.segmenters[target], "device", "") != settings.get("device", ""):
            self.segmenters.pop(target).unload()  # autre carte : le modèle est rechargé là où il y a la place
        if target not in self.segmenters:
            self.segmenters[target] = make_segmenter(target, settings)
        segmenter = self.segmenters[target]
        results = [segmenter(image, box) for box in boxes]
        mask = combine([r.mask for r in results])
        out_dir = Path(str(payload.get("output_dir") or REPO_ROOT / "data" / "mangastudio" / "sorties"))
        mask_path = out_dir / f"{source.stem}_{target}_mask.png"
        preview_path = out_dir / f"{source.stem}_{target}_apercu.png"
        write_png(mask_path, mask)
        write_png(preview_path, overlay(image, mask))
        first = results[0]
        return {"backend": first.backend, "simulated": first.simulated,
                "reason": getattr(segmenter, "reason", ""), "boxes": [list(b) for b in boxes],
                "seconds": round(sum(r.seconds for r in results), 3),
                "scores": [r.score for r in results], "mask_pixels": int(np.count_nonzero(mask)),
                "mask": str(mask_path), "preview": str(preview_path)}
