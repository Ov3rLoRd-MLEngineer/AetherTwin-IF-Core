"""calc_cas, statistiques : une et deux variables, effectifs, régressions, cellules en expressions, erreurs."""
from __future__ import annotations

import math

import pytest

from modules.calc_cas.engine import CasError, Session
from modules.calc_cas.stats import MODELS, describe, regress


def test_one_variable_statistics() -> None:
    s = describe({"x": [2, 4, 4, 4, 5, 5, 7, 9]})["one_var"]
    assert s["n"] == 8 and s["mean"] == 5 and s["sum"] == 40 and s["sum_sq"] == 232
    assert s["sigma"] == 2 and s["sx"] == pytest.approx(2.138089935, abs=1e-9) and s["variance"] == 4
    assert (s["min"], s["q1"], s["median"], s["q3"], s["max"], s["range"]) == (2, 4, 4.5, 6, 9, 7)


def test_quartiles_odd_count_exclude_median() -> None:
    s = describe({"x": [1, 2, 3, 4, 5, 6, 7]})["one_var"]
    assert (s["q1"], s["median"], s["q3"]) == (2, 4, 6)


def test_frequencies_and_expression_cells() -> None:
    s = describe({"x": ["1/2", "sqrt(4)", 3], "freq": [2, 1, 1]}, Session())["one_var"]
    assert s["n"] == 4 and s["sum"] == 6 and s["min"] == 0.5
    with pytest.raises(CasError, match="même longueur"):
        describe({"x": [1, 2, 3], "freq": [2, 1, ""]})


def test_frequencies() -> None:
    s = describe({"x": [1, 2, 3], "freq": [2, 1, 1]})["one_var"]
    assert s["n"] == 4 and s["mean"] == 1.75 and s["median"] == 1.5
    with pytest.raises(CasError, match="entiers positifs"):
        describe({"x": [1, 2], "freq": [1.5, 1]})
    with pytest.raises(CasError, match="Effectif total nul"):
        describe({"x": [1, 2], "freq": [0, 0]})


def test_two_variables() -> None:
    out = describe({"x": [1, 2, 3, 4], "y": [2, 4, 6, 8]})
    t = out["two_var"]
    assert t["n"] == 4 and t["mean_x"] == 2.5 and t["mean_y"] == 5 and t["r"] == 1 and t["sum_xy"] == 60


@pytest.mark.parametrize("model, x, y, coefs", [
    ("linear", [0, 1, 2, 3], [1, 3, 5, 7], {"a": 2, "b": 1}),
    ("quadratic", [-1, 0, 1, 2], [2, 1, 2, 5], {"a": 1, "b": 0, "c": 1}),
    ("cubic", [-1, 0, 1, 2, 3], [-1, 0, 1, 8, 27], {"a": 1, "b": 0, "c": 0, "d": 0}),
    ("exponential", [0, 1, 2, 3], [3, 6, 12, 24], {"a": 3, "b": 2}),
    ("power", [1, 2, 4, 8], [5, 20, 80, 320], {"a": 5, "b": 2}),
    ("logarithmic", [1, math.e, math.e ** 2], [1, 4, 7], {"a": 1, "b": 3}),
])
def test_regressions_recover_exact_models(model: str, x: list, y: list, coefs: dict) -> None:
    r = regress({"x": x, "y": y, "model": model})
    for name, value in coefs.items():
        assert r["coefficients"][name] == pytest.approx(value, abs=1e-6), (model, name)
    assert r["r2"] == pytest.approx(1, abs=1e-9) and r["form"] == MODELS[model]
    assert r["expr"] and "avec" in r["equation"]


def test_regression_expression_is_plottable() -> None:
    from modules.calc_cas.graph import plot
    r = regress({"x": [0, 1, 2, 3, 4, 5], "y": [2, 3.1, 4.4, 6.9, 10.2, 15.1], "model": "exponential"})
    assert 0.98 < r["r2"] < 1
    curve = plot([{"kind": "y", "expr": r["expr"]}], {"xmin": 0, "xmax": 5, "ymin": 0, "ymax": 20}, Session())
    assert "error" not in curve["curves"][0] and curve["curves"][0]["segments"]


def test_linear_regression_reports_r() -> None:
    r = regress({"x": [1, 2, 3, 4], "y": [4, 3, 2, 1], "model": "linear"})
    assert r["r"] == -1 and r["coefficients"] == {"a": -1, "b": 5} and r["expr"] == "(-1)*x + (5)"


@pytest.mark.parametrize("args, fragment", [
    ({"x": [1, 2], "y": [1], "model": "linear"}, "même longueur"),
    ({"x": [1], "y": [1], "model": "linear"}, "au moins 2"),
    ({"x": [1, 2, 3], "y": [1, 2, 3], "model": "cubic"}, "au moins 4"),
    ({"x": [1, 1, 1], "y": [1, 2, 3], "model": "linear"}, "variées"),
    ({"x": [0, 1], "y": [1, -1], "model": "exponential"}, "> 0"),
    ({"x": [0, 1], "y": [1, 2], "model": "power"}, "> 0"),
    ({"x": [-1, 1], "y": [1, 2], "model": "logarithmic"}, "> 0"),
    ({"x": [1, 2], "y": [1, 2], "model": "sinus"}, "Modèle inconnu"),
    ({"x": [1, "abc"], "y": [1, 2], "model": "linear"}, "ligne 2"),
    ({"x": [1, "2i"], "y": [1, 2], "model": "linear"}, "réel"),
    ({"x": "1,2", "y": [1, 2], "model": "linear"}, "liste"),
    ({"x": [], "y": [], "model": "linear"}, "vide"),
])
def test_regression_errors(args: dict, fragment: str) -> None:
    with pytest.raises(CasError, match=fragment):
        regress(args)


def test_describe_errors() -> None:
    with pytest.raises(CasError, match="vide"):
        describe({"x": ["", None]})
    with pytest.raises(CasError, match="même longueur"):
        describe({"x": [1, 2, 3], "y": [1, 2]})
    with pytest.raises(CasError, match="1/0|zéro"):
        describe({"x": ["1/0"]})
