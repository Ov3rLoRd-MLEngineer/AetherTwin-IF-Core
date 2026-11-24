"""voice : effets, profils, texte prononçable, installateur (sources fixes, archive sûre), commandes du module,
outils des agents, serveur MCP, analyse multipart de l'API. Aucun téléchargement ni moteur réel requis."""
from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from core.api import audio_suffix, multipart_fields
from core.module_api import load_manifest
from modules.voice import agent, effects, engines, installer, mcp_server
from modules.voice.module import VoiceModule
from modules.voice.profiles import ProfileStore, validate

ROOT = Path(__file__).resolve().parents[2]


def tone(seconds: float = 0.5, rate: int = 22050, freq: float = 220.0) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    return effects.write_wav((0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32), rate)


class FakeEngine:
    name = "piper"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def synthesize(self, text: str, voice: str, speed: float = 1.0, speaker: int = 0, timeout: float = 120) -> bytes:
        self.calls.append((text, voice, speed, speaker))
        return tone()


def make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None) -> tuple[VoiceModule, FakeEngine]:
    module = VoiceModule(load_manifest(ROOT / "modules" / "voice"), {"data_dir": str(tmp_path / "voice")})
    module.start()
    fake = FakeEngine()
    if monkeypatch is not None:
        monkeypatch.setattr(module.service, "_engine_for", lambda profile: (fake, str(profile.get("voice", "")), ""))
    return module, fake


# ---------- effets ----------
def test_effects_bounded_and_length() -> None:
    assert effects.clean({"pitch": 99, "gain": -99, "inconnu": 3})["pitch"] == 12
    with pytest.raises(ValueError):
        effects.clean({"robot": "beaucoup"})
    samples, rate = effects.read_wav(tone(1.0))
    for key in ("pitch", "bass", "treble", "robot", "radio", "tremolo"):
        out = effects.apply(samples, rate, {key: 6 if key in ("pitch", "bass", "treble") else 0.8})
        assert abs(len(out) - len(samples)) < rate * 0.1, key  # la durée ne change pas
        assert np.max(np.abs(out)) <= 0.99 + 1e-6
    assert len(effects.apply(samples, rate, {"echo": 0.5})) > len(samples)  # traîne de l'écho
    assert effects.apply_wav(tone(), {}) == tone()  # neutre : WAV rendu tel quel


def test_pitch_shift_moves_frequency() -> None:
    samples, rate = effects.read_wav(tone(1.0, freq=220.0))
    out = effects.pitch_shift(samples, 12, rate)
    spectrum = np.abs(np.fft.rfft(out[rate // 4: rate // 4 + 8192]))
    peak = np.argmax(spectrum) * rate / 8192
    assert 400 < peak < 480  # une octave plus haut


# ---------- texte ----------
def test_clean_text_and_sentences() -> None:
    text = "Voici **AetherTwin** : ```print(1)``` voir https://exemple.org. Æther répond ! Fin"
    clean = engines.clean_text(text)
    assert "print" not in clean and "http" not in clean and "*" not in clean
    assert "Éther Twinne" in clean and "Éther répond" in clean
    assert engines.sentences("Un. Deux ! Trois ? ...") == ["Un.", "Deux !", "Trois ?"]


# ---------- profils ----------
def test_profiles_store(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles.json")
    state = store.all()
    assert state["default"] == "aether" and state["mic"] == "ma_voix"
    assert {p["kind"] for p in state["profiles"]} == {"synthese", "micro"}
    saved = store.save({"id": "Grave", "kind": "synthese", "engine": "piper", "voice": "fr_FR-gilles-low",
                        "speed": 9, "effects": {"pitch": -30, "robot": 0}})
    assert saved["id"] == "grave" and saved["speed"] == 2.0 and saved["effects"] == {"pitch": -12.0}
    store.save({"id": "aether", "kind": "synthese", "voice": "fr_FR-upmc-medium"})  # remplace un intégré
    assert store.get("aether")["voice"] == "fr_FR-upmc-medium" and not store.get("aether")["builtin"]
    assert store.settings({"default": "grave", "speak_replies": True})["default"] == "grave"
    with pytest.raises(ValueError):
        store.settings({"default": "ma_voix"})  # un profil de micro ne lit pas les réponses
    assert store.delete("grave") and not store.delete("robot")  # intégré : rien à supprimer
    assert store.all()["default"] == "aether"  # profil disparu : retour au défaut
    for bad in ({"id": "../x"}, {"id": "ok", "kind": "autre"}, {"id": "ok", "engine": "cloud"}, "texte"):
        with pytest.raises(ValueError):
            validate(bad)


# ---------- installateur ----------
def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_installer_sources_and_zip(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        installer.fetch("https://exemple.org/piper.zip")
    with pytest.raises(ValueError):
        installer.extract_zip(make_zip({"../evade.txt": b"x"}), tmp_path / "cible")
    assert not (tmp_path / "evade.txt").exists()

    asked: list[str] = []

    def fetcher(url: str) -> bytes:
        asked.append(url)
        assert url.startswith(installer.ALLOWED_HOSTS)
        if url == installer.PIPER_URL:
            return make_zip({"piper/piper.exe": b"MZ", "piper/espeak-ng-data/fr_dict": b""})
        return b"{}" if url.endswith(".json") else b"onnx"

    result = installer.install(tmp_path / "piper", ["fr_FR-gilles-low", "inconnue"], fetcher)
    assert result["added"] == ["piper", "fr_FR-gilles-low"] and result["piper"]
    assert result["voices"]["fr_FR-gilles-low"] and not result["voices"]["fr_FR-siwis-medium"]
    assert installer.install(tmp_path / "piper", ["fr_FR-gilles-low"], fetcher)["added"] == []  # rien à refaire
    assert all("/v1.0.0/" in u for u in asked if "piper-voices" in u)


# ---------- module ----------
def test_module_speak_and_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, fake = make(tmp_path, monkeypatch)
    assert module.run("profiles", {})["default"] == "aether"
    out = module.run("speak", {"text": "Bonjour **toi**", "profile": "fuma"})
    assert fake.calls[-1][1] == "fr_FR-siwis-medium" and fake.calls[-1][2] == 1.1  # voix et vitesse du profil
    wav = base64.b64decode(out["audio"])
    assert out["profile"] == "fuma" and out["duration"] > 0.4 and wav[:4] == b"RIFF"
    filed = module.run("speak", {"text": "Salut", "file": True})
    path = module.service.tmp_path(filed["file"])
    assert path.is_file() and "audio" not in filed
    with pytest.raises(ValueError):
        module.run("speak", {"text": "Salut", "profile": "ma_voix"})  # profil de micro
    with pytest.raises(ValueError):
        module.run("speak", {"text": "```code```"})  # rien de prononçable
    with pytest.raises(ValueError):
        module.service.tmp_path("../../config.yaml")
    module.run("profile_save", {"profile": {"id": "moi", "kind": "micro", "effects": {"pitch": -3}}})
    assert module.run("settings", {"mic": "moi"})["mic"] == "moi"
    changed = base64.b64decode(module.run("effects", {"audio": base64.b64encode(tone()).decode(),
                                                      "effects": {"robot": 1}})["audio"])
    assert changed != tone() and changed[:4] == b"RIFF"
    with pytest.raises(ValueError):
        module.run("inconnue", {})
    assert module.run("vbcable", {})["url"] == "https://vb-audio.com/Cable/"


def test_module_fallback_to_windows_voice(tmp_path: Path) -> None:
    module, _ = make(tmp_path)  # Piper absent du dossier temporaire
    engine, voice, note = module.service._engine_for(module.service.profiles.get("aether"))
    if module.service.sapi.available():
        assert engine.name == "sapi" and note
    health = module.health()
    assert health.ok


def test_agent_tools_and_mcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = make(tmp_path, monkeypatch)
    played: list[bytes] = []
    monkeypatch.setattr(module.service, "play", played.append)
    names = {s["function"]["name"] for s in module.run("tools", {})}
    assert names == agent.TOOL_NAMES
    said = module.run("tool", {"name": "voice_speak", "arguments": {"text": "Coucou", "effects": {"radio": 1}}})
    assert said["ok"] and played and said["seconds_of_audio"] > 0
    assert module.run("tool", {"name": "voice_set_default", "arguments": {"profile": "robot"}})["default"] == "robot"
    assert not module.run("tool", {"name": "voice_set_default", "arguments": {"profile": "ma_voix"}})["ok"]
    assert not module.run("tool", {"name": "rm_rf", "arguments": {}})["ok"]

    reply = mcp_server.handle(module.service, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                               "params": {"protocolVersion": "2025-06-18"}})
    assert reply["result"]["serverInfo"]["name"] == "aethertwin-voice"
    listed = mcp_server.handle(module.service, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert {t["name"] for t in listed["result"]["tools"]} == agent.TOOL_NAMES
    called = mcp_server.handle(module.service, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                                "params": {"name": "voice_profiles", "arguments": {}}})
    assert not called["result"]["isError"] and json.loads(called["result"]["content"][0]["text"])["ok"]
    assert mcp_server.handle(module.service, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


# ---------- API ----------
def test_api_multipart_parsing() -> None:
    boundary = "----aether"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"rec.webm\"\r\n"
            f"Content-Type: audio/webm\r\n\r\n").encode() + b"\x1aE\xdf\xa3binaire\r\n" + (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\nfr\r\n--{boundary}--\r\n").encode()
    fields = multipart_fields(f"multipart/form-data; boundary={boundary}", body)
    assert fields["file"] == (b"\x1aE\xdf\xa3binaire", "audio/webm", "rec.webm")
    assert fields["language"][0] == b"fr"
    assert audio_suffix("audio/webm;codecs=opus") == "webm"
    assert audio_suffix("application/octet-stream", "note.ogg") == "ogg"
    assert audio_suffix("text/html", "x.exe") == "bin"


# ---------- fenêtre, pages, API du Hub ----------
WEB = ROOT / "core" / "web"


def test_window_and_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    import re

    from modules.voice import app

    assert load_manifest(ROOT / "modules" / "voice").app == ("Studio audio Æther", "modules.voice.app")
    from core import config

    monkeypatch.setattr(config, "section", lambda name, path=None: {"port": 5761} if name == "daemon" else {})
    assert app.page_url() == "http://127.0.0.1:5761/static/audio_app.html"
    opened: list[str] = []
    monkeypatch.setattr(app, "find_browser", lambda: None)
    monkeypatch.setattr(app.webbrowser, "open", opened.append)
    assert app.main() == 0 and opened[0].endswith("/static/audio_app.html")

    page = (WEB / "audio_app.html").read_text(encoding="utf-8")
    script = (WEB / "audio_app.js").read_text(encoding="utf-8")
    style = (WEB / "audio_app.css").read_text(encoding="utf-8")
    worklet = (WEB / "audio_worklet.js").read_text(encoding="utf-8")
    assert " style=" not in page  # la CSP du Hub refuse les styles en ligne
    # seul lien externe : la page officielle de VB-Cable (ouverte dans le navigateur, rien n'est chargé)
    assert re.findall(r"https?://(?!127\.0\.0\.1)[^\s\"'<]+", page) == ["https://vb-audio.com/Cable/"]
    for text in (script, style, worklet):
        assert not re.search(r"https?://(?!127\.0\.0\.1)", text)
    ids = set(re.findall(r'\$\("([\w-]+)"\)', script))
    missing = sorted(i for i in ids if f'id="{i}"' not in page)
    assert ids and not missing, f"identifiants absents de la page : {missing}"
    assert 'registerProcessor("aether-pitch-shifter"' in worklet and '"aether-pitch-shifter"' in script
    for f in effects.LIMITS:  # mêmes réglages que le serveur
        assert f'key: "{f}"' in script

    dashboard = (WEB / "dashboard.html").read_text(encoding="utf-8")
    assert '<section data-sub="Studio audio"' in dashboard and 'allow="microphone' in dashboard
    for name in ("voice.js", "audio_tool.js"):
        assert f"/static/{name}" in dashboard
        text = (WEB / name).read_text(encoding="utf-8")
        ids = set(re.findall(r'(?:\$|byId)\("([\w-]+)"\)', text))
        assert ids and not sorted(i for i in ids if f'id="{i}"' not in dashboard), name


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from core import config
    from core.api import create_app
    from core.daemon import Daemon
    from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
    from core.llm_router import LlmRouter
    from tests.core.test_daemon import ollama_stopped

    real = config.section
    monkeypatch.setattr(config, "section", lambda name, path=None: {"data_dir": str(tmp_path / "voice")}
                        if name == "voice" else real(name, path))
    (tmp_path / "modules").mkdir()
    daemon = Daemon(tmp_path / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    return TestClient(create_app(daemon))


def test_api_voice_settings_and_profiles(client, tmp_path: Path) -> None:
    state = client.get("/voice/settings").json()
    assert state["default"] == "aether" and not state["speak_replies"]
    changed = client.post("/voice/settings", json={"speak_replies": True, "mic": "ma_voix_robot"}).json()
    assert changed["mic"] == "ma_voix_robot" and changed["speak_replies"]
    assert client.post("/voice/settings", json={"default": "ma_voix"}).status_code == 400
    saved = client.post("/voice/profiles", json={"id": "moi", "kind": "micro", "effects": {"pitch": 50}}).json()
    assert saved["effects"] == {"pitch": 12.0}
    assert (tmp_path / "voice" / "profiles.json").is_file()
    assert client.post("/voice/profiles", json={"id": "../x"}).status_code == 400
    assert client.delete("/voice/profiles/moi").json() == {"deleted": True}
    # sans module voice dans ce Hub de test : refus clair, rien de lancé
    assert client.post("/v1/audio/speech", json={"input": ""}).status_code == 400
    assert client.post("/v1/audio/speech", json={"input": "Bonjour"}).status_code == 404
    empty = client.post("/v1/audio/transcriptions", content=b"", headers={"Content-Type": "audio/wav"})
    assert empty.status_code == 413
