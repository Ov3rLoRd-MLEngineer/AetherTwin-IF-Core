"""
Configuration de WoW Assistant
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class WoWConfig:
    # Chemins testés dans l'ordre (le premier qui contient WTF/Account est retenu).
    # Tu peux aussi forcer un chemin avec la variable d'environnement WOW_RETAIL_PATH.
    WOW_PATH_CANDIDATES = [
        "E:/World of Warcraft/_retail_",
        "E:/990Pro 2To/World of Warcraft/_retail_",
        "C:/Program Files (x86)/World of Warcraft/_retail_",
        "C:/Program Files/World of Warcraft/_retail_",
    ]

    # Addon
    ADDON_NAME = "HermesAssistant"
    ADDON_TOC = f"{ADDON_NAME}.toc"
    ADDON_LUA = f"{ADDON_NAME}.lua"
    DB_VARIABLE = "HermesAssistantCharDB"

    # Rafraîchissement : test de la date du fichier toutes les N secondes (très léger,
    # le fichier n'est relu que s'il a changé)
    MAX_RETRY_ATTEMPTS = 3
    DATA_REFRESH_INTERVAL = 1.0

    # Fichiers de l'appli
    HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
    ACTIVITY_FILE = os.path.join(BASE_DIR, "activity.json")
    LAYOUT_FILE = os.path.join(BASE_DIR, "layout.json")           # disposition des widgets de l'overlay
    CHAT_FILE = os.path.join(BASE_DIR, "chat_history.json")       # conversation avec l'assistant
    SNAPSHOT_CACHE_FILE = os.path.join(BASE_DIR, "cache", "last_snapshot.json")
    RECIPES_FILE = os.path.join(BASE_DIR, "recipes.json")
    HISTORY_MIN_INTERVAL = 300      # secondes entre deux points d'historique
    HISTORY_MAX_ENTRIES = 5000

    # --- Wowhead : liens et icônes -----------------------------------------------------
    # Le lien Wowhead de chaque objet équipé est fabriqué automatiquement à partir du lien
    # d'objet du jeu (identifiant, bonus, gemmes, enchantement). Pour forcer un lien précis,
    # Hermes peut éditer wowhead_links.json (voir wowhead.py).
    LINKS_FILE = os.path.join(BASE_DIR, "wowhead_links.json")
    WOWHEAD_BASE = "https://www.wowhead.com/fr"
    # Les icônes ne sont pas dans les fichiers du jeu : elles sont téléchargées une seule fois
    # (nom de l'icône via Wowhead, image via zamimg) puis gardées dans le cache local.
    ONLINE_ICONS = True
    WOWHEAD_TOOLTIP_URL = "https://nether.wowhead.com/tooltip/item/{id}?dataEnv=1"
    WOWHEAD_PAGE_URL = "https://www.wowhead.com/item={id}"
    # Même principe pour les sorts, hauts faits... ({kind} = spell, achievement)
    WOWHEAD_TOOLTIP_BASE = "https://nether.wowhead.com/tooltip/{kind}/{id}?dataEnv=1"
    WOWHEAD_PAGE_BASE = "https://www.wowhead.com/{kind}={id}"
    ICON_THROTTLE = 0.12            # pause entre deux téléchargements (politesse envers Wowhead)
    ICON_URL = "https://wow.zamimg.com/images/wow/icons/large/{name}.jpg"
    ICON_CACHE_DIR = os.path.join(BASE_DIR, "cache", "icons")
    ICON_NAMES_FILE = os.path.join(BASE_DIR, "cache", "icon_names.json")
    ITEM_NAMES_FILE = os.path.join(BASE_DIR, "cache", "display_names.json")
    HTTP_TIMEOUT = 8
    ICON_RETRY_SECONDS = 600

    # Dossier de l'addon (textures) et police du jeu (Friz Quadrata, si présente)
    ADDON_TEXTURES_DIR = None   # déduit plus bas

    @staticmethod
    def font_path(filename):
        """Chemin d'une police du jeu (ex. FRIZQT__.TTF), ou None si absente."""
        path = os.path.join(WoWConfig.WOW_PATH, "Fonts", filename)
        return path if os.path.isfile(path) else None

    @staticmethod
    def find_wow_path():
        """Retourne le premier dossier _retail_ valide (ou le chemin forcé / par défaut)."""
        env = os.environ.get("WOW_RETAIL_PATH")
        candidates = ([env] if env else []) + WoWConfig.WOW_PATH_CANDIDATES
        for path in candidates:
            if os.path.isdir(os.path.join(path, "WTF", "Account")):
                return path
        return candidates[0]

    @staticmethod
    def normalize_path(path):
        """Accepte le dossier du jeu, _retail_, WTF ou WTF/Account et renvoie le dossier _retail_ (ou "" si introuvable)."""
        path = (path or "").strip().strip('"').strip()
        if not path:
            return ""
        path = os.path.normpath(path)
        probes = [path]
        parent = path
        for _ in range(3):                       # on remonte : Account -> WTF -> _retail_
            parent = os.path.dirname(parent)
            probes.append(parent)
        probes += [os.path.join(path, "_retail_"), os.path.join(path, "World of Warcraft", "_retail_")]
        for probe in probes:
            if os.path.isdir(os.path.join(probe, "WTF", "Account")):
                return probe.replace("\\", "/")
        for probe in probes:                     # _retail_ sans WTF (jamais lancé) : on garde le dossier du jeu
            if os.path.basename(probe).lower() == "_retail_" and os.path.isdir(probe):
                return probe.replace("\\", "/")
        return ""

    @staticmethod
    def detect_installs():
        """Cherche les installations de WoW (tous les disques sous Windows). Retourne une liste de dossiers _retail_."""
        roots = []
        if os.name == "nt":
            roots = [f"{letter}:/" for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB"]
        else:
            roots = ["/"]
        found = []

        def add(candidate):
            if os.path.isdir(os.path.join(candidate, "WTF")) or os.path.isdir(os.path.join(candidate, "Interface")):
                norm = candidate.replace("\\", "/")
                if norm not in found:
                    found.append(norm)

        for path in WoWConfig.WOW_PATH_CANDIDATES:
            add(path)
        for root in roots:
            if not os.path.isdir(root):
                continue
            for sub in ("World of Warcraft", "Games/World of Warcraft", "Program Files (x86)/World of Warcraft",
                        "Program Files/World of Warcraft", "Jeux/World of Warcraft", "Battle.net/World of Warcraft"):
                add(os.path.join(root, sub, "_retail_"))
            try:                                  # un niveau de profondeur : « E:/990Pro 2To/World of Warcraft »
                for name in os.listdir(root):
                    full = os.path.join(root, name)
                    if name.startswith("$") or name in ("Windows", "Program Files", "Program Files (x86)", "ProgramData"):
                        continue
                    if os.path.isdir(full):
                        add(os.path.join(full, "World of Warcraft", "_retail_"))
            except OSError:
                pass
        return found

    @staticmethod
    def inspect_path(path):
        """Vérifications affichées dans les réglages : [(libellé, ok, détail)]."""
        retail = WoWConfig.normalize_path(path)
        if not retail:
            return [("Dossier _retail_", False, "introuvable : choisis le dossier qui contient WTF et Interface")]
        checks = [("Dossier _retail_", True, retail)]
        account = os.path.join(retail, "WTF", "Account")
        checks.append(("WTF/Account", os.path.isdir(account),
                       "trouvé" if os.path.isdir(account) else "absent : lance le jeu une fois"))
        addon = os.path.join(retail, "Interface", "AddOns", WoWConfig.ADDON_NAME)
        has_addon = os.path.isdir(addon) and os.path.isfile(os.path.join(addon, WoWConfig.ADDON_TOC))
        checks.append(("Addon " + WoWConfig.ADDON_NAME, has_addon,
                       "installé" if has_addon else "absent : copie le dossier de l'addon dans Interface/AddOns"))
        data = None
        if os.path.isdir(account):
            for dirpath, _dirs, files in os.walk(account):
                if WoWConfig.ADDON_NAME + ".lua" in files and os.path.basename(dirpath) == "SavedVariables":
                    data = os.path.join(dirpath, WoWConfig.ADDON_NAME + ".lua")
                    break
        checks.append(("Données de l'addon", data is not None,
                       "fichier trouvé" if data else "pas encore : en jeu, tape /ha save (ou /reload)"))
        logs = os.path.join(retail, "Logs")
        checks.append(("Journal de combat (Focus)", os.path.isdir(logs),
                       "dossier Logs présent" if os.path.isdir(logs) else "optionnel : /combatlog en jeu"))
        return checks

    @staticmethod
    def set_path(path):
        """Change le dossier du jeu à chaud. Retourne le dossier normalisé (ou "" s'il est invalide)."""
        retail = WoWConfig.normalize_path(path)
        if not retail:
            return ""
        WoWConfig.WOW_PATH = retail
        WoWConfig.SAVED_VARIABLES_PATH = os.path.join(retail, "WTF", "Account")
        WoWConfig.ADDON_TEXTURES_DIR = os.path.join(retail, "Interface", "AddOns", WoWConfig.ADDON_NAME, "Textures")
        return retail

    @staticmethod
    def is_wow_installed():
        return os.path.isdir(os.path.join(WoWConfig.WOW_PATH, "WTF", "Account"))

    @staticmethod
    def get_saved_variables_path():
        if WoWConfig.is_wow_installed():
            return WoWConfig.SAVED_VARIABLES_PATH
        return None


WoWConfig.WOW_PATH = WoWConfig.find_wow_path()
WoWConfig.SAVED_VARIABLES_PATH = os.path.join(WoWConfig.WOW_PATH, "WTF", "Account")
WoWConfig.ADDON_TEXTURES_DIR = os.path.join(
    WoWConfig.WOW_PATH, "Interface", "AddOns", WoWConfig.ADDON_NAME, "Textures")

APP_CONFIG = {
    "version": "1.9.0",
    "author": "Hermes Agent",
    "description": "Assistant WoW pour la gestion des personnages, quêtes, craft et inventaire",
    "tos_compliance": "Lecture seule via les fichiers de sauvegarde",
    "data_sources": ["SavedVariables"],
}
