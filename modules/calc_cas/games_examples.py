"""Jeux de démonstration du mode jeu (module `jeu`), écrits dans le Python du bac à sable : pas de classe, pas de
`global` (l'état vit dans des dictionnaires et des listes). Proposés dans Programmes → Jeux."""
from __future__ import annotations

SNAKE = '''# Snake : flèches pour tourner, Échap pour quitter
import jeu
from random import randint

C, L, H = 20, 24, 18                      # taille d'une case, largeur et hauteur en cases
jeu.fenetre(C * L, C * H, "Snake")
etat = {"serpent": [(12, 9), (11, 9), (10, 9)], "dir": (1, 0), "pomme": (5, 5), "score": 0, "fin": False, "t": 0}

def nouvelle_pomme():
    while True:
        p = (randint(0, L - 1), randint(0, H - 1))
        if p not in etat["serpent"]:
            return p

while jeu.image(60):
    for nom, d in (("gauche", (-1, 0)), ("droite", (1, 0)), ("haut", (0, -1)), ("bas", (0, 1))):
        if jeu.appuyee(nom) and (d[0] != -etat["dir"][0] or d[1] != -etat["dir"][1]):
            etat["dir"] = d
    etat["t"] += 1
    if not etat["fin"] and etat["t"] % 7 == 0:
        x, y = etat["serpent"][0]
        tete = (x + etat["dir"][0], y + etat["dir"][1])
        if not (0 <= tete[0] < L and 0 <= tete[1] < H) or tete in etat["serpent"]:
            etat["fin"] = True
        else:
            etat["serpent"].insert(0, tete)
            if tete == etat["pomme"]:
                etat["score"] += 1
                etat["pomme"] = nouvelle_pomme()
            else:
                etat["serpent"].pop()
    if etat["fin"] and jeu.appuyee("espace"):
        etat.update(serpent=[(12, 9), (11, 9), (10, 9)], dir=(1, 0), score=0, fin=False)
    jeu.effacer((18, 22, 28))
    jeu.rect(etat["pomme"][0] * C + 3, etat["pomme"][1] * C + 3, C - 6, C - 6, "rouge")
    for i, (x, y) in enumerate(etat["serpent"]):
        jeu.rect(x * C + 1, y * C + 1, C - 2, C - 2, "cyan" if i == 0 else (40, 150, 170))
    jeu.texte(8, 4, f"score {etat['score']}", "blanc", 18)
    if etat["fin"]:
        jeu.texte(130, 160, "Perdu ! espace pour rejouer", "jaune", 24)
'''

PONG = '''# Pong : haut / bas pour la raquette de gauche, contre l'ordinateur
import jeu

W, H = 640, 400
jeu.fenetre(W, H, "Pong")
b = {"x": W / 2, "y": H / 2, "vx": 5.0, "vy": 3.0}
j = {"moi": H / 2, "ia": H / 2, "s1": 0, "s2": 0}

while jeu.image(60):
    if jeu.touche("haut"): j["moi"] -= 7
    if jeu.touche("bas"): j["moi"] += 7
    j["moi"] = max(40, min(H - 40, j["moi"]))
    j["ia"] += max(-4.5, min(4.5, b["y"] - j["ia"]))          # l'ordinateur suit la balle, pas trop vite
    b["x"] += b["vx"]; b["y"] += b["vy"]
    if b["y"] < 8 or b["y"] > H - 8:
        b["vy"] = -b["vy"]
    for cx, cy, sens in ((24, j["moi"], 1), (W - 24, j["ia"], -1)):
        if abs(b["x"] - cx) < 10 and abs(b["y"] - cy) < 44 and b["vx"] * sens < 0:
            b["vx"] = -b["vx"] * 1.05
            b["vy"] += (b["y"] - cy) / 10
    if b["x"] < 0 or b["x"] > W:
        if b["x"] < 0: j["s2"] += 1
        else: j["s1"] += 1
        b.update(x=W / 2, y=H / 2, vx=5.0 if b["x"] < 0 else -5.0, vy=3.0)
    jeu.effacer("noir")
    for y in range(0, H, 24):
        jeu.rect(W / 2 - 2, y, 4, 12, "gris_fonce")
    jeu.rect(18, j["moi"] - 40, 10, 80, "cyan")
    jeu.rect(W - 28, j["ia"] - 40, 10, 80, "orange")
    jeu.cercle(b["x"], b["y"], 8, "blanc")
    jeu.texte(W / 2 - 70, 10, f"{j['s1']}      {j['s2']}", "blanc", 32)
'''

TETRIS = '''# Tetris : gauche / droite, haut pour tourner, bas pour accélérer, espace pour lâcher
import jeu
from random import choice

CL, CH, T = 10, 20, 24
jeu.fenetre(CL * T + 160, CH * T, "Tetris")
PIECES = {"I": [(0, 1), (1, 1), (2, 1), (3, 1)], "O": [(1, 0), (2, 0), (1, 1), (2, 1)],
          "T": [(1, 0), (0, 1), (1, 1), (2, 1)], "S": [(1, 0), (2, 0), (0, 1), (1, 1)],
          "Z": [(0, 0), (1, 0), (1, 1), (2, 1)], "J": [(0, 0), (0, 1), (1, 1), (2, 1)],
          "L": [(2, 0), (0, 1), (1, 1), (2, 1)]}
TEINTES = {"I": "cyan", "O": "jaune", "T": "violet", "S": "vert", "Z": "rouge", "J": "bleu", "L": "orange"}
grille = [[None] * CL for ligne in range(CH)]
p = {"forme": "T", "cases": [], "x": 3, "y": 0, "t": 0, "score": 0, "lignes": 0, "fin": False}

def nouvelle():
    p["forme"] = choice(list(PIECES))
    p["cases"] = list(PIECES[p["forme"]])
    p["x"], p["y"] = 3, 0
    if not libre(p["cases"], p["x"], p["y"]):
        p["fin"] = True

def libre(cases, x, y):
    for cx, cy in cases:
        gx, gy = cx + x, cy + y
        if gx < 0 or gx >= CL or gy >= CH or (gy >= 0 and grille[gy][gx]):
            return False
    return True

def poser():
    for cx, cy in p["cases"]:
        if p["y"] + cy >= 0:
            grille[p["y"] + cy][p["x"] + cx] = TEINTES[p["forme"]]
    pleines = [y for y in range(CH) if all(grille[y])]
    for y in pleines:
        del grille[y]
        grille.insert(0, [None] * CL)
    p["lignes"] += len(pleines)
    p["score"] += [0, 100, 300, 500, 800][len(pleines)]
    nouvelle()

nouvelle()
while jeu.image(60):
    if not p["fin"]:
        for nom, dx in (("gauche", -1), ("droite", 1)):
            if jeu.appuyee(nom) and libre(p["cases"], p["x"] + dx, p["y"]):
                p["x"] += dx
        if jeu.appuyee("haut") and p["forme"] != "O":
            tournee = [(2 - cy, cx) for cx, cy in p["cases"]]
            if libre(tournee, p["x"], p["y"]):
                p["cases"] = tournee
        if jeu.appuyee("espace"):
            while libre(p["cases"], p["x"], p["y"] + 1):
                p["y"] += 1
            poser()
        p["t"] += 1
        vitesse = 3 if jeu.touche("bas") else max(6, 30 - p["lignes"])
        if p["t"] % vitesse == 0:
            if libre(p["cases"], p["x"], p["y"] + 1):
                p["y"] += 1
            else:
                poser()
    jeu.effacer((18, 22, 28))
    for y in range(CH):
        for x in range(CL):
            jeu.rect(x * T, y * T, T - 1, T - 1, grille[y][x] or (30, 35, 44))
    if not p["fin"]:
        for cx, cy in p["cases"]:
            jeu.rect((p["x"] + cx) * T, (p["y"] + cy) * T, T - 1, T - 1, TEINTES[p["forme"]])
    jeu.texte(CL * T + 16, 20, "score", "gris_clair", 18)
    jeu.texte(CL * T + 16, 44, str(p["score"]), "blanc", 30)
    jeu.texte(CL * T + 16, 100, f"lignes {p['lignes']}", "gris_clair", 18)
    if p["fin"]:
        jeu.texte(30, 220, "Partie finie", "jaune", 30)
'''

RAYCASTING = '''# Labyrinthe en 3D par lancer de rayons (façon jeux de tir des années 90)
# haut / bas : avancer / reculer ; gauche / droite : tourner ; Échap : quitter
import jeu
from math import cos, sin, pi

W, H, COLONNES = 640, 400, 160
jeu.fenetre(W, H, "Labyrinthe 3D")
CARTE = ["1111111111111111",
         "1000000000100001",
         "1011110110101101",
         "1010000100001001",
         "1010111101111011",
         "1000100000000001",
         "1110101111110111",
         "1000001000010001",
         "1011111011010101",
         "1000000010000101",
         "1111111111111111"]
moi = {"x": 1.5, "y": 1.5, "a": 0.0}
CHAMP = pi / 3

def mur(x, y):
    return CARTE[int(y)][int(x)] == "1"

while jeu.image(30):
    pas, rot = 0.0, 0.0
    if jeu.touche("haut"): pas = 0.08
    if jeu.touche("bas"): pas = -0.06
    if jeu.touche("gauche"): rot = -0.06
    if jeu.touche("droite"): rot = 0.06
    moi["a"] += rot
    nx, ny = moi["x"] + cos(moi["a"]) * pas, moi["y"] + sin(moi["a"]) * pas
    if not mur(nx, moi["y"]): moi["x"] = nx
    if not mur(moi["x"], ny): moi["y"] = ny
    jeu.effacer((30, 34, 44))
    jeu.rect(0, H / 2, W, H / 2, (58, 52, 46))
    largeur = W / COLONNES
    for c in range(COLONNES):
        angle = moi["a"] - CHAMP / 2 + CHAMP * c / COLONNES
        dx, dy = cos(angle), sin(angle)
        d = 0.0
        while d < 20:
            d += 0.02
            if mur(moi["x"] + dx * d, moi["y"] + dy * d):
                break
        d *= cos(angle - moi["a"])                     # pas d'effet « œil de poisson »
        hauteur = min(H, H / max(d, 0.1))
        teinte = max(30, int(230 - d * 22))
        jeu.rect(c * largeur, (H - hauteur) / 2, largeur + 1, hauteur, (teinte // 3, teinte, teinte))
    jeu.texte(8, 8, "flèches : se déplacer", "gris_clair", 16)
'''

GAMES = {"snake": SNAKE, "pong": PONG, "tetris": TETRIS, "labyrinthe_3d": RAYCASTING}
