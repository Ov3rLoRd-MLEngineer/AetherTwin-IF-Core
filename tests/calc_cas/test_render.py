"""calc_cas, rendu des résultats en image : LaTeX de SymPy dessiné par matplotlib, repli texte sinon."""
from __future__ import annotations

import base64

import pytest
import sympy as sp

from modules.calc_cas.engine import present
from modules.calc_cas.render import mathtext_of, png_base64, png_of

pytest.importorskip("matplotlib")
PNG = b"\x89PNG\r\n\x1a\n"


def width(data: bytes) -> int:
    return int.from_bytes(data[16:20], "big")


@pytest.mark.parametrize("latex", [
    r"\frac{x^{3}}{3}", r"\int\limits_{0}^{3} x^{2}\, dx", r"\sqrt{2} + \pi", r"\left(x + 1\right)^{2}",
    r"\left[\begin{matrix}1 & 2\\3 & 4\end{matrix}\right]", sp.latex(sp.Matrix([[sp.Rational(1, 2), sp.sqrt(2)]])),
])
def test_formulas_become_transparent_png(latex: str) -> None:
    data = png_of(latex)
    assert data and data.startswith(PNG) and 0 < width(data) <= 5000


def test_unsupported_or_huge_formulas_fall_back() -> None:
    x = sp.Symbol("x")
    assert png_of(sp.latex(sp.Piecewise((x, x > 0), (0, True)))) is None
    assert png_of("x" * 5000) is None and png_of("") is None
    assert png_of(r"\frac{1}{") is None  # LaTeX invalide : pas d'exception, repli
    encoded = png_base64(r"\frac{1}{2}")
    assert encoded and base64.b64decode(encoded).startswith(PNG)


def test_mathtext_adaptations() -> None:
    assert mathtext_of(r"\text{abc}") == r"\mathrm{abc}"
    assert mathtext_of(r"\left(x + 1\right)") == "(x + 1)"
    assert r"\left(" in mathtext_of(r"\left(\frac{1}{2}\right)")  # contenu haut : délimiteurs extensibles
    assert mathtext_of(r"\frac{1}{2} + \frac{a}{\frac{1}{b}}").startswith(r"\dfrac{1}{2}")
    assert r"\int_{0}^{1}\,\," in mathtext_of(r"\int_{0}^{1} x dx")


def test_present_has_unicode_pretty_fallback() -> None:
    x = sp.Symbol("x")
    assert "√2" in present(sp.Rational(1, 2) + sp.sqrt(2))["pretty"]
    assert "\n" in present(sp.Integral(x ** 2, x))["pretty"]
