"""Service de connaissances du Hub : base vectorielle + collecte polie + ingestion (la nuit, ou à la demande).

Configuration (section `knowledge` de `config/local.yaml`), tout est facultatif :

    knowledge:
      db: "data/knowledge.sqlite"
      embed_model: "nomic-embed-text"   # vide = pas d'embedding (recherche par mots, mode dégradé)
      sources_file: "config/knowledge_sources.yaml"
      min_delay_s: 5                    # délai minimal entre deux requêtes vers un même site
      nightly: true                     # ingestion confiée à Fuma, chaque nuit

L'ingestion tourne dans **un fil séparé** : le tour de surveillance du démon n'est jamais bloqué.
Les domaines autorisés viennent de `web_domains` dans `config/allowlist.yaml`.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.knowledge.fetcher import FetchRefused, PoliteFetcher
from core.knowledge.store import KnowledgeError, KnowledgeStore, ollama_embedder

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ImportError):
        return {}
    return data if isinstance(data, dict) else {}


def load_sources(path: Path) -> list[dict[str, Any]]:
    """Sources déclarées : `url` (https), `license` (obligatoire), `tags`. Les entrées incomplètes sont ignorées."""
    sources = []
    for entry in _yaml(path).get("sources") or []:
        if isinstance(entry, dict) and str(entry.get("url", "")).startswith("https://") and entry.get("license"):
            sources.append({"url": str(entry["url"]), "license": str(entry["license"]),
                            "tags": [str(t) for t in entry.get("tags") or []], "title": str(entry.get("title", ""))})
    return sources


def allowed_domains(path: Path | None = None) -> list[str]:
    return [str(d) for d in _yaml(path or REPO_ROOT / "config" / "allowlist.yaml").get("web_domains") or []]


def ingest(store: KnowledgeStore, fetcher: PoliteFetcher, sources: list[dict[str, Any]],
           stop: threading.Event | None = None) -> dict[str, Any]:
    """Récupère chaque source et l'indexe. Une source en échec est notée, les suivantes continuent."""
    report: dict[str, Any] = {"added": 0, "replaced": 0, "unchanged": 0, "refused": [], "errors": []}
    for source in sources:
        if stop is not None and stop.is_set():
            report["stopped"] = True
            break
        try:
            page = fetcher.fetch(source["url"])
            if len(page.text) < 200:
                report["refused"].append({"url": source["url"], "reason": "texte trop court"})
                continue
            result = store.add_document(source["url"], source.get("title") or page.title or source["url"], page.text,
                                        source["license"], tags=source.get("tags", ()), fetched_at=page.fetched_at)
            report[result["status"]] += 1
        except FetchRefused as exc:
            report["refused"].append({"url": source["url"], "reason": str(exc)})
        except (KnowledgeError, OSError, ValueError) as exc:
            report["errors"].append({"url": source["url"], "error": f"{type(exc).__name__}: {exc}"})
    return report


class KnowledgeService:
    def __init__(self, settings: dict[str, Any] | None = None, root: Path = REPO_ROOT,
                 store: KnowledgeStore | None = None, fetcher: PoliteFetcher | None = None,
                 now: Callable[[], float] = time.time) -> None:
        settings = settings or {}
        self.root = root
        embed_model = str(settings.get("embed_model", "nomic-embed-text"))
        host = str(settings.get("ollama_host", "127.0.0.1:11434"))
        self.store = store or KnowledgeStore(root / str(settings.get("db", "data/knowledge.sqlite")),
                                             embedder=ollama_embedder(host, embed_model) if embed_model else None)
        self.fetcher = fetcher or PoliteFetcher(
            root / "cache" / "web", allowed_domains(root / "config" / "allowlist.yaml"),
            journal=root / "logs" / "web_fetch.jsonl", min_delay_s=float(settings.get("min_delay_s", 5)))
        self.sources_file = root / str(settings.get("sources_file", "config/knowledge_sources.yaml"))
        self.nightly = bool(settings.get("nightly", True))
        self._now = now
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_report: dict[str, Any] = {}
        self.last_run: dict[str, Any] = {}

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start_ingestion(self) -> bool:
        """Lance l'ingestion en arrière-plan. `False` si elle tourne déjà."""
        if self.running():
            return False
        self._stop.clear()
        sources = load_sources(self.sources_file)
        self.last_run = {"started_at": self._now(), "sources": len(sources)}

        def work() -> None:
            self.last_report = ingest(self.store, self.fetcher, sources, self._stop)
            self.last_run["finished_at"] = self._now()

        self._thread = threading.Thread(target=work, name="knowledge-ingest", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def search(self, query: str, k: int = 5, tag: str = "") -> dict[str, Any]:
        hits = self.store.search(query, k=k, tag=tag)
        return {"hits": [h.to_dict() for h in hits], "degraded": self.store.last_degraded_reason}

    def state(self) -> dict[str, Any]:
        return {"stats": self.store.stats(), "running": self.running(), "nightly": self.nightly,
                "sources_file": str(self.sources_file.relative_to(self.root)) if self.sources_file.is_relative_to(
                    self.root) else self.sources_file.name,
                "last_run": self.last_run, "last_report": self.last_report}
