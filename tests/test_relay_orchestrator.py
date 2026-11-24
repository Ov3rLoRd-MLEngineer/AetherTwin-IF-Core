"""Tests du relais Cloud <-> Local. Aucun appel réseau externe : serveur HTTP factice sur 127.0.0.1."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from scripts import relay_orchestrator as ro

T_START = 1_000_000.0
WINDOW_S = ro.DEFAULT_WINDOW_MINUTES * 60


# --------------------------------------------------------------------------- doublures
class FakeCloud:
    """Rejoue une liste de résultats et note le prompt et l'heure de chaque appel."""

    def __init__(self, clock: ro.Clock, results: list[ro.CloudResult]) -> None:
        self.clock, self.results = clock, list(results)
        self.calls: list[tuple[float, str]] = []

    def run(self, prompt: str) -> ro.CloudResult:
        self.calls.append((self.clock.now(), prompt))
        item = self.results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeGit(ro.NullGit):
    def __init__(self) -> None:
        self.commits: list[str] = []

    def head(self) -> str | None:
        return "abc1234567890"

    def wip_commit(self, message: str) -> str | None:
        self.commits.append(message)
        return "def4567890123"

    def log_since(self, base: str | None, limit: int = 40) -> str:
        return "def4567 wip(local): tâche faite"


class UnavailableLocal(ro.SimulatedLocal):
    def available(self) -> tuple[bool, str]:
        return False, "aider introuvable"


def make(tmp_path: Path, results: list, local_cls=ro.SimulatedLocal, **cfg):
    clock = ro.VirtualClock(T_START)
    config = ro.RelayConfig(repo=tmp_path, state_path=tmp_path / "logs" / "relay_state.json",
                            lock_path=tmp_path / "logs" / "relay.lock", **cfg)
    cloud, local, git = FakeCloud(clock, results), local_cls(clock), FakeGit()
    return ro.RelayOrchestrator(config, cloud, local, git, clock=clock), cloud, local, git, clock


QUOTA = ro.CloudResult(ro.Status.QUOTA, "usage limit reached")
DONE = ro.CloudResult(ro.Status.DONE, "ok")
TRANSIENT = ro.CloudResult(ro.Status.TRANSIENT, "429 rate_limit_error")


# --------------------------------------------------------------------------- état et verrou
def test_state_roundtrip_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "relay_state.json"
    state = ro.RelayState(phase="local", t0=12.5, resume_at=99.0, cycles=2)
    state.save(path)
    assert ro.RelayState.load(path) == state
    assert [p.name for p in path.parent.iterdir()] == ["relay_state.json"]  # aucun fichier temporaire restant


def test_corrupt_state_is_set_aside(tmp_path: Path) -> None:
    path = tmp_path / "relay_state.json"
    path.write_text("{ pas du json", encoding="utf-8")
    assert ro.RelayState.load(path) is None
    assert (tmp_path / "relay_state.json.corrupt").exists()


def test_missing_state_gives_none(tmp_path: Path) -> None:
    assert ro.RelayState.load(tmp_path / "absent.json") is None


def test_lock_blocks_a_live_owner_and_takes_over_a_dead_one(tmp_path: Path) -> None:
    path = tmp_path / "relay.lock"
    first = ro.SingleInstanceLock(path, pid=111, alive=lambda pid: True)
    first.acquire()
    with pytest.raises(ro.LockError):
        ro.SingleInstanceLock(path, pid=222, alive=lambda pid: True).acquire()
    # le propriétaire est mort (plantage, redémarrage) : le verrou orphelin est repris
    second = ro.SingleInstanceLock(path, pid=222, alive=lambda pid: False)
    second.acquire()
    assert json.loads(path.read_text(encoding="utf-8"))["pid"] == 222
    second.release()
    assert not path.exists()


def test_pid_is_alive() -> None:
    import os

    assert ro.pid_is_alive(os.getpid())
    assert not ro.pid_is_alive(-1)


def test_two_simultaneous_instances(tmp_path: Path) -> None:
    orch, cloud, *_ = make(tmp_path, [DONE])
    with ro.SingleInstanceLock(orch.cfg.lock_path):  # première instance : ce processus, bien vivant
        assert orch.run() == 3
    assert cloud.calls == []  # la seconde instance n'a rien lancé


# --------------------------------------------------------------------------- scénarios du relais
def test_nominal_run_records_t0(tmp_path: Path) -> None:
    orch, cloud, local, _git, _clock = make(tmp_path, [DONE])
    assert orch.run() == 0
    saved = ro.RelayState.load(orch.cfg.state_path)
    assert saved is not None and saved.phase == "done" and saved.t0 == T_START
    assert local.starts == 0
    assert not orch.cfg.lock_path.exists()


def test_transient_429_backs_off_then_continues(tmp_path: Path) -> None:
    orch, cloud, local, _git, clock = make(tmp_path, [TRANSIENT, TRANSIENT, DONE])
    assert orch.run() == 0
    assert len(cloud.calls) == 3
    assert local.starts == 0  # pas de bascule pour un 429 passager
    assert clock.now() - T_START == pytest.approx(5 + 10)  # backoff exponentiel court


def test_persistent_429_switches_to_local_then_returns_at_t0_plus_window(tmp_path: Path) -> None:
    orch, cloud, local, git, _clock = make(tmp_path, [TRANSIENT] * 5 + [DONE])
    assert orch.run() == 0
    assert len(cloud.calls) == 6
    assert local.starts >= 1 and local.stopped == 1
    assert git.commits == ["wip(local): point de reprise du relais avant retour au cloud"]
    resumed_at, resume_prompt = cloud.calls[-1]
    assert resumed_at == pytest.approx(T_START + WINDOW_S)  # T0 + 5 h 02 exactement
    assert "REVUE DU DIFF" in resume_prompt and "wip(local): tâche faite" in resume_prompt
    saved = ro.RelayState.load(orch.cfg.state_path)
    assert saved is not None and saved.cycles == 1 and saved.t0 == pytest.approx(T_START + WINDOW_S)


def test_usage_limit_message_switches_immediately(tmp_path: Path) -> None:
    orch, cloud, local, _git, _clock = make(tmp_path, [QUOTA, DONE])
    assert orch.run() == 0
    assert len(cloud.calls) == 2  # aucun backoff inutile
    assert local.starts >= 1
    assert cloud.calls[1][0] == pytest.approx(T_START + WINDOW_S)


def test_window_is_configurable(tmp_path: Path) -> None:
    orch, cloud, *_ = make(tmp_path, [QUOTA, DONE], window_minutes=10)
    assert orch.run() == 0
    assert cloud.calls[1][0] == pytest.approx(T_START + 600)


def test_server_retry_after_later_than_window_is_respected(tmp_path: Path) -> None:
    late = ro.CloudResult(ro.Status.QUOTA, "limit reached", retry_after=WINDOW_S + 3600)
    orch, cloud, *_ = make(tmp_path, [late, DONE])
    assert orch.run() == 0
    assert cloud.calls[1][0] == pytest.approx(T_START + WINDOW_S + 3600)


def test_restart_in_the_middle_of_the_local_window(tmp_path: Path) -> None:
    orch, cloud, local, git, _clock = make(tmp_path, [DONE])
    ro.RelayState(phase="local", t0=T_START - 3600, resume_at=T_START + 1000, cycles=1,
                  local_base_commit="abc").save(orch.cfg.state_path)
    assert orch.run() == 0
    assert local.starts >= 1  # l'agent local reprend sans repasser par le cloud
    assert len(cloud.calls) == 1 and cloud.calls[0][0] == pytest.approx(T_START + 1000)
    assert "REVUE DU DIFF" in cloud.calls[0][1]
    saved = ro.RelayState.load(orch.cfg.state_path)
    assert saved is not None and saved.cycles == 1  # la bascule n'est pas comptée deux fois


def test_restart_after_the_window_goes_straight_back_to_cloud(tmp_path: Path) -> None:
    orch, cloud, local, git, _clock = make(tmp_path, [DONE])
    ro.RelayState(phase="local", t0=T_START - 20000, resume_at=T_START - 10).save(orch.cfg.state_path)
    assert orch.run() == 0
    assert local.starts == 0 and len(git.commits) == 1
    assert cloud.calls[0][0] == T_START


def test_restart_during_cloud_phase_keeps_t0_inside_window(tmp_path: Path) -> None:
    orch, cloud, *_ = make(tmp_path, [DONE])
    ro.RelayState(phase="cloud", t0=T_START - 600).save(orch.cfg.state_path)
    assert orch.run() == 0
    assert "interrompu" in cloud.calls[0][1]
    saved = ro.RelayState.load(orch.cfg.state_path)
    assert saved is not None and saved.t0 == T_START - 600


def test_unavailable_local_agent_waits_without_crashing(tmp_path: Path) -> None:
    orch, cloud, local, _git, _clock = make(tmp_path, [QUOTA, DONE], local_cls=UnavailableLocal)
    assert orch.run() == 0
    assert local.starts == 0
    assert cloud.calls[1][0] == pytest.approx(T_START + WINDOW_S)


def test_cloud_error_stops_with_code_2(tmp_path: Path) -> None:
    orch, *_ = make(tmp_path, [ro.CloudResult(ro.Status.ERROR, "boom")])
    assert orch.run() == 2
    saved = ro.RelayState.load(orch.cfg.state_path)
    assert saved is not None and saved.phase == "error"


def test_max_cycles_stops_the_relay(tmp_path: Path) -> None:
    orch, cloud, *_ = make(tmp_path, [QUOTA, QUOTA], max_cycles=1)
    assert orch.run() == 2
    assert len(cloud.calls) == 2


def test_ctrl_c_saves_state_and_releases_lock(tmp_path: Path) -> None:
    orch, *_ = make(tmp_path, [KeyboardInterrupt()])
    assert orch.run() == 130
    assert not orch.cfg.lock_path.exists()
    saved = ro.RelayState.load(orch.cfg.state_path)
    assert saved is not None and saved.phase == "cloud" and "Interrompu" in saved.last_event


def test_ctrl_c_during_local_phase_stops_agent_and_commits(tmp_path: Path) -> None:
    orch, _cloud, local, git, clock = make(tmp_path, [QUOTA])

    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    clock.sleep = interrupt  # type: ignore[method-assign]
    assert orch.run() == 130
    assert local.stopped == 1 and len(git.commits) == 1
    saved = ro.RelayState.load(orch.cfg.state_path)
    assert saved is not None and saved.phase == "local"  # reprise possible au prochain lancement


# --------------------------------------------------------------------------- backend Claude Code
def test_claude_code_classification() -> None:
    classify = ro.ClaudeCodeBackend.classify
    assert classify(0, "Travail terminé.", "").status is ro.Status.DONE
    assert classify(1, "Claude usage limit reached. Your limit will reset at 3pm.", "").status is ro.Status.QUOTA
    assert classify(1, "", "API Error: 429 rate_limit_error").status is ro.Status.TRANSIENT
    assert classify(1, "", "API Error: 529 overloaded_error").status is ro.Status.TRANSIENT
    assert classify(1, "", "erreur inconnue").status is ro.Status.ERROR
    ok_json = json.dumps({"is_error": False, "result": "J'ai géré le cas 429 et la limite (usage limit) "
                                                       "dans le code. " + "x" * 400})
    assert classify(0, ok_json, "").status is ro.Status.DONE  # un succès qui PARLE de 429 reste un succès
    err_json = json.dumps({"is_error": True, "result": "You've hit your session limit · resets 3pm"})
    assert classify(0, err_json, "").status is ro.Status.QUOTA


def test_claude_code_backend_runs_a_real_subprocess_with_prompt_on_stdin(tmp_path: Path) -> None:
    script = ("import sys; p = sys.stdin.read(); "
              "print('usage limit reached' if 'MISSION' in p else 'prompt absent'); sys.exit(1)")
    backend = ro.ClaudeCodeBackend([sys.executable, "-c", script], cwd=tmp_path, timeout_s=60)
    assert backend.run("MISSION de test").status is ro.Status.QUOTA


def test_claude_code_backend_missing_binary(tmp_path: Path) -> None:
    backend = ro.ClaudeCodeBackend(["binaire-qui-n-existe-pas-xyz"], cwd=tmp_path, timeout_s=5)
    assert backend.run("x").status is ro.Status.ERROR


# --------------------------------------------------------------------------- backend API (serveur factice)
class _Handler(BaseHTTPRequestHandler):
    script: list[tuple[int, dict[str, str], dict]] = []
    seen: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        type(self).seen.append({"path": self.path, "body": json.loads(self.rfile.read(length) or b"{}"),
                                "has_key": bool(self.headers.get("x-api-key")
                                                or self.headers.get("authorization"))})
        status, headers, body = type(self).script.pop(0)
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: object) -> None:
        pass


ERR_429 = (429, {"retry-after": "1"}, {"type": "error", "error": {"type": "rate_limit_error",
                                                                  "message": "Too many requests"}})
ERR_429_LIMIT = (429, {"retry-after": "7200"}, {"type": "error", "error": {
    "type": "rate_limit_error", "message": "Usage limit reached for this period"}})
ERR_529 = (529, {}, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
ERR_400 = (400, {}, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}})
OK_200 = (200, {}, {"id": "msg_test", "type": "message", "role": "assistant", "model": "test-model",
                    "content": [{"type": "text", "text": "réponse factice"}], "stop_reason": "end_turn",
                    "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-factice-de-test")
    for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    _Handler.script, _Handler.seen = [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    backend = ro.ApiBackend("test-model", tmp_path / "logs" / "reponse.md",
                            base_url=f"http://127.0.0.1:{server.server_address[1]}", timeout_s=20)
    yield backend
    server.shutdown()
    server.server_close()


def test_api_backend_maps_http_errors(fake_api: ro.ApiBackend) -> None:
    _Handler.script = [ERR_429, ERR_429_LIMIT, ERR_529, ERR_400, OK_200]
    transient = fake_api.run("x")
    assert transient.status is ro.Status.TRANSIENT and transient.retry_after == 1
    quota = fake_api.run("x")
    assert quota.status is ro.Status.QUOTA and quota.retry_after == 7200
    assert fake_api.run("x").status is ro.Status.TRANSIENT  # 529 surcharge
    assert fake_api.run("x").status is ro.Status.ERROR  # 400 : pas de nouvel essai
    assert fake_api.run("bonjour").status is ro.Status.DONE
    assert fake_api.output_path.read_text(encoding="utf-8") == "réponse factice"
    assert len(_Handler.seen) == 5  # le SDK ne refait pas d'essais cachés (max_retries=0)
    last = _Handler.seen[-1]
    assert last["path"] == "/v1/messages" and last["has_key"]
    assert last["body"]["messages"] == [{"role": "user", "content": "bonjour"}]


def test_api_transient_429_then_success_end_to_end(fake_api: ro.ApiBackend, tmp_path: Path) -> None:
    _Handler.script = [ERR_429, OK_200]
    orch, _cloud, local, *_ = make(tmp_path, [])
    orch.cloud = fake_api
    assert orch.run() == 0
    assert local.starts == 0 and len(_Handler.seen) == 2


def test_api_persistent_429_switches_to_local_end_to_end(fake_api: ro.ApiBackend, tmp_path: Path) -> None:
    _Handler.script = [ERR_429] * 5 + [OK_200]
    orch, _cloud, local, git, clock = make(tmp_path, [])
    orch.cloud = fake_api
    assert orch.run() == 0
    assert local.starts >= 1 and len(git.commits) == 1
    assert clock.now() >= T_START + WINDOW_S
    assert "REVUE DU DIFF" in _Handler.seen[-1]["body"]["messages"][0]["content"]


def test_api_backend_without_credentials_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("anthropic")
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "vide"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    backend = ro.ApiBackend("test-model", tmp_path / "r.md", base_url="http://127.0.0.1:9", timeout_s=3)
    assert backend.run("x").status in (ro.Status.ERROR, ro.Status.TRANSIENT)  # jamais DONE, jamais d'exception


# --------------------------------------------------------------------------- agent local et Git
def test_aider_command_fixes_num_ctx_and_reads_handoff_files(tmp_path: Path) -> None:
    (tmp_path / "AGENT_HANDOFF.md").write_text("x", encoding="utf-8")
    agent = ro.SubprocessLocalAgent("aider", ro.DEFAULT_LOCAL_MODEL, 32768, "127.0.0.1:11434", tmp_path,
                                    tmp_path / "logs")
    cmd = agent.build_command("fais la tâche")
    assert cmd[:3] == ["aider", "--model", f"ollama_chat/{ro.DEFAULT_LOCAL_MODEL}"]
    assert cmd[cmd.index("--read") + 1] == "AGENT_HANDOFF.md" and cmd.count("--read") == 1
    assert "num_ctx: 32768" in (tmp_path / "logs" / "aider_model_settings.yml").read_text(encoding="utf-8")
    assert (tmp_path / "logs" / "relay_local_prompt.md").read_text(encoding="utf-8") == "fais la tâche"


def test_local_agent_unavailable_when_binary_or_model_is_missing(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    agent = ro.SubprocessLocalAgent("aider", "modele", 4096, "127.0.0.1:1", tmp_path, tmp_path,
                                    model_check=lambda host, model: (False, "modèle absent"))
    monkeypatch.setattr(ro.shutil, "which", lambda name: None)
    assert agent.available() == (False, "`aider` introuvable dans le PATH")
    monkeypatch.setattr(ro.shutil, "which", lambda name: "/bin/aider")
    assert agent.available() == (False, "modèle absent")


def test_local_claude_code_goes_through_the_local_router_without_any_real_key(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "vraie-cle-a-ne-pas-envoyer")
    agent = ro.SubprocessLocalAgent("claude-code", "qwen3-27b:latest", 32768, "127.0.0.1:11434", tmp_path,
                                    tmp_path / "logs", router_url="http://127.0.0.1:20128/v1")
    cmd = agent.build_command("fais la tâche")
    assert cmd == ["claude", "-p", "--model", "ollama/qwen3-27b:latest", "--permission-mode", "acceptEdits"]
    assert "fais la tâche" not in cmd  # le prompt passe par l'entrée standard, pas par la ligne de commande
    assert agent.prompt_file.read_text(encoding="utf-8") == "fais la tâche"
    env = agent.build_env()
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:20128/v1"
    assert env["ANTHROPIC_API_KEY"] == ""  # la vraie clé ne part jamais vers le routeur local
    assert env["ANTHROPIC_CONTEXT_LENGTH"] == "32768"  # aligné sur num_ctx d'Ollama


def test_local_claude_code_needs_the_router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ro.shutil, "which", lambda name: "/bin/claude")
    down = ro.SubprocessLocalAgent("claude-code", "m", 4096, "127.0.0.1:1", tmp_path, tmp_path,
                                   model_check=lambda host, model: (True, ""),
                                   router_check=lambda url: (False, "routeur éteint"))
    assert down.available() == (False, "routeur éteint")
    up = ro.SubprocessLocalAgent("claude-code", "m", 4096, "127.0.0.1:1", tmp_path, tmp_path,
                                 model_check=lambda host, model: (True, ""), router_check=lambda url: (True, ""))
    assert up.available() == (True, "")


def test_local_claude_code_real_subprocess_reads_prompt_from_stdin(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    agent = ro.SubprocessLocalAgent("claude-code", "m", 4096, "127.0.0.1:1", tmp_path, tmp_path / "logs")
    script = "import os, sys; print(sys.stdin.read().upper(), os.environ['ANTHROPIC_BASE_URL'])"
    monkeypatch.setattr(agent, "build_command",
                        lambda prompt: (agent.prompt_file.parent.mkdir(exist_ok=True),
                                        agent.prompt_file.write_text(prompt, encoding="utf-8"),
                                        [sys.executable, "-c", script])[-1])
    agent.start("bonjour local")
    agent._proc.wait(timeout=30)  # type: ignore[union-attr]
    assert not agent.is_running() and agent.exit_code() == 0
    agent.stop()
    out = (tmp_path / "logs" / "relay_local_agent.log").read_text(encoding="utf-8")
    assert "BONJOUR LOCAL" in out and ro.DEFAULT_ROUTER_URL in out


def test_router_unreachable_is_reported_not_raised() -> None:
    ok, reason = ro.router_is_up("http://127.0.0.1:9/v1", timeout_s=1)
    assert not ok and "injoignable" in reason


def test_ollama_unreachable_is_reported_not_raised() -> None:
    ok, reason = ro.ollama_has_model("127.0.0.1:9", "modele", timeout_s=1)
    assert not ok and "injoignable" in reason


def test_local_prompt_is_explicit() -> None:
    prompt = ro.build_local_prompt("- [ ] écrire le test X")
    for expected in ("AGENT_HANDOFF.md", "logs/CHANGELOG_DEV.md", "wip(local):", "écrire le test X"):
        assert expected in prompt


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_git_wip_commit_and_review_diff(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("config", "commit.gpgsign", "false")
    (tmp_path / "a.txt").write_text("un\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    repo = ro.GitRepo(tmp_path)
    base = repo.head()
    assert base and repo.wip_commit("wip(local): rien") is None  # rien à committer
    (tmp_path / "a.txt").write_text("un\ndeux\n", encoding="utf-8")
    sha = repo.wip_commit("wip(local): ajoute deux")
    assert sha and sha != base
    assert "wip(local): ajoute deux" in repo.log_since(base)
    assert "a.txt" in repo.diff_stat(base) and "+deux" in repo.diff(base, 10_000)
    assert "tronqué" in repo.diff(base, 10)


# --------------------------------------------------------------------------- ligne de commande
def test_dry_run_completes_a_full_cycle_without_services(tmp_path: Path) -> None:
    assert ro.main(["--dry-run", "--repo", str(tmp_path)]) == 0
    saved = ro.RelayState.load(tmp_path / "logs" / "relay_state.dryrun.json")
    assert saved is not None and saved.phase == "done" and saved.cycles == 1 and saved.cloud_runs == 2
    assert "MODE SIMULATION" in (tmp_path / "logs" / "relay.dryrun.log").read_text(encoding="utf-8")
    assert not (tmp_path / "logs" / "relay.dryrun.lock").exists()
    ro.log.handlers.clear()


def test_status_without_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ro.main(["--status", "--repo", str(tmp_path)]) == 0
    assert "Aucun état" in capsys.readouterr().out


@pytest.mark.parametrize("message", [
    "You've hit your 5-hour limit · resets 12:30am (Europe/Paris)",  # vrai message du 23/11 à 21 h 25
    "You've hit your 5-hour limit · resets 2:30am (Europe/Paris)",
])
def test_real_quota_messages_trigger_the_relay(message: str) -> None:
    assert ro.classify_text(message) is ro.Status.QUOTA
    payload = json.dumps({"is_error": True, "result": message})
    assert ro.ClaudeCodeBackend.classify(1, payload, "").status is ro.Status.QUOTA
    success = json.dumps({"is_error": False, "result": message})  # parfois rendu comme une réponse normale
    assert ro.ClaudeCodeBackend.classify(0, success, "").status is ro.Status.QUOTA
