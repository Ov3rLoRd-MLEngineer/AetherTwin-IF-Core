"""Routeur LLM du Hub : toutes les demandes de génération passent par ici, vers Ollama, en local.

Rôle :
- adresse d'Ollama **configurable** (hôte:port, machine locale ou réseau local) ;
- `num_ctx` toujours fixé (le contexte par défaut d'un modèle 30 B fait échouer le chargement) ;
- application des règles VRAM avec Inoue : **un seul gros modèle de langage chargé à la fois**.
  Avant d'en charger un nouveau, les autres sont réellement déchargés (`keep_alive: 0`) ;
- mesure : après chaque réponse, la VRAM réellement occupée par le modèle est relue dans `/api/ps`.

Aucune requête ne part vers un service cloud.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.guardians.inoue import Inoue, Verdict

GIB = 1024 ** 3
DEFAULT_HOST = "127.0.0.1:11434"
DEFAULT_NUM_CTX = 32768


class LlmError(RuntimeError):
    """Ollama injoignable, modèle absent, réponse inattendue."""


class LlmRefused(LlmError):
    """Inoue refuse ou diffère le chargement : le modèle ne tient pas dans le budget VRAM."""


@dataclass
class LlmConfig:
    host: str = DEFAULT_HOST
    default_model: str = ""
    num_ctx: int = DEFAULT_NUM_CTX
    keep_alive: str = "5m"
    timeout_s: float = 300.0
    big_model_gb: float = 8.0  # au-dessus : « gros modèle », un seul chargé à la fois
    vram_overhead: float = 1.15  # estimation avant chargement = taille des poids x ce facteur

    @classmethod
    def from_section(cls, raw: dict[str, Any]) -> LlmConfig:
        """Construit la configuration depuis la section `ollama` de `config/local.yaml`."""
        known = {"host": str, "num_ctx": int, "keep_alive": str, "timeout_s": float, "big_model_gb": float}
        values: dict[str, Any] = {k: cast(raw[k]) for k, cast in known.items() if raw.get(k) not in (None, "")}
        model = raw.get("default_model") or raw.get("model_economy") or ""
        return cls(default_model=str(model), **values)

    @property
    def base_url(self) -> str:
        return (self.host if self.host.startswith(("http://", "https://")) else f"http://{self.host}").rstrip("/")


def http_json(method: str, url: str, body: dict[str, Any] | None, timeout_s: float) -> dict[str, Any]:
    """Appel HTTP JSON vers Ollama. Lève `LlmError` avec un message lisible."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method,  # noqa: S310 — hôte Ollama configuré
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        raise LlmError(f"Ollama a répondu {exc.code} : {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LlmError(f"Ollama injoignable ({url}) : {exc}") from exc
    try:
        value = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise LlmError("réponse d'Ollama illisible") from exc
    return value if isinstance(value, dict) else {}


@dataclass
class LlmRouter:
    """Point d'entrée unique vers les modèles de langage locaux."""

    inoue: Inoue | None = None
    config: LlmConfig = field(default_factory=LlmConfig)
    transport: Callable[[str, str, dict[str, Any] | None, float], dict[str, Any]] = http_json
    measured_vram_gb: dict[str, float] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    # -- lecture de l'état d'Ollama
    def _call(self, method: str, path: str, body: dict[str, Any] | None = None, timeout_s: float | None = None) -> dict:
        return self.transport(method, self.config.base_url + path, body, timeout_s or self.config.timeout_s)

    def list_models(self) -> list[dict[str, Any]]:
        """Modèles installés : `[{"name", "size_gb", "parameters", "quantization"}]`."""
        out = []
        for item in self._call("GET", "/api/tags", timeout_s=10).get("models", []):
            details = item.get("details") or {}
            out.append({"name": str(item.get("name", "")), "size_gb": round(float(item.get("size", 0)) / GIB, 2),
                        "parameters": details.get("parameter_size", ""),
                        "quantization": details.get("quantization_level", "")})
        return sorted(out, key=lambda m: m["name"])

    def loaded(self) -> list[dict[str, Any]]:
        """Modèles actuellement en mémoire : `[{"name", "vram_gb", "size_gb", "context"}]` (lu dans `/api/ps`)."""
        out = []
        for item in self._call("GET", "/api/ps", timeout_s=10).get("models", []):
            out.append({"name": str(item.get("name", "")), "vram_gb": round(float(item.get("size_vram", 0)) / GIB, 2),
                        "size_gb": round(float(item.get("size", 0)) / GIB, 2),
                        "context": item.get("context_length")})
        return out

    def estimate_vram_gb(self, model: str) -> float:
        """VRAM à prévoir : la dernière valeur **mesurée** si elle existe, sinon taille des poids x marge."""
        if model in self.measured_vram_gb:
            return self.measured_vram_gb[model]
        for item in self.list_models():
            if item["name"] == model:
                return round(item["size_gb"] * self.config.vram_overhead, 2)
        raise LlmError(f"modèle non installé : {model} (ollama pull {model})")

    # -- chargement / déchargement
    def unload(self, model: str) -> None:
        """Décharge réellement un modèle de la VRAM (`keep_alive: 0`)."""
        self._call("POST", "/api/generate", {"model": model, "keep_alive": 0}, timeout_s=60)
        if self.inoue is not None:
            self.inoue.confirm_llm_unloaded(model)
            self.inoue.release(f"llm-small:{model}")

    def sync(self) -> list[str]:
        """Aligne la comptabilité d'Inoue sur ce qu'Ollama a vraiment en mémoire (les modèles expirent seuls)."""
        if self.inoue is None:
            return []
        in_memory = {m["name"] for m in self.loaded()}
        gone = [m for m in self.inoue.state()["loaded_llms"] if m not in in_memory]
        for model in gone:
            self.inoue.confirm_llm_unloaded(model)
        for key in list(self.inoue.state()["allocations"]):
            if key.startswith("llm-small:") and key.split(":", 1)[1] not in in_memory:
                self.inoue.release(key)
        return gone

    def _reserve(self, model: str) -> None:
        """Demande la VRAM à Inoue et décharge ce qui doit l'être. Lève `LlmRefused` si ça ne tient pas."""
        if self.inoue is None:
            return
        self.sync()
        need = self.estimate_vram_gb(model)
        if need < self.config.big_model_gb:  # petit modèle (vision 7 B, embeddings) : simple attribution
            decision = self.inoue.request(f"llm-small:{model}", need)
            if decision.verdict is not Verdict.GRANTED:
                self.inoue.release(f"llm-small:{model}")
                raise LlmRefused(f"{model} ({need:.1f} Go) : {decision.verdict.value} — {decision.reason}")
            return
        decision, to_unload = self.inoue.plan_llm_load(model, need)
        if decision.verdict is not Verdict.GRANTED:
            raise LlmRefused(f"{model} ({need:.1f} Go) : {decision.verdict.value} — {decision.reason}")
        for other in to_unload:  # un seul gros modèle à la fois : les autres sortent AVANT le chargement
            self._call("POST", "/api/generate", {"model": other, "keep_alive": 0}, timeout_s=60)

    # -- génération
    def chat(self, messages: list[dict[str, Any]], model: str | None = None, num_ctx: int | None = None,
             think: bool | None = None, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Envoie une conversation au modèle local. Retourne `{"content", "model", "num_ctx", "seconds", …}`."""
        model = model or self.config.default_model
        if not model:
            raise LlmError("aucun modèle demandé et aucun modèle par défaut configuré (section `ollama`)")
        ctx = int(num_ctx or self.config.num_ctx)
        with self._lock:  # une génération à la fois : la VRAM n'est pas partagée entre deux gros modèles
            self._reserve(model)
            body: dict[str, Any] = {"model": model, "messages": messages, "stream": False,
                                    "keep_alive": self.config.keep_alive,
                                    "options": {"num_ctx": ctx, **(options or {})}}
            if think is not None:
                body["think"] = think
            started = time.perf_counter()
            try:
                data = self._call("POST", "/api/chat", body)
            except LlmError:
                if self.inoue is not None:  # échec du chargement : la réservation est rendue
                    self.inoue.confirm_llm_unloaded(model)
                    self.inoue.release(f"llm-small:{model}")
                raise
            seconds = round(time.perf_counter() - started, 2)
            vram = None
            try:
                vram = next((m["vram_gb"] for m in self.loaded() if m["name"] == model), None)
            except LlmError:
                pass
            if vram:
                self.measured_vram_gb[model] = vram
        message = data.get("message") or {}
        return {"content": str(message.get("content", "")).strip(), "model": model, "num_ctx": ctx, "seconds": seconds,
                "vram_gb": vram, "prompt_tokens": data.get("prompt_eval_count"),
                "completion_tokens": data.get("eval_count")}

    def state(self) -> dict[str, Any]:
        """État pour l'API du démon. Ne lève jamais : Ollama arrêté = mode dégradé."""
        try:
            loaded, error = self.loaded(), ""
        except LlmError as exc:
            loaded, error = [], str(exc)
        return {"host": self.config.host, "default_model": self.config.default_model, "num_ctx": self.config.num_ctx,
                "reachable": not error, "error": error, "loaded": loaded,
                "measured_vram_gb": dict(self.measured_vram_gb)}


def openai_to_ollama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convertit des messages au format OpenAI (texte, ou parties texte + `image_url` en data URI) pour Ollama."""
    out = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            out.append({"role": message.get("role", "user"), "content": content})
            continue
        texts, images = [], []
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                texts.append(str(part.get("text", "")))
            elif part.get("type") == "image_url":
                url = str((part.get("image_url") or {}).get("url", ""))
                if url.startswith("data:") and "," in url:  # seules les images embarquées sont acceptées :
                    images.append(url.split(",", 1)[1])      # le routeur ne télécharge rien
        converted = {"role": message.get("role", "user"), "content": "\n".join(texts)}
        if images:
            converted["images"] = images
        out.append(converted)
    return out
