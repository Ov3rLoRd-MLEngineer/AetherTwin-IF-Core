"""
Mémorisation du dernier état connu (par personnage) : au lancement, l'interface affiche tout de suite
le stuff, les statistiques, les sacs, les métiers, les quêtes... du dernier personnage, même si le fichier
du jeu est absent, vide ou en cours d'écriture.
"""
import json
import os
import time

from gamedata import is_empty


def _quests_empty(quests):
    return not quests or (not quests.get("list") and not quests.get("completedTotal"))


class SnapshotCache:
    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) and data.get("character") else None
        except (OSError, ValueError):
            return None

    def save(self, snapshot):
        snapshot = dict(snapshot, cachedAt=int(time.time()))
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except (OSError, TypeError, ValueError) as e:
            print(f"Cache non sauvegardé : {e}")

    @staticmethod
    def merge(new, cached):
        """Snapshot du jeu complété par le cache : une section vide ou absente garde la valeur mémorisée.
        Le cache n'est utilisé que pour le même personnage."""
        if not cached:
            return new
        same_character = (new.get("character", {}).get("name") == cached.get("character", {}).get("name")
                          and new.get("character", {}).get("realm", "") == cached.get("character", {}).get("realm", ""))
        if not same_character:
            return new
        merged = dict(new)
        for key, old in cached.items():
            if key in ("cachedAt", "fileTime"):
                continue
            value = merged.get(key)
            empty = _quests_empty(value) if key == "quests" else is_empty(value)
            if empty and not is_empty(old):
                merged[key] = old
        return merged
