"""Veilleur de quota : détection du message de limite, lecture incrémentale, passation, lancement."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.dev_launcher import launch, quota_watch

TEXT = "You've hit your 5-hour limit · resets 7:30pm (Europe/Paris)"
LIMIT = {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit", "sessionId": "s1",
         "cwd": "D:\\x", "timestamp": "2026-11-24T16:20:25Z",
         "message": {"role": "assistant",
                     "content": [{"type": "text", "text": TEXT}]}}


def test_parse_limit_reads_the_real_message() -> None:
    info = quota_watch.parse_limit(LIMIT)
    assert info and info["reset"] == "19 h 30 (Europe/Paris)" and info["session"] == "s1"


@pytest.mark.parametrize(("when", "expected"), [("7:30pm", "19 h 30"), ("12:30am", "0 h 30"), ("12pm", "12 h 00"),
                                                ("5:50am", "5 h 50"), ("demain", "demain")])
def test_french_time(when: str, expected: str) -> None:
    assert quota_watch.french_time(when) == expected


def test_ordinary_messages_are_ignored() -> None:
    talk = {"type": "assistant", "message": {"content": [{"type": "text", "text": "you've hit your 5-hour limit"}]}}
    assert quota_watch.parse_limit(talk) is None  # une phrase du modèle, pas une erreur de l'API
    other = dict(LIMIT, message={"content": [{"type": "text", "text": "Overloaded"}]})
    assert quota_watch.parse_limit(other) is None
    assert quota_watch.parse_limit({"type": "user", "message": LIMIT["message"]}) is None


def _write(path: Path, *records: dict, partial: str = "") -> None:
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
        f.write(partial)


def test_watcher_only_sees_new_complete_lines(tmp_path: Path) -> None:
    session = tmp_path / "projet"
    session.mkdir()
    old = session / "a.jsonl"
    _write(old, LIMIT)  # limite déjà passée avant le démarrage : ignorée
    watcher = quota_watch.Watcher(tmp_path)
    assert watcher.poll() is None
    line = json.dumps(LIMIT)
    _write(old, {"type": "user", "message": {"content": "bonjour"}}, partial=line[:40])
    assert watcher.poll() is None  # ligne encore incomplète
    _write(old, partial=line[40:] + "\n")
    info, path = watcher.poll()
    assert path == old and info["reset"].startswith("19 h 30")
    fresh = session / "b.jsonl"  # session ouverte après le démarrage
    _write(fresh, LIMIT)
    assert watcher.poll()[1] == fresh


def test_last_user_request_skips_tool_results_and_reminders() -> None:
    lines = [json.dumps(r) for r in (
        {"type": "user", "message": {"content": "fais les vagues"}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "user", "message": {"content": [{"type": "text", "text": "et le plein écran"}]}},
        {"type": "user", "message": {"content": "<system-reminder>…</system-reminder>"}},
        {"type": "user", "isMeta": True, "message": {"content": "méta"}},
    )]
    assert quota_watch.last_user_request(lines) == "et le plein écran"


def test_handoff_asks_before_acting() -> None:
    info = quota_watch.parse_limit(LIMIT)
    text = quota_watch.handoff_text(info, "fais les vagues", "qwen3-coder:30b-a3b-64k", "abc commit", "")
    assert "RELAIS PRIS" in text and "continues" in text and "attendre" in text and "19 h 30" in text
    assert "attends sa réponse" in text and "git push" in text and "fais les vagues" in text
    assert "ESSAI" in quota_watch.handoff_text(info, "", "m", "", "", essai=True)


def test_hand_over_writes_handoff_and_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quota_watch, "RELAY_DIR", tmp_path)
    monkeypatch.setattr(quota_watch, "_launcher", lambda: type("L", (), {"task_model": lambda self, m: m or "mod"})())
    transcript = tmp_path / "t.jsonl"
    _write(transcript, {"type": "user", "message": {"content": "continue la voix"}}, LIMIT)
    opened = []
    record = quota_watch.hand_over(quota_watch.parse_limit(LIMIT), transcript,
                                   opener=lambda model: opened.append(model) or {"model": model, "how": "wt"})
    assert opened == ["mod"] and record["how"] == "wt"
    assert "continue la voix" in (tmp_path / "passation.md").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "journal.jsonl").read_text(encoding="utf-8"))["limite"]["session"] == "s1"


def test_batch_script_passes_the_first_message() -> None:
    env = launch.route_env("ollama", "qwen3-coder:30b-a3b-64k", 65536, "http://127.0.0.1:11434", "")
    script = launch.batch_script(env, Path("D:/repo"), ["claude.cmd"], "Relais", tools=quota_watch.LOCAL_TOOLS,
                                 confirm=True, prompt=quota_watch.FIRST_MESSAGE)
    last = script.strip().splitlines()[-1]
    assert last.endswith(f'"{quota_watch.FIRST_MESSAGE}"') and '--permission-mode "default"' in last
    with pytest.raises(launch.LaunchError):
        launch.batch_script(env, Path("D:/repo"), ["claude.cmd"], "Relais", prompt='a" & del *')
