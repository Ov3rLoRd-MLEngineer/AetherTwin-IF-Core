"""Pilotage d'OBS Studio par son serveur WebSocket (protocole obs-websocket v5, inclus dans OBS 28 et plus).

Sert d'outil aux agents (serveur MCP `aethertwin-obs`, voir `obs_mcp.py`) : préparer les scènes d'une capture
(fenêtres du Hub et de WoW Assistant, écran, logo), régler la vidéo, enregistrer, faire une capture d'image.

Garanties :
- connexion à la **boucle locale** seulement (127.0.0.1) ; aucune autre adresse n'est acceptée ;
- **aucune diffusion** : la liste des outils est fermée et ne contient ni StartStream ni réglage du service de
  diffusion. On peut enregistrer, pas diffuser ;
- les fichiers écrits par OBS à notre demande (captures d'image, enregistrements) vont dans un seul dossier
  (`AETHERTWIN_OBS_OUT`, sinon `cache/obs` du dépôt), jamais ailleurs ;
- le mot de passe du serveur WebSocket n'est jamais écrit dans le dépôt : il vient de la variable
  `OBS_WEBSOCKET_PASSWORD`, sinon du fichier de réglages qu'OBS tient lui-même sur cette machine.

Les outils ne lèvent jamais : erreur → {"ok": False, "error": …}.
"""
from __future__ import annotations

import base64
import hashlib
import itertools
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"
DEFAULT_PORT = 4455
TIMEOUT_S = 10.0
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".svg")


class ObsError(RuntimeError):
    """Erreur lisible renvoyée à l'agent."""


def obs_config_file() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"


def server_settings(config_file: Path | None = None) -> dict[str, Any]:
    """Port et mot de passe : variables d'environnement d'abord, puis les réglages locaux d'OBS."""
    data: dict[str, Any] = {}
    path = config_file or obs_config_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    port = int(os.environ.get("OBS_WEBSOCKET_PORT") or data.get("server_port") or DEFAULT_PORT)
    password = os.environ.get("OBS_WEBSOCKET_PASSWORD")
    if password is None and data.get("auth_required", True):
        password = data.get("server_password") or None
    return {"port": port, "password": password, "enabled": data.get("server_enabled"),
            "known": bool(data)}


def auth_string(password: str, salt: str, challenge: str) -> str:
    """Réponse au défi d'obs-websocket v5 : base64(sha256(base64(sha256(mot de passe + sel)) + défi))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def out_dir() -> Path:
    folder = Path(os.environ.get("AETHERTWIN_OBS_OUT") or ROOT / "cache" / "obs").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def confined(name: str, suffix: str) -> Path:
    """Un nom de fichier simple dans le dossier de sortie ; tout chemin ou remontée est refusé."""
    name = str(name or "").strip()
    if not name or Path(name).name != name or name.startswith("."):
        raise ObsError("nom de fichier simple attendu (sans dossier)")
    path = (out_dir() / name).with_suffix(suffix) if not name.lower().endswith(suffix) else out_dir() / name
    return path


class ObsClient:
    """Une connexion courte : on s'identifie, on envoie des requêtes, on ferme."""

    def __init__(self, port: int | None = None, password: str | None = None, host: str = HOST) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ObsError("OBS n'est piloté que sur la boucle locale")
        settings = server_settings()
        self.url = f"ws://{host}:{port or settings['port']}"
        self.password = password if password is not None else settings["password"]
        self.settings = settings
        self.ws: Any = None
        self.ids = itertools.count(1)

    def __enter__(self) -> ObsClient:
        from websockets.sync.client import connect  # websockets fait déjà partie des dépendances du Hub

        try:
            self.ws = connect(self.url, open_timeout=TIMEOUT_S, subprotocols=["obswebsocket.json"])
        except OSError as error:
            hint = (" Dans OBS : Outils > Paramètres du serveur WebSocket > « Activer le serveur WebSocket »."
                    if self.settings.get("enabled") is False else "")
            raise ObsError(f"OBS ne répond pas sur {self.url} ({error}).{hint}") from error
        hello = self._recv()
        if hello.get("op") != 0:
            raise ObsError("réponse inattendue d'OBS à l'ouverture")
        identify: dict[str, Any] = {"rpcVersion": 1, "eventSubscriptions": 0}
        auth = hello.get("d", {}).get("authentication")
        if auth:
            if not self.password:
                raise ObsError("OBS demande un mot de passe : définir OBS_WEBSOCKET_PASSWORD")
            identify["authentication"] = auth_string(self.password, auth["salt"], auth["challenge"])
        self.ws.send(json.dumps({"op": 1, "d": identify}))
        if self._recv().get("op") != 2:
            raise ObsError("OBS a refusé l'identification (mot de passe ?)")
        return self

    def __exit__(self, *exc: object) -> None:
        if self.ws is not None:
            self.ws.close()

    def _recv(self) -> dict[str, Any]:
        try:
            return json.loads(self.ws.recv(timeout=TIMEOUT_S))
        except Exception as error:  # fermeture par OBS (mauvais mot de passe : code 4009), délai dépassé…
            raise ObsError(f"OBS a coupé la connexion ou n'a pas répondu ({error})") from error

    def call(self, request: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        rid = str(next(self.ids))
        self.ws.send(json.dumps({"op": 6, "d": {"requestType": request, "requestId": rid,
                                                 "requestData": data or {}}}))
        while True:
            message = self._recv()
            if message.get("op") == 7 and message["d"].get("requestId") == rid:
                status = message["d"].get("requestStatus", {})
                if not status.get("result"):
                    raise ObsError(f"{request} : {status.get('comment') or 'refusé'} (code {status.get('code')})")
                return message["d"].get("responseData") or {}


# ---------- outils ----------
def _spec(name: str, description: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": props, "required": required}}}


STR, NUM, INT = {"type": "string"}, {"type": "number"}, {"type": "integer"}
TOOL_SPECS: list[dict[str, Any]] = [
    _spec("obs_status", "État d'OBS : version, scène affichée, liste des scènes, réglages vidéo, enregistrement.",
          {}, []),
    _spec("obs_scene_items", "Sources d'une scène, avec leur numéro, leur type et leur position.",
          {"scene": STR}, ["scene"]),
    _spec("obs_create_scene", "Crée une scène vide (sans effet si elle existe déjà).", {"scene": STR}, ["scene"]),
    _spec("obs_set_scene", "Affiche une scène dans le programme (ce qui est enregistré).", {"scene": STR}, ["scene"]),
    _spec("obs_list_targets", "Fenêtres ouvertes ou écrans que l'on peut capturer (valeurs à passer à "
          "obs_add_capture).", {"kind": {"type": "string", "enum": ["window", "monitor"]}}, ["kind"]),
    _spec("obs_add_capture", "Ajoute à une scène une capture de fenêtre (target = valeur de obs_list_targets "
          "kind=window) ou d'écran (kind=monitor). Remplace une source du même nom.",
          {"scene": STR, "name": STR, "kind": {"type": "string", "enum": ["window", "monitor"]}, "target": STR},
          ["scene", "name", "kind", "target"]),
    _spec("obs_add_image", "Ajoute une image (logo, carton) à une scène, depuis un fichier image local.",
          {"scene": STR, "name": STR, "file": STR}, ["scene", "name", "file"]),
    _spec("obs_place", "Place une source dans sa scène : position (x, y en pixels du canevas), échelle, "
          "ou « fit » pour l'ajuster au canevas entier.",
          {"scene": STR, "name": STR, "x": NUM, "y": NUM, "scale": NUM, "fit": {"type": "boolean"}},
          ["scene", "name"]),
    _spec("obs_remove_source", "Retire une source d'une scène.", {"scene": STR, "name": STR}, ["scene", "name"]),
    _spec("obs_set_video", "Règle la vidéo : taille du canevas, taille de sortie et images par seconde.",
          {"width": INT, "height": INT, "fps": INT}, ["width", "height", "fps"]),
    _spec("obs_screenshot", "Capture d'image d'une source ou d'une scène, écrite en PNG dans le dossier de sortie "
          "d'AetherTwin (nom de fichier simple).", {"source": STR, "file": STR, "width": INT}, ["source", "file"]),
    _spec("obs_record", "Enregistrement : start, stop (renvoie le fichier), status. Les vidéos vont dans le "
          "dossier de sortie d'AetherTwin. Aucune diffusion n'est possible par ces outils.",
          {"action": {"type": "string", "enum": ["start", "stop", "status"]}}, ["action"]),
]

INPUT_KINDS = {"window": "window_capture", "monitor": "monitor_capture"}
TARGET_PROPERTY = {"window": "window", "monitor": "monitor_id"}


def _item_id(obs: ObsClient, scene: str, name: str) -> int:
    return obs.call("GetSceneItemId", {"sceneName": scene, "sourceName": name})["sceneItemId"]


def _probe_input(obs: ObsClient, kind: str) -> str:
    """Une source de capture temporaire, le temps de lire la liste des cibles qu'OBS propose."""
    name = f"_aethertwin_sonde_{kind}"
    inputs = {i["inputName"] for i in obs.call("GetInputList").get("inputs", [])}
    if name not in inputs:
        scenes = [s["sceneName"] for s in obs.call("GetSceneList").get("scenes", [])]
        scene = "_aethertwin_sonde"
        if scene not in scenes:
            obs.call("CreateScene", {"sceneName": scene})
        obs.call("CreateInput", {"sceneName": scene, "inputName": name, "inputKind": INPUT_KINDS[kind],
                                 "sceneItemEnabled": False})
    return name


def run(obs: ObsClient, name: str, args: dict[str, Any]) -> Any:  # noqa: C901 - un aiguillage simple
    if name == "obs_status":
        scenes = obs.call("GetSceneList")
        return {"version": obs.call("GetVersion").get("obsVersion"),
                "scene": scenes.get("currentProgramSceneName"),
                "scenes": [s["sceneName"] for s in reversed(scenes.get("scenes", []))],
                "video": obs.call("GetVideoSettings"), "record": obs.call("GetRecordStatus"),
                "record_dir": obs.call("GetRecordDirectory").get("recordDirectory")}
    if name == "obs_scene_items":
        items = obs.call("GetSceneItemList", {"sceneName": args["scene"]}).get("sceneItems", [])
        return [{"id": i["sceneItemId"], "name": i["sourceName"], "kind": i.get("inputKind"),
                 "enabled": i.get("sceneItemEnabled"),
                 "x": i.get("sceneItemTransform", {}).get("positionX"),
                 "y": i.get("sceneItemTransform", {}).get("positionY")} for i in items]
    if name == "obs_create_scene":
        if args["scene"] not in [s["sceneName"] for s in obs.call("GetSceneList").get("scenes", [])]:
            obs.call("CreateScene", {"sceneName": args["scene"]})
        return {"scene": args["scene"]}
    if name == "obs_set_scene":
        obs.call("SetCurrentProgramScene", {"sceneName": args["scene"]})
        return {"scene": args["scene"]}
    if name == "obs_list_targets":
        kind = args["kind"]
        if kind not in INPUT_KINDS:
            raise ObsError("kind : window ou monitor")
        items = obs.call("GetInputPropertiesListPropertyItems", {
            "inputName": _probe_input(obs, kind), "propertyName": TARGET_PROPERTY[kind]}).get("propertyItems", [])
        return [{"label": i.get("itemName"), "target": i.get("itemValue")} for i in items if i.get("itemEnabled", True)]
    if name == "obs_add_capture":
        kind = args["kind"]
        if kind not in INPUT_KINDS:
            raise ObsError("kind : window ou monitor")
        settings: dict[str, Any] = {TARGET_PROPERTY[kind]: args["target"]}
        if kind == "window":
            settings.update({"capture_method": 2, "cursor": True, "client_area": True})  # WGC : fenêtres WebView2
        return _replace_input(obs, args["scene"], args["name"], INPUT_KINDS[kind], settings)
    if name == "obs_add_image":
        file = Path(str(args["file"])).expanduser().resolve()
        if file.suffix.lower() not in IMAGE_SUFFIXES or not file.is_file():
            raise ObsError("fichier image introuvable ou d'un type non pris en charge")
        return _replace_input(obs, args["scene"], args["name"], "image_source", {"file": str(file)})
    if name == "obs_place":
        item = _item_id(obs, args["scene"], args["name"])
        if args.get("fit"):
            video = obs.call("GetVideoSettings")
            transform: dict[str, Any] = {"boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsWidth": video["baseWidth"],
                                         "boundsHeight": video["baseHeight"], "positionX": 0, "positionY": 0,
                                         "alignment": 5}
        else:
            transform = {"boundsType": "OBS_BOUNDS_NONE"}
            for key, field in (("x", "positionX"), ("y", "positionY"), ("scale", "scaleX"), ("scale", "scaleY")):
                if args.get(key) is not None:
                    transform[field] = float(args[key])
        obs.call("SetSceneItemTransform", {"sceneName": args["scene"], "sceneItemId": item,
                                           "sceneItemTransform": transform})
        return {"scene": args["scene"], "name": args["name"], "transform": transform}
    if name == "obs_remove_source":
        obs.call("RemoveSceneItem", {"sceneName": args["scene"], "sceneItemId": _item_id(obs, args["scene"],
                                                                                          args["name"])})
        return {"removed": args["name"]}
    if name == "obs_set_video":
        width, height, fps = int(args["width"]), int(args["height"]), int(args["fps"])
        if not (320 <= width <= 7680 and 240 <= height <= 4320 and 1 <= fps <= 240):
            raise ObsError("taille ou cadence hors limites")
        obs.call("SetVideoSettings", {"baseWidth": width, "baseHeight": height, "outputWidth": width,
                                      "outputHeight": height, "fpsNumerator": fps, "fpsDenominator": 1})
        return obs.call("GetVideoSettings")
    if name == "obs_screenshot":
        path = confined(args["file"], ".png")
        data: dict[str, Any] = {"sourceName": args["source"], "imageFormat": "png", "imageFilePath": str(path)}
        if args.get("width"):
            data["imageWidth"] = int(args["width"])
        obs.call("SaveSourceScreenshot", data)
        return {"file": str(path)}
    if name == "obs_record":
        action = args["action"]
        if action == "start":
            obs.call("SetRecordDirectory", {"recordDirectory": str(out_dir())})
            obs.call("StartRecord")
            return {"recording": True, "folder": str(out_dir())}
        if action == "stop":
            return {"recording": False, "file": obs.call("StopRecord").get("outputPath")}
        if action == "status":
            return obs.call("GetRecordStatus")
        raise ObsError("action : start, stop ou status")
    raise ObsError(f"outil inconnu : {name}")


def _replace_input(obs: ObsClient, scene: str, name: str, kind: str, settings: dict[str, Any]) -> dict[str, Any]:
    inputs = {i["inputName"]: i.get("inputKind") for i in obs.call("GetInputList").get("inputs", [])}
    if name in inputs:
        if inputs[name] != kind:
            raise ObsError(f"une source « {name} » d'un autre type existe déjà")
        obs.call("SetInputSettings", {"inputName": name, "inputSettings": settings, "overlay": True})
        try:
            _item_id(obs, scene, name)
        except ObsError:
            obs.call("CreateSceneItem", {"sceneName": scene, "sourceName": name})
    else:
        obs.call("CreateInput", {"sceneName": scene, "inputName": name, "inputKind": kind,
                                 "inputSettings": settings})
    return {"scene": scene, "name": name, "kind": kind}


def call_tool(name: str, args: dict[str, Any], client: ObsClient | None = None) -> dict[str, Any]:
    if name not in {s["function"]["name"] for s in TOOL_SPECS}:
        return {"ok": False, "error": f"outil inconnu : {name}"}
    try:
        if client is not None:
            return {"ok": True, "result": run(client, name, dict(args or {}))}
        with ObsClient() as obs:
            return {"ok": True, "result": run(obs, name, dict(args or {}))}
    except (ObsError, KeyError, ValueError, TypeError) as error:
        message = f"argument manquant : {error}" if isinstance(error, KeyError) else str(error)
        return {"ok": False, "error": message}
