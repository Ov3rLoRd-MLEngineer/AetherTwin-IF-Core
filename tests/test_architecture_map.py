"""La carte d'architecture générée ne doit jamais être périmée."""
from __future__ import annotations

from scripts import gen_architecture_map as gen


def test_architecture_map_is_up_to_date() -> None:
    assert gen.main(["--check"]) == 0, "Lance : .venv\\Scripts\\python.exe scripts\\gen_architecture_map.py"


def test_signatures_are_extracted() -> None:
    text = gen.generate()
    assert "scripts/relay_orchestrator.py" in text
    assert "class RelayOrchestrator" in text
    assert "def run(self) -> int" in text


def test_render_keeps_manual_sections() -> None:
    manual = f"# Titre\n\nflux manuel\n\n{gen.BEGIN}\nvieux\n{gen.END}\n\n## Suite manuelle\n"
    out = gen.render(manual)
    assert out.startswith("# Titre\n\nflux manuel\n\n") and out.endswith("\n\n## Suite manuelle\n")
    assert "vieux" not in out
