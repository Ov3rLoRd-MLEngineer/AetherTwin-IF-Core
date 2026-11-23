"""Points de route : repérés dans les réponses, copiés d'un clic, donnés par les quêtes."""


def test_extract_ha_and_tomtom_commands() -> None:
    import waypoints
    text = ("Va voir **Marshal Dughan** : /ha way 42,1 65,9 (Comté-de-l'Or).\n"
            "Puis le PNJ à Valdrakken : /way #2112 58.2 35.1 Maître de vol\n"
            "Doublon : /ha way 42.1 65.9\nHors carte : /ha way 120 5")
    found = waypoints.extract(text)
    assert [w["cmd"] for w in found] == ["/ha way 42.1 65.9", "/ha way 2112 58.2 35.1"]
    assert found[0]["label"] == "Comté-de-l'Or" and found[1]["label"] == "Maître de vol"
    assert waypoints.quest_way({"name": "Loups", "way": {"map": 37, "x": 45.4, "y": 60.1}})["cmd"] == \
        "/ha way 37 45.4 60.1"
    assert waypoints.quest_way({"name": "Sans"}) is None


def test_hermes_answer_shows_copyable_waypoints(app, monkeypatch) -> None:
    import clipboard
    app.settings.set("llm.mode", "hermes")
    app.active_tab = app.TABS.index("Hermes")
    app.chat.messages = [{"role": "user", "text": "Où aller ?"},
                         {"role": "assistant", "text": "Rends la quête : /ha way 42.1 65.9 (Marshal Dughan)."}]
    app.draw(app.test_ctx)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    copied = []
    monkeypatch.setattr(clipboard, "set_text", copied.append)
    import waypoints
    waypoints.copy(app, waypoints.extract(app.chat.messages[-1]["text"])[0])
    assert copied == ["/ha way 42.1 65.9"]


def test_quest_detail_offers_its_waypoint(app) -> None:
    app.test_ctx.quests.load_from_dict({"list": [{"id": 10, "title": "Loups", "status": "incomplete", "level": 5,
                                                  "zone": "Elwynn", "way": {"map": 37, "x": 45.4, "y": 60.1,
                                                                            "zone": "Forêt d'Elwynn"}}]})
    app.active_tab = app.TABS.index("Journal des quêtes")
    app.draw(app.test_ctx)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    assert any(r.w == 170 and r.h == 26 for r, _fn in app._buttons)
