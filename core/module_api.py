"""Contrat de module du Hub : manifeste, événements, cycle de vie.

Un module est un dossier `modules/<nom>/` contenant un `manifest.json` et une classe
qui hérite de `ModuleBase`. Le daemon charge les modules d'après leur manifeste,
les lance dans des processus séparés et leur parle par le bus local.
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class ManifestError(ValueError):
    """Manifeste absent, illisible ou invalide."""


@dataclass(frozen=True)
class Triggers:
    """Ce qui active le module : processus (ex. « obs64.exe »), titres de fenêtres, ports."""

    processes: tuple[str, ...] = ()
    windows: tuple[str, ...] = ()
    ports: tuple[int, ...] = ()


@dataclass(frozen=True)
class Manifest:
    """Déclaration d'un module. Les besoins VRAM sont lus par Inoue avant tout démarrage."""

    name: str
    version: str
    description: str
    entry: str  # « paquet.module:Classe »
    vram_min_gb: float = 0.0
    vram_comfort_gb: float = 0.0
    python_deps: tuple[str, ...] = ()
    optional_deps: tuple[str, ...] = ()
    triggers: Triggers = field(default_factory=Triggers)
    network: tuple[str, ...] = ()  # domaines autorisés ; vide = aucun accès réseau externe
    experimental: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strings(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ManifestError(f"`{key}` doit être une liste de chaînes")
    return tuple(value)


def parse_manifest(raw: Any) -> Manifest:
    """Valide un manifeste déjà décodé. Lève `ManifestError` avec un message précis."""
    if not isinstance(raw, dict):
        raise ManifestError("le manifeste doit être un objet JSON")
    for key in ("name", "version", "description", "entry"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ManifestError(f"champ obligatoire manquant ou vide : `{key}`")
    if not NAME_PATTERN.match(raw["name"]):
        raise ManifestError(f"nom de module invalide : {raw['name']!r} (minuscules, chiffres, « _ »)")
    if raw["entry"].count(":") != 1:
        raise ManifestError("`entry` doit avoir la forme « paquet.module:Classe »")

    vram = {}
    for key in ("vram_min_gb", "vram_comfort_gb"):
        value = raw.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ManifestError(f"`{key}` doit être un nombre positif ou nul")
        vram[key] = float(value)
    if vram["vram_comfort_gb"] < vram["vram_min_gb"]:
        raise ManifestError("`vram_comfort_gb` ne peut pas être inférieur à `vram_min_gb`")

    trig = raw.get("triggers", {})
    if not isinstance(trig, dict):
        raise ManifestError("`triggers` doit être un objet")
    ports = trig.get("ports", [])
    if not isinstance(ports, list) or not all(isinstance(p, int) and 0 < p < 65536 for p in ports):
        raise ManifestError("`triggers.ports` doit être une liste de ports valides")

    return Manifest(
        name=raw["name"], version=raw["version"], description=raw["description"], entry=raw["entry"],
        vram_min_gb=vram["vram_min_gb"], vram_comfort_gb=vram["vram_comfort_gb"],
        python_deps=_strings(raw, "python_deps"), optional_deps=_strings(raw, "optional_deps"),
        triggers=Triggers(_strings(trig, "processes"), _strings(trig, "windows"), tuple(ports)),
        network=_strings(raw, "network"), experimental=bool(raw.get("experimental", False)),
    )


def load_manifest(module_dir: Path) -> Manifest:
    """Lit et valide `<module_dir>/manifest.json`."""
    path = module_dir / MANIFEST_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError(f"manifeste absent : {path}") from None
    except (OSError, ValueError) as exc:
        raise ManifestError(f"manifeste illisible ({path}) : {exc}") from exc
    try:
        return parse_manifest(raw)
    except ManifestError as exc:
        raise ManifestError(f"{path} : {exc}") from None


def discover_manifests(modules_root: Path) -> tuple[dict[str, Manifest], dict[str, str]]:
    """Parcourt `modules/`. Retourne (manifestes valides, erreurs par dossier). Un module cassé n'arrête rien."""
    found: dict[str, Manifest] = {}
    errors: dict[str, str] = {}
    if not modules_root.is_dir():
        return found, errors
    for child in sorted(modules_root.iterdir()):
        if not (child / MANIFEST_NAME).is_file():
            continue
        try:
            manifest = load_manifest(child)
        except ManifestError as exc:
            errors[child.name] = str(exc)
            continue
        if manifest.name in found:
            errors[child.name] = f"nom de module en double : {manifest.name}"
        else:
            found[manifest.name] = manifest
    return found, errors


@dataclass(frozen=True)
class Event:
    """Message du bus. `topic` est hiérarchique : « process.started », « gpu.alert », « module.gaming_hud.state »."""

    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "hub"
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Event:
        return cls(topic=str(raw["topic"]), payload=dict(raw.get("payload") or {}),
                   source=str(raw.get("source", "hub")), ts=float(raw.get("ts") or time.time()))

    def matches(self, pattern: str) -> bool:
        """« gpu.* » ou « gpu » couvre « gpu.alert » ; « * » couvre tout."""
        prefix = pattern[:-2] if pattern.endswith(".*") else pattern
        return pattern == "*" or self.topic == prefix or self.topic.startswith(prefix + ".")


@dataclass(frozen=True)
class Health:
    """Santé d'un module. `degraded` = démarré sans une dépendance optionnelle (GPU, jeu, OBS, poids…)."""

    ok: bool
    degraded: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModuleBase(ABC):
    """Classe de base de tout module. `publish` est fourni par le lanceur (bus du Hub)."""

    def __init__(self, manifest: Manifest, config: dict[str, Any] | None = None) -> None:
        self.manifest = manifest
        self.config = config or {}
        self.publish = lambda event: None  # remplacé par le lanceur ; sans bus, publier ne fait rien

    @property
    def name(self) -> str:
        return self.manifest.name

    @abstractmethod
    def start(self) -> None:
        """Démarre le module. Doit réussir en mode dégradé si une dépendance optionnelle manque."""

    @abstractmethod
    def stop(self) -> None:
        """Arrête proprement et libère les ressources (VRAM comprise)."""

    @abstractmethod
    def health(self) -> Health:
        """État de santé, interrogé par Fuma."""

    def handle_event(self, event: Event) -> None:  # noqa: B027 — optionnel : par défaut, un module ignore les événements
        """Reçoit un événement du bus."""

    def widget_schema(self) -> dict[str, Any]:
        """Schéma JSON de l'interface générée à la volée par le daemon (titre, sections, boutons)."""
        return {"title": self.manifest.description, "sections": []}
