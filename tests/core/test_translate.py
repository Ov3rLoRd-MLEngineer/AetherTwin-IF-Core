"""Traduction générale vers le français : détection de la langue, texte, image, voix (sans modèle réel)."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from core import translate
from core.daemon import Daemon
from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
from core.llm_router import LlmRouter
from tests.core.test_daemon import ollama_stopped


class FakeChat:
    """Faux routeur : lit une image (« AUCUN » si on le lui demande), traduit en préfixant « FR: »."""

    def __init__(self, seen_text: str = "こんにちは") -> None:
        self.calls: list[dict] = []
        self.seen_text = seen_text

    def __call__(self, messages, model=None, num_ctx=None, think=None, options=None):
        self.calls.append({"messages": messages, "model": model, "num_ctx": num_ctx})
        if "images" in messages[-1]:
            return {"content": self.seen_text, "model": model}
        return {"content": f"<think>…</think>FR: {messages[-1]['content']}", "model": "qwen3-27b", "seconds": 1.0}


@pytest.mark.parametrize("text, code", [("안녕하세요", "ko"), ("こんにちは世界", "ja"), ("你好世界", "zh"),
                                        ("Hello there", "en"), ("漢字とかな", "ja")])
def test_language_is_detected_from_the_script(text: str, code: str) -> None:
    assert translate.detect_language(text) == code


def test_unknown_script_is_refused() -> None:
    with pytest.raises(ValueError):
        translate.detect_language("Привет")


def test_text_translation_names_the_language_and_strips_thinking() -> None:
    chat = FakeChat()
    reply = translate.translate_text(chat, "  안녕하세요  ")
    assert reply["lang"] == "ko" and reply["translation"] == "FR: 안녕하세요"
    assert "coréen vers le français" in chat.calls[0]["messages"][0]["content"]
    with pytest.raises(ValueError):
        translate.translate_text(chat, "   ")
    with pytest.raises(ValueError):
        translate.translate_text(chat, "x" * (translate.MAX_TEXT + 1))


def png(width: int = 3000, height: int = 2000) -> bytes:
    return cv2.imencode(".png", np.full((height, width, 3), 255, np.uint8))[1].tobytes()


def test_image_is_read_by_the_vision_model_after_shrinking() -> None:
    chat = FakeChat()
    assert translate.read_image(chat, png(), "ja") == "こんにちは"
    call = chat.calls[0]
    assert call["model"] == "qwen2.5vl:7b" and "japonais" in call["messages"][0]["content"]
    data = cv2.imdecode(np.frombuffer(__import__("base64").b64decode(call["messages"][0]["images"][0]), np.uint8),
                        cv2.IMREAD_COLOR)
    assert data.shape[0] * data.shape[1] <= 1_310_000  # réduite (6 Mpx au départ)
    with pytest.raises(ValueError, match="aucun texte"):
        translate.read_image(FakeChat("AUCUN"), png(), "auto")
    with pytest.raises(ValueError, match="illisible"):
        translate.read_image(chat, b"pas une image")


def test_voice_without_faster_whisper_says_how_to_install(monkeypatch) -> None:
    monkeypatch.setattr(translate, "voice_available", lambda: False)
    with pytest.raises(RuntimeError, match="setup.ps1 -Voice"):
        translate.transcribe(b"audio")


def test_translation_routes(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from core.api import create_app

    (tmp_path / "modules").mkdir()
    daemon = Daemon(tmp_path / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    chat = FakeChat()
    monkeypatch.setattr(daemon.llm, "chat", chat)
    client = TestClient(create_app(daemon))
    reply = client.post("/translate/text", json={"text": "Hello", "lang": "auto"}).json()
    assert reply["lang"] == "en" and reply["translation"] == "FR: Hello"
    assert client.post("/translate/text", json={"text": ""}).status_code == 400
    assert client.post("/translate/text", json={"text": "hi", "lang": "de"}).status_code == 400
    image = client.post("/translate/image?lang=ja", content=png(400, 300), headers={"Content-Type": "image/png"})
    assert image.status_code == 200 and image.json()["translation"] == "FR: こんにちは"
    assert client.post("/translate/image", content=b"MZ", headers={"Content-Type": "text/plain"}).status_code == 415
    monkeypatch.setattr(translate, "voice_available", lambda: False)
    assert client.get("/translate/voice").json() == {"available": False}
    assert client.post("/translate/voice", content=b"audio").status_code == 503
