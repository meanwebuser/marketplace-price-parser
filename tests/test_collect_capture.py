"""Source-contract tests: click.py must capture enough raw data for an
offline manual audit of the analyzer (page text + skipped variant
controls). These run against the collector source because the collector
itself is a Node subprocess driven by live marketplaces."""

import subprocess
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


def test_embedded_page_program_recognizes_visible_selected_state():
    """Parse both JS layers and exercise the generic visible-state signal."""
    click_path = Path(__file__).resolve().parents[1] / "click.py"
    script = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('const PAGE_FN = `');
const end = src.indexOf('\n`;\n', start);
if (start < 0 || end < 0) throw new Error('PAGE_FN boundary not found');
const declaration = src.slice(start, end + 3);
const sandbox = {};
vm.runInNewContext(declaration + '\nthis.PAGE_FN_OUT = PAGE_FN;', sandbox);
const result = new Function(sandbox.PAGE_FN_OUT + `
  const fake = {
    matches: () => false,
    querySelector: () => null,
    getAttribute: () => null,
    className: ''
  };
  return isSelectedElement(fake, 'Opaque option\\nВыбран');
`)();
if (result !== true) throw new Error('visible selected state was not recognized');
"""
    subprocess.run(["node", "-e", script, str(click_path)], check=True)


def test_collector_defers_default_variant_and_requires_a_price_snapshot():
    assert "Number(a.selected) - Number(b.selected)" in CLICK
    assert "settled.prices.length > 0" in CLICK
