"""L'explorateur de données comme outil des agents locaux (bus du Hub et serveur MCP `aethertwin_donnees`).

Un modèle lit et écrit des classeurs, évalue des formules et lance ajustements et simulations : les nombres viennent
du moteur du tableur, pas de l'imagination du modèle. Les classeurs sont ceux de l'explorateur
(`data/data_lab/workbooks`) : on les voit aussitôt dans la fenêtre (bouton « Recharger »).
Les outils ne lèvent jamais : erreur → {"ok": False, "error": …}.
"""
from __future__ import annotations

from typing import Any

from modules.data_lab import analysis
from modules.data_lab.formula import Raise, Sheet, display, parse_formula, range_cells
from modules.data_lab.workbooks import Store, clean_cells, table_to_cells

S = {"type": "string"}
NUM = {"type": "number"}
BOOK = {"type": "string", "description": "Nom du classeur de l'explorateur (voir data_list_workbooks)."}
CELLS = {"type": "object", "description": "{\"A1\": \"valeur ou =formule\"} ; formules : SOMME, MOYENNE, SI, "
                                          "RESOUDRE(\"x^2-2\";1)… arguments séparés par « ; »."}


def _spec(name: str, description: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": props, "required": required}}}


TOOL_SPECS: list[dict[str, Any]] = [
    _spec("data_list_workbooks", "Liste les classeurs de l'explorateur de données d'AetherTwin.", {}, []),
    _spec("data_read_workbook", "Lit un classeur : contenu brut (formules) et valeurs calculées, sur une plage "
          "facultative (« A1:D20 »).", {"name": BOOK, "range": S}, ["name"]),
    _spec("data_write_cells", "Écrit des cellules dans un classeur (créé s'il n'existe pas) ; une valeur vide efface. "
          "Renvoie les valeurs recalculées des cellules écrites.", {"name": BOOK, "cells": CELLS}, ["name", "cells"]),
    _spec("data_write_table", "Écrit un tableau (liste de lignes) à partir d'une cellule (A1 par défaut).",
          {"name": BOOK, "rows": {"type": "array", "items": {"type": "array"}}, "origin": S}, ["name", "rows"]),
    _spec("data_evaluate", "Évalue une formule de tableur (« =MOYENNE(B2:B40) », « =RESOUDRE(\"x^3-x-1\";1) ») dans "
          "le contexte d'un classeur facultatif.", {"formula": S, "name": BOOK}, ["formula"]),
    _spec("data_fit", "Ajuste une courbe sur deux plages d'un classeur (lineaire, polynome, exponentiel, puissance, "
          "logarithme) : équation, coefficients, R².",
          {"name": BOOK, "x_range": S, "y_range": S, "model": {"type": "string", "enum": list(analysis.MODELS)},
           "degree": {"type": "integer"}}, ["name", "x_range", "y_range"]),
    _spec("data_sweep", "Balayage : fait varier une cellule d'entrée de start à stop (steps valeurs) et relève les "
          "cellules de sortie recalculées.",
          {"name": BOOK, "input": S, "start": NUM, "stop": NUM, "steps": {"type": "integer"},
           "outputs": {"type": "array", "items": S}}, ["name", "input", "start", "stop", "steps", "outputs"]),
    _spec("data_monte_carlo", "Simulation de Monte-Carlo : inputs = {cellule: {law: normale|uniforme|triangulaire|"
          "lognormale|exponentielle, a, b, c}} ; résume la distribution des sorties (moyenne, écart type, centiles).",
          {"name": BOOK, "inputs": {"type": "object"}, "outputs": {"type": "array", "items": S},
           "runs": {"type": "integer"}, "threshold": NUM, "seed": {"type": "integer"}}, ["name", "outputs"]),
    _spec("data_goal_seek", "Valeur cible : trouve la valeur de la cellule d'entrée qui donne `value` dans la "
          "cellule cible.", {"name": BOOK, "target": S, "value": NUM, "input": S},
          ["name", "target", "value", "input"]),
]


def _book_cells(store: Store, name: Any) -> dict[str, Any]:
    return store.load(name)["cells"] if name else {}


def call_tool(store: Store, name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        book = args.get("name")
        if name == "data_list_workbooks":
            result: Any = store.list()
        elif name == "data_read_workbook":
            cells = _book_cells(store, book)
            sheet = Sheet(cells)
            refs = range_cells(str(args["range"]).upper().replace("$", "")) if args.get("range") else sorted(cells)
            result = {"cells": {r: {"raw": cells.get(r, ""), "value": display(sheet.value(r))}
                                for r in refs if r in cells}}
        elif name in ("data_write_cells", "data_write_table"):
            try:
                cells = store.load(book)["cells"]
            except ValueError:
                cells = {}
            new = clean_cells(args.get("cells") or {}) if name == "data_write_cells" else \
                table_to_cells(list(args.get("rows") or []), str(args.get("origin") or "A1"))
            for k, v in (args.get("cells") or {}).items() if name == "data_write_cells" else []:
                if v in (None, ""):
                    cells.pop(str(k).upper(), None)
            cells.update(new)
            store.save(book, cells)
            sheet = Sheet(cells)
            result = {"name": book, "written": {r: display(sheet.value(r)) for r in new}}
        elif name == "data_evaluate":
            node = parse_formula(str(args.get("formula", "")))
            try:
                value = Sheet(_book_cells(store, book)).eval(node, None)
            except Raise as stop:
                value = stop.err
            result = {"value": display(value[0] if isinstance(value, list) and value else value)}
        elif name == "data_fit":
            result = analysis.fit(_book_cells(store, book), args["x_range"], args["y_range"],
                                  str(args.get("model") or "lineaire"), int(args.get("degree") or 2))
            result.pop("curve", None)
        elif name == "data_sweep":
            result = analysis.sweep(_book_cells(store, book), args["input"], args["start"], args["stop"],
                                    args["steps"], args["outputs"])
        elif name == "data_monte_carlo":
            result = analysis.monte_carlo(_book_cells(store, book), args.get("inputs") or {}, args["outputs"],
                                          int(args.get("runs") or 5000), args.get("seed"), args.get("threshold"))
            for out in result["outputs"].values():
                out.pop("histogram", None)
        elif name == "data_goal_seek":
            result = analysis.goal_seek(_book_cells(store, book), args["target"], args["value"], args["input"])
        else:
            return {"ok": False, "error": f"outil inconnu : {name}"}
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
        return {"ok": False, "error": str(exc) or type(exc).__name__}
    except Exception as exc:  # noqa: BLE001 — une erreur du moteur (ex. Raise) ne doit pas casser le serveur
        return {"ok": False, "error": str(exc) or type(exc).__name__}
    return {"ok": True, "result": result}
