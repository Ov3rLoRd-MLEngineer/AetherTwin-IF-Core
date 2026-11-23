"""
Données de compte / personnage qui n'ont pas leur propre module :
talents, grimoire, hauts faits, collections, transmogrification, monnaies, réputations,
verrouillages, Grande Chambre forte, banques, statistiques.
Et le "contexte" transmis à l'interface.
"""
from types import SimpleNamespace

# Valeurs par défaut de chaque section ; load() ne remplace une section que si la nouvelle est non vide
_DEFAULTS = {
    "talents": {"points": 0, "loadout": "", "hero": "", "nodes": []},
    "spellbook": [],
    "achievements": {"points": 0, "completed": 0, "total": 0, "categories": [], "recent": []},
    "collections": {
        "mounts": {"total": 0, "collected": 0, "list": []},
        "pets": {"total": 0, "owned": 0},
        "toys": {"total": 0, "collected": 0},
        "heirlooms": {"total": 0, "known": 0},
        "warbandMoney": 0,
    },
    "achv": {"updated": 0, "cats": [], "list": {}},
    "stats": {"updated": 0, "cats": [], "list": {}},
    "mounts": {"updated": 0, "list": []},
    "pets": {"updated": 0, "list": []},
    "toys": {"updated": 0, "list": []},
    "heirlooms": {"updated": 0, "list": []},
    "transmog": {"updated": 0, "setsUpdated": 0, "cats": [], "items": {}, "sets": []},
    "currencies": [],
    "factions": [],
    "lockouts": {"instances": [], "worldBosses": []},
    "vault": {"activities": [], "canClaim": False, "hasRewards": False},
    "mythicPlus": {"score": 0, "keystone": None, "dungeons": [], "week": []},
    "characterBank": {"updated": 0, "money": 0, "tabs": []},
    "bestiary": {},
    "warbandBank": {"updated": 0, "money": 0, "tabs": []},
    "guildBank": {"guild": "", "money": 0, "updated": 0, "tabs": []},
    "log": [],
    "scanInfo": {},
}


def is_empty(value):
    """Vrai pour None, '', 0, [], {} et les structures ne contenant que du vide."""
    if isinstance(value, dict):
        return all(is_empty(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(is_empty(v) for v in value)
    return value in (None, "", 0, False)


class GameData:
    def __init__(self):
        for key, default in _DEFAULTS.items():
            setattr(self, key, _copy(default))

    def load(self, snapshot):
        """Charge depuis un snapshot. Une section vide ne remplace jamais une section déjà remplie
        (données mémorisées). True si quelque chose a changé."""
        changed = False
        for key in _DEFAULTS:
            new = snapshot.get(key)
            if new is None or is_empty(new):
                continue
            if getattr(self, key) != new:
                setattr(self, key, new)
                changed = True
        return changed

    # ------------------------------------------------------------------ requêtes pratiques
    def spell_count(self):
        return sum(len(line["spells"]) for line in self.spellbook)

    @property
    def has_talents(self):
        return bool(self.talents.get("nodes"))

    def scan_age(self, key):
        """Secondes depuis la dernière analyse de `key` (achievements, mounts, pets, transmog...), ou None."""
        import time
        stamp = self.scanInfo.get(key)
        return int(time.time() - stamp) if stamp else None


def _copy(value):
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


def make_context(**kwargs):
    """Regroupe ce que l'interface doit afficher (character, quests, inventory, craft, history, data...)."""
    return SimpleNamespace(**kwargs)
