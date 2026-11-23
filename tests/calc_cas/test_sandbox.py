"""calc_cas, mode programmation : programmes ordinaires, input() rejoué, dessins, pont CAS, et surtout tentatives
d'évasion du bac à sable (refusées à l'analyse ou sans effet), boucle infinie, mémoire, sortie géante."""
from __future__ import annotations

import pytest

from modules.calc_cas.engine import Session
from modules.calc_cas.sandbox import EXAMPLES, check_program, run_program
from modules.calc_cas.worker import CasRunner


def run(code: str, inputs: list[str] | None = None, seed: int | None = 1) -> dict:
    return run_program(code, inputs, seed, Session())


def test_ordinary_program() -> None:
    code = "def fact(n):\n    return 1 if n < 2 else n * fact(n - 1)\nfor k in range(1, 6):\n    print(k, fact(k))\n"
    r = run(code)
    assert r["ok"] and r["output"].splitlines()[-1] == "5 120" and r["drawings"] == []


def test_allowed_modules_and_fstrings() -> None:
    r = run("import math\nfrom statistics import mean\nimport random as rd\nprint(f'{math.pi:.4f}', mean([1, 2, 3]), "
            "rd.randint(1, 1), math.sqrt(16))")
    assert r["ok"] and r["output"] == "3.1416 2 1 4.0\n"


def test_seed_makes_runs_reproducible() -> None:
    code = "from random import random\nprint(random())"
    assert run(code, seed=7)["output"] == run(code, seed=7)["output"] != run(code, seed=8)["output"]


def test_input_is_replayed_and_asks_when_missing() -> None:
    code = "a = int(input('a ? '))\nb = int(input('b ? '))\nprint('somme', a + b)"
    first = run(code)
    assert first["ok"] and first["needs_input"] and first["prompt"] == "a ? " and first["inputs_used"] == 0
    second = run(code, ["3"])
    assert second["needs_input"] and second["prompt"] == "b ? " and second["output"] == "a ? 3\n"
    done = run(code, ["3", "4"])
    assert done["ok"] and not done.get("needs_input") and done["output"].endswith("somme 7\n")


def test_drawings_and_cas_bridge() -> None:
    r = run("plot([1, 4, 9])\nscatter([0, 1], [1, 0])\nfplot(lambda x: 1 / x, -1, 1, 5)\ntext(0, 0, 'O')\n"
            "print(cas('integrate(x^2, x, 0, 3)'), cas_value('sqrt(2)') ** 2, cas_value('2 + 3i'))")
    assert r["ok"], r
    kinds = [d["type"] for d in r["drawings"]]
    assert kinds == ["line", "points", "line", "text"]
    assert r["drawings"][0]["points"] == [[0.0, 1.0], [1.0, 4.0], [2.0, 9.0]]
    assert None in r["drawings"][2]["points"]  # 1/0 laissé vide, pas d'erreur
    out = r["output"].split()
    assert out[0] == "9" and abs(float(out[1]) - 2) < 1e-12 and out[2] == "(2+3j)"


@pytest.mark.parametrize("title", sorted(EXAMPLES))
def test_examples_run(title: str) -> None:
    r = run(EXAMPLES[title], ["27"])
    assert r["ok"] and not r.get("needs_input"), r
    assert r["output"]


@pytest.mark.parametrize("code, fragment", [
    ("import os", "non disponible"), ("import sys", "non disponible"), ("from os import path", "non disponible"),
    ("import subprocess", "non disponible"), ("from . import x", "non disponible"),
    ("().__class__.__bases__[0].__subclasses__()", "interdit"), ("x = __builtins__", "interdits"),
    ("print.__self__", "interdit"), ("g = (i for i in [1])\ng.gi_frame", "gi_frame"),
    ("'{0.__class__}'.format(1)", "format"), ("class A:\n    pass", "ClassDef"),
    ("with x:\n    pass", "With"), ("global y", "Global"), ("def _cache():\n    pass", "interdits"),
    ("f'{(1).__class__}'", "interdit"), ("import math as _m", "interdits"),
    ("def f(_x):\n    return _x", "interdits"), ("x = (", "syntaxe"),
])
def test_escapes_are_refused_before_running(code: str, fragment: str) -> None:
    r = run(code)
    assert not r["ok"] and r.get("stage") == "analyse" and fragment in r["error"], r


@pytest.mark.parametrize("code", [
    "open('fichier.txt', 'w')", "eval('1+1')", "exec('print(1)')", "getattr(1, 'real')", "type(1)",
    "globals()", "vars()", "compile('1', 'x', 'eval')", "breakpoint()", "help(print)", "__import__('os')",
    "dir()", "setattr(print, 'x', 1)", "memoryview(b'x')", "object()",
])
def test_dangerous_builtins_do_not_exist(code: str) -> None:
    r = run(code)
    assert not r["ok"] and ("NameError" in r["error"] or "interdit" in r["error"]), r


@pytest.mark.parametrize("path", ["random.os", "statistics.sys", "random.Random", "math.sys"])
def test_module_namespaces_do_not_lead_to_system_modules(path: str) -> None:
    module = path.split(".")[0]
    r = run(f"import {module}\nprint({path})")
    assert not r["ok"] and "AttributeError" in r["error"], r


def test_runtime_errors_report_their_line() -> None:
    r = run("x = 1\ny = 0\nprint(x / y)")
    assert not r["ok"] and r["error"].startswith("Ligne 3") and "ZeroDivisionError" in r["error"]
    deep = run("def f(n):\n    return f(n + 1)\nf(0)")
    assert not deep["ok"] and "Récursion" in deep["error"]
    bad_input = run("n = int(input())", ["abc"])
    assert not bad_input["ok"] and "ValueError" in bad_input["error"]


def test_output_and_drawing_limits() -> None:
    r = run("while True:\n    print('x' * 1000)")
    assert not r["ok"] and "Sortie trop longue" in r["error"] and len(r["output"]) <= 100_000
    pts = run("for i in range(600):\n    plot([1, 2])")
    assert not pts["ok"] and "Trop de points" in pts["error"]


def test_check_program_rejects_non_text_and_huge_code() -> None:
    with pytest.raises(ValueError):
        check_program(3)  # type: ignore[arg-type]
    assert "trop long" in run("x = 1\n" * 5000)["error"]


@pytest.fixture(scope="module")
def sandbox():
    r = CasRunner(timeout_s=3, memory_mb=600)
    yield r
    r.stop()


def test_infinite_loop_is_killed_by_the_worker(sandbox: CasRunner) -> None:
    r = sandbox.call("program", code="while True:\n    pass", session="program", timeout_s=2)
    assert r["ok"] is False and r["timeout"] is True
    ok = sandbox.call("program", code="print(6 * 7)", session="program")
    assert ok["ok"] and ok["output"] == "42\n"


def test_memory_bomb_is_contained(sandbox: CasRunner) -> None:
    r = sandbox.call("program", code="x = [0] * (10 ** 9)\nprint(len(x))", session="program", timeout_s=20)
    assert r["ok"] is False and ("Mémoire" in r["error"] or r.get("timeout") or "arrêté" in r["error"]), r
    assert sandbox.call("program", code="print('encore là')", session="program")["output"] == "encore là\n"
