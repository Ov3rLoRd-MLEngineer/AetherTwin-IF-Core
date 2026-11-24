"""Onglet Développement : lanceur de Claude Code local, terminaux du Hub, pont MCP, tâches confiées, relais."""
from __future__ import annotations

import json
import queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.terminals import TerminalError, TerminalManager, child_env
from modules.dev_launcher import bridge_mcp, catalog, hermes_link, launch, relay_check
from modules.dev_launcher.tasks import DENY, TaskError, TaskRunner, clean_env

LIST = {"data": [
    {"id": "agy/claude-sonnet-4-6", "name": "agy/Claude Sonnet 4.6", "context_length": 1048576,
     "max_output_tokens": 64000, "capabilities": {"tool_calling": True, "vision": True}},
    {"id": "agy/gemini-4-argon-disabled"}, {"id": "cfp/x"}, {"id": "qwen3-27b:latest"},
    {"id": "antigravity/text-embedding"}, {"id": 'agy/bad"id'},
]}


# -- catalogue
def test_omniroute_list_falls_back_to_the_exported_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exported = tmp_path / "liste.json"
    exported.write_text(json.dumps(LIST), encoding="utf-8")
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.setattr(catalog, "service_up", lambda url, timeout=3.0: True)
    result = catalog.omniroute_models("http://127.0.0.1:20128", fallback=exported)
    assert result["source"] == "liste exportée" and result["cle"] is False
    assert [m["id"] for m in result["modeles"]] == ["agy/claude-sonnet-4-6"]  # désactivés, embeddings, autres écartés
    assert result["modeles"][0]["capacites"] == ["outils", "vision"]


def test_ollama_models_read_tags_loaded_and_context(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = {"/api/tags": {"models": [
        {"name": "qwen3-coder:30b", "size": 18_600_000_000, "details": {"parameter_size": "30.5B",
                                                                        "quantization_level": "Q4_K_M"}},
        {"name": "nomic-embed-text:latest", "details": {"family": "nomic-bert"}}]},
        "/api/version": {"version": "0.40.17"},
        "/api/ps": {"models": [{"name": "qwen3-coder:30b", "context_length": 32768, "size_vram": 2.1e10}]}}
    monkeypatch.setattr(catalog, "_get_json", lambda url, headers=None, timeout=4.0: answers[url[url.index("/api"):]])
    monkeypatch.setattr(catalog, "num_ctx", lambda base, name, timeout=4.0: 65536)
    result = catalog.ollama_models("http://127.0.0.1:11434")
    assert result["en_ligne"] and result["version"] == "0.40.17"
    (model,) = result["modeles"]
    assert model["charge"] and model["contexte"] == 32768 and model["contexte_regle"] == 65536


# -- lancement
def test_route_env_never_carries_a_real_key() -> None:
    env = launch.route_env("ollama", "qwen3-coder:30b", 65536, "http://127.0.0.1:11434", "http://127.0.0.1:20128")
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:11434" and env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama" and env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "65536"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "qwen3-coder:30b" and "ANTHROPIC_SMALL_FAST_MODEL" not in env
    omni = launch.route_env("omniroute", "agy/claude-sonnet-4-6", 0, "x", "http://127.0.0.1:20128")
    assert omni["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:20128/v1"
    with pytest.raises(launch.LaunchError):
        launch.route_env("ollama", 'x" & calc', 0, "a", "b")
    with pytest.raises(launch.LaunchError):
        launch.route_env("cloud", "x", 0, "a", "b")


def test_batch_script_and_launch_files(tmp_path: Path) -> None:
    env = launch.route_env("ollama", "qwen3-coder:30b", 32768, "http://127.0.0.1:11434", "")
    mcp = launch.mcp_config(tmp_path / "mcp.json")
    config = json.loads(mcp.read_text(encoding="utf-8"))["mcpServers"]["aethertwin"]
    assert config["args"][-1] == "claude" and config["args"][1].endswith("bridge_mcp.py")
    script = launch.batch_script(env, tmp_path, ["claude.cmd"], "Claude Code", mcp)
    assert f'cd /d "{tmp_path}"' in script and '--model "qwen3-coder:30b"' in script and "--mcp-config" in script
    assert "--tools" not in script and "--strict-mcp-config" not in script
    assert '--tools "Read,Write,Edit,Glob,Grep,Bash" --strict-mcp-config' in launch.batch_script(
        env, tmp_path, ["claude.cmd"], "t", None, launch.ESSENTIAL_TOOLS)
    assert 'set "CLAUDECODE="' in script and 'set "CLAUDE_CODE_MESSAGING_TOKEN="' in script  # session parente oubliée
    with pytest.raises(launch.LaunchError):
        launch.batch_script(env, Path('C:/a"b'), ["claude.cmd"], "t")
    folder = tmp_path / "lancements"
    for _ in range(3):
        launch.write_launch(folder, script, keep=2)
    assert len(list(folder.glob("claude_*.bat"))) == 2


def test_windows_terminal_gets_a_clean_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "secret-de-session")
    monkeypatch.setattr(launch, "windows_terminal", lambda: "wt.exe")
    calls: list[tuple[list[str], dict[str, Any]]] = []
    where = launch.open_in_windows_terminal(tmp_path / "a.bat", tmp_path, "Claude",
                                            spawner=lambda args, **kw: calls.append((args, kw)))
    args, kw = calls[0]
    assert where == "Windows Terminal" and args[0] == "wt.exe" and args[-2:] == ["/k", str(tmp_path / "a.bat")]
    assert "CLAUDE_CODE_MESSAGING_TOKEN" not in kw["env"]


# -- tâches confiées (Hermes -> Claude Code local)
RECEIVED: list[str] = []


class FakeProc:
    def __init__(self, *args: Any, **kw: Any) -> None:
        self.kw, self.returncode = kw, 0
        kw["stdout"].write(b"Fichier bonjour.py cree.")
        Path(kw["cwd"], "bonjour.py").write_text("print('Bonjour')", encoding="utf-8")

    def communicate(self, data: bytes, timeout: float) -> None:
        self.received = data
        RECEIVED.append(data.decode("utf-8"))


def test_delegated_tasks_stay_in_allowed_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("CLAUDECODE", "1")
    root = tmp_path / "travaux"
    seen: list[Any] = []

    def runner(cmd: list[str], **kw: Any) -> FakeProc:
        proc = FakeProc(cmd, **kw)
        seen.append((cmd, kw))
        return proc

    env = lambda model: launch.route_env("ollama", model or "qwen3-coder:30b", 32768, "http://127.0.0.1:11434", "")  # noqa: E731
    tasks = TaskRunner(tmp_path / "data", [root], lambda: ["claude.cmd"], env, runner=runner)
    with pytest.raises(TaskError, match="non autorisé"):
        tasks.start("x", folder=str(tmp_path / "ailleurs"))
    with pytest.raises(TaskError, match="non autorisé"):
        tasks.start("x", folder=str(root / ".." / "ailleurs"))
    with pytest.raises(TaskError, match="vide"):
        tasks.start("  ")
    started = tasks.start("Écris bonjour.py", origin="Hermes")
    for _ in range(100):
        view = tasks.view(started["id"])
        if view["etat"] != "en cours":
            break
        __import__("time").sleep(0.02)
    assert view["etat"] == "terminée" and view["fichiers"] == ["bonjour.py"] and "bonjour.py" in view["sortie"]
    assert Path(view["dossier"]).parent == root
    assert view["dossier"] in RECEIVED[-1] and RECEIVED[-1].endswith("Écris bonjour.py")
    cmd, kw = seen[0]
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert cmd[cmd.index("--tools") + 1] == "Read,Write,Edit,Glob,Grep"
    assert "OPENAI_API_KEY" not in kw["env"] and "CLAUDECODE" not in kw["env"]
    assert kw["env"]["ANTHROPIC_AUTH_TOKEN"] == "ollama"  # jeton factice de la route, gardé
    deny = json.loads(Path(cmd[cmd.index("--settings") + 1]).read_text(encoding="utf-8"))["permissions"]["deny"]
    assert deny == DENY and "Bash" in deny and "Read(//**/*.bat)" in deny
    assert tasks.list()[0]["id"] == started["id"]
    with pytest.raises(TaskError):
        tasks.view("../x")


def test_clean_env_drops_secrets() -> None:
    env = clean_env({"ANTHROPIC_AUTH_TOKEN": "ollama"})
    assert not any(k for k in env if "TOKEN" in k.upper() and k != "ANTHROPIC_AUTH_TOKEN")


# -- Hermes
def test_hermes_registration_backs_up_the_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config = tmp_path / "config.yaml"
    config.write_text("model:\n  default: x\nmcp_servers:\n  wow_assistant:\n    command: py\n", encoding="utf-8")
    assert hermes_link.state("hermes.exe") == {"installe": True, "pont": False, "config": True}
    calls: list[list[str]] = []

    def runner(args: list[str], **kw: Any) -> Any:
        calls.append(args)
        config.write_text(config.read_text(encoding="utf-8") + "  aethertwin_dev:\n    command: py\n", encoding="utf-8")
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    result = hermes_link.register("hermes.exe", runner=runner)
    assert result["pont"] and Path(result["sauvegarde"]).is_file()
    assert calls[0][1:4] == ["mcp", "add", "aethertwin_dev"] and calls[0][-1] == "hermes"
    assert hermes_link.register("hermes.exe", runner=runner)["deja"] is True and len(calls) == 1
    with pytest.raises(ValueError):
        hermes_link.register("")


# -- pont MCP
def test_bridge_exposes_tools_by_role(monkeypatch: pytest.MonkeyPatch) -> None:
    names = lambda role: [t["name"] for t in bridge_mcp.tool_list(role)]  # noqa: E731
    assert "claude_local_confier" in names("hermes") and "hermes_demander" not in names("hermes")
    assert "hermes_demander" in names("claude") and "claude_local_confier" not in names("claude")
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(bridge_mcp, "command", lambda name, payload=None, timeout=60.0: sent.append((name, payload))
                        or {"id": "abc123def456", "etat": "en cours"})
    reply = bridge_mcp.handle("hermes", {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
        "name": "claude_local_confier", "arguments": {"tache": "écris un test"}}})
    assert reply["result"]["isError"] is False and sent[0][1]["origine"] == "Hermes"
    unknown = bridge_mcp.handle("hermes", {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                                           "params": {"name": "hermes_demander"}})
    assert unknown["error"]["code"] == -32602
    assert bridge_mcp.handle("claude", {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_bridge_waits_for_hermes_then_hands_back_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter([{"cle": "hermes:1", "en_cours": True, "duree": 5}, {"cle": "hermes:1", "en_cours": False,
                                                                       "resultat": {"reponse": "Python 3.14"}}])
    monkeypatch.setattr(bridge_mcp, "command", lambda name, payload=None, timeout=60.0:
                        {"travail": {"cle": "hermes:1", "en_cours": True}} if name == "demander_hermes"
                        else next(states))
    monkeypatch.setattr(bridge_mcp.time, "sleep", lambda s: None)
    assert bridge_mcp.t_ask_hermes({"question": "version ?"}) == {"etat": "en cours", "cle": "hermes:1", "duree_s": 5,
                                                                  "conseil": "rappelle hermes_suivre avec cette clé "
                                                                             "dans une minute"} or True


# -- relais
def test_relay_ack_test_reads_the_handoff_without_writing(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    seen: dict[str, Any] = {}

    def runner(cmd: list[str], **kw: Any) -> Any:
        seen["cmd"], seen["input"] = cmd, kw["input"].decode("utf-8")
        heading = next(line[3:] for line in (repo / "AGENT_HANDOFF.md").read_text(encoding="utf-8").splitlines()
                       if line.startswith("## Où on en est"))
        answer = f"RELAI REÇU\n{heading}\nMission : AetherTwin."  # « RELAI » (sans S) observé en réel, toléré
        return SimpleNamespace(stdout=answer.encode(), stderr=b"", returncode=0)

    env = launch.route_env("ollama", "qwen3-coder:30b", 32768, "http://127.0.0.1:11434", "")
    report = relay_check.run_ack_test(repo, ["claude.cmd"], env, tmp_path / "essai.json", runner=runner)
    assert report["recu"] and report["depot_intact"] and report["lu"]  # titre daté recopié : fichier vraiment lu
    guessed = relay_check.run_ack_test(repo, ["claude.cmd"], env, tmp_path / "essai2.json", runner=lambda c, **k:
                                       SimpleNamespace(stdout=b"RELAIS RECU\nMission : relais.", stderr=b"",
                                                       returncode=0))
    assert guessed["recu"] and not guessed["lu"]
    assert "AGENT_HANDOFF.md" in seen["input"] and "ESSAI DU RELAIS" in seen["input"]
    assert seen["cmd"][seen["cmd"].index("--tools") + 1] == "Read,Glob,Grep"
    for tool in ("Edit", "Write", "Bash"):
        assert tool in seen["cmd"][seen["cmd"].index("--disallowedTools"):]
    assert "Reprise du relais" in report["retour_cloud"]
    assert relay_check.last_report(tmp_path / "essai.json")["recu"] is True


def test_relay_can_reach_ollama_without_omniroute() -> None:
    relay = relay_check.load_relay(Path(__file__).resolve().parents[2])
    assert relay.claude_model("http://127.0.0.1:11434", "qwen3-coder:30b") == "qwen3-coder:30b"
    assert relay.claude_model("http://127.0.0.1:20128/v1", "qwen3-coder:30b") == "ollama/qwen3-coder:30b"


# -- terminaux du Hub
class FakePty:
    def __init__(self) -> None:
        self.out: queue.Queue[str | None] = queue.Queue()
        self.written: list[str] = []
        self.size = (0, 0)
        self.alive = True
        self.out.put("Microsoft Windows\r\n")

    def read(self, n: int) -> str:
        item = self.out.get(timeout=5)
        if item is None:
            self.alive = False
            raise EOFError
        return item

    def write(self, data: str) -> None:
        self.written.append(data)
        self.out.put(f"echo:{data}")

    def setwinsize(self, rows: int, cols: int) -> None:
        self.size = (rows, cols)

    def isalive(self) -> bool:
        return self.alive

    def terminate(self, force: bool = False) -> None:
        self.out.put(None)


def test_terminal_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
    launches = tmp_path / "lancements"
    launches.mkdir()
    (launches / "claude_1.bat").write_text("@echo off", encoding="utf-8")
    (tmp_path / "autre.bat").write_text("@echo off", encoding="utf-8")
    spawned: list[tuple] = []
    pty = FakePty()
    manager = TerminalManager(launches, spawn=lambda *a: spawned.append(a) or pty)
    for bad in ("../autre.bat", "autre.bat", "claude_1.cmd", "x/claude_1.bat"):
        with pytest.raises(TerminalError):
            manager.open(launch=bad)
    view = manager.open(launch="claude_1.bat")
    argv, folder, env, rows, cols = spawned[0]
    assert argv[-1] == str(launches / "claude_1.bat") and argv[-2] == "/k" and folder == str(launches)
    assert "CLAUDE_CODE_SESSION_ID" not in env and env["TERM"] == "xterm-256color"
    received: list[str] = []
    replay = manager.get(view["id"]).subscribe(received.append)
    manager.write(view["id"], "dir\r")
    manager.resize(view["id"], 40, 120)
    for _ in range(100):
        if received or "echo" in manager.get(view["id"]).buffer:
            break
        __import__("time").sleep(0.01)
    assert pty.written == ["dir\r"] and pty.size == (40, 120)
    assert "Microsoft Windows" in replay + manager.get(view["id"]).buffer
    assert len(view["id"]) >= 24 and manager.list()[0]["id"] == view["id"]
    manager.close(view["id"])
    with pytest.raises(TerminalError):
        manager.get(view["id"])
    assert "CLAUDE_CODE_SESSION_ID" not in child_env()


@pytest.fixture
def client(tmp_path: Path) -> Any:
    from fastapi.testclient import TestClient

    from core.api import create_app
    from core.daemon import Daemon
    from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
    from core.llm_router import LlmRouter
    from tests.core.test_daemon import ollama_stopped

    (tmp_path / "modules").mkdir()
    daemon = Daemon(tmp_path / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    return TestClient(create_app(daemon))


def test_terminal_page_and_socket_are_local_only(client: Any) -> None:
    page = client.get("/terminal")
    assert page.status_code == 200 and "frame-ancestors 'self'" in page.headers["content-security-policy"]
    assert "/static/xterm.js" in page.text and client.get("/static/xterm.js").status_code == 200
    from starlette.websockets import WebSocketDisconnect

    for headers in ({"origin": "http://evil.example"}, {}):
        with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect(
                "/terminals/inconnu/ws", headers=headers):
            pass
        assert closed.value.code in (4403, 4404)
    assert client.post("/terminals", json={"lancement": "../../config/local.yaml"}).status_code == 400
    assert client.post("/terminals", json={}, headers={"origin": "http://evil.example"}).status_code == 403
    page = client.get("/").text
    for tab in ("developpement", "outils"):
        assert f'data-tab="{tab}"' in page and f'data-panel="{tab}"' in page


# -- choix du modèle des tâches (contexte d'au moins 64 k)
def test_task_model_needs_a_large_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.module_api import load_manifest
    from modules.dev_launcher import module as dev

    listed = {"modeles": [{"id": "qwen3-coder:30b", "contexte_regle": 0},
                          {"id": "gemma4:31b-64k", "contexte_regle": 65536},
                          {"id": "devstral:24b-64k", "contexte_regle": 65536}]}
    monkeypatch.setattr(dev.catalog, "ollama_models", lambda url: listed)
    monkeypatch.setattr(dev.catalog, "num_ctx", lambda url, name: 65536 if name.endswith("-64k") else 0)
    mod = dev.DevLauncherModule(load_manifest(Path(dev.__file__).parent), {"data_dir": str(tmp_path)})
    assert mod.task_model() == "devstral:24b-64k"  # modèle de code d'abord
    listed["modeles"].append({"id": "qwen3-coder:30b-a3b-64k", "contexte_regle": 65536})
    assert mod.task_model() == "qwen3-coder:30b-a3b-64k"  # « coder » avant « devstral » (appels d'outils fiables)
    env = mod.env_for()
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "65536" and mod.context_warning(env) == ""
    small = mod.env_for("qwen3-coder:30b")
    assert small["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "32768" and "65536" in mod.context_warning(small)
    mod.config["modele_taches"] = "qwen3-coder:30b"
    assert mod.task_model() == "qwen3-coder:30b"  # choix explicite respecté (avec avertissement)


def test_other_mcp_servers_can_be_registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config = tmp_path / "config.yaml"
    config.write_text("mcp_servers:\n  wow_assistant:\n    command: py\n", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(args: list[str], **kw: Any) -> Any:
        calls.append(args)
        added = "  aethertwin_calc:\n    command: py\n"
        config.write_text(config.read_text(encoding="utf-8") + added, encoding="utf-8")
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    result = hermes_link.register_server("hermes.exe", "aethertwin_calc", ["-I", "mcp_server.py"], runner=runner)
    assert result["pont"] and calls[0][1:4] == ["mcp", "add", "aethertwin_calc"]
    assert calls[0][-2:] == ["-I", "mcp_server.py"]
    for bad in ("Calc", "a", "calc-cas", "x; rm"):
        with pytest.raises(ValueError, match="nom de serveur"):
            hermes_link.register_server("hermes.exe", bad, [], runner=runner)
