"""Mesures exactes de géométrie plane pour l'application Géométrie de la fenêtre.

La construction (points libres, segments, droites, cercles, perpendiculaires, transformations, lieux…) vit dans la
page et se recalcule en direct pendant qu'on déplace les points. Ici, à la demande, le moteur rend les **valeurs
exactes**, de deux façons :

    measure({"what": "distance", "points": [[0, 0], [1, 1]]})       # -> √2 ≈ 1.41421356237
    measure({"what": "angle", "points": [[1, 0], [0, 0], [0, 1]]})   # -> π/2 (ou 90 en degrés)
    measure({"what": "figure", "objects": [...], "measure": {"m": "len", "refs": [3, 7]}})

Avec `figure`, la page envoie **toute la construction** (les mêmes objets qu'elle dessine) : le moteur la refait en
calcul exact, objet par objet, avec les mêmes formules et le même ordre des points d'intersection que la page. Un
point construit à coordonnées irrationnelles (intersection d'un cercle et d'une droite…) a donc sa vraie valeur
(`1 + √7/2`), et pas celle d'une fraction proche. L'équation d'un **lieu géométrique** s'obtient par élimination du
paramètre (bases de Gröbner) quand le point tracé dépend rationnellement du point mobile.

Les coordonnées décimales des points libres sont converties en fractions (`0.5` → 1/2) : avec la grille magnétique,
les points tombent sur des valeurs simples et les mesures exactes ont un sens (√2, 3√5/2…). Un point posé sur un
cercle (outil « Point sur objet ») est pris à sa position décimale, convertie en fraction.
"""
from __future__ import annotations

from typing import Any

import sympy as sp

from modules.calc_cas.engine import CasError, Session, parse, present

X, Y = sp.symbols("x y", real=True)
NEEDED = {"distance": 2, "midpoint": 2, "slope": 2, "line": 2, "angle": 3, "area": 3, "perimeter": 2,
          "circle": 2, "circumcircle": 3, "intersection": 4}
KINDS = {"pt", "mid", "inter", "seg", "line", "perp", "par", "bis", "circ", "circ3", "poly", "pton", "tr", "locus",
         "meas"}
MAX_OBJECTS = 300
EPS = 1e-12


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


def _circle(cx: Any, cy: Any, r2: Any) -> dict[str, Any]:
    r2 = sp.simplify(r2)
    if r2 == 0:
        raise CasError("Cercle de rayon nul")
    cx, cy = sp.simplify(cx), sp.simplify(cy)
    return {"centre": [cx, cy], "rayon": sp.sqrt(r2), "équation": sp.Eq((X - cx) ** 2 + (Y - cy) ** 2, r2)}


def _compute(what: str, pts: list[sp.Point2D], args: dict[str, Any]) -> Any:
    if len(pts) < NEEDED[what] or (what not in ("area", "perimeter") and len(pts) != NEEDED[what]):
        raise CasError(f"{what} : {NEEDED[what]} points attendus")
    if what == "distance":
        return sp.sqrt(sp.simplify((pts[1].x - pts[0].x) ** 2 + (pts[1].y - pts[0].y) ** 2))
    if what == "midpoint":
        return [sp.simplify((pts[0].x + pts[1].x) / 2), sp.simplify((pts[0].y + pts[1].y) / 2)]
    if what == "slope":
        dx = sp.simplify(pts[1].x - pts[0].x)
        if dx == 0:
            raise CasError("Droite verticale : pas de coefficient directeur")
        return sp.simplify((pts[1].y - pts[0].y) / dx)
    if what == "line":
        return _line_equation(pts[0], pts[1])
    if what == "angle":
        a, b, c = pts
        u, v = (a.x - b.x, a.y - b.y), (c.x - b.x, c.y - b.y)
        nu, nv = u[0] ** 2 + u[1] ** 2, v[0] ** 2 + v[1] ** 2
        if sp.simplify(nu) == 0 or sp.simplify(nv) == 0:
            raise CasError("Angle indéfini : un côté est de longueur nulle")
        result = sp.simplify(sp.acos(sp.simplify((u[0] * v[0] + u[1] * v[1]) / sp.sqrt(nu * nv))))
        return sp.simplify(result * 180 / sp.pi) if args.get("degrees") else result
    if what in ("area", "perimeter"):
        n = len(pts)
        if what == "area":
            twice = sum(pts[i].x * pts[(i + 1) % n].y - pts[(i + 1) % n].x * pts[i].y for i in range(n))
            return sp.Abs(sp.simplify(twice)) / 2
        sides = range(n if n > 2 else n - 1)
        return sp.simplify(sum(sp.sqrt(sp.simplify((pts[(i + 1) % n].x - pts[i].x) ** 2
                                                   + (pts[(i + 1) % n].y - pts[i].y) ** 2)) for i in sides))
    if what == "circle":
        center, through = pts
        return _circle(center.x, center.y, (through.x - center.x) ** 2 + (through.y - center.y) ** 2)
    if what == "circumcircle":
        a, b, c = pts
        if sp.simplify((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)) == 0:
            raise CasError("Points alignés : pas de cercle circonscrit")
        circle = sp.Circle(a, b, c)
        return _circle(circle.center.x, circle.center.y, circle.radius ** 2)
    a, b, c, d = pts  # intersection des droites (AB) et (CD)
    if a.equals(b) or c.equals(d):
        raise CasError("Deux points confondus ne définissent pas de droite")
    found = sp.Line(a, b).intersection(sp.Line(c, d))
    if not found:
        raise CasError("Droites parallèles : pas d'intersection")
    if isinstance(found[0], sp.Line):
        raise CasError("Droites confondues")
    return [sp.simplify(found[0].x), sp.simplify(found[0].y)]


def measure(args: dict[str, Any], session: Session | None = None) -> dict[str, Any]:
    """Mesure exacte : `what` parmi distance, midpoint, slope, line, angle, area, perimeter, circle (centre, point),
    circumcircle (3 points), intersection (droites AB et CD), ou `figure` (construction complète, voir le module).
    `degrees` pour les angles."""
    session = session or Session()
    what = str(args.get("what", ""))
    if what == "figure":
        return figure_measure(args, session)
    if what not in NEEDED:
        raise CasError(f"Mesure inconnue : {what!r} (possibles : {', '.join(NEEDED)}, figure)")
    return {"ok": True, "what": what, **present(_compute(what, _points(args, session), args))}


# ---------- construction refaite en exact ----------
def _float(expr: Any) -> float | None:
    """Valeur décimale d'une expression sans paramètre (None si elle dépend du paramètre d'un lieu)."""
    if getattr(expr, "free_symbols", None):
        return None
    return float(sp.re(sp.N(expr, 30)))


def _zero(expr: Any) -> bool:
    value = _float(expr)
    if value is None:
        return sp.simplify(expr) == 0
    return abs(value) < EPS


def _clean(expr: Any) -> Any:
    return sp.radsimp(sp.simplify(expr))


def _intersect(u: dict[str, Any] | None, v: dict[str, Any] | None) -> list[Any]:
    """Points d'intersection, dans l'ordre de la page (calc_geo.js, `intersect`)."""
    if not u or not v:
        return []
    if u["k"] == "ci" and v["k"] == "ln":
        u, v = v, u

    def on_seg(line: dict[str, Any], t: Any) -> bool:
        value = _float(t)
        return not line["seg"] or value is None or -1e-9 < value < 1 + 1e-9

    if u["k"] == "ln" and v["k"] == "ln":
        (ux, uy), (vx, vy) = u["a"], v["a"]
        udx, udy, vdx, vdy = u["b"][0] - ux, u["b"][1] - uy, v["b"][0] - vx, v["b"][1] - vy
        den = udx * vdy - udy * vdx
        if _zero(den):
            return []
        t = ((vx - ux) * vdy - (vy - uy) * vdx) / den
        s = ((vx - ux) * udy - (vy - uy) * udx) / den
        return [(ux + t * udx, uy + t * udy)] if on_seg(u, t) and on_seg(v, s) else []
    if u["k"] == "ln" and v["k"] == "ci":
        (ux, uy), (cx, cy) = u["a"], v["c"]
        udx, udy = u["b"][0] - ux, u["b"][1] - uy
        fx, fy = ux - cx, uy - cy
        a, b, c = udx ** 2 + udy ** 2, 2 * (fx * udx + fy * udy), fx ** 2 + fy ** 2 - v["r2"]
        disc = b ** 2 - 4 * a * c
        value = _float(disc)
        if value is not None and value < -EPS:
            return []
        root = 0 if value is not None and abs(value) < EPS else sp.sqrt(disc)
        return [(ux + t * udx, uy + t * udy) if on_seg(u, t) else None
                for t in ((-b - root) / (2 * a), (-b + root) / (2 * a))]
    if u["k"] == "ci" and v["k"] == "ci":
        (ux, uy), (vx, vy) = u["c"], v["c"]
        dx, dy = vx - ux, vy - uy
        d2 = dx ** 2 + dy ** 2
        d = sp.sqrt(d2)
        num = [_float(e) for e in (d, sp.sqrt(u["r2"]), sp.sqrt(v["r2"]))]
        if None not in num:
            dd, ur, vr = num
            if dd < EPS or dd > ur + vr + EPS or dd < abs(ur - vr) - EPS:
                return []
        a = (u["r2"] - v["r2"] + d2) / (2 * d)
        h2 = u["r2"] - a ** 2
        h2v = _float(h2)
        h = 0 if h2v is not None and abs(h2v) < EPS else sp.sqrt(h2)
        mx, my = ux + a * dx / d, uy + a * dy / d
        return [(mx - h * dy / d, my + h * dx / d), (mx + h * dy / d, my - h * dx / d)]
    return []


def _transform(o: dict[str, Any], R: dict[int, Any]) -> Any:
    """Fonction point -> point de la transformation `o` (symétries, rotation, translation)."""
    kind = o.get("f")
    if kind == "symc":
        cx, cy = _pt(R, o.get("c"))
        return lambda p: (2 * cx - p[0], 2 * cy - p[1])
    if kind == "syma":
        line = _get(R, o.get("l"), "ln")
        (ax, ay), (bx, by) = line["a"], line["b"]
        dx, dy = bx - ax, by - ay
        n2 = dx ** 2 + dy ** 2

        def mirror(p: Any) -> Any:
            k = ((p[0] - ax) * dx + (p[1] - ay) * dy) / n2
            return (2 * (ax + k * dx) - p[0], 2 * (ay + k * dy) - p[1])
        return mirror
    if kind == "rot":
        cx, cy = _pt(R, o.get("c"))
        try:
            theta = sp.Rational(str(o.get("deg", "0"))) * sp.pi / 180
        except (TypeError, ValueError):
            raise CasError("Angle de rotation invalide") from None
        cos, sin = sp.cos(theta), sp.sin(theta)
        return lambda p: (cx + cos * (p[0] - cx) - sin * (p[1] - cy), cy + sin * (p[0] - cx) + cos * (p[1] - cy))
    if kind == "trans":
        (ax, ay), (bx, by) = _pt(R, o.get("a")), _pt(R, o.get("b"))
        return lambda p: (p[0] + bx - ax, p[1] + by - ay)
    raise CasError(f"Transformation inconnue : {kind!r}")


class _Missing(Exception):
    """Objet dont un parent n'existe pas (comme `null` dans la page)."""


def _get(R: dict[int, Any], oid: Any, kind: str) -> dict[str, Any]:
    v = R.get(oid)
    if not v or v["k"] != kind:
        raise _Missing
    return v


def _pt(R: dict[int, Any], oid: Any) -> tuple[Any, Any]:
    return _get(R, oid, "pt")["xy"]


def _line(a: Any, b: Any, seg: bool) -> dict[str, Any]:
    if _zero((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2):
        raise _Missing
    return {"k": "ln", "a": a, "b": b, "seg": seg}


def _solve_one(o: dict[str, Any], R: dict[int, Any], session: Session, param: dict[str, Any] | None) -> Any:
    t = o.get("t")
    if t == "pt":
        return {"k": "pt", "xy": (_coord(o.get("x"), session), _coord(o.get("y"), session))}
    if t == "mid":
        (ax, ay), (bx, by) = _pt(R, o.get("a")), _pt(R, o.get("b"))
        return {"k": "pt", "xy": ((ax + bx) / 2, (ay + by) / 2)}
    if t == "inter":
        found = _intersect(R.get(o.get("a")), R.get(o.get("b")))
        i = o.get("i")
        if not isinstance(i, int) or not 0 <= i < len(found) or found[i] is None:
            raise _Missing
        return {"k": "pt", "xy": found[i]}
    if t in ("seg", "line"):
        return _line(_pt(R, o.get("a")), _pt(R, o.get("b")), t == "seg")
    if t in ("perp", "par"):
        line, (px, py) = _get(R, o.get("l"), "ln"), _pt(R, o.get("p"))
        dx, dy = line["b"][0] - line["a"][0], line["b"][1] - line["a"][1]
        if t == "perp":
            dx, dy = -dy, dx
        return _line((px, py), (px + dx, py + dy), False)
    if t == "bis":
        (ax, ay), (bx, by) = _pt(R, o.get("a")), _pt(R, o.get("b"))
        mx, my = (ax + bx) / 2, (ay + by) / 2
        return _line((mx, my), (mx - (by - ay), my + (bx - ax)), False)
    if t == "circ":
        (cx, cy), (px, py) = _pt(R, o.get("c")), _pt(R, o.get("p"))
        r2 = (px - cx) ** 2 + (py - cy) ** 2
        if _zero(r2):
            raise _Missing
        return {"k": "ci", "c": (cx, cy), "r2": r2}
    if t == "circ3":
        (ax, ay), (bx, by), (cx, cy) = (_pt(R, o.get(k)) for k in ("a", "b", "c"))
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if _zero(d):
            raise _Missing
        sa, sb, sc = ax ** 2 + ay ** 2, bx ** 2 + by ** 2, cx ** 2 + cy ** 2
        x = (sa * (by - cy) + sb * (cy - ay) + sc * (ay - by)) / d
        y = (sa * (cx - bx) + sb * (ax - cx) + sc * (bx - ax)) / d
        return {"k": "ci", "c": (x, y), "r2": (ax - x) ** 2 + (ay - y) ** 2}
    if t == "poly":
        pts = o.get("pts")
        if not isinstance(pts, list) or len(pts) > 64:
            raise CasError("Polygone invalide")
        return {"k": "pg", "pts": [_pt(R, p) for p in pts]}
    if t == "pton":
        curve = R.get(o.get("c"))
        if not curve:
            raise _Missing
        if param and param["id"] == o.get("id"):
            if curve["k"] == "ln":
                (ax, ay), (bx, by) = curve["a"], curve["b"]
                return {"k": "pt", "xy": (ax + param["T"] * (bx - ax), ay + param["T"] * (by - ay))}
            (cx, cy), r = curve["c"], sp.sqrt(curve["r2"])
            return {"k": "pt", "xy": (cx + r * param["C"], cy + r * param["S"])}
        if curve["k"] == "ln":  # position exacte sur la droite : paramètre converti en fraction
            u = _coord(o.get("u", 0), session)
            (ax, ay), (bx, by) = curve["a"], curve["b"]
            return {"k": "pt", "xy": (ax + u * (bx - ax), ay + u * (by - ay))}
        return {"k": "pt", "xy": (_coord(o.get("x"), session), _coord(o.get("y"), session))}
    if t == "tr":
        f = _transform(o, R)
        src = R.get(o.get("s"))
        if not src:
            raise _Missing
        if src["k"] == "pt":
            return {"k": "pt", "xy": f(src["xy"])}
        if src["k"] == "ln":
            return {"k": "ln", "a": f(src["a"]), "b": f(src["b"]), "seg": src["seg"]}
        if src["k"] == "ci":
            return {"k": "ci", "c": f(src["c"]), "r2": src["r2"]}
        if src["k"] == "pg":
            return {"k": "pg", "pts": [f(p) for p in src["pts"]]}
        raise _Missing
    return None  # mesures et lieux : pas d'objet géométrique ici


def _objects(args: dict[str, Any]) -> list[dict[str, Any]]:
    objs = args.get("objects")
    if not isinstance(objs, list) or not objs:
        raise CasError("Figure vide")
    if len(objs) > MAX_OBJECTS:
        raise CasError(f"{MAX_OBJECTS} objets au plus")
    for o in objs:
        if not isinstance(o, dict) or not isinstance(o.get("id"), int) or o.get("t") not in KINDS:
            raise CasError("Objet de figure invalide")
    return objs


def solve_figure(objs: list[dict[str, Any]], session: Session,
                 param: dict[str, Any] | None = None) -> dict[int, Any]:
    R: dict[int, Any] = {}
    for o in objs:
        try:
            R[o["id"]] = _solve_one(o, R, session, param)
        except _Missing:
            R[o["id"]] = None
    return R


def _named(objs: list[dict[str, Any]], oid: Any) -> str:
    return next((str(o.get("name")) for o in objs if o.get("id") == oid and o.get("name")), "?")


def _locus_equation(objs: list[dict[str, Any]], R: dict[int, Any], locus: dict[str, Any],
                    session: Session) -> Any:
    """Équation du lieu du point `a` quand le point sur objet `b` parcourt sa courbe (élimination du paramètre)."""
    driver = next((o for o in objs if o.get("id") == locus.get("b") and o.get("t") == "pton"), None)
    curve = R.get(driver.get("c")) if driver else None
    if not curve:
        raise CasError("Lieu : le point mobile doit être un point sur objet")
    T, C, S, Z = sp.symbols("_t _c _s _z")
    gens = [T] if curve["k"] == "ln" else [C, S]
    traced = solve_figure(objs, session, {"id": driver["id"], "T": T, "C": C, "S": S}).get(locus.get("a"))
    if not traced or traced["k"] != "pt":
        raise CasError("Lieu : le point tracé n'existe pas")
    polys, dens = [], []
    for coord, value in zip((X, Y), traced["xy"], strict=True):
        num, den = sp.fraction(sp.together(sp.expand(value)))
        try:
            sp.Poly(num, *gens)
            sp.Poly(den, *gens)
        except sp.PolynomialError:
            raise CasError("Lieu : le point tracé ne dépend pas rationnellement du point mobile "
                           "(racine carrée…) ; équation exacte non disponible") from None
        polys.append(sp.expand(coord * den - num))
        dens.append(den)
    if curve["k"] == "ci":
        polys.append(C ** 2 + S ** 2 - 1)
    polys.append(sp.expand(Z * dens[0] * dens[1] - 1))  # écarte les valeurs qui annulent un dénominateur
    try:
        basis = sp.groebner(polys, Z, *gens, X, Y, order="lex")
    except Exception as exc:  # noqa: BLE001 — coefficients hors de portée de l'élimination
        raise CasError(f"Lieu : élimination impossible ({type(exc).__name__})") from None
    found = [g for g in basis.exprs if not (g.free_symbols & {Z, *gens})]
    if not found:
        raise CasError("Lieu : pas d'équation (le point tracé ne bouge pas, ou le lieu remplit le plan)")
    eq = sp.factor(min(found, key=sp.count_ops))
    return sp.Eq(eq, 0)


def figure_measure(args: dict[str, Any], session: Session) -> dict[str, Any]:
    """Valeur exacte d'une mesure de la construction : `measure` = {"m": len|angle|area|pt|eq, "refs"|"c"}."""
    objs = _objects(args)
    spec = args.get("measure")
    if not isinstance(spec, dict):
        raise CasError("Mesure de figure attendue")
    R = solve_figure(objs, session)
    m = spec.get("m")
    if m in ("len", "angle", "area", "pt"):
        refs = spec.get("refs")
        if not isinstance(refs, list) or not refs or len(refs) > 64:
            raise CasError("Points de la mesure invalides")
        pts = []
        for ref in refs:
            v = R.get(ref)
            if not v or v["k"] != "pt":
                raise CasError(f"Le point {_named(objs, ref)} n'existe pas dans cette position")
            pts.append(sp.Point2D(_clean(v["xy"][0]), _clean(v["xy"][1]), evaluate=False))
        if m == "pt":
            return {"ok": True, "what": "point", **present([pts[0].x, pts[0].y])}
        what = {"len": "distance", "angle": "angle", "area": "area"}[m]
        return {"ok": True, "what": what, **present(_compute(what, pts, args))}
    if m == "eq":
        target = next((o for o in objs if o.get("id") == spec.get("c")), None)
        if target and target.get("t") == "locus":
            return {"ok": True, "what": "locus", **present(_locus_equation(objs, R, target, session))}
        v = R.get(spec.get("c"))
        if not v or v["k"] not in ("ln", "ci"):
            raise CasError("Équation : choisir une droite, un cercle ou un lieu")
        if v["k"] == "ln":
            a, b = (sp.Point2D(_clean(p[0]), _clean(p[1]), evaluate=False) for p in (v["a"], v["b"]))
            return {"ok": True, "what": "line", **present(_line_equation(a, b))}
        return {"ok": True, "what": "circle", **present(_circle(_clean(v["c"][0]), _clean(v["c"][1]), v["r2"]))}
    raise CasError(f"Mesure de figure inconnue : {m!r}")
