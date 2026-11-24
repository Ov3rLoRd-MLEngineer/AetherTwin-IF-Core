"""Moteur de formules du tableur : analyse, évaluation paresseuse, dépendances et cycles. Aucun `eval` Python.

Une cellule contient une valeur (« 12 », « 3,5 », « bonjour ») ou une formule qui commence par « = ».
Dans une formule : nombres avec un point décimal, arguments séparés par « ; » (ou « , »), références `A1`, `$B$2`,
plages `A1:C10`, chaînes "entre guillemets", opérateurs `+ - * / ^ & = <> < > <= >=` et `%` final.
Les fonctions ont leur nom français et anglais (SOMME = SUM, MOYENNE = AVERAGE, SI = IF…), voir `FUNCTIONS`.

Fonctions d'équations : `RESOUDRE("x^2-2"; 1)` (racine près de 1), `DERIVEE("x^3"; 2)`, `INTEGRALE("sin(x)"; 0; PI())`
— la variable s'appelle `x`, l'expression peut aussi lire les cellules de la feuille.

Les erreurs sont des valeurs (`#DIV/0!`, `#VALEUR!`, `#REF!`, `#NOM?`, `#CYCLE!`, `#NUM!`) qui se propagent.
"""
from __future__ import annotations

import math
import random
import re
import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

MAX_COLS = 52        # A … AZ
MAX_ROWS = 2000
REF = re.compile(r"\$?([A-Z]{1,2})\$?(\d{1,4})")


class SheetError(ValueError):
    pass


@dataclass(frozen=True)
class Err:
    code: str

    def __str__(self) -> str:
        return self.code


DIV0, VALUE, REFE, NAME, CYCLE, NUM, NA = (Err(c) for c in ("#DIV/0!", "#VALEUR!", "#REF!", "#NOM?", "#CYCLE!",
                                                            "#NUM!", "#N/A"))


class Raise(Exception):
    """Arrête une évaluation avec une erreur de tableur."""

    def __init__(self, err: Err) -> None:
        super().__init__(err.code)
        self.err = err


# ---------- références ----------
def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def col_name(index: int) -> str:
    s = ""
    index += 1
    while index:
        index, r = divmod(index - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_ref(text: str) -> tuple[int, int]:
    m = REF.fullmatch(text.strip().upper())
    if not m:
        raise SheetError(f"référence invalide : {text!r}")
    c, r = col_index(m.group(1)), int(m.group(2)) - 1
    if not (0 <= c < MAX_COLS and 0 <= r < MAX_ROWS):
        raise SheetError(f"référence hors de la feuille : {text!r}")
    return c, r


def ref_name(c: int, r: int) -> str:
    return f"{col_name(c)}{r + 1}"


def range_cells(text: str) -> list[str]:
    """« A1:B3 » → [A1, B1, A2, B2, A3, B3] (ligne par ligne)."""
    if ":" not in text:
        c, r = parse_ref(text)
        return [ref_name(c, r)]
    a, b = text.split(":", 1)
    (c1, r1), (c2, r2) = parse_ref(a), parse_ref(b)
    return [ref_name(c, r) for r in range(min(r1, r2), max(r1, r2) + 1) for c in range(min(c1, c2), max(c1, c2) + 1)]


def parse_value(text: Any) -> Any:
    """Contenu non formule : nombre (virgule ou point décimal, espaces de milliers, %), booléen ou texte."""
    if text is None:
        return None
    if isinstance(text, bool | int | float):
        return text
    s = str(text).strip()
    if s == "":
        return None
    up = s.upper()
    if up in ("VRAI", "TRUE"):
        return True
    if up in ("FAUX", "FALSE"):
        return False
    t = s.replace(" ", "").replace("\xa0", "").replace(" ", "")
    pct = t.endswith("%")
    if pct:
        t = t[:-1]
    if re.fullmatch(r"[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?", t):
        v = float(t.replace(",", "."))
        return v / 100 if pct else v
    return s


# ---------- analyse ----------
TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)
  | (?P<str>"([^"]|"")*")
  | (?P<range>\$?[A-Za-z]{1,2}\$?\d{1,4}:\$?[A-Za-z]{1,2}\$?\d{1,4})
  | (?P<ref>\$?[A-Za-z]{1,2}\$?\d{1,4}(?![A-Za-z0-9_.(]))
  | (?P<name>[A-Za-z_][A-Za-z0-9_.]*)
  | (?P<op><>|<=|>=|[-+*/^&=<>%(),;:])
""", re.X)


def tokenize(text: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise SheetError(f"caractère inattendu « {text[pos]} »")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        out.append((kind, m.group()))
    out.append(("end", ""))
    return out


class Parser:
    """Descente récursive : comparaison < concaténation < addition < multiplication < puissance < unaire."""

    def __init__(self, text: str) -> None:
        self.toks = tokenize(text)
        self.i = 0

    def peek(self) -> tuple[str, str]:
        return self.toks[self.i]

    def take(self, value: str | None = None) -> tuple[str, str]:
        tok = self.toks[self.i]
        if value is not None and tok[1] != value:
            raise SheetError(f"« {value} » attendu, « {tok[1] or 'fin'} » trouvé")
        self.i += 1
        return tok

    def parse(self) -> tuple:
        node = self.comparison()
        if self.peek()[0] != "end":
            raise SheetError(f"« {self.peek()[1]} » inattendu")
        return node

    def comparison(self) -> tuple:
        node = self.concat()
        while self.peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.take()[1]
            node = ("cmp", op, node, self.concat())
        return node

    def concat(self) -> tuple:
        node = self.additive()
        while self.peek()[1] == "&":
            self.take()
            node = ("cat", node, self.additive())
        return node

    def additive(self) -> tuple:
        node = self.term()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self) -> tuple:
        node = self.unary()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self) -> tuple:
        if self.peek()[1] in ("-", "+"):
            op = self.take()[1]
            node = self.unary()
            return ("neg", node) if op == "-" else node
        return self.power()

    def power(self) -> tuple:
        node = self.postfix()
        if self.peek()[1] == "^":
            self.take()
            node = ("bin", "^", node, self.unary())   # à droite : 2^3^2 = 2^9
        return node

    def postfix(self) -> tuple:
        node = self.atom()
        while self.peek()[1] == "%":
            self.take()
            node = ("bin", "/", node, ("num", 100.0))
        return node

    def atom(self) -> tuple:
        kind, text = self.take()
        if kind == "num":
            return ("num", float(text))
        if kind == "str":
            return ("str", text[1:-1].replace('""', '"'))
        if kind == "range":
            a, b = text.upper().replace("$", "").split(":")
            parse_ref(a)
            parse_ref(b)
            return ("range", f"{a}:{b}")
        if kind == "ref":
            plain = text.upper().replace("$", "")
            parse_ref(plain)
            return ("ref", plain)
        if kind == "name":
            up = text.upper()
            if self.peek()[1] == "(":
                self.take()
                args = []
                if self.peek()[1] != ")":
                    args.append(self.comparison())
                    while self.peek()[1] in (";", ","):
                        self.take()
                        args.append(self.comparison())
                self.take(")")
                return ("call", up, args)
            if up in ("VRAI", "TRUE"):
                return ("bool", True)
            if up in ("FAUX", "FALSE"):
                return ("bool", False)
            if REF.fullmatch(up.replace("$", "")):
                plain = up.replace("$", "")
                parse_ref(plain)
                return ("ref", plain)
            if up == "X":
                return ("var",)
            return ("name", up)
        if text == "(":
            node = self.comparison()
            self.take(")")
            return node
        raise SheetError(f"« {text or 'fin de formule'} » inattendu")


def parse_formula(text: str) -> tuple:
    body = text[1:] if text.startswith("=") else text
    if not body.strip():
        raise SheetError("formule vide")
    return Parser(body).parse()


def references(node: tuple) -> set[str]:
    """Cellules lues par une formule (plages développées)."""
    out: set[str] = set()

    def walk(n: Any) -> None:
        if not isinstance(n, tuple) or not n:
            return
        if n[0] == "ref":
            out.add(n[1])
        elif n[0] == "range":
            out.update(range_cells(n[1]))
        for child in n[1:]:
            if isinstance(child, tuple):
                walk(child)
            elif isinstance(child, list):
                for c in child:
                    walk(c)

    walk(node)
    return out


# ---------- évaluation ----------
def to_num(v: Any) -> float:
    if isinstance(v, Err):
        raise Raise(v)
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, int | float):
        return float(v)
    p = parse_value(v)
    if isinstance(p, float):
        return p
    raise Raise(VALUE)


def to_bool(v: Any) -> bool:
    if isinstance(v, Err):
        raise Raise(v)
    if isinstance(v, str):
        up = v.upper()
        if up in ("VRAI", "TRUE"):
            return True
        if up in ("FAUX", "FALSE", ""):
            return False
        raise Raise(VALUE)
    return bool(to_num(v))


def to_text(v: Any) -> str:
    if isinstance(v, Err):
        raise Raise(v)
    if v is None:
        return ""
    if isinstance(v, bool):
        return "VRAI" if v else "FAUX"
    if isinstance(v, float):
        return display(v)
    return str(v)


def display(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, Err):
        return v.code
    if isinstance(v, bool):
        return "VRAI" if v else "FAUX"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        if abs(v) >= 1e9 or abs(v) < 1e-5:
            return f"{v:.6g}"
        return f"{v:.10g}"
    return str(v)


def flatten(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    for v in values:
        if isinstance(v, list):
            out.extend(flatten(v))
        else:
            out.append(v)
    return out


def numbers(values: Iterable[Any]) -> list[float]:
    """Nombres d'arguments ou de plages : dans une plage, textes et vides sont ignorés (comme un tableur)."""
    out = []
    for v in values:
        if isinstance(v, list):
            for x in flatten(v):
                if isinstance(x, Err):
                    raise Raise(x)
                if isinstance(x, int | float) and not isinstance(x, bool):
                    out.append(float(x))
        else:
            out.append(to_num(v))
    return out


def criterion(crit: Any) -> Callable[[Any], bool]:
    """Critère de NB.SI / SOMME.SI : « >5 », « <>0 », « =abc », « abc », 3."""
    if isinstance(crit, int | float) and not isinstance(crit, bool):
        return lambda v: isinstance(v, int | float) and float(v) == float(crit)
    text = to_text(crit)
    m = re.match(r"^(<=|>=|<>|<|>|=)?(.*)$", text)
    op, rest = m.group(1) or "=", m.group(2)
    target = parse_value(rest)
    ops = {"=": lambda a, b: a == b, "<>": lambda a, b: a != b, "<": lambda a, b: a < b, ">": lambda a, b: a > b,
           "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}

    def test(v: Any) -> bool:
        if isinstance(target, float):
            if not isinstance(v, int | float) or isinstance(v, bool):
                return op == "<>"
            return ops[op](float(v), target)
        a, b = to_text(v).lower(), str(target or "").lower()
        return ops[op](a, b) if op in ("=", "<>") else False

    return test


def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    if len(xs) != len(ys) or len(xs) < 2:
        raise Raise(NA)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    if sxx == 0:
        raise Raise(DIV0)
    slope = sxy / sxx
    r = sxy / math.sqrt(sxx * syy) if syy else 1.0
    return slope, my - slope * mx, r


def _pairs(a: Any, b: Any) -> tuple[list[float], list[float]]:
    """Deux plages de même taille → leurs nombres alignés (paires incomplètes ignorées)."""
    xa, xb = flatten(a if isinstance(a, list) else [a]), flatten(b if isinstance(b, list) else [b])
    if len(xa) != len(xb):
        raise Raise(NA)

    def num(v: Any) -> bool:
        if isinstance(v, Err):
            raise Raise(v)
        return isinstance(v, int | float) and not isinstance(v, bool)

    pairs = [(float(u), float(v)) for u, v in zip(xa, xb, strict=True) if num(u) and num(v)]
    return [u for u, _v in pairs], [v for _u, v in pairs]


def _stdev(xs: list[float], sample: bool = True) -> float:
    if len(xs) < (2 if sample else 1):
        raise Raise(DIV0)
    return statistics.stdev(xs) if sample else statistics.pstdev(xs)


def _round(x: float, n: float = 0) -> float:
    q = 10 ** int(n)
    return math.floor(abs(x) * q + 0.5) / q * (1 if x >= 0 else -1)


# nom → (fonction, mode) ; mode « v » : arguments évalués, « lazy » : nœuds bruts (SI, ET…)
FUNCTIONS: dict[str, tuple[Callable[..., Any], str]] = {}


def fn(*names: str, lazy: bool = False) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(f: Callable[..., Any]) -> Callable[..., Any]:
        for n in names:
            FUNCTIONS[n] = (f, "lazy" if lazy else "v")
        return f
    return deco


fn("SOMME", "SUM")(lambda *a: sum(numbers(a)))
fn("PRODUIT", "PRODUCT")(lambda *a: math.prod(numbers(a)))
fn("MIN")(lambda *a: min(numbers(a)) if numbers(a) else 0.0)
fn("MAX")(lambda *a: max(numbers(a)) if numbers(a) else 0.0)
fn("NB", "COUNT")(lambda *a: float(len(numbers(a))))
fn("NBVAL", "COUNTA")(lambda *a: float(sum(1 for v in flatten(list(a)) if v not in (None, ""))))
fn("NB.VIDE", "COUNTBLANK")(lambda *a: float(sum(1 for v in flatten(list(a)) if v in (None, ""))))
fn("MEDIANE", "MEDIAN")(lambda *a: statistics.median(numbers(a)) if numbers(a) else Err("#NUM!"))
fn("ECARTYPE", "ECARTYPE.STANDARD", "STDEV", "STDEV.S")(lambda *a: _stdev(numbers(a)))
fn("ECARTYPEP", "ECARTYPE.PEARSON", "STDEVP", "STDEV.P")(lambda *a: _stdev(numbers(a), False))
fn("VAR", "VAR.S")(lambda *a: _stdev(numbers(a)) ** 2)
fn("ABS")(lambda x: abs(to_num(x)))
fn("RACINE", "SQRT")(lambda x: math.sqrt(to_num(x)) if to_num(x) >= 0 else NUM)
fn("EXP")(lambda x: math.exp(to_num(x)))
fn("LN")(lambda x: math.log(to_num(x)) if to_num(x) > 0 else NUM)
fn("LOG10")(lambda x: math.log10(to_num(x)) if to_num(x) > 0 else NUM)
fn("LOG")(lambda x, b=10.0: math.log(to_num(x), to_num(b)) if to_num(x) > 0 else NUM)
fn("PUISSANCE", "POWER")(lambda x, y: to_num(x) ** to_num(y))
fn("PI")(lambda: math.pi)
fn("SIN")(lambda x: math.sin(to_num(x)))
fn("COS")(lambda x: math.cos(to_num(x)))
fn("TAN")(lambda x: math.tan(to_num(x)))
fn("ASIN")(lambda x: math.asin(to_num(x)) if abs(to_num(x)) <= 1 else NUM)
fn("ACOS")(lambda x: math.acos(to_num(x)) if abs(to_num(x)) <= 1 else NUM)
fn("ATAN")(lambda x: math.atan(to_num(x)))
fn("DEGRES", "DEGREES")(lambda x: math.degrees(to_num(x)))
fn("RADIANS")(lambda x: math.radians(to_num(x)))
fn("ARRONDI", "ROUND")(lambda x, n=0: _round(to_num(x), to_num(n)))
fn("ENT", "INT")(lambda x: float(math.floor(to_num(x))))
fn("MOD")(lambda a, b: math.fmod(to_num(a), to_num(b)) % to_num(b) if to_num(b) else DIV0)
fn("SIGNE", "SIGN")(lambda x: float((to_num(x) > 0) - (to_num(x) < 0)))
fn("NON", "NOT")(lambda x: not to_bool(x))
fn("CONCAT", "CONCATENER", "CONCATENATE")(lambda *a: "".join(to_text(v) for v in flatten(list(a))))
fn("NBCAR", "LEN")(lambda s: float(len(to_text(s))))
fn("MAJUSCULE", "UPPER")(lambda s: to_text(s).upper())
fn("MINUSCULE", "LOWER")(lambda s: to_text(s).lower())
fn("SOMMEPROD", "SUMPRODUCT")(lambda a, b: sum(x * y for x, y in zip(*_pairs(a, b), strict=True)))
fn("PENTE", "SLOPE")(lambda ys, xs: _linreg(*_pairs(xs, ys))[0])
fn("ORDONNEE.ORIGINE", "INTERCEPT")(lambda ys, xs: _linreg(*_pairs(xs, ys))[1])
fn("COEFFICIENT.CORRELATION", "CORREL")(lambda a, b: _linreg(*_pairs(a, b))[2])
fn("COEFFICIENT.DETERMINATION", "RSQ")(lambda ys, xs: _linreg(*_pairs(xs, ys))[2] ** 2)


@fn("PREVISION", "FORECAST", "PREVISION.LINEAIRE", "FORECAST.LINEAR")
def _forecast(x: Any, ys: Any, xs: Any) -> float:
    slope, inter, _r = _linreg(*_pairs(xs, ys))
    return inter + slope * to_num(x)


@fn("MOYENNE", "AVERAGE")
def _mean(*a: Any) -> Any:
    xs = numbers(a)
    return sum(xs) / len(xs) if xs else DIV0


@fn("NB.SI", "COUNTIF")
def _countif(rng: Any, crit: Any) -> float:
    test = criterion(crit)
    return float(sum(1 for v in flatten(rng if isinstance(rng, list) else [rng]) if test(v)))


@fn("SOMME.SI", "SUMIF")
def _sumif(rng: Any, crit: Any, sum_rng: Any = None) -> float:
    test = criterion(crit)
    keys = flatten(rng if isinstance(rng, list) else [rng])
    vals = flatten(sum_rng if isinstance(sum_rng, list) else [sum_rng]) if sum_rng is not None else keys
    return sum(float(v) for k, v in zip(keys, vals, strict=False)
               if test(k) and isinstance(v, int | float) and not isinstance(v, bool))


@fn("MOYENNE.SI", "AVERAGEIF")
def _averageif(rng: Any, crit: Any, avg_rng: Any = None) -> Any:
    n = _countif(rng, crit)
    return _sumif(rng, crit, avg_rng) / n if n else DIV0


class Sheet:
    """Une feuille : contenus bruts → valeurs. `rng` rend les tirages aléatoires reproductibles."""

    def __init__(self, cells: dict[str, Any], overrides: dict[str, Any] | None = None,
                 rng: random.Random | None = None) -> None:
        self.raw: dict[str, Any] = {}
        for k, v in (cells or {}).items():
            c, r = parse_ref(k)
            if v not in (None, ""):
                self.raw[ref_name(c, r)] = v
        self.overrides = {parse_ref_name(k): v for k, v in (overrides or {}).items()}
        self.rng = rng or random.Random()  # noqa: S311 — ALEA() du tableur
        self.cache: dict[str, Any] = {}
        self.visiting: set[str] = set()
        self.ast: dict[str, Any] = {}

    def formula_ast(self, ref: str) -> Any:
        if ref not in self.ast:
            try:
                self.ast[ref] = parse_formula(str(self.raw[ref]))
            except SheetError as exc:
                self.ast[ref] = exc
        return self.ast[ref]

    def value(self, ref: str) -> Any:
        if ref in self.overrides:
            return self.overrides[ref]
        if ref in self.cache:
            return self.cache[ref]
        raw = self.raw.get(ref)
        if not (isinstance(raw, str) and raw.startswith("=")):
            v = parse_value(raw)
            self.cache[ref] = v
            return v
        if ref in self.visiting:
            return CYCLE
        self.visiting.add(ref)
        try:
            node = self.formula_ast(ref)
            if isinstance(node, SheetError):
                v: Any = Err("#FORMULE!")
            else:
                v = self.eval(node, None)
                if isinstance(v, list):
                    v = v[0] if v else VALUE
                if isinstance(v, float) and not math.isfinite(v):
                    v = NUM
        except Raise as stop:
            v = stop.err
        except ZeroDivisionError:
            v = DIV0
        except (OverflowError, ValueError):
            v = NUM
        finally:
            self.visiting.discard(ref)
        self.cache[ref] = v
        return v

    def eval(self, n: tuple, x: float | None) -> Any:
        kind = n[0]
        if kind in ("num", "str", "bool"):
            return n[1]
        if kind == "ref":
            v = self.value(n[1])
            return v
        if kind == "range":
            return [self.value(r) for r in range_cells(n[1])]
        if kind == "var":
            if x is None:
                raise Raise(NAME)
            return x
        if kind == "neg":
            return -to_num(self.eval(n[1], x))
        if kind == "bin":
            a, b = to_num(self.eval(n[2], x)), to_num(self.eval(n[3], x))
            op = n[1]
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "/":
                if b == 0:
                    raise Raise(DIV0)
                return a / b
            if a == 0 and b < 0:
                raise Raise(DIV0)
            r = a ** b
            if isinstance(r, complex):
                raise Raise(NUM)
            return r
        if kind == "cat":
            return to_text(self.eval(n[1], x)) + to_text(self.eval(n[2], x))
        if kind == "cmp":
            a, b = self.eval(n[2], x), self.eval(n[3], x)
            for v in (a, b):
                if isinstance(v, Err):
                    raise Raise(v)
            if isinstance(a, int | float) and isinstance(b, int | float):
                pa, pb = float(a), float(b)
            else:
                pa, pb = to_text(a).lower(), to_text(b).lower()
            return {"=": pa == pb, "<>": pa != pb, "<": pa < pb, ">": pa > pb, "<=": pa <= pb, ">=": pa >= pb}[n[1]]
        if kind == "name":
            raise Raise(NAME)
        if kind == "call":
            return self.call(n[1], n[2], x)
        raise Raise(VALUE)

    def call(self, name: str, args: list[tuple], x: float | None) -> Any:
        if name in ("SI", "IF"):
            if len(args) < 2:
                raise Raise(VALUE)
            if to_bool(self.eval(args[0], x)):
                return self.eval(args[1], x)
            return self.eval(args[2], x) if len(args) > 2 else False
        if name in ("SIERREUR", "IFERROR"):
            try:
                v = self.eval(args[0], x)
            except Raise:
                return self.eval(args[1], x)
            return self.eval(args[1], x) if isinstance(v, Err) else v
        if name in ("ET", "AND"):
            return all(to_bool(v) for a in args for v in flatten([self.eval(a, x)]))
        if name in ("OU", "OR"):
            return any(to_bool(v) for a in args for v in flatten([self.eval(a, x)]))
        if name in ("ALEA", "RAND"):
            return self.rng.random()
        if name in ("ALEA.ENTRE.BORNES", "RANDBETWEEN"):
            a, b = (to_num(self.eval(v, x)) for v in args)
            return float(self.rng.randint(math.ceil(a), math.floor(b)))
        if name in ("LOI.NORMALE", "NORMALE", "NORMAL"):
            mu, sigma = (to_num(self.eval(v, x)) for v in args)
            return self.rng.gauss(mu, sigma)
        if name in ("UNIFORME", "UNIFORM"):
            a, b = (to_num(self.eval(v, x)) for v in args)
            return self.rng.uniform(a, b)
        if name in ("RESOUDRE", "SOLVE", "DERIVEE", "DERIVATIVE", "INTEGRALE", "INTEGRAL"):
            return self.calculus(name, args, x)
        if name not in FUNCTIONS:
            raise Raise(NAME)
        f, _mode = FUNCTIONS[name]
        values = [self.eval(a, x) for a in args]
        try:
            result = f(*values)
        except TypeError:
            raise Raise(VALUE) from None
        if isinstance(result, Err):
            raise Raise(result)
        return float(result) if isinstance(result, int) and not isinstance(result, bool) else result

    def calculus(self, name: str, args: list[tuple], x: float | None) -> float:
        """Équations : l'expression (texte) dépend de `x` et peut lire la feuille."""
        if not args:
            raise Raise(VALUE)
        text = to_text(self.eval(args[0], x))
        try:
            node = parse_formula(text)
        except SheetError:
            raise Raise(VALUE) from None
        nums = [to_num(self.eval(a, x)) for a in args[1:]]

        def f(t: float) -> float:
            return to_num(self.eval(node, t))

        if name in ("DERIVEE", "DERIVATIVE"):
            if len(nums) != 1:
                raise Raise(VALUE)
            h = 1e-5 * max(1.0, abs(nums[0]))
            return (f(nums[0] - 2 * h) - 8 * f(nums[0] - h) + 8 * f(nums[0] + h) - f(nums[0] + 2 * h)) / (12 * h)
        if name in ("INTEGRALE", "INTEGRAL"):
            if len(nums) != 2:
                raise Raise(VALUE)
            return simpson(f, nums[0], nums[1])
        guess = nums[0] if nums else 0.0
        root = find_root(f, guess)
        if root is None:
            raise Raise(NUM)
        return root

    def values(self) -> dict[str, Any]:
        return {ref: self.value(ref) for ref in self.raw}


def parse_ref_name(text: str) -> str:
    c, r = parse_ref(text)
    return ref_name(c, r)


def simpson(f: Callable[[float], float], a: float, b: float, n: int = 400) -> float:
    if a == b:
        return 0.0
    h = (b - a) / n
    s = f(a) + f(b)
    for i in range(1, n):
        s += (4 if i % 2 else 2) * f(a + i * h)
    return s * h / 3


def find_root(f: Callable[[float], float], guess: float, tol: float = 1e-12) -> float | None:
    """Racine de f près de `guess` : sécante, puis recherche d'un changement de signe et dichotomie."""
    def safe(t: float) -> float | None:
        try:
            v = f(t)
        except (Raise, ZeroDivisionError, OverflowError, ValueError):
            return None
        return v if math.isfinite(v) else None

    x0, x1 = guess, guess + max(1e-4, abs(guess) * 1e-3)
    f0, f1 = safe(x0), safe(x1)
    for _ in range(60):
        if f0 is None or f1 is None or f1 == f0:
            break
        x2 = x1 - f1 * (x1 - x0) / (f1 - f0)
        if not math.isfinite(x2):
            break
        x0, f0, x1, f1 = x1, f1, x2, safe(x2)
        if f1 is not None and (abs(f1) < tol or abs(x1 - x0) < tol * max(1.0, abs(x1))):
            return x1
    # repli : on élargit autour de la valeur de départ jusqu'à encadrer un changement de signe
    step = max(0.1, abs(guess) * 0.1)
    fg = safe(guess)
    for _ in range(60):
        for a, b in ((guess - step, guess), (guess, guess + step)):
            fa, fb = safe(a), safe(b)
            if fa is not None and fb is not None and fa * fb <= 0:
                for _ in range(200):
                    m = (a + b) / 2
                    fm = safe(m)
                    if fm is None:
                        return None
                    if fa * fm <= 0:
                        b, fb = m, fm
                    else:
                        a, fa = m, fm
                    if abs(b - a) < tol * max(1.0, abs(m)):
                        break
                return (a + b) / 2
        step *= 1.6
    return guess if fg == 0 else None
