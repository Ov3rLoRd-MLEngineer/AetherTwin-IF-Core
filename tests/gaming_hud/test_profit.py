"""Rentabilité des recettes et décors du logis : calcul, onglets (sans texte coupé) et outils de Hermes."""
import json
import os
from pathlib import Path

RECIPES = {"Alchimie": {"updated": 1, "list": [
    {"id": 1, "name": "Potion de soins", "out": 100, "outQty": 2,
     "mats": [{"ids": [10, 11], "quantity": 3, "name": "Herbe"}, {"ids": [12], "quantity": 1, "name": "Fiole"}]},
    {"id": 2, "name": "Flacon perdant", "out": 101, "outQty": 1,
     "mats": [{"ids": [10], "quantity": 10, "name": "Herbe"}]},
    {"id": 3, "name": "Élixir rare", "out": 102, "mats": [{"ids": [13], "quantity": 1, "name": "Fleur introuvable"}]},
    {"id": 4, "name": "Ancienne recette", "mats": [{"ids": [10], "quantity": 1, "name": "Herbe"}]},
]}}
PRICES = {10: 500, 11: 300, 12: 100, 100: 2000, 101: 1000, 102: 9000}


class FakeMarket:
    def estimate(self, item_id):
        return (PRICES[item_id], "TSM") if item_id in PRICES else (None, None)


def _recipes():
    from craft import CraftSystem
    craft = CraftSystem()
    craft.load_game_recipes(RECIPES)
    return craft


def test_ranking_costs_sale_and_missing_prices() -> None:
    import profit
    rows = profit.ranking(_recipes().recipes, FakeMarket())
    assert [r["name"] for r in rows] == ["Potion de soins", "Flacon perdant", "Élixir rare"]   # sans « out » : écartée
    potion, loser, rare = rows
    assert potion["cost"] == 3 * 300 + 100 and potion["value"] == int(2000 * 2 * 0.95)
    assert potion["profit"] == potion["value"] - 1000
    assert loser["profit"] == 950 - 5000 and rare["profit"] is None and rare["missing"] == ["Fleur introuvable"]
    text = profit.describe(rows, str)
    assert "bénéfice -4050" in text and "non chiffrable (composants sans prix : Fleur introuvable)" in text


def test_market_profit_view_and_decor_collection_render(app, tmp_path) -> None:
    from addon_data import Market

    from config import WoWConfig
    app.test_ctx.craft.load_game_recipes(RECIPES)
    app.market = Market(WoWConfig.WOW_PATH, getattr(app.test_ctx.character, "realm", "") or "")
    app.market.set_bnet({k: {"market": v, "min": v, "quantity": 5} for k, v in PRICES.items()})
    app.state["market_job"] = {"busy": False, "note": "", "ok": True}
    app.active_tab = app.TABS.index("Hôtel des ventes")
    app.state["market_view"] = "craft"
    shots = os.environ.get("AETHERTWIN_SHOTS")
    for _ in range(2):
        app.screen.cut.clear()
        app.draw(app.test_ctx)
    assert app.screen.cut == [] and app.market.bnet          # pas de relecture qui effacerait les prix
    if shots:
        import pygame
        Path(shots).mkdir(parents=True, exist_ok=True)
        pygame.image.save(app.screen, os.path.join(shots, "market_profit.png"))

    app.active_tab = app.TABS.index("Collections du bataillon")
    app.state["collection"] = "decor"
    app.test_ctx.data.decor = {"updated": 1, "owned": 0, "exempt": 0, "max": 0, "list": []}
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    app.test_ctx.data.decor = {"updated": 1, "owned": 2, "exempt": 0, "max": 5000, "list": [
        {"id": 245001, "name": "Lanterne de la Lune", "stored": 1, "placed": 2, "quality": 3, "redeemable": 0,
         "source": "Vendeur : Marchand du logis", "record": 77},
        {"id": 0, "name": "Tapis sans objet", "stored": 0, "placed": 1, "quality": 1, "redeemable": 1,
         "source": "", "record": 78}]}
    for _ in range(2):
        app.screen.cut.clear()
        app.draw(app.test_ctx)
    assert app.screen.cut == []
    if shots:
        import pygame
        pygame.image.save(app.screen, os.path.join(shots, "decor_collection.png"))


def test_hermes_reads_decor_and_profit() -> None:
    import hermes_mcp

    class Game:
        def snapshot(self):
            return {"professions": [{"name": "Alchimie", "level": 50, "max": 100}], "recipes": RECIPES,
                    "decor": {"owned": 2, "max": 5000, "list": [{"name": "Lanterne de la Lune", "stored": 1,
                                                                  "placed": 2}]}}

        def market(self):
            return FakeMarket()

    def call(name, args):
        return json.loads(hermes_mcp.call_tool(Game(), name, args)["content"][0]["text"])

    decor = call("wow_collections", {"kind": "decor"})["décors_du_logis"]
    assert decor["possédés"] == 2 and decor["résultats"][0]["placés"] == 2
    out = call("wow_professions", {"rentabilite": True})
    assert out["rentabilité"][0]["recette"] == "Potion de soins" and out["rentabilité"][2]["bénéfice"] is None
    assert "rentabilité" not in call("wow_professions", {})
