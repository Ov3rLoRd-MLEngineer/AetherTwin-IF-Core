"""Analyses du tableur : balayage de paramètres, Monte-Carlo, valeur cible, ajustement de courbes, statistiques, tri.

Tout part du contenu brut des cellules (comme le tableur) : une simulation remplace temporairement la valeur d'une ou
plusieurs cellules d'entrée et relit les cellules de sortie, recalculées avec leurs formules.
"""
from __future__ import annotations

import math
import random
import statistics
from typing import Any

import numpy as np

from modules.data_lab.formula import Err, Sheet, SheetError, display, find_root, parse_ref_name, range_cells

MAX_SWEEP = 2001
MAX_RUNS = 50_000


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(float(v)) else None


def _outputs(outputs: Any) -> list[str]:
    refs = [parse_ref_name(r) for r in (outputs if isinstance(outputs, list) else [outputs]) if str(r).strip()]
    if not refs:
        raise SheetError("indique au moins une cellule de sortie")
    return refs


def _input(cells: dict[str, Any], ref: str) -> str:
    ref = parse_ref_name(ref)
    raw = cells.get(ref)
    if isinstance(raw, str) and raw.startswith("="):
        raise SheetError(f"{ref} contient une formule : la cellule d'entrée doit être une valeur")
    return ref


def sweep(cells: dict[str, Any], input_ref: str, start: float, stop: float, steps: int, outputs: Any,
          input2: str | None = None, start2: float | None = None, stop2: float | None = None,
          steps2: int | None = None) -> dict[str, Any]:
    """Table de données : fait varier une cellule (ou deux) et relève les sorties."""
    ref = _input(cells, input_ref)
    outs = _outputs(outputs)
    steps = int(steps)
    if not 2 <= steps <= MAX_SWEEP:
        raise SheetError(f"nombre de pas entre 2 et {MAX_SWEEP}")
    xs = [float(start) + (float(stop) - float(start)) * i / (steps - 1) for i in range(steps)]
    if input2:
        ref2 = _input(cells, input2)
        n2 = int(steps2 or 0)
        if not 2 <= n2 <= 101 or steps * n2 > 20_000:
            raise SheetError("deuxième variable : 2 à 101 pas, 20 000 calculs au plus")
        ys = [float(start2) + (float(stop2) - float(start2)) * j / (n2 - 1) for j in range(n2)]
        grid = []
        for y in ys:
            row = []
            for x in xs:
                v = Sheet(cells, {ref: x, ref2: y}).value(outs[0])
                row.append(_num(v))
            grid.append(row)
        return {"input": ref, "input2": ref2, "x": xs, "y": ys, "output": outs[0], "grid": grid}
    series = {o: [] for o in outs}
    for x in xs:
        sheet = Sheet(cells, {ref: x})
        for o in outs:
            series[o].append(_num(sheet.value(o)))
    return {"input": ref, "x": xs, "series": series}


def _draw(rng: random.Random, spec: dict[str, Any]) -> float:
    law = str(spec.get("law", "normale")).lower()
    a, b, c = (float(spec.get(k) or 0) for k in ("a", "b", "c"))
    if law in ("normale", "normal"):
        return rng.gauss(a, abs(b))
    if law in ("uniforme", "uniform"):
        return rng.uniform(min(a, b), max(a, b))
    if law in ("triangulaire", "triangular"):
        lo, hi = min(a, b), max(a, b)
        return rng.triangular(lo, hi, min(max(c, lo), hi))
    if law in ("lognormale", "lognormal"):
        return rng.lognormvariate(a, abs(b))
    if law in ("exponentielle", "exponential"):
        if a <= 0:
            raise SheetError("loi exponentielle : moyenne a > 0")
        return rng.expovariate(1 / a)
    raise SheetError(f"loi inconnue : {law!r} (normale, uniforme, triangulaire, lognormale, exponentielle)")


def summary(values: list[float], bins: int = 30) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    arr = np.asarray(values, dtype=float)
    counts, edges = np.histogram(arr, bins=bins)
    q = np.percentile(arr, [5, 25, 50, 75, 95])
    return {"n": int(arr.size), "mean": float(arr.mean()), "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
            "min": float(arr.min()), "max": float(arr.max()), "p5": float(q[0]), "q1": float(q[1]),
            "median": float(q[2]), "q3": float(q[3]), "p95": float(q[4]),
            "histogram": {"counts": counts.tolist(), "edges": edges.tolist()}}


def monte_carlo(cells: dict[str, Any], inputs: dict[str, dict[str, Any]], outputs: Any, runs: int = 5000,
                seed: int | None = None, threshold: float | None = None) -> dict[str, Any]:
    """Tire les entrées selon leur loi (et les ALEA() des formules), relève les sorties, résume leur distribution."""
    outs = _outputs(outputs)
    runs = int(runs)
    if not 10 <= runs <= MAX_RUNS:
        raise SheetError(f"entre 10 et {MAX_RUNS} tirages")
    refs = {_input(cells, r): spec for r, spec in (inputs or {}).items()}
    rng = random.Random(seed)  # noqa: S311 — simulation, pas de cryptographie
    got: dict[str, list[float]] = {o: [] for o in outs}
    errors = 0
    for _ in range(runs):
        draws = {r: _draw(rng, spec) for r, spec in refs.items()}
        sheet = Sheet(cells, draws, rng=rng)
        for o in outs:
            v = _num(sheet.value(o))
            if v is None:
                errors += 1
            else:
                got[o].append(v)
    result = {"runs": runs, "errors": errors, "inputs": list(refs), "outputs": {o: summary(v) for o, v in got.items()}}
    if threshold is not None:
        t = float(threshold)
        result["above"] = {o: (sum(1 for x in v if x > t) / len(v) if v else None) for o, v in got.items()}
    return result


def goal_seek(cells: dict[str, Any], target_ref: str, value: float, input_ref: str) -> dict[str, Any]:
    """Valeur cible : quelle valeur de la cellule d'entrée donne `value` dans la cellule cible ?"""
    ref, target = _input(cells, input_ref), parse_ref_name(target_ref)
    start = _num(Sheet(cells).value(ref)) or 0.0
    goal = float(value)

    def f(x: float) -> float:
        v = Sheet(cells, {ref: x}).value(target)
        if _num(v) is None:
            raise ZeroDivisionError
        return float(v) - goal

    root = find_root(f, start, tol=1e-12)
    if root is None:
        raise SheetError("pas de solution trouvée près de la valeur actuelle : change la valeur de départ")
    reached = Sheet(cells, {ref: root}).value(target)
    return {"input": ref, "value": root, "display": display(root), "target": target, "reached": _num(reached)}


MODELS = {"lineaire": "y = a·x + b", "polynome": "polynôme de degré n", "exponentiel": "y = a·e^(b·x)",
          "puissance": "y = a·x^b", "logarithme": "y = a + b·ln(x)"}


def _column(cells: dict[str, Any], rng: str) -> list[Any]:
    sheet = Sheet(cells)
    return [sheet.value(r) for r in range_cells(rng.upper().replace("$", ""))]


def fit(cells: dict[str, Any], x_range: str, y_range: str, model: str = "lineaire", degree: int = 2) -> dict[str, Any]:
    """Moindres carrés : équation, coefficients, R², courbe et formule de tableur équivalente."""
    xs_raw, ys_raw = _column(cells, x_range), _column(cells, y_range)
    if len(xs_raw) != len(ys_raw):
        raise SheetError("les plages X et Y doivent avoir la même taille")
    pts = [(_num(a), _num(b)) for a, b in zip(xs_raw, ys_raw, strict=True)]
    pts = [(a, b) for a, b in pts if a is not None and b is not None]
    x = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    if x.size < 2:
        raise SheetError("au moins deux points numériques")
    model = model.lower()
    if model == "lineaire":
        a, b = np.polyfit(x, y, 1)
        pred, coefs = a * x + b, {"a": a, "b": b}
        eq, cell = f"y = {_n(a)}·x {_sgn(b)}", f"={_n(a, 1)}*{{x}}+({_n(b, 1)})"
    elif model == "polynome":
        deg = int(degree)
        if not 1 <= deg <= 6 or x.size <= deg:
            raise SheetError("degré entre 1 et 6, et plus de points que le degré")
        c = np.polyfit(x, y, deg)
        pred = np.polyval(c, x)
        c[np.abs(c) < 1e-9 * np.max(np.abs(c))] = 0.0   # bruit d'arrondi : 1e-14·x n'apporte rien
        coefs = {f"c{deg - i}": v for i, v in enumerate(c)}
        terms = [f"{_n(v)}·x^{deg - i}" if deg - i > 1 else (f"{_n(v)}·x" if deg - i == 1 else _n(v))
                 for i, v in enumerate(c) if v != 0] or ["0"]
        eq = "y = " + " + ".join(terms).replace("+ -", "− ")
        cell = "=" + ("+".join(f"({_n(v, 1)})*{{x}}^{deg - i}" for i, v in enumerate(c) if v != 0) or "0")
    elif model in ("exponentiel", "puissance", "logarithme"):
        if model in ("exponentiel", "puissance") and np.any(y <= 0):
            raise SheetError("modèle exponentiel ou puissance : toutes les valeurs Y doivent être positives")
        if model in ("puissance", "logarithme") and np.any(x <= 0):
            raise SheetError("modèle puissance ou logarithme : toutes les valeurs X doivent être positives")
        if model == "exponentiel":
            b, ln_a = np.polyfit(x, np.log(y), 1)
            a = math.exp(ln_a)
            pred, eq, cell = a * np.exp(b * x), f"y = {_n(a)}·e^({_n(b)}·x)", f"={_n(a, 1)}*EXP({_n(b, 1)}*{{x}})"
        elif model == "puissance":
            b, ln_a = np.polyfit(np.log(x), np.log(y), 1)
            a = math.exp(ln_a)
            pred, eq, cell = a * x ** b, f"y = {_n(a)}·x^{_n(b)}", f"={_n(a, 1)}*{{x}}^{_n(b, 1)}"
        else:
            b, a = np.polyfit(np.log(x), y, 1)
            pred, eq, cell = a + b * np.log(x), f"y = {_n(a)} {_sgn(b)}·ln(x)", f"={_n(a, 1)}+({_n(b, 1)})*LN({{x}})"
        coefs = {"a": a, "b": b}
    else:
        raise SheetError(f"modèle inconnu : {model!r} ({', '.join(MODELS)})")
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    lo, hi = float(x.min()), float(x.max())
    grid = np.linspace(lo, hi, 120)
    curve_cells = {"A1": "0"}
    formula = cell.replace("{x}", "A1")
    sheet_curve = [[float(g), _num(Sheet(curve_cells, {"A1": float(g)}).eval(_parse(formula), None))] for g in grid]
    return {"model": model, "equation": eq, "coefficients": {k: float(v) for k, v in coefs.items()}, "r2": r2,
            "points": [[float(a), float(b)] for a, b in zip(x, y, strict=True)], "curve": sheet_curve,
            "formula": cell, "rmse": math.sqrt(ss_res / x.size)}


def _parse(formula: str) -> Any:
    from modules.data_lab.formula import parse_formula

    return parse_formula(formula)


def _n(v: float, exact: int = 0) -> str:
    v = float(v)
    if exact:
        return repr(v)
    return f"{v:.6g}".replace("e+0", "e").replace("e-0", "e-")


def _sgn(v: float) -> str:
    return f"+ {_n(v)}" if v >= 0 else f"− {_n(-v)}"


def describe(cells: dict[str, Any], rng: str) -> dict[str, Any]:
    values = [_num(v) for v in _column(cells, rng)]
    nums = [v for v in values if v is not None]
    out = summary(nums, bins=min(30, max(5, int(math.sqrt(len(nums) or 1)) + 1)))
    out["text_or_empty"] = len(values) - len(nums)
    if len(nums) > 1:
        out["variance"] = statistics.variance(nums)
    return out


def sort_range(cells: dict[str, Any], rng: str, key_col: str, descending: bool = False,
               header: bool = False) -> dict[str, Any]:
    """Trie les lignes d'une plage de valeurs (pas de formules, elles changeraient de sens en bougeant)."""
    from modules.data_lab.formula import col_index, parse_ref, ref_name

    a, b = rng.upper().replace("$", "").split(":")
    (c1, r1), (c2, r2) = parse_ref(a), parse_ref(b)
    c1, c2, r1, r2 = min(c1, c2), max(c1, c2), min(r1, r2), max(r1, r2)
    k = col_index(key_col.upper()) if key_col.isalpha() else parse_ref(key_col)[0]
    if not c1 <= k <= c2:
        raise SheetError("la colonne de tri doit être dans la plage")
    start = r1 + (1 if header else 0)
    rows = []
    for r in range(start, r2 + 1):
        row = [cells.get(ref_name(c, r), "") for c in range(c1, c2 + 1)]
        if any(isinstance(v, str) and v.startswith("=") for v in row):
            raise SheetError("la plage contient des formules : trie une plage de valeurs (copie les valeurs d'abord)")
        rows.append(row)
    sheet = Sheet(cells)

    def key(row_index: int) -> tuple:
        v = sheet.value(ref_name(k, start + row_index))
        n = _num(v)
        return (0, n, "") if n is not None else (1, 0.0, display(v).lower()) if v not in (None, "") else (2, 0.0, "")

    order = sorted(range(len(rows)), key=key, reverse=descending)
    if descending:   # les cases vides restent en bas
        order = [i for i in order if key(i)[0] != 2] + [i for i in order if key(i)[0] == 2]
    changes = {}
    for new_r, old_i in enumerate(order):
        for ci, c in enumerate(range(c1, c2 + 1)):
            changes[ref_name(c, start + new_r)] = rows[old_i][ci]
    return {"cells": changes}


def errors_of(cells: dict[str, Any]) -> dict[str, str]:
    return {k: v.code for k, v in Sheet(cells).values().items() if isinstance(v, Err)}
