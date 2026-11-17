"""mangastudio : segmentation (simulation hors GPU), nœuds ComfyUI, workflow de continuité, module."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from core.module_api import Event, load_manifest
from modules.mangastudio.module import MangaStudioModule, read_rgb, status, write_png
from modules.mangastudio.segment import (
    SimulatedSegmenter,
    check_box,
    combine,
    make_segmenter,
    missing_dependencies,
    overlay,
)

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / "modules" / "mangastudio"
ABSENT = {"handsegnet_weights": "absent/hand.safetensors", "footsegnet_weights": "absent/foot.safetensors"}


def drawing() -> np.ndarray:
    """Fond clair, une « main » (forme pleine) dans la boîte (100, 80, 220, 220)."""
    image = np.full((300, 320, 3), 235, np.uint8)
    cv2.ellipse(image, (160, 150), (45, 55), 0, 0, 360, (230, 180, 150), -1)
    for k in range(4):
        cv2.rectangle(image, (125 + k * 20, 70 + 15), (138 + k * 20, 110), (230, 180, 150), -1)
    return image


def test_check_box() -> None:
    assert check_box([220, 220, 100, 80], 320, 300) == (100, 80, 220, 220)  # coins inversés : remis en ordre
    assert check_box([-50, -5, 999, 999], 320, 300) == (0, 0, 319, 299)  # bornée à l'image
    for bad in ([1, 2, 3], "0,0,10,10", [10, 10, 12, 12]):
        with pytest.raises(ValueError):
            check_box(bad, 320, 300)


def test_simulation_is_used_and_said_when_weights_are_missing() -> None:
    segmenter = make_segmenter("hand", ABSENT)
    assert isinstance(segmenter, SimulatedSegmenter) and segmenter.reason
    result = segmenter(drawing(), (100, 80, 220, 220))
    assert result.simulated and result.backend == "simulation (GrabCut)" and result.score is None
    ys, xs = np.nonzero(result.mask)
    assert len(xs) > 3000 and xs.min() >= 100 and xs.max() <= 220  # la forme, et rien hors de la boîte
    assert result.mask[150, 160] == 255 and result.mask[90, 105] == 0
    with pytest.raises(ValueError):
        make_segmenter("tête", ABSENT)


def test_combine_and_overlay() -> None:
    a, b = np.zeros((10, 10), np.uint8), np.zeros((10, 10), np.uint8)
    a[1:3, 1:3], b[6:8, 6:8] = 255, 255
    both = combine([a, b])
    assert int(np.count_nonzero(both)) == 8
    shown = overlay(np.full((10, 10, 3), 200, np.uint8), both)
    assert not np.array_equal(shown[1, 1], [200, 200, 200]) and np.array_equal(shown[4, 4], [200, 200, 200])


def test_module_segments_in_simulation_and_writes_files(tmp_path: Path) -> None:
    source = tmp_path / "planche.png"
    write_png(source, drawing())
    module = MangaStudioModule(load_manifest(STUDIO), ABSENT)
    sent: list[Event] = []
    module.publish = sent.append  # type: ignore[method-assign]
    module.start()
    module.handle_event(Event("module.mangastudio.cmd.segment", {
        "request_id": "r1", "input": str(source), "target": "hand", "boxes": [[100, 80, 220, 220]],
        "output_dir": str(tmp_path / "sorties")}))
    reply = sent[-1].payload
    assert reply["ok"] and reply["request_id"] == "r1", reply
    result = reply["result"]
    assert result["simulated"] and ("introuvables" in result["reason"] or "absentes" in result["reason"])
    assert read_rgb(Path(result["preview"])).shape == (300, 320, 3)
    assert cv2.imdecode(np.fromfile(result["mask"], np.uint8), cv2.IMREAD_GRAYSCALE).max() == 255
    module.handle_event(Event("module.mangastudio.cmd.segment", {"request_id": "r2", "input": str(source),
                                                                 "boxes": []}))
    assert sent[-1].payload["ok"] is False and "boîte" in sent[-1].payload["error"]
    module.handle_event(Event("module.mangastudio.cmd.status", {"request_id": "r3"}))
    assert sent[-1].payload["result"]["simulation"] is True
    assert module.health().degraded is True
    module.stop()


def test_status_reports_models(tmp_path: Path) -> None:
    weights = tmp_path / "hand.safetensors"
    weights.write_bytes(b"x")
    state = status({"handsegnet_weights": str(weights), "footsegnet_weights": "absent.safetensors"})
    assert state["models"]["hand"]["present"] is True and state["models"]["foot"]["present"] is False
    assert state["models"]["hand"]["ready"] is (not missing_dependencies())


def test_grounding_prepare_and_parse() -> None:
    from modules.mangastudio import grounding

    data, sx, sy = grounding.prepare(np.zeros((451, 443, 3), np.uint8))
    assert data and sx == pytest.approx(443 / 980) and sy == pytest.approx(451 / 1008)  # mesuré en réel
    text = '```json\n[{"bbox_2d": [456, 275, 527, 335], "label": "hand"}, {"bbox_2d": [1, 2, 3]}, "x"]\n```'
    boxes = grounding.parse_boxes(text, sx, sy, 443, 451)
    assert len(boxes) == 1
    x1, y1, x2, y2 = boxes[0]
    assert 200 <= x1 < 206 and 116 <= y1 < 124 and 236 < x2 <= 242 and 148 < y2 <= 154  # échelle + 12 % de marge
    assert grounding.parse_boxes("[]", 1, 1, 10, 10) == [] and grounding.parse_boxes("rien", 1, 1, 10, 10) == []
    assert grounding.parse_boxes('[{"bbox_2d": [5000, 5000, 6000, 6000]}]', 1, 1, 100, 100) == []  # hors image


def test_grounding_detect_uses_the_hub_router() -> None:
    from modules.mangastudio import grounding

    calls = []

    def chat(messages, model, num_ctx, options):
        calls.append((messages, model, num_ctx, options))
        return {"content": '[{"bbox_2d": [100, 100, 300, 300], "label": "hand"}]'}

    boxes = grounding.detect(drawing(), "foot", chat)
    assert len(boxes) == 1 and calls[0][1] == "qwen2.5vl:7b" and calls[0][2] == 4096
    assert "foot or shoe" in calls[0][0][0]["content"] and calls[0][0][0]["images"]
    with pytest.raises(ValueError):
        grounding.detect(drawing(), "tête", chat)


def load_nodes_standalone():
    """Charge le dossier des nœuds comme le ferait ComfyUI : seul, sans le reste d'AetherTwin."""
    spec = importlib.util.spec_from_file_location("aethertwin_segnet", STUDIO / "comfyui_nodes" / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_comfyui_nodes_load_and_declare_their_signature() -> None:
    nodes = load_nodes_standalone()
    assert set(nodes.NODE_CLASS_MAPPINGS) == {"AetherTwinHandSegNet", "AetherTwinFootSegNet"}
    assert set(nodes.NODE_DISPLAY_NAME_MAPPINGS) == set(nodes.NODE_CLASS_MAPPINGS)
    for cls in nodes.NODE_CLASS_MAPPINGS.values():
        spec = cls.INPUT_TYPES()
        assert spec["required"]["image"] == ("IMAGE",)
        assert all(spec["required"][k][0] == "INT" for k in ("x1", "y1", "x2", "y2"))
        assert cls.RETURN_TYPES == ("MASK",) and callable(getattr(cls(), cls.FUNCTION))
    source = (STUDIO / "comfyui_nodes" / "__init__.py").read_text(encoding="utf-8")
    assert "from modules" not in source and "import core" not in source  # dossier autonome


def test_continuity_workflow_structure() -> None:
    workflow = json.loads((STUDIO / "workflows" / "continuity.json").read_text(encoding="utf-8"))
    types = {node["class_type"] for node in workflow.values()}
    for needed in ("IPAdapterUnifiedLoader", "IPAdapter", "ControlNetLoader", "ControlNetApplyAdvanced",
                   "KSampler", "AetherTwinHandSegNet", "SaveImage"):
        assert needed in types
    for node_id, node in workflow.items():
        for value in node["inputs"].values():
            if isinstance(value, list):  # lien [nœud, sortie] vers un nœud existant
                assert value[0] in workflow and isinstance(value[1], int), (node_id, value)
    assert "AetherTwinHandSegNet" in load_nodes_standalone().NODE_CLASS_MAPPINGS


@pytest.mark.skipif(os.environ.get("AETHERTWIN_REAL_OLLAMA") != "1" or bool(missing_dependencies())
                    or not (ROOT / "models" / "mangastudio" / "handsegnet_vit_b_best.safetensors").is_file(),
                    reason="test réel sur GPU : AETHERTWIN_REAL_OLLAMA=1, torch et poids requis")
def test_real_handsegnet_through_the_comfyui_node() -> None:
    import torch

    nodes = load_nodes_standalone()
    image = torch.from_numpy(drawing().astype("float32") / 255.0)[None]
    weights = str(ROOT / "models" / "mangastudio" / "handsegnet_vit_b_best.safetensors")
    (mask,) = nodes.HandSegNetMask().segment(image, 100, 80, 220, 220, weights)
    print("pixels du masque :", int(mask.sum()), file=sys.stderr)
    assert mask.shape == (1, 300, 320) and float(mask.max()) in (0.0, 1.0)
