"""
Réglages de l'application (settings.json) : assistant IA, icônes en ligne...
"""
import json
import os

from config import BASE_DIR

SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

DEFAULTS = {
    "llm": {
        "mode": "api",                       # "api" (compatible OpenAI : Ollama, LM Studio, vLLM, Open WebUI, Omniroute...) ou "exe"
        "endpoint": "",                      # ex. http://127.0.0.1:11434/v1
        "servers": [],                       # serveurs enregistrés : [{"url", "api_key", "enabled"}] ; l'actif reste "endpoint"
        "model": "",
        "api_key": "",
        "exe_path": "hermes.exe",
        "exe_args": "{prompt}",              # {prompt} est remplacé par la question ; sans {prompt} elle est envoyée sur l'entrée standard
        "system_prompt": "Tu es un assistant expert de World of Warcraft. Réponds en français, de façon claire et concise.",
    },
    "online_icons": True,
    "app": {"pos": None},                     # dernière position de la fenêtre principale
    "game": {"path": ""},                     # dossier _retail_ de WoW (vide = détection automatique)
    "bnet": {"client_id": "", "client_secret": "", "region": ""},   # API Battle.net (facultative)
    "model3d": {"enabled": False},            # vue 3D (visionneuse de Wowhead), désactivée par défaut
    "overlay": {
        "start_in_overlay": False,
        "opacity": 100,                       # 40 à 100 %
        "anchor_game": True,                  # se place sur la fenêtre de WoW
        "monitor": 0,                         # écran de l'overlay si WoW n'est pas trouvé (0 = écran principal)
        "app_monitor": -1,                    # écran de la fenêtre principale (-1 = là où elle est)
        "locked": False,                      # verrouille la position des widgets
        "hotkeys": {"overlay": "F9", "lock": "F10", "focus": "F11", "capture": "F7"},
    },
    "focus": {"auto": True, "quiet_seconds": 5},
    "voice": {
        "enabled": False,
        "mode": "ptt",                        # "ptt" (appuyer pour parler) ou "vad" (activation vocale)
        "ptt_key": "F8",                      # touche ou bouton de souris : F8, Ctrl+Space, Mouse4...
        "device": "",                         # nom du micro (vide = micro par défaut de Windows)
        "sensitivity": 3,                     # 1 (peu sensible) à 5 (très sensible)
        "auto_send": True,                    # envoie le message dès qu'il est transcrit
        "speak_answers": False,               # lit les réponses de l'assistant à voix haute
        "stt": {"backend": "api", "endpoint": "", "model": "whisper-1", "fw_model": "small", "api_key": "", "exe": "",
                "args": "-f {audio} -l fr -nt", "language": "fr"},
        "tts": {"backend": "sapi", "rate": 0, "max_chars": 700, "piper_exe": "piper", "piper_model": ""},
    },
    "vision": {"hide_ms": 80, "watch_clipboard": True, "max_edge": 1600},
    "web": {
        "openwebui_url": "http://localhost:3000",
        "video_url": "https://www.youtube.com/",
        # Seuls ces domaines (et leurs sous-domaines) peuvent s'afficher dans un widget web
        "allowed_hosts": "localhost, 127.0.0.1, youtube.com, youtu.be, twitch.tv",
        "scale": 1.0,                         # corrige l'écart éventuel avec la mise à l'échelle de Windows (125 %, 150 %...)
    },
}


class Settings:
    def __init__(self, path=SETTINGS_FILE):
        self.path = path
        self.data = _merge(DEFAULTS, {})
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            self.data = _merge(DEFAULTS, stored if isinstance(stored, dict) else {})
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print(f"Réglages non sauvegardés : {e}")
            return False

    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted, value):
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value


def _merge(defaults, stored):
    out = {}
    for key, value in defaults.items():
        if isinstance(value, dict):
            out[key] = _merge(value, stored.get(key, {}) if isinstance(stored.get(key), dict) else {})
        else:
            out[key] = stored.get(key, value)
    for key, value in stored.items():   # clé inconnue des valeurs par défaut : gardée (perdue avant le 23/11)
        out.setdefault(key, value)
    return out
