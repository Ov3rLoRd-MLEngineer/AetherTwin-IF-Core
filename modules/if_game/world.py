"""« Fuma & Inoue : Les Gardiens de l'Éther » — monde, règles et narration.

Principe de sûreté : **le modèle propose, le code valide et applique.**
- L'état du monde est un JSON structuré (`World`), seul le code le modifie.
- Les actions du joueur sont analysées par le code (`parse_action`), jamais par le modèle.
- Un lieu ou une réplique proposés par le modèle sont validés (forme, longueurs, ton calme) ; refusés, ils sont
  remplacés par le générateur procédural, déterministe pour une graine donnée. Sans modèle, le jeu est complet.
- Pas de combat, pas d'échec punitif : l'énergie d'Inoue baisse en marchant, Fuma propose le repos, une
  énigme ratée donne un indice.
"""
from __future__ import annotations

import json
import random
import re
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

Propose = Callable[[str], str]  # prompt -> texte (JSON attendu) ; branché sur le Hub

DIRECTIONS = {"nord": "sud", "sud": "nord", "est": "ouest", "ouest": "est", "haut": "bas", "bas": "haut"}
ALIASES = {"n": "nord", "s": "sud", "e": "est", "o": "ouest", "monter": "haut", "descendre": "bas"}
MAX_ENERGY = 10
# Le jeu reste calme : un texte du modèle qui contient l'un de ces mots est refusé.
HARSH = re.compile(r"\b(tu[eé]|tuer|meurtre|sang|cadavre|combat|attaqu|arme|ennemi|guerre|mort|mourir|bless|"
                   r"terreur|monstre|kill|blood|dead|attack|weapon)\w*", re.I)

PLACES = ["Jardin", "Bibliothèque", "Lac", "Clairière", "Observatoire", "Pont", "Grotte", "Serre", "Phare", "Verger"]
QUALITIES = ["des brumes dorées", "aux lucioles", "des murmures", "suspendu", "de cristal", "endormi",
             "des vents tièdes", "aux mille reflets", "de nacre", "des marées calmes"]
DETAILS = ["Des fils de lumière flottent lentement entre les pierres.",
           "Une mousse douce étouffe chaque pas.",
           "L'air sent la pluie d'été et le papier ancien.",
           "Des cloches de verre tintent au moindre souffle.",
           "Des reflets d'aurore glissent sur l'eau immobile.",
           "Une chaleur tranquille monte du sol."]
ITEMS = ["plume d'étoile", "galet chantant", "fiole de brume", "clé de nacre", "graine lumineuse",
         "carte pliée", "lanterne tiède", "coquillage d'éther"]
RIDDLES = [("Plus j'éclaire, plus l'ombre grandit derrière toi. Qui suis-je ?", ["lumiere", "la lumiere"]),
           ("Je me repose le jour et veille la nuit dans le ciel. Qui suis-je ?", ["lune", "la lune"]),
           ("On me garde quand on me donne. Qu'est-ce que je suis ?", ["promesse", "une promesse", "la parole"]),
           ("Je tombe sans me blesser et je remonte en nuage. Qui suis-je ?", ["pluie", "la pluie", "eau"])]


def plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii").strip(" .!?'\"")


@dataclass
class Place:
    id: str
    name: str
    description: str
    exits: dict[str, str] = field(default_factory=dict)  # direction -> id du lieu, ou "" si pas encore exploré
    items: list[str] = field(default_factory=list)
    riddle: dict[str, Any] | None = None  # {"question", "answers", "solved", "hint"}
    origin: str = "procédural"  # « procédural » ou « modèle local »
    pos: list[int] | None = None  # [x, y, niveau] sur la carte du monde (nord = y − 1, haut = niveau + 1)


@dataclass
class World:
    seed: int
    turn: int = 0
    here: str = "sanctuaire"
    energy: int = MAX_ENERGY
    inventory: list[str] = field(default_factory=list)
    places: dict[str, Place] = field(default_factory=dict)
    journal: list[str] = field(default_factory=list)
    riddles_solved: int = 0

    # -- création et sauvegarde
    @classmethod
    def new(cls, seed: int) -> World:
        world = cls(seed=seed)
        world.places["sanctuaire"] = Place(
            "sanctuaire", "Sanctuaire de l'Éther",
            "Un cercle de pierres claires où Inoue, gardienne de la lumière, et Fuma, gardien du repos, "
            "veillent ensemble. Des chemins s'ouvrent dans plusieurs directions.",
            exits={"nord": "", "est": "", "ouest": ""}, items=["lanterne tiède"], pos=[0, 0, 0])
        return world

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> World:
        places = {pid: Place(**p) for pid, p in data.get("places", {}).items()}
        world = cls(**{k: v for k, v in data.items() if k != "places"})
        world.places = places
        world.validate()
        if any(p.pos is None for p in places.values()):
            assign_positions(world)  # sauvegarde d'avant la carte : positions déduites des chemins
        return world

    def at(self, pos: list[int]) -> Place | None:
        return next((p for p in self.places.values() if p.pos == pos), None)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> World:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def validate(self) -> None:
        """Invariants du monde ; lève `ValueError` si une sauvegarde est incohérente."""
        if self.here not in self.places:
            raise ValueError(f"lieu courant inconnu : {self.here}")
        if not 0 <= self.energy <= MAX_ENERGY:
            raise ValueError("énergie hors bornes")
        for place in self.places.values():
            for direction, target in place.exits.items():
                if direction not in DIRECTIONS or (target and target not in self.places):
                    raise ValueError(f"sortie invalide : {place.id} {direction} -> {target}")

    @property
    def place(self) -> Place:
        return self.places[self.here]

    def rng(self, salt: str) -> random.Random:
        return random.Random(f"{self.seed}:{salt}")  # noqa: S311 — jeu, pas de cryptographie

    def log(self, text: str) -> str:
        self.journal = (self.journal + [text])[-60:]
        return text


# -- carte du monde : chaque lieu a une case ; aller au nord puis au sud ramène au même lieu ----------------------
VECTORS = {"nord": (0, -1, 0), "sud": (0, 1, 0), "est": (1, 0, 0), "ouest": (-1, 0, 0), "haut": (0, 0, 1),
           "bas": (0, 0, -1)}


def step(pos: list[int], direction: str) -> list[int]:
    dx, dy, dz = VECTORS[direction]
    return [pos[0] + dx, pos[1] + dy, pos[2] + dz]


def free_near(world: World, pos: list[int]) -> list[int]:
    """Case libre la plus proche (même niveau), pour une ancienne sauvegarde dont deux lieux se chevauchent."""
    taken = {tuple(p.pos) for p in world.places.values() if p.pos is not None}
    for radius in range(0, 50):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) == radius and (pos[0] + dx, pos[1] + dy, pos[2]) not in taken:
                    return [pos[0] + dx, pos[1] + dy, pos[2]]
    raise ValueError("carte pleine")


def assign_positions(world: World) -> None:
    """Positions déduites des chemins (parcours en largeur depuis le sanctuaire)."""
    for place in world.places.values():
        place.pos = None
    start = "sanctuaire" if "sanctuaire" in world.places else next(iter(world.places))
    world.places[start].pos = [0, 0, 0]
    queue = [start]
    while queue:
        place = world.places[queue.pop(0)]
        for direction, target in place.exits.items():
            other = world.places.get(target) if target else None
            if other is not None and other.pos is None:
                other.pos = free_near(world, step(place.pos, direction))
                queue.append(other.id)
    for place in world.places.values():
        if place.pos is None:
            place.pos = free_near(world, [0, 0, 0])


def link_neighbours(world: World, place: Place) -> None:
    """Un nouveau lieu se raccorde aux voisins déjà connus qui ont un chemin inexploré vers sa case."""
    for direction in DIRECTIONS:
        neighbour = world.at(step(place.pos, direction))
        back = DIRECTIONS[direction]
        if neighbour is not None and neighbour.exits.get(back) == "":
            neighbour.exits[back] = place.id
            place.exits[direction] = neighbour.id


# -- génération des lieux ------------------------------------------------------------------------------------------
def procedural_place(world: World, place_id: str, came_from: str) -> Place:
    rng = world.rng(place_id)
    name = f"{rng.choice(PLACES)} {rng.choice(QUALITIES)}"
    description = " ".join(rng.sample(DETAILS, 2))
    exits = {DIRECTIONS[came_from]: world.here}
    for direction in rng.sample([d for d in DIRECTIONS if d != DIRECTIONS[came_from]], rng.randint(1, 2)):
        exits[direction] = ""
    items = [rng.choice(ITEMS)] if rng.random() < 0.5 else []
    riddle = None
    if rng.random() < 0.35:
        question, answers = rng.choice(RIDDLES)
        riddle = {"question": question, "answers": answers, "solved": False,
                  "hint": f"La réponse commence par « {answers[0][0].upper()} »."}
    return Place(place_id, name, description, exits, items, riddle)


def place_prompt(world: World, direction: str) -> str:
    return (
        "Tu inventes un lieu pour un jeu d'exploration CALME et poétique (aucune violence, aucun danger), "
        "« Fuma & Inoue : Les Gardiens de l'Éther ». Les gardiens arrivent depuis « "
        f"{world.place.name} » en allant vers le {direction}.\n"
        'Réponds uniquement en JSON : {"name": "nom du lieu (2 à 6 mots)", '
        '"description": "deux phrases sensorielles et apaisantes", '
        '"item": "un petit objet à ramasser, ou une chaîne vide"}'
    )


def validate_proposal(text: str, known_names: set[str]) -> dict[str, str] | None:
    """Ce que le code accepte d'un lieu proposé par le modèle ; `None` = refus (le procédural prend le relais)."""
    match = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", text, flags=re.S), flags=re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    name, description = str(data.get("name", "")).strip(), str(data.get("description", "")).strip()
    item = str(data.get("item", "")).strip()
    if not (3 <= len(name) <= 48 and 20 <= len(description) <= 320 and len(item) <= 40):
        return None
    if name in known_names or any(HARSH.search(t) for t in (name, description, item)):
        return None
    if "\n" in name or "{" in description:
        return None
    return {"name": name, "description": description, "item": item}


def create_place(world: World, direction: str, propose: Propose | None) -> Place:
    place_id = f"lieu{len(world.places)}"
    place = procedural_place(world, place_id, direction)
    if propose is not None:
        try:
            proposal = validate_proposal(propose(place_prompt(world, direction)),
                                         {p.name for p in world.places.values()})
        except Exception:  # noqa: BLE001 — modèle indisponible : le procédural suffit
            proposal = None
        if proposal:
            place.name, place.description, place.origin = proposal["name"], proposal["description"], "modèle local"
            place.items = [proposal["item"]] if proposal["item"] else []
    return place


# -- actions -------------------------------------------------------------------------------------------------------
def parse_action(text: str) -> tuple[str, str]:
    """(verbe, argument) reconnus par le code. Tout le reste est « inconnu »."""
    words = plain(text).split()
    if not words:
        return "inconnu", ""
    verb, rest = words[0], " ".join(words[1:])
    if verb in ALIASES or verb in DIRECTIONS:
        return "aller", ALIASES.get(verb, verb)
    if verb in ("aller", "va", "vers") and rest:
        target = rest.split()[-1]
        return "aller", ALIASES.get(target, target)
    if verb in ("regarder", "voir", "observer", "l"):
        return "regarder", ""
    if verb in ("prendre", "ramasser") and rest:
        return "prendre", re.sub(r"^(le|la|les|l|un|une)\s+", "", rest)
    if verb in ("inventaire", "sac", "i"):
        return "inventaire", ""
    if verb in ("repos", "reposer", "dormir", "pause"):
        return "repos", ""
    if verb in ("repondre", "reponse") and rest:
        return "repondre", rest
    if verb == "parler" and rest:
        return "parler", "fuma" if "fuma" in rest else "inoue" if "inoue" in rest else ""
    if verb in ("aide", "help", "?"):
        return "aide", ""
    return "inconnu", plain(text)


HELP = ("Actions : nord / sud / est / ouest / haut / bas, regarder, prendre <objet>, inventaire, repos, "
        "répondre <mot>, parler à Inoue, parler à Fuma, aide.")
LINES = {"inoue": ["Inoue sourit : « Chaque pas éclaire un peu plus le chemin. »",
                   "Inoue fait briller sa paume : « Regarde, la lumière aime les curieux. »"],
         "fuma": ["Fuma murmure : « Rien ne presse. Le monde nous attend. »",
                  "Fuma s'assoit un instant : « Le repos aussi est une découverte. »"]}


def describe(world: World) -> str:
    place = world.place
    exits = ", ".join(f"{d}{'' if t else ' (inconnu)'}" for d, t in place.exits.items()) or "aucune"
    parts = [f"{place.name}. {place.description}", f"Sorties : {exits}."]
    if place.items:
        parts.append(f"Ici : {', '.join(place.items)}.")
    if place.riddle and not place.riddle["solved"]:
        parts.append(f"Une inscription murmure : « {place.riddle['question']} »")
    return " ".join(parts)


def act(world: World, text: str, propose: Propose | None = None, talk: Propose | None = None) -> str:
    """Applique une action du joueur et rend la narration. Seul point qui modifie le monde."""
    verb, arg = parse_action(text)
    world.turn += 1
    place = world.place
    if verb == "aide":
        return world.log(HELP)
    if verb == "regarder":
        return world.log(describe(world))
    if verb == "inventaire":
        return world.log(f"Dans le sac : {', '.join(world.inventory) or 'rien encore'}. Énergie d'Inoue : "
                         f"{world.energy}/{MAX_ENERGY}.")
    if verb == "repos":
        world.energy = MAX_ENERGY
        return world.log("Fuma étend un voile d'ombre douce. Les gardiens se reposent ; Inoue rayonne à nouveau "
                         f"({MAX_ENERGY}/{MAX_ENERGY}).")
    if verb == "prendre":
        found = next((item for item in place.items if plain(item) == arg or arg in plain(item)), None)
        if found is None:
            return world.log(f"Il n'y a pas de « {arg} » ici.")
        place.items.remove(found)
        world.inventory.append(found)
        return world.log(f"Inoue ramasse : {found}.")
    if verb == "repondre":
        riddle = place.riddle
        if not riddle or riddle["solved"]:
            return world.log("Aucune inscription n'attend de réponse ici.")
        if plain(arg) in {plain(a) for a in riddle["answers"]}:
            riddle["solved"] = True
            world.riddles_solved += 1
            world.energy = MAX_ENERGY
            return world.log("L'inscription s'illumine et se dissout en poussière d'étoiles. Inoue retrouve "
                             "toute sa lumière.")
        return world.log(f"Fuma penche la tête : « Pas tout à fait. » {riddle['hint']}")
    if verb == "parler":
        if not arg:
            return world.log("Parler à qui ? Inoue ou Fuma.")
        line = ""
        if talk is not None:
            try:
                candidate = re.sub(r"<think>.*?</think>", "", talk(talk_prompt(world, arg)), flags=re.S).strip()
                if 10 <= len(candidate) <= 280 and not HARSH.search(candidate) and "{" not in candidate:
                    line = f"{arg.capitalize()} : « {candidate.strip(chr(34) + '«» ')} »"
            except Exception:  # noqa: BLE001 — réplique type si le modèle ne répond pas
                line = ""
        return world.log(line or world.rng(f"{arg}{world.turn}").choice(LINES[arg]))
    if verb == "aller":
        if arg not in place.exits:
            return world.log(f"Pas de chemin vers « {arg} » ici. {HELP.split('.')[0]}.")
        if world.energy <= 0:
            return world.log("Inoue vacille doucement. Fuma propose une pause : tape « repos ».")
        target = place.exits[arg]
        if not target:
            existing = world.at(step(place.pos, arg))
            if existing is not None:  # la case est déjà un lieu connu : le chemin y mène, dans les deux sens
                existing.exits[DIRECTIONS[arg]] = place.id
                target = existing.id
            else:
                new = create_place(world, arg, propose)
                new.pos = step(place.pos, arg)
                world.places[new.id] = new
                link_neighbours(world, new)
                target = new.id
            place.exits[arg] = target
        world.here = target
        world.energy -= 1
        world.validate()
        return world.log(describe(world))
    return world.log(f"Les gardiens ne comprennent pas. {HELP}")


def talk_prompt(world: World, who: str) -> str:
    persona = ("Inoue, gardienne de la lumière et de l'énergie, enjouée et curieuse" if who == "inoue"
               else "Fuma, gardien de l'ombre et du repos, posé et bienveillant")
    return (f"Tu es {persona}, dans un jeu d'exploration calme. Lieu : {world.place.name} — "
            f"{world.place.description} Dis une seule réplique courte (une ou deux phrases), apaisante, en "
            "français, sans guillemets.")


def view(world: World) -> dict[str, Any]:
    """Ce que l'interface affiche."""
    place = world.place
    return {"seed": world.seed, "turn": world.turn, "place": place.name, "place_id": place.id,
            "description": place.description, "origin": place.origin,
            "exits": place.exits, "items": place.items, "energy": world.energy, "max_energy": MAX_ENERGY,
            "inventory": world.inventory, "riddles_solved": world.riddles_solved, "explored": len(world.places),
            "riddle": place.riddle["question"] if place.riddle and not place.riddle["solved"] else "",
            "journal": world.journal[-12:], "pos": place.pos, "bag": bag(world.inventory),
            "map": [{"id": p.id, "name": p.name, "pos": p.pos, "exits": {d: bool(t) for d, t in p.exits.items()},
                     "riddle": bool(p.riddle and not p.riddle["solved"])} for p in world.places.values()]}


def bag(inventory: list[str]) -> list[list[Any]]:
    """Inventaire regroupé : [[objet, nombre]], du plus fréquent au plus rare (l'ordre d'arrivée départage).
    « Une plume de nuage » et « plume de nuage » sont le même objet."""
    names: dict[str, str] = {}
    counts: dict[str, int] = {}
    for item in inventory:
        bare = re.sub(r"^(?:(?:une?|le|la|les|des)\s+|l['’]\s*)", "", item.strip(), flags=re.I)
        key = plain(bare)
        names.setdefault(key, bare[:1].lower() + bare[1:])
        counts[key] = counts.get(key, 0) + 1
    return [[names[key], n] for key, n in sorted(counts.items(), key=lambda kv: -kv[1])]
