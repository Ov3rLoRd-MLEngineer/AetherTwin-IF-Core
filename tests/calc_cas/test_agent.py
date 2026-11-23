"""calc_cas, intégration agent : définitions d'outils, appels structurés, boucle de délégation (modèle SIMULÉ),
serveur MCP stdio (protocole réel, dans un sous-processus)."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from modules.calc_cas import agent, mcp_server
from modules.calc_cas.worker import CasRunner

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def runner():
    r = CasRunner(timeout_s=20)
    yield r
    r.stop()


def test_tool_specs_are_valid_function_schemas() -> None:
    names = [s["function"]["name"] for s in agent.TOOL_SPECS]
    assert names == ["cas_compute", "cas_analyze_function", "cas_statistics"]
    for spec in agent.TOOL_SPECS:
        params = spec["function"]["parameters"]
        assert spec["type"] == "function" and params["type"] == "object"
        assert set(params["required"]) <= set(params["properties"]) and len(spec["function"]["description"]) > 40
    json.dumps(agent.TOOL_SPECS)


def test_compute_tool_returns_structured_output(runner: CasRunner) -> None:
    out = agent.call_tool(runner, "cas_compute", {"expression": "integrate(x^2, x, 0, 2)"})
    assert out["ok"] and out["tool"] == "cas_compute" and out["exact"] == "8/3" and out["approx"] == "2.66666666667"
    assert "mathml" not in out and "latex" in out  # sortie compacte pour un modèle


@pytest.mark.parametrize("name, args, fragment", [
    ("cas_compute", {}, "expression"), ("cas_compute", {"expression": "1/0"}, "zéro"),
    ("rm", {"x": 1}, "outil inconnu"), ("cas_compute", {"expression": "x.__class__"}, "refusée"),
    ("cas_analyze_function", {"expression": "x", "what": "aire"}, "Analyse inconnue"),
    ("cas_statistics", {"x": []}, "vide"),
])
def test_tool_errors_never_raise(runner: CasRunner, name: str, args: dict, fragment: str) -> None:
    out = agent.call_tool(runner, name, args)
    assert out["ok"] is False and fragment in out["error"]


def test_analyze_and_statistics_tools(runner: CasRunner) -> None:
    zeros = agent.call_tool(runner, "cas_analyze_function", {"expression": "x^2 - 2", "what": "zeros"})
    assert [p["x_exact"] for p in zeros["points"]] == ["-sqrt(2)", "sqrt(2)"]
    stats = agent.call_tool(runner, "cas_statistics", {"x": [1, 2, 3], "y": [2, 4, 6], "regression": "linear"})
    assert stats["coefficients"] == {"a": 2, "b": 0} or stats["coefficients"]["a"] == pytest.approx(2)
    desc = agent.call_tool(runner, "cas_statistics", {"x": [1, 2, 3]})
    assert desc["one_var"]["mean"] == 2


def test_agent_session_is_isolated_from_user(runner: CasRunner) -> None:
    runner.call("eval", text="z := 99")
    assert agent.call_tool(runner, "cas_compute", {"expression": "z + 1"})["exact"] == "z + 1"


def test_ask_loop_delegates_calculations(runner: CasRunner) -> None:
    """Modèle SIMULÉ : il demande deux calculs, puis répond avec les résultats reçus."""
    seen: list[list[dict]] = []

    def fake_llm(messages: list[dict]) -> str:
        seen.append(list(messages))
        if len(seen) == 1:
            return "Je calcule.\nCAS: solve(x^2 = 2x, x)\n`CAS: integrate(2x - x^2, x, 0, 2)`"
        return "L'aire vaut 4/3."

    result = agent.ask("Aire entre x^2 et 2x ?", fake_llm, runner)
    assert result["answer"] == "L'aire vaut 4/3."
    assert [c["expression"] for c in result["calls"]] == ["solve(x^2 = 2x, x)", "integrate(2x - x^2, x, 0, 2)"]
    assert result["calls"][1]["result"]["exact"] == "4/3"
    feedback = seen[1][-1]["content"]
    assert "integrate(2x - x^2, x, 0, 2) → 4/3 (≈ 1.33333333333)" in feedback and "[x = 0, x = 2]" in feedback
    assert seen[0][0]["role"] == "system" and "CAS:" in seen[0][0]["content"]


def test_ask_loop_is_bounded_and_reports_errors(runner: CasRunner) -> None:
    calls = []

    def stubborn(messages: list[dict]) -> str:
        calls.append(1)
        return "CAS: 1/0" if len(calls) <= agent.MAX_ROUNDS else "Impossible : division par zéro."

    result = agent.ask("1/0 ?", stubborn, runner)
    assert len(calls) == agent.MAX_ROUNDS + 1 and len(result["calls"]) == agent.MAX_ROUNDS
    assert result["answer"].startswith("Impossible") and not result["calls"][0]["result"]["ok"]
    with pytest.raises(ValueError):
        agent.ask("  ", stubborn, runner)


def test_mcp_handle_in_process(runner: CasRunner) -> None:
    init = mcp_server.handle(runner, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "2024-11-05"}})
    assert init["result"]["protocolVersion"] == "2024-11-05"
    assert mcp_server.handle(runner, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = mcp_server.handle(runner, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in tools} == agent.TOOL_NAMES and all("inputSchema" in t for t in tools)
    det = {"name": "cas_compute", "arguments": {"expression": "det([[1,2],[3,4]])"}}
    call = mcp_server.handle(runner, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": det})
    assert call["result"]["structuredContent"]["exact"] == "-2" and call["result"]["isError"] is False
    bad = mcp_server.handle(runner, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                     "params": {"name": "cas_compute", "arguments": {"expression": "2+*"}}})
    assert bad["result"]["isError"] is True
    assert mcp_server.handle(runner, {"jsonrpc": "2.0", "id": 5, "method": "nope"})["error"]["code"] == -32601
    out = io.StringIO()
    mcp_server.serve(io.StringIO("pas du json\n\n"), out, runner)
    assert json.loads(out.getvalue())["error"]["code"] == -32700


def test_mcp_server_subprocess_end_to_end() -> None:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "cas_compute", "arguments": {"expression": "limit(sin(x)/x, x, 0)"}}},
    ]
    stdin = "".join(json.dumps(r) + "\n" for r in requests)
    proc = subprocess.run([sys.executable, "-m", "modules.calc_cas.mcp_server"], input=stdin.encode("utf-8"),
                          capture_output=True, cwd=ROOT, timeout=120, check=False)
    lines = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
    assert [m["id"] for m in lines] == [1, 2], proc.stderr.decode("utf-8", "replace")
    assert lines[1]["result"]["structuredContent"]["exact"] == "1"
