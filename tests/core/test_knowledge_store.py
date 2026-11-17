"""Base vectorielle : découpage, recherche par vecteurs (faux embedder déterministe), mode dégradé, sources."""
from __future__ import annotations

import hashlib
import os

import pytest

from core.knowledge.store import (
    KnowledgeError,
    KnowledgeStore,
    _words,
    chunk_text,
    cosine,
    lexical_score,
    ollama_embedder,
)


def fake_embedder(dimension: int = 64, name: str = "faux-v1"):
    """Sac de mots haché : deux textes qui partagent des mots ont des vecteurs proches. Déterministe."""
    calls: list[int] = []

    def embed(texts: list[str]) -> list[list[float]]:
        calls.append(len(texts))
        vectors = []
        for text in texts:
            vector = [0.0] * dimension
            for word in _words(text):
                vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % dimension] += 1.0  # noqa: S324
            vectors.append(vector)
        return vectors
    embed.model_name = name  # type: ignore[attr-defined]
    embed.calls = calls  # type: ignore[attr-defined]
    return embed


ASTRO = ("La vitesse de libération est la vitesse minimale pour quitter l'attraction d'un astre.\n\n"
         "Pour la Terre, la vitesse de libération vaut environ 11,2 km/s au niveau du sol.")
BIO = ("Le pourcentage GC mesure la proportion de guanine et de cytosine dans une séquence d'ADN.\n\n"
       "Un ADN riche en GC est plus stable, car la paire G-C forme trois liaisons hydrogène.")
CHEM = "Le pH d'un acide faible dépend de sa constante d'acidité Ka et de sa concentration."


@pytest.fixture
def store(tmp_path):
    s = KnowledgeStore(tmp_path / "k.sqlite", embedder=fake_embedder())
    s.add_document("https://exemple.org/astro", "Vitesse de libération", ASTRO, "CC BY-SA 4.0", tags=["astro"])
    s.add_document("https://exemple.org/bio", "Pourcentage GC", BIO, "CC BY-SA 4.0", tags=["bio"])
    s.add_document("https://exemple.org/chem", "pH d'un acide faible", CHEM, "CC BY 4.0", tags=["chem"])
    yield s
    s.close()


def test_chunk_text_respects_size_and_keeps_everything() -> None:
    text = "\n\n".join(f"Paragraphe {i}. " + "mot " * 60 for i in range(12))
    chunks = chunk_text(text, max_chars=500, overlap=80)
    assert all(len(c) <= 500 for c in chunks) and len(chunks) > 3
    for i in range(12):
        assert any(f"Paragraphe {i}." in c for c in chunks)
    long = "Phrase courte. " * 200
    assert all(len(c) <= 900 for c in chunk_text(long))
    assert chunk_text("") == []


def test_cosine_and_lexical() -> None:
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0
    assert lexical_score("vitesse libération", "La VITESSE de liberation") == pytest.approx(0.8)
    assert lexical_score("vitesse libération", "La VITESSE de liberation", title="Vitesse de libération") == 1.0
    assert _words("Le pH et le Ka de la solution") == {"ph", "ka", "solution"}  # mots courts gardés, vides retirés


def test_rare_words_weigh_more_in_degraded_mode(tmp_path) -> None:
    plain = KnowledgeStore(tmp_path / "p.sqlite")
    plain.add_document("https://exemple.org/code", "Code génétique", "Un acide aminé faible ou fort, selon le codon. "
                       "Chaque acide aminé est codé par un triplet.", "CC0")
    plain.add_document("https://exemple.org/ph", "Potentiel hydrogène", "Le pH d'un acide faible dépend de son Ka.",
                       "CC0")
    plain.add_document("https://exemple.org/autre", "Autre", "Un acide fort se dissocie totalement.", "CC0")
    assert plain.search("pH acide faible Ka", k=1)[0].url == "https://exemple.org/ph"
    plain.close()


def test_vector_search_finds_the_right_source(store) -> None:
    hits = store.search("quelle vitesse pour la libération depuis la Terre ?", k=2)
    assert hits[0].url == "https://exemple.org/astro" and hits[0].mode == "vecteurs"
    assert store.search("guanine cytosine ADN", k=1)[0].url == "https://exemple.org/bio"
    assert [h.url for h in store.search("acide", k=5, tag="chem")] == ["https://exemple.org/chem"]
    assert store.stats() == {"documents": 3, "chunks": 3, "vectorized": 3, "embedder": "faux-v1",
                             "dimension": 64, "configured_embedder": "faux-v1"}


def test_sources_for_the_tutor(store) -> None:
    sources = store.sources_for("pourcentage GC séquence")
    assert sources[0]["url"] == "https://exemple.org/bio" and sources[0]["license"] == "CC BY-SA 4.0"
    assert set(sources[0]) == {"title", "url", "license", "excerpt"}


def test_unchanged_document_is_not_reembedded(store) -> None:
    calls = store.embedder.calls
    before = len(calls)
    assert store.add_document("https://exemple.org/bio", "Pourcentage GC", BIO, "CC BY-SA 4.0")["status"] == "unchanged"
    assert len(calls) == before
    result = store.add_document("https://exemple.org/bio", "Pourcentage GC", BIO + "\n\nAjout.", "CC BY-SA 4.0")
    assert result["status"] == "replaced" and store.stats()["documents"] == 3


def test_license_is_mandatory(store) -> None:
    with pytest.raises(KnowledgeError, match="licence"):
        store.add_document("https://exemple.org/x", "X", "texte", license=" ")


def test_mixing_embedding_models_is_refused_then_reindex(tmp_path, store) -> None:
    other = KnowledgeStore(store.path, embedder=fake_embedder(32, name="autre-v2"))
    with pytest.raises(KnowledgeError, match="réindexer"):
        other.add_document("https://exemple.org/y", "Y", "nouveau texte", "CC0")
    hits = other.search("vitesse libération")  # recherche : bascule sur les mots, signalée
    assert hits and hits[0].mode == "mots" and "faux-v1" in other.last_degraded_reason
    assert other.reindex() == 3
    assert other.search("vitesse libération")[0].mode == "vecteurs"
    other.close()


def test_degraded_mode_without_embedder_or_when_it_fails(tmp_path) -> None:
    plain = KnowledgeStore(tmp_path / "p.sqlite")
    plain.add_document("https://exemple.org/astro", "Vitesse de libération", ASTRO, "CC BY-SA 4.0")
    hit = plain.search("libération de la Terre")[0]
    assert hit.mode == "mots" and "embedding" in plain.last_degraded_reason
    assert plain.search("rien à voir zzz") == []

    def broken(texts):
        raise KnowledgeError("embedding indisponible (test)")

    plain.embedder, plain.embedder_name = broken, "cassé"
    result = plain.add_document("https://exemple.org/bio", "GC", BIO, "CC BY-SA 4.0")
    assert result["vectorized"] is False and "indisponible" in result["embed_error"]  # texte gardé, sans vecteur
    assert plain.stats()["documents"] == 2 and plain.stats()["vectorized"] == 0
    assert plain.search("guanine cytosine")[0].mode == "mots"
    plain.embedder, plain.embedder_name = fake_embedder(), "faux-v1"  # le modèle revient : on rattrape
    assert plain.reindex() == 2 and plain.stats()["vectorized"] == 2
    assert plain.search("guanine cytosine")[0].mode == "vecteurs"
    plain.close()


def test_ollama_embedder_reports_a_clear_error() -> None:
    embed = ollama_embedder(host="127.0.0.1:9", timeout_s=1)  # port fermé
    with pytest.raises(KnowledgeError, match="embedding indisponible"):
        embed(["bonjour"])


@pytest.mark.skipif(os.environ.get("AETHERTWIN_REAL_OLLAMA") != "1", reason="test réel : AETHERTWIN_REAL_OLLAMA=1")
def test_real_ollama_embedding(tmp_path) -> None:  # demande `ollama pull nomic-embed-text`
    store = KnowledgeStore(tmp_path / "r.sqlite", embedder=ollama_embedder())
    store.add_document("https://exemple.org/astro", "Vitesse de libération", ASTRO, "CC BY-SA 4.0")
    store.add_document("https://exemple.org/bio", "Pourcentage GC", BIO, "CC BY-SA 4.0")
    hits = store.search("Combien faut-il de km/s pour échapper à la gravité terrestre ?", k=1)
    print(store.stats(), hits[0].score)
    assert hits[0].url == "https://exemple.org/astro" and hits[0].mode == "vecteurs"
