"""Génie chimique : masses molaires, gaz parfait, bilans de matière, équilibres. Code déterministe.

Unités explicites dans les noms (kg, mol, Pa, K, m³). Les masses atomiques sont les valeurs abrégées
de l'UICPA ; la table couvre les éléments courants et se complète au besoin.
"""
from __future__ import annotations

import math
import re
from typing import Any

R = 8.314462618  # J mol⁻¹ K⁻¹, constante des gaz parfaits (exacte depuis 2019)
ATM_PA = 101_325.0
ZERO_CELSIUS_K = 273.15

ATOMIC_MASS = {  # g/mol
    "H": 1.008, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81, "C": 12.011, "N": 14.007, "O": 15.999,
    "F": 18.998, "Ne": 20.180, "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974, "S": 32.06,
    "Cl": 35.45, "Ar": 39.95, "K": 39.098, "Ca": 40.078, "Ti": 47.867, "Cr": 51.996, "Mn": 54.938, "Fe": 55.845,
    "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38, "Br": 79.904, "Ag": 107.87, "I": 126.90, "Ba": 137.33,
    "Au": 196.97, "Hg": 200.59, "Pb": 207.2,
}

_TOKEN = re.compile(r"([A-Z][a-z]?)|(\d+)|([()])")


class ChemistryError(ValueError):
    """Formule, composition ou grandeur invalide."""


def _positive(**values: float) -> None:
    for name, value in values.items():
        if not (isinstance(value, int | float) and math.isfinite(value) and value > 0):
            raise ChemistryError(f"{name} doit être un nombre strictement positif (reçu : {value!r})")


# -- formules et masses molaires
def parse_formula(formula: str) -> dict[str, int]:
    """Composition atomique d'une formule brute, parenthèses comprises : « Al2(SO4)3 » → {Al: 2, S: 3, O: 12}."""
    text = formula.replace(" ", "")
    if not text:
        raise ChemistryError("formule vide")
    position = 0
    stack: list[dict[str, int]] = [{}]
    last: tuple[str, Any] | None = None  # dernier élément ou groupe fermé, pour appliquer un indice
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match:
            raise ChemistryError(f"caractère inattendu dans « {formula} » : {text[position]!r}")
        element, number, paren = match.groups()
        position = match.end()
        if element:
            if element not in ATOMIC_MASS:
                raise ChemistryError(f"élément inconnu de la table : {element}")
            stack[-1][element] = stack[-1].get(element, 0) + 1
            last = ("element", element)
        elif number:
            count = int(number)
            if last is None or count == 0:
                raise ChemistryError(f"indice mal placé dans « {formula} »")
            if last[0] == "element":
                stack[-1][last[1]] += count - 1
            else:  # groupe entre parenthèses : déjà ajouté une fois, on ajoute le reste
                for name, amount in last[1].items():
                    stack[-1][name] += amount * (count - 1)
            last = None
        elif paren == "(":
            stack.append({})
            last = None
        else:
            if len(stack) == 1:
                raise ChemistryError(f"parenthèse fermante en trop dans « {formula} »")
            group = stack.pop()
            if not group:
                raise ChemistryError(f"parenthèses vides dans « {formula} »")
            for name, amount in group.items():
                stack[-1][name] = stack[-1].get(name, 0) + amount
            last = ("group", group)
    if len(stack) != 1:
        raise ChemistryError(f"parenthèse non fermée dans « {formula} »")
    return stack[0]


def molar_mass_g_mol(formula: str) -> float:
    return sum(ATOMIC_MASS[element] * count for element, count in parse_formula(formula).items())


def moles_from_mass(mass_g: float, formula: str) -> float:
    _positive(mass_g=mass_g)
    return mass_g / molar_mass_g_mol(formula)


def mass_g_from_moles(amount_mol: float, formula: str) -> float:
    _positive(amount_mol=amount_mol)
    return amount_mol * molar_mass_g_mol(formula)


def mass_fractions(formula: str) -> dict[str, float]:
    """Fraction massique de chaque élément dans le composé (la somme vaut 1)."""
    total = molar_mass_g_mol(formula)
    return {element: ATOMIC_MASS[element] * count / total for element, count in parse_formula(formula).items()}


# -- gaz parfait
def ideal_gas_volume_m3(amount_mol: float, temperature_k: float, pressure_pa: float) -> float:
    """V = n R T / P."""
    _positive(amount_mol=amount_mol, temperature_k=temperature_k, pressure_pa=pressure_pa)
    return amount_mol * R * temperature_k / pressure_pa


def ideal_gas_moles(pressure_pa: float, volume_m3: float, temperature_k: float) -> float:
    """n = P V / (R T)."""
    _positive(pressure_pa=pressure_pa, volume_m3=volume_m3, temperature_k=temperature_k)
    return pressure_pa * volume_m3 / (R * temperature_k)


def celsius_to_kelvin(temperature_c: float) -> float:
    kelvin = temperature_c + ZERO_CELSIUS_K
    if kelvin < 0:
        raise ChemistryError("température sous le zéro absolu")
    return kelvin


# -- bilans de matière
def mix_streams(streams: list[dict[str, Any]]) -> dict[str, Any]:
    """Mélangeur en régime permanent, sans réaction.

    Chaque courant : `{"flow_kg_h": débit, "fractions": {constituant: fraction massique}}`.
    Retourne le débit total et la composition de sortie ; chaque constituant est conservé.
    """
    if not streams:
        raise ChemistryError("aucun courant d'entrée")
    totals: dict[str, float] = {}
    flow = 0.0
    for index, stream in enumerate(streams, start=1):
        rate, fractions = stream.get("flow_kg_h"), stream.get("fractions")
        _positive(**{f"débit du courant {index}": rate})
        if not isinstance(fractions, dict) or not fractions:
            raise ChemistryError(f"courant {index} : fractions manquantes")
        if any(value < 0 for value in fractions.values()) or abs(sum(fractions.values()) - 1.0) > 1e-6:
            raise ChemistryError(f"courant {index} : les fractions massiques doivent être positives et sommer à 1")
        flow += rate
        for name, fraction in fractions.items():
            totals[name] = totals.get(name, 0.0) + rate * fraction
    return {"flow_kg_h": flow, "component_kg_h": totals, "fractions": {n: m / flow for n, m in totals.items()}}


def dilution_volume(c1: float, v1: float, c2: float) -> float:
    """Dilution C1 V1 = C2 V2 : volume final V2, dans l'unité de V1. C2 doit être inférieure ou égale à C1."""
    _positive(c1=c1, v1=v1, c2=c2)
    if c2 > c1:
        raise ChemistryError("une dilution ne peut pas augmenter la concentration (C2 > C1)")
    return c1 * v1 / c2


def balance_closure(inputs_kg_h: list[float], outputs_kg_h: list[float]) -> dict[str, float]:
    """Fermeture d'un bilan global : écart entre entrées et sorties, en kg/h et en pourcentage des entrées."""
    total_in, total_out = sum(inputs_kg_h), sum(outputs_kg_h)
    _positive(total_des_entrées=total_in)
    return {"in_kg_h": total_in, "out_kg_h": total_out, "gap_kg_h": total_in - total_out,
            "gap_percent": 100.0 * (total_in - total_out) / total_in}


# -- équilibres
def ph_strong_acid(concentration_mol_l: float) -> float:
    """pH d'un monoacide fort : −log10(C). Valable tant que C reste grand devant 10⁻⁷ mol/L."""
    _positive(concentration_mol_l=concentration_mol_l)
    return -math.log10(concentration_mol_l)


def ph_strong_base(concentration_mol_l: float, pkw: float = 14.0) -> float:
    """pH d'une monobase forte à 25 °C : pKe + log10(C)."""
    _positive(concentration_mol_l=concentration_mol_l)
    return pkw + math.log10(concentration_mol_l)


def ph_weak_acid(concentration_mol_l: float, ka: float) -> float:
    """pH d'un monoacide faible : résolution exacte de Ka = x² / (C − x), sans l'approximation x ≪ C."""
    _positive(concentration_mol_l=concentration_mol_l, ka=ka)
    h = (-ka + math.sqrt(ka ** 2 + 4.0 * ka * concentration_mol_l)) / 2.0
    return -math.log10(h)


def ph_buffer(pka: float, base_mol_l: float, acid_mol_l: float) -> float:
    """Équation de Henderson-Hasselbalch : pH = pKa + log10([base] / [acide])."""
    _positive(base_mol_l=base_mol_l, acid_mol_l=acid_mol_l)
    return pka + math.log10(base_mol_l / acid_mol_l)


def equilibrium_constant(delta_g_j_mol: float, temperature_k: float = 298.15) -> float:
    """K = exp(−ΔG° / (R T))."""
    _positive(temperature_k=temperature_k)
    return math.exp(-delta_g_j_mol / (R * temperature_k))
