"""
Réglages de l'application (settings.json) : assistant IA, icônes en ligne...
"""
import json
import os

from config import BASE_DIR

SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
# Identifiants Battle.net : aussi gardés dans le profil Windows de l'utilisateur, pour que TOUTES les copies de
# l'appli (dossier du dépôt, D:\Hermes-Agent\wow_assistant_v9...) les retrouvent : recopier le dossier ne les
# perd plus. Jamais dans le dépôt.
SHARED_FILE = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "WoWAssistant", "shared.json")
SHARED_KEYS = ("bnet.client_id", "bnet.client_secret", "bnet.region")

DEFAULTS = {
    "llm": {
        "mode": "api",                       # "hermes" (Hermes Agent), "api" (compatible OpenAI : Ollama, LM Studio, vLLM, Open WebUI, Omniroute...) ou "exe"
        "endpoint": "",                      # ex. http://127.0.0.1:11434/v1
        "servers": [],                       # serveurs enregistrés : [{"url", "api_key", "enabled"}] ; l'actif reste "endpoint"
        "model": "",
        "api_key": "",
        "exe_path": "hermes.exe",
        "exe_args": "{prompt}",              # {prompt} est remplacé par la question ; sans {prompt} elle est envoyée sur l'entrée standard
        "system_prompt": "Tu es un assistant expert de World of Warcraft. Réponds en français, de façon claire et concise.",
    },
    # Hermes Agent : auto / api / cli ; session de la conversation ; réflexion demandée au modèle à chaque question
    # (low / medium / xhigh, ou "hermes" = réglage de Hermes). « high » est refusé par le modèle de Qwen 3.5.
    "hermes": {"transport": "auto", "session_id": "", "reasoning": "medium"},
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
    def __init__(self, path=SETTINGS_FILE, shared_path=None):
        self.path = path
        # fichier partagé : seulement pour les vrais réglages de l'appli (les tests passent un autre chemin)
        self.shared_path = shared_path if shared_path is not None else (SHARED_FILE if path == SETTINGS_FILE else "")
        self.data = _merge(DEFAULTS, {})
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            self.data = _merge(DEFAULTS, stored if isinstance(stored, dict) else {})
        except (OSError, ValueError):
            pass
        if self.get("llm.mode") == "exe":     # « Programme local » retiré (23/11) : il servait à lancer Hermes
            self.set("llm.mode", "hermes")
        shared = _read_json(self.shared_path)
        for key in SHARED_KEYS:          # valeur vide ici, présente dans le profil : on la reprend
            if not self.get(key) and shared.get(key):
                self.set(key, shared[key])
        if self.shared_path and any(self.get(k) and k not in shared for k in SHARED_KEYS):
            # 1er lancement d'une copie qui a déjà ses identifiants : ils passent dans le profil
            _write_json(self.shared_path, dict(shared, **{k: self.get(k, "") or "" for k in SHARED_KEYS}))

    def save(self):
        ok = _write_json(self.path, self.data)
        if ok and self.shared_path:
            shared = _read_json(self.shared_path)
            wanted = {key: self.get(key, "") or "" for key in SHARED_KEYS}
            if any(shared.get(k, "") != v for k, v in wanted.items()):
                ok = _write_json(self.shared_path, dict(shared, **wanted))
        return ok

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


def _read_json(path):
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError as e:
        print(f"Réglages non sauvegardés ({path}) : {e}")
        return False


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
