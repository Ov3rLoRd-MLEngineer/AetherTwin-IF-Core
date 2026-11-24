"""Rendu des résultats en image : LaTeX de SymPy dessiné par matplotlib (mathtext), PNG transparent.

    png_of(r"\\frac{x^{3}}{3}")   # -> octets PNG (encre noire sur fond transparent), ou None si impossible

L'encre est noire : la page l'inverse en thème sombre (filtre CSS), une seule image suffit pour les deux thèmes.
mathtext ne connaît ni les environnements `matrix` ni `cases` : une matrice seule est mise en page ici, cellule par
cellule, avec ses crochets ; pour le reste (systèmes par morceaux, matrices imbriquées…), `None`, et la page affiche
le repli texte `sympy.pretty(use_unicode=True)` donné par le moteur.
"""
from __future__ import annotations

import base64
import io
import re
from functools import lru_cache
from typing import Any

FONT_PT = 15.0
DPI = 200  # affiché à la moitié : net sur les écrans à haute densité
MAX_LATEX = 4000
MAX_PIXELS = 5000
MATRIX = re.compile(r"^\\left\[\\begin\{matrix\}(?P<body>.*)\\end\{matrix\}\\right\]$", re.S)


@lru_cache(maxsize=1)
def _mpl() -> Any:
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import mathtext
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    from matplotlib.lines import Line2D

    prop = FontProperties(size=FONT_PT, math_fontfamily="cm")
    return {"parser": mathtext.MathTextParser("path"), "Figure": Figure, "prop": prop, "Line2D": Line2D}


def mathtext_of(latex: str) -> str:
    """Adapte le LaTeX de SymPy au sous-ensemble mathtext de matplotlib."""
    text = latex.strip()
    text = re.sub(r"\\text\{([^{}]*)\}", r"\\mathrm{\1}", text)
    text = text.replace(r"\displaystyle", "").replace(r"\limits", "").replace(r"\nolimits", "")
    text = re.sub(r"\\(?:mathtt|textrm|textit)\{", r"\\mathrm{", text)
    # mathtext dimensionne mal les délimiteurs extensibles autour d'un contenu d'une ligne : parenthèses simples
    tall = re.compile(r"\\(?:frac|sum|int|prod|sqrt|binom|lim)|\^\{|_\{")
    simple = re.compile(r"\\left([(\[|])((?:(?!\\left|\\right).)*?)\\right([)\]|])", re.S)
    previous = None
    while previous != text:
        previous = text
        text = simple.sub(lambda m: m.group(0).replace("\\left", "\\bigl").replace("\\right", "\\bigr")
                          if tall.search(m.group(2)) else f"{m.group(1)}{m.group(2).strip()}{m.group(3)}", text)
    text = text.replace(r"\bigl", r"\left").replace(r"\bigr", r"\right")
    text = _display_fractions(text)
    # espace après ∫ et ses bornes : l'intégrande ne chevauche pas le signe
    text = re.sub(r"\\int(?![a-z])((?:[_^](?:\{[^{}]*\}|[^{\s\\]))*)", r"\\int\1\\,\\,", text)
    return text


def _display_fractions(text: str) -> str:
    """`\\frac` hors de toute accolade (fraction principale) en `\\dfrac` : taille d'affichage, pas de texte."""
    out, depth, i = [], 0, 0
    while i < len(text):
        if text.startswith(r"\frac", i) and depth == 0:
            out.append(r"\dfrac")
            i += 5
            continue
        depth += {"{": 1, "}": -1}.get(text[i], 0) if text[i - 1:i] != "\\" else 0
        out.append(text[i])
        i += 1
    return "".join(out)


def _size(m: dict[str, Any], tex: str) -> tuple[float, float, float]:
    """Largeur, hauteur, profondeur (en points) d'une formule mathtext ; lève ValueError si invalide."""
    w, h, d, *_ = m["parser"].parse(f"${tex}$", dpi=72, prop=m["prop"])
    return float(w), float(h), float(d)


def _save(fig: Any) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, dpi=DPI, format="png", transparent=True)
    return buffer.getvalue()


def _formula(m: dict[str, Any], tex: str) -> bytes:
    w, h, d = _size(m, tex)
    pad = 2.0
    fig = m["Figure"](figsize=((w + 2 * pad) / 72, (h + 2 * pad) / 72))
    fig.text(pad / (w + 2 * pad), (d + pad) / (h + 2 * pad), f"${tex}$", fontproperties=m["prop"], color="black")
    return _save(fig)


def _matrix(m: dict[str, Any], body: str) -> bytes:
    rows = [[cell.strip() for cell in row.split("&")] for row in re.split(r"\\\\", body) if row.strip()]
    if not rows or any(len(r) != len(rows[0]) for r in rows):
        raise ValueError("matrice irrégulière")
    cells = [[mathtext_of(c) or "{}" for c in row] for row in rows]
    sizes = [[_size(m, c) for c in row] for row in cells]
    col_w = [max(sizes[i][j][0] for i in range(len(rows))) for j in range(len(rows[0]))]
    row_h = [max(s[1] - s[2] for s in row) for row in sizes]
    row_d = [max(s[2] for s in row) for row in sizes]
    gap_x, gap_y, bracket, pad = 14.0, 7.0, 7.0, 3.0
    width = sum(col_w) + gap_x * (len(col_w) - 1) + 2 * (bracket + 4) + 2 * pad
    height = sum(row_h) + sum(row_d) + gap_y * (len(rows) - 1) + 2 * pad + 6
    fig = m["Figure"](figsize=(width / 72, height / 72))
    y = height - pad - 3
    for i, row in enumerate(cells):
        y -= row_h[i]
        x = pad + bracket + 4
        for j, tex in enumerate(row):
            offset = (col_w[j] - sizes[i][j][0]) / 2  # cellules centrées
            fig.text((x + offset) / width, y / height, f"${tex}$", fontproperties=m["prop"], color="black")
            x += col_w[j] + gap_x
        y -= row_d[i] + gap_y
    for left in (True, False):  # crochets [ ]
        x0 = pad + 1 if left else width - pad - 1
        x1 = x0 + bracket if left else x0 - bracket
        xs, ys = [x1, x0, x0, x1], [height - pad, height - pad, pad, pad]
        fig.add_artist(m["Line2D"]([v / width for v in xs], [v / height for v in ys], color="black", linewidth=1.2,
                                   transform=fig.transFigure))
    return _save(fig)


def png_of(latex: str) -> bytes | None:
    """PNG transparent de la formule, ou `None` si mathtext ne sait pas la dessiner."""
    if not latex or len(latex) > MAX_LATEX:
        return None
    try:
        m = _mpl()
        found = MATRIX.match(latex.strip())
        if found and r"\begin" not in found.group("body"):
            data = _matrix(m, found.group("body"))
        elif r"\begin" in latex:
            return None
        else:
            data = _formula(m, mathtext_of(latex))
    except Exception:  # noqa: BLE001 — formule hors de portée de mathtext : repli texte côté page
        return None
    width = int.from_bytes(data[16:20], "big") if data[:8] == b"\x89PNG\r\n\x1a\n" else 0
    return data if 0 < width <= MAX_PIXELS else None


def png_base64(latex: str) -> str | None:
    data = png_of(latex)
    return base64.b64encode(data).decode("ascii") if data else None
