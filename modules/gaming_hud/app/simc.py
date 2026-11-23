"""
Profil SimulationCraft (le texte que l'addon SimulationCraft donne avec /simc) construit à partir des données de
l'addon HermesAssistant : à coller sur Raidbots (Droptimizer, Top Gear, Quick Sim) pour des conseils d'équipement
tirés d'une vraie simulation au lieu d'une liste « meilleur en emplacement » générale.

Équipement porté seulement : les objets des sacs n'ont pas leur emplacement dans l'export de l'addon (Top Gear les
voudrait). Le format suit celui de l'addon SimulationCraft ; à vérifier sur Raidbots (import refusé = signaler).
"""
import re
import time

SLOTS = {1: "head", 2: "neck", 3: "shoulder", 15: "back", 5: "chest", 9: "wrist", 10: "hands", 6: "waist",
         7: "legs", 8: "feet", 11: "finger1", 12: "finger2", 13: "trinket1", 14: "trinket2", 16: "main_hand",
         17: "off_hand"}
SPEC_IDS = {
    102: "balance", 103: "feral", 104: "guardian", 105: "restoration", 250: "blood", 251: "frost", 252: "unholy",
    577: "havoc", 581: "vengeance", 253: "beast_mastery", 254: "marksmanship", 255: "survival", 62: "arcane",
    63: "fire", 64: "frost", 268: "brewmaster", 270: "mistweaver", 269: "windwalker", 65: "holy", 66: "protection",
    70: "retribution", 256: "discipline", 257: "holy", 258: "shadow", 259: "assassination", 260: "outlaw",
    261: "subtlety", 262: "elemental", 263: "enhancement", 264: "restoration", 265: "affliction", 266: "demonology",
    267: "destruction", 71: "arms", 72: "fury", 73: "protection", 1467: "devastation", 1468: "preservation",
    1473: "augmentation",
}
SPEC_FR = {"équilibre": "balance", "farouche": "feral", "gardien": "guardian", "restauration": "restoration",
           "sang": "blood", "givre": "frost", "impie": "unholy", "dévastation": "havoc", "vengeance": "vengeance",
           "maîtrise des bêtes": "beast_mastery", "précision": "marksmanship", "survie": "survival",
           "arcanes": "arcane", "feu": "fire", "maître brasseur": "brewmaster", "tisse-brume": "mistweaver",
           "marche-vent": "windwalker", "sacré": "holy", "protection": "protection", "vindicte": "retribution",
           "discipline": "discipline", "ombre": "shadow", "assassinat": "assassination", "hors-la-loi": "outlaw",
           "finesse": "subtlety", "élémentaire": "elemental", "amélioration": "enhancement",
           "affliction": "affliction", "démonologie": "demonology", "destruction": "destruction", "armes": "arms",
           "fureur": "fury", "préservation": "preservation", "augmentation": "augmentation"}
RACES = {"Scourge": "undead", "EarthenDwarf": "earthen", "Earthen": "earthen"}
PROFESSIONS = {"alchimie": "alchemy", "forge": "blacksmithing", "enchantement": "enchanting",
               "ingénierie": "engineering", "herboristerie": "herbalism", "calligraphie": "inscription",
               "joaillerie": "jewelcrafting", "travail du cuir": "leatherworking", "minage": "mining",
               "dépeçage": "skinning", "couture": "tailoring"}
ROLES = {"guardian": "tank", "blood": "tank", "vengeance": "tank", "brewmaster": "tank", "protection": "tank",
         "restoration": "heal", "mistweaver": "heal", "holy": "heal", "discipline": "heal", "preservation": "heal"}


def _token(text):
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", str(text or "")).lower()
    return re.sub(r"[^a-z0-9_]", "", text.replace(" ", "_"))


def parse_item_string(item_string):
    """« item:ID:enchant:gem1:gem2:gem3:gem4:suffix:unique:linkLevel:spec:modMask:context:nBonus:b...:nMods:t:v... »"""
    parts = str(item_string or "").split(":")
    if len(parts) < 2 or parts[0] != "item":
        return None

    def num(i):
        try:
            return int(parts[i]) if i < len(parts) and parts[i] else 0
        except ValueError:
            return 0

    item = {"id": num(1), "enchant": num(2), "gems": [g for g in (num(3), num(4), num(5), num(6)) if g],
            "spec": num(10), "context": num(12), "bonus": [], "mods": {}}
    n_bonus = num(13)
    item["bonus"] = [num(14 + i) for i in range(n_bonus) if num(14 + i)]
    pos = 14 + n_bonus
    for i in range(num(pos)):
        item["mods"][num(pos + 1 + 2 * i)] = num(pos + 2 + 2 * i)
    return item


def spec_token(snapshot):
    for e in snapshot.get("equipment") or []:
        parsed = parse_item_string(e.get("itemString"))
        if parsed and parsed["spec"] in SPEC_IDS:
            return SPEC_IDS[parsed["spec"]]
    spec = str((snapshot.get("character") or {}).get("specialization") or "").strip().lower()
    return SPEC_FR.get(spec, _token(spec))


def profile(snapshot, region=""):
    """Texte du profil SimulationCraft, ou "" sans personnage. `region` : si l'addon ne l'a pas donnée."""
    c = dict(snapshot.get("character") or {})
    c["region"] = c.get("region") or region
    if not c.get("name"):
        return ""
    klass = str(c.get("classFile") or "").lower()
    spec = spec_token(snapshot)
    race = RACES.get(c.get("raceFile", ""), _token(c.get("raceFile", "")))
    profs = []
    for p in snapshot.get("professions") or []:
        name = PROFESSIONS.get(str(p.get("name", "")).strip().lower())
        if name:
            profs.append(f"{name}={p.get('level', 0)}")
    lines = [f"# {c['name']} - {c.get('specialization', '')} - {time.strftime('%Y-%m-%d %H:%M')} - "
             f"{c.get('region', '')}/{c.get('realm', '')}",
             "# Généré par WoW Assistant (données de l'addon HermesAssistant), format de l'addon SimulationCraft",
             f'{klass}="{c["name"]}"', f"level={c.get('level', 0)}", f"race={race}",
             f"region={str(c.get('region') or '').lower()}", f"server={_token(c.get('realm', ''))}",
             f"role={ROLES.get(spec, 'attack')}", f"spec={spec}"]
    if profs:
        lines.append("professions=" + "/".join(profs))
    loadout = (snapshot.get("talents") or {}).get("loadout")
    if loadout:
        lines.append(f"talents={loadout}")
    lines.append("")
    for e in sorted(snapshot.get("equipment") or [], key=lambda e: list(SLOTS).index(int(e.get("slot", 0)))
                    if int(e.get("slot", 0)) in SLOTS else 99):
        slot = SLOTS.get(int(e.get("slot", 0) or 0))
        item = parse_item_string(e.get("itemString"))
        if not slot or not item or not item["id"]:
            continue
        fields = [f"{slot}=", f"id={item['id']}"]
        if item["enchant"]:
            fields.append(f"enchant_id={item['enchant']}")
        if item["gems"]:
            fields.append("gem_id=" + "/".join(str(g) for g in item["gems"]))
        if item["bonus"]:
            fields.append("bonus_id=" + "/".join(str(b) for b in item["bonus"]))
        if item["mods"].get(9):                      # niveau du joueur quand l'objet a été obtenu
            fields.append(f"drop_level={item['mods'][9]}")
        if item["context"]:
            fields.append(f"context={item['context']}")
        lines.append(f"# {e.get('name', '')} ({e.get('ilvl', '')})")
        lines.append(",".join(fields))
    return "\n".join(lines) + "\n"


RAIDBOTS_URL = "https://www.raidbots.com/simbot/droptimizer"
RESULT_PROMPT = ("Voici le résultat d'une simulation Raidbots que je viens de faire (texte copié de la page du "
                 "rapport). Dis-moi en quelques lignes : les 3 à 5 meilleures améliorations, d'où elles viennent, "
                 "et ce que je devrais viser en premier. Enregistre la conclusion dans la base de connaissances "
                 "(thème équipement) avec le lien du rapport s'il y est.\n\n")


def looks_like_result(text):
    text = str(text or "")
    return len(text) > 40 and bool(re.search(r"raidbots|droptimizer|top gear|dps|\bilvl\b|\+\d+(?:[.,]\d+)?\s*%",
                                             text, re.I))


def report_link(text):
    m = re.search(r"https?://(?:www\.)?raidbots\.com/simbot/report/[A-Za-z0-9]+", str(text or ""))
    return m.group(0) if m else ""
