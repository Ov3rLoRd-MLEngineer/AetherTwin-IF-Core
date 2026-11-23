"""Statistiques à une et deux variables, régressions courantes.

Conventions (choix les plus simples, notés dans le README) :
- quartiles par la méthode des demi-séries (médiane de la moitié basse et de la moitié haute, médiane exclue si
  l'effectif est impair) ;
- `sx` = écart type de l'échantillon (diviseur n − 1), `sigma` = écart type de la population (diviseur n) ;
- r² des régressions calculé dans l'espace d'origine (y observés contre y prédits), y compris pour les modèles
  exponentiel, puissance et logarithmique ajustés par linéarisation.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from modules.calc_cas.engine import CasError, Session, to_float

MAX_POINTS = 10_000
MODELS = {
    "linear": "y = a·x + b",
    "quadratic": "y = a·x² + b·x + c",
    "cubic": "y = a·x³ + b·x² + c·x + d",
    "exponential": "y = a·b^x",
    "power": "y = a·x^b",
    "logarithmic": "y = a + b·ln(x)",
}


def _column(raw: Any, name: str, session: Session | None) -> np.ndarray:
    if not isinstance(raw, list | tuple):
        raise CasError(f"La colonne {name} doit être une liste de nombres")
    cells = [c for c in raw if not (isinstance(c, str) and not c.strip()) and c is not None]
    if not cells:
        raise CasError(f"La colonne {name} est vide")
    if len(cells) > MAX_POINTS:
        raise CasError(f"{MAX_POINTS} valeurs au plus par colonne")
    values = []
    for i, cell in enumerate(cells, start=1):
        try:
            values.append(to_float(cell, session))
        except CasError as exc:
            raise CasError(f"{name}, ligne {i} : {exc}") from None
    return np.array(values, dtype=float)


def _r(v: float) -> float | None:
    return float(f"{v:.12g}") if math.isfinite(v) else None


def _median(sorted_vals: np.ndarray) -> float:
    n = len(sorted_vals)
    return float(sorted_vals[n // 2]) if n % 2 else float((sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2)


def one_var(x: np.ndarray, freq: np.ndarray | None = None) -> dict[str, Any]:
    if freq is not None:
        if len(freq) != len(x):
            raise CasError("Les effectifs doivent avoir la même longueur que les valeurs")
        if np.any(freq < 0) or np.any(freq != np.round(freq)):
            raise CasError("Les effectifs doivent être des entiers positifs")
        x = np.repeat(x, freq.astype(int))
        if len(x) == 0:
            raise CasError("Effectif total nul")
    n = len(x)
    s = np.sort(x)
    mean = float(np.mean(x))
    half = n // 2
    lower, upper = s[:half], s[half + (n % 2):]
    out = {"n": n, "mean": mean, "sum": float(np.sum(x)), "sum_sq": float(np.sum(x * x)),
           "sigma": float(np.std(x)), "sx": float(np.std(x, ddof=1)) if n > 1 else math.nan,
           "variance": float(np.var(x)), "min": float(s[0]), "q1": _median(lower) if len(lower) else float(s[0]),
           "median": _median(s), "q3": _median(upper) if len(upper) else float(s[-1]), "max": float(s[-1])}
    out["range"] = out["max"] - out["min"]
    return {k: (_r(v) if isinstance(v, float) else v) for k, v in out.items()}


def two_var(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    if len(x) != len(y):
        raise CasError(f"Les colonnes n'ont pas la même longueur ({len(x)} et {len(y)})")
    if len(x) < 2:
        raise CasError("Au moins deux points")
    cov = float(np.mean((x - x.mean()) * (y - y.mean())))
    sx, sy = float(np.std(x)), float(np.std(y))
    r = cov / (sx * sy) if sx > 0 and sy > 0 else math.nan
    return {k: _r(v) if isinstance(v, float) else v for k, v in {
        "n": len(x), "mean_x": float(x.mean()), "mean_y": float(y.mean()), "sx": float(np.std(x, ddof=1)),
        "sy": float(np.std(y, ddof=1)), "sigma_x": sx, "sigma_y": sy, "sum_xy": float(np.sum(x * y)),
        "cov": cov, "r": r}.items()}


def describe(args: dict[str, Any], session: Session | None = None) -> dict[str, Any]:
    """`{"x": [...], "freq"?: [...]}` -> statistiques à une variable ; avec `"y"` -> à deux variables aussi."""
    x = _column(args.get("x"), "X", session)
    out: dict[str, Any] = {"ok": True}
    freq = _column(args["freq"], "effectifs", session) if args.get("freq") else None
    out["one_var"] = one_var(x, freq)
    if args.get("y"):
        out["two_var"] = two_var(x, _column(args.get("y"), "Y", session))
    return out


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def regress(args: dict[str, Any], session: Session | None = None) -> dict[str, Any]:
    """Ajuste un modèle de `MODELS`. Retourne coefficients, équation lisible, expression traçable et r²."""
    model = str(args.get("model", "linear"))
    if model not in MODELS:
        raise CasError("Modèle inconnu : " + ", ".join(MODELS))
    x = _column(args.get("x"), "X", session)
    y = _column(args.get("y"), "Y", session)
    if len(x) != len(y):
        raise CasError(f"Les colonnes n'ont pas la même longueur ({len(x)} et {len(y)})")
    need = {"linear": 2, "quadratic": 3, "cubic": 4}.get(model, 2)
    if len(x) < need:
        raise CasError(f"Régression {model} : au moins {need} points")
    if len(set(x.tolist())) < need:
        raise CasError("Les abscisses ne sont pas assez variées pour ce modèle")

    with np.errstate(all="ignore"):
        if model in ("linear", "quadratic", "cubic"):
            degree = need - 1
            coefs = np.polyfit(x, y, degree)
            names = "abcd"[: degree + 1]
            coefficients = dict(zip(names, coefs.tolist(), strict=True))
            powers = [degree - i for i in range(degree + 1)]
            expr = " + ".join(f"({_fmt(c)})*x^{p}" if p > 1 else f"({_fmt(c)})*x" if p == 1 else f"({_fmt(c)})"
                              for c, p in zip(coefs, powers, strict=True))
            predicted = np.polyval(coefs, x)
        elif model == "exponential":
            if np.any(y <= 0):
                raise CasError("Régression exponentielle : toutes les valeurs de y doivent être > 0")
            slope, intercept = np.polyfit(x, np.log(y), 1)
            a, b = math.exp(intercept), math.exp(slope)
            coefficients = {"a": a, "b": b}
            expr = f"({_fmt(a)})*({_fmt(b)})^x"
            predicted = a * b ** x
        elif model == "power":
            if np.any(y <= 0) or np.any(x <= 0):
                raise CasError("Régression puissance : x et y doivent être > 0")
            slope, intercept = np.polyfit(np.log(x), np.log(y), 1)
            a, b = math.exp(intercept), float(slope)
            coefficients = {"a": a, "b": b}
            expr = f"({_fmt(a)})*x^({_fmt(b)})"
            predicted = a * x ** b
        else:  # logarithmic
            if np.any(x <= 0):
                raise CasError("Régression logarithmique : toutes les valeurs de x doivent être > 0")
            slope, intercept = np.polyfit(np.log(x), y, 1)
            coefficients = {"a": float(intercept), "b": float(slope)}
            expr = f"({_fmt(intercept)}) + ({_fmt(slope)})*ln(x)"
            predicted = intercept + slope * np.log(x)

    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else (1.0 if ss_res < 1e-12 else math.nan)
    out: dict[str, Any] = {"ok": True, "model": model, "form": MODELS[model],
                           "coefficients": {k: _r(float(v)) for k, v in coefficients.items()},
                           "expr": expr.replace("+ (-", "- (").replace("+ -", "- "), "r2": _r(r2)}
    out["equation"] = MODELS[model] + "  avec " + ", ".join(f"{k} = {_fmt(v)}" for k, v in coefficients.items())
    if model == "linear":
        out["r"] = two_var(x, y)["r"]
    return out
