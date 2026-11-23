"""Moteur de calcul formel du module calc_cas (SymPy).

Analyse sûre : le texte saisi passe par les transformations de SymPy (multiplication implicite, `^`, `=`), puis
le code Python obtenu est **vérifié par son arbre syntaxique** avant toute évaluation : aucun accès d'attribut,
aucun nom commençant par « _ », aucune fonction anonyme ni compréhension, appels limités à des noms. L'évaluation
se fait sans `__builtins__`, avec une liste fermée de noms (`GLOBALS`) et les définitions de la session.

Ce module ne gère pas le délai maximal : il tourne dans le processus de calcul de `worker.py`, que le module du Hub
tue et relance quand un calcul dépasse son délai.
"""
from __future__ import annotations

import ast
import html.entities
import math
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    eval_expr,
    implicit_application,
    implicit_multiplication,
    standard_transformations,
    stringify_expr,
)

MAX_INPUT = 2000
DIGITS = 12
TRANSFORMS = standard_transformations + (implicit_multiplication, implicit_application, convert_xor)
NAME_RE = re.compile(r"^[^\W\d_]\w{0,30}$")
DEF_RE = re.compile(r"^\s*([^\W\d_]\w{0,30})\s*(?:\(([^()]*)\))?\s*:=\s*(.+)$", re.S)


class CasError(ValueError):
    """Erreur lisible destinée à l'utilisateur (saisie invalide, calcul impossible)."""


# ---------------------------------------------------------------- outils internes
def _sym(value: Any) -> Any:
    """Listes Python -> objets SymPy (listes de listes -> matrice si rectangulaire)."""
    if isinstance(value, sp.MatrixBase):
        return value
    if isinstance(value, list | tuple):
        return [_sym(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float | str):
        return sp.sympify(value)
    return value


def _matrix(value: Any) -> sp.Matrix:
    if isinstance(value, sp.MatrixBase):
        return sp.Matrix(value)
    if isinstance(value, list | tuple) and value:
        rows = [list(r) if isinstance(r, list | tuple) else [r] for r in value]
        if len({len(r) for r in rows}) != 1:
            raise CasError("Matrice invalide : toutes les lignes doivent avoir la même longueur")
        return sp.Matrix(rows)
    raise CasError("Une matrice est attendue, par exemple [[1, 2], [3, 4]]")


def _free_var(expr: Any, var: Any = None) -> sp.Symbol:
    if var is not None:
        if not isinstance(var, sp.Symbol):
            raise CasError(f"La variable doit être un nom, pas {var}")
        return var
    symbols = sorted(getattr(sp.sympify(expr), "free_symbols", set()), key=str)
    if len(symbols) == 1:
        return symbols[0]
    if not symbols:
        return sp.Symbol("x")
    names = {str(s): s for s in symbols}
    if "x" in names:
        return names["x"]
    raise CasError("Plusieurs variables possibles (" + ", ".join(names) + ") : précise la variable")


def _values(data: Any) -> list[Any]:
    if isinstance(data, sp.MatrixBase):
        return list(data)
    if not isinstance(data, list | tuple) or not data:
        raise CasError("Une liste non vide est attendue, par exemple [1, 2, 3]")
    return [sp.sympify(v) for v in data]


# ---------------------------------------------------------------- fonctions proposées à la saisie
def cas_diff(f: Any, x: Any = None, n: Any = 1) -> Any:
    x = _free_var(f, x)
    return sp.diff(f, x, int(n))


def cas_integrate(f: Any, x: Any = None, a: Any = None, b: Any = None) -> Any:
    if isinstance(x, tuple | list) and len(x) == 3:  # integrate(f, (x, a, b))
        x, a, b = x
    x = _free_var(f, x)
    if (a is None) != (b is None):
        raise CasError("Intégrale définie : donne les deux bornes, integrate(f, x, a, b)")
    return sp.integrate(f, (x, a, b)) if a is not None else sp.integrate(f, x)


def cas_limit(f: Any, x: Any = None, a: Any = 0, direction: str = "+-") -> Any:
    x = _free_var(f, x)
    direction = {"gauche": "-", "droite": "+", "left": "-", "right": "+"}.get(str(direction), str(direction))
    if direction not in ("+", "-", "+-"):
        raise CasError("Sens de la limite : \"+\" (droite), \"-\" (gauche) ou \"+-\" (deux côtés)")
    if direction == "+-" and a in (sp.oo, -sp.oo):
        direction = "-" if a == sp.oo else "+"
    try:
        result = sp.limit(f, x, a, direction)
    except ValueError as exc:
        if "does not exist" in str(exc):
            raise CasError("La limite n'existe pas (limites à gauche et à droite différentes)") from None
        raise
    if result == sp.zoo:
        raise CasError("La limite n'existe pas : infinie, de signe différent à gauche et à droite")
    return result


def cas_solve(eq: Any, *variables: Any) -> list[Any]:
    """Équation ou système. Retourne une liste de solutions, chacune sous forme d'égalités `x = valeur`."""
    eqs = list(eq) if isinstance(eq, list | tuple) else [eq]
    if len(variables) == 1 and isinstance(variables[0], list | tuple):
        variables = tuple(variables[0])
    if not variables:
        symbols: set[Any] = set()
        for e in eqs:
            symbols |= getattr(e, "free_symbols", set())
        variables = tuple(sorted(symbols, key=str))
    if not variables:
        raise CasError("Aucune inconnue dans l'équation")
    solutions = sp.solve(eqs if len(eqs) > 1 else eqs[0], list(variables), dict=True)
    out = []
    for sol in solutions:
        eqs_out = [sp.Eq(v, sol[v]) for v in variables if v in sol]
        out.append(eqs_out[0] if len(eqs_out) == 1 else eqs_out)
    return out


def cas_nsolve(eq: Any, x: Any = None, x0: Any = 0) -> Any:
    x = _free_var(eq, x)
    expr = eq.lhs - eq.rhs if isinstance(eq, sp.Eq) else eq
    try:
        return sp.Eq(x, sp.nsolve(expr, x, x0))
    except (ValueError, ZeroDivisionError) as exc:
        raise CasError(f"Résolution numérique impossible depuis {x0} : essaie un autre point de départ "
                       f"({exc})") from None


def cas_sum(f: Any, k: Any = None, a: Any = None, b: Any = None) -> Any:
    if isinstance(k, tuple | list) and len(k) == 3:
        k, a, b = k
    if isinstance(f, list | tuple | sp.MatrixBase) and k is None:  # somme des termes d'une liste
        return sp.Add(*_values(f))
    k = _free_var(f, k)
    if a is None or b is None:
        raise CasError("Somme : sum(terme, k, début, fin)")
    return sp.summation(f, (k, a, b))


def cas_product(f: Any, k: Any = None, a: Any = None, b: Any = None) -> Any:
    if isinstance(k, tuple | list) and len(k) == 3:
        k, a, b = k
    if isinstance(f, list | tuple | sp.MatrixBase) and k is None:
        return sp.Mul(*_values(f))
    k = _free_var(f, k)
    if a is None or b is None:
        raise CasError("Produit : product(terme, k, début, fin)")
    return sp.product(f, (k, a, b))


def cas_taylor(f: Any, x: Any = None, a: Any = 0, n: Any = 6) -> Any:
    x = _free_var(f, x)
    return sp.series(f, x, a, int(n)).removeO()


def cas_det(m: Any) -> Any:
    m = _matrix(m)
    if not m.is_square:
        raise CasError("Le déterminant n'existe que pour une matrice carrée")
    return m.det()


def cas_inv(m: Any) -> Any:
    if not isinstance(m, list | tuple | sp.MatrixBase):
        return 1 / sp.sympify(m)
    m = _matrix(m)
    if not m.is_square:
        raise CasError("Seule une matrice carrée peut être inversible")
    if m.det() == 0:
        raise CasError("Matrice non inversible (déterminant nul)")
    return m.inv()


def cas_eigenvals(m: Any) -> dict[Any, Any]:
    m = _matrix(m)
    if not m.is_square:
        raise CasError("Valeurs propres : matrice carrée attendue")
    return dict(sorted(m.eigenvals().items(), key=lambda kv: sp.default_sort_key(kv[0])))


def cas_eigenvects(m: Any) -> list[Any]:
    m = _matrix(m)
    if not m.is_square:
        raise CasError("Vecteurs propres : matrice carrée attendue")
    return [[val, mult, [list(v) for v in vecs]] for val, mult, vecs in m.eigenvects()]


def cas_mean(data: Any) -> Any:
    vals = _values(data)
    return sp.Add(*vals) / len(vals)


def cas_median(data: Any) -> Any:
    vals = sorted(_values(data), key=lambda v: float(v))
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def cas_variance(data: Any) -> Any:  # variance de la population (diviseur n)
    vals = _values(data)
    m = sp.Add(*vals) / len(vals)
    return sp.simplify(sp.Add(*[(v - m) ** 2 for v in vals]) / len(vals))


def cas_stdev(data: Any) -> Any:  # écart type de l'échantillon (diviseur n - 1)
    vals = _values(data)
    if len(vals) < 2:
        raise CasError("Écart type : au moins deux valeurs")
    m = sp.Add(*vals) / len(vals)
    return sp.sqrt(sp.simplify(sp.Add(*[(v - m) ** 2 for v in vals]) / (len(vals) - 1)))


def cas_polar(z: Any) -> list[Any]:
    z = sp.sympify(z)
    return [sp.simplify(sp.Abs(z)), sp.simplify(sp.arg(z))]


def cas_approx(expr: Any, digits: Any = 15) -> Any:
    return _evalf(expr, int(digits))


def cas_rref(m: Any) -> Any:
    return _matrix(m).rref()[0]


FUNCTIONS: dict[str, Callable[..., Any]] = {
    # algèbre
    "simplify": sp.simplify, "expand": sp.expand, "factor": sp.factor, "cancel": sp.cancel, "apart": sp.apart,
    "together": sp.together, "trigsimp": sp.trigsimp, "expand_trig": sp.expand_trig, "collect": sp.collect,
    "numer": sp.numer, "denom": sp.denom, "subs": lambda e, a, b: sp.sympify(e).subs(a, b),
    # analyse
    "diff": cas_diff, "integrate": cas_integrate, "limit": cas_limit, "taylor": cas_taylor, "series": cas_taylor,
    "sum": cas_sum, "product": cas_product,
    # équations
    "solve": cas_solve, "nsolve": cas_nsolve,
    # matrices
    "Matrix": lambda rows: _matrix(rows), "matrix": lambda rows: _matrix(rows), "det": cas_det, "inv": cas_inv,
    "transpose": lambda m: _matrix(m).T, "eigenvals": cas_eigenvals, "eigenvects": cas_eigenvects,
    "rank": lambda m: _matrix(m).rank(), "rref": cas_rref, "trace": lambda m: _matrix(m).trace(),
    "eye": lambda n: sp.eye(int(n)), "identity": lambda n: sp.eye(int(n)),
    "zeros": lambda r, c=None: sp.zeros(int(r), int(c or r)), "ones": lambda r, c=None: sp.ones(int(r), int(c or r)),
    "dot": lambda a, b: _matrix(a).dot(_matrix(b)), "cross": lambda a, b: _matrix(a).cross(_matrix(b)),
    # complexes
    "re": sp.re, "im": sp.im, "arg": sp.arg, "conj": sp.conjugate, "conjugate": sp.conjugate,
    "polar": cas_polar, "expand_complex": sp.expand_complex,
    # arithmétique
    "gcd": sp.gcd, "lcm": sp.lcm, "isprime": lambda n: bool(sp.isprime(int(n))), "factorint": sp.factorint,
    "divisors": sp.divisors, "mod": sp.Mod, "Mod": sp.Mod, "factorial": sp.factorial, "binomial": sp.binomial,
    "nCr": sp.binomial, "floor": sp.floor, "ceiling": sp.ceiling, "ceil": sp.ceiling, "round": lambda v, d=0:
    sp.Float(round(float(v), int(d))) if int(d) else sp.Integer(round(float(v))),
    "N": cas_approx, "approx": cas_approx, "evalf": cas_approx,
    # statistiques sur listes (exactes)
    "mean": cas_mean, "median": cas_median, "variance": cas_variance, "stdev": cas_stdev,
    "min": sp.Min, "max": sp.Max, "length": lambda d: len(_values(d)),
    # fonctions usuelles
    "sqrt": sp.sqrt, "root": sp.root, "cbrt": sp.cbrt, "exp": sp.exp, "log": sp.log, "ln": sp.log,
    "log10": lambda v: sp.log(v, 10), "abs": sp.Abs, "Abs": sp.Abs, "sign": sp.sign,
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "cot": sp.cot, "sec": sp.sec, "csc": sp.csc,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "atan2": sp.atan2, "arcsin": sp.asin, "arccos": sp.acos,
    "arctan": sp.atan, "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh, "asinh": sp.asinh, "acosh": sp.acosh,
    "atanh": sp.atanh, "gamma": sp.gamma, "Eq": sp.Eq, "Piecewise": sp.Piecewise,
}

# Alias français (avec et sans accents).
ALIASES = {
    "simplifier": "simplify", "developper": "expand", "développer": "expand", "factoriser": "factor",
    "deriver": "diff", "dériver": "diff", "derivee": "diff", "dérivée": "diff", "integrer": "integrate",
    "intégrer": "integrate", "integrale": "integrate", "intégrale": "integrate", "limite": "limit",
    "resoudre": "solve", "résoudre": "solve", "somme": "sum", "produit": "product", "determinant": "det",
    "déterminant": "det", "inverse": "inv", "valeurs_propres": "eigenvals", "vecteurs_propres": "eigenvects",
    "transposee": "transpose", "transposée": "transpose", "pgcd": "gcd", "ppcm": "lcm", "premier": "isprime",
    "moyenne": "mean", "mediane": "median", "médiane": "median", "ecart_type": "stdev", "écart_type": "stdev",
    "approche": "approx", "approché": "approx", "conjugue": "conj", "conjugué": "conj",
}

CONSTANTS: dict[str, Any] = {"pi": sp.pi, "π": sp.pi, "e": sp.E, "E": sp.E, "i": sp.I, "I": sp.I, "oo": sp.oo,
                             "inf": sp.oo, "infini": sp.oo, "true": True, "false": False}

# Noms nécessaires au code produit par l'analyseur de SymPy (nombres, symboles inconnus, factorielle).
PARSER_NAMES: dict[str, Any] = {"Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
                                "Symbol": sp.Symbol, "Function": sp.Function}

GLOBALS: dict[str, Any] = {**PARSER_NAMES, **FUNCTIONS, **{k: FUNCTIONS[v] for k, v in ALIASES.items()},
                           **CONSTANTS}
RESERVED = frozenset(GLOBALS)

_FORBIDDEN_NODES = (ast.Attribute, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
                    ast.NamedExpr, ast.Await, ast.Yield, ast.YieldFrom, ast.JoinedStr, ast.Starred)


class _NestedListsToMatrix(ast.NodeTransformer):
    """`[[1, 2], [3, 4]]` -> `Matrix([[1, 2], [3, 4]])` : une liste de listes est une matrice."""

    def visit_List(self, node: ast.List) -> ast.AST:
        self.generic_visit(node)
        if node.elts and all(isinstance(e, ast.List) for e in node.elts):
            return ast.Call(func=ast.Name("Matrix", ast.Load()), args=[node], keywords=[])
        return node


def check_code(code: str) -> str:
    """Refuse tout code Python qui sortirait du calcul : attributs, noms « _… », appels non nommés…

    Retourne le code à évaluer (listes de listes changées en matrices)."""
    try:
        tree = ast.parse(code, mode="eval")
    except SyntaxError:
        raise CasError("Expression invalide") from None
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            raise CasError("Expression refusée : construction non autorisée")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise CasError("Expression refusée : les noms commençant par « _ » sont interdits")
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise CasError("Expression refusée : appel non autorisé")
        if isinstance(node, ast.Constant) and isinstance(node.value, bytes):
            raise CasError("Expression refusée")
    tree = ast.fix_missing_locations(_NestedListsToMatrix().visit(tree))
    return ast.unparse(tree)


def _single_equal(text: str) -> int:
    for k, c in enumerate(text):
        if c == "=" and (k == 0 or text[k - 1] not in "=<>!:") and (k + 1 >= len(text) or text[k + 1] != "="):
            return k
    return -1


def wrap_equations(text: str) -> str:
    """`x^2 = 2` -> `Eq(x^2, 2)`, y compris dans les arguments : `solve(x+y=3, x)` -> `solve(Eq(x+y, 3), x)`."""
    for _ in range(64):
        idx = _single_equal(text)
        if idx < 0:
            return text
        depth, i = 0, idx - 1
        while i >= 0:
            c = text[i]
            if c in ")]":
                depth += 1
            elif c in "([":
                if depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 0:
                break
            i -= 1
        depth, j = 0, idx + 1
        while j < len(text):
            c = text[j]
            if c in "([":
                depth += 1
            elif c in ")]":
                if depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 0:
                break
            j += 1
        left, right = text[i + 1:idx].strip(), text[idx + 1:j].strip()
        if not left or not right:
            raise CasError("Équation incomplète : il faut une expression de chaque côté de « = »")
        text = f"{text[:i + 1]}Eq({left}, {right}){text[j:]}"
    raise CasError("Trop d'équations dans la saisie")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    for a, b in (("×", "*"), ("·", "*"), ("÷", "/"), ("−", "-"), ("²", "^2"), ("³", "^3"),
                 ("≤", "<="), ("≥", ">="), ("∞", "oo"), ("θ", "theta")):
        text = text.replace(a, b)
    text = re.sub(r"√\s*(\d+(?:\.\d+)?|[^\W\d]\w*)(?!\s*\()", lambda m: f"sqrt({m.group(1)})", text)  # √2, √x
    return text.replace("√", "sqrt").strip()


_DEG = sp.pi / 180
DEGREE_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "sin": lambda v: sp.sin(v * _DEG), "cos": lambda v: sp.cos(v * _DEG), "tan": lambda v: sp.tan(v * _DEG),
    "cot": lambda v: sp.cot(v * _DEG), "sec": lambda v: sp.sec(v * _DEG), "csc": lambda v: sp.csc(v * _DEG),
    "asin": lambda v: sp.asin(v) / _DEG, "acos": lambda v: sp.acos(v) / _DEG, "atan": lambda v: sp.atan(v) / _DEG,
    "atan2": lambda y, x: sp.atan2(y, x) / _DEG, "arg": lambda z: sp.arg(z) / _DEG,
}
DEGREE_FUNCTIONS.update(arcsin=DEGREE_FUNCTIONS["asin"], arccos=DEGREE_FUNCTIONS["acos"],
                        arctan=DEGREE_FUNCTIONS["atan"])
SETTINGS = {"angle": ("rad", "deg")}
STO_RE = re.compile(r"^(.+?)\s*(?:→|->)\s*([^\W\d_]\w{0,30})\s*$", re.S)


# ---------------------------------------------------------------- session
@dataclass
class Session:
    """Variables et fonctions définies par l'utilisateur (`a := 3`, `f(x) := x^2`) et dernier résultat (`ans`)."""

    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # nom -> texte de la définition (rejouable)
    settings: dict[str, Any] = field(default_factory=lambda: {"angle": "rad"})

    def locals(self, exclude: Iterable[str] = ()) -> dict[str, Any]:
        skip = set(exclude)
        return {k: v for k, v in self.values.items() if k not in skip}

    def delete(self, name: str) -> bool:
        self.sources.pop(name, None)
        return self.values.pop(name, None) is not None

    def listing(self) -> list[dict[str, str]]:
        return [{"name": name, "source": src, "value": sp.sstr(self.values.get(name))}
                for name, src in self.sources.items()]


def parse(text: str, session: Session | None = None, extra: dict[str, Any] | None = None,
          exclude: Iterable[str] = ()) -> Any:
    """Texte -> objet SymPy évalué (aucune simplification forcée)."""
    text = normalize(text)
    if not text:
        raise CasError("Saisie vide")
    if len(text) > MAX_INPUT:
        raise CasError(f"Saisie trop longue ({len(text)} caractères, {MAX_INPUT} au plus)")
    if "__" in text or ":=" in text:
        raise CasError("Expression invalide" if ":=" in text else "Expression refusée")
    text = wrap_equations(text)
    degrees = bool(session and session.settings.get("angle") == "deg")
    local_dict = {**(DEGREE_FUNCTIONS if degrees else {}), **(session.locals(exclude) if session else {}),
                  **(extra or {})}
    global_dict = {"__builtins__": {}, **GLOBALS}
    try:
        code = stringify_expr(text, local_dict, global_dict, TRANSFORMS)
    except (SyntaxError, TypeError, ValueError, IndexError) as exc:
        raise CasError(f"Expression invalide : {exc}") from None
    except Exception as exc:  # noqa: BLE001 — TokenError et autres erreurs de lecture
        raise CasError(f"Expression invalide ({type(exc).__name__})") from None
    code = check_code(code)
    try:
        return _sym(eval_expr(code, local_dict, global_dict))
    except CasError:
        raise
    except ZeroDivisionError:
        raise CasError("Division par zéro") from None
    except SyntaxError:
        raise CasError("Expression invalide") from None
    except (TypeError, ValueError, AttributeError, NotImplementedError, sp.SympifyError) as exc:
        raise CasError(_explain(exc)) from None
    except RecursionError:
        raise CasError("Expression trop imbriquée") from None


def _explain(exc: Exception) -> str:
    msg = str(exc)
    if "is not callable" in msg:
        return "Expression invalide : multiplication implicite ambiguë ou fonction inconnue (" + msg + ")"
    if "takes" in msg and "argument" in msg or "missing" in msg and "argument" in msg:
        return "Mauvais nombre d'arguments : " + msg
    if "Matrix size mismatch" in msg or "shape" in msg.lower() or "dimension" in msg.lower():
        return "Dimensions de matrices incompatibles"
    return f"Calcul impossible : {msg}" if msg else f"Calcul impossible ({type(exc).__name__})"


# ---------------------------------------------------------------- présentation
def _evalf(obj: Any, digits: int = DIGITS) -> Any:
    if isinstance(obj, list | tuple):
        return [_evalf(o, digits) for o in obj]
    if isinstance(obj, dict):
        return {_evalf(k, digits): _evalf(v, digits) for k, v in obj.items()}
    if isinstance(obj, bool | int | str):
        return obj
    if hasattr(obj, "evalf"):
        try:
            return obj.evalf(digits)
        except (TypeError, ValueError, AttributeError):
            return obj
    return obj


def _contains_undefined(obj: Any) -> bool:
    if isinstance(obj, list | tuple):
        return any(_contains_undefined(o) for o in obj)
    if isinstance(obj, dict):
        return any(_contains_undefined(k) or _contains_undefined(v) for k, v in obj.items())
    return isinstance(obj, sp.Basic) and (obj.has(sp.zoo) or obj.has(sp.nan))


def text_of(obj: Any) -> str:
    if isinstance(obj, bool):
        return "vrai" if obj else "faux"
    if isinstance(obj, list | tuple):
        return "[" + ", ".join(text_of(o) for o in obj) + "]"
    if isinstance(obj, dict):
        return "{" + ", ".join(f"{text_of(k)}: {text_of(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, sp.Eq):
        return f"{sp.sstr(obj.lhs)} = {sp.sstr(obj.rhs)}"
    return sp.sstr(obj)


def latex_of(obj: Any) -> str:
    if isinstance(obj, bool):
        return r"\text{" + ("vrai" if obj else "faux") + "}"
    if isinstance(obj, list | tuple):
        return r"\left[" + ", ".join(latex_of(o) for o in obj) + r"\right]"
    if isinstance(obj, dict):
        return r"\left\{" + ", ".join(f"{latex_of(k)} : {latex_of(v)}" for k, v in obj.items()) + r"\right\}"
    try:
        return sp.latex(obj)
    except Exception:  # noqa: BLE001 — affichage seulement
        return r"\text{" + text_of(obj) + "}"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_ENTITY = re.compile(r"&([A-Za-z]+);")
_XML_ENTITIES = frozenset({"lt", "gt", "amp", "quot", "apos"})


def _entities(text: str) -> str:
    """Entités nommées (&pi;, &InvisibleTimes;) -> caractères : le MathML reste du XML valide."""
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in _XML_ENTITIES:
            return m.group(0)
        return html.entities.html5.get(name + ";", m.group(0))
    return _ENTITY.sub(sub, text)


def mathml_of(obj: Any) -> str:
    """MathML de présentation (affiché nativement par les navigateurs, sans bibliothèque externe)."""
    return _entities(_mathml(obj))


def _mathml(obj: Any) -> str:
    if isinstance(obj, bool):
        return f"<mtext>{'vrai' if obj else 'faux'}</mtext>"
    if isinstance(obj, list | tuple):
        sep = "<mo>,</mo>"
        return f"<mrow><mo>[</mo>{sep.join(_mathml(o) for o in obj)}<mo>]</mo></mrow>"
    if isinstance(obj, dict):
        sep = "<mo>,</mo>"
        items = sep.join(f"{_mathml(k)}<mo>:</mo>{_mathml(v)}" for k, v in obj.items())
        return f"<mrow><mo>{{</mo>{items}<mo>}}</mo></mrow>"
    try:
        return sp.mathml(obj, printer="presentation")
    except Exception:  # noqa: BLE001 — affichage seulement
        return f"<mtext>{_esc(text_of(obj))}</mtext>"


_TRAILING = re.compile(r"(\d)\.(\d*?)0+(?!\d)")


def trim_zeros(text: str) -> str:
    """« 0.500000000000 » -> « 0.5 », « 4.00000 » -> « 4 » (texte, LaTeX et MathML)."""
    return _TRAILING.sub(lambda m: m.group(1) + ("." + m.group(2) if m.group(2) else ""), text)


def _wants_approx(obj: Any) -> bool:
    """Approché utile : valeur numérique (sans variable libre) qui n'est pas déjà un entier ou un décimal."""
    if isinstance(obj, list | tuple):
        return any(_wants_approx(o) for o in obj)
    if isinstance(obj, dict):
        return any(_wants_approx(k) or _wants_approx(v) for k, v in obj.items())
    if isinstance(obj, sp.MatrixBase):
        return any(_wants_approx(o) for o in obj)
    if isinstance(obj, sp.Eq):
        return _wants_approx(obj.rhs)
    if not isinstance(obj, sp.Basic) or isinstance(obj, sp.Integer | sp.Float):
        return False
    return not obj.free_symbols and not isinstance(obj, sp.logic.boolalg.Boolean)


def present(obj: Any) -> dict[str, Any]:
    """Résultat exact + approché, en texte, LaTeX et MathML. L'approché est omis s'il n'apporte rien."""
    out: dict[str, Any] = {"exact": text_of(obj), "latex": latex_of(obj), "mathml": mathml_of(obj),
                           "approx": None, "approx_latex": None, "approx_mathml": None}
    if not _wants_approx(obj):
        return out
    approx = _evalf(obj)
    approx_text = trim_zeros(text_of(approx))
    if approx_text != out["exact"]:
        out.update(approx=approx_text, approx_latex=trim_zeros(latex_of(approx)),
                   approx_mathml=trim_zeros(mathml_of(approx)))
    return out


def _kind(obj: Any) -> str:
    if isinstance(obj, bool):
        return "booléen"
    if isinstance(obj, sp.MatrixBase):
        return "matrice"
    if isinstance(obj, list | tuple):
        return "liste"
    if isinstance(obj, dict):
        return "dictionnaire"
    if isinstance(obj, sp.Eq | sp.Rel):
        return "relation"
    if isinstance(obj, sp.Lambda):
        return "fonction"
    return "expression"


# ---------------------------------------------------------------- point d'entrée
def define(text: str, session: Session) -> dict[str, Any]:
    match = DEF_RE.match(normalize(text))
    if not match:
        raise CasError("Définition invalide : écris « a := 3 » ou « f(x) := x^2 + 1 »")
    name, params_text, body = match.group(1), match.group(2), match.group(3)
    if name in RESERVED or name.startswith("_"):
        raise CasError(f"« {name} » est un nom réservé")
    if name == "ans":
        raise CasError("« ans » est réservé au dernier résultat")
    if params_text is None:
        value = parse(body, session)
        if isinstance(value, sp.Lambda):
            raise CasError("Pour une fonction, écris « f(x) := … »")
    else:
        params = [p.strip() for p in params_text.split(",") if p.strip()]
        if not params or not all(NAME_RE.match(p) and p not in RESERVED for p in params):
            raise CasError("Paramètres invalides : f(x) := … ou g(x, y) := …")
        if len(set(params)) != len(params):
            raise CasError("Paramètre répété dans la définition")
        symbols = [sp.Symbol(p) for p in params]
        expr = parse(body, session, extra={p: s for p, s in zip(params, symbols, strict=True)}, exclude=params)
        if isinstance(expr, list | tuple | dict | bool):
            raise CasError("Une fonction doit renvoyer une expression")
        value = sp.Lambda(tuple(symbols), expr)
    if _contains_undefined(value):
        raise CasError("Division par zéro ou forme indéterminée : définition refusée")
    session.delete(name)  # une redéfinition passe en dernier (ordre de rejeu)
    session.values[name] = value
    session.sources[name] = normalize(text)
    shown = value.expr if isinstance(value, sp.Lambda) else value
    label = f"{name}({params_text.strip()})" if params_text is not None else name
    return {"ok": True, "input": text, "kind": "définition", "definition": {"name": name, "source": normalize(text)},
            "label": label, **present(shown)}


def evaluate(text: str, session: Session | None = None) -> dict[str, Any]:
    """Évalue une saisie. Ne lève jamais : retourne `{"ok": False, "error": …}` en cas de problème."""
    session = session if session is not None else Session()
    try:
        if not isinstance(text, str):
            raise CasError("La saisie doit être du texte")
        sto = STO_RE.match(normalize(text))
        if sto and not DEF_RE.match(normalize(text)):  # « expr → nom » (touche sto→) = « nom := expr »
            result = define(f"{sto.group(2)} := {sto.group(1)}", session)
            result["input"] = text
            return result
        if DEF_RE.match(normalize(text)):
            return define(text, session)
        result = parse(text, session)
        if isinstance(result, sp.Lambda):
            raise CasError("Fonction sans argument : écris par exemple f(2) ou f(x)")
        if isinstance(result, sp.Basic) and result.has(sp.Integral) and not isinstance(result, sp.MatrixBase):
            warning = "Primitive non exprimable avec les fonctions usuelles : intégrale laissée telle quelle"
        else:
            warning = None
        if isinstance(result, sp.Expr) and result.is_number and result.has(sp.I):
            result = sp.expand_complex(result)  # (1+2i)(3-i) -> 5 + 5i
        if _contains_undefined(result):
            raise CasError("Division par zéro ou forme indéterminée : résultat non défini")
        session.values["ans"] = result
        out = {"ok": True, "input": text, "kind": _kind(result), **present(result)}
        if warning:
            out["warning"] = warning
        return out
    except CasError as exc:
        return {"ok": False, "input": text, "error": str(exc)}
    except ZeroDivisionError:
        return {"ok": False, "input": text, "error": "Division par zéro"}
    except RecursionError:
        return {"ok": False, "input": text, "error": "Expression trop imbriquée"}
    except Exception as exc:  # noqa: BLE001 — jamais de plantage : l'erreur devient un message lisible
        return {"ok": False, "input": text, "error": _explain(exc)}


def to_float(value: Any, session: Session | None = None) -> float:
    """Valeur d'une cellule (nombre ou texte « 1/3 », « sqrt(2) ») -> flottant."""
    if isinstance(value, bool):
        raise CasError("Valeur numérique attendue")
    if isinstance(value, int | float):
        return float(value)
    obj = parse(str(value), session)
    try:
        number = complex(sp.N(obj))
    except (TypeError, ValueError):
        raise CasError(f"« {value} » n'est pas un nombre") from None
    if not (math.isfinite(number.real) and math.isfinite(number.imag)):
        raise CasError(f"« {value} » n'est pas un nombre fini (division par zéro ?)")
    if abs(number.imag) > 1e-12:
        raise CasError(f"« {value} » n'est pas un nombre réel")
    return number.real
