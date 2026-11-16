"""Génère la partie automatique de ARCHITECTURE_MAP.md (arborescence + signatures publiques) via `ast`.

Le contenu est inséré entre les marqueurs AUTO:BEGIN / AUTO:END ; le reste du fichier
(flux de données, diagrammes) est rédigé à la main et n'est jamais touché.

    python scripts/gen_architecture_map.py          # met le fichier à jour
    python scripts/gen_architecture_map.py --check  # code 1 si le fichier est périmé
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "ARCHITECTURE_MAP.md"
BEGIN, END = "<!-- AUTO:BEGIN -->", "<!-- AUTO:END -->"
CODE_DIRS = ("core", "modules", "scripts")
TREE_DIRS = ("core", "modules", "scripts", "config", "tests", "docs", "research", "assets", "logs", ".github")
SKIP = {"__pycache__", ".venv", ".git", ".pytest_cache", ".ruff_cache"}


def first_line(doc: str | None) -> str:
    return doc.strip().splitlines()[0].strip() if doc and doc.strip() else ""


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix}{node.name}({ast.unparse(node.args)}){returns}"


def describe_module(path: Path) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [f"### `{rel}`", "", f"*Erreur de syntaxe : {exc.msg} (ligne {exc.lineno})*", ""]
    lines = [f"### `{rel}`", ""]
    summary = first_line(ast.get_docstring(tree))
    if summary:
        lines += [summary, ""]
    entries: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith("_"):
            entries.append(f"- `{signature(node)}`" + _doc_suffix(node))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            bases = f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else ""
            entries.append(f"- **`class {node.name}{bases}`**" + _doc_suffix(node))
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and not item.name.startswith("_"):
                    entries.append(f"  - `{signature(item)}`" + _doc_suffix(item))
    lines += entries or ["*(aucun symbole public)*"]
    lines.append("")
    return lines


def _doc_suffix(node: ast.AST) -> str:
    summary = first_line(ast.get_docstring(node))  # type: ignore[arg-type]
    return f" — {summary}" if summary else ""


def tree_lines() -> list[str]:
    out = ["```"]
    for name in TREE_DIRS:
        base = ROOT / name
        if not base.is_dir():
            continue
        out.append(f"{name}/")
        for path in sorted(base.rglob("*")):
            parts = path.relative_to(ROOT).parts
            if SKIP & set(parts) or path.name.endswith((".pyc", ".log", ".lock")) or "relay_state" in path.name:
                continue
            if path.is_file() and parts[0] == "logs" and path.name != "CHANGELOG_DEV.md":
                continue
            indent = "  " * (len(parts) - 1)
            out.append(f"{indent}{path.name}{'/' if path.is_dir() else ''}")
    out.append("```")
    return out


def generate() -> str:
    lines = ["## Arborescence (générée)", "", *tree_lines(), "", "## Signatures publiques (générées)", ""]
    for name in CODE_DIRS:
        for path in sorted((ROOT / name).rglob("*.py")) if (ROOT / name).is_dir() else []:
            if SKIP & set(path.parts) or (path.name == "__init__.py" and not path.read_text("utf-8").strip()):
                continue
            lines += describe_module(path)
    return "\n".join(lines).rstrip() + "\n"


def render(current: str) -> str:
    block = f"{BEGIN}\n{generate()}{END}"
    if BEGIN in current and END in current:
        head, rest = current.split(BEGIN, 1)
        return head + block + rest.split(END, 1)[1]
    return current.rstrip() + "\n\n" + block + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="échoue si ARCHITECTURE_MAP.md est périmé")
    args = parser.parse_args(argv)
    current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else "# ARCHITECTURE_MAP\n"
    updated = render(current)
    if args.check:
        if updated != current:
            print("ARCHITECTURE_MAP.md est périmé : lance scripts/gen_architecture_map.py", file=sys.stderr)
            return 1
        return 0
    if updated != current:
        TARGET.write_text(updated, encoding="utf-8", newline="\n")
        print("ARCHITECTURE_MAP.md mis à jour.")
    else:
        print("ARCHITECTURE_MAP.md déjà à jour.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
