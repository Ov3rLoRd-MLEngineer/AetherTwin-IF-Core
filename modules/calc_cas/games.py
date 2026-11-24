"""Mode jeu des Programmes : un programme Python du bac à sable dessine dans sa propre fenêtre, en temps réel.

    python -I modules/calc_cas/games.py <fichier du programme>      (lancé par le module, une partie à la fois)

Le programme passe les mêmes contrôles que dans la console (`sandbox.check_program`), avec un module de plus,
`jeu` : une petite bibliothèque graphique en français, construite sur pygame, qui ne rend **jamais** d'objet pygame
(seulement des nombres, des booléens et des tuples). Pas de fichiers, pas de réseau, mémoire bornée.

    import jeu
    jeu.fenetre(480, 360, "Mon jeu")
    x = 240
    while jeu.image(30):                 # 30 images par seconde ; False quand la fenêtre est fermée (ou Échap)
        if jeu.touche("gauche"): x -= 4
        if jeu.touche("droite"): x += 4
        jeu.effacer("noir")
        jeu.cercle(x, 180, 12, "jaune")
        jeu.texte(8, 8, f"x = {x}")

Pas de délai maximal ici (un jeu dure) : la partie s'arrête à la fermeture de la fenêtre ou par « Arrêter ».
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

if __package__ in (None, ""):  # lancé comme script : la racine du dépôt remplace le dossier du script
    sys.path[0] = str(Path(__file__).resolve().parents[2])

COLORS = {
    "noir": (0, 0, 0), "blanc": (255, 255, 255), "rouge": (230, 57, 70), "vert": (47, 158, 68),
    "bleu": (25, 113, 194), "jaune": (250, 210, 50), "cyan": (46, 196, 214), "magenta": (214, 51, 108),
    "orange": (242, 140, 40), "gris": (128, 128, 128), "gris_clair": (200, 200, 200), "gris_fonce": (50, 54, 62),
    "violet": (112, 72, 232), "rose": (247, 131, 172), "marron": (140, 90, 50),
}
KEYS = {"gauche": "left", "droite": "right", "haut": "up", "bas": "down", "espace": "space", "entree": "return",
        "entrée": "return", "echap": "escape", "maj": "left shift", "ctrl": "left ctrl", "tab": "tab"}
MAX_SIZE = (1920, 1080)
MAX_PRINT = 20_000


class GameClosed(BaseException):  # noqa: N818 — signal d'arrêt, pas une erreur ; hors d'atteinte des `except Exception`
    pass


def color_of(value: Any) -> tuple[int, int, int]:
    """« rouge », (r, g, b) ou « #rrggbb »."""
    if isinstance(value, str):
        name = value.strip().lower()
        if name in COLORS:
            return COLORS[name]
        if len(name) == 7 and name.startswith("#"):
            try:
                return int(name[1:3], 16), int(name[3:5], 16), int(name[5:7], 16)
            except ValueError:
                pass
        raise ValueError(f"couleur inconnue : {value!r} (ex. « rouge », (255, 0, 0), « #ff0000 »)")
    try:
        r, g, b = (int(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError(f"couleur invalide : {value!r}") from None
    return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))


class Game:
    """État d'une partie (fenêtre, clavier, souris), derrière les fonctions du module `jeu`."""

    def __init__(self, pygame: Any) -> None:
        self.pg = pygame
        self.screen: Any = None
        self.clock: Any = None
        self.fonts: dict[int, Any] = {}
        self.held: set[str] = set()
        self.pressed: set[str] = set()
        self.mouse = (0, 0, 0)
        self.closed = False
        self.started = time.monotonic()
        self.printed = 0

    def _need(self) -> Any:
        if self.screen is None:
            self.fenetre()
        return self.screen

    # -- fenêtre et boucle
    def fenetre(self, largeur: Any = 480, hauteur: Any = 360, titre: Any = "Jeu") -> None:
        w, h = int(largeur), int(hauteur)
        if not (80 <= w <= MAX_SIZE[0] and 60 <= h <= MAX_SIZE[1]):
            raise ValueError(f"fenêtre de 80×60 à {MAX_SIZE[0]}×{MAX_SIZE[1]}")
        self.screen = self.pg.display.set_mode((w, h), self.pg.SCALED | self.pg.RESIZABLE)
        self.pg.display.set_caption(f"{str(titre)[:60]} — Æther CAS")
        self.clock = self.pg.time.Clock()

    def image(self, fps: Any = 30) -> bool:
        """Affiche l'image dessinée, attend la suivante, lit le clavier. False quand la fenêtre est fermée."""
        if self.closed:
            raise GameClosed
        self._need()
        self.pg.display.flip()
        self.clock.tick(max(1, min(int(fps), 240)))
        self.pressed = set()
        for event in self.pg.event.get():
            if event.type == self.pg.QUIT:
                self.closed = True
            elif event.type == self.pg.KEYDOWN:
                name = self.pg.key.name(event.key)
                self.held.add(name)
                self.pressed.add(name)
                if name == "escape":
                    self.closed = True
            elif event.type == self.pg.KEYUP:
                self.held.discard(self.pg.key.name(event.key))
            elif event.type in (self.pg.MOUSEMOTION, self.pg.MOUSEBUTTONDOWN, self.pg.MOUSEBUTTONUP):
                x, y = self.pg.mouse.get_pos()
                self.mouse = (int(x), int(y), int(any(self.pg.mouse.get_pressed())))
        return not self.closed

    # -- dessin
    def effacer(self, couleur: Any = "noir") -> None:
        self._need().fill(color_of(couleur))

    def rect(self, x: Any, y: Any, largeur: Any, hauteur: Any, couleur: Any = "blanc", plein: Any = True) -> None:
        self.pg.draw.rect(self._need(), color_of(couleur), (int(x), int(y), int(largeur), int(hauteur)),
                          0 if plein else 1)

    def cercle(self, x: Any, y: Any, rayon: Any, couleur: Any = "blanc", plein: Any = True) -> None:
        self.pg.draw.circle(self._need(), color_of(couleur), (int(x), int(y)), max(0, int(rayon)), 0 if plein else 1)

    def ligne(self, x1: Any, y1: Any, x2: Any, y2: Any, couleur: Any = "blanc", epaisseur: Any = 1) -> None:
        self.pg.draw.line(self._need(), color_of(couleur), (int(x1), int(y1)), (int(x2), int(y2)),
                          max(1, min(int(epaisseur), 50)))

    def polygone(self, points: Any, couleur: Any = "blanc", plein: Any = True) -> None:
        pts = [(int(x), int(y)) for x, y in list(points)[:2000]]
        if len(pts) >= 3:
            self.pg.draw.polygon(self._need(), color_of(couleur), pts, 0 if plein else 1)

    def texte(self, x: Any, y: Any, message: Any, couleur: Any = "blanc", taille: Any = 20) -> None:
        size = max(8, min(int(taille), 120))
        if size not in self.fonts:
            self.fonts[size] = self.pg.font.SysFont("segoeui,arial", size)
        surface = self.fonts[size].render(str(message)[:300], True, color_of(couleur))
        self._need().blit(surface, (int(x), int(y)))

    # -- entrées
    def touche(self, nom: Any) -> bool:
        """Touche maintenue : « gauche », « droite », « haut », « bas », « espace », « entree », lettres, chiffres."""
        return KEYS.get(str(nom).lower(), str(nom).lower()) in self.held

    def appuyee(self, nom: Any) -> bool:
        """Touche enfoncée pendant la dernière image (une seule fois par appui)."""
        return KEYS.get(str(nom).lower(), str(nom).lower()) in self.pressed

    def souris(self) -> tuple[int, int, int]:
        """(x, y, bouton enfoncé 0/1)."""
        return self.mouse

    def temps(self) -> float:
        return time.monotonic() - self.started

    def largeur(self) -> int:
        return int(self._need().get_width())

    def hauteur(self) -> int:
        return int(self._need().get_height())

    def print(self, *values: Any, sep: Any = " ", end: Any = "\n") -> None:
        text = str(sep).join(str(v) for v in values) + str(end)
        self.printed += len(text)
        if self.printed <= MAX_PRINT:
            sys.stdout.write(text)
            sys.stdout.flush()

    def module(self) -> SimpleNamespace:
        names = ("fenetre", "image", "effacer", "rect", "cercle", "ligne", "polygone", "texte", "touche", "appuyee",
                 "souris", "temps", "largeur", "hauteur")
        return SimpleNamespace(**{n: getattr(self, n) for n in names}, couleurs=tuple(COLORS))


def no_input(prompt: Any = "") -> str:
    raise ValueError("input() n'existe pas en mode jeu : lis le clavier avec jeu.touche(…) ou jeu.appuyee(…)")


def play(code: str, pygame: Any = None) -> int:
    """Joue un programme. Rend le code de sortie (0 : fin normale, 1 : erreur, affichée sur la sortie d'erreur)."""
    from modules.calc_cas import sandbox

    if pygame is None:
        import os

        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
    game = Game(pygame)
    modules = {**sandbox.MODULES, "jeu": game.module()}
    try:
        tree = sandbox.check_program(code, modules)
        program = sandbox.Program([])
        namespace = sandbox._globals(program, modules)  # noqa: SLF001 — même environnement que la console
        namespace["__builtins__"].update(print=game.print, input=no_input)
        pygame.init()
        sys.setrecursionlimit(1500)
        exec(compile(tree, "<programme>", "exec"), namespace)  # noqa: S102 — code vérifié, processus isolé et borné
        if game.screen is not None and not game.closed:  # programme terminé : la dernière image reste affichée
            while game.image(30):
                pass
    except GameClosed:
        pass
    except sandbox.SandboxError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001 — erreur du programme, avec sa ligne
        line = sandbox._line_of(exc)  # noqa: SLF001
        sys.stderr.write(f"{'Ligne ' + str(line) + ' — ' if line else ''}{type(exc).__name__} : {exc}\n")
        return 1
    finally:
        pygame.quit()
    return 0


def main(argv: list[str]) -> int:
    from modules.calc_cas.worker import limit_memory

    if len(argv) != 2:
        sys.stderr.write("usage : games.py <programme.py>\n")
        return 2
    limit_memory(768)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    random.seed()
    return play(Path(argv[1]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
