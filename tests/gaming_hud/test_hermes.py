"""Hermes Agent dans WoW Assistant : outils de jeu (serveur MCP), pont vers Hermes (API, CLI, mise en place),
conversation partagée (onglet, widgets Assistant et Coach).

Aucun Hermes réel n'est lancé : le dossier de Hermes est simulé dans un dossier temporaire, l'API par un faux
`urlopen` et la CLI par un faux lanceur. AETHERTWIN_SHOTS=<dossier> enregistre les captures des écrans rendus.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pygame
import pytest

KEY = "k" * 64


def shot(ui, name: str) -> None:
    folder = os.environ.get("AETHERTWIN_SHOTS")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        pygame.image.save(ui.screen, str(Path(folder) / f"{name}.png"))


# --------------------------------------------------------------------------- faux Hermes
def fake_home(tmp_path: Path, api=True, mcp=False, skill=False) -> Path:
    home = tmp_path / "hermes"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "hermes.exe").write_bytes(b"")
    (home / "gateway_state.json").write_text(json.dumps({"code_version": "0.23.2", "gateway_state": "running",
                                                         "pid": os.getpid()}), encoding="utf-8")
    env = "OPENAI_API_KEY=secret-ne-pas-afficher\n" + ("API_SERVER_ENABLED=true\nAPI_SERVER_KEY=" + KEY + "\n" if api
                                                       else "API_SERVER_ENABLED=false\n")
    (home / ".env").write_text(env, encoding="utf-8")
    config = "model:\n  default: qwen3:14b\n  provider: ollama\n"
    if mcp:
        config += "mcp_servers:\n  wow_assistant:\n    command: python\n"
    (home / "config.yaml").write_text(config, encoding="utf-8")
    if skill:
        target = home / "skills" / "gaming" / "wow-coach"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("---\nname: wow-coach\n---\n", encoding="utf-8")
    return home


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeOpener:
    """Faux urlopen : session, flux SSE de réponse, autorisation."""

    def __init__(self, events):
        self.events, self.calls = events, []

    def __call__(self, request, timeout=30):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        self.calls.append((request.get_method(), request.full_url, body, dict(request.header_items())))
        url = request.full_url
        if url.endswith("/api/sessions"):
            return FakeResponse(b'{"session": {"id": "s42"}}')
        if url.endswith("/chat/stream"):
            sse = "".join(f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in self.events)
            return FakeResponse((": ping\n\n" + sse).encode("utf-8"))
        return FakeResponse(b"{}")


class Settings(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def set(self, key, value):
        self[key] = value

    def save(self):
        return True


@pytest.fixture
def hb(monkeypatch):
    import hermes_bridge
    monkeypatch.setattr(hermes_bridge, "_port_open", lambda port, host="127.0.0.1", timeout=0.3: True)
    return hermes_bridge


def wait(job, seconds=5.0):
    import time
    end = time.monotonic() + seconds
    while not job.done and time.monotonic() < end:
        time.sleep(0.01)
    assert job.done


# --------------------------------------------------------------------------- serveur MCP (outils de jeu)
class FakeGame:
    def __init__(self):
        self.snap = {
            "character": {"name": "Sakuranïchan", "realm": "Hyjal", "level": 48, "class": "Druide",
                          "specialization": "Équilibre", "zone": "Forêt d'Elwynn", "money": 1234567, "ilvl": 301},
            "equipment": [{"slot": 1, "name": "|cff0070ddCasque du vent|r", "ilvl": 300, "quality": 3, "id": 11}],
            "quests": {}, "bags": {}, "professions": [],
        }

    def snapshot(self):
        return self.snap

    def source(self):
        return "test"

    def bestiary(self):
        return []

    def activity(self):
        return []


def test_mcp_server_speaks_json_rpc_and_lists_read_only_tools() -> None:
    import hermes_mcp
    game = FakeGame()
    init = hermes_mcp.handle(game, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                    "params": {"protocolVersion": "2025-03-26"}})
    assert init["result"]["protocolVersion"] == "2025-03-26" and "tools" in init["result"]["capabilities"]
    assert hermes_mcp.handle(game, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = hermes_mcp.handle(game, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert len(tools) == 12
    assert [t["name"] for t in tools if not t["annotations"]["readOnlyHint"]] == ["wow_knowledge_save"]
    assert {t["name"] for t in tools} >= {"wow_character", "wow_quests", "wow_inventory", "wow_bestiary"}
    unknown = hermes_mcp.handle(game, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                       "params": {"name": "rm_rf", "arguments": {}}})
    assert unknown["error"]["code"] == -32602


def test_mcp_character_tool_returns_clean_game_text() -> None:
    import hermes_mcp
    reply = hermes_mcp.handle(FakeGame(), {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                           "params": {"name": "wow_character", "arguments": {}}})
    content = reply["result"]["content"][0]["text"]
    assert reply["result"]["isError"] is False
    assert "Sakuranïchan" in content and "Casque du vent" in content and "|c" not in content
    assert hermes_mcp.clean_codes("|cffff0000Rouge|r |TInterface\\Icons\\x:0|t ok").strip().endswith("ok")


def test_mcp_serve_answers_one_line_per_request() -> None:
    import hermes_mcp
    stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n\nnot json\n'
                        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    stdout = io.StringIO()
    hermes_mcp.serve(stdin, stdout, FakeGame())
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0] == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert lines[1]["error"]["code"] == -32700 and len(lines) == 2


# --------------------------------------------------------------------------- état de Hermes sur le PC
def test_hermes_info_reads_the_install_without_exposing_secrets(tmp_path, hb) -> None:
    info = hb.HermesInfo(str(fake_home(tmp_path, mcp=True, skill=True)))
    st = info.refresh()
    assert st["found"] and st["gateway"] and st["api_up"] and st["skill"] and st["mcp"]
    assert st["version"] == "0.23.2" and st["model"] == "qwen3:14b"
    assert st["api_key"] is True and KEY not in json.dumps(st) and "secret-ne-pas-afficher" not in json.dumps(st)


def test_mcp_registered_only_inside_mcp_servers_section(hb) -> None:
    assert hb.mcp_registered("mcp_servers:\n  wow_assistant:\n    command: py\n")
    assert not hb.mcp_registered("toolsets:\n  wow_assistant:\nmcp_servers:\n  autre:\n")
    assert not hb.mcp_registered("mcp_servers:\n  autre: {}\nwow_assistant:\n")


def test_parse_sse_handles_comments_multiline_and_names(hb) -> None:
    stream = [b": keepalive\n", b"event: assistant.delta\n", b'data: {"delta": "Bon"}\n', b"\n",
              b'data: {"event": "done"}\n', b"\n"]
    assert list(hb.parse_sse(stream)) == [("assistant.delta", {"delta": "Bon"}), ("done", {"event": "done"})]


# --------------------------------------------------------------------------- conversation par l'API
def test_api_streams_answer_tools_and_reuses_the_session(tmp_path, hb) -> None:
    events = [("run.started", {"run_id": "r1"}), ("tool.started", {"tool_name": "mcp_wow_assistant_wow_quests",
                                                                   "preview": "{}"}),
              ("assistant.delta", {"delta": "Fais "}), ("assistant.delta", {"delta": "la quête X."}),
              ("assistant.completed", {"content": "Fais la quête X."}), ("run.completed", {}), ("done", {})]
    opener = FakeOpener(events)
    settings = Settings()
    client = hb.HermesClient(settings, hb.HermesInfo(str(fake_home(tmp_path))), opener=opener)
    assert client.transport() == "api"
    job = client.ask("Que faire ?", images=[("image/png", "QUJD")])
    wait(job)
    assert job.error == "" and job.text == "Fais la quête X." and job.run_id == "r1"
    assert [kind for _t, kind, _x in job.events] == ["tool"] and "Données : quêtes" in job.events[0][2]
    assert settings["hermes.session_id"] == "s42"
    method, url, body, headers = opener.calls[1]
    assert url == "http://127.0.0.1:8642/api/sessions/s42/chat/stream"
    assert body["message"][1]["image_url"]["url"] == "data:image/png;base64,QUJD"
    assert headers["Authorization"] == "Bearer " + KEY
    wait(client.ask("Et ensuite ?"))
    assert sum(1 for c in opener.calls if c[1].endswith("/api/sessions")) == 1      # même session Hermes


def test_approval_is_only_granted_by_the_player(tmp_path, hb) -> None:
    opener = FakeOpener([])
    client = hb.HermesClient(Settings(), hb.HermesInfo(str(fake_home(tmp_path))), opener=opener)
    job = hb.HermesJob("api")
    client._on_event(job, "approval.request", {"run_id": "r9", "command": "del x", "description": "Supprimer",
                                               "choices": ["once", "session", "always", "deny"]})
    assert job.approval and job.status() == "En attente de votre autorisation"
    assert not [c for c in opener.calls if "approval" in c[1]]
    assert client.approve(job, "deny") is True and job.approval is None
    assert opener.calls[-1][1].endswith("/v1/runs/r9/approval") and opener.calls[-1][2] == {"choice": "deny"}


# --------------------------------------------------------------------------- CLI (sans réglage)
def test_cli_mode_restricts_tools_and_recalls_history(tmp_path, hb) -> None:
    home = fake_home(tmp_path, api=False, mcp=True, skill=True)
    seen = {}

    class Proc:
        returncode = 0

        def __init__(self, args, **kwargs):
            seen["args"], seen["kwargs"] = args, kwargs

        def communicate(self, timeout=None):
            return "Réponse CLI".encode(), b""

    client = hb.HermesClient(Settings(), hb.HermesInfo(str(home)), runner=Proc)
    assert client.transport() == "cli"
    job = client.ask("Mes talents ?", images=[("image/png", "x")],
                     history=[("user", "Bonjour"), ("assistant", "Salut")])
    wait(job)
    args = seen["args"]
    assert job.text == "Réponse CLI" and args[1] == "-z"
    toolsets = args[args.index("-t") + 1].split(",")
    assert "mcp-wow_assistant" in toolsets and not {"terminal", "file", "browser", "code_execution"} & set(toolsets)
    assert args[args.index("-s") + 1] == "wow-coach"
    assert "Joueur : Bonjour" in args[2] and "capture" in args[2]
    assert seen["kwargs"]["stdin"] is not None and seen["kwargs"]["cwd"]


def test_no_hermes_gives_a_clear_error(tmp_path, hb, monkeypatch) -> None:
    monkeypatch.setattr(hb.shutil, "which", lambda name: None)
    client = hb.HermesClient(Settings(), hb.HermesInfo(str(tmp_path / "absent")))
    job = client.ask("?")
    assert job.done and "introuvable" in job.error and not client.is_configured()


# --------------------------------------------------------------------------- mise en place (boutons de l'onglet)
def test_install_skill_copies_wow_coach(tmp_path, hb) -> None:
    info = hb.HermesInfo(str(fake_home(tmp_path)))
    ok, _text = hb.install_skill(info)
    skill = Path(info.skill_path()).read_text(encoding="utf-8")
    assert ok and info.refresh()["skill"] and "name: wow-coach" in skill


def test_register_mcp_uses_hermes_own_command_with_backup(tmp_path, hb) -> None:
    home = fake_home(tmp_path)
    info = hb.HermesInfo(str(home))
    seen = {}

    def runner(args, **kwargs):
        seen["args"], seen["input"] = args, kwargs.get("input")
        with open(home / "config.yaml", "a", encoding="utf-8") as f:
            f.write("mcp_servers:\n  wow_assistant:\n    command: python\n")
        return type("R", (), {"stdout": "", "stderr": ""})()

    ok, text = hb.register_mcp(info, python=r"C:\Python311\pythonw.exe", runner=runner)
    assert ok and "12 outils" in text and seen["input"] == "y\n"
    assert seen["args"][1:6] == ["mcp", "add", "wow_assistant", "--command", r"C:\Python311\python.exe"]
    assert seen["args"][-2:] == ["-I", hb.MCP_SCRIPT]
    assert list(home.glob("config.yaml.wow-assistant-*.bak"))


def test_enable_api_adds_a_key_keeps_other_lines_and_never_reports_it(tmp_path, hb) -> None:
    home = fake_home(tmp_path, api=False)
    info = hb.HermesInfo(str(home))
    ok, text = hb.enable_api(info)
    env = hb.read_env(str(home / ".env"))
    assert ok and env["API_SERVER_ENABLED"] == "true" and len(env["API_SERVER_KEY"]) == 64
    assert env["OPENAI_API_KEY"] == "secret-ne-pas-afficher" and env["API_SERVER_KEY"] not in text
    assert list(home.glob(".env.wow-assistant-*.bak"))
    hb.enable_api(info)
    assert hb.read_env(str(home / ".env"))["API_SERVER_KEY"] == env["API_SERVER_KEY"]   # clé existante gardée


# --------------------------------------------------------------------------- conversation partagée
class FakeHermes:
    def __init__(self):
        self.asked, self.stopped, self.approved, self.new = [], [], [], 0

    def is_configured(self):
        return True

    def describe(self):
        return "Hermes 0.23.2 · API de la passerelle"

    def ask(self, prompt, images=None, history=None):
        import hermes_bridge
        self.asked.append((prompt, images, history))
        self.job = hermes_bridge.HermesJob("api")
        return self.job

    def stop(self, job):
        self.stopped.append(job)

    def approve(self, job, choice):
        self.approved.append(choice)

    def new_session(self):
        self.new += 1


def test_chat_with_hermes_sends_history_and_keeps_tools(tmp_path) -> None:
    from llm import LLMClient
    from widgets_builtin import ChatState
    fake = FakeHermes()
    llm = LLMClient(Settings({"llm.mode": "hermes"}), hermes=fake)
    chat = ChatState(str(tmp_path / "chat.json"), llm)
    chat.messages = [{"role": "user", "text": "Salut"}, {"role": "assistant", "text": "Bonjour !"}]
    assert chat.submit("Que faire ?", None, [("image/png", "x")])
    prompt, images, history = fake.asked[0]
    assert prompt == "Que faire ?" and images == [("image/png", "x")]
    assert history == [("user", "Salut"), ("assistant", "Bonjour !")]
    job = fake.job
    job.note("tool", "Données : quêtes")
    job.text, job.done = "Va à Comté-du-Lac.", True
    chat.poll()
    assert chat.messages[-1] == {"role": "assistant", "text": "Va à Comté-du-Lac.", "tools": ["Données : quêtes"]}
    chat.new_conversation()
    assert chat.messages == [] and fake.new == 1


def test_chat_without_hermes_keeps_the_old_call(tmp_path) -> None:
    from widgets_builtin import ChatState

    class OldLLM:
        def is_configured(self):
            return True

        def ask(self, prompt, images=None):
            self.prompt = prompt
            return type("J", (), {"done": False, "text": "", "error": ""})()

    old = OldLLM()
    chat = ChatState(str(tmp_path / "chat.json"), old)
    assert chat.submit("Bonjour", None)
    chat.stop()
    assert chat.job is None and chat.messages[-1]["text"] == "Arrêté."


def test_markdown_from_hermes_is_shown_as_plain_text() -> None:
    import chatview
    text = "## Plan\n- **Quête** `X` [Wowhead](https://www.wowhead.com/fr/quest=1)\n```\ncode\n```"
    assert chatview.plain(text) == "Plan\n• Quête X Wowhead (https://www.wowhead.com/fr/quest=1)\ncode"


# --------------------------------------------------------------------------- onglet Hermes et widgets
@pytest.fixture
def hermes_app(app, tmp_path, hb):
    app.settings.set("llm.mode", "hermes")
    app.llm._hermes = hb.HermesClient(app.settings, hb.HermesInfo(str(fake_home(tmp_path, mcp=True))),
                                      opener=FakeOpener([]))
    app.active_tab = app.TABS.index("Hermes")
    from coach_knowledge import KnowledgeBase
    app.knowledge = KnowledgeBase(str(tmp_path / "coach_knowledge.json"))   # jamais celle du profil Windows
    return app


def _busy_job(app, approval=False):
    import hermes_bridge
    job = hermes_bridge.HermesJob("api")
    job.note("tool", "Données : personnage")
    job.note("tool", "Recherche web : meilleur équipement druide équilibre niveau 48")
    job.text = "Voici un plan **court** :\n- Termine la quête de la Garde de Hurlevent\n- Améliore tes bottes"
    if approval:
        job.approval = {"run_id": "r1", "command": "powershell Get-Process", "description": "Lister les processus",
                        "choices": ["once", "session", "always", "deny"]}
    app.chat.job = job
    return job


def test_hermes_tab_renders_status_setup_and_chat_without_cut_text(hermes_app) -> None:
    app = hermes_app
    app.chat.messages = [{"role": "user", "text": "Que faire maintenant ?"},
                         {"role": "assistant", "text": "1. **Rends** la quête.\n2. Va à Comté-du-Lac.",
                          "tools": ["Données : quêtes : {}", "Recherche web : x"]}]
    app.draw(app.test_ctx)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    shot(app, "hermes_tab")
    _busy_job(app, approval=True)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    shot(app, "hermes_tab_approval")


def test_hermes_tab_buttons_switch_assistant_and_transport(hermes_app) -> None:
    app = hermes_app
    app.settings.set("llm.mode", "api")
    app.draw(app.test_ctx)
    use = [fn for rect, fn in app._buttons if rect.w == 400 - 32 and rect.h == 30]
    use[0]()                                            # « Utiliser Hermes comme assistant »
    assert app.settings.get("llm.mode") == "hermes"


def test_overlay_assistant_and_coach_widgets_render(hermes_app) -> None:
    from widgets_builtin import draw_assistant, draw_coach
    app = hermes_app
    app.chat.messages = [{"role": "assistant", "text": "Dernier conseil : répare ton équipement."}]
    _busy_job(app, approval=True)
    app.screen.fill((0, 0, 0))
    app._buttons, app._tips, app._scroll_regions, app._scrollbars = [], [], [], []
    app.screen.cut.clear()
    draw_assistant(app, app.test_ctx, (20, 20, 440, 420))
    draw_coach(app, app.test_ctx, (500, 20, 380, 300))
    assert app.screen.cut == []
    shot(app, "hermes_widgets")
    stop = [fn for rect, fn in app._buttons if rect.collidepoint(500 + 380 - 20, 30)]
    job = app.chat.job
    stop[0]()                                           # « Stop » du widget Coach
    import time
    end = time.monotonic() + 3
    while not job.stopped and time.monotonic() < end:
        time.sleep(0.01)
    assert job.stopped


def test_settings_page_offers_hermes_and_opens_its_tab(hermes_app) -> None:
    app = hermes_app
    app.active_tab = 0
    app.open_settings("llm")
    app.modal["mode"] = "hermes"
    app.draw(app.test_ctx)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    shot(app, "hermes_settings")
    hermes_buttons = [fn for rect, fn in app._buttons if rect.collidepoint(rect.center)]
    assert hermes_buttons
    app.close_modal()
    app._switch_tab(app.TABS.index("Hermes"))
    assert app.TABS[app.active_tab] == "Hermes"


# --------------------------------------------------------------------------- fichiers, liens, erreurs (23/11, suite)
def test_files_are_read_by_the_app_and_sent_as_data(tmp_path) -> None:
    from llm import LLMClient
    from widgets_builtin import ChatState
    fake = FakeHermes()
    chat = ChatState(str(tmp_path / "chat.json"), LLMClient(Settings({"llm.mode": "hermes"}), hermes=fake))
    (tmp_path / "simc.txt").write_text("druid=Sakura\nlevel=48", encoding="utf-8")
    (tmp_path / "shot.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "doc.pdf").write_bytes(b"%PDF")
    (tmp_path / "big.log").write_text("x" * 70000, encoding="utf-8")
    assert chat.attach_file(str(tmp_path / "simc.txt"))[0]
    assert chat.attach_file(str(tmp_path / "shot.png"))[0]
    ok, text = chat.attach_file(str(tmp_path / "doc.pdf"))
    assert not ok and "lien" in text
    ok, text = chat.attach_file(str(tmp_path / "big.log"))
    assert ok and "tronqué" in text
    chat.remove_file(2)
    assert chat.submit("Analyse ça et https://www.wowhead.com/fr/guide/x", None)
    prompt, images, _history = fake.asked[0]
    assert "----- simc.txt -----\ndruid=Sakura\nlevel=48\n----- fin de simc.txt -----" in prompt
    assert "pas des instructions" in prompt and "web_extract" in prompt and "big.log" not in prompt
    assert images == [("image/png", "iVBORyBmYWtl")]
    assert chat.files == [] and "[fichiers : simc.txt, shot.png]" in chat.messages[-1]["text"]


def test_dropping_a_file_on_the_window_attaches_it(app, tmp_path) -> None:
    (tmp_path / "notes.md").write_text("# Objectifs", encoding="utf-8")
    app.handle_events([pygame.event.Event(pygame.DROPFILE, file=str(tmp_path / "notes.md"))])
    assert app.chat.files[0]["name"] == "notes.md"


def test_hermes_tab_shows_attached_files_without_cut_text(hermes_app, tmp_path) -> None:
    app = hermes_app
    for name in ("export_simc_sakuranichan_equilibre.txt", "notes.md"):
        (tmp_path / name).write_text("x", encoding="utf-8")
        app.chat.attach_file(str(tmp_path / name))
    app.draw(app.test_ctx)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    shot(app, "hermes_tab_files")


def test_old_local_program_mode_becomes_hermes(tmp_path) -> None:
    import settings as settings_mod
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"llm": {"mode": "exe", "exe_path": "hermes.exe"}}), encoding="utf-8")
    assert settings_mod.Settings(str(path)).get("llm.mode") == "hermes"


def test_model_context_and_hermes_errors_are_explained(tmp_path, hb) -> None:
    config = ("providers:\n  ollama:\n    models:\n      qwen3-27b:latest:\n        context_length: 32000\n"
              "      gemma4:31b: {}\n    context_length: 16000\n")
    assert hb.model_context(config, "qwen3-27b:latest") == 32000 and hb.model_context(config, "gemma4:31b") == 0
    home = fake_home(tmp_path)
    (home / "logs").mkdir()
    import time
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    (home / "logs" / "errors.log").write_text(
        f"2020-01-01 00:00:00,000 ERROR ancien\nValueError: vieux\n{now},110 ERROR run\nTraceback...\n"
        "ValueError: Model qwen3-27b:latest has a context window of 32,000 tokens, which is below the minimum "
        "64,000 required by Hermes Agent.\n", encoding="utf-8")
    detail = hb.last_error(str(home), time.time())
    explained = hb.explain_error(detail)
    assert "32,000" in explained and "64,000" in explained and "Contexte" in explained

    class Proc:
        returncode = 0

        def __init__(self, args, **kwargs):
            pass

        def communicate(self, timeout=None):
            return "⚠️ Something went wrong and I couldn't finish this reply.".encode(), b""

    client = hb.HermesClient(Settings(), hb.HermesInfo(str(home)), runner=Proc)
    client.settings.set("hermes.transport", "cli")
    job = client.ask("?")
    wait(job)
    assert job.text == "" and "Contexte" in job.error


def test_reasoning_level_is_sent_on_both_paths(tmp_path, hb) -> None:
    home = fake_home(tmp_path, api=False)
    client = hb.HermesClient(Settings(), hb.HermesInfo(str(home)))
    args = client.cli_args("?")
    assert args[args.index("--reasoning") + 1] == "medium"                 # défaut : « high » refusé par Qwen 3.5
    client.settings.set("hermes.reasoning", "hermes")
    assert "--reasoning" not in client.cli_args("?")
    opener = FakeOpener([("assistant.completed", {"content": "ok"}), ("done", {})])
    api = hb.HermesClient(Settings({"hermes.reasoning": "low"}), hb.HermesInfo(str(fake_home(tmp_path / "b"))),
                          opener=opener)
    wait(api.ask("?"))
    assert opener.calls[-1][2]["model_options"] == {"reasoning_effort": "low"}
    assert "Réflexion" in hb.explain_error("HTTP 500: Jinja Exception: Unexpected reasoning effort high.")


def test_desktop_app_is_launched_detached_from_the_app_console(tmp_path, hb) -> None:
    import subprocess
    home = fake_home(tmp_path)
    exe = home / "hermes-agent" / "apps" / "desktop" / "release" / "win-unpacked" / "Hermes.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    seen = {}

    def runner(args, **kwargs):
        seen.update(kwargs, args=args)

    ok, _text = hb.open_desktop(hb.HermesInfo(str(home)), runner=runner)
    assert ok and seen["args"] == [str(exe)] and seen["stdout"] is subprocess.DEVNULL
    if hasattr(subprocess, "DETACHED_PROCESS"):
        assert seen["creationflags"] & subprocess.DETACHED_PROCESS


def test_restart_gateway_runs_hermes_command_and_waits_for_the_api(tmp_path, hb) -> None:
    seen = {}

    def runner(args, **kwargs):
        seen["args"] = args
        return type("R", (), {"stdout": "", "stderr": ""})()

    ok, text = hb.restart_gateway(hb.HermesInfo(str(fake_home(tmp_path))), runner=runner, wait=1)
    assert ok and seen["args"][1:] == ["gateway", "restart"] and "API en marche" in text


def test_tool_labels_and_ready_made_figures_for_the_model(hb) -> None:
    import hermes_mcp
    assert hb._tool_label("mcp_wow_assistant__wow_character", "") == "Données : personnage"
    assert hb._tool_label("mcp_wow_assistant_wow_quests", "") == "Données : quêtes"
    assert hermes_mcp._xp_progress({"xp": 10027, "xpMax": 39165}) == \
        "25.6 % du niveau en cours, 29138 XP restants avant le niveau suivant"
    assert hermes_mcp.QUALITIES[2] == "inhabituel (vert)"


# --------------------------------------------------------------------------- base de connaissances du coach
def test_knowledge_base_player_corrections_win_and_web_facts_need_a_source(tmp_path) -> None:
    import time

    from coach_knowledge import REVERIFY_DAYS, KnowledgeBase
    kb = KnowledgeBase(str(tmp_path / "kb.json"))
    ok, msg, _e = kb.add("talents", "Talents de héros : niveau", "Disponibles au niveau 71.", source="")
    assert not ok and "lien" in msg
    assert kb.add("talents", "Talents de héros : niveau", "Disponibles au niveau 71.",
                  source="https://www.wowhead.com/fr/guide/hero-talents")[0]
    assert kb.add("règle", "Touche des talents", "La fenêtre des talents s'ouvre avec N.", source="joueur",
                  status="joueur")[0]
    ok, msg, _e = kb.add("règle", "Touche des talents", "R", source="https://exemple.fr")
    assert not ok and "joueur" in msg                                          # le web ne remplace pas le joueur
    found = kb.search("quel niveau pour les talents de héros")
    assert found[0]["statut"].startswith("corrigé par le joueur")             # la règle du joueur passe d'abord
    assert any("71" in f["fait"] for f in found)
    entry = next(e for e in kb.entries if e["status"] == "sourcé")
    entry["verified"] = time.time() - (REVERIFY_DAYS + 1) * 86400
    assert kb.stats()["à revérifier"] == 1
    assert kb.set_status(entry["id"], "rejeté") and not any("71" in f["fait"] for f in kb.search("talents héros"))
    again = KnowledgeBase(str(tmp_path / "kb.json"))                           # relu depuis le fichier
    assert len(again.entries) == 2


def test_mcp_knowledge_tools_read_and_write_the_coach_base(tmp_path) -> None:
    import hermes_mcp
    from coach_knowledge import KnowledgeBase
    game = FakeGame()
    kb = KnowledgeBase(str(tmp_path / "kb.json"))
    game.knowledge = lambda: kb
    save = hermes_mcp.call_tool(game, "wow_knowledge_save", {
        "topic": "quête", "subject": "La chute du Trompeur", "fact": "Dernière quête de la campagne ; ne donne "
        "plus d'XP.", "source_url": "https://www.wowhead.com/fr/quest=46805"})
    assert json.loads(save["content"][0]["text"])["enregistré"] is True
    found = json.loads(hermes_mcp.call_tool(game, "wow_knowledge_search", {"query": "Trompeur"})["content"][0]["text"])
    assert found["connaissances"][0]["source"] == "https://www.wowhead.com/fr/quest=46805"
    refused = hermes_mcp.call_tool(game, "wow_knowledge_save", {"topic": "quête", "subject": "x", "fact": "y"})
    assert json.loads(refused["content"][0]["text"])["enregistré"] is False


def test_player_correction_is_saved_and_recalled_to_hermes(tmp_path) -> None:
    from coach_knowledge import KnowledgeBase
    from llm import LLMClient
    from widgets_builtin import ChatState
    fake = FakeHermes()
    chat = ChatState(str(tmp_path / "chat.json"), LLMClient(Settings({"llm.mode": "hermes"}), hermes=fake))
    chat.knowledge = KnowledgeBase(str(tmp_path / "kb.json"))
    chat.messages = [{"role": "user", "text": "Analyse mon perso"},
                     {"role": "assistant", "text": "Choisis ton talent de héros."}]
    assert chat.correct("Les talents de héros ne s'ouvrent pas au niveau 48.", None)
    entry = chat.knowledge.entries[0]
    assert entry["status"] == "joueur" and entry["question"] == "Analyse mon perso"
    assert "Correction du joueur" in fake.asked[-1][0]
    fake.job.text, fake.job.done = "Compris.", True
    chat.poll()
    chat.submit("Que faire avec mes talents de héros ?", None)
    assert "Corrections du joueur à respecter" in fake.asked[-1][0]
    assert "ne s'ouvrent pas au niveau 48" in fake.asked[-1][0]


def test_knowledge_view_renders_without_cut_text(hermes_app) -> None:
    app = hermes_app
    kb = app.knowledge
    kb.add("règle", "Touche des talents", "La fenêtre des talents et de la spécialisation s'ouvre avec N "
           "(touche par défaut).", source="joueur", status="joueur")
    kb.add("build", "Farouche : statistiques (Midnight 12.0)", "Maîtrise > Coup critique > Hâte > Polyvalence "
           "pour Druid of the Claw, d'après le guide BiS de Wowhead. " * 2,
           source="https://www.wowhead.com/fr/guide/classes/druid/feral/stat-priority-pve-dps")
    app.state["hermes_view"] = "kb"
    app.draw(app.test_ctx)
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    shot(app, "hermes_knowledge")
    app.state["hermes_view"] = "chat"
    app.chat.messages = [{"role": "user", "text": "?"}, {"role": "assistant", "text": "Réponse."}]
    app.state["hermes_correcting"] = True
    app.screen.cut.clear()
    app.draw(app.test_ctx)
    assert app.screen.cut == []
    shot(app, "hermes_correcting")
