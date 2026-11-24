"""Le labo de chimie comme outil des agents locaux (bus du Hub et serveur MCP `aethertwin_chimie`).

Les calculs sont exacts et déterministes : un modèle délègue ici masses molaires, équilibrages, pH et titrages au
lieu de les estimer. Les outils ne lèvent jamais : erreur → {"ok": False, "error": …}.
"""
from __future__ import annotations

from typing import Any

from modules.chem_lab import chemistry, elements, solutions

NUM = {"type": "number"}
KIND = {"type": "string", "enum": list(solutions.KINDS), "description": "Nature : " + " ; ".join(
    f"{k} = {v}" for k, v in solutions.KINDS.items())}


def _spec(name: str, description: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": props, "required": required}}}


TOOL_SPECS: list[dict[str, Any]] = [
    _spec("chem_element", "Fiche d'un élément du tableau périodique (symbole, numéro atomique ou nom français) : "
          "masse atomique, groupe, période, famille, électronégativité, état à 20 °C.",
          {"element": {"type": "string", "description": "« Fe », « 26 » ou « fer »."}}, ["element"]),
    _spec("chem_molar_mass", "Masse molaire exacte (g/mol) et composition massique d'une formule chimique. "
          "Parenthèses, crochets et hydrates acceptés : « Ca(OH)2 », « CuSO4·5H2O ».",
          {"formula": {"type": "string"}}, ["formula"]),
    _spec("chem_balance", "Équilibre une équation chimique (coefficients entiers minimaux, charges comprises). "
          "Exemple : « MnO4^- + Fe^2+ + H^+ -> Mn^2+ + Fe^3+ + H2O ».",
          {"equation": {"type": "string"}}, ["equation"]),
    _spec("chem_stoichiometry", "Stœchiométrie : réactif limitant, avancement, masses consommées et formées. "
          "quantities = {réactif: {mass_g} ou {mol} ou {volume_L, concentration}} ; les autres réactifs sont en excès.",
          {"equation": {"type": "string"}, "quantities": {"type": "object"},
           "yield_percent": {"type": "number", "description": "Rendement réel en %, 100 par défaut."}},
          ["equation", "quantities"]),
    _spec("chem_ph", "pH exact d'une solution d'acide ou de base dans l'eau à 25 °C (sans approximation).",
          {"kind": KIND, "concentration": {"type": "number", "description": "mol/L"},
           "pka": {"type": "number", "description": "pKa du couple (acide ou base faible)."}},
          ["kind", "concentration"]),
    _spec("chem_buffer", "pH exact d'un tampon HA/A⁻ (concentrations en mol/L) comparé à Henderson-Hasselbalch.",
          {"acid": NUM, "base": NUM, "pka": NUM}, ["acid", "base", "pka"]),
    _spec("chem_titration", "Simule un titrage acido-basique (acide par NaOH ou base par HCl) : courbe pH = f(V), "
          "volume et pH à l'équivalence, demi-équivalence, indicateurs colorés adaptés.",
          {"analyte": KIND, "c_analyte": {"type": "number", "description": "mol/L"},
           "v_analyte_ml": {"type": "number"}, "c_titrant": {"type": "number", "description": "mol/L"},
           "pka": NUM, "points": {"type": "integer", "description": "points de la courbe (41 par défaut ici)."}},
          ["analyte", "c_analyte", "v_analyte_ml", "c_titrant"]),
    _spec("chem_dilution", "C1·V1 = C2·V2 : donne trois grandeurs sur quatre, la quatrième est calculée.",
          {"c1": NUM, "v1": NUM, "c2": NUM, "v2": NUM}, []),
    _spec("chem_preparation", "Masse de solide à peser pour préparer un volume de solution à une concentration.",
          {"formula": {"type": "string"}, "concentration": {"type": "number", "description": "mol/L"},
           "volume_L": NUM, "purity_percent": NUM}, ["formula", "concentration", "volume_L"]),
]


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "chem_element":
            result: Any = elements.element(args.get("element"))
        elif name == "chem_molar_mass":
            result = chemistry.molar_mass(str(args.get("formula", "")))
        elif name == "chem_balance":
            result = chemistry.balance(str(args.get("equation", "")))
        elif name == "chem_stoichiometry":
            result = chemistry.stoichiometry(str(args.get("equation", "")), dict(args.get("quantities") or {}),
                                             float(args.get("yield_percent") or 100))
        elif name == "chem_ph":
            result = solutions.solution_ph(str(args.get("kind")), args.get("concentration"), args.get("pka"))
        elif name == "chem_buffer":
            result = solutions.buffer_ph(args.get("acid"), args.get("base"), float(args.get("pka")))
        elif name == "chem_titration":
            result = solutions.titration(str(args.get("analyte")), args.get("c_analyte"), args.get("v_analyte_ml"),
                                         args.get("c_titrant"), args.get("pka"), points=int(args.get("points") or 41))
            result = {k: v for k, v in result.items() if k != "all_indicators"}
        elif name == "chem_dilution":
            result = solutions.dilution(args.get("c1"), args.get("v1"), args.get("c2"), args.get("v2"))
        elif name == "chem_preparation":
            result = solutions.preparation(str(args.get("formula", "")), args.get("concentration"),
                                           args.get("volume_L"), float(args.get("purity_percent") or 100))
        else:
            return {"ok": False, "error": f"outil inconnu : {name}"}
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        return {"ok": False, "error": str(exc) or type(exc).__name__}
    return {"ok": True, "result": result}
