"""
Relève les textes d'interface de WoW Assistant (français) pour le catalogue de traduction anglais.

Usage : python scripts/extract_ui_strings.py [--missing]
- sans option : écrit la liste complète (chaînes et modèles des f-strings, « {0} objets ») sur la sortie ;
- --missing : seulement ceux qui n'ont pas encore de traduction dans app/i18n_en.json.

Les modèles des f-strings remplacent chaque valeur par {0}, {1}... : c'est la clé du catalogue (voir i18n.py).
"""
import ast
import json
import pathlib
import re
import sys

APP = pathlib.Path(__file__).resolve().parents[1] / "modules" / "gaming_hud" / "app"
# textes envoyés seulement aux IA (Hermes, assistant) : pas d'interface à traduire
SKIP = {"hermes_mcp.py", "llm.py", "lua_parser.py", "i18n.py", "gameversion.py"}
MAX_LEN = 240


def _visible(s):
    s = s.strip()
    if len(s) < 2 or len(s) > MAX_LEN or not re.search(r"[A-Za-zÀ-ÿ]", s):
        return False
    if re.fullmatch(r"[a-z0-9_.:/\\-]+", s):             # clés, chemins, identifiants
        return False
    if re.match(r"(https?://|/data/|INVTYPE_|\.|#|%|\{)", s):
        return False
    return bool(re.search(r"[À-ÿ]", s) or " " in s or s[0].isupper())


def _template(node):
    parts, n = [], 0
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append(str(v.value).replace("{", "{{").replace("}", "}}"))
        else:
            parts.append("{" + str(n) + "}")
            n += 1
    return "".join(parts), n


def strings():
    found = {}
    for path in sorted(APP.glob("*.py")):
        if path.name in SKIP:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs, inner = set(), set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
            if isinstance(node, ast.JoinedStr):
                inner.update(id(v) for v in node.values)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                text, n = _template(node)
                literal = re.sub(r"\{\d+\}", "", text)
                if n and _visible(literal) and len(text) <= MAX_LEN:
                    found.setdefault(text, path.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs \
                    and id(node) not in inner and _visible(node.value):
                found.setdefault(node.value, path.name)
    return found


if __name__ == "__main__":
    catalog = {}
    if "--missing" in sys.argv:
        try:
            catalog = json.loads((APP / "i18n_en.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            catalog = {}
    out = {k: v for k, v in strings().items() if k not in catalog}
    sys.stdout.reconfigure(encoding="utf-8")
    json.dump(out, sys.stdout, ensure_ascii=False, indent=0)
