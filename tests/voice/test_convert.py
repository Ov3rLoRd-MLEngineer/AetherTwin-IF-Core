"""Conversion de voix : banque avec consentement (phrase dite, textes lus vérifiés), poids vérifiés, analyse sûre de
la configuration de WavLM, commandes du module. Aucun téléchargement ni modèle réel requis."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import numpy as np
import pytest

from modules.voice import convert, effects
from modules.voice.profiles import validate
from tests.voice.test_voice import make


def speech(seconds: float = 3.0, rate: int = 16000) -> bytes:
    """Son voisé (harmoniques) entouré de silence, pour passer le découpage du silence."""
    t = np.arange(int(seconds * rate)) / rate
    voiced = sum(0.15 * np.sin(2 * np.pi * f * t) for f in (140, 280, 420))
    pad = np.zeros(rate // 2)
    return effects.write_wav(np.concatenate([pad, voiced, pad]).astype(np.float32), rate)


def hears(text: str):
    return lambda wav: text


def test_words_and_similarity() -> None:
    assert convert.words("Ça, c'est l'Été !") == ["ca", "c", "est", "l", "ete"]
    assert convert.similarity(convert.PROMPTS[0], convert.PROMPTS[0].upper()) == 1.0
    assert convert.similarity(convert.PROMPTS[0], "bonjour tout le monde") < convert.MATCH_MIN


def test_trim_and_decode() -> None:
    x = convert.decode(speech(2.0))
    assert x.dtype == np.float32 and abs(x.size / 16000 - 3.0) < 0.01
    trimmed = convert.trim_silence(x)
    assert 1.9 < trimmed.size / 16000 < 2.3
    assert convert.trim_silence(np.zeros(16000, dtype=np.float32)).size == 0
    resampled = convert.decode(effects.write_wav(np.zeros(22050, dtype=np.float32), 22050))  # 1 s à 22,05 kHz
    assert abs(resampled.size - 16000) < 10


def test_conv_layers_parser_never_executes() -> None:
    # wavlm importe PyTorch, installé seulement avec setup.ps1 -Gpu.
    pytest.importorskip("torch")
    from modules.voice.vc.wavlm import parse_conv_layers

    spec = "[(512,10,5)] + [(512,3,2)] * 4 + [(512,2,2)] * 2"
    assert parse_conv_layers(spec) == [(512, 10, 5)] + [(512, 3, 2)] * 4 + [(512, 2, 2)] * 2
    for bad in ("__import__('os').system('x')", "[(1,2,3)] * 2 + open('x')", "[x for x in ()]"):
        with pytest.raises(ValueError):
            parse_conv_layers(bad)


def test_bank_requires_spoken_consent_then_read_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(convert, "READY_SECONDS", 2.5)  # une prise de 3 s suffit ici
    bank = convert.VoiceBank(tmp_path / "bank")
    with pytest.raises(ValueError, match="attestation"):
        bank.create("ma_voix", "Ma voix", "Jérémy", attest=False)
    with pytest.raises(ValueError, match="prénom"):
        bank.create("ma_voix", "Ma voix", "  ", attest=True)
    for bad in ("../x", "A", "a/b", ""):
        with pytest.raises(ValueError):
            bank.create(bad, "x", "Jérémy", attest=True)
    voice = bank.create("ma_voix", "Ma voix", "Jérémy", attest=True)
    assert "Jérémy" in voice["consent_text"] and not voice["consented"]
    assert bank.next_prompt("ma_voix")["consent"] is True
    with pytest.raises(ValueError, match="pas prête"):
        bank.takes("ma_voix")
    # la première prise doit être la phrase de consentement, entendue par Whisper
    with pytest.raises(ValueError, match="ne correspond pas"):
        bank.add_take("ma_voix", speech(), 0, hears(convert.PROMPTS[0]))
    first = bank.add_take("ma_voix", speech(), -1, hears(voice["consent_text"]))
    assert first["match"] == 1.0 and first["next"]["consent"] is False
    prompt = first["next"]["index"]
    with pytest.raises(ValueError, match="ne correspond pas"):  # un autre fichier, d'autres paroles : refusé
        bank.add_take("ma_voix", speech(), prompt, hears("salut c'est une vidéo de quelqu'un d'autre"))
    with pytest.raises(ValueError, match="entre"):
        bank.add_take("ma_voix", speech(0.5), prompt, hears(convert.PROMPTS[prompt]))
    second = bank.add_take("ma_voix", speech(), prompt, hears(convert.PROMPTS[prompt]))
    assert second["next"]["index"] != prompt
    skipped = bank.next_prompt("ma_voix", after=second["next"]["index"])  # « Autre texte »
    assert skipped["index"] not in (prompt, second["next"]["index"]) and skipped["left"] == len(convert.PROMPTS) - 1
    assert convert.MAX_TAKES >= 100 and len(convert.PROMPTS) >= 70
    assert convert.prompt_label(len(convert.PROMPTS) - 1).endswith("partie 4 sur 4") and convert.prompt_label(0) == ""
    listed = bank.all()
    assert listed[0]["ready"] and listed[0]["takes"] == 2
    assert len(bank.takes("ma_voix")) == 2
    with pytest.raises(ValueError, match="consentement"):
        bank.delete_take("ma_voix", 0)
    assert bank.delete_take("ma_voix", second["take"]) and not bank.all()[0]["ready"]
    with pytest.raises(ValueError, match="lecture au moins"):
        bank.takes("ma_voix")
    assert bank.delete("ma_voix") and bank.all() == []


def test_weights_install_checks_source_size_and_hash(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source"):
        convert.fetch_to("https://example.com/WavLM-Large.pt", tmp_path / "x.pt", 10, "")
    fetched: list[str] = []

    def fake(url: str, target: Path, size: int, sha: str) -> None:
        assert url.startswith(convert.RELEASE) and len(sha) == 64
        fetched.append(target.name)
        with target.open("wb") as f:
            f.truncate(size)

    result = convert.install(tmp_path / "w", fake)
    assert sorted(fetched) == sorted(convert.WEIGHTS) and all(result["weights"].values())
    assert convert.install(tmp_path / "w", fake)["fetched"] == []
    for size, sha in convert.WEIGHTS.values():
        assert size > 1_000_000 and len(sha) == 64 and hashlib.sha256(b"").hexdigest() != sha


def test_profile_convert_field() -> None:
    p = validate({"id": "moi", "kind": "synthese", "engine": "piper", "voice": "v", "convert": "ma_voix"})
    assert p["convert"] == "ma_voix"
    assert "convert" not in validate({"id": "moi", "kind": "synthese", "engine": "piper", "voice": "v"})
    with pytest.raises(ValueError):
        validate({"id": "moi", "kind": "synthese", "engine": "piper", "voice": "v", "convert": "../x"})


def test_module_commands_and_conversion_in_synthesis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, fake = make(tmp_path, monkeypatch)
    s = module.service
    status = module.run("vc_status", {})
    assert status["voices"] == [] and status["prompts"] == len(convert.PROMPTS) and not status["installed"]
    voice = module.run("vc_create", {"id": "ma_voix", "label": "Ma voix", "name": "Jérémy", "attest": True})
    monkeypatch.setattr(s, "transcribe", lambda audio, language="fr": {"text": voice["consent_text"]})
    audio = base64.b64encode(speech()).decode("ascii")
    assert module.run("vc_take", {"voice": "ma_voix", "prompt": -1, "audio": audio})["take"] == 0
    assert module.run("vc_voice", {"voice": "ma_voix"})["consented"]
    # pas de poids (ou pas de PyTorch, installation sans -Gpu) : message clair, rien de chargé
    with pytest.raises(RuntimeError, match="poids|PyTorch absent"):
        module.run("vc_convert", {"voice": "ma_voix", "audio": audio})
    converted: list[str] = []
    monkeypatch.setattr(s.converter, "convert_wav", lambda wav, vid: converted.append(vid) or speech(1.0))
    out = module.run("speak", {"text": "Bonjour", "profile_data": {"id": "moi", "kind": "synthese", "engine": "piper",
                                                                    "voice": "v", "convert": "ma_voix"}})
    assert converted == ["ma_voix"] and out["audio"]
    reply = module.run("vc_convert", {"voice": "ma_voix", "audio": audio, "effects": {"echo": 0.2}})
    assert reply["voice"] == "ma_voix" and reply["audio"] and reply["duration"] > 0.5
    assert module.run("vc_delete", {"voice": "ma_voix"})["deleted"]
    with pytest.raises(ValueError):
        module.run("vc_nimporte", {})
