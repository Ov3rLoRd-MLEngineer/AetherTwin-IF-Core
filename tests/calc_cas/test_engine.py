"""calc_cas, moteur : chaque fonction du CAS, cas limites (division par zéro, résultats non exacts, saisies
invalides ou malveillantes), session (variables, fonctions), présentation (texte, LaTeX, MathML)."""
from __future__ import annotations

import pytest

from modules.calc_cas.demos import EXAMPLES
from modules.calc_cas.engine import Session, evaluate, normalize, to_float, trim_zeros, wrap_equations


def ok(text: str, session: Session | None = None) -> dict:
    result = evaluate(text, session)
    assert result["ok"], result
    return result


def err(text: str, session: Session | None = None) -> str:
    result = evaluate(text, session)
    assert not result["ok"], result
    assert isinstance(result["error"], str) and result["error"]
    return result["error"]


@pytest.mark.parametrize("text, exact", [
    # arithmétique exacte
    ("2 + 2", "4"), ("1/3 + 1/6", "1/2"), ("sqrt(8)", "2*sqrt(2)"), ("2^100", str(2 ** 100)), ("5!", "120"),
    ("√2 * √2", "2"), ("√(9)", "3"), ("7 × 6", "42"), ("10 ÷ 4", "5/2"),
    # algèbre
    ("simplify((x^2 - 1)/(x - 1))", "x + 1"), ("expand((a + b)^2)", "a**2 + 2*a*b + b**2"),
    ("factor(x^2 - 5x + 6)", "(x - 3)*(x - 2)"), ("2x + 3x", "5*x"), ("2(x + 1)", "2*x + 2"),
    ("apart(1/(x^2 - 1))", "-1/(2*(x + 1)) + 1/(2*(x - 1))"), ("cancel((x^2 + 2x + 1)/(x + 1))", "x + 1"),
    # dérivées
    ("diff(x^3, x)", "3*x**2"), ("diff(sin(x)^2)", "2*sin(x)*cos(x)"), ("diff(x^4, x, 2)", "12*x**2"),
    ("dériver(e^(2x))", "2*exp(2*x)"), ("diff(x*y^2, y)", "2*x*y"),
    # intégrales
    ("integrate(x^2, x)", "x**3/3"), ("integrate(x^2, x, 0, 3)", "9"), ("integrate(1/x, x, 1, e)", "1"),
    ("integrate(e^(-x^2), x, -oo, oo)", "sqrt(pi)"), ("intégrer(cos(x))", "sin(x)"),
    ("integrate(1/x^2, x, 1, oo)", "1"),
    # limites
    ("limit(sin(x)/x, x, 0)", "1"), ("limit((1 + 1/n)^n, n, oo)", "E"), ("limit(1/x, x, 0, \"+\")", "oo"),
    ("limit(1/x, x, 0, \"-\")", "-oo"), ("limit(1/x, x, oo)", "0"), ("limite(x^2, x, 3)", "9"),
    # équations et systèmes
    ("solve(x^2 = 2, x)", "[x = -sqrt(2), x = sqrt(2)]"), ("solve(x^2 + 1 = 0)", "[x = -I, x = I]"),
    ("solve([x + y = 3, x - y = 1], [x, y])", "[[x = 2, y = 1]]"), ("solve(x^2 = -4x - 4, x)", "[x = -2]"),
    ("résoudre(2x + 1 = 7)", "[x = 3]"), ("solve(x = x + 1, x)", "[]"),
    # sommes et suites
    ("sum(k, k, 1, n)", "n**2/2 + n/2"), ("sum(1/k^2, k, 1, oo)", "pi**2/6"), ("sum(2^k, k, 0, 10)", "2047"),
    ("product(k, k, 1, 5)", "120"), ("sum([1, 2, 3, 4])", "10"),
    # matrices
    ("det([[1, 2], [3, 4]])", "-2"), ("inv([[2, 0], [0, 4]])", "Matrix([\n[1/2,   0],\n[  0, 1/4]])"),
    ("eigenvals([[2, 1], [1, 2]])", "{1: 1, 3: 1}"), ("transpose([[1, 2]])", "Matrix([\n[1],\n[2]])"),
    ("[[1, 2], [3, 4]] * [[1], [1]]", "Matrix([\n[3],\n[7]])"), ("rank([[1, 2], [2, 4]])", "1"),
    ("trace([[1, 2], [3, 4]])", "5"), ("det(eye(3))", "1"),
    # complexes
    ("(1 + 2i)(3 - i)", "5 + 5*I"), ("i^2", "-1"), ("abs(3 + 4i)", "5"), ("re(2 + 3i)", "2"), ("im(2 + 3i)", "3"),
    ("conj(2 + 3i)", "2 - 3*I"), ("e^(i pi)", "-1"), ("polar(1 + i)", "[sqrt(2), pi/4]"),
    # arithmétique, statistiques exactes
    ("gcd(12, 18)", "6"), ("lcm(4, 6)", "12"), ("isprime(97)", "vrai"), ("isprime(91)", "faux"),
    ("factorint(360)", "{2: 3, 3: 2, 5: 1}"), ("mean([1, 2, 3, 4])", "5/2"), ("median([3, 1, 2])", "2"),
    ("variance([1, 2, 3, 4])", "5/4"), ("binomial(5, 2)", "10"),
    # séries
    ("taylor(e^x, x, 0, 4)", "x**3/6 + x**2/2 + x + 1"),
])
def test_exact_results(text: str, exact: str) -> None:
    assert ok(text)["exact"] == exact


def test_exact_and_approx_together() -> None:
    r = ok("sqrt(2)")
    assert r["exact"] == "sqrt(2)" and r["approx"] == "1.41421356237"
    assert r["latex"] == r"\sqrt{2}" and "<msqrt>" in r["mathml"]
    assert ok("pi")["approx"] == "3.14159265359"
    assert ok("1/4")["approx"] == "0.25"  # zéros de fin retirés
    assert ok("4")["approx"] is None and ok("2x")["approx"] is None  # rien d'utile à approcher
    assert ok("solve(x^2 = 2, x)")["approx"] == "[x = -1.41421356237, x = 1.41421356237]"
    assert ok("approx(pi, 30)")["exact"].startswith("3.1415926535897932384626433832")
    assert ok("N(sqrt(2))")["exact"].startswith("1.41421356237")


def test_non_elementary_integral_is_kept_with_warning_and_approximated() -> None:
    r = ok("integrate(sin(x)/log(x), x)")
    assert r["exact"].startswith("Integral(") and "warning" in r
    definite = ok("integrate(e^(-x^3), x, 0, 1)")
    assert definite["approx"] is not None and abs(float(definite["approx"]) - 0.807511182139) < 1e-9


@pytest.mark.parametrize("text", ["1/0", "0/0", "x/0", "1/(2 - 2)", "log(0)", "oo - oo"])
def test_division_by_zero_and_undefined_never_crash(text: str) -> None:
    assert "zéro" in err(text) or "indéfini" in err(text) or "défini" in err(text)


@pytest.mark.parametrize("text, fragment", [
    ("", "vide"), ("   ", "vide"), ("2 +* 3", "invalide"), ("(x + 1", "invalide"), ("sin(", "invalide"),
    ("x = ", "incomplète"), ("= 3", "incomplète"), ("limit(1/x, x, 0)", "n'existe pas"),
    ("inv([[1, 2], [2, 4]])", "non inversible"), ("det([[1, 2, 3], [4, 5, 6]])", "carrée"),
    ("[[1, 2], [3]]", "même longueur"), ("[[1, 2]] * [[1, 2]]", "incompatibles"),
    ("integrate(x, x, 1)", "deux bornes"), ("diff(a*b)", "précise la variable"),
    ("limit(x, x, 0, \"haut\")", "Sens"), ("sum(k, k)", "début, fin"), ("mean([])", "non vide"),
    ("x" * 2001, "trop longue"), ("stdev([1])", "deux valeurs"),
])
def test_invalid_inputs_give_readable_errors(text: str, fragment: str) -> None:
    assert fragment in err(text)


@pytest.mark.parametrize("text", [
    "x.__class__", "().__class__.__bases__", "__import__('os')", "open('fichier')", "eval('1')",
    "exec('1')", "Symbol('x').evalf", "[c for c in [1]]", "(lambda: 1)()", "globals()", "_secret",
    "f'{1}'", "getattr(x, 'y')", "Function('f')(x).func", "sin.__call__(1)",
])
def test_code_injection_is_refused(text: str) -> None:
    result = evaluate(text)
    # soit refusé, soit traité comme un symbole/fonction formelle inoffensif : jamais d'exécution Python
    if result["ok"]:
        assert result["kind"] in ("expression", "relation"), result
        assert "os" not in result["exact"] or "Symbol" not in result["exact"]
    else:
        assert result["error"]


def test_injection_does_not_reach_builtins() -> None:
    for text in ("open('x')", "eval('1+1')", "globals()", "getattr(x, 'y')"):
        result = evaluate(text)
        assert not result["ok"] or result["exact"] in ("open(x)", "eval(1+1)", "globals()", "getattr(x, y)",
                                                        "eval(2)"), result


def test_session_variables_functions_and_ans() -> None:
    s = Session()
    assert ok("a := 5", s)["kind"] == "définition"
    ok("f(x) := x^2 + a", s)
    assert ok("f(3)", s)["exact"] == "14"
    assert ok("diff(f(t), t)", s)["exact"] == "2*t"
    ok("g(x, y) := x*y + 1", s)
    assert ok("g(2, 3)", s)["exact"] == "7"
    assert ok("2 + 3", s)["exact"] == "5" and ok("ans * 2", s)["exact"] == "10"
    ok("a := 10", s)  # redéfinition
    assert ok("a + 1", s)["exact"] == "11"
    assert [d["name"] for d in s.listing()] == ["f", "g", "a"]
    assert s.delete("a") and ok("a + 1", s)["exact"] == "a + 1"
    ok("x := 3", s)
    assert ok("f(x) := x^2", s)["exact"] == "x**2"  # le paramètre masque la variable x
    assert ok("f(2)", s)["exact"] == "4"
    assert ok("L := [1, 2, 3]", s) and ok("mean(L)", s)["exact"] == "2"


@pytest.mark.parametrize("text, fragment", [
    ("sin := 3", "réservé"), ("pi := 3", "réservé"), ("ans := 1", "réservé"), ("f(x, x) := x", "répété"),
    ("f() := 1", "Paramètres invalides"), ("f(sin) := 1", "Paramètres invalides"), ("a := 1/0", "zéro"),
    ("f(x) := [x, 1]", "expression"),
])
def test_invalid_definitions(text: str, fragment: str) -> None:
    assert fragment in err(text)


def test_function_without_argument_is_explained() -> None:
    s = Session()
    ok("f(x) := x + 1", s)
    assert "sans argument" in err("f", s)


def test_wrap_equations_and_normalize() -> None:
    assert wrap_equations("x^2 = 2") == "Eq(x^2, 2)"
    assert wrap_equations("solve([x+y=3, x-y=1], [x,y])").replace(" ", "") == "solve([Eq(x+y,3),Eq(x-y,1)],[x,y])"
    assert wrap_equations("x == 2") == "x == 2" and wrap_equations("x <= 2") == "x <= 2"
    assert normalize("√2 × 3") == "sqrt(2) * 3" and normalize("x²") == "x^2"


def test_trim_zeros_and_to_float() -> None:
    assert trim_zeros("0.500000") == "0.5" and trim_zeros("4.000") == "4" and trim_zeros("10.05") == "10.05"
    assert trim_zeros("1.50000e-5") == "1.5e-5"
    assert to_float("1/4") == 0.25 and to_float(3) == 3.0 and abs(to_float("sqrt(2)") - 2 ** 0.5) < 1e-12
    for bad in ("x", "i", True):
        with pytest.raises(ValueError):
            to_float(bad)


def test_non_text_input() -> None:
    assert not evaluate(42)["ok"]  # type: ignore[arg-type]


@pytest.mark.parametrize("title, text, exact", EXAMPLES)
def test_demo_examples(title: str, text: str, exact: str) -> None:
    assert ok(text)["exact"] == exact, title


def test_degree_mode() -> None:
    s = Session()
    s.settings["angle"] = "deg"
    assert ok("sin(30)", s)["exact"] == "1/2" and ok("cos(180)", s)["exact"] == "-1"
    assert ok("asin(1)", s)["exact"] == "90" and ok("atan(1)", s)["exact"] == "45"
    s.settings["angle"] = "rad"
    assert ok("sin(pi/6)", s)["exact"] == "1/2"


def test_sto_arrow_defines_a_variable() -> None:
    s = Session()
    r = ok("3^2 + 1 → b", s)
    assert r["kind"] == "définition" and r["input"] == "3^2 + 1 → b" and ok("b", s)["exact"] == "10"
    assert ok("x^2 -> g", s) and ok("g + 1", s)["exact"] == "x**2 + 1"
    assert "réservé" in err("5 → pi", s)
