"""Vue 3D facultative : relais local de la visionneuse de Wowhead, modèles Battle.net, essayage, incrustation."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import model3d
import pytest


class FakeBnet:
    """Réponses Battle.net minimales : un personnage (2 objets visibles + un anneau caché) et leurs apparences."""

    def get(self, path, namespace, max_age=0):
        if path.endswith("/appearance"):
            assert path == "/profile/wow/character/ysondre/aeliana/appearance"
            return {"playable_race": {"id": 4}, "gender": {"type": "FEMALE"},
                    "customizations": [{"option": {"id": 49}, "choice": {"id": 807}}],
                    "items": [{"id": 10, "slot": {"type": "HEAD"}}, {"id": 11, "slot": {"type": "CHEST"}},
                              {"id": 12, "slot": {"type": "FINGER_1"}}]}
        if path.startswith("/data/wow/item/"):
            n = int(path.rsplit("/", 1)[1])
            return {"appearances": [{"id": 100 + n}]}
        if path.startswith("/data/wow/item-appearance/"):
            n = int(path.rsplit("/", 1)[1]) - 100
            kind = {10: "HEAD", 11: "CHEST", 20: "ROBE"}.get(n, "HEAD")
            return {"slot": {"type": kind}, "item_display_info_id": 5000 + n}
        if path.startswith("/data/wow/creature/"):
            return {"creature_displays": [{"id": 777}]}
        raise AssertionError(path)


def test_character_model_and_try_on() -> None:
    m = model3d.character_model(FakeBnet(), "Ysondre", "Aeliana")
    assert m["race"] == 4 and m["gender"] == 1 and m["options"] == [{"optionId": 49, "choiceId": 807}]
    assert m["items"] == [[1, 5010], [5, 5011]]           # l'anneau n'a pas de modèle : ignoré
    robe = model3d.appearance_display(FakeBnet(), 20)
    assert robe == (20, 5020)
    tried = model3d.try_on(m, [robe])
    assert [1, 5010] in tried["items"] and [20, 5020] in tried["items"]
    assert [5, 5011] not in tried["items"]                # la robe remplace le torse
    assert m["items"] == [[1, 5010], [5, 5011]]           # le modèle d'origine n'est pas modifié
    assert model3d.creature_model(FakeBnet(), 30, "Araignée") == {"kind": "model", "id": 777, "type": 8,
                                                                    "caption": "Araignée"}


def test_scaled_window_coordinates() -> None:
    assert model3d.scale_rect((1620, 860), (1620, 860), (600, 120, 420, 560)) == (600, 120, 420, 560)
    # fenêtre agrandie : mise à l'échelle × 1.5, bandes noires à gauche et à droite
    assert model3d.scale_rect((2700, 1290), (1620, 860), (0, 0, 100, 100)) == (135, 0, 150, 150)
    assert model3d.scale_rect((0, 0), (1620, 860), (0, 0, 10, 10)) is None   # fenêtre réduite


def test_relay_serves_page_model_and_only_wowhead_viewer_files(tmp_path: Path) -> None:
    asked = []

    def opener(request, timeout=30):
        asked.append(request.full_url)
        if request.full_url.endswith("missing.js"):
            raise urllib.error.HTTPError(request.full_url, 404, "absent", {}, io.BytesIO(b""))
        return io.BytesIO(b"// js")

    viewer = model3d.Viewer3D(str(tmp_path / "cache"), opener=opener)
    try:
        base = viewer.url().rsplit("/", 1)[0]
        assert base.startswith("http://127.0.0.1:")

        def fetch(path):
            try:
                with urllib.request.urlopen(base + "/" + path, timeout=5) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, b""

        status, page = fetch("viewer.html")
        assert status == 200 and b"ZamModelViewer" in page
        viewer.show({"kind": "model", "id": 777, "type": 8})
        status, body = fetch("model.json")
        assert status == 200 and json.loads(body)["id"] == 777 and json.loads(body)["version"] == 1
        assert fetch("zam/modelviewer/live/viewer/viewer.min.js") == (200, b"// js")
        assert fetch("zam/modelviewer/live/viewer/viewer.min.js") == (200, b"// js")   # 2e fois : cache disque
        assert asked == ["https://wow.zamimg.com/modelviewer/live/viewer/viewer.min.js"]
        assert fetch("zam/modelviewer/live/missing.js")[0] == 404
        assert fetch("zam/images/wow/icons/large/x.jpg")[0] == 403      # hors de la visionneuse : refusé
        assert fetch("zam/modelviewer/live/../../secret")[0] in (403, 404)
        assert fetch("settings.json")[0] == 404
        assert viewer.server.server_address[0] == "127.0.0.1"
    finally:
        viewer.close()


def test_embedding_hides_without_a_frame_and_reports_errors(tmp_path: Path) -> None:
    viewer = model3d.Viewer3D(str(tmp_path))
    assert viewer.embed(None, (0, 0, 10, 10)) is False and viewer.proc is None    # pas de fenêtre parente
    assert viewer.embed(123, None) is False and viewer.proc is None              # rien à montrer : pas de processus
    viewer.error = "test"
    assert viewer.embed(123, (0, 0, 10, 10)) is False and viewer.proc is None
    viewer.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_preview_boxes_register_the_embedded_view(app, enabled) -> None:
    class FakeViewer:
        error = ""

        def can_embed(self):
            return True

        def window_open(self):
            return False

        def embed(self, parent, rect):
            self.rect = rect
            return rect is not None

        def show(self, model):
            self.model = model

    class Media:
        bnet = FakeBnet()

        def available(self):
            return True

        def request(self, key, loader):
            pass

        def value(self, key):
            return {"kind": "model", "id": 1, "type": 8} if key.startswith("3d:") else None

        def state(self, key):
            return "prête"

    app.viewer3d = FakeViewer()
    app.media = Media()
    app._can_embed = True
    app._main_hwnd = lambda: 42
    app.settings.set("model3d.enabled", enabled)
    app.media_view = lambda *a, **k: True
    app.view3d_box((100, 100, 300, 400), "npc:1", lambda: None)
    assert (app._embed is not None) is enabled
    if enabled:
        assert app._embed.top == 100 + app.VIEW3D_STRIP          # le bandeau (aide, bouton Image) reste visible
        app.state["view3d_flat"] = True                          # « Image » : la vue 3D se masque
        app._embed = None
        app.view3d_box((100, 100, 300, 400), "npc:1", lambda: None)
        assert app._embed is None
