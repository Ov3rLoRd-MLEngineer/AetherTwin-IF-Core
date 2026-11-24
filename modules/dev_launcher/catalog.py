"""Catalogue des modèles pour Claude Code local : Ollama (direct) et OmniRoute (facultatif).

- Ollama sert directement le format de Claude Code (`/v1/messages`) depuis ses versions récentes : c'est la route
  par défaut, sans routeur à installer sur un PC vierge.
- OmniRoute ajoute ses fournisseurs (Antigravity, Gemini…). Sa liste `/v1/models` demande sa clé : elle est lue
  dans une variable d'environnement (jamais dans le dépôt). Sans clé, la liste exportée à côté de l'ancien lanceur
  (`liste modèles json.txt`) sert de repli.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MODEL_ID = re.compile(r"^[\w.:/@+-]{1,160}$")
# Préfixes d'OmniRoute retenus par l'ancien lanceur (fournisseurs utilisables par Claude Code).
OMNI_PREFIXES = ("agy/", "antigravity/", "dva/", "aug/", "zc/", "cxa/", "gemini/")


def _get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 4.0) -> Any:
    req = urllib.request.Request(url, headers=headers or {})  # noqa: S310 — adresses http locales de la config
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 — adresses locales configurées
        return json.loads(response.read().decode("utf-8"))


def service_up(url: str, timeout: float = 3.0) -> bool:
    """Le service répond-il (même par une erreur HTTP : il est lancé) ?"""
    try:
        with urllib.request.urlopen(url, timeout=timeout):  # noqa: S310
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _size_gb(value: Any) -> float:
    try:
        return round(float(value) / 1e9, 1)
    except (TypeError, ValueError):
        return 0.0


def num_ctx(base: str, name: str, timeout: float = 4.0) -> int:
    """Contexte réglé dans le Modelfile du modèle (`PARAMETER num_ctx`), 0 s'il n'y en a pas."""
    try:
        req = urllib.request.Request(f"{base}/api/show", data=json.dumps({"model": name}).encode("utf-8"),  # noqa: S310
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            params = json.loads(response.read().decode("utf-8")).get("parameters") or ""
    except (urllib.error.URLError, OSError, ValueError):
        return 0
    found = re.search(r"^num_ctx\s+(\d+)", params, re.M)
    return int(found.group(1)) if found else 0


def ollama_models(base: str, timeout: float = 4.0) -> dict[str, Any]:
    """Modèles installés (et chargés) dans Ollama. Les modèles d'embedding sont écartés."""
    base = base.rstrip("/")
    try:
        tags = _get_json(f"{base}/api/tags", timeout=timeout)
        version = _get_json(f"{base}/api/version", timeout=timeout).get("version", "")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"en_ligne": False, "erreur": str(exc)[:200], "modeles": []}
    try:
        loaded = {m.get("name"): m for m in _get_json(f"{base}/api/ps", timeout=timeout).get("models", [])}
    except (urllib.error.URLError, OSError, ValueError):
        loaded = {}
    models = []
    for item in tags.get("models", []):
        name = str(item.get("name", ""))
        details = item.get("details") or {}
        family = " ".join(details.get("families") or [details.get("family", "")]).lower()
        if not name or "embed" in name.lower() or "bert" in family:
            continue
        live = loaded.get(name) or {}
        configured = num_ctx(base, name, timeout)
        models.append({
            "id": name, "nom": name, "route": "ollama", "fournisseur": "Ollama (local)",
            "taille_go": _size_gb(item.get("size")), "parametres": details.get("parameter_size", ""),
            "quantification": details.get("quantization_level", ""), "famille": details.get("family", ""),
            "charge": bool(live), "contexte": live.get("context_length") or configured or None,
            "contexte_regle": configured,  # num_ctx du modèle (Modelfile) ; 0 = défaut d'Ollama
            "vram_go": _size_gb(live.get("size_vram")) if live else None,
        })
    models.sort(key=lambda m: (not m["charge"], m["id"].lower()))
    return {"en_ligne": True, "version": version, "modeles": models}


def variant_name(model: str, context: int = 65536) -> str:
    """Nom de la variante : « dépôt:étiquette-64k » (« dépôt:latest » devient « dépôt:64k »)."""
    if not MODEL_ID.match(model or "") or "/" in model.split(":", 1)[-1]:
        raise ValueError("identifiant de modèle invalide")
    suffix = f"{context // 1024}k"
    repo, _, tag = model.partition(":")
    if tag.endswith(f"-{suffix}") or tag == suffix:
        raise ValueError(f"{model} est déjà une variante {suffix}")
    return f"{repo}:{suffix}" if tag in ("", "latest") else f"{repo}:{tag}-{suffix}"


def create_variant(base: str, model: str, context: int = 65536, timeout: float = 600.0) -> dict[str, Any]:
    """Crée dans Ollama une variante du modèle servie avec `context` jetons (aucun poids copié)."""
    name = variant_name(model, context)
    body = json.dumps({"model": name, "from": model, "parameters": {"num_ctx": int(context)},
                       "stream": False}).encode("utf-8")
    req = urllib.request.Request(f"{base.rstrip('/')}/api/create", data=body,  # noqa: S310 — Ollama local
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            reply = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Ollama a refusé : {exc.read().decode('utf-8', 'replace')[:200]}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(f"Ollama injoignable : {exc}") from exc
    if reply.get("status") not in (None, "success"):
        raise ValueError(f"Ollama : {reply.get('status')}")
    return {"modele": name, "depuis": model, "contexte": int(context), "contexte_servi": num_ctx(base, name)}


def _omni_entry(raw: dict[str, Any]) -> dict[str, Any] | None:
    model_id = str(raw.get("id", ""))
    low = model_id.lower()
    if (not MODEL_ID.match(model_id) or "embed" in low or "image" in low or low.endswith("-disabled")
            or not low.startswith(OMNI_PREFIXES)):
        return None
    caps = raw.get("capabilities") or {}
    return {
        "id": model_id, "nom": str(raw.get("name") or model_id).split("/", 1)[-1], "route": "omniroute",
        "fournisseur": "OmniRoute · " + model_id.split("/", 1)[0], "contexte": raw.get("context_length"),
        "sortie_max": raw.get("max_output_tokens"),
        "capacites": [label for key, label in (("tool_calling", "outils"), ("vision", "vision"),
                                                ("reasoning", "raisonnement")) if caps.get(key)],
    }


def omniroute_models(url: str, key_env: str = "OMNIROUTE_API_KEY", fallback: Path | None = None,
                     timeout: float = 4.0) -> dict[str, Any]:
    """Modèles d'OmniRoute : liste en direct avec la clé (variable d'environnement), sinon la liste exportée."""
    base = url.rstrip("/").removesuffix("/v1")
    online = service_up(base + "/", timeout)
    key = os.environ.get(key_env, "") if key_env else ""
    data, source, error = None, "", ""
    if online and key:
        try:
            data = _get_json(f"{base}/v1/models", {"Authorization": f"Bearer {key}"}, timeout)
            source = "en direct"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            error = f"liste refusée ({str(exc)[:120]})"
    if data is None and fallback and fallback.is_file():
        try:
            data = json.loads(fallback.read_text(encoding="utf-8"))
            source = "liste exportée"
        except (OSError, ValueError) as exc:
            error = error or f"liste exportée illisible ({exc})"
    raw = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    models = [entry for entry in (_omni_entry(r) for r in raw if isinstance(r, dict)) if entry]
    return {"en_ligne": online, "cle": bool(key), "source": source, "erreur": error, "modeles": models}
