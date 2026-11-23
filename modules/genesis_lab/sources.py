"""Branchements du Professeur sur les outils déjà en place.

- `wikipedia(...)` : lit un article de Wikipédia en français avec le `PoliteFetcher` du Hub (liste blanche
  `config/allowlist.yaml`, robots.txt respecté, délai entre deux requêtes, cache local, journal). Seules les
  pages `/wiki/<Titre>` sont lues : c'est ce que robots.txt autorise.
- `hermes_verifier(...)` : pose une question à Hermes Agent en ligne de commande (`hermes -z`), avec les seuls
  outils sûrs (recherche web, mémoire…) et sans la compétence de coaching WoW. Rien n'est modifié côté Hermes.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Réponses de Hermes qui signalent un échec (celles du pont de WoW Assistant, et l'erreur de fournisseur vue en réel).
FAILED = ("couldn't finish this reply", "Your request was not processed", "Something went wrong",
          "returned a server error", "Provider said:")


def wikipedia(cache_dir: Path, journal: Path | None = None, fetcher: Any = None,
              lang: str = "fr") -> Callable[[str], dict[str, str] | None]:
    """Fabrique la lecture d'un article (titre -> {"title", "url", "text"} ou None)."""
    if fetcher is None:
        from core.knowledge.fetcher import PoliteFetcher
        from core.knowledge.service import allowed_domains
        fetcher = PoliteFetcher(Path(cache_dir), allowed_domains(), journal=journal, min_delay_s=2.0)

    def read(title: str) -> dict[str, str] | None:
        title = " ".join(str(title).split())[:120]
        if not title or any(ch in title for ch in "#<>[]{}|"):
            return None
        url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'), safe='_()-,')}"
        try:
            page = fetcher.fetch(url)
        except Exception:  # noqa: BLE001 — article absent, robots, réseau : pas de source, sans plus
            return None
        text = page.text or ""
        if len(text) < 300:
            return None
        return {"title": (page.title or title).replace(" — Wikipédia", "").strip(), "url": url, "text": text}

    return read


def hermes_exe() -> str:
    """Chemin de Hermes Agent s'il est installé (lu par le pont de WoW Assistant), sinon ''."""
    try:
        from modules.gaming_hud import ensure_app_path
        ensure_app_path()
        import hermes_bridge  # type: ignore[import-not-found]  # import « à plat » de l'application
        return str(hermes_bridge.HermesInfo().refresh(force=True).get("exe") or "")
    except Exception:  # noqa: BLE001 — Hermes absent : la vérification est simplement indisponible
        return ""


def hermes_verifier(exe: str = "", runner: Callable[..., Any] = subprocess.run,
                    timeout_s: float = 600.0, reasoning: str = "medium") -> Callable[[str], str] | None:
    """Question -> réponse de Hermes (CLI, outils sûrs uniquement). None si Hermes est introuvable."""
    exe = exe or hermes_exe()
    if not exe:
        return None
    try:
        from modules.gaming_hud import ensure_app_path
        ensure_app_path()
        from hermes_bridge import SAFE_TOOLSETS  # type: ignore[import-not-found]
        toolsets = ",".join(SAFE_TOOLSETS)
    except Exception:  # noqa: BLE001
        toolsets = "web,memory,session_search,todo"

    def ask(prompt: str) -> str:
        # Niveau de réflexion explicite : « high » (réglage par défaut de Hermes) est refusé par Qwen (essai réel).
        result = runner([exe, "-z", prompt, "-t", toolsets, "--reasoning", reasoning], stdin=subprocess.DEVNULL,
                        capture_output=True, cwd=tempfile.gettempdir(), timeout=timeout_s, creationflags=NO_WINDOW)
        text = (result.stdout or b"").decode("utf-8", "replace").strip()
        if any(marker in text for marker in FAILED) and not re.search(r"verdict\s*:", text, re.I):
            # Essai réel du 23/11 : erreur du fournisseur de Hermes rendue comme une réponse ordinaire.
            first = text.splitlines()[0][:200] if text else ""
            raise RuntimeError(f"Hermes n'a pas pu répondre ({first}). Détails : commande « hermes logs ».")
        if not text:
            detail = (result.stderr or b"").decode("utf-8", "replace").strip()[-300:]
            raise RuntimeError("Hermes n'a pas répondu" + (f" : {detail}" if detail else ""))
        return text

    return ask
