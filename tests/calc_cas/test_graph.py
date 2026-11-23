"""calc_cas, graphes : échantillonnage (y = f(x), paramétrique, polaire), asymptotes coupées, analyse
(zéros, extrema, intersections) avec forme exacte vérifiée."""
from __future__ import annotations

import math

import pytest

from modules.calc_cas.engine import CasError, Session, evaluate
from modules.calc_cas.graph import analyze, exact_guess, plot

WIN = {"xmin": -10, "xmax": 10, "ymin": -7, "ymax": 7}


def points(result: dict, i: int = 0) -> list[list[float]]:
    return [p for seg in result["curves"][i]["segments"] for p in seg]


def test_function_plot_samples_the_window() -> None:
    result = plot([{"kind": "y", "expr": "x^2"}], WIN, Session(), samples=201)
    pts = points(result)
    assert len(pts) == 201 and pts[0] == [-10.0, 100.0] and pts[100] == [0.0, 0.0]
    assert result["curves"][0]["label"] == "y = x**2"


def test_asymptote_and_undefined_parts_split_the_curve() -> None:
    tan = plot([{"kind": "y", "expr": "tan(x)"}], WIN, Session(), samples=2000)
    assert len(tan["curves"][0]["segments"]) >= 6  # une branche par période visible
    root = plot([{"kind": "y", "expr": "sqrt(x)"}], WIN, Session(), samples=201)
    assert all(x >= 0 for x, _ in points(root))  # rien pour x < 0 (valeurs complexes écartées)
    inv = plot([{"kind": "y", "expr": "1/x"}], WIN, Session(), samples=200)
    assert len(inv["curves"][0]["segments"]) == 2


def test_parametric_and_polar_curves() -> None:
    circle = plot([{"kind": "param", "x": "3cos(t)", "y": "3sin(t)", "tmin": 0, "tmax": 2 * math.pi}],
                  WIN, Session(), samples=100)
    assert all(abs(math.hypot(x, y) - 3) < 1e-4 for x, y in points(circle))
    rose = plot([{"kind": "polar", "r": "cos(4 theta)", "tmin": 0, "tmax": 2 * math.pi}], WIN, Session(), 400)
    assert max(math.hypot(x, y) for x, y in points(rose)) == pytest.approx(1, abs=1e-3)


def test_user_functions_and_y_equals_form_are_plotted() -> None:
    s = Session()
    evaluate("g(x) := 2x + 1", s)
    evaluate("x := 5", s)  # une variable x de l'utilisateur ne fige pas la courbe
    result = plot([{"kind": "y", "expr": "g(x)"}, {"kind": "y", "expr": "y = x/2"}], WIN, s, samples=51)
    assert points(result, 0)[0] == [-10.0, -19.0] and points(result, 0)[25] == [0.0, 1.0]
    assert points(result, 1)[-1] == [10.0, 5.0]


def test_bad_curve_does_not_hide_the_others() -> None:
    result = plot([{"kind": "y", "expr": "x +* 2"}, {"kind": "y", "expr": "a*x"}, {"kind": "y", "expr": "x"},
                   {"kind": "spirale"}], WIN, Session())
    errors = [c.get("error", "") for c in result["curves"]]
    assert "invalide" in errors[0] and "Variable inconnue" in errors[1] and not errors[2] and "inconnu" in errors[3]
    assert result["curves"][2]["segments"]


@pytest.mark.parametrize("window", [{"xmin": 1, "xmax": 1}, {"xmin": "a"}, {"ymin": 5, "ymax": -5},
                                    {"xmin": float("inf")}])
def test_invalid_window(window: dict) -> None:
    with pytest.raises(CasError, match="Fenêtre"):
        plot([{"kind": "y", "expr": "x"}], window, Session())


def test_plot_limits() -> None:
    with pytest.raises(CasError):
        plot([], WIN, Session())
    with pytest.raises(CasError):
        plot([{"kind": "y", "expr": "x"}] * 9, WIN, Session())


def test_zeros_with_exact_forms() -> None:
    result = analyze({"what": "zeros", "expr": "x^2 - 2", "xmin": -5, "xmax": 5}, Session())
    assert [p["x_exact"] for p in result["points"]] == ["-sqrt(2)", "sqrt(2)"]
    assert result["points"][1]["x"] == pytest.approx(math.sqrt(2), abs=1e-10)
    trig = analyze({"what": "zeros", "expr": "sin(x)", "xmin": -1, "xmax": 7}, Session())
    assert [p.get("x_exact") for p in trig["points"]] == ["0", "pi", "2*pi"]


def test_double_root_and_false_zeros() -> None:
    double = analyze({"what": "zeros", "expr": "(x - 1)^2", "xmin": -5, "xmax": 5}, Session())
    assert [p.get("x_exact") for p in double["points"]] == ["1"]
    tan = analyze({"what": "zeros", "expr": "tan(x)", "xmin": 1, "xmax": 2}, Session())
    assert tan["points"] == []  # le saut en π/2 n'est pas un zéro
    inv = analyze({"what": "zeros", "expr": "1/x", "xmin": -1, "xmax": 1}, Session())
    assert inv["points"] == []


def test_extrema_are_classified() -> None:
    result = analyze({"what": "extrema", "expr": "x^3 - 3x", "xmin": -3, "xmax": 3}, Session())
    found = [(p["type"], p["x_exact"], p["y_exact"]) for p in result["points"]]
    assert found == [("maximum", "-1", "2"), ("minimum", "1", "-2")]
    assert analyze({"what": "extrema", "expr": "x^3", "xmin": -3, "xmax": 3}, Session())["points"] == []


def test_intersections_numeric_when_no_closed_form() -> None:
    result = analyze({"what": "intersections", "expr": "cos(x)", "other": "x", "xmin": -5, "xmax": 5}, Session())
    assert len(result["points"]) == 1
    p = result["points"][0]
    assert p["x"] == pytest.approx(0.739085133215, abs=1e-9) and "x_exact" not in p  # nombre de Dottie
    line = analyze({"what": "intersections", "expr": "x^2", "other": "2x", "xmin": -5, "xmax": 5}, Session())
    assert [(p["x_exact"], p["y_exact"]) for p in line["points"]] == [("0", "0"), ("2", "4")]


def test_analyze_errors() -> None:
    with pytest.raises(CasError):
        analyze({"what": "aire", "expr": "x"}, Session())
    with pytest.raises(CasError, match="Intervalle"):
        analyze({"what": "zeros", "expr": "x", "xmin": 3, "xmax": 1}, Session())


def test_exact_guess_is_only_returned_when_verified() -> None:
    import sympy as sp
    x = sp.Symbol("x")
    assert exact_guess(math.sqrt(2), x**2 - 2) == sp.sqrt(2)
    assert exact_guess(0.739085133215161, sp.cos(x) - x) is None


def test_table_of_values() -> None:
    from modules.calc_cas.graph import table
    t = table({"expr": "1/x", "start": -1, "step": 0.5, "count": 5}, Session())
    assert t["rows"] == [[-1.0, -1.0], [-0.5, -2.0], [0.0, None], [0.5, 2.0], [1.0, 1.0]]
    with pytest.raises(CasError, match="pas non nul"):
        table({"expr": "x", "step": 0}, Session())
