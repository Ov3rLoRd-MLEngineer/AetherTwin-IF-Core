"""Collecte polie : liste blanche, robots.txt, délai par hôte, cache, journal, types et tailles. Sans réseau."""
from __future__ import annotations

import json

import pytest

from core.knowledge.fetcher import MAX_BYTES, USER_AGENT, FetchRefused, PoliteFetcher, html_to_text

PAGE = b"""<html><head><title>Vitesse de lib\xc3\xa9ration</title><script>alert(1)</script></head>
<body><nav>Menu Accueil</nav><h1>Vitesse de lib\xc3\xa9ration</h1>
<p>La vitesse de lib\xc3\xa9ration de la Terre vaut <b>11,2</b> km/s.</p><table><tr><td>Infobox</td></tr></table>
<p>Elle d\xc3\xa9pend de la masse et du rayon.<sup>[1]</sup></p><footer>Mentions</footer></body></html>"""
ROBOTS = b"User-agent: *\nDisallow: /w/\nDisallow: /prive\n"


class FakeWeb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.pages = {
            "https://fr.wikipedia.org/robots.txt": (200, "text/plain", ROBOTS),
            "https://fr.wikipedia.org/wiki/Vitesse": (200, "text/html; charset=utf-8", PAGE),
            "https://fr.wikipedia.org/image.png": (200, "image/png", b"\x89PNG"),
            "https://fr.wikipedia.org/wiki/Enorme": (200, "text/html", b"x" * (MAX_BYTES + 1)),
            "https://sans-robots.org/robots.txt": (404, "text/html", b""),
            "https://sans-robots.org/page": (200, "text/plain", b"Texte brut."),
            "https://en-panne.org/robots.txt": (503, "text/html", b""),
        }

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers))
        status, ctype, body = self.pages.get(url, (404, "text/html", b""))
        return status, {"content-type": ctype}, body


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 2))
        self.t += seconds


@pytest.fixture
def setup(tmp_path):
    web, clock = FakeWeb(), Clock()
    fetcher = PoliteFetcher(tmp_path / "cache", ["wikipedia.org", "sans-robots.org", "en-panne.org"],
                            journal=tmp_path / "journal.jsonl", min_delay_s=5, opener=web, now=clock.now,
                            sleep=clock.sleep)
    return fetcher, web, clock, tmp_path / "journal.jsonl"


def test_html_to_text_drops_site_banners_and_edit_links() -> None:
    html = ("<title>Parsec — Wikipédia</title><body class='skin vector-toc-available'><div class='infobox_v3'>"
            "Boîte</div><div class='bandeau-container'><div>Cet article manque de "
            "sources.</div></div><h2>Définition<span class='mw-editsection'>[modifier | modifier le code]</span>"
            "</h2><p>Un parsec vaut 3,26 années-lumière.<br>Suite.</p><div class='navbox'><ul><li>Voir aussi</li>"
            "</ul></div><p>Fin.</p>")
    title, text = html_to_text(html)
    assert title == "Parsec"
    assert text == "Définition\n\nUn parsec vaut 3,26 années-lumière.\n\nSuite.\n\nFin."


def test_html_to_text_keeps_content_drops_chrome() -> None:
    title, text = html_to_text(PAGE.decode("utf-8"))
    assert title == "Vitesse de libération"
    assert "11,2 km/s" in text and "masse et du rayon." in text
    for noise in ("alert", "Menu", "Infobox", "Mentions", "[1]"):
        assert noise not in text


def test_fetch_respects_robots_delay_and_user_agent(setup) -> None:
    fetcher, web, clock, journal = setup
    page = fetcher.fetch("https://fr.wikipedia.org/wiki/Vitesse")
    assert page.title == "Vitesse de libération" and not page.from_cache
    assert [u for u, _ in web.calls] == ["https://fr.wikipedia.org/robots.txt", "https://fr.wikipedia.org/wiki/Vitesse"]
    assert all(h["User-Agent"] == USER_AGENT for _, h in web.calls)
    assert clock.slept == [5.0]  # robots.txt puis la page : 5 s d'écart sur le même hôte
    with pytest.raises(FetchRefused, match="robots"):
        fetcher.fetch("https://fr.wikipedia.org/w/index.php?title=X")
    with pytest.raises(FetchRefused, match="robots"):
        fetcher.fetch("https://fr.wikipedia.org/prive/page")
    assert len(web.calls) == 2  # les refus robots ne déclenchent aucune requête
    outcomes = [json.loads(line)["outcome"] for line in journal.read_text(encoding="utf-8").splitlines()]
    assert outcomes == ["récupéré", "refusé", "refusé"]


def test_cache_avoids_refetch_until_expiry(setup) -> None:
    fetcher, web, clock, _ = setup
    fetcher.fetch("https://fr.wikipedia.org/wiki/Vitesse")
    assert fetcher.fetch("https://fr.wikipedia.org/wiki/Vitesse").from_cache is True
    assert len(web.calls) == 2
    clock.t += 8 * 24 * 3600
    assert fetcher.fetch("https://fr.wikipedia.org/wiki/Vitesse").from_cache is False
    assert len(web.calls) == 3


@pytest.mark.parametrize("url, reason", [
    ("http://fr.wikipedia.org/wiki/Vitesse", "https"),
    ("https://evil.example.com/page", "liste blanche"),
    ("https://wikipedia.org.evil.com/page", "liste blanche"),
    ("file:///C:/Windows/win.ini", "https"),
])
def test_only_https_allowed_domains(setup, url, reason) -> None:
    fetcher, web, _, _ = setup
    with pytest.raises(FetchRefused, match=reason):
        fetcher.fetch(url)
    assert web.calls == []


def test_types_sizes_and_unknown_robots(setup) -> None:
    fetcher, _, _, _ = setup
    with pytest.raises(FetchRefused, match="non textuel"):
        fetcher.fetch("https://fr.wikipedia.org/image.png")
    with pytest.raises(FetchRefused, match="Mio"):
        fetcher.fetch("https://fr.wikipedia.org/wiki/Enorme")
    assert fetcher.fetch("https://sans-robots.org/page").text == "Texte brut."  # robots absent (404) : permis
    with pytest.raises(FetchRefused, match="robots"):
        fetcher.fetch("https://en-panne.org/page")  # robots en erreur 5xx : on s'abstient
