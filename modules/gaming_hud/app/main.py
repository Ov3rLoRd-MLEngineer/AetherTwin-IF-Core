"""
Point d'entrée de WoW Assistant
"""
import os
import sys
import time

import pygame

from config import WoWConfig
from character import Character
from quests import QuestTracker
from craft import CraftSystem
from inventory import Inventory
from history import ActivityLog, History, snapshot_state
from gamedata import GameData, make_context
from game_connection import GameConnection
from ui import UI
import overlay as ov
from focus import CombatMonitor, FocusManager
from hotkeys import Hotkeys
from vision import VisionManager
from voice import VoiceManager
from webwidget import WebHost
from widgets_builtin import WEB_URL_SETTINGS
from widgets import WidgetManager
from widgets_builtin import ChatState, build_specs
from settings import Settings
from llm import LLMClient
from snapcache import SnapshotCache
from bnet import BattleNet
from media import MediaStore


def resolve_game_path(settings):
    """Détermine le dossier _retail_ : réglage enregistré > variable WOW_RETAIL_PATH > détection automatique."""
    saved = WoWConfig.set_path(settings.get("game.path", ""))
    if saved:
        return saved
    if WoWConfig.is_wow_installed():
        return WoWConfig.WOW_PATH
    for candidate in WoWConfig.detect_installs():
        if WoWConfig.set_path(candidate) and WoWConfig.is_wow_installed():
            print(f"Jeu détecté automatiquement : {WoWConfig.WOW_PATH}")
            settings.set("game.path", WoWConfig.WOW_PATH)
            settings.save()
            return WoWConfig.WOW_PATH
    return ""


def main():
    print("Démarrage de WoW Assistant...")

    character = Character()
    quests = QuestTracker()
    craft = CraftSystem()
    inventory = Inventory()
    data = GameData()
    history = History(WoWConfig.HISTORY_FILE, WoWConfig.HISTORY_MIN_INTERVAL, WoWConfig.HISTORY_MAX_ENTRIES)
    activity = ActivityLog(WoWConfig.ACTIVITY_FILE)
    settings = Settings()
    resolve_game_path(settings)
    connection = GameConnection()
    llm = LLMClient(settings)
    cache = SnapshotCache(WoWConfig.SNAPSHOT_CACHE_FILE)
    ui = UI(settings=settings, llm=llm)
    ui.icons.enabled = bool(settings.get("online_icons", True))
    cached = cache.load()

    # ------------------------------------------------------------------ overlay, widgets, mode Focus, raccourcis
    manager = WidgetManager(build_specs(), WoWConfig.LAYOUT_FILE)
    manager.locked = bool(settings.get("overlay.locked", False))
    ui.manager = manager
    chat = ChatState(WoWConfig.CHAT_FILE, llm)
    ui.chat = chat
    # captures d'écran (vision) et voix : l'overlay est masqué un instant pendant une capture
    vision = VisionManager(settings, hide=lambda: ui.set_overlay_visible(False),
                           show=lambda: ui.set_overlay_visible(True), game_rect=ov.find_game_rect)
    voice = VoiceManager(settings)
    ui.vision, ui.voice = vision, voice
    webhost = WebHost(settings)
    ui.webhost = webhost
    # API Battle.net (facultative) : rendus officiels, images des montures, prix de l'Hôtel des ventes
    ui.media = MediaStore(BattleNet(settings, os.path.join(WoWConfig.BASE_DIR, "cache", "bnet")))
    focus = FocusManager(settings)
    monitor = CombatMonitor(os.path.join(WoWConfig.WOW_PATH, "Logs"), settings.get("focus.quiet_seconds", 5))
    hotkeys = Hotkeys()
    overlay_state = {"visible": True, "geometry": None, "checked": 0.0}

    def overlay_geometry():
        """Zone de l'overlay : la fenêtre de WoW, sinon l'écran choisi dans les réglages."""
        rect = ov.find_game_rect() if settings.get("overlay.anchor_game", True) else None
        if rect:
            return (rect[2], rect[3]), (rect[0], rect[1])
        monitors = ov.list_monitors()
        index = int(settings.get("overlay.monitor", 0))
        mx, my, mw, mh = monitors[index] if 0 <= index < len(monitors) else monitors[0]
        return (mw, mh), (mx, my)

    def enter_overlay():
        """Ouvre l'overlay en plus de la fenêtre principale (qui reste sur son écran)."""
        size, pos = overlay_geometry()
        if ui.open_overlay(size, pos, settings.get("overlay.opacity", 100)):
            overlay_state.update(visible=True, geometry=(size, pos))
        else:
            ui.notify(ui.overlay_error or "Overlay impossible", 8)

    def leave_overlay():
        ui.close_overlay()

    def enter_app():
        """Remet la fenêtre principale au premier plan."""
        ui.raise_app()

    def place_app_window():
        """Restaure la position de la fenêtre principale (écran choisi ou dernière position)."""
        monitors = ov.list_monitors()
        index = int(settings.get("overlay.app_monitor", -1))
        pos = settings.get("app.pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2 and any(
                mx - 50 <= pos[0] < mx + mw - 50 and my - 50 <= pos[1] < my + mh - 50 for mx, my, mw, mh in monitors):
            ui.move_app(pos)
        elif 0 <= index < len(monitors):
            mx, my, mw, mh = monitors[index]
            ui.move_app((mx + max(0, (mw - ui.W) // 2), my + max(0, (mh - ui.H) // 2)))

    def game_path_changed(path):
        """Nouveau dossier du jeu choisi dans les réglages : tout est reconnecté sans redémarrer."""
        nonlocal cached
        if not WoWConfig.set_path(path):
            return
        connection.set_path(WoWConfig.WOW_PATH)
        monitor.logs_dir = os.path.join(WoWConfig.WOW_PATH, "Logs")
        monitor._path = None
        print(f"Dossier du jeu : {WoWConfig.WOW_PATH}")
        ui.refresh_requested = True

    def toggle_lock():
        manager.locked = not manager.locked
        settings.set("overlay.locked", manager.locked)
        settings.save()
        manager.save()

    def focus_status():
        base = ("forcé " + ("actif" if focus.manual else "inactif")) if focus.manual is not None else (
            "automatique" if focus.auto_enabled else "automatique désactivé")
        return f"{base}  ·  journal de combat : {monitor.status}" + ("  ·  FOCUS ACTIF" if focus.active else "")

    def player_context():
        # Dans AetherTwin, le contexte de l'assistant vient de l'adaptateur de jeu (interface GameAdapter).
        # Copie autonome de l'appli (sans le paquet « modules ») ou aucune donnée de jeu : phrase d'origine.
        state = connection.snapshot or cached or {}
        if state.get("character", {}).get("name"):
            try:
                from modules.gaming_hud.adapters.wow_retail import context_from_state
                return context_from_state(state)
            except ImportError:
                pass
        c = character
        return (f"Contexte joueur : {c.name}, niveau {c.level} {c.class_name} {c.spec}, zone {c.location or 'inconnue'}, "
                f"niveau d'objet {c.ilvl:g}.")

    def after_attach():
        if ui.overlay_on:
            manager.set_enabled("assistant", True)

    def do_capture():
        att = vision.capture_game()
        if att:
            ui.notify(f"Capture jointe ({att.size[0]}x{att.size[1]})")
            after_attach()
        else:
            ui.notify(vision.error or "Capture impossible", 7)

    def mic_cycle():
        """Micro : désactivé -> appuyer pour parler -> activation vocale -> désactivé."""
        if not settings.get("voice.enabled", False):
            settings.set("voice.enabled", True)
            settings.set("voice.mode", "ptt")
        elif settings.get("voice.mode", "ptt") == "ptt":
            settings.set("voice.mode", "vad")
        else:
            settings.set("voice.enabled", False)
        settings.save()
        voice.apply_settings()
        if voice.error:
            ui.notify(voice.error, 8)

    def voice_label():
        if not settings.get("voice.enabled", False):
            return "Micro : off"
        return "Micro : PTT" if settings.get("voice.mode", "ptt") == "ptt" else "Micro : voix"

    def speak_answer(text):
        if settings.get("voice.speak_answers", False):
            voice.speak(text)

    chat.on_answer = speak_answer

    def deliver_voice_text(text):
        auto = settings.get("voice.auto_send", True)
        if ui.overlay_on and ui.overlay_visible:
            manager.set_enabled("assistant", True)
            if auto:
                chat.submit(text, ui.ctx, vision.payload())
                vision.clear()
            else:
                ui.inputs["chat_msg"] = text
        else:
            ui.ask_assistant("Message vocal", player_context(), prefill=text)
            if auto:
                ui._modal_send()

    def handle_voice_event(kind, payload):
        _, settings_modal = ui.any_modal("settings")
        if kind == "error":
            ui.notify("Voix : " + payload, 6)
            if settings_modal:
                settings_modal["status"], settings_modal["status_ok"] = payload, False
        elif kind == "oneshot":
            where, compose = ui.any_modal("compose")
            if compose and compose["stage"] == "input":
                ui.use(where)
                try:
                    ui.inputs["llm_msg"] = payload
                    ui.focus = "llm_msg"
                    if settings.get("voice.auto_send", True):
                        ui._modal_send()
                finally:
                    ui.use("app")
            elif settings_modal:
                settings_modal["status"], settings_modal["status_ok"] = f"Entendu : « {payload} »", True
            else:
                deliver_voice_text(payload)
        elif kind == "text":
            deliver_voice_text(payload)

    def settings_changed():
        voice.apply_settings()
        vision.start_watch()
        manager.locked = bool(settings.get("overlay.locked", False))
        monitor.quiet_seconds = settings.get("focus.quiet_seconds", 5)
        hotkeys.start(settings.get("overlay.hotkeys") or {})
        ui.set_overlay_opacity(settings.get("overlay.opacity", 100))

    def toggle_overlay_hotkey():
        if not ui.overlay_on:
            enter_overlay()
        else:
            overlay_state["visible"] = not overlay_state["visible"]
            ui.set_overlay_visible(overlay_state["visible"])

    ui.actions = {
        "to_overlay": enter_overlay, "to_app": enter_app, "close_overlay": leave_overlay,
        "game_path_changed": game_path_changed, "toggle_lock": toggle_lock,
        "cycle_focus": focus.cycle_manual, "focus_label": lambda: focus.label, "focus_status": focus_status,
        "open_widgets": lambda: ui.open_settings("widgets"), "settings_changed": settings_changed,
        "capture": do_capture, "mic_cycle": mic_cycle, "voice_label": voice_label, "speak": speak_answer,
        "after_attach": after_attach,
    }
    hotkeys.start(settings.get("overlay.hotkeys") or {})
    vision.start_watch()
    voice.apply_settings()

    n_recipes = craft.load_recipes_file(WoWConfig.RECIPES_FILE)
    if n_recipes:
        print(f"{n_recipes} recettes chargées depuis recipes.json")

    def apply_snapshot(snapshot, from_cache=False):
        """Répartit les données du jeu entre les différents modules."""
        character.update_from_dict(snapshot.get("character"))
        character.load_equipment(snapshot.get("equipment"))
        character.load_played(snapshot.get("played"))
        inventory.load_from_dict(snapshot.get("inventory"))
        quests.load_from_dict(snapshot.get("quests"))
        craft.load_professions(snapshot.get("professions"))
        craft.load_game_recipes(snapshot.get("recipes"))
        data.load(snapshot)
        if from_cache:
            return
        extras = {"quests": quests.count(), "ach_points": data.achievements.get("points", 0)}
        history.record(character, extras)
        when = int(snapshot["character"].get("updated") or time.time())
        new_events = activity.process(character.key, snapshot_state(character, quests, data), when)
        activity.merge_game_log(character.key, snapshot.get("log"))
        print(f"Données actualisées : {character} - {quests.count()} quêtes, "
              f"{inventory.get_total_items()} objets, {len(new_events)} nouvel(s) événement(s)")

    def load_from_game(force=False):
        """Lit le fichier du jeu, le complète avec le cache (une section vide ne remplace jamais une section connue)."""
        nonlocal cached
        if not connection.refresh(force=force):
            return False
        merged = SnapshotCache.merge(connection.snapshot, cached)
        connection.snapshot = merged
        apply_snapshot(merged)
        cache.save(merged)
        cached = merged
        return True

    # 1) on affiche tout de suite le dernier état mémorisé (stuff, stats, sacs, métiers, quêtes...)
    if cached:
        apply_snapshot(cached, from_cache=True)
        print(f"Données mémorisées chargées : {character}")
    # 2) puis on lit le fichier du jeu
    if load_from_game():
        pass
    elif cached:
        print("Fichier du jeu sans nouvelles données : on garde les données mémorisées.")
    elif not connection.is_connected():
        print("Attention : données du jeu inaccessibles. Mode démo.")
        character.name = "Aeliana"
        character.level = 60
        character.class_name = "Mage"
        character.class_file = "MAGE"
        character.race = "Humain"
        character.faction = "Alliance"
    else:
        print("Dossier WoW trouvé mais pas encore de données (tape /ha save en jeu).")

    place_app_window()
    if settings.get("overlay.start_in_overlay", False):
        enter_overlay()
    if not WoWConfig.is_wow_installed():
        ui.open_settings("game")       # dossier du jeu introuvable : on ouvre directement la page « Jeu »
        ui.notify("Dossier du jeu introuvable : indique-le dans Paramètres > Jeu", 10)

    clock = pygame.time.Clock()
    last_check = time.time()

    running = True
    while running:
        running = ui.handle_events(pygame.event.get())

        now = time.time()
        # raccourcis globaux
        for action in hotkeys.poll():
            if action == "overlay":
                toggle_overlay_hotkey()
            elif action == "lock":
                toggle_lock()
            elif action == "focus":
                focus.cycle_manual()
            elif action == "capture":
                do_capture()
        for kind, payload in voice.poll():
            handle_voice_event(kind, payload)
        # mode Focus : combat détecté par le journal de combat du jeu
        focus.combat = monitor.update(now)
        manager.focus_active = focus.active
        # l'overlay suit la fenêtre de WoW
        if ui.overlay_on and settings.get("overlay.anchor_game", True) and now - overlay_state["checked"] > 2:
            overlay_state["checked"] = now
            rect = ov.find_game_rect()
            if rect:
                geometry = ((rect[2], rect[3]), (rect[0], rect[1]))
                if overlay_state["geometry"] and geometry != overlay_state["geometry"]:
                    if geometry[0] == overlay_state["geometry"][0]:
                        ui.move_overlay(geometry[1])
                        overlay_state["geometry"] = geometry
                    else:
                        ui.open_overlay(geometry[0], geometry[1], settings.get("overlay.opacity", 100))
                        overlay_state["geometry"] = geometry
                        manager.set_screen_size(geometry[0])
        if ui.refresh_requested:
            ui.refresh_requested = False
            last_check = now
            if load_from_game(force=True):
                ui.notify(f"Actualisé à {time.strftime('%H:%M:%S')}")
            else:
                ui.notify("Aucune donnée plus récente : tapez /ha save en jeu puis réessayez", 7)
        elif now - last_check >= WoWConfig.DATA_REFRESH_INTERVAL:
            last_check = now
            load_from_game()

        status = connection.status_lines()
        if cached and not connection.file_path and cached.get("cachedAt"):
            status = [f"Données mémorisées du {time.strftime('%d/%m/%Y %H:%M', time.localtime(cached['cachedAt']))} (fichier du jeu absent)"]
        ctx = make_context(
            character=character, quests=quests, inventory=inventory, craft=craft,
            history=history, activity=activity, data=data,
            status_lines=status,
            session=history.session_summary(character.key),
        )
        ui.draw(ctx)
        if ui.overlay_on:
            ui.draw_overlay(ctx)
        # widgets web : leurs fenêtres (processus isolés) suivent la position des widgets de l'overlay
        origin = (overlay_state["geometry"][1] if overlay_state.get("geometry") else (0, 0))
        wants = {wid: dict(state, enabled=manager.entry(wid)["enabled"], url=settings.get(WEB_URL_SETTINGS.get(wid, ""), ""))
                 for wid, state in manager.web_state.items()}
        webhost.sync(wants, origin, ui.overlay_on and overlay_state["visible"])
        pygame.display.flip()
        clock.tick(30)

    pos = ui.app_window_position()
    if pos:
        settings.set("app.pos", [int(pos[0]), int(pos[1])])
        settings.save()
    # filet de sécurité : si un thread ou un processus enfant bloque la fermeture, on force la sortie après 4 s
    import threading
    killer = threading.Timer(4.0, lambda: os._exit(0))
    killer.daemon = True
    killer.start()
    try:
        ui.close_overlay()
    except Exception:
        pass
    hotkeys.stop()
    webhost.stop_all()
    voice.stop()
    vision.stop_watch()
    print("WoW Assistant fermé.")
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
