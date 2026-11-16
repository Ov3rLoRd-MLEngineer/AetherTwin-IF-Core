"""
Pictogrammes dessinés (sans fichier image) pour les catégories de transmogrification.
Chaque forme est décrite en coordonnées relatives (0 à 1) dans le carré du pictogramme.
"""
import pygame

# Identifiants de catégorie = Enum.TransmogCollectionType de WoW
_BY_CATEGORY = {
    1: "helm", 2: "shoulder", 3: "cloak", 4: "chest", 5: "shirt", 6: "tabard", 7: "bracer", 8: "glove",
    9: "belt", 10: "legs", 11: "boot", 12: "wand", 13: "axe", 14: "sword", 15: "mace", 16: "dagger",
    17: "fist", 18: "shield", 19: "orb", 20: "axe", 21: "sword", 22: "mace", 23: "staff", 24: "polearm",
    25: "bow", 26: "gun", 27: "crossbow", 28: "glaive", 29: "paired",
}

_SHAPES = {
    "helm": [("poly", [(.18, .88), (.18, .46), (.28, .2), (.5, .1), (.72, .2), (.82, .46), (.82, .88), (.64, .88),
                       (.64, .6), (.36, .6), (.36, .88)])],
    "shoulder": [("poly", [(.08, .75), (.12, .35), (.32, .18), (.48, .3), (.48, .75), (.28, .85)]),
                 ("poly", [(.92, .75), (.88, .35), (.68, .18), (.52, .3), (.52, .75), (.72, .85)])],
    "cloak": [("poly", [(.28, .1), (.72, .1), (.88, .9), (.12, .9)]), ("circle", (.5, .16), .07)],
    "chest": [("poly", [(.12, .22), (.35, .12), (.65, .12), (.88, .22), (.78, .46), (.72, .9), (.28, .9), (.22, .46)])],
    "shirt": [("poly", [(.08, .26), (.35, .12), (.65, .12), (.92, .26), (.8, .46), (.72, .4), (.72, .9), (.28, .9),
                        (.28, .4), (.2, .46)])],
    "tabard": [("poly", [(.28, .1), (.72, .1), (.72, .68), (.5, .92), (.28, .68)]), ("line", (.5, .2), (.5, .7), 2),
               ("line", (.36, .38), (.64, .38), 2)],
    "bracer": [("rect", .2, .3, .6, .4), ("line", (.2, .42), (.8, .42), 2), ("line", (.2, .58), (.8, .58), 2)],
    "glove": [("poly", [(.25, .92), (.18, .5), (.28, .5), (.28, .25), (.38, .25), (.38, .45), (.44, .12), (.54, .12),
                        (.54, .45), (.6, .18), (.7, .18), (.68, .5), (.8, .4), (.86, .5), (.72, .92)])],
    "belt": [("rect", .08, .4, .84, .2), ("rect", .4, .32, .2, .36)],
    "legs": [("poly", [(.25, .1), (.75, .1), (.82, .92), (.56, .92), (.5, .4), (.44, .92), (.18, .92)])],
    "boot": [("poly", [(.3, .1), (.58, .1), (.58, .6), (.88, .7), (.88, .92), (.24, .92)])],
    "wand": [("line", (.2, .88), (.72, .28), 3), ("circle", (.8, .2), .09)],
    "sword": [("line", (.2, .86), (.8, .14), 3), ("line", (.28, .52), (.48, .72), 3), ("circle", (.16, .9), .05)],
    "axe": [("line", (.25, .92), (.68, .14), 3), ("poly", [(.55, .12), (.9, .22), (.82, .52), (.58, .4)])],
    "mace": [("line", (.22, .9), (.62, .32), 3), ("circle", (.7, .24), .17)],
    "dagger": [("line", (.3, .8), (.72, .28), 3), ("line", (.26, .52), (.44, .72), 3)],
    "fist": [("rect", .24, .3, .52, .42), ("circle", (.3, .3), .07), ("circle", (.45, .27), .07),
             ("circle", (.6, .27), .07), ("circle", (.74, .3), .07), ("rect", .3, .72, .4, .14)],
    "shield": [("poly", [(.14, .14), (.86, .14), (.86, .56), (.5, .92), (.14, .56)])],
    "orb": [("circle", (.5, .52), .3), ("circle", (.4, .42), .07)],
    "staff": [("line", (.2, .92), (.74, .2), 3), ("circle", (.8, .14), .1)],
    "polearm": [("line", (.2, .92), (.74, .2), 3), ("poly", [(.7, .26), (.9, .06), (.88, .32)])],
    "bow": [("line", (.7, .1), (.36, .3), 3), ("line", (.36, .3), (.26, .5), 3), ("line", (.26, .5), (.36, .7), 3),
            ("line", (.36, .7), (.7, .9), 3), ("line", (.7, .1), (.7, .9), 1)],
    "gun": [("poly", [(.08, .38), (.74, .38), (.74, .52), (.48, .52), (.42, .86), (.28, .86), (.3, .52), (.08, .52)])],
    "crossbow": [("line", (.18, .2), (.5, .34), 3), ("line", (.82, .2), (.5, .34), 3), ("line", (.5, .34), (.5, .9), 3),
                 ("line", (.18, .2), (.82, .2), 1)],
    "glaive": [("poly", [(.16, .18), (.4, .5), (.16, .82)]), ("poly", [(.84, .18), (.6, .5), (.84, .82)]),
               ("line", (.4, .5), (.6, .5), 3)],
    "paired": [("line", (.2, .86), (.8, .14), 3), ("line", (.8, .86), (.2, .14), 3)],
    "set": [("rect", .12, .58, .5, .3), ("rect", .38, .36, .5, .3), ("rect", .2, .12, .5, .3)],
}


def draw_icon(surface, key, rect, color):
    """Dessine le pictogramme d'une catégorie (identifiant TransmogCollectionType) ou 'set' dans rect."""
    shape = _SHAPES.get(_BY_CATEGORY.get(key, key) if not isinstance(key, str) else key, _SHAPES["orb"])
    rect = pygame.Rect(rect)
    fill = tuple(int(c * 0.45) for c in color)

    def pt(p):
        return (rect.x + int(p[0] * rect.w), rect.y + int(p[1] * rect.h))

    for op in shape:
        kind = op[0]
        if kind == "poly":
            points = [pt(p) for p in op[1]]
            pygame.draw.polygon(surface, fill, points)
            pygame.draw.polygon(surface, color, points, 2)
        elif kind == "line":
            pygame.draw.line(surface, color, pt(op[1]), pt(op[2]), op[3])
        elif kind == "circle":
            pygame.draw.circle(surface, fill, pt(op[1]), max(2, int(op[2] * rect.w)))
            pygame.draw.circle(surface, color, pt(op[1]), max(2, int(op[2] * rect.w)), 2)
        elif kind == "rect":
            r = pygame.Rect(rect.x + int(op[1] * rect.w), rect.y + int(op[2] * rect.h), int(op[3] * rect.w), int(op[4] * rect.h))
            pygame.draw.rect(surface, fill, r, border_radius=2)
            pygame.draw.rect(surface, color, r, 2, border_radius=2)
