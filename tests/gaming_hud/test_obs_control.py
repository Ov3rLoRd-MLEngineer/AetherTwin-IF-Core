"""Pilotage d'OBS : protocole obs-websocket v5 joué contre un faux serveur local (aucun OBS requis)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from websockets.sync.server import serve

from modules.gaming_hud import obs_control
from modules.gaming_hud.obs_control import ObsClient, auth_string, call_tool
from modules.gaming_hud.obs_mcp import SERVER


class FakeObs:
    """Un OBS minimal : défi d'authentification, quelques requêtes, mémoire des appels."""

    def __init__(self, password: str | None = "secret-de-test") -> None:  # noqa: S107 - faux OBS de test
        self.password, self.calls, self.scenes = password, [], ["Scène"]
        self.inputs: dict[str, str] = {}
        self.server = serve(self.handler, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def handler(self, ws: Any) -> None:
        hello: dict[str, Any] = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
        if self.password:
            hello["authentication"] = {"challenge": "defi", "salt": "sel"}
        ws.send(json.dumps({"op": 0, "d": hello}))
        identify = json.loads(ws.recv())["d"]
        if self.password and identify.get("authentication") != auth_string(self.password, "sel", "defi"):
            ws.close(4009, "Authentication failed")
            return
        ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        for raw in ws:
            d = json.loads(raw)["d"]
            self.calls.append((d["requestType"], d["requestData"]))
            ok, data = self.answer(d["requestType"], d["requestData"])
            ws.send(json.dumps({"op": 7, "d": {"requestType": d["requestType"], "requestId": d["requestId"],
                                                "requestStatus": {"result": ok, "code": 100 if ok else 600,
                                                                  "comment": None if ok else "introuvable"},
                                                "responseData": data}}))

    def answer(self, kind: str, data: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        if kind == "GetVersion":
            return True, {"obsVersion": "32.0.0"}
        if kind == "GetSceneList":
            return True, {"currentProgramSceneName": self.scenes[0],
                          "scenes": [{"sceneName": s} for s in self.scenes]}
        if kind == "CreateScene":
            self.scenes.append(data["sceneName"])
            return True, {}
        if kind == "GetInputList":
            return True, {"inputs": [{"inputName": n, "inputKind": k} for n, k in self.inputs.items()]}
        if kind == "CreateInput":
            self.inputs[data["inputName"]] = data["inputKind"]
            return True, {"sceneItemId": len(self.inputs)}
        if kind == "GetSceneItemId":
            return (True, {"sceneItemId": 1}) if data["sourceName"] in self.inputs else (False, {})
        if kind == "GetInputPropertiesListPropertyItems":
            return True, {"propertyItems": [{"itemName": "[obs] AetherTwin", "itemValue": "AetherTwin:Chrome:x.exe",
                                             "itemEnabled": True}]}
        if kind == "GetVideoSettings":
            return True, {"baseWidth": 1920, "baseHeight": 1080}
        if kind == "StopRecord":
            return True, {"outputPath": "C:/video.mkv"}
        return True, {}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    obs = FakeObs()
    monkeypatch.setenv("OBS_WEBSOCKET_PORT", str(obs.port))
    monkeypatch.setenv("OBS_WEBSOCKET_PASSWORD", "secret-de-test")
    monkeypatch.setenv("AETHERTWIN_OBS_OUT", str(tmp_path / "sortie"))
    yield obs
    obs.server.shutdown()


def test_auth_string_matches_protocol_example() -> None:
    # Exemple de la documentation d'obs-websocket v5 (mot de passe « supersecretpassword »).
    assert auth_string("supersecretpassword", "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=",
                       "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY=") == "1Ct943GAT+6YQUUX47Ia/ncufilbe6+oD6lY+5kaCu4="


def test_status_scene_capture_and_record(fake: FakeObs) -> None:
    assert call_tool("obs_status", {})["result"]["version"] == "32.0.0"
    assert call_tool("obs_create_scene", {"scene": "Démo"})["ok"] and "Démo" in fake.scenes
    targets = call_tool("obs_list_targets", {"kind": "window"})["result"]
    assert targets == [{"label": "[obs] AetherTwin", "target": "AetherTwin:Chrome:x.exe"}]
    added = call_tool("obs_add_capture", {"scene": "Démo", "name": "Hub", "kind": "window",
                                          "target": targets[0]["target"]})
    assert added["ok"] and fake.inputs["Hub"] == "window_capture"
    assert call_tool("obs_place", {"scene": "Démo", "name": "Hub", "fit": True})["ok"]
    start = call_tool("obs_record", {"action": "start"})
    assert start["ok"] and ("SetRecordDirectory", {"recordDirectory": start["result"]["folder"]}) in fake.calls
    assert call_tool("obs_record", {"action": "stop"})["result"]["file"] == "C:/video.mkv"


def test_screenshot_stays_in_output_folder(fake: FakeObs, tmp_path: Path) -> None:
    shot = call_tool("obs_screenshot", {"source": "Démo", "file": "accueil"})
    assert shot["ok"] and Path(shot["result"]["file"]) == tmp_path / "sortie" / "accueil.png"
    for bad in ("../x", "C:/Windows/x.png", "sous/dossier.png", ".cache"):
        assert not call_tool("obs_screenshot", {"source": "Démo", "file": bad})["ok"]


def test_no_streaming_tool_and_bad_password(fake: FakeObs, monkeypatch) -> None:
    names = {s["function"]["name"] for s in obs_control.TOOL_SPECS}
    assert not any("stream" in n for n in names)
    source = Path(obs_control.__file__).read_text(encoding="utf-8")
    assert "StartStream" not in source.replace("ni StartStream", "")
    assert call_tool("obs_stream", {})["ok"] is False
    monkeypatch.setenv("OBS_WEBSOCKET_PASSWORD", "faux")
    result = call_tool("obs_status", {})
    assert result["ok"] is False and "connexion" in result["error"]


def test_loopback_only_and_offline_message(monkeypatch, tmp_path) -> None:
    with pytest.raises(obs_control.ObsError):
        ObsClient(host="192.168.1.10")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"server_enabled": False, "server_port": 1, "auth_required": False}))
    monkeypatch.setattr(obs_control, "obs_config_file", lambda: config)
    monkeypatch.delenv("OBS_WEBSOCKET_PORT", raising=False)
    monkeypatch.delenv("OBS_WEBSOCKET_PASSWORD", raising=False)
    result = call_tool("obs_status", {})
    assert result["ok"] is False and "Activer le serveur WebSocket" in result["error"]


def test_mcp_server_lists_obs_tools() -> None:
    reply = SERVER.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [t["name"] for t in reply["result"]["tools"]]
    assert "obs_add_capture" in names and "obs_record" in names
