"""Version WoW Forever : fonctions absentes cachées (Mythique+, Chambre forte, logis, Raidbots), Questie lu par
l'addon, et Hermes prévenu de la variante."""
import json
import os
from pathlib import Path


def test_features_by_flavor(tmp_path) -> None:
    import features
    forever, retail = str(tmp_path / "_forever_"), str(tmp_path / "_retail_")
    assert features.flavor(forever) == "forever" and features.label(forever) == "WoW Forever"
    assert not features.has("mythicplus", forever) and not features.has("housing", forever)
    assert features.has("mythicplus", retail) and features.coach_note(retail) == ""
    assert "Mythique+" in features.coach_note(forever)


def test_forever_hides_absent_features(app, tmp_path, monkeypatch) -> None:
    from config import WoWConfig
    monkeypatch.setattr(WoWConfig, "WOW_PATH", str(tmp_path / "_forever_"))
    shots = os.environ.get("AETHERTWIN_SHOTS")
    clicked = []
    monkeypatch.setattr(app, "copy_simc_profile", lambda: clicked.append(1))
    for tab in ("Personnage", "Instances et Chambre", "Collections du bataillon"):
        app.active_tab = app.TABS.index(tab)
        app.state["collection"] = "decor"
        for _ in range(2):
            app.screen.cut.clear()
            app.draw(app.test_ctx)
        assert app.screen.cut == []
        if shots:
            import pygame
            Path(shots).mkdir(parents=True, exist_ok=True)
            pygame.image.save(app.screen, os.path.join(shots, f"forever_{app.active_tab}.png"))
    assert app.state["collection"] != "decor"                   # pas de logis sur Forever
    app.active_tab = 0
    app.draw(app.test_ctx)
    assert not any("Raidbots" in str(getattr(t, "get", lambda k, d=None: d)("rows", "")) for _r, t in app._tips)


def test_hermes_is_told_the_flavor(tmp_path) -> None:
    import hermes_mcp
    folder = tmp_path / "_forever_"
    folder.mkdir()

    class Game:
        def snapshot(self):
            return {"character": {"name": "Sakura"}, "quests": {"questie": "12.9.0", "list": [
                {"title": "Loups", "id": 10, "status": "complete",
                 "questie": {"finisher": "Marshal Dughan", "required": 5}}]}}

        def source(self):
            return "test"

        def _game_path(self):
            return str(folder)

    status = json.loads(hermes_mcp.call_tool(Game(), "wow_status", {})["content"][0]["text"])
    assert "WoW Forever" in status["variante"]
    quests = json.loads(hermes_mcp.call_tool(Game(), "wow_quests", {})["content"][0]["text"])
    assert "Questie 12.9.0" in quests["questie"]
    assert quests["liste"][0]["questie"] == {"à_rendre_à": "Marshal Dughan", "niveau_requis": 5}
