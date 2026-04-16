from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
ROADMAP = ROOT / "docs" / "ROADMAP.md"


def test_roadmap_exists_and_readme_links_to_it() -> None:
    assert ROADMAP.exists(), "docs/ROADMAP.md should exist"
    readme_text = README.read_text(encoding="utf-8")
    assert "docs/ROADMAP.md" in readme_text, "README.md should link to docs/ROADMAP.md"


def test_roadmap_tracks_external_source_and_status_labels() -> None:
    roadmap_text = ROADMAP.read_text(encoding="utf-8").lower()

    assert "/users/asd/desktop/empire_deck_external.html" in roadmap_text

    for status in ("implemented", "partial", "planned", "not started"):
        assert status in roadmap_text, f"ROADMAP.md should contain the status label: {status}"
