"""Graphes : échantillonnage des courbes (y = f(x), paramétriques, polaires) et analyse (zéros, extrema,
intersections). Le dessin, le zoom et le déplacement sont faits par l'interface : elle redemande des points
pour la nouvelle fenêtre.

Les points sont renvoyés en segments (listes de [x, y]) : une asymptote ou un trou de définition coupe la courbe.
Les abscisses remarquables sont cherchées numériquement (changements de signe puis dichotomie), puis une forme
exacte est proposée (`nsimplify`) **seulement si elle se vérifie** à 50 chiffres.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import sympy as sp

from modules.calc_cas.engine import CasError, Session, latex_of, parse

MAX_CURVES = 8
MAX_SAMPLES = 4000
X, T, THETA = sp.Symbol("x"), sp.Symbol("t"), sp.Symbol("theta")


def _window(raw: dict[str, Any]) -> tuple[float, float, float, float]:
    try:
        xmin, xmax = float(raw.get("xmin", -10)), float(raw.get("xmax", 10))
        ymin, ymax = float(raw.get("ymin", -7)), float(raw.get("ymax", 7))
    except (TypeError, ValueError):
        raise CasError("Fenêtre invalide : xmin, xmax, ymin, ymax doivent être des nombres") from None
    if not all(math.isfinite(v) for v in (xmin, xmax, ymin, ymax)) or xmin >= xmax or ymin >= ymax:
        raise CasError("Fenêtre invalide : il faut xmin < xmax et ymin < ymax")
    return xmin, xmax, ymin, ymax


def _function(text: str, var: sp.Symbol, session: Session) -> tuple[Any, Any]:
    """Texte -> (expression SymPy, fonction numpy vectorisée)."""
    expr = parse(str(text), session, exclude=[str(var)], extra={str(var): var})
    if isinstance(expr, sp.Lambda):
        expr = expr(var)
    if isinstance(expr, sp.Eq):  # « y = x^2 » : on garde le membre de droite
        expr = expr.rhs if expr.lhs == sp.Symbol("y") else expr.lhs - expr.rhs
    if not isinstance(expr, sp.Expr):
        raise CasError(f"« {text} » n'est pas une fonction numérique")
    others = expr.free_symbols - {var}
    if others:
        raise CasError(f"Variable inconnue dans « {text} » : " + ", ".join(sorted(map(str, others)))
                       + f" (seule {var} est permise, ou définis-la avec « := »)")
    fn = sp.lambdify(var, expr, modules=["numpy"])
    return expr, fn


def _eval(fn: Any, values: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        try:
            out = fn(values)
        except (ZeroDivisionError, OverflowError, ValueError, TypeError):
            out = np.array([_safe_scalar(fn, v) for v in values])
    out = np.asarray(out, dtype=complex) * np.ones_like(values)
    real = out.real.astype(float)
    real[np.abs(out.imag) > 1e-9 * (1 + np.abs(real))] = np.nan
    real[~np.isfinite(real)] = np.nan
    return real


def _safe_scalar(fn: Any, v: float) -> complex:
    try:
        return complex(fn(v))
    except (ZeroDivisionError, OverflowError, ValueError, TypeError):
        return complex(np.nan)


def _segments(xs: np.ndarray, ys: np.ndarray, ylim: tuple[float, float] | None) -> list[list[list[float]]]:
    """Coupe aux valeurs non définies et aux sauts d'un bord de la fenêtre à l'autre (asymptotes verticales)."""
    ymin, ymax = ylim or (-math.inf, math.inf)
    span_y = ymax - ymin
    segments: list[list[list[float]]] = []
    current: list[list[float]] = []
    prev_y = None
    for x, y in zip(xs.tolist(), ys.tolist(), strict=True):
        if math.isnan(x) or math.isnan(y):
            if len(current) > 1:
                segments.append(current)
            current, prev_y = [], None
            continue
        if prev_y is not None and (abs(y - prev_y) > 4 * span_y or (prev_y > ymax and y < ymin)
                                   or (prev_y < ymin and y > ymax)):
            if len(current) > 1:
                segments.append(current)
            current = []
        current.append([float(f"{x:.6g}"), float(f"{y:.6g}")])
        prev_y = y
    if len(current) > 1:
        segments.append(current)
    return segments


def plot(curves: list[dict[str, Any]], window: dict[str, Any], session: Session,
         samples: int = 600) -> dict[str, Any]:
    """Points de chaque courbe. Une courbe invalide reçoit `error` sans empêcher les autres."""
    if not isinstance(curves, list) or not curves:
        raise CasError("Aucune courbe à tracer")
    if len(curves) > MAX_CURVES:
        raise CasError(f"{MAX_CURVES} courbes au plus")
    xmin, xmax, ymin, ymax = _window(window)
    samples = max(50, min(int(samples), MAX_SAMPLES))
    span_y = ymax - ymin
    out = []
    for index, curve in enumerate(curves):
        kind = str(curve.get("kind", "y"))
        item: dict[str, Any] = {"index": index, "kind": kind}
        try:
            if kind == "y":
                expr, fn = _function(curve.get("expr", ""), X, session)
                xs = np.linspace(xmin, xmax, samples)
                ys = _eval(fn, xs)
                ys[(ys < ymin - 50 * span_y) | (ys > ymax + 50 * span_y)] = np.nan
                item.update(label=f"y = {sp.sstr(expr)}", latex=f"y = {latex_of(expr)}")
            elif kind in ("param", "polar"):
                tmin, tmax = float(curve.get("tmin", 0)), float(curve.get("tmax", 2 * math.pi))
                if not (math.isfinite(tmin) and math.isfinite(tmax)) or tmin >= tmax:
                    raise CasError("Intervalle du paramètre invalide (tmin < tmax)")
                ts = np.linspace(tmin, tmax, samples)
                if kind == "param":
                    ex, fx = _function(curve.get("x", ""), T, session)
                    ey, fy = _function(curve.get("y", ""), T, session)
                    xs, ys = _eval(fx, ts), _eval(fy, ts)
                    item.update(label=f"x = {sp.sstr(ex)}, y = {sp.sstr(ey)}")
                else:
                    er, fr = _function(curve.get("r", curve.get("expr", "")), THETA, session)
                    rs = _eval(fr, ts)
                    xs, ys = rs * np.cos(ts), rs * np.sin(ts)
                    item.update(label=f"r = {sp.sstr(er)}")
            else:
                raise CasError(f"Type de courbe inconnu : {kind!r} (y, param ou polar)")
            item["segments"] = _segments(xs, ys, (ymin, ymax) if kind == "y" else None)
        except CasError as exc:
            item["error"] = str(exc)
        out.append(item)
    return {"ok": True, "window": {"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax}, "curves": out}


# ---------------------------------------------------------------- analyse
def _bisect(fn: Any, a: float, b: float, fa: float) -> float:
    for _ in range(80):
        m = (a + b) / 2
        fm = float(_eval(fn, np.array([m]))[0])
        if math.isnan(fm):
            return math.nan
        if fm == 0:
            return m
        if (fm < 0) == (fa < 0):
            a, fa = m, fm
        else:
            b = m
    return (a + b) / 2


def _roots(expr: Any, fn: Any, xmin: float, xmax: float, n: int = 2000) -> list[float]:
    """Racines de `expr` dans [xmin, xmax] : changements de signe et minima de |f| proches de 0."""
    xs = np.linspace(xmin, xmax, n)
    ys = _eval(fn, xs)
    scale = float(np.nanmax(np.abs(ys))) if np.any(np.isfinite(ys)) else 1.0
    roots: list[float] = []
    for i in range(n - 1):
        a, b, fa, fb = xs[i], xs[i + 1], ys[i], ys[i + 1]
        if math.isnan(fa) or math.isnan(fb):
            continue
        if fa == 0:
            roots.append(float(a))
        elif fa * fb < 0:
            r = _bisect(fn, float(a), float(b), float(fa))
            # écarte les faux zéros d'une discontinuité (tan, 1/x) : |f| doit être petit au point trouvé
            if not math.isnan(r) and abs(float(_eval(fn, np.array([r]))[0])) < 1e-6 * (1 + scale):
                roots.append(r)
        elif 0 < i and abs(fa) < 1e-9 * (1 + scale) and not math.isnan(ys[i - 1]) \
                and abs(ys[i - 1]) > abs(fa) < abs(fb):
            roots.append(float(a))  # racine double (tangente à l'axe)
    if not math.isnan(ys[-1]) and ys[-1] == 0:
        roots.append(float(xs[-1]))
    # tangence fine : minimum local de |f| entre deux échantillons, raffiné sur la dérivée
    try:
        d_expr = sp.diff(expr, X)
        d_fn = sp.lambdify(X, d_expr, modules=["numpy"])
        dys = _eval(d_fn, xs)
        for i in range(n - 1):
            if dys[i] * dys[i + 1] < 0 and not math.isnan(ys[i]) and abs(ys[i]) < 1e-3 * (1 + scale):
                r = _bisect(d_fn, float(xs[i]), float(xs[i + 1]), float(dys[i]))
                if not math.isnan(r) and abs(float(_eval(fn, np.array([r]))[0])) < 1e-10 * (1 + scale):
                    roots.append(r)
    except (TypeError, ValueError, NotImplementedError):
        pass
    roots.sort()
    unique: list[float] = []
    for r in roots:
        if not unique or abs(r - unique[-1]) > 1e-7 * max(1.0, abs(r)):
            unique.append(r)
    return unique[:50]


def exact_guess(value: float, expr: Any) -> Any:
    """Forme exacte d'une racine numérique (√2, π/4, 1/3…) si elle annule vraiment `expr` à 50 chiffres."""
    if abs(value) < 1e-12:
        candidates = [sp.Integer(0)]
    else:
        candidates = []
        for consts in ([], [sp.pi], [sp.E]):
            try:
                candidates.append(sp.nsimplify(value, consts, tolerance=1e-9, rational=False))
            except (TypeError, ValueError, NotImplementedError):
                continue
    for cand in candidates:
        if cand.is_Float or len(str(cand)) > 40:
            continue
        try:
            residue = abs(complex(sp.N(expr.subs(X, cand), 50)))
        except (TypeError, ValueError):
            continue
        if residue < 1e-40:
            return cand
    return None


def _point(x: float, y_fn: Any, y_expr: Any, kind: str, root_expr: Any) -> dict[str, Any]:
    y = float(_eval(y_fn, np.array([x]))[0])
    point: dict[str, Any] = {"type": kind, "x": float(f"{x:.12g}"), "y": float(f"{y:.12g}") if math.isfinite(y)
                             else None}
    exact = exact_guess(x, root_expr)
    if exact is not None:
        point["x_exact"] = sp.sstr(exact)
        point["x_latex"] = latex_of(exact)
        try:
            y_exact = sp.nsimplify(sp.simplify(y_expr.subs(X, exact)))
            if len(sp.sstr(y_exact)) <= 40:
                point["y_exact"] = sp.sstr(y_exact)
                point["y_latex"] = latex_of(y_exact)
        except (TypeError, ValueError, NotImplementedError):
            pass
    return point


def analyze(args: dict[str, Any], session: Session) -> dict[str, Any]:
    """`what` : « zeros », « extrema » ou « intersections » (avec `other`) sur [xmin, xmax]."""
    what = str(args.get("what", "zeros"))
    xmin, xmax = float(args.get("xmin", -10)), float(args.get("xmax", 10))
    if not (math.isfinite(xmin) and math.isfinite(xmax)) or xmin >= xmax:
        raise CasError("Intervalle invalide : il faut xmin < xmax")
    expr, fn = _function(args.get("expr", ""), X, session)
    points: list[dict[str, Any]] = []
    if what == "zeros":
        for r in _roots(expr, fn, xmin, xmax):
            points.append(_point(r, fn, expr, "zéro", expr))
    elif what == "extrema":
        d1 = sp.diff(expr, X)
        d1_fn = sp.lambdify(X, d1, modules=["numpy"])
        d2_fn = sp.lambdify(X, sp.diff(d1, X), modules=["numpy"])
        for r in _roots(d1, d1_fn, xmin, xmax):
            curv = float(_eval(d2_fn, np.array([r]))[0])
            h = 1e-4 * max(1.0, abs(r))
            left, mid, right = _eval(fn, np.array([r - h, r, r + h]))
            if math.isnan(curv) or abs(curv) < 1e-10:
                if mid < left and mid < right:
                    kind = "minimum"
                elif mid > left and mid > right:
                    kind = "maximum"
                else:
                    continue  # point d'inflexion à tangente horizontale
            else:
                kind = "minimum" if curv > 0 else "maximum"
            points.append(_point(r, fn, expr, kind, d1))
    elif what == "intersections":
        other, _ = _function(args.get("other", ""), X, session)
        diff = sp.simplify(expr - other)
        diff_fn = sp.lambdify(X, diff, modules=["numpy"])
        for r in _roots(diff, diff_fn, xmin, xmax):
            points.append(_point(r, fn, expr, "intersection", diff))
    else:
        raise CasError("Analyse inconnue : zeros, extrema ou intersections")
    return {"ok": True, "what": what, "expr": sp.sstr(expr), "points": points}
