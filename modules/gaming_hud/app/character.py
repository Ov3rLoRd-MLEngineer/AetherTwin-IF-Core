"""
Gestion du personnage pour WoW Assistant
"""

# Couleurs de classe officielles (clé = classFile fourni par l'addon)
CLASS_COLORS = {
    "DEATHKNIGHT": (196, 30, 58),
    "DEMONHUNTER": (163, 48, 201),
    "DRUID": (255, 124, 10),
    "EVOKER": (51, 147, 127),
    "HUNTER": (170, 211, 114),
    "MAGE": (63, 199, 235),
    "MONK": (0, 255, 152),
    "PALADIN": (244, 140, 186),
    "PRIEST": (255, 255, 255),
    "ROGUE": (255, 244, 104),
    "SHAMAN": (0, 112, 221),
    "WARLOCK": (135, 136, 238),
    "WARRIOR": (198, 155, 109),
}
FACTION_COLORS = {"Alliance": (74, 141, 255), "Horde": (214, 48, 49)}

# Disposition de la fenêtre de personnage : (numéro d'emplacement WoW, libellé)
EQUIPMENT_LAYOUT = {
    "left": [(1, "Tête"), (2, "Cou"), (3, "Épaules"), (15, "Dos"),
             (5, "Torse"), (4, "Chemise"), (19, "Tabard"), (9, "Poignets")],
    "right": [(10, "Mains"), (6, "Taille"), (7, "Jambes"), (8, "Pieds"),
              (11, "Anneau 1"), (12, "Anneau 2"), (13, "Bijou 1"), (14, "Bijou 2")],
    "bottom": [(16, "Main droite"), (17, "Main gauche")],
}


def format_duration(seconds):
    """3 725 -> '1 h 2 min' ; 90 000 -> '1 j 1 h 0 min'"""
    seconds = int(seconds or 0)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} j {hours} h {minutes} min"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


class Character:
    """Données et statistiques du personnage"""

    def __init__(self):
        self.name = ""
        self.title_name = ""    # nom + titre, comme en haut de la fenêtre de personnage
        self.realm = ""
        self.region = ""        # « EU », « US »… (addon 1.7) : règle l'API Battle.net
        self.level = 1
        self.class_name = ""
        self.class_file = ""
        self.race = ""
        self.race_file = ""
        self.faction = ""
        self.sex = 0
        self.spec = ""
        self.ilvl = 0
        self.xp = 0
        self.xp_max = 0
        self.rested_xp = 0
        self.money = 0          # en cuivre
        self.zone = ""
        self.subzone = ""
        self.armor = 0
        self.crit = 0
        self.haste = 0
        self.mastery = 0
        self.versatility = 0
        self.equipment = {}     # numéro d'emplacement -> objet équipé
        self.played_total = 0   # /played, en secondes
        self.played_level = 0
        self.played_updated = 0
        self.stats = {
            "strength": 0,
            "agility": 0,
            "stamina": 0,
            "intellect": 0,
            "spirit": 0
        }

    # ------------------------------------------------------------------ mise à jour
    def update_from_dict(self, data):
        """Met à jour depuis les données de l'addon. Retourne True si quelque chose a changé."""
        if not data:
            return False
        new_values = {
            "name": data.get("name", self.name),
            "title_name": data.get("titleName", self.title_name),
            "realm": data.get("realm", self.realm),
            "region": data.get("region", self.region),
            "level": data.get("level", self.level),
            "class_name": data.get("class", self.class_name),
            "class_file": data.get("classFile", self.class_file),
            "race": data.get("race", self.race),
            "race_file": data.get("raceFile", self.race_file),
            "faction": data.get("faction", self.faction),
            "sex": data.get("sex", self.sex),
            "spec": data.get("specialization", self.spec),
            "ilvl": data.get("ilvl", self.ilvl),
            "xp": data.get("xp", self.xp),
            "xp_max": data.get("xpMax", self.xp_max),
            "rested_xp": data.get("restedXP", self.rested_xp),
            "money": data.get("money", self.money),
            "zone": data.get("zone", self.zone),
            "subzone": data.get("subzone", self.subzone),
            "armor": data.get("armor", self.armor),
            "crit": data.get("crit", self.crit),
            "haste": data.get("haste", self.haste),
            "mastery": data.get("mastery", self.mastery),
            "versatility": data.get("versatility", self.versatility),
        }
        stats = data.get("stats")
        if isinstance(stats, dict) and stats:
            merged = dict(self.stats)
            merged.update({k: v for k, v in stats.items() if k in merged})
            new_values["stats"] = merged

        changed = False
        for attr, value in new_values.items():
            if getattr(self, attr) != value:
                setattr(self, attr, value)
                changed = True
        return changed

    def load_equipment(self, items):
        """Charge les objets équipés. True si quelque chose a changé."""
        new = {}
        for raw in items or []:
            slot = raw.get("slot")
            if slot is not None and raw.get("id"):
                new[int(slot)] = raw
        changed = new != self.equipment
        self.equipment = new
        return changed

    def load_played(self, data):
        """Charge le /played : {'total': s, 'level': s, 'updated': epoch}"""
        if not data:
            return False
        total, level = data.get("total", 0), data.get("level", 0)
        changed = (total, level) != (self.played_total, self.played_level)
        self.played_total, self.played_level = total, level
        self.played_updated = data.get("updated", 0)
        return changed

    def load_character(self, char_data):
        """Charge les données depuis un dict (remet à zéro ce qui manque)"""
        self.__init__()
        self.update_from_dict(char_data)

    def save_character(self):
        """Retourne les données sous forme de dict"""
        return {
            "name": self.name,
            "realm": self.realm,
            "level": self.level,
            "class": self.class_name,
            "classFile": self.class_file,
            "race": self.race,
            "raceFile": self.race_file,
            "faction": self.faction,
            "sex": self.sex,
            "specialization": self.spec,
            "ilvl": self.ilvl,
            "xp": self.xp,
            "xpMax": self.xp_max,
            "restedXP": self.rested_xp,
            "money": self.money,
            "zone": self.zone,
            "subzone": self.subzone,
            "stats": dict(self.stats),
        }

    # ------------------------------------------------------------------ calculs
    @property
    def display_title(self):
        return self.title_name or self.name

    @property
    def subtitle(self):
        """'Druidesse Farouche de niveau 48'"""
        who = " ".join(part for part in (self.class_name, self.spec) if part)
        return f"{who} de niveau {self.level}".strip()

    def primary_stat(self):
        """(libellé, valeur) de la caractéristique principale (la plus haute)."""
        options = [("Force", "strength"), ("Agilité", "agility"), ("Intelligence", "intellect")]
        label, key = max(options, key=lambda o: self.stats.get(o[1], 0))
        return label, self.stats.get(key, 0)

    @property
    def key(self):
        """Identifiant unique (personnage + serveur), utilisé pour l'historique"""
        return f"{self.name}-{self.realm}" if self.realm else self.name

    @property
    def xp_percent(self):
        if not self.xp_max:
            return 0.0
        return max(0.0, min(100.0, 100.0 * self.xp / self.xp_max))

    @property
    def class_color(self):
        return CLASS_COLORS.get(self.class_file.upper(), (255, 255, 255))

    @property
    def faction_color(self):
        return FACTION_COLORS.get(self.faction, (200, 200, 200))

    @property
    def location(self):
        if self.zone and self.subzone and self.subzone != self.zone:
            return f"{self.zone} - {self.subzone}"
        return self.zone

    @staticmethod
    def split_money(copper):
        copper = int(copper or 0)
        return copper // 10000, (copper // 100) % 100, copper % 100

    @staticmethod
    def format_money(copper):
        gold, silver, cop = Character.split_money(copper)
        return f"{gold:,} or {silver} arg {cop} cu".replace(",", " ")

    def update_stats(self, stat_name, value):
        if stat_name in self.stats:
            self.stats[stat_name] = value

    def get_stat(self, stat_name):
        return self.stats.get(stat_name, 0)

    def __str__(self):
        return f"{self.name} - Niveau {self.level} {self.class_name}"
