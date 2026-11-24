"""calc_cas, mode jeu : bibliothèque `jeu` (pygame, sans fenêtre réelle ici), contrôles du bac à sable, exemples."""
from __future__ import annotations

import pytest

from modules.calc_cas import games
from modules.calc_cas.games_examples import GAMES
from modules.calc_cas.sandbox import MODULES, SandboxError, check_program

pygame = pytest.importorskip("pygame")


@pytest.fixture
def headless(monkeypatch: pytest.MonkeyPatch):
    """Pilote vidéo factice ; la fenêtre « se ferme » d'elle-même après quelques images."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    image = games.Game.image
    frames = {"n": 0}

    def counted(self, fps=30):
        frames["n"] += 1
        if frames["n"] % 12 == 0:
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        return image(self, 1000)

    monkeypatch.setattr(games.Game, "image", counted)
    return frames


def test_colors() -> None:
    assert games.color_of("rouge") == games.COLORS["rouge"]
    assert games.color_of("#ff8000") == (255, 128, 0)
    assert games.color_of((300, -5, 10)) == (255, 0, 10)
    for bad in ("fuchsia", "#zz0000", 7, (1, 2)):
        with pytest.raises(ValueError):
            games.color_of(bad)


@pytest.mark.parametrize("name", sorted(GAMES))
def test_examples_pass_the_sandbox_and_run(name: str, headless, capsys) -> None:
    check_program(GAMES[name], {**MODULES, "jeu": None})
    assert games.play(GAMES[name]) == 0, capsys.readouterr().err
    assert headless["n"] >= 12


def test_errors_are_reported_with_their_line(headless, capsys) -> None:
    assert games.play("import jeu\njeu.fenetre(200, 100)\nx = 1 / 0\n") == 1
    assert "Ligne 3" in capsys.readouterr().err
    assert games.play("import jeu\njeu.fenetre(10, 10)\n") == 1  # fenêtre trop petite
    assert games.play("import os\n") == 1
    assert games.play("import jeu\ninput('?')\n") == 1
    assert "jeu.touche" in capsys.readouterr().err


def test_print_goes_to_the_log(headless, capsys) -> None:
    assert games.play("print('bonjour', 2)\n") == 0
    assert "bonjour 2" in capsys.readouterr().out


def test_console_refuses_jeu_with_a_hint() -> None:
    with pytest.raises(SandboxError, match="Jouer"):
        check_program("import jeu\n")
    with pytest.raises(SandboxError):
        check_program("from jeu import _Game\n", {**MODULES, "jeu": None})


def test_module_exposes_no_pygame_object() -> None:
    namespace = games.Game(pygame).module()
    assert all(callable(getattr(namespace, n)) for n in ("fenetre", "image", "rect", "touche", "souris"))
    assert not any("pygame" in repr(v) for v in vars(namespace).values() if not callable(v))
