"""Nœuds ComfyUI d'AetherTwin : masque de main (HandSegNet) et de pied (FootSegNet).

Installation : copier ce dossier dans `ComfyUI/custom_nodes/aethertwin_segnet/`, déposer les poids
(`handsegnet_vit_b_best.safetensors`, `footsegnet_vit_b_best.safetensors`) dans `ComfyUI/models/sams/`
ou donner leur chemin dans le nœud, puis installer `segment-anything` dans l'environnement de ComfyUI :
`pip install git+https://github.com/facebookresearch/segment-anything.git`.

Le dossier est autonome (aucun import du reste d'AetherTwin) ; `torch` et `segment_anything` ne sont importés
qu'à l'exécution du nœud, ce qui permet de tester son chargement sans ComfyUI.

Types ComfyUI : IMAGE = tenseur [lot, hauteur, largeur, 3] en flottants 0–1 ; MASK = [lot, hauteur, largeur].
"""
from __future__ import annotations

import os
from typing import Any

WEIGHT_FILES = {"hand": "handsegnet_vit_b_best.safetensors", "foot": "footsegnet_vit_b_best.safetensors"}
_CACHE: dict[str, Any] = {}


def _resolve_weights(target: str, path: str) -> str:
    if path:
        return path
    try:  # dossier de modèles de ComfyUI, s'il est là
        import folder_paths  # type: ignore[import-not-found]

        for folder in ("sams", "segment_anything"):
            found = folder_paths.get_full_path(folder, WEIGHT_FILES[target])
            if found:
                return found
    except Exception:  # noqa: BLE001, S110 — hors de ComfyUI : on tente le dossier courant
        pass
    return os.path.join("models", "sams", WEIGHT_FILES[target])


def _predictor(weights: str) -> Any:
    if weights not in _CACHE:
        import torch
        from segment_anything import SamPredictor, sam_model_registry

        if weights.endswith(".safetensors"):
            from safetensors.torch import load_file

            state = load_file(weights)
        else:
            state = torch.load(weights, map_location="cpu", weights_only=True)
        sam = sam_model_registry["vit_b"](checkpoint=None)
        sam.load_state_dict(state)
        sam.to("cuda" if torch.cuda.is_available() else "cpu").eval()
        _CACHE.clear()  # un seul modèle en mémoire à la fois
        _CACHE[weights] = SamPredictor(sam)
    return _CACHE[weights]


def segment_batch(image: Any, box: tuple[int, int, int, int], target: str, weights: str = "") -> Any:
    """Masque pour chaque image du lot. `box` en pixels (x1, y1, x2, y2), bornée à l'image."""
    import numpy as np
    import torch

    predictor = _predictor(_resolve_weights(target, weights))
    masks = []
    for frame in image:
        rgb = (frame.cpu().numpy() * 255).clip(0, 255).astype("uint8")
        height, width = rgb.shape[:2]
        x1, y1, x2, y2 = box
        x1, x2 = sorted((max(0, min(width - 1, x1)), max(0, min(width - 1, x2))))
        y1, y2 = sorted((max(0, min(height - 1, y1)), max(0, min(height - 1, y2))))
        with torch.inference_mode():
            predictor.set_image(rgb)
            result, _scores, _ = predictor.predict(box=np.array([x1, y1, x2, y2]), multimask_output=False)
        masks.append(torch.from_numpy(result[0].astype("float32")))
    return torch.stack(masks)


class _SegNetNode:
    TARGET = "hand"
    CATEGORY = "AetherTwin/masques"
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("masque",)
    FUNCTION = "segment"

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:  # noqa: N802 — nom imposé par ComfyUI
        box = {"default": 0, "min": 0, "max": 16384, "step": 1}
        return {
            "required": {"image": ("IMAGE",), "x1": ("INT", box), "y1": ("INT", box),
                         "x2": ("INT", {**box, "default": 512}), "y2": ("INT", {**box, "default": 512})},
            "optional": {"weights_path": ("STRING", {"default": ""})},
        }

    def segment(self, image: Any, x1: int, y1: int, x2: int, y2: int, weights_path: str = "") -> tuple[Any]:
        return (segment_batch(image, (x1, y1, x2, y2), self.TARGET, weights_path),)


class HandSegNetMask(_SegNetNode):
    """Masque d'une main dans la boîte (HandSegNet, SAM ViT-B affiné, Apache 2.0)."""

    TARGET = "hand"


class FootSegNetMask(_SegNetNode):
    """Masque d'un pied ou d'une chaussure dans la boîte (FootSegNet, SAM ViT-B affiné, Apache 2.0)."""

    TARGET = "foot"


NODE_CLASS_MAPPINGS = {"AetherTwinHandSegNet": HandSegNetMask, "AetherTwinFootSegNet": FootSegNetMask}
NODE_DISPLAY_NAME_MAPPINGS = {"AetherTwinHandSegNet": "Masque de main (HandSegNet)",
                              "AetherTwinFootSegNet": "Masque de pied (FootSegNet)"}
