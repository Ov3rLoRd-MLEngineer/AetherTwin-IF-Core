"""Tests de WoW Assistant v9 (code d'origine, dans `_import/`), en mode headless : aucune fenêtre réelle.

Les modules d'origine s'importent à plat (`import ui`, `import settings`) : leur dossier est ajouté au chemin.
Rien n'est écrit dans les fichiers de l'appli : réglages, disposition et historiques vont dans un dossier temporaire.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

APP_DIR = Path(__file__).resolve().parents[2] / "modules" / "gaming_hud" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

pygame = pytest.importorskip("pygame")


class SpySurface(pygame.Surface):
    """Surface qui note tout ce qui est dessiné coupé horizontalement par la zone de dessin (texte tronqué)."""

    def __init__(self, size) -> None:
        super().__init__(size)
        self.cut: list[tuple[int, int, int, int]] = []
        self.blits: list[pygame.Rect] = []

    def blit(self, source, dest, *args, **kwargs):
        rect = source.get_rect(topleft=dest) if not isinstance(dest, pygame.Rect) else dest
        self.blits.append(pygame.Rect(rect))
        clip = self.get_clip()
        visible = rect.clip(clip)
        if visible.h > 0 and visible.w > 0 and (rect.left < clip.left or rect.right > clip.right):
            self.cut.append((rect.x, rect.y, rect.w, rect.h))
        return super().blit(source, dest, *args, **kwargs)


@pytest.fixture
def app(tmp_path: Path):
    """Assemble l'interface comme `main.py`, avec le personnage de démonstration et des fichiers temporaires."""
    import settings as settings_mod
    from character import Character
    from craft import CraftSystem
    from focus import FocusManager
    from gamedata import GameData, make_context
    from history import ActivityLog, History
    from inventory import Inventory
    from llm import LLMClient
    from quests import QuestTracker
    from ui import UI
    from vision import VisionManager
    from voice import VoiceManager
    from webwidget import WebHost
    from widgets import WidgetManager
    from widgets_builtin import ChatState, build_specs

    settings = settings_mod.Settings(str(tmp_path / "settings.json"))
    llm = LLMClient(settings)
    ui = UI(settings=settings, llm=llm)
    ui.icons.enabled = False  # aucune requête réseau pendant les tests
    ui.screen = SpySurface((ui.W, ui.H))
    manager = WidgetManager(build_specs(), str(tmp_path / "layout.json"))
    focus = FocusManager(settings)
    ui.manager, ui.chat = manager, ChatState(str(tmp_path / "chat.json"), llm)
    from coach_knowledge import KnowledgeBase
    from routine import RoutineStore
    ui.knowledge = KnowledgeBase(str(tmp_path / "coach_knowledge.json"))   # jamais les fichiers du profil Windows
    ui.routine = RoutineStore(str(tmp_path / "routine.json"))
    from combat_report import ReportBuilder
    ui.reports = ReportBuilder(str(tmp_path / "combat_reports.json"))
    ui.vision, ui.voice, ui.webhost = VisionManager(settings), VoiceManager(settings), WebHost(settings)
    ui.actions = {
        "to_overlay": lambda: None, "to_app": lambda: None, "close_overlay": ui.close_overlay,
        "game_path_changed": lambda path: None, "toggle_lock": lambda: None, "cycle_focus": focus.cycle_manual,
        "focus_label": lambda: focus.label, "focus_status": lambda: "automatique", "settings_changed": lambda: None,
        "open_widgets": lambda: ui.open_settings("widgets"), "capture": lambda: None, "mic_cycle": lambda: None,
        "voice_label": lambda: "Micro : off", "speak": lambda text: None, "after_attach": lambda: None,
    }
    character = Character()
    character.name, character.level, character.class_name = "Aeliana", 60, "Mage"
    character.class_file, character.race, character.faction = "MAGE", "Humain", "Alliance"
    history = History(str(tmp_path / "history.json"), 60, 100)
    ui.test_ctx = make_context(
        character=character, quests=QuestTracker(), inventory=Inventory(), craft=CraftSystem(), history=history,
        activity=ActivityLog(str(tmp_path / "activity.json")), data=GameData(),
        status_lines=["Mode démo"], session=history.session_summary(character.key))
    ui.draw(ui.test_ctx)
    yield ui
    ui.voice.stop()
    ui.webhost.stop_all()
    pygame.quit()
