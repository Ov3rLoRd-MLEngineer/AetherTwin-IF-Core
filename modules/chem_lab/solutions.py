"""Solutions aqueuses à 25 °C : pH exact, dilutions, préparation, titrages acido-basiques simulés.

Le pH se calcule sans approximation (ni « acide faible peu dissocié », ni oubli de l'eau) ; on résout
l'électroneutralité

    h + Σ cations forts + Σ C·h/(h+Ka) [couples BH⁺/B]  =  Kw/h + Σ anions forts + Σ C·Ka/(h+Ka) [couples HA/A⁻]

par dichotomie sur log h (fonction monotone, une seule racine). Un acide fort est un couple de pKa très bas,
une base forte apporte des cations (Na⁺), etc. Les titrages enchaînent ce calcul volume après volume.
"""
from __future__ import annotations

import math
from typing import Any

PKW = 14.0
KW = 10 ** -PKW
STRONG_PKA = -10.0      # « acide fort » : complètement dissocié en pratique

INDICATORS = [  # nom, zone de virage, couleur acide, couleur basique
    {"name": "hélianthine (méthylorange)", "low": 3.1, "high": 4.4, "acid": "#d9342b", "base": "#f2b632"},
    {"name": "vert de bromocrésol", "low": 3.8, "high": 5.4, "acid": "#e7c93a", "base": "#2f6fb5"},
    {"name": "rouge de méthyle", "low": 4.2, "high": 6.2, "acid": "#d42f45", "base": "#efc534"},
    {"name": "bleu de bromothymol (BBT)", "low": 6.0, "high": 7.6, "acid": "#e8c832", "base": "#2459b8"},
    {"name": "rouge de phénol", "low": 6.8, "high": 8.4, "acid": "#efc430", "base": "#d6336c"},
    {"name": "phénolphtaléine", "low": 8.2, "high": 10.0, "acid": "#f4f6f8", "base": "#d6338f"},
    {"name": "thymolphtaléine", "low": 9.3, "high": 10.5, "acid": "#f4f6f8", "base": "#2d5fc4"},
]

KINDS = {
    "acide_fort": "acide fort (ex. HCl)", "acide_faible": "acide faible (ex. CH3COOH, pKa 4,76)",
    "base_forte": "base forte (ex. NaOH)", "base_faible": "base faible (ex. NH3, pKa 9,25)",
}


class SolutionError(ValueError):
    pass


def _num(name: str, value: Any, positive: bool = True) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise SolutionError(f"{name} : nombre attendu") from None
    if not math.isfinite(v) or (positive and v <= 0) or v < 0:
        raise SolutionError(f"{name} doit être {'strictement ' if positive else ''}positif")
    return v


def ph_of(acids: list[tuple[float, float]] = (), bases: list[tuple[float, float]] = (),
          cations: float = 0.0, anions: float = 0.0) -> float:
    """pH d'un mélange. acids : [(C, pKa)] couples HA/A⁻ apportés sous forme HA ; bases : [(C, pKa)] couples BH⁺/B
    apportés sous forme B ; cations / anions : ions forts spectateurs (Na⁺, Cl⁻…) en mol/L."""

    def excess(log_h: float) -> float:
        h = 10 ** log_h
        positive = h + cations + sum(c * h / (h + 10 ** -pk) for c, pk in bases)
        negative = KW / h + anions + sum(c * 10 ** -pk / (h + 10 ** -pk) for c, pk in acids)
        return positive - negative

    lo, hi = -16.0, 2.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if excess(mid) > 0:
            hi = mid
        else:
            lo = mid
    return -(lo + hi) / 2


def solution_ph(kind: str, concentration: float, pka: float | None = None) -> dict[str, Any]:
    c = _num("concentration", concentration)
    if kind == "acide_fort":
        ph = ph_of(acids=[(c, STRONG_PKA)])
    elif kind == "base_forte":
        ph = ph_of(cations=c)
    elif kind == "acide_faible":
        ph = ph_of(acids=[(c, float(_need(pka)))])
    elif kind == "base_faible":
        ph = ph_of(bases=[(c, float(_need(pka)))])
    else:
        raise SolutionError(f"nature inconnue : {kind!r} ({', '.join(KINDS)})")
    h = 10 ** -ph
    out = {"kind": kind, "concentration": c, "ph": round(ph, 3), "h3o": h, "oh": KW / h}
    if kind in ("acide_faible", "base_faible"):
        ka = 10 ** -float(pka)
        out["dissociation_percent"] = round(100 * (ka / (h + ka) if kind == "acide_faible" else h / (h + ka)), 3)
    return out


def _need(pka: Any) -> float:
    if pka in (None, ""):
        raise SolutionError("pKa nécessaire pour un acide ou une base faible")
    return float(pka)


def buffer_ph(acid_c: float, base_c: float, pka: float) -> dict[str, Any]:
    """Tampon HA / A⁻ (A⁻ apporté avec Na⁺) : pH exact et valeur de Henderson-Hasselbalch pour comparer."""
    a, b = _num("acide", acid_c, False), _num("base", base_c, False)
    if a + b <= 0:
        raise SolutionError("tampon vide")
    ph = ph_of(acids=[(a + b, float(pka))], cations=b)
    hh = float(pka) + math.log10(b / a) if a > 0 and b > 0 else None
    return {"ph": round(ph, 3), "henderson": None if hh is None else round(hh, 3)}


def dilution(c1: Any = None, v1: Any = None, c2: Any = None, v2: Any = None) -> dict[str, Any]:
    """C1·V1 = C2·V2 : laisse vide la grandeur cherchée (une seule)."""
    values = {"c1": c1, "v1": v1, "c2": c2, "v2": v2}
    missing = [k for k, v in values.items() if v in (None, "")]
    if len(missing) != 1:
        raise SolutionError("donne exactement trois grandeurs sur quatre")
    known = {k: _num(k, v) for k, v in values.items() if k not in missing}
    m = missing[0]
    if m == "c1":
        known[m] = known["c2"] * known["v2"] / known["v1"]
    elif m == "v1":
        known[m] = known["c2"] * known["v2"] / known["c1"]
    elif m == "c2":
        known[m] = known["c1"] * known["v1"] / known["v2"]
    else:
        known[m] = known["c1"] * known["v1"] / known["c2"]
    if known["c2"] > known["c1"]:
        raise SolutionError("une dilution ne peut pas augmenter la concentration (C2 > C1)")
    return {**known, "found": m, "factor": known["c1"] / known["c2"]}


def preparation(formula: str, concentration: float, volume_l: float, purity_percent: float = 100.0) -> dict[str, Any]:
    """Masse de solide à peser pour préparer V litres à C mol/L."""
    from modules.chem_lab.chemistry import molar_mass

    mm = molar_mass(formula)["molar_mass"]
    c, v = _num("concentration", concentration), _num("volume", volume_l)
    p = _num("pureté", purity_percent) / 100
    if p > 1:
        raise SolutionError("pureté au plus 100 %")
    n = c * v
    return {"formula": formula, "molar_mass": mm, "mol": n, "mass_g": n * mm / p}


def titration(analyte: str, c_analyte: float, v_analyte_ml: float, c_titrant: float,
              pka: float | None = None, v_max_ml: float | None = None, points: int = 241) -> dict[str, Any]:
    """Courbe de titrage pH = f(V versé). Analyte : acide (fort/faible) titré par la soude, ou base (forte/faible)
    titrée par l'acide chlorhydrique. Renvoie la courbe, l'équivalence, la demi-équivalence et les indicateurs."""
    ca, va, ct = _num("C analyte", c_analyte), _num("V analyte", v_analyte_ml) / 1000, _num("C titrant", c_titrant)
    if analyte not in KINDS:
        raise SolutionError(f"analyte inconnu : {analyte!r}")
    weak = analyte.endswith("faible")
    pk = _need(pka) if weak else None
    v_eq = ca * va / ct
    v_max = (_num("V max", v_max_ml) / 1000) if v_max_ml else 2 * v_eq
    points = max(21, min(int(points), 2001))

    def ph_at(v: float) -> float:
        total = va + v
        c_an, c_ti = ca * va / total, ct * v / total
        if analyte == "acide_fort":
            return ph_of(acids=[(c_an, STRONG_PKA)], cations=c_ti)
        if analyte == "acide_faible":
            return ph_of(acids=[(c_an, pk)], cations=c_ti)
        if analyte == "base_forte":
            return ph_of(cations=c_an, acids=[(c_ti, STRONG_PKA)])
        return ph_of(bases=[(c_an, pk)], acids=[(c_ti, STRONG_PKA)])

    curve = []
    for i in range(points):
        v = v_max * i / (points - 1)
        curve.append([round(v * 1000, 4), round(ph_at(v), 4)])
    ph_eq = ph_at(v_eq)
    suitable = [ind["name"] for ind in INDICATORS if ind["low"] <= ph_eq <= ind["high"]]
    jump = (ph_at(v_eq * 0.99), ph_at(v_eq * 1.01))
    for ind in INDICATORS:
        ind_ok = min(jump) <= ind["low"] and ind["high"] <= max(jump)
        if ind_ok and ind["name"] not in suitable:
            suitable.append(ind["name"])
    return {
        "analyte": analyte, "titrant": "NaOH" if analyte.startswith("acide") else "HCl",
        "curve": curve, "v_eq_ml": round(v_eq * 1000, 4), "ph_eq": round(ph_eq, 3),
        "v_half_ml": round(v_eq * 500, 4), "ph_half": round(ph_at(v_eq / 2), 3),
        "ph_start": round(ph_at(0.0), 3), "jump": [round(min(jump), 2), round(max(jump), 2)],
        "indicators": suitable, "all_indicators": INDICATORS,
    }
