"""Explorateur de données : moteur de formules, simulations, ajustements, classeurs, imports, MCP."""
from __future__ import annotations

import base64
import io
import json
import math
import zipfile
from pathlib import Path

import pytest

from modules.data_lab import analysis, formula
from modules.data_lab.agent import call_tool
from modules.data_lab.formula import Sheet
from modules.data_lab.mcp_server import make_server
from modules.data_lab.module import DataLabModule, recalc
from modules.data_lab.workbooks import Store, export_csv, import_csv, import_xlsx


def val(cells, ref):
    return Sheet(cells).value(ref)


@pytest.mark.parametrize("text, expected", [
    ("=1+2*3", 7.0), ("=(1+2)*3", 9.0), ("=2^3^2", 512.0), ("=-2^2", -4.0), ("=10%", 0.1), ("=7/2", 3.5),
    ("=SOMME(1;2;3)", 6.0), ("=SUM(1,2,3)", 6.0), ("=MOYENNE(2;4)", 3.0), ("=ARRONDI(2.345;2)", 2.35),
    ("=ARRONDI(-2.5;0)", -3.0), ("=SI(3>2;\"oui\";\"non\")", "oui"), ("=\"a\"&1&VRAI", "a1VRAI"),
    ("=ET(VRAI;1>0)", True), ("=NON(FAUX)", True), ("=MOD(-7;3)", 2.0), ("=LOG(8;2)", 3.0), ("=ENT(-1.5)", -2.0),
    ("=PI()", math.pi), ("=MAJUSCULE(\"é\")", "É"), ("=SIERREUR(1/0;42)", 42.0),
])
def test_formula_values(text, expected):
    v = val({"A1": text}, "A1")
    assert v == pytest.approx(expected) if isinstance(expected, float) else v == expected


def test_references_ranges_and_values():
    cells = {"A1": "1", "A2": "2,5", "A3": "texte", "A4": "", "B1": "=SOMME(A1:A4)", "B2": "=NB(A1:A4)",
             "B3": "=NBVAL(A1:A4)", "B4": "=$A$1+A$2", "B5": "=A3*2", "C1": "50%", "C2": "1 234,5"}
    s = Sheet(cells)
    assert s.value("B1") == 3.5 and s.value("B2") == 2.0 and s.value("B3") == 3.0 and s.value("B4") == 3.5
    assert s.value("B5") == formula.VALUE
    assert s.value("C1") == 0.5 and s.value("C2") == 1234.5


@pytest.mark.parametrize("text, code", [
    ("=1/0", "#DIV/0!"), ("=FOO(1)", "#NOM?"), ("=RACINE(-1)", "#NUM!"), ("=(1+", "#FORMULE!"),
    ("=PENTE(A1:A2;A1:A3)", "#N/A"),
])
def test_errors(text, code):
    assert str(val({"A1": "1", "A2": "2", "A3": "3", "B1": text}, "B1")) == code


def test_cycles_and_error_propagation():
    s = Sheet({"A1": "=B1+1", "B1": "=A1", "C1": "=A1*2", "D1": "=1/0", "E1": "=D1+1"})
    assert s.value("A1") == formula.CYCLE and s.value("C1") == formula.CYCLE
    assert s.value("E1") == formula.DIV0


def test_equation_functions():
    cells = {"A1": "2", "B1": '=RESOUDRE("x^2-A1";1)', "B2": '=DERIVEE("x^3";2)', "B3": '=INTEGRALE("x^2";0;3)',
             "B4": '=RESOUDRE("x^2+1";0)', "B5": '=SOLVE("COS(x)-x";1)'}
    s = Sheet(cells)
    assert s.value("B1") == pytest.approx(math.sqrt(2), abs=1e-10)
    assert s.value("B2") == pytest.approx(12, abs=1e-6)
    assert s.value("B3") == pytest.approx(9, abs=1e-9)
    assert s.value("B4") == formula.NUM
    assert s.value("B5") == pytest.approx(0.7390851332, abs=1e-9)


def test_statistics_functions():
    cells = {f"A{i}": str(i) for i in range(1, 6)}
    cells.update({f"B{i}": str(2 * i + 1) for i in range(1, 6)})
    cells.update({"C1": "=PENTE(B1:B5;A1:A5)", "C2": "=ORDONNEE.ORIGINE(B1:B5;A1:A5)", "C3": "=CORREL(A1:A5;B1:B5)",
                  "C4": "=ECARTYPE(A1:A5)", "C5": "=MEDIANE(A1:A5)", "C6": '=NB.SI(A1:A5;">2")',
                  "C7": '=SOMME.SI(A1:A5;">=4";B1:B5)', "C8": "=PREVISION(10;B1:B5;A1:A5)",
                  "C9": "=SOMMEPROD(A1:A5;B1:B5)"})
    s = Sheet(cells)
    assert (s.value("C1"), s.value("C2"), s.value("C3")) == pytest.approx((2, 1, 1))
    assert s.value("C4") == pytest.approx(1.5811388) and s.value("C5") == 3
    assert s.value("C6") == 3 and s.value("C7") == 20 and s.value("C8") == pytest.approx(21) and s.value("C9") == 125


def test_random_is_reproducible_with_seed():
    import random

    a = Sheet({"A1": "=ALEA()"}, rng=random.Random(3)).value("A1")  # noqa: S311
    b = Sheet({"A1": "=ALEA()"}, rng=random.Random(3)).value("A1")  # noqa: S311
    assert a == b and 0 <= a < 1


LOAN = {"B1": "200000", "B2": "3,5%", "B3": "25", "B5": "=B1*(B2/12)/(1-(1+B2/12)^(-B3*12))", "B6": "=B5*B3*12-B1"}


def test_sweep_and_two_way_table():
    r = analysis.sweep(LOAN, "B3", 10, 30, 3, ["B5", "B6"])
    assert r["x"] == [10, 20, 30] and r["series"]["B5"][0] > r["series"]["B5"][2]
    grid = analysis.sweep(LOAN, "B3", 10, 30, 3, ["B5"], "B2", 0.02, 0.05, 4)
    assert len(grid["grid"]) == 4 and len(grid["grid"][0]) == 3
    with pytest.raises(ValueError):
        analysis.sweep(LOAN, "B5", 0, 1, 3, ["B6"])   # une formule ne peut pas être une entrée


def test_monte_carlo_and_goal_seek():
    r = analysis.monte_carlo(LOAN, {"B2": {"law": "normale", "a": 0.035, "b": 0.005}}, ["B6"], 2000, seed=7,
                             threshold=120000)
    o = r["outputs"]["B6"]
    assert 95000 < o["mean"] < 106000 and o["p5"] < o["median"] < o["p95"] and 0 < r["above"]["B6"] < 0.3
    assert sum(o["histogram"]["counts"]) == 2000
    g = analysis.goal_seek(LOAN, "B5", 900, "B1")
    assert g["reached"] == pytest.approx(900, abs=1e-6) and 179000 < g["value"] < 181000
    with pytest.raises(ValueError):
        analysis.monte_carlo(LOAN, {"B2": {"law": "inconnue"}}, ["B6"], 10)


def test_fit_models():
    xs = {f"A{i}": str(i) for i in range(1, 11)}
    quad = {**xs, **{f"B{i}": str(3 * i * i + 2) for i in range(1, 11)}}
    f = analysis.fit(quad, "A1:A10", "B1:B10", "polynome", 2)
    assert f["r2"] == pytest.approx(1) and f["coefficients"]["c2"] == pytest.approx(3) and "x^1" not in f["formula"]
    expo = {**xs, **{f"B{i}": str(2 * math.exp(0.3 * i)) for i in range(1, 11)}}
    e = analysis.fit(expo, "A1:A10", "B1:B10", "exponentiel")
    assert e["coefficients"]["a"] == pytest.approx(2) and e["coefficients"]["b"] == pytest.approx(0.3)
    cell = e["formula"].replace("{x}", "A3")
    assert Sheet({**expo, "C3": cell}).value("C3") == pytest.approx(2 * math.exp(0.9))
    lin = analysis.fit({**xs, **{f"B{i}": str(5 - i) for i in range(1, 11)}}, "A1:A10", "B1:B10")
    assert lin["equation"] == "y = -1·x + 5"
    with pytest.raises(ValueError):
        analysis.fit({**xs, "B1": "-1", "B2": "2"}, "A1:A2", "B1:B2", "exponentiel")


def test_sort_and_describe():
    cells = {"A1": "nom", "A2": "c", "A3": "a", "A4": "b", "B2": "3", "B3": "1", "B4": "2"}
    out = analysis.sort_range(cells, "A1:B4", "B", header=True)["cells"]
    assert [out["A2"], out["A3"], out["A4"]] == ["a", "b", "c"]
    with pytest.raises(ValueError):
        analysis.sort_range({**cells, "B2": "=1"}, "A1:B4", "B")
    d = analysis.describe(cells, "B1:B4")
    assert d["n"] == 3 and d["mean"] == 2 and d["text_or_empty"] == 1


def test_store_and_imports(tmp_path):
    store = Store(tmp_path)
    store.save("essai 1", {"a1": "1", "B2": "=A1*2", "C3": ""})
    assert store.load("essai 1")["cells"] == {"A1": "1", "B2": "=A1*2"}
    assert store.list()[0]["name"] == "essai 1"
    for bad in ("../x", "", ".cache", "a/b"):
        with pytest.raises(ValueError):
            store.save(bad, {})
    assert import_csv(b"x;y\n1,5;2\n")["A2"] == "1,5"
    assert import_csv(b"x,y\n1,2\n")["B2"] == "2"
    csv_text = export_csv({"A1": "x", "A2": "=1/4"})
    assert csv_text.splitlines() == ["x", "0,25"]


def make_xlsx() -> bytes:
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>2.5</v></c></row>'
             '<row r="2"><c r="A2"><f>SUM(B1,3)</f><v>5.5</v></c><c r="B2" t="b"><v>1</v></c></row>'
             '</sheetData></worksheet>')
    shared = ('<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Titre</t></si></sst>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
        zf.writestr("xl/sharedStrings.xml", shared)
    return buf.getvalue()


def test_xlsx_import_keeps_formulas():
    cells = import_xlsx(make_xlsx())
    assert cells == {"A1": "Titre", "B1": "2.5", "A2": "=SUM(B1,3)", "B2": "VRAI"}
    assert Sheet(cells).value("A2") == 5.5
    with pytest.raises(ValueError):
        import_xlsx(b"pas un zip")


def test_module_commands(tmp_path):
    m = DataLabModule.__new__(DataLabModule)
    m.store = Store(tmp_path)
    r = m.run("recalc", {"cells": {"A1": "2", "A2": "=A1*3", "A3": "=1/0", "A4": "x"}})["values"]
    assert r["A2"] == ["6", "n"] and r["A3"] == ["#DIV/0!", "e"] and r["A4"] == ["x", "t"]
    data = base64.b64encode(b"a;b\n1;2\n").decode()
    assert m.run("import", {"filename": "t.csv", "data": data})["cells"]["B2"] == "2"
    assert "RESOUDRE" in m.run("functions", {}) and "SOMME" in m.run("functions", {})
    assert recalc({})["values"] == {}
    with pytest.raises(ValueError):
        m.run("inconnue", {})


def test_agent_tools_and_mcp(tmp_path):
    store = Store(tmp_path)
    w = call_tool(store, "data_write_table", {"name": "mesures", "rows": [["x", "y"], [1, 2], [2, 4], [3, 6]]})
    assert w["ok"], w
    call_tool(store, "data_write_cells", {"name": "mesures", "cells": {"C2": "=B2/A2"}})
    read = call_tool(store, "data_read_workbook", {"name": "mesures", "range": "A1:C2"})["result"]["cells"]
    assert read["C2"] == {"raw": "=B2/A2", "value": "2"}
    assert call_tool(store, "data_evaluate", {"formula": "=SOMME(B2:B4)", "name": "mesures"})["result"]["value"] == "12"
    assert call_tool(store, "data_evaluate", {"formula": "=1/0"})["result"]["value"] == "#DIV/0!"
    fit = call_tool(store, "data_fit", {"name": "mesures", "x_range": "A2:A4", "y_range": "B2:B4"})["result"]
    assert fit["coefficients"]["a"] == pytest.approx(2)
    assert call_tool(store, "data_read_workbook", {"name": "absent"})["ok"] is False
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "data_list_workbooks", "arguments": {}}}]
    out = io.StringIO()
    make_server(store).serve(io.StringIO("\n".join(json.dumps(x) for x in lines) + "\n"), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert len(replies[0]["result"]["tools"]) >= 9
    assert replies[1]["result"]["structuredContent"]["result"][0]["name"] == "mesures"


def test_page_wired():
    root = Path(__file__).resolve().parents[2]
    html = (root / "core/web/dashboard.html").read_text(encoding="utf-8")
    assert 'data-sub="Explorateur de données"' in html
    page = (root / "core/web/data_app.html").read_text(encoding="utf-8")
    assert "style=" not in page and "<script>" not in page
