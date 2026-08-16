"""Source-contract tests: click.py must capture enough raw data for an
offline manual audit of the analyzer (page text + skipped variant
controls). These run against the collector source because the collector
itself is a Node subprocess driven by live marketplaces."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLICK = (Path(__file__).resolve().parents[1] / "click.py").read_text(encoding="utf-8")


def test_collector_saves_page_text_excerpt():
    # body innerText excerpt per listing — the only offline evidence for
    # delivery-type checks (chip text alone is often silent)
    assert "pageText" in CLICK


def test_collector_saves_description_text():
    # seller description (collapsed behind expanders) — textContent of
    # description containers, the main manual-audit evidence
    assert "descText" in CLICK
    assert "grabDescText" in CLICK


def test_collector_saves_skipped_controls():
    # controls rejected by the keyword filter must still be recorded,
    # otherwise silently missed variants (GO / Plus / token chips) are
    # invisible to any audit
    assert "skippedControls" in CLICK
