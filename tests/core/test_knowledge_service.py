"""Service de connaissances : sources déclarées, ingestion en arrière-plan, API du Hub, tâche de nuit de Fuma."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.daemon import Daemon
from core.hardware.gpu_monitor import GpuMonitor, UnknownBackend
from core.knowledge.fetcher import PoliteFetcher
from core.knowledge.service import KnowledgeService, allowed_domains, ingest, load_sources
from core.knowledge.store import KnowledgeStore
from core.llm_router import LlmRouter
from tests.core.test_daemon import ollama_stopped, wait_for
from tests.core.test_knowledge_store import fake_embedder

REPO = Path(__file__).resolve().parents[2]
LONG = "<p>" + "La vitesse de libération dépend de la masse de l'astre et de son rayon. " * 6 + "</p>"


def web(url, headers, timeout):
    pages = {
        "https://fr.wikipedia.org/robots.txt": (200, b"User-agent: *\nDisallow: /w/\n"),
        "https://fr.wikipedia.org/wiki/Liberation": (200, f"<title>Vitesse</title>{LONG}".encode()),
        "https://fr.wikipedia.org/wiki/Court": (200, b"<p>Trop court.</p>"),
    }
    status, body = pages.get(url, (404, b""))
    return status, {"content-type": "text/html; charset=utf-8"}, body


SOURCES = [
    {"url": "https://fr.wikipedia.org/wiki/Liberation", "license": "CC BY-SA 4.0", "tags": ["astro"], "title": ""},
    {"url": "https://fr.wikipedia.org/wiki/Court", "license": "CC BY-SA 4.0", "tags": [], "title": ""},
    {"url": "https://fr.wikipedia.org/w/index.php", "license": "CC BY-SA 4.0", "tags": [], "title": ""},
    {"url": "https://fr.wikipedia.org/wiki/Absente", "license": "CC BY-SA 4.0", "tags": [], "title": ""},
]


def make_service(tmp_path: Path) -> KnowledgeService:
    store = KnowledgeStore(tmp_path / "k.sqlite", embedder=fake_embedder())
    fetcher = PoliteFetcher(tmp_path / "cache", ["wikipedia.org"], journal=tmp_path / "j.jsonl", min_delay_s=0,
                            opener=web)
    sources = tmp_path / "sources.yaml"
    sources.write_text("sources:\n  - {url: 'https://fr.wikipedia.org/wiki/Liberation', license: 'CC BY-SA 4.0',"
                       " tags: [astro]}\n", encoding="utf-8")
    return KnowledgeService({"sources_file": str(sources)}, root=tmp_path, store=store, fetcher=fetcher)


def test_repo_sources_are_declared_and_allowed() -> None:
    sources = load_sources(REPO / "config" / "knowledge_sources.yaml")
    domains = allowed_domains(REPO / "config" / "allowlist.yaml")
    assert len(sources) >= 15 and domains == ["wikipedia.org"]
    for source in sources:
        assert source["license"] and source["tags"] and source["url"].startswith("https://fr.wikipedia.org/wiki/")


def test_load_sources_skips_incomplete_entries(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text("sources:\n  - {url: 'https://a.org/x'}\n  - {url: 'http://a.org/y', license: CC0}\n"
                    "  - {url: 'https://a.org/z', license: CC0, tags: [t]}\n", encoding="utf-8")
    assert [s["url"] for s in load_sources(path)] == ["https://a.org/z"]
    assert load_sources(tmp_path / "absent.yaml") == []


def test_ingest_reports_each_outcome(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    report = ingest(service.store, service.fetcher, SOURCES)
    assert report["added"] == 1 and report["errors"] == []
    reasons = {r["url"].rsplit("/", 1)[-1]: r["reason"] for r in report["refused"]}
    assert reasons["Court"] == "texte trop court" and "robots" in reasons["index.php"] and "404" in reasons["Absente"]
    assert ingest(service.store, service.fetcher, SOURCES[:1])["unchanged"] == 1  # le cache et le hachage servent
    hit = service.search("masse de l'astre")["hits"][0]
    assert hit["title"] == "Vitesse" and hit["license"] == "CC BY-SA 4.0"


def test_hub_api_and_night_task(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from core.api import create_app

    service = make_service(tmp_path)
    (tmp_path / "modules").mkdir()
    daemon = Daemon(tmp_path / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped), knowledge=service)
    assert [t["name"] for t in daemon.fuma.state()["night_tasks"]] == ["ingestion des connaissances"]
    client = TestClient(create_app(daemon))
    assert client.post("/knowledge/ingest").json()["started"] is True
    assert wait_for(lambda: not service.running() and service.last_report.get("added") == 1)
    assert client.get("/knowledge").json()["stats"]["documents"] == 1
    hits = client.get("/knowledge/search", params={"q": "vitesse de libération", "k": 2}).json()["hits"]
    assert hits[0]["url"] == "https://fr.wikipedia.org/wiki/Liberation"
    assert client.get("/health").json()["knowledge"]["stats"]["documents"] == 1


def test_ingestion_catches_up_vectors_once_the_model_exists(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    working = service.store.embedder

    def missing(texts):
        from core.knowledge.store import KnowledgeError
        raise KnowledgeError("embedding indisponible (modèle absent)")

    service.store.embedder = missing
    assert service.start_ingestion()
    assert wait_for(lambda: not service.running() and "reindex_error" in service.last_report)
    assert service.store.stats()["vectorized"] == 0
    service.store.embedder = working  # `ollama pull` fait : la collecte suivante rattrape les vecteurs
    assert service.start_ingestion()
    assert wait_for(lambda: not service.running() and service.last_report.get("reindexed") == 1)
    assert service.last_report["unchanged"] == 1 and service.store.stats()["vectorized"] == 1


def test_api_without_knowledge_is_503(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from core.api import create_app

    (tmp_path / "modules").mkdir()
    daemon = Daemon(tmp_path / "modules", monitor=GpuMonitor(UnknownBackend()), process_names=lambda: set(),
                    llm=LlmRouter(transport=ollama_stopped))
    assert TestClient(create_app(daemon)).get("/knowledge/search", params={"q": "x"}).status_code == 503


@pytest.mark.parametrize("hits, expected", [
    ([], []),
    ([{"title": "T", "url": "https://u", "license": "L"}],
     [{"title": "T", "url": "https://u", "license": "L", "text": ""}]),
])
def test_professor_hub_search(monkeypatch, hits, expected) -> None:
    import io
    import json

    from modules.genesis_lab import module

    seen = []

    def fake_urlopen(url, timeout):
        seen.append(url)
        return io.BytesIO(json.dumps({"hits": hits}).encode())

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    assert module.hub_search("http://127.0.0.1:5750")("pH acide faible") == expected
    assert seen == ["http://127.0.0.1:5750/knowledge/search?q=pH+acide+faible&k=3"]
