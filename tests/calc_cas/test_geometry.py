"""calc_cas, géométrie : mesures exactes à partir de coordonnées (fractions, racines), erreurs lisibles."""
from __future__ import annotations

import pytest

from modules.calc_cas.engine import CasError
from modules.calc_cas.geometry import measure


def exact(what: str, points: list, **extra) -> str:
    return measure({"what": what, "points": points, **extra})["exact"]


@pytest.mark.parametrize(("what", "points", "expected"), [
    ("distance", [[0, 0], [1, 1]], "sqrt(2)"),
    ("distance", [[0, 0], [3, 4]], "5"),
    ("midpoint", [[0.5, 0], [1, "sqrt(2)"]], "[3/4, sqrt(2)/2]"),
    ("slope", [[0, 0], [3, 2]], "2/3"),
    ("line", [[0, 1], [2, 5]], "y = 2*x + 1"),
    ("line", [[2, 1], [2, 5]], "x = 2"),
    ("angle", [[1, 0], [0, 0], [0, 1]], "pi/2"),
    ("area", [[0, 0], [4, 0], [0, 3]], "6"),
    ("area", [[0, 0], [2, 0], [2, 2], [0, 2]], "4"),
    ("perimeter", [[0, 0], [4, 0], [0, 3]], "12"),
    ("perimeter", [[0, 0], [1, 1]], "sqrt(2)"),
    ("intersection", [[0, 0], [1, 1], [0, 2], [2, 0]], "[1, 1]"),
])
def test_exact_measures(what: str, points: list, expected: str) -> None:
    assert exact(what, points) == expected


def test_angle_in_degrees_and_approximation() -> None:
    assert exact("angle", [[1, 0], [0, 0], [1, 1]], degrees=True) == "45"
    result = measure({"what": "distance", "points": [[0, 0], [1, 2]]})
    assert result["exact"] == "sqrt(5)" and result["approx"] == "2.2360679775" and "<msqrt>" in result["mathml"]


def test_circles() -> None:
    assert "rayon: 5" in exact("circle", [[1, 1], [4, 5]])
    circum = exact("circumcircle", [[0, 0], [2, 0], [0, 2]])
    assert "centre: [1, 1]" in circum and "rayon: sqrt(2)" in circum and "= 2" in circum


@pytest.mark.parametrize(("what", "points", "message"), [
    ("intersection", [[0, 0], [1, 1], [0, 1], [1, 2]], "parallèles"),
    ("intersection", [[0, 0], [1, 1], [2, 2], [3, 3]], "confondues"),
    ("circumcircle", [[0, 0], [1, 1], [2, 2]], "alignés"),
    ("line", [[1, 1], [1, 1]], "confondus"),
    ("slope", [[1, 0], [1, 5]], "verticale"),
    ("angle", [[0, 0], [0, 0], [1, 0]], "longueur nulle"),
    ("circle", [[1, 1], [1, 1]], "rayon nul"),
    ("distance", [[0, 0]], "2 points"),
    ("volume", [[0, 0]], "Mesure inconnue"),
    ("distance", "A B", "Points attendus"),
    ("distance", [[0, 0], [float("nan"), 1]], "non finie"),
    ("distance", [[0, 0], ["t", 1]], "non réelle"),
    ("distance", [[0, 0], ["__import__('os')", 1]], "."),
])
def test_errors_are_readable(what: str, points, message: str) -> None:
    with pytest.raises(CasError, match=message):
        measure({"what": what, "points": points})


# -- construction complète refaite en exact (bouton « exact » de la page)
A = {"id": 1, "t": "pt", "x": 0, "y": 0, "name": "A"}
B = {"id": 2, "t": "pt", "x": 2, "y": 0, "name": "B"}
CIRCLE = {"id": 3, "t": "circ", "c": 1, "p": 2}
C = {"id": 4, "t": "pt", "x": 1, "y": 3, "name": "C"}
D = {"id": 5, "t": "pt", "x": 0.5, "y": -1, "name": "D"}
LINE = {"id": 6, "t": "line", "a": 4, "b": 5}
FIGURE = [A, B, CIRCLE, C, D, LINE, {"id": 7, "t": "inter", "a": 6, "b": 3, "i": 0, "name": "E"},
          {"id": 8, "t": "inter", "a": 3, "b": 6, "i": 1, "name": "F"}]


def fig(measure_spec: dict, objects: list | None = None, **extra) -> dict:
    return measure({"what": "figure", "objects": objects or FIGURE, "measure": measure_spec, **extra})


def test_constructed_points_keep_their_irrational_value() -> None:
    e, f = fig({"m": "pt", "refs": [7]}), fig({"m": "pt", "refs": [8]})
    assert "sqrt(235)" in e["exact"] and "sqrt(235)" in f["exact"]
    assert e["approx"].startswith("[0.8512") and f["approx"].startswith("[0.3795")  # même ordre que la page
    assert fig({"m": "len", "refs": [7, 8]})["exact"] == "2*sqrt(611)/13"
    assert fig({"m": "eq", "c": 6})["exact"] == "y = 8*x - 5"
    assert "x**2 + y**2 = 4" in fig({"m": "eq", "c": 3})["exact"]


def test_circle_circle_intersection_is_exact() -> None:
    objs = [A, B, CIRCLE, {"id": 4, "t": "circ", "c": 2, "p": 1},
            {"id": 5, "t": "inter", "a": 3, "b": 4, "i": 0, "name": "I"}]
    assert fig({"m": "pt", "refs": [5]}, objs)["exact"] == "[1, sqrt(3)]"  # indice 0 : formule de la page
    assert fig({"m": "angle", "refs": [2, 1, 5]}, objs, degrees=True)["exact"] == "60"


def test_transformations() -> None:
    objs = [*FIGURE, {"id": 9, "t": "tr", "f": "rot", "s": 2, "c": 1, "deg": "60", "name": "B'"},
            {"id": 10, "t": "tr", "f": "syma", "s": 2, "l": 6, "name": "B''"},
            {"id": 11, "t": "tr", "f": "symc", "s": 3, "c": 4},
            {"id": 12, "t": "tr", "f": "trans", "s": 6, "a": 1, "b": 2}]
    assert fig({"m": "pt", "refs": [9]}, objs)["exact"] == "[1, sqrt(3)]"
    assert fig({"m": "pt", "refs": [10]}, objs)["exact"] == "[-46/65, 22/65]"
    assert "(x - 2)**2 + (y - 6)**2 = 4" in fig({"m": "eq", "c": 11}, objs)["exact"]
    assert fig({"m": "eq", "c": 12}, objs)["exact"] == "y = 8*x - 21"


def test_locus_equations() -> None:
    on_circle = [*FIGURE, {"id": 20, "t": "pton", "c": 3, "x": 2, "y": 0, "name": "P"},
                 {"id": 21, "t": "mid", "a": 4, "b": 20, "name": "M"}, {"id": 22, "t": "locus", "a": 21, "b": 20}]
    assert fig({"m": "eq", "c": 22}, on_circle)["exact"] == "2*x**2 - 2*x + 2*y**2 - 6*y + 3 = 0"
    on_line = [*FIGURE, {"id": 20, "t": "pton", "c": 6, "u": 0.3, "name": "P"},
               {"id": 21, "t": "tr", "f": "rot", "s": 20, "c": 1, "deg": "90"},
               {"id": 22, "t": "locus", "a": 21, "b": 20}]
    assert fig({"m": "eq", "c": 22}, on_line)["exact"] == "x + 8*y - 5 = 0"
    assert fig({"m": "pt", "refs": [20]}, on_line)["exact"] == "[17/20, 9/5]"  # u = 3/10 sur (CD)


def test_figure_errors_are_readable() -> None:
    with pytest.raises(CasError, match="vide"):
        measure({"what": "figure", "objects": [], "measure": {"m": "pt", "refs": [1]}})
    with pytest.raises(CasError, match="invalide"):
        measure({"what": "figure", "objects": [{"id": 1, "t": "exec"}], "measure": {"m": "pt", "refs": [1]}})
    with pytest.raises(CasError, match="n'existe pas"):  # E n'existe plus quand la droite rate le cercle
        fig({"m": "pt", "refs": [7]}, [A, B, CIRCLE, {**C, "x": 5}, {**D, "x": 5}, LINE, FIGURE[6]])
    with pytest.raises(CasError, match="Angle"):
        fig({"m": "pt", "refs": [9]}, [*FIGURE, {"id": 9, "t": "tr", "f": "rot", "s": 2, "c": 1, "deg": "abc"}])
    with pytest.raises(CasError, match="inconnue"):
        fig({"m": "volume"})
