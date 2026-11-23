"""Exemples de démonstration (interface, vidéo du concours, tests). Chacun est vérifié par `tests/calc_cas`."""
from __future__ import annotations

from typing import Any

# (titre, saisie, résultat exact attendu)
EXAMPLES: list[tuple[str, str, str]] = [
    ("Fractions exactes", "1/3 + 1/6", "1/2"),
    ("Racines simplifiées", "sqrt(72)", "6*sqrt(2)"),
    ("Développer", "expand((x + 1)^3)", "x**3 + 3*x**2 + 3*x + 1"),
    ("Factoriser", "factor(x^3 - 6x^2 + 11x - 6)", "(x - 3)*(x - 2)*(x - 1)"),
    ("Dériver", "diff(x^2 sin(x), x)", "x**2*cos(x) + 2*x*sin(x)"),
    ("Primitive", "integrate(x e^x, x)", "(x - 1)*exp(x)"),
    ("Intégrale de Gauss", "integrate(e^(-x^2), x, -oo, oo)", "sqrt(pi)"),
    ("Limite remarquable", "limit(sin(x)/x, x, 0)", "1"),
    ("Équation du second degré", "solve(x^2 - 2 = 0, x)", "[x = -sqrt(2), x = sqrt(2)]"),
    ("Système linéaire", "solve([2x + y = 5, x - y = 1], [x, y])", "[[x = 2, y = 1]]"),
    ("Série de Bâle", "sum(1/k^2, k, 1, oo)", "pi**2/6"),
    ("Déterminant", "det([[2, 1], [1, 3]])", "5"),
    ("Valeurs propres", "eigenvals([[2, 1], [1, 2]])", "{1: 1, 3: 1}"),
    ("Complexes", "(1 + 2i)(3 - i)", "5 + 5*I"),
    ("Formule d'Euler", "e^(i pi) + 1", "0"),
    ("Taylor", "taylor(cos(x), x, 0, 6)", "x**4/24 - x**2/2 + 1"),
]

GRAPH_EXAMPLES: list[dict[str, Any]] = [
    {"title": "Polynôme et ses extrema", "curves": [{"kind": "y", "expr": "x^3 - 3x"}],
     "analyze": {"what": "extrema", "expr": "x^3 - 3x"}},
    {"title": "Intersection cosinus / droite", "curves": [{"kind": "y", "expr": "cos(x)"}, {"kind": "y", "expr": "x"}],
     "analyze": {"what": "intersections", "expr": "cos(x)", "other": "x"}},
    {"title": "Rosace polaire", "curves": [{"kind": "polar", "r": "cos(4 theta)", "tmin": 0, "tmax": 6.2832}]},
    {"title": "Cercle paramétrique", "curves": [{"kind": "param", "x": "3cos(t)", "y": "3sin(t)", "tmin": 0,
                                                 "tmax": 6.2832}]},
]

STATS_EXAMPLE = {"title": "Croissance exponentielle", "x": [0, 1, 2, 3, 4, 5], "y": [2, 3.1, 4.4, 6.9, 10.2, 15.1],
                 "model": "exponential"}

AGENT_EXAMPLE = "Quelle est l'aire exacte entre les courbes y = x^2 et y = 2x ?"


def catalog() -> dict[str, Any]:
    return {"examples": [{"title": t, "input": i, "expected": e} for t, i, e in EXAMPLES],
            "graphs": GRAPH_EXAMPLES, "stats": STATS_EXAMPLE, "agent": AGENT_EXAMPLE}
