"""Source-contract tests: click.py must capture enough raw data for an
offline manual audit of the analyzer (page text + skipped variant
controls). These run against the collector source because the collector
itself is a Node subprocess driven by live marketplaces."""

import json
import subprocess
import sys
from pathlib import Path
import pytest

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
const unavailable = new Function(sandbox.PAGE_FN_OUT + `
  return isUnavailableText('Вариант нет в наличии');
`)();
if (unavailable !== true) throw new Error('unavailable text was not recognized');
"""
    subprocess.run(["node", "-e", script, str(click_path)], check=True)


def test_collector_defers_default_variant_and_requires_a_price_snapshot():
    assert "Number(a.selected) - Number(b.selected)" in CLICK
    assert "settled.prices.length > 0" in CLICK


def test_collector_retries_integrity_failures_and_ignores_sidebar_price_noise():
    assert "CAPTURE_RETRIES" in CLICK
    assert "MAX_CAPTURE_RETRIES = 4" in CLICK
    assert "missing price snapshot" in CLICK
    assert "unstable changed price" in CLICK
    assert "primary.length > 0 ? primary : all" in CLICK


def test_capture_retry_parser_keeps_default_accepts_limit_and_rejects_invalid_values():
    click_path = Path(__file__).resolve().parents[1] / "click.py"
    script = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('const MAX_CAPTURE_RETRIES = 4;');
const end = src.indexOf('\nlet CAPTURE_RETRIES;', start);
if (start < 0 || end < 0) throw new Error('capture retry parser boundary not found');
const sandbox = {};
vm.runInNewContext(src.slice(start, end) + '\nthis.parse = parseCaptureRetries;', sandbox);
const failures = [5, -1, 1.5, 'invalid', true].map(value => {
  try { sandbox.parse(value); return null; } catch (error) { return error.message; }
});
console.log(JSON.stringify({defaultValue: sandbox.parse(undefined), maximumValue: sandbox.parse(4), failures}));
"""
    result = subprocess.run(["node", "-e", script, str(click_path)], check=True, capture_output=True, text=True)
    parsed = json.loads(result.stdout)
    assert parsed["defaultValue"] == 2
    assert parsed["maximumValue"] == 4
    assert len(parsed["failures"]) == 5
    assert all("--capture-retries must be an integer from 0 to 4" in message for message in parsed["failures"])


def test_direct_collector_cli_rejects_retry_count_above_hard_limit(tmp_path):
    click_path = Path(__file__).resolve().parents[1] / "click.py"
    output = tmp_path / "must-not-be-created.json"
    result = subprocess.run(
        ["node", str(click_path), "--capture-retries", "5", "--out", str(output)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 2
    assert "error: --capture-retries must be an integer from 0 to 4 (default 2)" in result.stderr
    assert not output.exists()


def test_collector_keeps_a_stable_locator_when_control_text_mutates():
    assert "domIndex" in CLICK
    assert "findElementByIndex(ctrl.kind, ctrl.domIndex)" in CLICK


def test_ggsel_guest_mode_uses_a_visible_browser_and_captures_new_account():
    assert "GGSEL_IDS.length === 0" in CLICK
    assert "предоставлю" in CLICK
    assert "нов(?:ый|ая)" in CLICK
    assert "getByRole('button', { name: ctrl.text, exact: true })" in CLICK


def test_collector_requires_selected_state_for_a_new_variant_price():
    assert "await target.click({ timeout: CLICK_TIMEOUT_MS })" in CLICK
    assert "settled.stable && selectedAfter" in CLICK


def test_collector_supports_real_chrome_cdp_without_a_stale_user_agent():
    assert "connectOverCDP(CDP_URL)" in CLICK
    assert "MARKETPLACE_CDP_URL" in CLICK
    assert "Chrome/120" not in CLICK


def test_collector_ignores_noninteractive_labels():
    assert "if (associated || explicitlyInteractive)" in CLICK


def test_initially_selected_control_must_still_be_selected_after_click():
    # Evaluate the actual collector predicate; no browser/network needed.
    import re
    predicate = re.search(r"priceVerified: (.*?),\n        priceSettleMs", CLICK, re.S).group(1)
    script = "const verify=(ctrl,settled,selectedAfter)=>(" + predicate + ");" + """
const settled={prices:[{}],stable:true,changed:false};
if (verify({selected:true},settled,false)) throw new Error('stale default price was verified');
if (!verify({selected:true},settled,true)) throw new Error('selected default price rejected');
if (!verify({selected:false},{...settled,changed:true},true)) throw new Error('new selected price rejected');
if (verify({selected:false},{...settled,changed:true},false)) throw new Error('unselected price verified');
"""
    subprocess.run(["node", "-e", script], check=True)
