"""Mode programmation : programmes Python exécutés dans un bac à sable.

Comme le Python d'une calculatrice : `print`, `input`, boucles, fonctions, listes, modules `math`, `cmath`,
`random`, `statistics`, plus un pont vers le moteur de calcul formel (`cas("integrate(x^2, x)")`) et des
fonctions de dessin (`plot`, `scatter`, `fplot`, `text`) affichées dans l'écran graphique.

Protections, en couches :
1. **Analyse du code** avant exécution (arbre syntaxique) : imports limités à la liste blanche, aucun nom ni
   attribut commençant par « _ », attributs d'introspection interdits (`gi_frame`, `f_globals`, `format`…),
   pas de classes, de `with`, d'`async`, de `global`.
2. **Exécution sans les fonctions natives dangereuses** : seule une liste fermée de fonctions est fournie (pas
   d'`open`, `eval`, `exec`, `getattr`, `type`, `__import__`…) ; les modules sont des copies de leurs fonctions
   publiques (impossible de remonter à `os` ou `sys`).
3. **Processus séparé** (`worker.py`), tué au-delà du délai, avec **mémoire bornée** (objet de tâche Windows,
   `RLIMIT_AS` ailleurs) ; sortie bornée.

`input()` : le programme est rejoué depuis le début avec les réponses déjà données (graine aléatoire fixée pour la
partie) ; quand il demande une nouvelle valeur, l'exécution s'arrête et l'interface pose la question.
"""
from __future__ import annotations

import ast
import builtins
import cmath
import math
import random
import statistics
import sys
import time
from types import SimpleNamespace
from typing import Any

MAX_CODE = 20_000
MAX_OUTPUT = 100_000
MAX_POINTS = 50_000
MAX_DRAWINGS = 500
MAX_DATA = 2_000_000  # données fournies au programme (texte CSV…) : `DONNEES`, `lire_csv()`

FORBIDDEN_ATTRS = frozenset({
    "gi_frame", "gi_code", "gi_yieldfrom", "gi_running", "cr_frame", "cr_code", "cr_await", "ag_frame", "ag_code",
    "f_globals", "f_locals", "f_builtins", "f_back", "f_code", "f_trace", "tb_frame", "tb_next", "co_code",
    "format", "format_map", "mro", "func_globals", "func_code", "im_func", "im_self", "load_module",
})
FORBIDDEN_NODES = (ast.ClassDef, ast.With, ast.AsyncWith, ast.AsyncFor, ast.AsyncFunctionDef, ast.Await,
                   ast.Global, ast.Nonlocal)
SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bin", "bool", "chr", "complex", "dict", "divmod", "enumerate", "filter", "float",
    "frozenset", "hex", "int", "isinstance", "iter", "len", "list", "map", "max", "min", "next", "oct", "ord",
    "pow", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip", "hash",
    "Exception", "ValueError", "TypeError", "ZeroDivisionError", "IndexError", "KeyError", "ArithmeticError",
    "OverflowError", "RuntimeError", "StopIteration", "AssertionError", "NameError",
)
RANDOM_NAMES = ("random", "randint", "randrange", "uniform", "choice", "choices", "shuffle", "sample", "seed",
                "gauss", "normalvariate", "expovariate")
STATISTICS_NAMES = ("mean", "fmean", "median", "median_low", "median_high", "mode", "multimode", "stdev", "pstdev",
                    "variance", "pvariance", "quantiles", "correlation", "covariance", "linear_regression",
                    "geometric_mean", "harmonic_mean", "StatisticsError")


class SandboxError(ValueError):
    """Programme refusé avant exécution (construction interdite)."""


class NeedInput(Exception):  # noqa: N818 — signal interne, pas une erreur de l'utilisateur
    def __init__(self, prompt: str) -> None:
        super().__init__(prompt)
        self.prompt = prompt


class OutputLimit(Exception):  # noqa: N818
    pass


def _namespace(module: Any, names: tuple[str, ...] | None = None) -> SimpleNamespace:
    """Copie des fonctions et constantes publiques d'un module : aucun chemin vers `sys`, `os`…"""
    chosen = names or tuple(n for n in dir(module) if not n.startswith("_"))
    values = {n: getattr(module, n) for n in chosen if hasattr(module, n)}
    return SimpleNamespace(**{n: v for n, v in values.items() if not isinstance(v, type(sys))})


def check_program(code: str, modules: dict[str, Any] | None = None) -> ast.Module:
    """Refuse un programme qui sortirait du bac à sable. Lève `SandboxError` avec la ligne fautive.
    `modules` : modules importables (par défaut `MODULES` ; le mode jeu y ajoute `jeu`)."""
    allowed = MODULES if modules is None else modules
    if not isinstance(code, str):
        raise SandboxError("Le programme doit être du texte")
    if len(code) > MAX_CODE:
        raise SandboxError(f"Programme trop long ({len(code)} caractères, {MAX_CODE} au plus)")
    try:
        tree = ast.parse(code, "<programme>", "exec")
    except SyntaxError as exc:
        raise SandboxError(f"Erreur de syntaxe ligne {exc.lineno} : {exc.msg}") from None
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, FORBIDDEN_NODES):
            raise SandboxError(f"Ligne {line} : {type(node).__name__} n'est pas permis dans le bac à sable")
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
            for name in names:
                if name == "jeu" and "jeu" not in allowed:
                    raise SandboxError(f"Ligne {line} : ce programme utilise « jeu » : lance-le avec « Jouer » "
                                       "(fenêtre de jeu)")
                if name not in allowed:
                    raise SandboxError(f"Ligne {line} : module « {name} » non disponible "
                                       f"(disponibles : {', '.join(sorted(allowed))})")
            if isinstance(node, ast.ImportFrom) and node.level:
                raise SandboxError(f"Ligne {line} : import relatif interdit")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise SandboxError(f"Ligne {line} : les noms commençant par « _ » sont interdits")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in FORBIDDEN_ATTRS):
            raise SandboxError(f"Ligne {line} : attribut « {node.attr} » interdit dans le bac à sable")
        defined = (node.name if isinstance(node, ast.FunctionDef) else node.arg if isinstance(node, ast.arg)
                   else None)
        if isinstance(node, ast.alias):  # `from jeu import _x` comme `import x as _y`
            defined = node.name if node.name.startswith("_") else node.asname
        if defined and defined.startswith("_"):
            raise SandboxError(f"Ligne {line} : les noms commençant par « _ » sont interdits")
    return tree


MODULES: dict[str, SimpleNamespace] = {
    "math": _namespace(math),
    "cmath": _namespace(cmath),
    "random": _namespace(random, RANDOM_NAMES),
    "statistics": _namespace(statistics, STATISTICS_NAMES),
}


class Program:
    """Une exécution : sortie, dessins, réponses aux `input()`."""

    def __init__(self, inputs: list[str], cas_session: Any = None, data: str = "") -> None:
        self.inputs = list(inputs)
        self.data = data
        self.used = 0
        self.output: list[str] = []
        self.size = 0
        self.drawings: list[dict[str, Any]] = []
        self.points = 0
        self.cas_session = cas_session

    # -- entrées / sorties
    def write(self, text: str) -> None:
        self.size += len(text)
        if self.size > MAX_OUTPUT:
            raise OutputLimit(f"Sortie trop longue (plus de {MAX_OUTPUT} caractères) : programme arrêté")
        self.output.append(text)

    def print(self, *values: Any, sep: Any = " ", end: Any = "\n") -> None:
        self.write(str(sep).join(str(v) for v in values) + str(end))

    def input(self, prompt: Any = "") -> str:
        prompt = str(prompt)
        if self.used >= len(self.inputs):
            raise NeedInput(prompt)
        value = str(self.inputs[self.used])
        self.used += 1
        self.write(f"{prompt}{value}\n")
        return value

    # -- dessin
    def _add(self, item: dict[str, Any], count: int) -> None:
        self.points += count
        if self.points > MAX_POINTS or len(self.drawings) >= MAX_DRAWINGS:
            raise OutputLimit("Trop de points à dessiner : programme arrêté")
        self.drawings.append(item)

    @staticmethod
    def _numbers(values: Any, name: str) -> list[float]:
        try:
            out = [float(v) for v in values]
        except (TypeError, ValueError):
            raise ValueError(f"{name} doit être une liste de nombres") from None
        return out

    def plot(self, xs: Any, ys: Any = None, color: Any = None) -> None:
        """plot(xs, ys) : ligne brisée ; plot(ys) : abscisses 0, 1, 2…"""
        if ys is None:
            ys, xs = xs, range(len(list(xs)))
        x, y = self._numbers(xs, "xs"), self._numbers(ys, "ys")
        if len(x) != len(y):
            raise ValueError("plot : xs et ys doivent avoir la même longueur")
        self._add({"type": "line", "points": [[a, b] for a, b in zip(x, y, strict=True) if math.isfinite(a)
                                              and math.isfinite(b)], "color": color and str(color)}, len(x))

    def scatter(self, xs: Any, ys: Any, color: Any = None) -> None:
        x, y = self._numbers(xs, "xs"), self._numbers(ys, "ys")
        if len(x) != len(y):
            raise ValueError("scatter : xs et ys doivent avoir la même longueur")
        self._add({"type": "points", "points": [[a, b] for a, b in zip(x, y, strict=True)
                                                if math.isfinite(a) and math.isfinite(b)],
                   "color": color and str(color)}, len(x))

    def fplot(self, f: Any, xmin: float = -10, xmax: float = 10, n: int = 400, color: Any = None) -> None:
        """fplot(f, a, b) : trace une fonction Python de x."""
        if not callable(f):
            raise ValueError("fplot : le premier argument doit être une fonction, ex. fplot(lambda x: x**2, -3, 3)")
        n = max(2, min(int(n), 4000))
        pts: list[list[float] | None] = []
        for i in range(n):
            x = float(xmin) + (float(xmax) - float(xmin)) * i / (n - 1)
            try:
                y = float(f(x))
                pts.append([x, y] if math.isfinite(y) else None)
            except (ValueError, ZeroDivisionError, OverflowError, TypeError):
                pts.append(None)
        self._add({"type": "line", "points": pts, "color": color and str(color)}, n)

    def text(self, x: float, y: float, s: Any) -> None:
        self._add({"type": "text", "x": float(x), "y": float(y), "text": str(s)[:200]}, 1)

    # -- données fournies par l'appelant (un agent qui analyse un fichier CSV, par exemple)
    def lire_csv(self, texte: Any = None, sep: Any = None) -> list[list[Any]]:
        """Découpe un texte CSV (par défaut `DONNEES`) en lignes ; les nombres (virgule française comprise)
        sont convertis. Séparateur deviné (`;`, `,`, tabulation) si `sep` est absent."""
        text = self.data if texte is None else str(texte)
        lines = [line for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
        if sep is None:
            head = lines[0] if lines else ""
            sep = max((";", ",", "\t"), key=head.count) if any(c in head for c in ";,\t") else ","
        rows = []
        for line in lines:
            row: list[Any] = []
            for cell in line.split(str(sep)):
                cell = cell.strip().strip('"')
                try:
                    number = float(cell.replace(",", ".")) if sep != "," else float(cell)
                    row.append(int(number) if number.is_integer() and "." not in cell and "," not in cell
                               else number)
                except ValueError:
                    row.append(cell)
            rows.append(row)
        return rows

    # -- pont vers le moteur de calcul formel
    def cas(self, expression: Any) -> str:
        from modules.calc_cas.engine import evaluate

        result = evaluate(str(expression), self.cas_session)
        if not result["ok"]:
            raise ValueError(f"cas({expression!r}) : {result['error']}")
        return str(result["exact"])

    def cas_value(self, expression: Any) -> Any:
        """Valeur numérique Python (int, float ou complex) d'une expression du CAS."""
        from modules.calc_cas.engine import CasError, parse

        try:
            obj = parse(str(expression), self.cas_session)
            number = complex(obj.evalf(15))
        except (CasError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"cas_value({expression!r}) : {exc}") from None
        if number.imag == 0:
            return int(number.real) if number.real.is_integer() and abs(number.real) < 2 ** 53 else number.real
        return number


def _globals(program: Program, modules: dict[str, Any] | None = None) -> dict[str, Any]:
    safe = {name: getattr(builtins, name) for name in SAFE_BUILTIN_NAMES}
    allowed = MODULES if modules is None else modules

    def guarded_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        if level or name not in allowed:
            raise ImportError(f"module « {name} » non disponible")
        return allowed[name]

    safe.update(print=program.print, input=program.input, __import__=guarded_import)
    return {"__builtins__": safe, "__name__": "programme", "plot": program.plot, "scatter": program.scatter,
            "fplot": program.fplot, "text": program.text, "cas": program.cas, "cas_value": program.cas_value,
            "pi": math.pi, "e": math.e, "sqrt": math.sqrt, "DONNEES": program.data,
            "lire_csv": program.lire_csv}


def run_program(code: str, inputs: list[str] | None = None, seed: int | None = None,
                cas_session: Any = None, data: str | None = None) -> dict[str, Any]:
    """Exécute un programme. Ne lève jamais : retourne la sortie, les dessins et l'éventuelle erreur.
    `data` : texte mis à disposition du programme (`DONNEES`, `lire_csv()`), jamais un chemin de fichier."""
    started = time.monotonic()
    if data is not None and len(str(data)) > MAX_DATA:
        return {"ok": False, "error": f"Données trop longues ({len(str(data))} caractères, {MAX_DATA} au plus)",
                "output": "", "drawings": [], "inputs_used": 0, "elapsed_ms": 0}
    program = Program([str(v) for v in (inputs or [])][:200], cas_session, str(data or ""))
    result: dict[str, Any] = {"ok": True}
    try:
        tree = check_program(code)
        compiled = compile(tree, "<programme>", "exec")
        random.seed(seed)
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(min(old_limit, 1500))
        try:
            exec(compiled, _globals(program))  # noqa: S102 — code vérifié, fonctions natives filtrées, processus isolé
        finally:
            sys.setrecursionlimit(old_limit)
    except SandboxError as exc:
        result = {"ok": False, "error": str(exc), "stage": "analyse"}
    except NeedInput as exc:
        result = {"ok": True, "needs_input": True, "prompt": exc.prompt}
    except OutputLimit as exc:
        result = {"ok": False, "error": str(exc)}
    except MemoryError:
        result = {"ok": False, "error": "Mémoire insuffisante : le programme demande trop de place"}
    except RecursionError:
        result = {"ok": False, "error": "Récursion trop profonde (1 500 appels imbriqués au plus)"}
    except Exception as exc:  # noqa: BLE001 — toute erreur du programme est rendue avec sa ligne
        result = {"ok": False, "error": f"{type(exc).__name__} : {exc}", "line": _line_of(exc)}
    result.update(output="".join(program.output), drawings=program.drawings, inputs_used=program.used,
                  elapsed_ms=round((time.monotonic() - started) * 1000))
    if result.get("line"):
        result["error"] = f"Ligne {result['line']} — {result['error']}"
    return result


def _line_of(exc: BaseException) -> int | None:
    tb = exc.__traceback__
    line = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<programme>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


EXAMPLES: dict[str, str] = {
    "suite_syracuse": (
        "# Suite de Syracuse : nombre d'étapes pour revenir à 1\n"
        "n = int(input(\"Entier de départ ? \"))\n"
        "etapes, valeurs = 0, [n]\n"
        "while n != 1:\n"
        "    n = n // 2 if n % 2 == 0 else 3 * n + 1\n"
        "    etapes += 1\n"
        "    valeurs.append(n)\n"
        "print(\"Étapes :\", etapes, \"— maximum :\", max(valeurs))\n"
        "plot(valeurs)\n"),
    "dichotomie": (
        "# Racine de f par dichotomie, comparée au calcul exact\n"
        "def f(x):\n"
        "    return x**2 - 2\n\n"
        "a, b = 0, 2\n"
        "for i in range(40):\n"
        "    m = (a + b) / 2\n"
        "    if f(a) * f(m) <= 0:\n"
        "        b = m\n"
        "    else:\n"
        "        a = m\n"
        "print(\"Dichotomie :\", (a + b) / 2)\n"
        "print(\"Exact (CAS) :\", cas(\"solve(x^2 - 2 = 0, x)\"))\n"
        "fplot(f, -2, 2)\n"),
    "monte_carlo": (
        "# Estimation de pi par la méthode de Monte-Carlo\n"
        "from random import random\n"
        "n, dedans = 5000, 0\n"
        "xs, ys = [], []\n"
        "for i in range(n):\n"
        "    x, y = random(), random()\n"
        "    if x*x + y*y <= 1:\n"
        "        dedans += 1\n"
        "        if len(xs) < 1500:\n"
        "            xs.append(x); ys.append(y)\n"
        "print(\"pi ≈\", 4 * dedans / n)\n"
        "scatter(xs, ys)\n"),
    "tableau_valeurs": (
        "# Tableau de valeurs et dérivée exacte\n"
        "import math\n"
        "print(\"f'(x) =\", cas(\"diff(x*sin(x), x)\"))\n"
        "for k in range(6):\n"
        "    x = k * math.pi / 4\n"
        "    print(f\"x = {x:.3f}   f(x) = {x * math.sin(x):.5f}\")\n"
        "fplot(lambda x: x * math.sin(x), 0, 2 * math.pi)\n"),
}
