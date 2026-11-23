"""calc_cas, processus de calcul : délai maximal (un calcul pathologique ne bloque rien), relance, rejeu des
définitions, sessions séparées utilisateur / agent."""
from __future__ import annotations

import time

import pytest

from modules.calc_cas.worker import CasRunner


@pytest.fixture(scope="module")
def runner():
    r = CasRunner(timeout_s=20)
    yield r
    r.stop()


def test_eval_through_worker(runner: CasRunner) -> None:
    result = runner.call("eval", text="integrate(x^2, x)")
    assert result["ok"] and result["exact"] == "x**3/3" and "elapsed_ms" in result


def test_timeout_kills_and_restarts_with_definitions(runner: CasRunner) -> None:
    assert runner.call("eval", text="k := 7")["ok"]
    assert runner.call("eval", text="h(x) := k*x")["ok"]
    before = runner.restarts
    started = time.monotonic()
    result = runner.call("eval", text="9^9^9", timeout_s=1.0)  # des minutes de calcul : interrompu
    assert time.monotonic() - started < 10
    assert result == {"ok": False, "timeout": True, "error": result["error"]} and "Délai dépassé" in result["error"]
    assert runner.restarts == before + 1
    # le moteur relancé répond, avec les définitions rejouées
    assert runner.call("eval", text="h(2)")["exact"] == "14"


def test_sessions_are_separate(runner: CasRunner) -> None:
    runner.call("eval", text="secret := 42")
    assert runner.call("eval", text="secret", session="agent")["exact"] == "secret"
    assert runner.call("eval", text="secret")["exact"] == "42"
    assert runner.definitions["user"]["secret"] == "secret := 42"
    assert "secret" not in runner.definitions.get("agent", {})


def test_vars_delete_reset(runner: CasRunner) -> None:
    runner.call("eval", text="w := 2", session="t")
    assert [v["name"] for v in runner.call("vars", session="t")] == ["w"]
    assert runner.call("delete", name="w", session="t") is True
    assert runner.call("vars", session="t") == []
    runner.call("eval", text="w := 3", session="t")
    assert runner.call("reset", target="t") is True
    assert runner.call("vars", session="t") == []


def test_unknown_operation_raises_value_error(runner: CasRunner) -> None:
    with pytest.raises(ValueError, match="opération inconnue"):
        runner.call("rm_rf")
    assert runner.call("ping") == "pong"  # le processus a survécu
