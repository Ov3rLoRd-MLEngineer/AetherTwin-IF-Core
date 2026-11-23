"""Le CAS comme outil des agents locaux : un modèle délègue un calcul exact au lieu de l'inventer.

Trois portes, mêmes outils (`TOOL_SPECS`, schémas JSON au format « function calling » d'Ollama / OpenAI) :

1. Bus du Hub : `module.calc_cas.cmd.tool {"name": "cas_compute", "arguments": {"expression": "…"}}`.
2. Serveur MCP stdio (`python -m modules.calc_cas.mcp_server`) pour Hermes Agent ou tout client MCP local.
3. `ask()` : boucle de délégation par le modèle du Hub (`/v1/chat/completions`), sans dépendre du support des
   « tools » par le modèle : il écrit `CAS: <expression>`, le code calcule et lui rend le résultat.

Les sorties sont structurées (`ok`, `exact`, `approx`, `latex`, `error`). Les agents ont leur propre session :
ils ne voient ni ne modifient les variables de l'utilisateur.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

AGENT_SESSION = "agent"
MAX_ROUNDS = 4
MAX_CALLS_PER_ROUND = 6

TOOL_SPECS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "cas_compute",
        "description": (
            "Moteur de calcul formel exact (SymPy, local). À utiliser pour TOUT calcul au lieu de le faire de tête : "
            "arithmétique exacte, simplify/expand/factor, diff(f, x), integrate(f, x) ou integrate(f, x, a, b), "
            "limit(f, x, a), solve(équation, x) ou solve([éq1, éq2], [x, y]), sum(terme, k, a, b), "
            "det/inv/eigenvals sur [[1, 2], [3, 4]], nombres complexes (i), approx(expr, chiffres). "
            "Syntaxe : ^ pour la puissance, = pour une équation, pi, e, i, oo (infini). "
            "Renvoie le résultat exact et sa valeur approchée."),
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "Expression à calculer, ex. « integrate(x^2*exp(x), x) »"},
        }, "required": ["expression"]},
    }},
    {"type": "function", "function": {
        "name": "cas_analyze_function",
        "description": ("Étudie une fonction de x sur un intervalle : zéros, extrema (minimum/maximum) ou points "
                        "d'intersection avec une autre fonction. Valeurs numériques + forme exacte quand elle se "
                        "vérifie."),
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "Fonction de x, ex. « x^3 - 3x »"},
            "what": {"type": "string", "enum": ["zeros", "extrema", "intersections"]},
            "other": {"type": "string", "description": "Seconde fonction (pour « intersections »)"},
            "xmin": {"type": "number", "default": -10}, "xmax": {"type": "number", "default": 10},
        }, "required": ["expression", "what"]},
    }},
    {"type": "function", "function": {
        "name": "cas_statistics",
        "description": ("Statistiques d'une série (moyenne, écart type, quartiles…) ; avec y, statistiques à deux "
                        "variables et régression (linear, quadratic, cubic, exponential, power, logarithmic)."),
        "parameters": {"type": "object", "properties": {
            "x": {"type": "array", "items": {"type": "number"}},
            "y": {"type": "array", "items": {"type": "number"}},
            "regression": {"type": "string",
                           "enum": ["linear", "quadratic", "cubic", "exponential", "power", "logarithmic"]},
        }, "required": ["x"]},
    }},
]
TOOL_NAMES = frozenset(spec["function"]["name"] for spec in TOOL_SPECS)


def _clean(result: Any) -> Any:
    """Retire ce qui n'intéresse pas un modèle (MathML, durées) pour garder une réponse compacte."""
    if isinstance(result, dict):
        return {k: _clean(v) for k, v in result.items()
                if not k.endswith("mathml") and k not in ("elapsed_ms", "approx_latex") and v is not None}
    if isinstance(result, list):
        return [_clean(v) for v in result]
    return result


def call_tool(runner: Any, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Exécute un outil. Ne lève jamais : toute erreur devient `{"ok": False, "error": …}`."""
    args = arguments if isinstance(arguments, dict) else {}
    try:
        if name not in TOOL_NAMES:
            raise ValueError(f"outil inconnu : {name!r} (outils : {', '.join(sorted(TOOL_NAMES))})")
        if name == "cas_compute":
            expression = args.get("expression")
            if not isinstance(expression, str) or not expression.strip():
                raise ValueError("argument `expression` (texte) obligatoire")
            result = runner.call("eval", text=expression, session=AGENT_SESSION)
        elif name == "cas_analyze_function":
            result = runner.call("analyze", session=AGENT_SESSION, expr=str(args.get("expression", "")),
                                 what=str(args.get("what", "zeros")), other=str(args.get("other", "")),
                                 xmin=float(args.get("xmin", -10)), xmax=float(args.get("xmax", 10)))
        else:
            payload = {"x": args.get("x"), "y": args.get("y")}
            if args.get("regression"):
                result = runner.call("regress", session=AGENT_SESSION, model=str(args["regression"]), **payload)
            else:
                result = runner.call("stats", session=AGENT_SESSION, **payload)
    except (ValueError, TypeError, RuntimeError) as exc:
        return {"ok": False, "tool": name, "error": str(exc)}
    out = _clean(result) if isinstance(result, dict) else {"ok": True, "result": result}
    return {"tool": name, **out}


# ---------------------------------------------------------------- délégation par le modèle du Hub
SYSTEM_PROMPT = (
    "Tu es un assistant de mathématiques. Tu disposes d'un moteur de calcul formel EXACT. Ne fais jamais un "
    "calcul de tête : pour chaque calcul, écris une ligne qui commence par « CAS: » suivie de l'expression, et "
    "rien d'autre dans ce message. Exemples :\n"
    "CAS: integrate(x^2*exp(x), x)\nCAS: solve(x^2 - 5x + 6 = 0, x)\nCAS: det([[1, 2], [3, 4]])\n"
    "Syntaxe : ^ pour la puissance, = pour une équation, pi, e, i, oo ; fonctions simplify, expand, factor, "
    "diff, integrate (avec bornes : integrate(f, x, a, b)), limit(f, x, a), solve, sum(terme, k, a, b), det, inv, "
    "eigenvals, approx. Quand tu as reçu les résultats, réponds en français, en t'appuyant uniquement sur eux, "
    "sans ligne « CAS: »."
)
CAS_LINE = re.compile(r"^\s*(?:`{0,3})\s*CAS\s*:\s*(.+?)\s*`*\s*$", re.M)


def _summary(expression: str, result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"{expression} → ERREUR : {result.get('error')}"
    text = f"{expression} → {result.get('exact')}"
    if result.get("approx"):
        text += f" (≈ {result['approx']})"
    if result.get("warning"):
        text += f" [{result['warning']}]"
    return text


def ask(question: str, llm: Callable[[list[dict[str, str]]], str], runner: Any,
        max_rounds: int = MAX_ROUNDS) -> dict[str, Any]:
    """Pose une question au modèle local ; chaque ligne `CAS:` est calculée par le moteur et rendue au modèle."""
    question = str(question).strip()
    if not question:
        raise ValueError("question vide")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question[:4000]}]
    calls: list[dict[str, Any]] = []
    for _ in range(max_rounds):
        reply = llm(messages)
        expressions = CAS_LINE.findall(reply)[:MAX_CALLS_PER_ROUND]
        if not expressions:
            return {"answer": reply.strip(), "calls": calls}
        lines = []
        for expression in expressions:
            result = call_tool(runner, "cas_compute", {"expression": expression})
            calls.append({"expression": expression, "result": result})
            lines.append(_summary(expression, result))
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "Résultats du moteur de calcul (exacts) :\n" + "\n".join(lines)
                      + "\nRéponds maintenant à la question, ou demande d'autres calculs avec « CAS: »."}]
    messages.append({"role": "user", "content": "Réponds maintenant avec les résultats obtenus, sans « CAS: »."})
    return {"answer": llm(messages).strip(), "calls": calls}
