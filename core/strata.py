"""Strata : moteur d'inférence secondaire, pour les modèles de langage « mélange d'experts » (MoE).

Ollama reste le moteur principal (vision, embeddings, modèles denses). Strata est **optionnel** :
- désactivé par défaut (section `strata` de `config/local.yaml`) ; absent ou arrêté = mode dégradé, aucune erreur ;
- interrogé au format OpenAI (`/v1/models`, `/v1/chat/completions`) sur 127.0.0.1 uniquement ;
- ses modèles apparaissent dans le Hub sous le nom `strata/<id>` ; le routeur (`core.llm_router`) les sert ici.

Différences avec Ollama, qui guident le routeur et Inoue :
- pas de `/api/ps` ni de `keep_alive` : Strata garde son modèle en mémoire tant qu'il tourne. On ne peut pas le
  décharger requête par requête ; on l'arrête (`strata launch --stop`) ou on le démarre, sur un clic seulement ;
- sa VRAM n'est pas lisible par modèle : Inoue la voit dans la mesure réelle des cartes (`GpuMonitor`).

Le démarrage et l'arrêt passent par le programme installé (`launcher`, ex. `...\\terminal\\current\\bin\\strata.cmd`),
sans interpréteur de commandes, avec un préréglage enregistré (`preset`). Aucune clé n'est écrite ici : si Strata en
demande une, elle est lue dans la variable d'environnement nommée par `key_env`.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PREFIX = "strata/"
DEFAULT_HOST = "127.0.0.1:8090"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


class StrataError(RuntimeError):
    """Strata injoignable, refus ou réponse illisible."""


def is_strata(model: str | None) -> bool:
    return bool(model) and str(model).startswith(PREFIX)


@dataclass
class StrataConfig:
    enabled: bool = False
    host: str = DEFAULT_HOST
    model: str = ""             # id servi par Strata ; vide = le premier de /v1/models
    timeout_s: float = 600.0
    launcher: str = ""          # chemin de strata.cmd (installation locale) ; vide = pas de démarrage depuis le Hub
    data_dir: str = ""          # STRATA_DATA_DIR de l'installation ; vide = celui de Strata
    preset: str = ""            # préréglage `strata launch --preset` (modèle, contexte, cartes, port)
    key_env: str = ""       # nom d'une variable d'environnement, jamais la clé elle-même
    fallback_to_ollama: bool = True
    vram_gb: float = 0.0        # place annoncée à Inoue quand Strata tourne (0 = la mesure des cartes suffit)

    @classmethod
    def from_section(cls, raw: dict[str, Any]) -> StrataConfig:
        """Depuis la section `strata` de `config/local.yaml` (absente = désactivé)."""
        casts: dict[str, Callable[[Any], Any]] = {
            "host": str, "model": str, "timeout_s": float, "launcher": str, "data_dir": str, "preset": str,
            "key_env": str, "vram_gb": float}
        values: dict[str, Any] = {k: cast(raw[k]) for k, cast in casts.items() if raw.get(k) not in (None, "")}
        for flag in ("enabled", "fallback_to_ollama"):
            if raw.get(flag) is not None:
                values[flag] = bool(raw[flag])
        return cls(**values)

    @property
    def base_url(self) -> str:
        return (self.host if self.host.startswith(("http://", "https://")) else f"http://{self.host}").rstrip("/")

    def local(self) -> bool:
        """Seule une adresse de cette machine est acceptée (règle du projet : 127.0.0.1)."""
        return (urllib.parse.urlsplit(self.base_url).hostname or "") in LOCAL_HOSTS


def _headers(config: StrataConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get(config.key_env, "") if config.key_env else ""
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def http_json(method: str, url: str, body: dict[str, Any] | None, timeout_s: float,
              headers: dict[str, str]) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310 — hôte local vérifié
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise StrataError(f"Strata a répondu {exc.code} : {exc.read().decode('utf-8', 'ignore')[:300]}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise StrataError(f"Strata injoignable ({url}) : {exc}") from exc
    try:
        value = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise StrataError("réponse de Strata illisible") from exc
    return value if isinstance(value, dict) else {}


def http_sse(url: str, body: dict[str, Any], timeout_s: float, headers: dict[str, str]) -> Iterator[dict[str, Any]]:
    """Réponse diffusée au format OpenAI : lignes `data: {...}`, puis `data: [DONE]`."""
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",  # noqa: S310
                                     headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=timeout_s)  # noqa: S310 — hôte local vérifié
    except urllib.error.HTTPError as exc:
        raise StrataError(f"Strata a répondu {exc.code} : {exc.read().decode('utf-8', 'ignore')[:300]}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise StrataError(f"Strata injoignable ({url}) : {exc}") from exc
    with response:
        for raw in response:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                return
            try:
                yield json.loads(payload)
            except ValueError as exc:
                raise StrataError("morceau de réponse de Strata illisible") from exc


def ollama_to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages du routeur (format Ollama, images en base64 à part) vers le format OpenAI attendu par Strata."""
    out = []
    for message in messages:
        images = message.get("images") or []
        if not images:
            out.append({"role": message.get("role", "user"), "content": message.get("content", "")})
            continue
        parts: list[dict[str, Any]] = [{"type": "text", "text": str(message.get("content", ""))}]
        parts += [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}} for image in images]
        out.append({"role": message.get("role", "user"), "content": parts})
    return out


@dataclass
class StrataBackend:
    """Client du serveur Strata local, plus son démarrage et son arrêt (sur demande de l'utilisateur)."""

    config: StrataConfig = field(default_factory=StrataConfig)
    transport: Callable[..., dict[str, Any]] = http_json
    stream_transport: Callable[..., Iterator[dict[str, Any]]] = http_sse
    runner: Callable[..., Any] = subprocess.run
    spawner: Callable[..., Any] = subprocess.Popen
    _starting: subprocess.Popen[bytes] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _check_host(self) -> None:
        if not self.config.local():
            raise StrataError(f"adresse refusée : {self.config.host} (Strata doit écouter sur 127.0.0.1)")

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None,
              timeout_s: float | None = None) -> dict[str, Any]:
        self._check_host()
        return self.transport(method, self.config.base_url + path, body, timeout_s or self.config.timeout_s,
                              _headers(self.config))

    # -- modèles
    def models(self) -> list[str]:
        """Ids servis par Strata (sans le préfixe `strata/`)."""
        data = self._call("GET", "/v1/models", timeout_s=5).get("data") or []
        return [str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")]

    def resolve(self, model: str | None) -> str:
        """`strata/<id>` ou `strata/` → id réel ; vide = celui de la configuration, sinon le premier servi."""
        name = str(model or "")[len(PREFIX):] if is_strata(model) else str(model or "")
        if name:
            return name
        if self.config.model:
            return self.config.model
        served = self.models()
        if not served:
            raise StrataError("Strata ne sert aucun modèle")
        return served[0]

    # -- génération
    def chat(self, messages: list[dict[str, Any]], model: str | None = None,
             options: dict[str, Any] | None = None, max_tokens: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.resolve(model), "messages": ollama_to_openai(messages), "stream": False}
        if options and options.get("temperature") is not None:
            body["temperature"] = options["temperature"]
        if max_tokens:
            body["max_tokens"] = max_tokens
        data = self._call("POST", "/v1/chat/completions", body)
        choices = data.get("choices") or [{}]
        message = (choices[0] or {}).get("message") or {}
        usage = data.get("usage") or {}
        return {"content": str(message.get("content") or "").strip(), "model": PREFIX + body["model"],
                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}

    def chat_stream(self, messages: list[dict[str, Any]], model: str | None = None,
                    options: dict[str, Any] | None = None) -> Iterator[str]:
        self._check_host()
        body: dict[str, Any] = {"model": self.resolve(model), "messages": ollama_to_openai(messages), "stream": True}
        if options and options.get("temperature") is not None:
            body["temperature"] = options["temperature"]
        for chunk in self.stream_transport(self.config.base_url + "/v1/chat/completions", body,
                                           self.config.timeout_s, _headers(self.config)):
            for choice in chunk.get("choices") or []:
                piece = str(((choice or {}).get("delta") or {}).get("content") or "")
                if piece:
                    yield piece

    # -- démarrage / arrêt (sur un clic, jamais automatiquement)
    def launcher(self) -> Path | None:
        path = Path(self.config.launcher) if self.config.launcher else None
        return path if path is not None and path.is_file() else None

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.config.data_dir:
            env["STRATA_DATA_DIR"] = self.config.data_dir
        env.setdefault("STRATA_UPDATE_CHECK", "0")   # pas de vérification de mise à jour lancée par le Hub
        return env

    def start(self) -> dict[str, Any]:
        """Démarre le préréglage en arrière-plan (`--no-tui`) ; le chargement du modèle prend du temps."""
        launcher = self.launcher()
        if launcher is None:
            raise StrataError("Strata n'est pas installé ici (strata.launcher dans config/local.yaml)")
        if not self.config.preset:
            raise StrataError("aucun préréglage Strata (strata.preset dans config/local.yaml)")
        with self._lock:
            if self._starting is not None and self._starting.poll() is None:
                return {"started": False, "detail": "démarrage déjà en cours"}
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._starting = self.spawner(
                [str(launcher), "launch", "--preset", self.config.preset, "--access", "local", "--yes", "--no-tui"],
                env=self._env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        return {"started": True, "detail": f"préréglage « {self.config.preset} » en cours de chargement"}

    def stop(self) -> dict[str, Any]:
        """Arrête le modèle servi : Strata rend toute sa VRAM et sa RAM (essai du 23/11 : 24 Go de RAM)."""
        launcher = self.launcher()
        if launcher is None:
            raise StrataError("Strata n'est pas installé ici (strata.launcher dans config/local.yaml)")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        args = [str(launcher), "launch", "--stop"] + (["--preset", self.config.preset] if self.config.preset else [])
        done = self.runner(args, env=self._env(), capture_output=True, timeout=120, creationflags=flags)
        return {"stopped": getattr(done, "returncode", 1) == 0}

    def starting(self) -> bool:
        return self._starting is not None and self._starting.poll() is None

    # -- état (tableau de bord)
    def state(self) -> dict[str, Any]:
        """Ne lève jamais. `status` : désactivé | non installé | arrêté | démarrage | actif."""
        base = {"enabled": self.config.enabled, "host": self.config.host, "model": self.config.model,
                "installed": self.launcher() is not None, "preset": self.config.preset, "models": [], "error": ""}
        if not self.config.enabled:
            return {**base, "status": "désactivé", "reachable": False}
        try:
            served = self.models()
        except StrataError as exc:
            status = "démarrage" if self.starting() else ("arrêté" if base["installed"] else "non installé")
            return {**base, "status": status, "reachable": False, "error": str(exc)}
        return {**base, "status": "actif", "reachable": True, "models": [PREFIX + m for m in served]}
