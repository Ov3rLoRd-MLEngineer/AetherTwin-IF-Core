"""Labo de chimie : tableau périodique, formules, équilibrage, stœchiométrie, pH, titrages, MCP."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from modules.chem_lab import agent, chemistry, elements, solutions
from modules.chem_lab.mcp_server import SERVER
from modules.chem_lab.module import ChemLabModule


def test_periodic_table_complete():
    assert len(elements.ELEMENTS) == 118
    assert [e["z"] for e in elements.ELEMENTS] == list(range(1, 119))
    assert elements.element("fer")["symbol"] == "Fe"
    assert elements.element("26")["name"] == "Fer"
    assert elements.element("Og")["period"] == 7
    assert sum(e["category"] == "la" for e in elements.ELEMENTS) == 15
    assert sum(e["category"] == "ac" for e in elements.ELEMENTS) == 15
    assert elements.element("Br")["state"] == "liquide" and elements.element("Ne")["state"] == "gaz"
    with pytest.raises(ValueError):
        elements.element("Xx")


@pytest.mark.parametrize("formula, mass", [
    ("H2O", 18.015), ("CuSO4·5H2O", 249.677), ("K4[Fe(CN)6]", 368.345), ("Ca(OH)2", 74.092),
    ("Al2(SO4)3", 342.131), ("C6H12O6", 180.156),
])
def test_molar_mass(formula, mass):
    assert chemistry.molar_mass(formula)["molar_mass"] == pytest.approx(mass, abs=0.002)


@pytest.mark.parametrize("bad", ["H2O)", "(H2O", "Xy2", "H2O$", ""])
def test_bad_formulas(bad):
    with pytest.raises(ValueError):
        chemistry.molar_mass(bad)


@pytest.mark.parametrize("equation, expected", [
    ("H2 + O2 -> H2O", "2 H2 + O2 → 2 H2O"),
    ("C3H8 + O2 -> CO2 + H2O", "C3H8 + 5 O2 → 3 CO2 + 4 H2O"),
    ("Fe + O2 = Fe2O3", "4 Fe + 3 O2 → 2 Fe2O3"),
    ("KMnO4 + HCl -> KCl + MnCl2 + H2O + Cl2", "2 KMnO4 + 16 HCl → 2 KCl + 2 MnCl2 + 8 H2O + 5 Cl2"),
    ("MnO4^- + Fe^2+ + H^+ -> Mn^2+ + Fe^3+ + H2O", "MnO4^- + 5 Fe^2+ + 8 H^+ → Mn^2+ + 5 Fe^3+ + 4 H2O"),
    ("Cu(aq) + 2 Ag^+(aq) → Cu^2+(aq) + Ag(s)", "Cu(aq) + 2 Ag^+(aq) → Cu^2+(aq) + 2 Ag(s)"),
])
def test_balance(equation, expected):
    assert chemistry.balance(equation)["balanced"] == expected


@pytest.mark.parametrize("equation", ["H2 + O2", "H2 -> O2", "H2 + O2 -> H2O + H2O2", "NaCl -> Na + Cl + K"])
def test_balance_refuses(equation):
    with pytest.raises(ValueError):
        chemistry.balance(equation)


def test_stoichiometry_limiting_reagent():
    r = chemistry.stoichiometry("CH4 + O2 -> CO2 + H2O", {"CH4": {"mass_g": 16.043}, "O2": {"mol": 1}})
    assert r["limiting"] == "O2" and r["extent_max_mol"] == pytest.approx(0.5)
    co2 = next(p for p in r["products"] if p["species"] == "CO2")
    assert co2["formed_g"] == pytest.approx(22.0045, abs=1e-3)
    ch4 = next(x for x in r["reactants"] if x["species"] == "CH4")
    assert ch4["left_mol"] == pytest.approx(0.5, abs=1e-4)
    half = chemistry.stoichiometry("CH4 + O2 -> CO2 + H2O", {"O2": {"mol": 1}}, yield_percent=50)
    assert half["extent_mol"] == pytest.approx(0.25)
    with pytest.raises(ValueError):
        chemistry.stoichiometry("CH4 + O2 -> CO2 + H2O", {"CO2": {"mol": 1}})


@pytest.mark.parametrize("kind, c, pka, ph", [
    ("acide_fort", 0.1, None, 1.0), ("acide_fort", 1e-8, None, 6.98), ("base_forte", 0.01, None, 12.0),
    ("acide_faible", 0.1, 4.76, 2.88), ("base_faible", 0.1, 9.25, 11.12),
])
def test_ph(kind, c, pka, ph):
    assert solutions.solution_ph(kind, c, pka)["ph"] == pytest.approx(ph, abs=0.01)


def test_buffer_and_dilution_and_preparation():
    assert solutions.buffer_ph(0.1, 0.1, 4.76)["ph"] == pytest.approx(4.76, abs=0.01)
    r = solutions.dilution(c1=1, c2=0.1, v2=500)
    assert r["found"] == "v1" and r["v1"] == pytest.approx(50)
    with pytest.raises(ValueError):
        solutions.dilution(c1=0.1, v1=10, c2=1)
    with pytest.raises(ValueError):
        solutions.dilution(c1=1)
    assert solutions.preparation("NaCl", 0.5, 0.25)["mass_g"] == pytest.approx(7.305, abs=1e-3)


def test_titration_weak_acid():
    t = solutions.titration("acide_faible", 0.1, 20, 0.1, 4.76)
    assert t["v_eq_ml"] == pytest.approx(20) and t["ph_eq"] == pytest.approx(8.72, abs=0.02)
    assert t["ph_half"] == pytest.approx(4.76, abs=0.01)
    assert "phénolphtaléine" in t["indicators"] and "hélianthine (méthylorange)" not in t["indicators"]
    phs = [p for _v, p in t["curve"]]
    assert all(b >= a - 1e-9 for a, b in zip(phs, phs[1:], strict=False))   # la courbe monte toujours


def test_titration_bases_go_down():
    t = solutions.titration("base_faible", 0.1, 20, 0.1, 9.25)
    phs = [p for _v, p in t["curve"]]
    assert phs[0] > 11 and phs[-1] < 2 and t["ph_eq"] == pytest.approx(5.27, abs=0.03)
    assert solutions.titration("base_forte", 0.05, 10, 0.1)["v_eq_ml"] == pytest.approx(5)


def test_agent_tools_never_raise():
    assert agent.call_tool("chem_balance", {"equation": "H2 + O2 -> H2O"})["result"]["balanced"] == "2 H2 + O2 → 2 H2O"
    assert agent.call_tool("chem_balance", {"equation": "n'importe quoi"})["ok"] is False
    assert agent.call_tool("chem_ph", {"kind": "acide_faible", "concentration": 0.1})["ok"] is False
    assert agent.call_tool("nope", {})["ok"] is False
    t = agent.call_tool("chem_titration", {"analyte": "acide_fort", "c_analyte": 0.1, "v_analyte_ml": 10,
                                           "c_titrant": 0.1})
    assert t["ok"] and len(t["result"]["curve"]) == 41


def test_mcp_server_roundtrip():
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
             {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
             {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "chem_molar_mass", "arguments": {"formula": "H2O"}}}]
    out = io.StringIO()
    SERVER.serve(io.StringIO("\n".join(json.dumps(x) for x in lines) + "\n"), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert {t["name"] for t in replies[1]["result"]["tools"]} >= {"chem_balance", "chem_titration"}
    assert replies[2]["result"]["structuredContent"]["result"]["molar_mass"] == pytest.approx(18.015)


def test_module_commands():
    m = ChemLabModule.__new__(ChemLabModule)
    assert len(m.run("elements", {})["elements"]) == 118
    assert m.run("balance", {"equation": "Na + Cl2 -> NaCl"})["balanced"] == "2 Na + Cl2 → 2 NaCl"
    with pytest.raises(ValueError):
        m.run("inconnue", {})


def test_page_wired():
    root = Path(__file__).resolve().parents[2]
    html = (root / "core/web/dashboard.html").read_text(encoding="utf-8")
    assert 'data-sub="Labo de chimie"' in html and "labs_tool.js" in html
    page = (root / "core/web/chem_app.html").read_text(encoding="utf-8")
    assert "style=" not in page and "<script>" not in page   # CSP : ni style ni script en ligne
