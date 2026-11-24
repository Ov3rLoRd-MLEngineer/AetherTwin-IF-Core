"""Formules, masses molaires, équilibrage exact des équations et stœchiométrie. Code déterministe.

Écriture acceptée :

- formules avec parenthèses ou crochets et hydrates : « Ca(OH)2 », « K4[Fe(CN)6] », « CuSO4·5H2O » (ou « CuSO4*5H2O ») ;
- charges en fin d'espèce après « ^ » : « Fe^3+ », « MnO4^- », « SO4^2- » ; l'électron s'écrit « e^- » ;
- état facultatif en fin d'espèce : « (aq) », « (s) », « (l) », « (g) » ;
- flèche « -> », « → », « = » ou « <=> » ; espèces séparées par « + » entouré d'espaces.

L'équilibrage cherche le noyau entier de la matrice de conservation (éléments et charge) en arithmétique exacte
(SymPy) : un seul équilibrage possible → coefficients entiers les plus petits ; zéro ou plusieurs → message clair.
"""
from __future__ import annotations

import math
import re
from typing import Any

from modules.chem_lab.elements import MASS

_STATE = re.compile(r"\((aq|s|l|g)\)$")
_CHARGE = re.compile(r"\^(\d*)([+-])$")
_COEF = re.compile(r"^(\d+(?:[.,]\d+)?|\d+/\d+)\s*(?=[A-Z(\[e])")
_TOKEN = re.compile(r"([A-Z][a-z]?)|(\d+)|([(\[])|([)\]])|(.)")


class ChemError(ValueError):
    """Formule, équation ou grandeur invalide."""


def _parse_group(text: str) -> dict[str, int]:
    stack: list[dict[str, int]] = [{}]
    tokens = list(_TOKEN.finditer(text))
    i = 0
    while i < len(tokens):
        sym, num, opening, closing, other = tokens[i].groups()
        if other is not None:
            raise ChemError(f"caractère inattendu {other!r} dans « {text} »")
        if num is not None:
            raise ChemError(f"nombre mal placé dans « {text} »")
        count = 1
        if i + 1 < len(tokens) and tokens[i + 1].group(2):
            count = int(tokens[i + 1].group(2))
            i += 1
        if sym:
            if sym not in MASS:
                raise ChemError(f"élément inconnu : {sym!r} (dans « {text} »)")
            stack[-1][sym] = stack[-1].get(sym, 0) + count
            if count == 0:
                raise ChemError(f"indice nul dans « {text} »")
        elif opening:
            stack.append({})
            if count != 1:
                raise ChemError(f"nombre mal placé dans « {text} »")
        elif closing:
            if len(stack) == 1:
                raise ChemError(f"parenthèse fermante en trop dans « {text} »")
            inner = stack.pop()
            for k, v in inner.items():
                stack[-1][k] = stack[-1].get(k, 0) + v * count
        i += 1
    if len(stack) != 1:
        raise ChemError(f"parenthèse non fermée dans « {text} »")
    return stack[0]


def parse_species(text: str) -> dict[str, Any]:
    """« Fe2(SO4)3(aq) » → {formula, atoms, charge, state} ; « e^- » → électron."""
    raw = text.strip().replace(" ", "")
    if not raw:
        raise ChemError("espèce vide")
    state = ""
    m = _STATE.search(raw)
    if m:
        state, raw = m.group(1), raw[: m.start()]
    charge = 0
    m = _CHARGE.search(raw)
    if m:
        charge = (int(m.group(1) or 1)) * (1 if m.group(2) == "+" else -1)
        raw = raw[: m.start()]
    if raw == "e":
        return {"formula": "e", "atoms": {}, "charge": charge or -1, "state": state}
    atoms: dict[str, int] = {}
    for index, part in enumerate(re.split(r"[·*.•]", raw)):
        if not part:
            raise ChemError(f"hydrate mal écrit : « {text} »")
        mult = 1
        lead = re.match(r"^(\d+)(?=[A-Z(\[])", part)
        if lead and index > 0:   # « ·5H2O » : 5 molécules d'eau
            mult, part = int(lead.group(1)), part[lead.end():]
        for k, v in _parse_group(part).items():
            atoms[k] = atoms.get(k, 0) + v * mult
    if not atoms:
        raise ChemError(f"formule vide : « {text} »")
    return {"formula": raw, "atoms": atoms, "charge": charge, "state": state}


def molar_mass(formula: str) -> dict[str, Any]:
    """Masse molaire (g/mol) et composition massique d'une formule."""
    sp = parse_species(formula)
    total = sum(MASS[el] * n for el, n in sp["atoms"].items())
    parts = [{"element": el, "count": n, "mass": round(MASS[el] * n, 4),
              "percent": round(100 * MASS[el] * n / total, 3)} for el, n in sp["atoms"].items()]
    return {"formula": sp["formula"], "charge": sp["charge"], "molar_mass": round(total, 4), "composition": parts}


def split_equation(text: str) -> tuple[list[str], list[str]]:
    for arrow in ("<=>", "<->", "⇌", "->", "→", "=>", "="):
        if arrow in text:
            left, right = text.split(arrow, 1)
            break
    else:
        raise ChemError("flèche absente : écris par exemple « H2 + O2 -> H2O »")

    def side(s: str) -> list[str]:
        items = [x.strip() for x in re.split(r"\s\+\s|\s\+(?=\s*\d*\s*[A-Z(\[e])|^\+", s) if x and x.strip()]
        if not items:
            raise ChemError("un côté de l'équation est vide")
        return items

    return side(left), side(right)


def _strip_coef(item: str) -> str:
    m = _COEF.match(item)
    return item[m.end():].strip() if m else item


def balance(equation: str) -> dict[str, Any]:
    """Équilibre une équation (coefficients entiers les plus petits), charges comprises."""
    import sympy

    left, right = split_equation(equation)
    species = [parse_species(_strip_coef(s)) for s in left + right]
    elements = sorted({el for sp in species for el in sp["atoms"]})
    rows = [[sp["atoms"].get(el, 0) * (1 if i < len(left) else -1) for i, sp in enumerate(species)]
            for el in elements]
    if any(sp["charge"] for sp in species):
        rows.append([sp["charge"] * (1 if i < len(left) else -1) for i, sp in enumerate(species)])
    for el in elements:
        if not any(el in sp["atoms"] for sp in species[: len(left)]) or \
           not any(el in sp["atoms"] for sp in species[len(left):]):
            raise ChemError(f"l'élément {el} n'apparaît que d'un côté : équation impossible à équilibrer")
    space = sympy.Matrix(rows).nullspace()
    if not space:
        raise ChemError("aucun équilibrage possible : vérifie les formules")
    if len(space) > 1:
        raise ChemError("plusieurs équilibrages indépendants : l'équation mélange plusieurs réactions, "
                        "sépare-les ou précise les produits")
    vec = space[0]
    lcm = sympy.ilcm(*[sympy.fraction(sympy.nsimplify(v))[1] for v in vec])
    ints = [int(v * lcm) for v in vec]
    if all(v < 0 for v in ints):
        ints = [-v for v in ints]
    if any(v <= 0 for v in ints):
        raise ChemError("pas d'équilibrage à coefficients tous positifs : une espèce est du mauvais côté ?")
    g = math.gcd(*ints)
    coefs = [v // g for v in ints]

    def show(i: int, sp: dict[str, Any]) -> str:
        name = (left + right)[i]
        name = _strip_coef(name)
        return name if coefs[i] == 1 else f"{coefs[i]} {name}"

    text_left = " + ".join(show(i, sp) for i, sp in enumerate(species[: len(left)]))
    text_right = " + ".join(show(len(left) + i, sp) for i, sp in enumerate(species[len(left):]))
    return {
        "balanced": f"{text_left} → {text_right}",
        "reactants": [{"species": _strip_coef(s), "coef": coefs[i]} for i, s in enumerate(left)],
        "products": [{"species": _strip_coef(s), "coef": coefs[len(left) + i]} for i, s in enumerate(right)],
        "check": {el: sum(sp["atoms"].get(el, 0) * coefs[i] for i, sp in enumerate(species[: len(left)]))
                  for el in elements},
    }


def _amount(spec: dict[str, Any], molar: float) -> float:
    if "mol" in spec and spec["mol"] not in (None, ""):
        n = float(spec["mol"])
    elif "mass_g" in spec and spec["mass_g"] not in (None, ""):
        n = float(spec["mass_g"]) / molar
    elif "volume_L" in spec and "concentration" in spec:
        n = float(spec["volume_L"]) * float(spec["concentration"])
    else:
        raise ChemError("quantité attendue : mol, mass_g, ou volume_L et concentration")
    if not (math.isfinite(n) and n >= 0):
        raise ChemError("quantité négative ou invalide")
    return n


def stoichiometry(equation: str, quantities: dict[str, dict[str, Any]], yield_percent: float = 100.0) -> dict[str, Any]:
    """Réactif limitant, avancement maximal, quantités consommées, formées et restantes.

    `quantities` : {espèce réactive: {"mass_g": …} | {"mol": …} | {"volume_L": …, "concentration": …}}.
    Les réactifs non renseignés sont supposés en excès.
    """
    bal = balance(equation)
    if not quantities:
        raise ChemError("donne la quantité d'au moins un réactif")
    names = {r["species"]: r for r in bal["reactants"]}
    unknown = [k for k in quantities if k not in names]
    if unknown:
        raise ChemError(f"pas un réactif de l'équation : {', '.join(unknown)}")
    rate = float(yield_percent) / 100.0
    if not 0 < rate <= 1:
        raise ChemError("rendement entre 0 et 100 %")
    extents = {}
    rows = []
    for name, spec in quantities.items():
        mm = molar_mass(name)["molar_mass"] if parse_species(name)["atoms"] else 0.0
        n0 = _amount(spec, mm)
        extents[name] = n0 / names[name]["coef"]
        rows.append((name, n0, mm))
    limiting = min(extents, key=extents.get)
    xmax = extents[limiting]
    x = xmax * rate
    out_r = []
    for r in bal["reactants"]:
        mm = molar_mass(r["species"])["molar_mass"] if parse_species(r["species"])["atoms"] else 0.0
        used = r["coef"] * x
        start = next((n0 for name, n0, _m in rows if name == r["species"]), None)
        out_r.append({"species": r["species"], "coef": r["coef"], "molar_mass": mm,
                      "initial_mol": start, "used_mol": used, "used_g": used * mm,
                      "left_mol": None if start is None else start - used,
                      "left_g": None if start is None else (start - used) * mm})
    out_p = []
    for p in bal["products"]:
        mm = molar_mass(p["species"])["molar_mass"] if parse_species(p["species"])["atoms"] else 0.0
        out_p.append({"species": p["species"], "coef": p["coef"], "molar_mass": mm,
                      "formed_mol": p["coef"] * x, "formed_g": p["coef"] * x * mm,
                      "max_g": p["coef"] * xmax * mm})
    return {"balanced": bal["balanced"], "limiting": limiting, "extent_max_mol": xmax, "extent_mol": x,
            "yield_percent": rate * 100, "reactants": out_r, "products": out_p}
