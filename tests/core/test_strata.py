"""Strata, moteur secondaire : faux serveur compatible OpenAI (HTTP réel sur 127.0.0.1), arbitrage VRAM avec Inoue
(Ollama déchargé avant Strata, gros modèle Ollama refusé tant que Strata tourne) et repli sur Ollama s'il est arrêté."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from core.guardians.inoue import Inoue
from core.hardware.gpu_monitor import GpuMonitor
from core.llm_router import LlmConfig, LlmError, LlmRefused, LlmRouter
from core.strata import StrataBackend, StrataConfig, StrataError, ollama_to_openai
from tests.core.test_llm_router import USER, FakeOllama, TwoGpus


class FakeStrata:
    """Imite /v1/models et /v1/chat/completions (réponse entière ou diffusée en SSE)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        handler = type("Handler", (_Handler,), {"fake": self})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.host = f"127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Handler(BaseHTTPRequestHandler):
    fake: FakeStrata

    def _send(self, status: int, body: dict, kind: str = "application/json") -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": "qwen36-moe", "object": "model"}]})
        else:
            self._send(404, {"error": "inconnu"})

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))) or b"{}")
        self.fake.calls.append(body)
        if self.path != "/v1/chat/completions" or body.get("model") != "qwen36-moe":
            self._send(404, {"error": "modèle inconnu"})
        elif body.get("stream"):
            chunks = [{"choices": [{"delta": {"content": w}}]} for w in ("Moi ", "aussi")]
            payload = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            raw = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        else:
            self._send(200, {"choices": [{"message": {"role": "assistant", "content": " réponse MoE "}}],
                             "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture
def ollama():
    fake = FakeOllama()
    yield fake
    fake.close()


@pytest.fixture
def strata():
    fake = FakeStrata()
    yield fake
    fake.close()


def make_router(ollama: FakeOllama, host: str, **strata_cfg: Any) -> LlmRouter:
    backend = StrataBackend(StrataConfig(enabled=True, host=host, **strata_cfg))
    return LlmRouter(Inoue(GpuMonitor(TwoGpus())), LlmConfig(host=ollama.host, default_model="gros-a:27b"),
                     strata=backend)


def closed_port() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    host = f"127.0.0.1:{server.server_address[1]}"
    server.server_close()
    return host


def test_config_defaults_and_local_only() -> None:
    cfg = StrataConfig.from_section({"enabled": True, "host": "127.0.0.1:8090", "preset": "AetherTwin", "vram_gb": 3})
    assert cfg.enabled and cfg.base_url == "http://127.0.0.1:8090" and cfg.preset == "AetherTwin" and cfg.vram_gb == 3
    assert not StrataConfig.from_section({}).enabled                           # section absente : désactivé
    remote = StrataBackend(StrataConfig(enabled=True, host="192.168.1.20:8090"))
    with pytest.raises(StrataError, match="127.0.0.1"):
        remote.models()


def test_state_reports_disabled_stopped_and_active(strata: FakeStrata) -> None:
    assert StrataBackend(StrataConfig()).state()["status"] == "désactivé"
    stopped = StrataBackend(StrataConfig(enabled=True, host=closed_port())).state()
    assert stopped["status"] == "non installé" and not stopped["reachable"] and stopped["error"]
    active = StrataBackend(StrataConfig(enabled=True, host=strata.host)).state()
    assert active["status"] == "actif" and active["models"] == ["strata/qwen36-moe"]


def test_ollama_is_unloaded_before_strata_answers(ollama: FakeOllama, strata: FakeStrata) -> None:
    router = make_router(ollama, strata.host)
    router.chat(USER, model="gros-b:30b")
    assert list(ollama.loaded) == ["gros-b:30b"]
    answer = router.chat(USER, model="strata/qwen36-moe", options={"temperature": 0.2})
    assert answer["content"] == "réponse MoE" and answer["model"] == "strata/qwen36-moe"
    assert answer["backend"] == "strata" and answer["completion_tokens"] == 3
    assert ollama.loaded == {} and ("/api/generate", {"model": "gros-b:30b", "keep_alive": 0}) in ollama.calls
    assert strata.calls[-1]["temperature"] == 0.2 and strata.calls[-1]["messages"] == USER
    assert router.inoue is not None and router.inoue.state()["loaded_llms"] == ["strata/qwen36-moe"]


def test_large_ollama_model_waits_while_strata_runs(ollama: FakeOllama, strata: FakeStrata) -> None:
    router = make_router(ollama, strata.host)
    router.chat(USER, model="strata/")                       # « strata/ » seul : le premier modèle servi
    with pytest.raises(LlmRefused, match="Strata occupe la VRAM"):
        router.chat(USER, model="gros-a:27b")
    assert router.chat(USER, model="petit-vision:7b")["content"]   # un petit modèle (vision) passe toujours
    strata.close()                                           # Strata arrêté : sa place est rendue
    assert router.chat(USER, model="gros-a:27b")["content"] == "réponse de gros-a:27b"
    assert router.inoue is not None and "strata/qwen36-moe" not in router.inoue.state()["loaded_llms"]


def test_stopped_strata_falls_back_to_ollama(ollama: FakeOllama) -> None:
    router = make_router(ollama, closed_port())
    answer = router.chat(USER, model="strata/qwen36-moe")
    assert answer["content"] == "réponse de gros-a:27b" and answer["fallback_from"] == "strata/qwen36-moe"
    assert "injoignable" in answer["fallback_reason"]
    assert "".join(router.chat_stream(USER, model="strata/qwen36-moe")) == "Bonjour Jérémy"
    strict = make_router(ollama, closed_port(), fallback_to_ollama=False)
    with pytest.raises(LlmError, match="injoignable"):
        strict.chat(USER, model="strata/qwen36-moe")
    disabled = LlmRouter(None, LlmConfig(host=ollama.host), strata=StrataBackend(StrataConfig()))
    with pytest.raises(LlmError, match="pas activé"):
        disabled.chat(USER, model="strata/x")


def test_stream_and_model_list(ollama: FakeOllama, strata: FakeStrata) -> None:
    router = make_router(ollama, strata.host)
    assert "".join(router.chat_stream(USER, model="strata/qwen36-moe")) == "Moi aussi"
    names = [m["name"] for m in router.list_models()]
    assert names[-1] == "strata/qwen36-moe" and "gros-a:27b" in names
    assert router.state()["strata"]["status"] == "actif"
    strata.close()
    assert all(not n.startswith("strata/") for n in (m["name"] for m in router.list_models()))
    assert router.state()["strata"]["status"] == "non installé" and router.state()["reachable"]


def test_images_are_sent_in_openai_format() -> None:
    out = ollama_to_openai([{"role": "user", "content": "que vois-tu ?", "images": ["QUJD"]}])
    assert out[0]["content"][0] == {"type": "text", "text": "que vois-tu ?"}
    assert out[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,QUJD"


def test_start_and_stop_use_the_installed_launcher(tmp_path: Path) -> None:
    launcher = tmp_path / "strata.cmd"
    launcher.write_text("@echo off\n", encoding="utf-8")
    seen: list[list[str]] = []

    class Proc:
        def poll(self) -> int | None:
            return None

    def spawner(args: list[str], **kwargs: Any) -> Proc:
        seen.append(args)
        assert kwargs["env"]["STRATA_DATA_DIR"] == str(tmp_path)
        return Proc()

    def runner(args: list[str], **_kwargs: Any) -> Any:
        seen.append(args)
        return type("Done", (), {"returncode": 0})()

    cfg = StrataConfig(enabled=True, host=closed_port(), launcher=str(launcher), data_dir=str(tmp_path),
                       preset="AetherTwin")
    backend = StrataBackend(cfg, spawner=spawner, runner=runner)
    assert backend.start()["started"] and backend.state()["status"] == "démarrage"
    assert backend.start()["started"] is False                 # un seul démarrage à la fois
    assert backend.stop() == {"stopped": True}
    assert seen[0][1:] == ["launch", "--preset", "AetherTwin", "--access", "local", "--yes", "--no-tui"]
    assert seen[1][1:] == ["launch", "--stop", "--preset", "AetherTwin"]
    with pytest.raises(StrataError, match="pas installé"):
        StrataBackend(StrataConfig(enabled=True, preset="x")).start()


def test_api_lists_strata_models_and_drives_it(ollama: FakeOllama, strata: FakeStrata, tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from core.api import create_app
    from core.daemon import Daemon

    daemon = Daemon(tmp_path / "modules", monitor=GpuMonitor(TwoGpus()), process_names=lambda: set())
    daemon.llm = make_router(ollama, strata.host)
    daemon.llm.inoue = daemon.inoue
    daemon.start()
    try:
        client = TestClient(create_app(daemon))
        data = client.get("/v1/models").json()["data"]
        assert {"id": "strata/qwen36-moe", "object": "model", "owned_by": "strata"} in data
        done = client.post("/v1/chat/completions", json={"model": "strata/qwen36-moe", "messages": USER}).json()
        assert done["choices"][0]["message"]["content"] == "réponse MoE"
        assert client.get("/health").json()["llm"]["strata"]["status"] == "actif"
        assert client.post("/strata/start").status_code == 503          # pas de lanceur configuré
        daemon.llm.strata = StrataBackend(StrataConfig())
        assert client.post("/strata/stop").status_code == 404           # désactivé
    finally:
        daemon.stop()
