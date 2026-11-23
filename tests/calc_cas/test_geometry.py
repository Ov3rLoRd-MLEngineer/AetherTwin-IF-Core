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
