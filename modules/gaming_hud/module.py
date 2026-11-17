"""Module du Hub : lit l'état du jeu par un `GameAdapter` et le publie sur le bus.

Ce module est un service de données, sans fenêtre : l'application Pygame (`python -m modules.gaming_hud`)
reste indépendante. Il publie :

    module.gaming_hud.state     {"showcase", "state", "omitted", "context", "adapter"}
    module.gaming_hud.showcase  {"on"}

**Mode Showcase** : dès qu'un logiciel de diffusion tourne (OBS), tout ce qui est publié passe par
`GameAdapter.privacy_filter(state, "showcase")`. Le mode s'active aussi par la commande
`module.gaming_hud.cmd.showcase` `{"on": true}`.

Configuration (section `gaming_hud` de `config/local.yaml`), tout est facultatif :

    adapter: wow_retail            # wow_retail | log_tail | screen_ocr
    game_path: ""                  # dossier _retail_ ; vide = détection automatique
    rules_file: ""                 # log_tail : fichier de règles YAML
    screen_ocr: {fields: [...]}    # screen_ocr : champs à lire à l'écran
    poll_seconds: 2
    showcase_processes: [obs64.exe, obs32.exe, obs.exe]
    hide_character_names: false
    gold: round                    # round | hide | keep
    obs_hud: true                  # sert la page d'overlay pour OBS
    obs_hud_port: 5757             # http://127.0.0.1:5757/obs-hud (boucle locale uniquement)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from core.hardware.gpu_monitor import GpuMonitor
from core.module_api import Event, Health, Manifest, ModuleBase
from modules.gaming_hud.adapters.base import META_KEY, PRIVACY_OFF, PRIVACY_SHOWCASE, GameAdapter
from modules.gaming_hud.adapters.privacy import PrivacyOptions
from modules.gaming_hud.obs_server import DEFAULT_PORT, ObsServer, overlay_view

DEFAULT_SHOWCASE_PROCESSES = ("obs64.exe", "obs32.exe", "obs.exe")
MAX_SECTION_BYTES = 20_000  # une section plus lourde (collections, hauts faits…) n'est pas publiée sur le bus
REPUBLISH_SECONDS = 30.0


def build_adapter(config: dict[str, Any]) -> GameAdapter:
    """Construit l'adaptateur demandé par la configuration. Lève `ValueError` si elle est invalide."""
    options = PrivacyOptions(hide_character_names=bool(config.get("hide_character_names", False)),
                             gold=str(config.get("gold", "round")))
    kind = str(config.get("adapter", "wow_retail"))
    if kind == "wow_retail":
        from modules.gaming_hud.adapters.wow_retail import WowRetailAdapter

        return WowRetailAdapter(config.get("game_path") or None, options=options,
                                autodetect=bool(config.get("autodetect", True)))
    if kind == "log_tail":
        from modules.gaming_hud.adapters.log_tail import LogTailAdapter

        if not config.get("rules_file"):
            raise ValueError("adaptateur log_tail : `rules_file` est obligatoire")
        return LogTailAdapter.from_file(Path(str(config["rules_file"])), options)
    if kind == "screen_ocr":
        from modules.gaming_hud.adapters.screen_ocr import ScreenOcrAdapter

        return ScreenOcrAdapter(dict(config.get("screen_ocr") or {}), options)
    raise ValueError(f"adaptateur inconnu : {kind!r} (wow_retail, log_tail, screen_ocr)")


def compact(state: dict[str, Any], limit: int = MAX_SECTION_BYTES) -> tuple[dict[str, Any], list[str]]:
    """Sépare les sections publiables des sections trop lourdes pour le bus. Retourne (état, sections omises)."""
    kept, omitted = {}, []
    for name, value in state.items():
        size = len(json.dumps(value, ensure_ascii=False, default=str))
        if name == META_KEY or size <= limit:
            kept[name] = value
        else:
            omitted.append(name)
    return kept, sorted(omitted)


def running_process_names() -> set[str]:
    """Noms des processus en cours (minuscules) ; ensemble vide si `psutil` est absent."""
    try:
        import psutil
    except ImportError:
        return set()
    names = set()
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"]:
                names.add(proc.info["name"].lower())
        except Exception:  # noqa: BLE001, S112 — processus disparu entre-temps
            continue
    return names


class GamingHudModule(ModuleBase):
    """Publie l'état du jeu ; bascule en mode Showcase quand un logiciel de diffusion est lancé."""

    def __init__(self, manifest: Manifest, config: dict[str, Any] | None = None) -> None:
        super().__init__(manifest, config)
        self.adapter: GameAdapter | None = None
        self.adapter_error = ""
        self.showcase = False
        self.poll_seconds = float(self.config.get("poll_seconds", 2.0))
        self.showcase_processes = {str(p).lower() for p in
                                   self.config.get("showcase_processes", DEFAULT_SHOWCASE_PROCESSES)}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_digest = ""
        self._since_publish = 0.0
        self.last_state: dict[str, Any] = {}
        self.obs: ObsServer | None = None  # page d'overlay pour OBS (source navigateur)
        self.obs_error = ""
        self._gpu: GpuMonitor | None = None

    # -- cycle de vie
    def start(self) -> None:
        try:
            self.adapter = build_adapter(self.config)
        except Exception as exc:  # noqa: BLE001 — sans adaptateur, le module reste en vie, en mode dégradé
            self.adapter, self.adapter_error = None, f"{type(exc).__name__}: {exc}"
        if self.showcase_processes & running_process_names():
            self.set_showcase(True)  # le logiciel de diffusion tournait déjà au démarrage du module
        if self.config.get("obs_hud", True):
            try:
                self.obs = ObsServer(self.overlay_snapshot, port=int(self.config.get("obs_hud_port", DEFAULT_PORT)))
                self.obs.start()
            except (OSError, ValueError) as exc:  # port déjà pris : le module continue sans overlay
                self.obs, self.obs_error = None, f"overlay OBS indisponible : {exc}"
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="gaming-hud-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.obs is not None:
            self.obs.stop()
            self.obs = None
        if self._thread is not None:
            self._thread.join(timeout=5)

    def overlay_snapshot(self) -> dict[str, Any]:
        """Ce que la page d'overlay affiche. TOUJOURS filtré en mode Showcase, quel que soit le mode du module :
        cette page est faite pour être diffusée."""
        if self._gpu is None:
            self._gpu = GpuMonitor()
        gpus = self._gpu.report()["gpus"]
        if self.adapter is None:
            return overlay_view({}, gpus, showcase=True)
        with self._lock:
            raw = self.adapter.read_state()
        return overlay_view(self.adapter.privacy_filter(raw, PRIVACY_SHOWCASE), gpus, showcase=True)

    def health(self) -> Health:
        if self.adapter is None:
            return Health(ok=True, degraded=True, detail=f"aucun adaptateur : {self.adapter_error}")
        detected = False
        try:
            detected = self.adapter.detect()
        except Exception:  # noqa: BLE001, S110 — detect() ne doit jamais faire échouer le bilan de santé
            pass
        detail = f"adaptateur {self.adapter.id}" + ("" if detected else " — jeu introuvable (mode dégradé)")
        detail += " — SHOWCASE" if self.showcase else ""
        if self.obs is not None:
            detail += f" — overlay {self.obs.url}"
        elif self.obs_error:
            detail += f" — {self.obs_error}"
        return Health(ok=True, degraded=not detected, detail=detail)

    # -- événements du Hub
    def handle_event(self, event: Event) -> None:
        name = str(event.payload.get("name", "")).lower()
        if event.topic == "process.started" and name in self.showcase_processes:
            self.set_showcase(True)
        elif event.topic == "process.stopped" and name in self.showcase_processes:
            self.set_showcase(False)
        elif event.topic == f"module.{self.name}.cmd.showcase":
            self.set_showcase(bool(event.payload.get("on", True)))
        elif event.topic == f"module.{self.name}.cmd.refresh":
            self.publish_state(force=True)

    def set_showcase(self, on: bool) -> None:
        if on == self.showcase:
            return
        self.showcase = on
        self.publish(Event(f"module.{self.name}.showcase", {"on": on}, source=self.name))
        self.publish_state(force=True)

    # -- lecture et publication
    def read(self) -> dict[str, Any]:
        """Lit l'état et rend ce qui a le droit de sortir du module dans le mode courant."""
        if self.adapter is None:
            return {"showcase": self.showcase, "adapter": None, "state": {}, "omitted": [],
                    "context": "", "error": self.adapter_error}
        raw = self.adapter.read_state()
        mode = PRIVACY_SHOWCASE if self.showcase else PRIVACY_OFF
        visible = self.adapter.privacy_filter(raw, mode)
        state, omitted = compact(visible)
        # le contexte destiné à l'assistant est bâti sur l'état filtré : en Showcase, il ne contient rien de privé
        return {"showcase": self.showcase, "adapter": self.adapter.id, "state": state, "omitted": omitted,
                "context": self.adapter.context_for_llm(visible)}

    def publish_state(self, force: bool = False) -> bool:
        """Publie l'état s'il a changé (ou si `force`). Retourne True si un événement est parti."""
        with self._lock:
            try:
                payload = self.read()
            except Exception as exc:  # noqa: BLE001 — une lecture ratée est signalée, le module continue
                self.publish(Event(f"module.{self.name}.error",
                                   {"stage": "read", "error": f"{type(exc).__name__}: {exc}"}, source=self.name))
                return False
            self.last_state = payload
            comparable = {k: v for k, v in payload["state"].items() if k != META_KEY}
            digest = json.dumps([payload["showcase"], comparable], sort_keys=True, ensure_ascii=False, default=str)
            if not force and digest == self._last_digest and self._since_publish < REPUBLISH_SECONDS:
                return False
            self._last_digest, self._since_publish = digest, 0.0
            self.publish(Event(f"module.{self.name}.state", payload, source=self.name))
            return True

    def _loop(self) -> None:
        self.publish_state(force=True)
        while not self._stop.wait(self.poll_seconds):
            self._since_publish += self.poll_seconds
            self.publish_state()
