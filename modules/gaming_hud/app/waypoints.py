"""
Points de route : commande « /ha way [carte] x y » de l'addon (point de route du jeu, sans TomTom).

- Quêtes : l'addon 1.10 exporte les coordonnées (quêtes de la carte actuelle, prochain point de route).
- Réponses de Hermes : les « /ha way ... » et les « /way #carte x y » (format TomTom) sont repérés pour être copiés
  d'un clic ; il suffit de les coller dans la discussion du jeu.
"""
import re

_HA = re.compile(r"/ha\s+way\s+((?:#?\d+\s+)?\d{1,3}(?:[.,]\d+)?\s+\d{1,3}(?:[.,]\d+)?)([^\n/]*)", re.I)
_TOMTOM = re.compile(r"/way\s+(#\d+\s+)?(\d{1,3}(?:[.,]\d+)?)\s+(\d{1,3}(?:[.,]\d+)?)([^\n/]*)", re.I)
MAX_LABEL = 48


def _clean_label(text):
    text = re.sub(r"[`*_\[\]()]", "", text or "").strip(" .,:;-—")
    return text[:MAX_LABEL]


def command(map_id, x, y, label=""):
    coords = f"{float(x):.1f} {float(y):.1f}"
    cmd = f"/ha way {int(map_id)} {coords}" if map_id else f"/ha way {coords}"
    return {"cmd": cmd, "label": _clean_label(label)}


def quest_way(quest):
    way = quest.get("way") or {}
    if not way or not way.get("x"):
        return None
    return command(way.get("map"), way["x"], way["y"], quest.get("name") or quest.get("title") or "")


def extract(text, limit=6):
    """Points de route cités dans un texte : [{"cmd", "label"}], sans doublon."""
    found, seen = [], set()
    for m in _HA.finditer(text or ""):
        parts = m.group(1).replace(",", ".").replace("#", "").split()
        nums = [float(p) for p in parts]
        way = command(nums[0] if len(nums) == 3 else 0, nums[-2], nums[-1], m.group(2))
        if way["cmd"] not in seen:
            seen.add(way["cmd"])
            found.append(way)
    for m in _TOMTOM.finditer(text or ""):
        map_id = int(m.group(1).strip().lstrip("#")) if m.group(1) else 0
        way = command(map_id, m.group(2).replace(",", "."), m.group(3).replace(",", "."), m.group(4))
        if way["cmd"] not in seen:
            seen.add(way["cmd"])
            found.append(way)
    return [w for w in found if 0 <= float(w["cmd"].split()[-2]) <= 100 and 0 <= float(w["cmd"].split()[-1]) <= 100][:limit]


def copy(ui, way):
    try:
        import clipboard
        clipboard.set_text(way["cmd"])
        ui.notify(f"Copié : {way['cmd']} — collez-le dans la discussion du jeu (addon 1.10).", 8)
    except Exception as e:      # noqa: BLE001
        ui.notify(f"Copie impossible : {e}")


LEVELING_PROMPT = ("Je veux monter de niveau efficacement. Vu mon personnage (niveau, XP de repos, zone), mes quêtes "
                   "et ma base de connaissances, propose un parcours concret : zones dans l'ordre, campagne ou "
                   "Chromie, donjons, quêtes qui donnent vraiment de l'XP. Vérifie en ligne la meilleure option pour "
                   "mon niveau. Quand tu as des coordonnées (Wowhead), donne le point de route sous la forme "
                   "« /ha way x y » avec la zone.")
