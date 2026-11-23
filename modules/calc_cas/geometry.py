"""Mesures exactes de géométrie plane pour l'application Géométrie de la fenêtre.

La construction (points libres, segments, droites, cercles, perpendiculaires…) vit dans la page et se recalcule
en direct pendant qu'on déplace les points. Ici, à la demande, le moteur rend les **valeurs exactes** :

    measure({"what": "distance", "points": [[0, 0], [1, 1]]})       # -> √2 ≈ 1.41421356237
    measure({"what": "angle", "points": [[1, 0], [0, 0], [0, 1]]})   # -> π/2 (ou 90 en degrés)
    measure({"what": "circumcircle", "points": [[0, 0], [2, 0], [0, 2]]})

Les coordonnées décimales sont converties en fractions (`0.5` → 1/2) : avec la grille magnétique, les points
tombent sur des valeurs simples et les mesures exactes ont un sens (√2, 3√5/2…).
"""
from __future__ import annotations

from typing import Any

import sympy as sp

from modules.calc_cas.engine import CasError, Session, parse, present

X, Y = sp.symbols("x y", real=True)
NEEDED = {"distance": 2, "midpoint": 2, "slope": 2, "line": 2, "angle": 3, "area": 3, "perimeter": 2,
          "circle": 2, "circumcircle": 3, "intersection": 4}


def _coord(value: Any, session: Session) -> Any:
    if isinstance(value, bool):
        raise CasError("Coordonnée invalide")
    if isinstance(value, int | float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CasError("Coordonnée non finie")
        return sp.nsimplify(value, rational=True, tolerance=1e-9) if isinstance(value, float) else sp.Integer(value)
    expr = parse(str(value), session)
    if not getattr(expr, "is_real", False) or expr.free_symbols:
        raise CasError(f"Coordonnée non réelle : {value}")
    return expr


def _points(args: dict[str, Any], session: Session) -> list[sp.Point2D]:
    raw = args.get("points")
    if not isinstance(raw, list) or not all(isinstance(p, list | tuple) and len(p) == 2 for p in raw):
        raise CasError("Points attendus sous la forme [[x, y], …]")
    if len(raw) > 64:
        raise CasError("64 points au plus")
    return [sp.Point2D(_coord(p[0], session), _coord(p[1], session), evaluate=False) for p in raw]


def _line_equation(a: sp.Point2D, b: sp.Point2D) -> Any:
    if a.equals(b):
        raise CasError("Deux points confondus ne définissent pas de droite")
    dx, dy = b.x - a.x, b.y - a.y
    if sp.simplify(dx) == 0:
        return sp.Eq(X, sp.simplify(a.x))
    m = sp.simplify(dy / dx)
    return sp.Eq(Y, sp.expand(m * X + sp.simplify(a.y - m * a.x)))


def measure(args: dict[str, Any], session: Session | None = None) -> dict[str, Any]:
    """Mesure exacte : `what` parmi distance, midpoint, slope, line, angle, area, perimeter, circle (centre, point),
    circumcircle (3 points), intersection (droites AB et CD). `degrees` pour les angles."""
    session = session or Session()
    what = str(args.get("what", ""))
    if what not in NEEDED:
        raise CasError(f"Mesure inconnue : {what!r} (possibles : {', '.join(NEEDED)})")
    pts = _points(args, session)
    if len(pts) < NEEDED[what] or (what not in ("area", "perimeter") and len(pts) != NEEDED[what]):
        raise CasError(f"{what} : {NEEDED[what]} points attendus")
    if what == "distance":
        result = sp.sqrt(sp.simplify((pts[1].x - pts[0].x) ** 2 + (pts[1].y - pts[0].y) ** 2))
    elif what == "midpoint":
        result = [sp.simplify((pts[0].x + pts[1].x) / 2), sp.simplify((pts[0].y + pts[1].y) / 2)]
    elif what == "slope":
        dx = sp.simplify(pts[1].x - pts[0].x)
        if dx == 0:
            raise CasError("Droite verticale : pas de coefficient directeur")
        result = sp.simplify((pts[1].y - pts[0].y) / dx)
    elif what == "line":
        result = _line_equation(pts[0], pts[1])
    elif what == "angle":
        a, b, c = pts
        u, v = (a.x - b.x, a.y - b.y), (c.x - b.x, c.y - b.y)
        nu, nv = u[0] ** 2 + u[1] ** 2, v[0] ** 2 + v[1] ** 2
        if sp.simplify(nu) == 0 or sp.simplify(nv) == 0:
            raise CasError("Angle indéfini : un côté est de longueur nulle")
        result = sp.simplify(sp.acos(sp.simplify((u[0] * v[0] + u[1] * v[1]) / sp.sqrt(nu * nv))))
        if args.get("degrees"):
            result = sp.simplify(result * 180 / sp.pi)
    elif what in ("area", "perimeter"):
        n = len(pts)
        if what == "area":
            twice = sum(pts[i].x * pts[(i + 1) % n].y - pts[(i + 1) % n].x * pts[i].y for i in range(n))
            result = sp.Abs(sp.simplify(twice)) / 2
        else:
            closed = n > 2
            sides = range(n if closed else n - 1)
            result = sp.simplify(sum(sp.sqrt(sp.simplify((pts[(i + 1) % n].x - pts[i].x) ** 2
                                                          + (pts[(i + 1) % n].y - pts[i].y) ** 2)) for i in sides))
    elif what == "circle":
        center, through = pts
        r2 = sp.simplify((through.x - center.x) ** 2 + (through.y - center.y) ** 2)
        if r2 == 0:
            raise CasError("Cercle de rayon nul")
        result = {"centre": [center.x, center.y], "rayon": sp.sqrt(r2),
                  "équation": sp.Eq((X - center.x) ** 2 + (Y - center.y) ** 2, r2)}
    elif what == "circumcircle":
        a, b, c = pts
        if sp.simplify((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)) == 0:
            raise CasError("Points alignés : pas de cercle circonscrit")
        circle = sp.Circle(a, b, c)
        r2 = sp.simplify(circle.radius ** 2)
        result = {"centre": [sp.simplify(circle.center.x), sp.simplify(circle.center.y)],
                  "rayon": sp.sqrt(r2),
                  "équation": sp.Eq((X - circle.center.x) ** 2 + (Y - circle.center.y) ** 2, r2)}
    else:  # intersection des droites (AB) et (CD)
        a, b, c, d = pts
        if a.equals(b) or c.equals(d):
            raise CasError("Deux points confondus ne définissent pas de droite")
        found = sp.Line(a, b).intersection(sp.Line(c, d))
        if not found:
            raise CasError("Droites parallèles : pas d'intersection")
        if isinstance(found[0], sp.Line):
            raise CasError("Droites confondues")
        result = [sp.simplify(found[0].x), sp.simplify(found[0].y)]
    return {"ok": True, "what": what, **present(result)}
