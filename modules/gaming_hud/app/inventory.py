"""
Gestion de l'inventaire pour WoW Assistant
"""

QUALITY_NAMES = {0: "Médiocre", 1: "Commun", 2: "Inhabituel", 3: "Rare", 4: "Épique",
                 5: "Légendaire", 6: "Artefact", 7: "Héritage"}


class Inventory:
    """Objets présents dans les sacs"""

    def __init__(self):
        self.items = []
        self.capacity = 30      # nombre d'emplacements au total
        self.slots_used = None  # None = inconnu (pas encore de données du jeu)

    # ------------------------------------------------------------------ chargement
    def load_from_dict(self, data):
        """Charge les sacs depuis l'addon. Retourne True si quelque chose a changé."""
        if not data:
            return False
        items = []
        for raw in data.get("items", []):
            items.append({
                "id": raw.get("id", 0),
                "name": raw.get("name", "") or f"Objet {raw.get('id', '?')}",
                "quantity": raw.get("count", 1),
                "type": raw.get("type", "") or "Divers",
                "quality": raw.get("quality", 0),
            })
        capacity = data.get("capacity", self.capacity) or self.capacity
        used = data.get("used", self.slots_used)
        changed = (items != self.items or capacity != self.capacity or used != self.slots_used)
        self.items, self.capacity, self.slots_used = items, capacity, used
        return changed

    # ------------------------------------------------------------------ gestion manuelle
    def add_item(self, item_id, name, quantity=1, item_type="consumable"):
        existing = self.get_item(item_id)
        if existing:
            existing["quantity"] += quantity
            return
        self.items.append({"id": item_id, "name": name, "quantity": quantity,
                           "type": item_type, "quality": 1})

    def remove_item(self, item_id, quantity=1):
        for item in self.items:
            if item["id"] == item_id:
                if item["quantity"] >= quantity:
                    item["quantity"] -= quantity
                    if item["quantity"] <= 0:
                        self.items.remove(item)
                    return True
        return False

    def clear_inventory(self):
        self.items.clear()
        self.slots_used = None

    # ------------------------------------------------------------------ requêtes
    def get_item(self, item_id):
        for item in self.items:
            if item["id"] == item_id:
                return item
        return None

    def count_item(self, item_id=None, name=None):
        """Quantité totale d'un objet, par identifiant ou (à défaut) par nom exact."""
        total = 0
        for item in self.items:
            if item_id is not None and item["id"] == item_id:
                total += item["quantity"]
            elif item_id is None and name and item["name"].lower() == name.lower():
                total += item["quantity"]
        return total

    def name_of(self, item_id):
        item = self.get_item(item_id)
        return item["name"] if item else ""

    def find(self, text):
        """Recherche par morceau de nom (insensible à la casse)."""
        text = (text or "").lower()
        return [i for i in self.items if text in i["name"].lower()]

    def get_items_by_type(self, item_type):
        return [item for item in self.items if item["type"] == item_type]

    def count_by_type(self):
        """{type: quantité totale}, du plus fourni au moins fourni."""
        totals = {}
        for item in self.items:
            totals[item["type"]] = totals.get(item["type"], 0) + item["quantity"]
        return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))

    def top_items(self, n=6):
        return sorted(self.items, key=lambda i: i["quantity"], reverse=True)[:n]

    def get_total_items(self):
        return sum(item["quantity"] for item in self.items)

    def free_slots(self):
        if self.slots_used is None:
            return max(0, self.capacity - self.get_total_items())
        return max(0, self.capacity - self.slots_used)

    def is_full(self):
        return self.free_slots() == 0
