"""
Suivi des quêtes pour WoW Assistant
"""

STATUS_LABELS = {"incomplete": "En cours", "complete": "À rendre", "failed": "Échouée"}


class QuestTracker:
    """Quêtes du journal. Statuts : incomplete (en cours), complete (à rendre), failed."""

    def __init__(self):
        self.quests = []
        self.max_quests = 35
        self.completed_total = 0   # quêtes terminées depuis la création du personnage

    # ------------------------------------------------------------------ chargement
    def load_from_dict(self, data):
        """Remplace tout le journal par celui de l'addon. True si quelque chose a changé."""
        if not data:
            return False
        quests = []
        for raw in data.get("list", []):
            status = raw.get("status", "incomplete")
            quests.append({
                "id": raw.get("id", 0),
                "name": raw.get("title", "") or f"Quête {raw.get('id', '?')}",
                "level": raw.get("level", 0),
                "status": status,
                "completed": status == "complete",
                "zone": raw.get("zone", ""),
                "task": bool(raw.get("task", False)),
                "freq": raw.get("freq", 0),
                "tracked": bool(raw.get("tracked", False)),
                "focus": bool(raw.get("focus", False)),
                "reward_xp": raw.get("rewardXP", 0),
                "reward_money": raw.get("rewardMoney", 0),
                "rewards": [{"name": r.get("name", ""), "count": r.get("count", 1), "quality": r.get("quality", 1)}
                            for r in raw.get("rewards", [])],
                "objectives": [{"text": o.get("text", ""), "done": bool(o.get("done", False)),
                                "have": o.get("have", 0), "need": o.get("need", 0)}
                               for o in raw.get("objectives", [])],
            })
        max_quests = data.get("max", self.max_quests) or self.max_quests
        completed_total = data.get("completedTotal", self.completed_total)
        changed = (quests != self.quests or max_quests != self.max_quests
                   or completed_total != self.completed_total)
        self.quests, self.max_quests = quests, max_quests
        self.completed_total = completed_total
        return changed

    # ------------------------------------------------------------------ gestion manuelle
    def add_quest(self, quest_id, name, level, status="incomplete"):
        self.quests.append({
            "id": quest_id, "name": name, "level": level, "status": status,
            "completed": status == "complete", "zone": "", "task": False, "objectives": [],
        })

    def complete_quest(self, quest_id):
        return self.update_quest_status(quest_id, "complete")

    def update_quest_status(self, quest_id, status):
        for quest in self.quests:
            if quest["id"] == quest_id:
                quest["status"] = status
                quest["completed"] = status == "complete"
                return True
        return False

    # ------------------------------------------------------------------ requêtes
    def get_quest_by_id(self, quest_id):
        for quest in self.quests:
            if quest["id"] == quest_id:
                return quest
        return None

    def get_incomplete_quests(self):
        return [q for q in self.quests if q["status"] == "incomplete"]

    def get_completed_quests(self):
        """Quêtes terminées, prêtes à être rendues."""
        return [q for q in self.quests if q["status"] == "complete"]

    def ready_to_turn_in(self):
        return self.get_completed_quests()

    def group_by_zone(self):
        """{zone: [quêtes]} en conservant l'ordre du journal."""
        groups = {}
        for quest in self.quests:
            groups.setdefault(quest["zone"] or "Divers", []).append(quest)
        return groups

    @staticmethod
    def progress(quest):
        """(objectifs terminés, objectifs totaux)"""
        objectives = quest.get("objectives", [])
        return sum(1 for o in objectives if o["done"]), len(objectives)

    @staticmethod
    def status_label(quest):
        return STATUS_LABELS.get(quest.get("status", "incomplete"), "En cours")

    def count(self):
        return len(self.quests)
