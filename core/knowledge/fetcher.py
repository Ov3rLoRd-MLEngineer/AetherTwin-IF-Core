"""Collecte web **polie** pour la base de connaissances.

Règles, toutes appliquées ici et testées :
- **domaines autorisés seulement** (`web_domains` de `config/allowlist.yaml`) ; https uniquement ;
- **robots.txt** lu et respecté pour notre User-Agent (robots illisible → on s'abstient) ;
- **débit limité** : un délai minimal entre deux requêtes vers le même hôte ;
- **User-Agent honnête** qui nomme le projet, sans donnée personnelle ;
- **cache local** : une page déjà récupérée et encore fraîche n'est pas redemandée ;
- **journal** JSONL de chaque décision (récupéré, cache, refusé par robots, hors liste…) ;
- taille maximale et types de contenu limités au texte (HTML, texte brut).

Le transport (`opener`) et l'horloge sont injectables : les tests ne touchent pas le réseau.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

USER_AGENT = "AetherTwin-IFCore/0.1 (assistant local de recherche ; collecte polie, respecte robots.txt)"
MAX_BYTES = 3 * 1024 * 1024
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")

# opener(url, headers, timeout) -> (status, headers en minuscules, corps)
Opener = Callable[[str, dict[str, str], float], tuple[int, dict[str, str], bytes]]


class FetchRefused(RuntimeError):
    """La page n'est pas récupérée, et c'est voulu (hors liste, robots.txt, type, taille)."""


@dataclass
class Page:
    url: str
    status: int
    title: str
    text: str
    fetched_at: float
    from_cache: bool = False


def urllib_opener(url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 — https et domaine vérifiés avant
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read(MAX_BYTES + 1)
            return response.status, {k.lower(): v for k, v in response.headers.items()}, body
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, b""


class _TextExtractor(HTMLParser):
    """Texte lisible d'une page HTML : titres et paragraphes, sans scripts, menus ni pieds de page."""

    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "table", "sup",
            "figure", "button"}
    # Classes d'habillage (bandeaux, liens « modifier », boîtes de navigation, références…), tous sites confondus.
    # Un jeton de classe est du bruit s'il vaut le mot, commence par « mot- / mot_ » ou finit par « -mot ».
    NOISE_WORDS = ("editsection", "bandeau", "banner", "ambox", "navbox", "noprint", "metadata", "reference",
                   "references", "reflist", "toc", "cookie", "breadcrumb", "sidebar", "infobox", "hatnote",
                   "catlinks", "printfooter", "homonymie")
    _WORDS = "|".join(NOISE_WORDS)
    NOISE = re.compile(rf"^(?:(?:{_WORDS})(?:[-_].*)?|.*-(?:{_WORDS}))$", re.I)
    BLOCK = {"p", "h1", "h2", "h3", "h4", "li", "dd", "dt", "blockquote", "pre", "div", "br"}
    VOID = {"br", "img", "meta", "link", "input", "hr", "wbr", "source", "area", "base", "col", "embed", "track"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._stack: list[str] = []
        self._skip_from: int | None = None  # profondeur où commence la zone ignorée
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
            return
        if tag in self.BLOCK:
            self.parts.append("\n\n")
        if tag in self.VOID:
            return
        self._stack.append(tag)
        if self._skip_from is None:
            tokens = " ".join(v or "" for k, v in attrs if k in ("class", "id", "role")).split()
            if tag in self.SKIP or any(self.NOISE.match(token) for token in tokens):
                self._skip_from = len(self._stack)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            return
        if tag in self.BLOCK:
            self.parts.append("\n\n")
        if tag in self.VOID or tag not in self._stack:
            return
        while self._stack and self._stack.pop() != tag:  # HTML mal fermé : on referme jusqu'à la balise
            pass
        if self._skip_from is not None and len(self._stack) < self._skip_from:
            self._skip_from = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._skip_from is None:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(titre, texte). Les espaces sont normalisés, les paragraphes séparés par une ligne vide."""
    parser = _TextExtractor()
    parser.feed(html)
    raw = "".join(parser.parts)
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", raw)]
    title = re.sub(r"\s+", " ", parser.title).strip()
    title = re.sub(r"\s[—–|-]\s[^—–|]{1,30}$", "", title)  # « Article — Wikipédia » → « Article »
    return title, "\n\n".join(p for p in paragraphs if len(p) > 1)


class PoliteFetcher:
    def __init__(self, cache_dir: Path, allowed_domains: list[str], journal: Path | None = None,
                 min_delay_s: float = 5.0, cache_ttl_s: float = 7 * 24 * 3600, timeout_s: float = 30.0,
                 opener: Opener = urllib_opener, now: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.cache_dir = cache_dir
        self.allowed = {d.lower().strip() for d in allowed_domains if d.strip()}
        self.journal = journal
        self.min_delay_s, self.cache_ttl_s, self.timeout_s = min_delay_s, cache_ttl_s, timeout_s
        self._open, self._now, self._sleep = opener, now, sleep
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    # -- règles
    def check_url(self, url: str) -> str:
        """Retourne l'hôte si l'URL est autorisée, sinon lève `FetchRefused`."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https":
            raise FetchRefused(f"https uniquement : {url}")
        if not any(host == d or host.endswith("." + d) for d in self.allowed):
            raise FetchRefused(f"domaine hors liste blanche : {host or '?'}")
        return host

    def _wait_turn(self, host: str) -> None:
        with self._lock:
            last = self._last_request.get(host)
            if last is not None:
                delay = self.min_delay_s - (self._now() - last)
                if delay > 0:
                    self._sleep(delay)
            self._last_request[host] = self._now()

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT, "Accept": "text/html, text/plain;q=0.8"}

    def robots_allows(self, url: str) -> bool:
        host = self.check_url(url)
        if host not in self._robots:
            parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            self._wait_turn(host)
            try:
                status, _, body = self._open(f"https://{host}/robots.txt", self._headers(), self.timeout_s)
            except Exception:  # noqa: BLE001 — injoignable : prudence, on s'abstient
                status, body = 0, b""
            if status == 200:
                parser.parse(body.decode("utf-8", "replace").splitlines())
            elif 400 <= status < 500:
                parser.parse([])  # pas de robots.txt : tout est permis (usage établi)
            else:
                parser = None  # 5xx ou réseau : on ne sait pas, donc non
            self._robots[host] = parser
        robots = self._robots[host]
        return bool(robots and robots.can_fetch(USER_AGENT, url))

    # -- cache et journal
    def _cache_file(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + ".json")

    def _log(self, url: str, outcome: str, **extra: Any) -> None:
        if self.journal is None:
            return
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        entry = {"t": round(self._now(), 1), "url": url, "outcome": outcome, **extra}
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # -- récupération
    def fetch(self, url: str, force: bool = False) -> Page:
        try:
            self.check_url(url)
        except FetchRefused as exc:
            self._log(url, "refusé", reason=str(exc))
            raise
        cached = self._cache_file(url)
        if not force and cached.is_file():
            data = json.loads(cached.read_text(encoding="utf-8"))
            if self._now() - data["fetched_at"] < self.cache_ttl_s:
                self._log(url, "cache")
                return Page(**data, from_cache=True)
        if not self.robots_allows(url):
            self._log(url, "refusé", reason="robots.txt")
            raise FetchRefused(f"robots.txt interdit ou illisible pour {url}")
        host = self.check_url(url)
        self._wait_turn(host)
        status, headers, body = self._open(url, self._headers(), self.timeout_s)
        content_type = headers.get("content-type", "").split(";")[0].strip().lower()
        if status != 200:
            self._log(url, "erreur", status=status)
            raise FetchRefused(f"statut HTTP {status} pour {url}")
        if content_type not in TEXT_TYPES:
            self._log(url, "refusé", reason=f"type {content_type or '?'}")
            raise FetchRefused(f"type de contenu non textuel : {content_type or '?'}")
        if len(body) > MAX_BYTES:
            self._log(url, "refusé", reason="trop gros")
            raise FetchRefused(f"page de plus de {MAX_BYTES // 1024 // 1024} Mio")
        charset = re.search(r"charset=([\w-]+)", headers.get("content-type", ""))
        decoded = body.decode(charset.group(1) if charset else "utf-8", "replace")
        title, text = html_to_text(decoded) if content_type != "text/plain" else ("", decoded.strip())
        page = Page(url, status, title, text, self._now())
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps({k: v for k, v in page.__dict__.items() if k != "from_cache"},
                                     ensure_ascii=False), encoding="utf-8")
        self._log(url, "récupéré", status=status, bytes=len(body), chars=len(text))
        return page
