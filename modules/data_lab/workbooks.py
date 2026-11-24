"""Classeurs de l'explorateur : enregistrement local (JSON), import CSV et Excel (.xlsx), export CSV.

Un classeur = {"cells": {"A1": "texte ou =formule"}, "widths": {…}, "charts": […]} dans
`data/data_lab/workbooks/<nom>.json`. L'import .xlsx lit la première feuille avec la bibliothèque standard
(zip + XML) : valeurs, textes partagés et formules (les noms anglais des fonctions sont compris).
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET  # noqa: S405 — fichiers de l'utilisateur, entités externes non résolues

from modules.data_lab.formula import MAX_COLS, MAX_ROWS, Sheet, SheetError, display, parse_ref, ref_name

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path("data") / "data_lab"
NAME = re.compile(r"[\w][\w .\-]{0,59}")
MAX_IMPORT = 20_000_000
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def clean_name(name: Any) -> str:
    text = str(name or "").strip()
    if not NAME.fullmatch(text) or text.startswith("."):
        raise SheetError("nom de classeur : lettres, chiffres, espaces, « _ », « - », « . » (60 au plus)")
    return text


def clean_cells(cells: Any) -> dict[str, str]:
    if not isinstance(cells, dict):
        raise SheetError("cellules : objet {\"A1\": …} attendu")
    out = {}
    for k, v in cells.items():
        c, r = parse_ref(str(k))
        if v is None or v == "":
            continue
        out[ref_name(c, r)] = v if isinstance(v, str) else display(v)
    return out


class Store:
    def __init__(self, root: Path) -> None:
        self.folder = root / "workbooks"

    def path(self, name: Any) -> Path:
        return self.folder / f"{clean_name(name)}.json"

    def list(self) -> list[dict[str, Any]]:
        if not self.folder.is_dir():
            return []
        out = []
        for p in sorted(self.folder.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
            try:
                cells = json.loads(p.read_text(encoding="utf-8")).get("cells", {})
            except (OSError, ValueError):
                continue
            out.append({"name": p.stem, "cells": len(cells),
                        "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
        return out

    def load(self, name: Any) -> dict[str, Any]:
        p = self.path(name)
        if not p.is_file():
            raise SheetError(f"classeur introuvable : {name}")
        book = json.loads(p.read_text(encoding="utf-8"))
        book["name"] = p.stem
        return book

    def save(self, name: Any, cells: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        p = self.path(name)
        book = {"cells": clean_cells(cells), **{k: v for k, v in (extra or {}).items() if k in ("widths", "charts")}}
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(book, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(p)
        return {"name": p.stem, "cells": len(book["cells"])}

    def delete(self, name: Any) -> dict[str, Any]:
        p = self.path(name)
        if not p.is_file():
            raise SheetError(f"classeur introuvable : {name}")
        p.unlink()
        return {"name": p.stem, "deleted": True}


def table_to_cells(rows: list[list[Any]], origin: str = "A1") -> dict[str, str]:
    c0, r0 = parse_ref(origin)
    cells = {}
    for i, row in enumerate(rows):
        if r0 + i >= MAX_ROWS:
            break
        for j, v in enumerate(row):
            if c0 + j >= MAX_COLS:
                break
            if v not in (None, ""):
                cells[ref_name(c0 + j, r0 + i)] = v if isinstance(v, str) else display(v)
    return cells


def import_csv(data: bytes) -> dict[str, str]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:5000]
    delim = max((";", ",", "\t"), key=sample.count)
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return table_to_cells(rows)


def _xlsx_ref(ref: str) -> tuple[int, int]:
    return parse_ref(ref)


def import_xlsx(data: bytes) -> dict[str, str]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SheetError("fichier Excel illisible (.xlsx attendu ; un vieux .xls doit être réenregistré)") from None
    with zf:
        names = set(zf.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))  # noqa: S314
            for si in root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in names:
            sheets = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
            if not sheets:
                raise SheetError("aucune feuille dans ce classeur Excel")
            sheet_name = sheets[0]
        info = zf.getinfo(sheet_name)
        if info.file_size > MAX_IMPORT * 5:
            raise SheetError("feuille Excel trop grosse")
        root = ET.fromstring(zf.read(sheet_name))  # noqa: S314
    cells: dict[str, str] = {}
    for c in root.iter(f"{{{NS['m']}}}c"):
        ref = c.get("r", "")
        try:
            col, row = _xlsx_ref(ref)
        except SheetError:
            continue
        f = c.find("m:f", NS)
        v = c.find("m:v", NS)
        kind = c.get("t", "")
        if f is not None and f.text:
            cells[ref_name(col, row)] = "=" + f.text   # « , » sépare aussi les arguments ici
        elif kind == "s" and v is not None:
            cells[ref_name(col, row)] = shared[int(v.text or 0)]
        elif kind == "inlineStr":
            cells[ref_name(col, row)] = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
        elif kind == "b" and v is not None:
            cells[ref_name(col, row)] = "VRAI" if v.text == "1" else "FAUX"
        elif v is not None and v.text is not None:
            cells[ref_name(col, row)] = v.text
    return cells


def import_file(filename: str, data: bytes) -> dict[str, str]:
    if len(data) > MAX_IMPORT:
        raise SheetError("fichier trop gros (20 Mo au plus)")
    low = filename.lower()
    if low.endswith(".xlsx") or low.endswith(".xlsm"):
        return import_xlsx(data)
    if low.endswith((".csv", ".tsv", ".txt")):
        return import_csv(data)
    raise SheetError("format accepté : .csv, .tsv, .txt ou .xlsx")


def export_csv(cells: dict[str, Any], separator: str = ";") -> str:
    sheet = Sheet(cells)
    vals = sheet.values()
    if not vals:
        return ""
    coords = [parse_ref(k) for k in vals]
    max_c, max_r = max(c for c, _ in coords), max(r for _, r in coords)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=separator, lineterminator="\r\n")
    for r in range(max_r + 1):
        row = []
        for c in range(max_c + 1):
            text = display(vals.get(ref_name(c, r)))
            if separator == ";" and isinstance(vals.get(ref_name(c, r)), float):
                text = text.replace(".", ",")
            row.append(text)
        w.writerow(row)
    return buf.getvalue()
