"""WoW Assistant : API Battle.net (serveur factice), addons existants (fichiers factices au format de TSM et
d'Auctionator), synthèse des prix. Aucun accès réseau, aucun fichier du jeu modifié."""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import addon_data
import bnet
import pygame
import pytest


# --------------------------------------------------------------------------- faux jeu
def make_wow(tmp_path: Path) -> Path:
    wow = tmp_path / "_retail_"
    addons = wow / "Interface" / "AddOns"
    for folder, toc in {
        "Auctionator": ("## Title: |cff00ff00Auctionator|r\n## Version: 300.1\n"
                        "## SavedVariables: AUCTIONATOR_PRICE_DATABASE, AUCTIONATOR_CONFIG\n"),
        "TradeSkillMaster_AppHelper": "## Title: TSM AppHelper\n## Version: 4.14\n",
        "Details": "## Title: Details! Damage Meter\n## SavedVariablesPerCharacter: _detalhes_database\n",
    }.items():
        (addons / folder).mkdir(parents=True)
        (addons / folder / f"{folder}.toc").write_text(toc, encoding="utf-8")
    (addons / "TradeSkillMaster_AppHelper" / "AppData.lua").write_text(
        'select(2, ...).LoadData("AUCTIONDB_REGION_STAT","EU",[[return {downloadTime=1700000000,'
        'fields={"itemString","regionMarketValue","regionSoldPerDay"},data={{"i:2589",900,42},{"i:2770",150,10}}}]])'
        ' --<AUCTIONDB_REGION_STAT,EU,1700000000>\n'
        'select(2, ...).LoadData("AUCTIONDB_NON_COMMODITY_DATA","EU-Ysondre",[[return {downloadTime=1700003600,'
        'fields={"itemString","minBuyout","numAuctions","marketValueRecent"},data={{"i:2589",700,5,800},'
        '{"i:19019:1:2",123456789,1,120000000},{"bizarre",1,1,1}}}]])\n'
        'select(2, ...).LoadData("APP_INFO","Global",[[return {version=41}]])\n', encoding="utf-8")
    sv = wow / "WTF" / "Account" / "COMPTE" / "SavedVariables"
    sv.mkdir(parents=True)
    (sv / "Auctionator.lua").write_text(
        'AUCTIONATOR_PRICE_DATABASE = {\n ["__dbversion"] = 6,\n ["Ysondre"] = {\n'
        '  ["2589"] = { ["m"] = 650, ["h"] = { [20000] = 700, [20001] = 650 } },\n'
        '  ["2589:0:0"] = { ["m"] = 900 },\n  ["12345"] = { ["m"] = 0 },\n'
        '  ["g:999"] = "pas une table",\n },\n}\n', encoding="utf-8")
    (sv / "Blizzard_Console.lua").write_text("x = 1\n", encoding="utf-8")
    char = wow / "WTF" / "Account" / "COMPTE" / "Ysondre" / "Aeliana" / "SavedVariables"
    char.mkdir(parents=True)
    (char / "Details.lua").write_text(
        '_detalhes_database = { ["tabela_historico"] = { ["x"] = 1 }, ["ativo"] = true }\n', encoding="utf-8")
    return wow


def test_installed_addons_and_their_saved_data(tmp_path: Path) -> None:
    wow = make_wow(tmp_path)
    addons = {a["folder"]: a for a in addon_data.installed_addons(str(wow))}
    assert addons["Auctionator"]["title"] == "Auctionator"  # codes couleur du jeu retirés
    assert addons["Auctionator"]["saved"] == ["AUCTIONATOR_PRICE_DATABASE", "AUCTIONATOR_CONFIG"]
    assert addons["Details"]["saved"] == ["_detalhes_database"]
    files = addon_data.saved_variable_files(str(wow))
    assert [(f["addon"], f["scope"]) for f in files] == [("Auctionator", "compte"), ("Details", "Ysondre / Aeliana")]
    data = addon_data.load_saved_variables(files[1]["path"])
    rows = addon_data.tree_rows(data["_detalhes_database"], prefix="_detalhes_database")
    assert rows[0] == (0, "_detalhes_database", "{2 entrées}") and (1, "ativo", "True") in rows


def test_tsm_prices_prefer_the_character_realm(tmp_path: Path) -> None:
    prices, when = addon_data.tsm_prices(str(make_wow(tmp_path)), realm="Ysondre")
    assert when == 1700003600
    assert prices[2589]["marketValueRecent"] == 800 and prices[2589]["regionMarketValue"] == 900
    assert prices[19019]["minBuyout"] == 123456789
    assert 2770 in prices  # présent seulement dans les données de région
    assert addon_data.tsm_prices(str(tmp_path / "absent")) == ({}, None)


def test_auctionator_prices_with_history(tmp_path: Path) -> None:
    prices, when = addon_data.auctionator_prices(str(make_wow(tmp_path)), realm="Ysondre")
    assert prices[2589] == {"price": 650, "history": [(20000, 700), (20001, 650)]}  # la variante la moins chère
    assert 12345 not in prices and when


def test_market_combines_sources_and_values_bags(tmp_path: Path) -> None:
    market = addon_data.Market(str(make_wow(tmp_path)), "Ysondre").reload()
    assert market.estimate(2589) == (800, "TSM")
    market.set_bnet({2589: {"min": 500, "market": 520, "quantity": 300, "listings": 12}})
    assert market.estimate(2589) == (520, "Battle.net")
    assert market.estimate(424242) == (None, None)
    total, rows = market.value_of([{"id": 2589, "quantity": 10}, {"id": 2770, "count": 3}, {"id": 1}])
    assert total == 5200 + 450 and rows[0][1:] == (520, 5200, "Battle.net") and rows[-1][1] is None
    assert [name for name, *_ in market.sources()] == ["Battle.net (HdV officiel)", "TradeSkillMaster", "Auctionator"]


def test_market_summary_ignores_outliers() -> None:
    summary = bnet.market_summary([(100, 10), (110, 10), (120, 50), (5000, 1), (0, 4)])
    assert summary["min"] == 100 and summary["quantity"] == 71 and summary["listings"] == 4
    assert summary["market"] == 100  # 15 % de 71 = 10 unités, toutes au prix le plus bas
    assert bnet.market_summary([]) is None
    assert bnet.realm_slug("Marécage de Zangar") == "marecage-de-zangar"
    assert bnet.realm_slug("Kael'thas") == "kaelthas"


# --------------------------------------------------------------------------- faux Battle.net
class FakeBnet:
    """Imite oauth.battle.net et eu.api.blizzard.com (réponses fixes) et note les URL demandées."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.reject = False

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.urls.append(url)
        if "oauth.battle.net" in url:
            if self.reject:
                raise urllib.error.HTTPError(url, 401, "refusé", {}, None)
            assert request.get_header("Authorization").startswith("Basic ")
            return self.reply({"access_token": "jeton", "expires_in": 86399})
        assert request.get_header("Authorization") in ("Bearer jeton", None)
        if "render.worldofwarcraft.com" in url:
            return io.BytesIO(b"\x89PNG image")
        if "/realm/index" in url:
            return self.reply({"realms": [{"name": "Marécage de Zangar", "slug": "marecage-de-zangar"}]})
        if "/data/wow/realm/marecage-de-zangar" in url:
            return self.reply({"connected_realm": {"href": "https://eu.api.blizzard.com/data/wow/connected-realm/1390?x"}})
        if "/character-media" in url:
            assert "/profile/wow/character/marecage-de-zangar/aeliana/" in url and "namespace=profile-eu" in url
            return self.reply({"assets": [{"key": "avatar", "value": "https://render.worldofwarcraft.com/eu/a.jpg"},
                                          {"key": "main-raw", "value": "https://render.worldofwarcraft.com/eu/m.png"}]})
        if "/data/wow/mount/6" in url:
            return self.reply({"creature_displays": [{"id": 2404}]})
        if "/creature-display/2404" in url:
            return self.reply({"assets": [{"key": "zoom", "value": "https://render.worldofwarcraft.com/eu/z.jpg"}]})
        if "/auctions/commodities" in url:
            return self.reply({"auctions": [{"item": {"id": 2589}, "quantity": 20, "unit_price": 500},
                                            {"item": {"id": 2589}, "quantity": 5, "unit_price": 480}]})
        if "/connected-realm/1390/auctions" in url:
            return self.reply({"auctions": [
                {"item": {"id": 19019, "bonus_lists": [1]}, "quantity": 1, "buyout": 9000000},
                {"item": {"id": 19019}, "quantity": 2, "buyout": 10000000}]})
        raise urllib.error.HTTPError(url, 404, "inconnu", {}, None)

    @staticmethod
    def reply(data):
        return io.BytesIO(json.dumps(data).encode("utf-8"))


class Settings(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def client(tmp_path: Path, fake: FakeBnet) -> bnet.BattleNet:
    settings = Settings({"bnet.client_id": "id", "bnet.client_secret": "secret", "bnet.region": "eu"})
    return bnet.BattleNet(settings, str(tmp_path / "cache"), opener=fake)


def test_battle_net_character_render_and_mount_image(tmp_path: Path) -> None:
    fake = FakeBnet()
    api = client(tmp_path, fake)
    path = api.character_render("Marécage de Zangar", "Aeliana")
    assert path.endswith("main-raw.png") and Path(path).read_bytes() == b"\x89PNG image"
    calls = len(fake.urls)
    assert api.character_render("Marécage de Zangar", "Aeliana") == path and len(fake.urls) == calls  # cache
    assert Path(api.mount_image(6)).is_file()
    assert sum("oauth" in u for u in fake.urls) == 1  # un seul jeton pour toutes les requêtes


def test_battle_net_auction_prices(tmp_path: Path) -> None:
    api = client(tmp_path, FakeBnet())
    commodities = api.commodities()
    assert commodities[2589]["min"] == 480 and commodities[2589]["quantity"] == 25
    realm = api.realm_auctions("Marécage de Zangar")
    assert realm[19019]["min"] == 5000000  # 10 000 000 pour 2 : ramené à l'unité


def test_battle_net_refuses_bad_credentials_and_foreign_media(tmp_path: Path) -> None:
    fake = FakeBnet()
    fake.reject = True
    with pytest.raises(bnet.BnetError, match="refusés"):
        client(tmp_path, fake).commodities()
    unset = bnet.BattleNet(Settings(), str(tmp_path / "c"), opener=fake)
    assert not unset.configured()
    with pytest.raises(bnet.BnetError, match="non renseignés"):
        unset.token()
    with pytest.raises(bnet.BnetError, match="inattendue"):
        client(tmp_path, FakeBnet()).download("https://exemple.com/x.png", "x")


# --------------------------------------------------------------------------- onglet Hôtel des ventes
def test_market_tab_renders_every_view(app, tmp_path: Path, monkeypatch) -> None:
    """L'onglet s'affiche sur un faux jeu (prix TSM et Auctionator, données d'addons), sans rien couper."""
    import os
    import time as time_mod

    from inventory import Inventory

    from config import WoWConfig

    wow = make_wow(tmp_path)
    monkeypatch.setattr(WoWConfig, "WOW_PATH", str(wow))
    inventory = Inventory()
    inventory.items = [{"id": 2589, "name": "Étoffe de lin", "quantity": 20, "quality": 1, "type": "Artisanat"},
                       {"id": 19019, "name": "Thunderfury", "quantity": 1, "quality": 5, "type": "Arme"},
                       {"id": 7, "name": "Caillou", "quantity": 3, "quality": 0, "type": "Divers"}]
    app.test_ctx.inventory = inventory
    app.test_ctx.character.realm = "Ysondre"
    app.active_tab = app.TABS.index("Hôtel des ventes")
    app.draw(app.test_ctx)
    for _ in range(50):  # lecture des prix en arrière-plan
        if not app.state["market_job"]["busy"]:
            break
        time_mod.sleep(0.05)
    shots = os.environ.get("AETHERTWIN_SHOTS")
    for view in ("value", "banks", "search", "addons"):
        app.state["market_view"] = view
        if view == "search":
            app.inputs["market_search"] = "lin"
        app.screen.cut.clear()
        app.draw(app.test_ctx)
        if view == "addons":
            state = app.state["addons"]
            _open = next(f for f in state["files"] if f["addon"] == "Details")
            from tabs_market import _open_file
            _open_file(app, state, _open)
            for _ in range(50):
                if not state["busy"]:
                    break
                time_mod.sleep(0.05)
            assert state["rows"] and state["rows"][0][1] == "_detalhes_database"
            app.draw(app.test_ctx)
        assert app.screen.cut == [], view
        if shots:
            pygame.image.save(app.screen, str(Path(shots) / f"market_{view}.png"))
    total, rows = app.market.value_of(inventory.items)
    assert total == 800 * 20 + 120000000 and rows[-1][1] is None  # TSM : valeur du royaume, puis prix minimum

def test_mythic_plus_from_the_addon_to_the_instances_tab(app, tmp_path: Path) -> None:
    import os

    from game_connection import _normalize_mythic

    raw = {"score": 2735, "keystone": {"mapID": 502, "name": "Prieuré de la Flamme sacrée", "level": 12},
           "dungeons": {1: {"name": "Cavernes", "level": 11, "score": 310, "inTime": True},
                        2: {"name": "Prieuré de la Flamme sacrée", "level": 10, "score": 280, "inTime": False},
                        3: {"name": "Cité des fils", "level": 0, "score": 0}},
           "week": {1: {"name": "Cavernes", "level": 11, "completed": True}}}
    mp = _normalize_mythic(raw)
    assert mp["keystone"] == {"name": "Prieuré de la Flamme sacrée", "level": 12} and len(mp["dungeons"]) == 3
    assert _normalize_mythic(None) == {"score": 0, "keystone": None, "dungeons": [], "week": []}
    app.test_ctx.data.mythicPlus = mp
    app.active_tab = app.TABS.index("Instances et Chambre")
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    if os.environ.get("AETHERTWIN_SHOTS"):
        pygame.image.save(app.screen, str(Path(os.environ["AETHERTWIN_SHOTS"]) / "instances_mythic.png"))

def test_character_render_replaces_the_silhouette(app, tmp_path: Path) -> None:
    """Avec l'API Battle.net branchée, l'onglet Personnage montre le rendu officiel (ici une image factice)."""
    import os
    import time as time_mod

    from media import MediaStore

    image = pygame.Surface((300, 600), pygame.SRCALPHA)
    pygame.draw.ellipse(image, (200, 160, 90), (60, 20, 180, 560))
    path = tmp_path / "render.png"
    pygame.image.save(image, str(path))

    class FakeApi:
        def configured(self):
            return True

        def character_render(self, realm, name):
            assert (realm, name) == ("Ysondre", "Aeliana")
            return str(path)

    app.media = MediaStore(FakeApi())
    app.test_ctx.character.realm = "Ysondre"
    app.active_tab = 0
    app.draw(app.test_ctx)
    for _ in range(40):
        if app.media.state("char:Ysondre:Aeliana") == "prête":
            break
        time_mod.sleep(0.05)
    app.draw(app.test_ctx)
    assert app.media.surface("char:Ysondre:Aeliana") is not None
    if os.environ.get("AETHERTWIN_SHOTS"):
        pygame.image.save(app.screen, str(Path(os.environ["AETHERTWIN_SHOTS"]) / "character_render.png"))

    class Broken(FakeApi):
        def character_render(self, realm, name):
            raise RuntimeError("introuvable sur Battle.net")

    app.media = MediaStore(Broken())
    app.draw(app.test_ctx)
    for _ in range(40):
        if app.media.state("char:Ysondre:Aeliana") == "erreur":
            break
        time_mod.sleep(0.05)
    app.draw(app.test_ctx)  # l'erreur s'affiche à la place de l'image, sans planter
    assert "introuvable" in app.media.error("char:Ysondre:Aeliana")
