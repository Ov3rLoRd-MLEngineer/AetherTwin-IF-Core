"""
Fonctions du jeu selon sa variante (Retail, WoW Forever, Classic), d'après le dossier choisi (`_retail_`,
`_forever_`...) : l'appli cache ce qui n'existe pas dans la variante jouée au lieu d'afficher des cadres vides.

WoW Forever (relevé du 23/11/2026, sites de joueurs : à confirmer sur les notes officielles) : niveau 60, pas de
Mythique+, pas de Gouffres, pas de Grande Chambre forte (pas de saisons), pas de logis (ses décors ne servent que
sur Retail), pas de vol ; à la place : Camping et Héritage (« Legacy »). Raidbots / SimulationCraft ne simulent pas
Forever. Questie (base de quêtes) a une version Forever : l'addon HermesAssistant s'en sert s'il est installé.
"""
import gameversion

ABSENT = {
    "forever": {"mythicplus", "delves", "vault", "housing", "raidbots", "hero_talents"},
    "classic": {"mythicplus", "delves", "vault", "housing", "raidbots", "hero_talents", "warband"},
    "retail": set(),
}
LABELS = {"retail": "Retail", "forever": "WoW Forever", "classic": "Classic"}
MAX_LEVEL = {"forever": 60, "classic": 60}


def flavor(game_path=None):
    if game_path is None:
        from config import WoWConfig
        game_path = WoWConfig.WOW_PATH
    return gameversion.flavor(game_path)


def has(feature, game_path=None):
    """La fonction `feature` existe-t-elle dans la variante du jeu choisie ?"""
    return feature not in ABSENT.get(flavor(game_path), set())


def label(game_path=None):
    return LABELS.get(flavor(game_path), "Retail")


def coach_note(game_path=None):
    """Phrase ajoutée au contexte de l'assistant : la variante change les conseils (pas de M+ sur Forever...)."""
    f = flavor(game_path)
    if f == "forever":
        return ("Le joueur est sur WoW Forever (niveau maximum 60, pas de Mythique+, de Gouffres, de Grande Chambre "
                "forte, de logis ni de vol ; Camping et Héritage existent) : ne conseille que ce qui existe "
                "sur Forever.")
    if f == "classic":
        return "Le joueur est sur WoW Classic : ne conseille que ce qui existe dans cette version."
    return ""
