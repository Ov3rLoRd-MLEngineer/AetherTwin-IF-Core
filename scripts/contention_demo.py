"""Scénario de contention : ce qu'Inoue apporte de plus qu'Ollama seul, mesuré sur les vraies cartes.

Un autre programme (PyTorch, comme ComfyUI) occupe de la VRAM sur une carte. On demande ensuite deux gros modèles :
  1. **sans le Hub** : Ollama seul, les deux demandes en même temps ;
  2. **avec le Hub** : routeur + Inoue, qui mesure les cartes et met en file au lieu de planter ;
  3. l'occupant libère sa place : la demande en file est servie.

    .venv\\Scripts\\python.exe scripts\\contention_demo.py
    .venv\\Scripts\\python.exe scripts\\contention_demo.py --occupant-gb 12 --card 1 --json logs\\contention.json

Prérequis : Ollama lancé, deux gros modèles installés, PyTorch avec CUDA (`requirements-gpu.txt`). Le script ne
touche pas au Hub en marche : il crée son propre routeur et sa propre Inoue. Tous les modèles sont déchargés à la fin.
Résultats de référence (26/11/2026) : `docs/HARDWARE_FIT.md`, section « Contention mesurée ».
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.guardians.inoue import Inoue  # noqa: E402
from core.hardware.gpu_monitor import GpuMonitor  # noqa: E402
from core.llm_router import LlmConfig, LlmError, LlmRefused, LlmRouter  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"
PROMPT = "Explique en cinq phrases ce qu'est la mémoire vidéo d'une carte graphique."


def ollama(path: str, body: dict[str, Any] | None = None, timeout: float = 600) -> dict[str, Any]:
    request = urllib.request.Request(OLLAMA + path, data=json.dumps(body).encode() if body is not None else None,  # noqa: S310
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — boucle locale seulement
        return json.loads(response.read())


def vram_mib(monitor: GpuMonitor) -> dict[int, int]:
    return {g.index: g.vram_used_mib for g in monitor.snapshot()}


def unload_all() -> None:
    for model in ollama("/api/ps").get("models", []):
        ollama("/api/generate", {"model": model["name"], "keep_alive": 0})
    deadline = time.monotonic() + 30
    while ollama("/api/ps").get("models") and time.monotonic() < deadline:
        time.sleep(0.5)


def generate(model: str, num_ctx: int) -> dict[str, Any]:
    """Une génération directe sur Ollama, sans le Hub. Une erreur HTTP est un résultat, pas une exception."""
    started = time.monotonic()
    body = {"model": model, "prompt": PROMPT, "stream": False, "think": False,
            "options": {"num_ctx": num_ctx, "num_predict": 120}}
    try:
        reply = ollama("/api/generate", body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        return {"model": model, "error": exc.code, "out_of_memory": "out of memory" in detail.lower(),
                "seconds": round(time.monotonic() - started, 1)}
    return {"model": model, "seconds": round(time.monotonic() - started, 1),
            "tokens_per_s": round(reply["eval_count"] / (reply["eval_duration"] / 1e9), 1)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--occupant-gb", type=float, default=12.0, help="VRAM tenue par l'autre programme (Gio)")
    parser.add_argument("--card", type=int, default=1, help="carte occupée par l'autre programme")
    parser.add_argument("--models", nargs=2, default=["qwen3-27b:latest", "qwen3-coder:30b-a3b-q4_K_M"])
    parser.add_argument("--num-ctx", type=int, default=32768)
    parser.add_argument("--json", type=Path, help="écrit aussi les résultats dans ce fichier")
    args = parser.parse_args(argv)

    import torch  # importé ici : `--help` marche sans PyTorch

    monitor = GpuMonitor()
    report: dict[str, Any] = {"date": time.strftime("%Y-%m-%d %H:%M"), "occupant_gb": args.occupant_gb,
                              "card": args.card, "models": args.models, "num_ctx": args.num_ctx}
    unload_all()
    occupant = torch.empty(int(args.occupant_gb * 2**30), dtype=torch.uint8, device=f"cuda:{args.card}")
    torch.cuda.synchronize(args.card)
    report["vram_with_occupant_mib"] = vram_mib(monitor)
    print(f"Occupant : {args.occupant_gb:g} Gio sur la carte {args.card} — VRAM {report['vram_with_occupant_mib']}")

    print("1. Sans le Hub : Ollama seul, deux gros modèles en même temps…")
    results: list[dict[str, Any]] = []
    threads = [threading.Thread(target=lambda m=m: results.append(generate(m, args.num_ctx))) for m in args.models]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    report["without_hub"] = results
    for result in results:
        print("   ", json.dumps(result, ensure_ascii=False))
    unload_all()

    print("2. Avec le Hub : routeur + Inoue…")
    inoue = Inoue(monitor)
    router = LlmRouter(inoue=inoue, config=LlmConfig(num_ctx=args.num_ctx))
    messages = [{"role": "user", "content": PROMPT}]
    started = time.monotonic()
    try:
        router.chat(messages, model=args.models[0], think=False, options={"num_predict": 120})
        report["with_hub"] = {"verdict": "accordé", "seconds": round(time.monotonic() - started, 2)}
    except LlmRefused as exc:
        report["with_hub"] = {"verdict": "en file", "seconds": round(time.monotonic() - started, 2),
                              "reason": str(exc)}
    report["with_hub"]["inoue"] = {k: inoue.state()[k] for k in ("budget_gb", "measured_used_gb", "available_gb")}
    print("   ", json.dumps(report["with_hub"], ensure_ascii=False))

    print("3. L'occupant libère sa place : la demande est servie…")
    del occupant
    torch.cuda.empty_cache()
    time.sleep(2)
    started = time.monotonic()
    try:
        router.chat(messages, model=args.models[0], think=False, options={"num_predict": 120})
        report["after_release"] = {"verdict": "accordé", "seconds": round(time.monotonic() - started, 1)}
    except (LlmRefused, LlmError) as exc:
        report["after_release"] = {"verdict": "échec", "reason": str(exc)}
    print("   ", json.dumps(report["after_release"], ensure_ascii=False))
    unload_all()

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Résultats écrits dans {args.json}")
    hub_ok = report["with_hub"]["verdict"] == "en file" and report["after_release"]["verdict"] == "accordé"
    return 0 if hub_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
