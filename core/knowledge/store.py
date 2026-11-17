"""Base de connaissances locale : textes découpés, vecteurs d'embedding, recherche par similarité.

Tout tient dans un seul fichier SQLite (bibliothèque standard), sans dépendance lourde :

    store = KnowledgeStore(Path("data/knowledge.sqlite"), embedder=ollama_embedder())
    store.add_document("https://…", "Titre", texte, license="CC BY-SA 4.0")
    store.search("vitesse de libération", k=3)

- L'embedding est **injectable** (`Embedder`) : les tests passent de faux vecteurs, le Hub passe
  `ollama_embedder()` (modèle local, ex. `nomic-embed-text`, à installer par `ollama pull`).
- Sans embedder, ou si le modèle d'embedding est injoignable, la recherche retombe sur un score par mots
  communs (**mode dégradé**, signalé dans le résultat). On n'invente jamais un vecteur.
- La base retient le nom du modèle d'embedding : mélanger deux modèles rendrait les distances absurdes,
  donc c'est refusé (`KnowledgeError`), il faut réindexer.
- Chaque passage garde sa source (URL, titre, licence, date) pour être cité.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.request
from array import array
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

Embedder = Callable[[list[str]], list[list[float]]]

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, license TEXT NOT NULL,
    fetched_at REAL NOT NULL, content_hash TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, text TEXT NOT NULL, vector BLOB
);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
"""


class KnowledgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Hit:
    url: str
    title: str
    license: str
    text: str
    score: float
    mode: str  # "vecteurs" ou "mots" (mode dégradé)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -- découpage et similarité ---------------------------------------------------------------------------------------
def chunk_text(text: str, max_chars: int = 900, overlap: int = 150) -> list[str]:
    """Découpe par paragraphes, en morceaux d'au plus `max_chars`, avec un recouvrement pour garder le contexte."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        while len(paragraph) > max_chars:  # paragraphe trop long : coupe sur une fin de phrase si possible
            cut = paragraph.rfind(". ", 0, max_chars)
            cut = cut + 1 if cut > max_chars // 2 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[max(0, cut - overlap):].strip()
        if current and len(current) + 2 + len(paragraph) > max_chars:
            chunks.append(current)
            current = current[-overlap:].lstrip() + "\n\n" + paragraph if overlap else paragraph
            if len(current) > max_chars:
                current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / math.sqrt(na * nb) if na and nb else 0.0


def _words(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")
    return {w for w in re.findall(r"[a-z0-9]{3,}", plain)}


def lexical_score(query: str, text: str) -> float:
    q, t = _words(query), _words(text)
    return len(q & t) / len(q) if q else 0.0


def _pack(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def _unpack(blob: bytes) -> array:
    values = array("f")
    values.frombytes(blob)
    return values


# -- embedder local ------------------------------------------------------------------------------------------------
def ollama_embedder(host: str = "127.0.0.1:11434", model: str = "nomic-embed-text",
                    timeout_s: float = 120.0) -> Embedder:
    """Embeddings par le serveur Ollama local (`/api/embed`). Lève `KnowledgeError` si indisponible."""
    def embed(texts: list[str]) -> list[list[float]]:
        body = json.dumps({"model": model, "input": texts, "keep_alive": "2m"}).encode("utf-8")
        request = urllib.request.Request(f"http://{host}/api/embed", data=body,  # noqa: S310 — Ollama local
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — réseau, 404 modèle absent… : une seule erreur claire
            raise KnowledgeError(f"embedding indisponible ({model} sur {host}) : {exc}") from exc
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise KnowledgeError(f"réponse d'embedding inattendue de {model}")
        return vectors
    embed.model_name = model  # type: ignore[attr-defined]
    return embed


# -- la base -------------------------------------------------------------------------------------------------------
class KnowledgeStore:
    def __init__(self, path: Path, embedder: Embedder | None = None, embedder_name: str = "",
                 now: Callable[[], float] = time.time) -> None:
        self.path = path
        self.embedder = embedder
        self.embedder_name = embedder_name or str(getattr(embedder, "model_name", "") or
                                                  ("inconnu" if embedder else ""))
        self._now = now
        self._lock = threading.Lock()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self.last_degraded_reason = ""

    def close(self) -> None:
        self._db.close()

    # -- méta
    def _meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _check_embedder(self) -> None:
        stored = self._meta("embedder")
        if stored and self.embedder and stored != self.embedder_name:
            raise KnowledgeError(f"la base a été indexée avec « {stored} », pas « {self.embedder_name} » : "
                                 "réindexer (reindex) avant de mélanger les modèles")

    # -- écriture
    def add_document(self, url: str, title: str, text: str, license: str, tags: Iterable[str] = (),  # noqa: A002
                     fetched_at: float | None = None) -> dict[str, Any]:
        """Ajoute ou remplace un document. Sans changement de contenu, ne refait rien (`unchanged`)."""
        if not license.strip():
            raise KnowledgeError("licence obligatoire : on ne stocke pas un texte dont on ignore les droits")
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunks = chunk_text(text)
        with self._lock:
            row = self._db.execute("SELECT id, content_hash FROM documents WHERE url = ?", (url,)).fetchone()
            if row and row[1] == content_hash:
                return {"url": url, "status": "unchanged", "chunks": 0}
            vectors: list[list[float]] | None = None
            if self.embedder is not None and chunks:
                self._check_embedder()
                vectors = self.embedder(chunks)  # KnowledgeError remonte : rien n'est écrit à moitié
            with self._db:
                if row:
                    self._db.execute("DELETE FROM documents WHERE id = ?", (row[0],))
                cursor = self._db.execute(
                    "INSERT INTO documents (url, title, license, fetched_at, content_hash, tags) VALUES (?,?,?,?,?,?)",
                    (url, title, license, fetched_at if fetched_at is not None else self._now(), content_hash,
                     json.dumps(sorted(set(tags)))))
                doc_id = cursor.lastrowid
                self._db.executemany(
                    "INSERT INTO chunks (document_id, position, text, vector) VALUES (?,?,?,?)",
                    [(doc_id, i, chunk, _pack(vectors[i]) if vectors else None) for i, chunk in enumerate(chunks)])
                if vectors:
                    self._db.execute("INSERT OR REPLACE INTO meta VALUES ('embedder', ?)", (self.embedder_name,))
                    self._db.execute("INSERT OR REPLACE INTO meta VALUES ('dimension', ?)", (str(len(vectors[0])),))
        return {"url": url, "status": "replaced" if row else "added", "chunks": len(chunks)}

    def remove(self, url: str) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM documents WHERE url = ?", (url,)).rowcount > 0

    def reindex(self) -> int:
        """Recalcule tous les vecteurs avec l'embedder courant (changement de modèle). Rend le nombre de passages."""
        if self.embedder is None:
            raise KnowledgeError("aucun embedder : rien à réindexer")
        with self._lock:
            rows = self._db.execute("SELECT id, text FROM chunks ORDER BY id").fetchall()
            vectors = self.embedder([text for _, text in rows]) if rows else []
            with self._db:
                self._db.executemany("UPDATE chunks SET vector = ? WHERE id = ?",
                                     [(_pack(v), cid) for (cid, _), v in zip(rows, vectors, strict=True)])
                self._db.execute("INSERT OR REPLACE INTO meta VALUES ('embedder', ?)", (self.embedder_name,))
        return len(rows)

    # -- lecture
    def search(self, query: str, k: int = 5, tag: str = "") -> list[Hit]:
        """Les `k` passages les plus proches. Retombe sur les mots communs si les vecteurs sont indisponibles."""
        sql = ("SELECT c.text, c.vector, d.url, d.title, d.license FROM chunks c JOIN documents d "
               "ON d.id = c.document_id")
        params: tuple[Any, ...] = ()
        if tag:
            sql += " WHERE d.tags LIKE ?"
            params = (f'%"{tag}"%',)
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        query_vector: list[float] | None = None
        self.last_degraded_reason = ""
        if self.embedder is None:
            self.last_degraded_reason = "pas de modèle d'embedding configuré"
        else:
            try:
                self._check_embedder()
                query_vector = self.embedder([query])[0]
            except KnowledgeError as exc:
                self.last_degraded_reason = str(exc)
        hits: list[Hit] = []
        for text, blob, url, title, license_ in rows:
            if query_vector is not None and blob is not None:
                vector = _unpack(blob)
                if len(vector) != len(query_vector):
                    continue
                hits.append(Hit(url, title, license_, text, round(cosine(query_vector, vector), 4), "vecteurs"))
            elif query_vector is None:
                score = lexical_score(query, f"{title} {text}")
                if score > 0:
                    hits.append(Hit(url, title, license_, text, round(score, 4), "mots"))
        hits.sort(key=lambda h: h.score, reverse=True)
        best: list[Hit] = []
        seen: set[str] = set()
        for hit in hits:  # au plus deux passages par document, pour varier les sources
            if sum(1 for b in best if b.url == hit.url) >= 2 or (hit.url, hit.text) in seen:
                continue
            seen.add((hit.url, hit.text))  # type: ignore[arg-type]
            best.append(hit)
            if len(best) == k:
                break
        return best

    def sources_for(self, query: str, k: int = 3) -> list[dict[str, str]]:
        """Format attendu par le Professeur (`Tutor(search=…)`) : titre, URL, licence, extrait."""
        return [{"title": h.title, "url": h.url, "license": h.license, "excerpt": h.text[:300]}
                for h in self.search(query, k=k)]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            documents = self._db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunks, vectors = self._db.execute("SELECT COUNT(*), COUNT(vector) FROM chunks").fetchone()
        return {"documents": documents, "chunks": chunks, "vectorized": vectors,
                "embedder": self._meta("embedder") or "", "dimension": int(self._meta("dimension") or 0),
                "configured_embedder": self.embedder_name}
