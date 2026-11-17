"""Adaptateurs de jeu : contrat commun, WoW, suivi de journal, capture d'écran, filtre de confidentialité."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from modules.gaming_hud.adapters.base import META_KEY, GameAdapter
from modules.gaming_hud.adapters.log_tail import LogTailAdapter, RulesError, parse_rules
from modules.gaming_hud.adapters.privacy import MASK, PrivacyOptions, filter_state, leaks, round_amount, scrub_text
from modules.gaming_hud.adapters.screen_ocr import ScreenOcrAdapter, extract_json
from modules.gaming_hud.adapters.wow_retail import WowRetailAdapter

# Canaris : données privées plantées dans les jeux de test. Aucune ne doit ressortir en mode Showcase.
ACCOUNT = "COMPTECANARI"
EMAIL = "secret.canari@example.com"
USER_PATH = "C:/" + "Users/ProfilCanari/Documents/notes.txt"  # assemblé : ce fichier ne contient pas de vrai chemin
API_KEY = "sk-canari-" + "0123456789abcdefABCDEF0123"
NAME, REALM, GUILD = "Canarinom", "RoyaumeCanari", "GuildeCanari"
GOLD_COPPER, GUILD_COPPER = 1234567, 98765432

SAVED_VARIABLES = f"""
HermesAssistantCharDB = {{
	["characterData"] = {{
		["name"] = "{NAME}",
		["realm"] = "{REALM}",
		["level"] = 48,
		["class"] = "Druidesse",
		["specialization"] = "Farouche",
		["zone"] = "Hurlevent",
		["ilvl"] = 17.5,
		["money"] = {GOLD_COPPER},
		["updated"] = 1700000000,
	}},
	["log"] = {{
		{{
			["kind"] = "chat",
			["text"] = "{NAME} a écrit à {EMAIL} ; fichier {USER_PATH} ; clé {API_KEY}",
		}}, -- [1]
	}},
	["guildBank"] = {{
		["guild"] = "{GUILD}",
		["money"] = {GUILD_COPPER},
	}},
	["quests"] = {{
		["count"] = 1,
		["list"] = {{
			{{
				["title"] = "Une quête pour {NAME}",
			}}, -- [1]
		}},
	}},
}}
"""


@pytest.fixture
def game_dir(tmp_path: Path) -> Path:
    saved = tmp_path / "_retail_" / "WTF" / "Account" / ACCOUNT / "SavedVariables"
    saved.mkdir(parents=True)
    (saved / "HermesAssistant.lua").write_text(SAVED_VARIABLES, encoding="utf-8")
    return tmp_path / "_retail_"


@pytest.fixture
def wow(game_dir: Path) -> WowRetailAdapter:
    return WowRetailAdapter(str(game_dir), autodetect=False)


# --------------------------------------------------------------------------- contrat commun
def test_all_adapters_satisfy_the_contract(wow: WowRetailAdapter, tmp_path: Path) -> None:
    log = LogTailAdapter({"path": str(tmp_path / "x.log"), "rules": [{"field": "a", "pattern": "a"}]})
    ocr = ScreenOcrAdapter({"fields": [{"name": "hp", "type": "int"}]}, capture=lambda: b"png",
                           vision=lambda p, i: "{}")
    for adapter in (wow, log, ocr):
        assert isinstance(adapter, GameAdapter), type(adapter).__name__
        state = adapter.read_state()
        assert state[META_KEY]["read_only"] is True and state[META_KEY]["adapter"] == adapter.id
        assert adapter.schema()["sections"] and adapter.widgets()[0]["title"]
        assert isinstance(adapter.context_for_llm(state), str)
        assert adapter.privacy_filter(state, "off") == state
        with pytest.raises(ValueError, match="confidentialité"):
            adapter.privacy_filter(state, "inconnu")


# --------------------------------------------------------------------------- WoW
def test_wow_reads_saved_variables(wow: WowRetailAdapter) -> None:
    assert wow.detect() is True
    state = wow.read_state()
    assert state["character"]["name"] == NAME and state["character"]["level"] == 48
    assert state["character"]["money"] == GOLD_COPPER and state["guildBank"]["guild"] == GUILD
    assert state[META_KEY]["has_data"] and ACCOUNT in state[META_KEY]["source_file"]
    assert wow.context_for_llm(state) == (f"Contexte joueur : {NAME}, niveau 48 Druidesse Farouche, "
                                          "zone Hurlevent, niveau d'objet 17.5.")


def test_wow_without_game_is_degraded_not_broken(tmp_path: Path) -> None:
    adapter = WowRetailAdapter(str(tmp_path / "absent"), autodetect=False)
    state = adapter.read_state()
    assert adapter.detect() is False and state[META_KEY]["has_data"] is False
    assert "inconnu" in adapter.context_for_llm(state)
    assert adapter.privacy_filter(state, "showcase")[META_KEY]["adapter"] == "wow_retail"


def test_wow_empty_section_never_overwrites_a_known_one(wow: WowRetailAdapter, game_dir: Path) -> None:
    assert wow.read_state()["quests"]["list"]
    path = game_dir / "WTF" / "Account" / ACCOUNT / "SavedVariables" / "HermesAssistant.lua"
    emptied = SAVED_VARIABLES.replace('["count"] = 1,', '["count"] = 0,').replace(
        f'{{\n\t\t\t\t["title"] = "Une quête pour {NAME}",\n\t\t\t}}, -- [1]\n', "")
    path.write_text(emptied, encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    state = wow.read_state()
    assert state["quests"]["list"], "une section vide (déconnexion, fichier en cours d'écriture) a écrasé les quêtes"


def test_wow_adapter_never_writes_into_the_game_folder(wow: WowRetailAdapter, game_dir: Path) -> None:
    before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in game_dir.rglob("*"))
    for _ in range(3):
        wow.privacy_filter(wow.read_state(), "showcase")
    assert sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in game_dir.rglob("*")) == before


def test_showcase_never_leaks_account_paths_emails_or_keys(wow: WowRetailAdapter) -> None:
    state = wow.read_state()
    shown = wow.privacy_filter(state, "showcase")
    assert leaks(shown, [ACCOUNT, EMAIL, "ProfilCanari", "notes.txt", API_KEY, "canari@"]) == []
    assert "source_file" not in shown[META_KEY]
    assert shown["character"]["name"] == NAME  # par défaut, le nom du personnage reste affiché
    assert shown["character"]["level"] == 48 and shown["character"]["zone"] == "Hurlevent"  # le reste est intact
    assert state["character"]["money"] == GOLD_COPPER and ACCOUNT in state[META_KEY]["source_file"]  # original intact


def test_showcase_rounds_gold_by_default_and_can_hide_it(wow: WowRetailAdapter, game_dir: Path) -> None:
    shown = wow.privacy_filter(wow.read_state(), "showcase")
    assert shown["character"]["money"] == 100 * 10_000  # 123 pièces d'or -> 100
    assert shown["guildBank"]["money"] == 10_000 * 10_000  # 9 876 pièces d'or -> 10 000
    assert leaks(shown, [str(GOLD_COPPER), str(GUILD_COPPER)]) == []
    hidden = WowRetailAdapter(str(game_dir), options=PrivacyOptions(gold="hide"), autodetect=False)
    assert hidden.privacy_filter(hidden.read_state(), "showcase")["character"]["money"] is None


def test_showcase_can_hide_character_names_everywhere(game_dir: Path) -> None:
    adapter = WowRetailAdapter(str(game_dir), options=PrivacyOptions(hide_character_names=True), autodetect=False)
    shown = adapter.privacy_filter(adapter.read_state(), "showcase")
    assert leaks(shown, [NAME, REALM, GUILD, ACCOUNT, EMAIL, API_KEY]) == []
    assert shown["character"]["name"] == "Aventurier"
    assert shown["quests"]["list"][0]["title"] == "Une quête pour Aventurier"  # y compris au milieu d'un texte


def test_real_game_data_if_present() -> None:
    """Lecture réelle des SavedVariables de la machine. Ignoré s'il n'y a ni jeu ni données (CI)."""
    adapter = WowRetailAdapter(options=PrivacyOptions(hide_character_names=True, gold="hide"))
    state = adapter.read_state()
    if not state[META_KEY]["has_data"]:
        pytest.skip("aucune donnée de jeu réelle sur cette machine")
    name = state["character"]["name"]
    source = Path(state[META_KEY]["source_file"])
    account = source.parts[source.parts.index("Account") + 1]
    assert name and state["character"]["level"] >= 1
    shown = adapter.privacy_filter(state, "showcase")
    assert leaks(shown, [name, account, str(source.parent), source.drive + "\\"]) == []
    assert name in adapter.context_for_llm(state)


# --------------------------------------------------------------------------- utilitaires de confidentialité
def test_scrub_text() -> None:
    text = f"mail {EMAIL}, fichier {USER_PATH}, partage \\\\serveur\\dossier, clé {API_KEY}, site https://www.wowhead.com/fr"
    cleaned = scrub_text(text)
    assert leaks(cleaned, [EMAIL, "ProfilCanari", "serveur", API_KEY]) == []
    assert "https://www.wowhead.com/fr" in cleaned  # une adresse web n'est pas un chemin de fichier
    assert scrub_text("Niveau 48 : Hurlevent, 12/35 quêtes") == "Niveau 48 : Hurlevent, 12/35 quêtes"


@pytest.mark.parametrize(("value", "unit", "expected"), [(1234567, 10_000, 1_000_000), (98765432, 10_000, 100_000_000),
                                                         (9999, 10_000, 0), (0, 1, 0), (-5, 1, 0), (149, 1, 100),
                                                         (150, 1, 200)])
def test_round_amount(value: int, unit: int, expected: int) -> None:
    assert round_amount(value, unit) == expected


def test_filter_drops_sensitive_keys_at_any_depth() -> None:
    state = {"a": {"b": [{"api_key": "x", "apiKey": "y", "password": "z", "token": "t", "email": "e",
                          "accountName": "n", "filePath": "p", "ok": 1}]}, "battleTag": "Joueur#1234"}
    assert filter_state(state, PrivacyOptions()) == {"a": {"b": [{"ok": 1}]}}


def test_privacy_options_are_validated() -> None:
    with pytest.raises(ValueError, match="gold"):
        PrivacyOptions(gold="montrer")


# --------------------------------------------------------------------------- suivi de journal
RULES = {
    "id": "demo", "game": "Jeu démo", "path": "game.log",
    "rules": [
        {"field": "zone", "pattern": r"Entering zone: (?P<value>.+)"},
        {"field": "level", "pattern": r"Now level (\d+)", "type": "int"},
        {"field": "hp", "pattern": r"HP: (?P<value>[\d.]+)%", "type": "float"},
        {"field": "deaths", "pattern": "You died", "mode": "count"},
        {"field": "loot", "pattern": r"loot: (?P<value>.+)", "mode": "append", "max": 2},
        {"field": "whispers", "pattern": r"Whisper from (?P<value>.+)", "mode": "append", "private": True},
    ],
}


def test_log_tail_follows_a_growing_file(tmp_path: Path) -> None:
    log = tmp_path / "game.log"
    adapter = LogTailAdapter(RULES, base_dir=tmp_path)
    assert adapter.detect() is False and adapter.read_state()[META_KEY]["error"] == "journal introuvable"
    log.write_text("Entering zone: Forêt\nNow level 12\nHP: 87.5%\nYou died\nloot: Épée\n", encoding="utf-8")
    fields = adapter.read_state()["fields"]
    assert fields == {"zone": "Forêt", "level": 12, "hp": 87.5, "deaths": 1, "loot": ["Épée"]}
    with open(log, "a", encoding="utf-8") as handle:
        handle.write("You died\nloot: Arc\nloot: Bouclier\nEntering zone: Dés")  # dernière ligne incomplète
    fields = adapter.read_state()["fields"]
    assert fields["deaths"] == 2 and fields["loot"] == ["Arc", "Bouclier"] and fields["zone"] == "Forêt"
    with open(log, "a", encoding="utf-8") as handle:
        handle.write("ert\nNow level beaucoup\n")  # la ligne se termine ; une valeur du mauvais type est ignorée
    fields = adapter.read_state()["fields"]
    assert fields["zone"] == "Désert" and fields["level"] == 12
    assert adapter.read_state()["fields"] == fields  # rien de nouveau : rien n'est relu ni recompté


def test_log_tail_restarts_after_truncation(tmp_path: Path) -> None:
    log = tmp_path / "game.log"
    log.write_text("Entering zone: Une très longue zone de départ\nYou died\n", encoding="utf-8")
    adapter = LogTailAdapter(RULES, base_dir=tmp_path)
    assert adapter.read_state()["fields"]["deaths"] == 1
    log.write_text("Entering zone: Ville\n", encoding="utf-8")  # le jeu a recréé son journal
    assert adapter.read_state()["fields"]["zone"] == "Ville"


def test_log_tail_never_modifies_the_log(tmp_path: Path) -> None:
    log = tmp_path / "game.log"
    log.write_bytes(b"Entering zone: A\r\nYou died\r\n")
    before = (log.read_bytes(), log.stat().st_mtime_ns)
    adapter = LogTailAdapter(RULES, base_dir=tmp_path)
    assert adapter.read_state()["fields"] == {"zone": "A", "deaths": 1}
    assert (log.read_bytes(), log.stat().st_mtime_ns) == before


def test_log_tail_showcase_masks_private_fields_and_scrubs_text(tmp_path: Path) -> None:
    (tmp_path / "game.log").write_text(f"Whisper from AmiSecret\nEntering zone: {EMAIL}\n", encoding="utf-8")
    adapter = LogTailAdapter(RULES, base_dir=tmp_path)
    state = adapter.read_state()
    shown = adapter.privacy_filter(state, "showcase")
    assert shown["fields"]["whispers"] == MASK and leaks(shown, ["AmiSecret", EMAIL, str(tmp_path)]) == []
    assert state["fields"]["whispers"] == ["AmiSecret"]
    assert "zone = " in adapter.context_for_llm(state)
    assert adapter.schema()["fields"]["whispers"]["private"] is True


def test_log_tail_example_rules_file_is_valid(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[2] / "modules" / "gaming_hud" / "rules" / "log_tail.example.yaml"
    adapter = LogTailAdapter.from_file(example)
    assert adapter.id == "demo_log" and len(adapter.rules) == 6
    assert adapter.read_state()["fields"] == {}  # le journal d'exemple n'existe pas : état vide, aucune erreur levée


@pytest.mark.parametrize(("config", "message"), [
    ([], "dictionnaire"),
    ({"rules": [{"field": "a", "pattern": "a"}]}, "path"),
    ({"path": "x", "rules": []}, "rules"),
    ({"path": "x", "rules": [{"field": "a"}]}, "obligatoires"),
    ({"path": "x", "rules": [{"field": "a", "pattern": "(", "type": "str"}]}, "invalide"),
    ({"path": "x", "rules": [{"field": "a", "pattern": "a", "type": "date"}]}, "type inconnu"),
    ({"path": "x", "rules": [{"field": "a", "pattern": "a", "mode": "sum"}]}, "mode inconnu"),
])
def test_log_tail_rejects_invalid_rules(config: object, message: str) -> None:
    with pytest.raises(RulesError, match=message):
        parse_rules(config)


# --------------------------------------------------------------------------- capture d'écran (expérimental)
OCR_CONFIG = {"id": "ocr_demo", "game": "Jeu démo", "min_interval_s": 60,
              "fields": [{"name": "hp", "type": "int", "description": "points de vie"},
                         {"name": "zone", "type": "str"}, {"name": "pseudo", "type": "str", "private": True}]}


def test_screen_ocr_validates_what_the_model_answers() -> None:
    calls = []

    def vision(prompt: str, image: bytes) -> str:
        calls.append((prompt, image))
        return '```json\n{"hp": "80", "zone": "Forêt", "pseudo": "JoueurSecret", "invente": 1}\n```'

    adapter = ScreenOcrAdapter(OCR_CONFIG, capture=lambda: b"PNG", vision=vision)
    state = adapter.read_state()
    assert state["fields"] == {"hp": 80, "zone": "Forêt", "pseudo": "JoueurSecret"}  # « invente » est écarté
    assert state[META_KEY]["experimental"] is True and '"hp" (int)' in calls[0][0] and calls[0][1] == b"PNG"
    adapter.read_state()
    assert len(calls) == 1  # intervalle minimal respecté : le modèle n'est pas rappelé à chaque lecture
    adapter.read_state(force=True)
    assert len(calls) == 2
    shown = adapter.privacy_filter(state, "showcase")
    assert shown["fields"]["pseudo"] == MASK and leaks(shown, ["JoueurSecret"]) == []
    assert "peut être inexact" in adapter.context_for_llm(state)


@pytest.mark.parametrize("answer", ["je ne sais pas", '{"hp": "beaucoup", "zone": null}', "", "[1, 2]"])
def test_screen_ocr_keeps_unreadable_values_absent(answer: str) -> None:
    adapter = ScreenOcrAdapter(OCR_CONFIG, capture=lambda: b"PNG", vision=lambda p, i: answer)
    state = adapter.read_state()
    assert state["fields"] == {} and state[META_KEY]["error"]  # aucune valeur inventée


def test_screen_ocr_survives_capture_and_model_failures() -> None:
    def no_screen() -> bytes:
        raise RuntimeError("pas d'écran")

    adapter = ScreenOcrAdapter(OCR_CONFIG, capture=no_screen, vision=lambda p, i: "{}")
    assert adapter.detect() is False and "pas d'écran" in adapter.read_state()[META_KEY]["error"]

    def model_down(prompt: str, image: bytes) -> str:
        raise OSError("connexion refusée")

    adapter = ScreenOcrAdapter(OCR_CONFIG, capture=lambda: b"PNG", vision=model_down)
    assert "connexion refusée" in adapter.read_state()[META_KEY]["error"]


def test_extract_json() -> None:
    assert extract_json('Voici : {"a": 1} merci') == {"a": 1}
    assert extract_json("```json\n{\"a\": 2}\n```") == {"a": 2}
    assert extract_json("rien") == {} and extract_json("{cassé") == {}


def test_screen_ocr_config_is_validated() -> None:
    with pytest.raises(ValueError, match="fields"):
        ScreenOcrAdapter({"fields": []})
    with pytest.raises(ValueError, match="type inconnu"):
        ScreenOcrAdapter({"fields": [{"name": "x", "type": "date"}]})


@pytest.mark.skipif(not os.environ.get("AETHERTWIN_REAL_OLLAMA"),
                    reason="définir AETHERTWIN_REAL_OLLAMA=1 (GPU requis)")
def test_screen_ocr_with_the_real_local_vision_model() -> None:
    """Test réel : une image générée contenant du texte est lue par le modèle de vision local d'Ollama."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (900, 360), (20, 24, 32))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 54)
    except OSError:
        font = ImageFont.load_default()
    draw.text((40, 40), "PV : 80 / 100", fill=(120, 230, 120), font=font)
    draw.text((40, 130), "Niveau 12", fill=(240, 240, 240), font=font)
    draw.text((40, 220), "Zone : Marais", fill=(240, 200, 90), font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    config = {"model": os.environ.get("AETHERTWIN_VISION_MODEL", "qwen2.5vl:7b"),
              "fields": [{"name": "pv", "type": "int",
                          "description": "points de vie actuels (premier nombre après PV)"},
                         {"name": "niveau", "type": "int", "description": "niveau du personnage"},
                         {"name": "zone", "type": "str", "description": "nom de la zone"}]}
    adapter = ScreenOcrAdapter(config, capture=buffer.getvalue)
    state = adapter.read_state()
    print("\nRÉEL screen_ocr :", json.dumps(state, ensure_ascii=False))
    assert state["fields"].get("pv") == 80 and state["fields"].get("niveau") == 12
    assert "marais" in str(state["fields"].get("zone", "")).lower()
