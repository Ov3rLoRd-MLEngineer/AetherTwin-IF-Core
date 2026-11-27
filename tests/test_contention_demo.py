"""Scénario de contention : le script s'importe et s'explique sans GPU ni PyTorch."""
from __future__ import annotations

import pytest

from scripts import contention_demo


def test_help_works_without_pytorch(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        contention_demo.main(["--help"])
    assert exc.value.code == 0 and "--occupant-gb" in capsys.readouterr().out
