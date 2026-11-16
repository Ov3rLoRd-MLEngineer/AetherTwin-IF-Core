"""
Système de craft pour WoW Assistant
Les métiers viennent de l'addon ; les recettes viennent d'un fichier recipes.json que tu remplis
(l'addon ne peut pas lister les recettes sans ouvrir la fenêtre du métier).

Format de recipes.json :
{"recipes": [
  {"id": 1, "name": "Nom de la recette", "profession": "Alchimie", "required_level": 1,
   "materials": [{"item_id": 12345, "name": "Nom de l'objet", "quantity": 2}]}
]}
"""
import json
import os


class CraftSystem:
    """Métiers, recettes et calcul de ce qui est fabricable avec les sacs"""

    def __init__(self):
        self.professions = {}
        self.recipes = []

    # ------------------------------------------------------------------ métiers
    def load_professions(self, data):
        """Charge les métiers depuis l'addon. True si quelque chose a changé."""
        if data is None:
            return False
        new = {}
        for raw in data:
            name = raw.get("name")
            if not name:
                continue
            previous = self.professions.get(name, {})
            new[name] = {
                "level": raw.get("level", 0),
                "max_level": raw.get("max", 0),
                "recipes_known": previous.get("recipes_known", []),
                "skills": previous.get("skills", {}),
            }
        changed = new != self.professions
        self.professions = new
        return changed

    def add_profession(self, profession_name, level=1):
        self.professions[profession_name] = {
            "level": level, "max_level": 0, "recipes_known": [], "skills": {}
        }

    def get_profession_info(self, profession_name):
        return self.professions.get(profession_name, None)

    def update_profession_skill(self, profession_name, skill_name, value):
        if profession_name in self.professions:
            self.professions[profession_name]["skills"][skill_name] = value

    # ------------------------------------------------------------------ recettes
    def load_recipes_file(self, path):
        """Charge recipes.json (ignoré s'il n'existe pas). Retourne le nombre de recettes."""
        if not path or not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"recipes.json illisible : {e}")
            return 0
        self.recipes = []
        for r in data.get("recipes", []):
            self.add_recipe(r.get("id"), r.get("name", ""), r.get("profession", ""),
                            r.get("required_level", 1), r.get("materials", []))
        return len(self.recipes)

    def add_recipe(self, recipe_id, name, profession, required_level=1, materials=None, source="file"):
        self.recipes.append({
            "id": recipe_id,
            "name": name,
            "profession": profession,
            "required_level": required_level,
            "materials": materials or [],
            "crafted": False,
            "source": source,
        })

    def load_game_recipes(self, recipes):
        """Recettes lues en jeu (fenêtre de métier ouverte) : remplacent les précédentes du jeu,
        sans toucher à celles de recipes.json. True si quelque chose a changé."""
        before = [r for r in self.recipes if r.get("source") == "game"]
        self.recipes = [r for r in self.recipes if r.get("source") != "game"]
        for profession, record in (recipes or {}).items():
            for recipe in record.get("list", []):
                materials = []
                for m in recipe.get("mats", []):
                    ids = m.get("ids", [])
                    if ids:
                        materials.append({"item_id": ids[0], "item_ids": ids,
                                          "name": m.get("name", ""), "quantity": m.get("quantity", 1)})
                self.add_recipe(recipe.get("id"), recipe.get("name", ""), profession, 0, materials, source="game")
        after = [r for r in self.recipes if r.get("source") == "game"]
        return before != after

    def recipes_for(self, profession_name):
        """Recettes d'un métier (le nom exporté peut différer légèrement du nom affiché : on tolère l'inclusion)."""
        exact = [r for r in self.recipes if r["profession"] == profession_name]
        if exact:
            return exact
        low = profession_name.lower()
        return [r for r in self.recipes
                if r["profession"].lower() in low or low in r["profession"].lower()]

    def craft_item(self, recipe_id):
        for recipe in self.recipes:
            if recipe["id"] == recipe_id:
                recipe["crafted"] = True
                return True
        return False

    def get_available_recipes(self, profession_name, player_level):
        """Recettes d'un métier dont le niveau requis est atteint.
        Utilise le niveau du métier si on le connaît, sinon le niveau du joueur."""
        info = self.professions.get(profession_name)
        level = info["level"] if info and info.get("level") else player_level
        return [r for r in self.recipes
                if r["profession"] == profession_name and r["required_level"] <= level]

    # ------------------------------------------------------------------ fabricable ?
    @staticmethod
    def _owned(material, inventory):
        """Quantité possédée. 'item_ids' = qualités alternatives d'un même composant (toutes comptent)."""
        ids = material.get("item_ids")
        if ids:
            return sum(inventory.count_item(item_id=i) for i in ids)
        return inventory.count_item(item_id=material.get("item_id"), name=material.get("name"))

    def missing_materials(self, recipe, inventory):
        """[(nom, manquant)] pour une seule fabrication."""
        missing = []
        for m in recipe["materials"]:
            need = m.get("quantity", 1)
            have = self._owned(m, inventory)
            if have < need:
                missing.append((m.get("name") or f"Objet {m.get('item_id')}", need - have))
        return missing

    def max_crafts(self, recipe, inventory):
        """Combien de fois on peut fabriquer la recette avec les sacs actuels."""
        counts = []
        for m in recipe["materials"]:
            need = max(1, m.get("quantity", 1))
            counts.append(self._owned(m, inventory) // need)
        return min(counts) if counts else 0

    def can_craft(self, recipe, inventory):
        return bool(recipe["materials"]) and self.max_crafts(recipe, inventory) >= 1

    def craftable_recipes(self, inventory, profession_name=None, player_level=None):
        """Recettes fabricables maintenant : [(recette, nombre_max)]"""
        result = []
        for recipe in self.recipes:
            if profession_name and recipe["profession"] != profession_name:
                continue
            info = self.professions.get(recipe["profession"])
            level = info["level"] if info and info.get("level") else player_level
            if level is not None and recipe["required_level"] > level:
                continue
            n = self.max_crafts(recipe, inventory)
            if n >= 1 and recipe["materials"]:
                result.append((recipe, n))
        return result
