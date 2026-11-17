"""Le module scantrad dans son vrai processus, piloté par le démon (sans modèle : détection et effacement)."""
from __future__ import annotations

from pathlib import Path

from core.daemon import REPO_ROOT, Daemon
from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
from core.llm_router import LlmRouter
from tests.core.test_daemon import ollama_stopped, wait_for

PAGE = Path(__file__).resolve().parents[1] / "data" / "scantrad" / "page_test.png"


def test_scantrad_module_translates_on_command(tmp_path: Path) -> None:
    daemon = Daemon(REPO_ROOT / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    daemon.start()
    try:
        assert daemon.activate("scantrad").verdict.value == "accordé"
        assert wait_for(lambda: daemon.modules["scantrad"].last_health.get("ok") is True)
        out = tmp_path / "sortie.png"
        reply = daemon.command("scantrad", "page", {"input": str(PAGE), "output": str(out), "no_llm": True},
                               timeout_s=60)
        assert reply["ok"] is True, reply
        assert reply["result"]["metrics"]["bubbles"] == 5 and out.is_file()
        missing = daemon.command("scantrad", "page", {"input": str(tmp_path / "absente.png")}, timeout_s=30)
        assert missing["ok"] is False and "introuvable" in missing["error"]
    finally:
        daemon.stop()
