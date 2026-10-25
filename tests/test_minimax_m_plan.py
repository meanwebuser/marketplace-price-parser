"""MiniMax renamed plans must survive discovery, analysis and site export."""

import csv
import json
import subprocess
from pathlib import Path

import pytest

from analyzer.price import classify_tier
from cli import _analyze, _parse_args
from families.minimax import CONFIG as MINIMAX
from scanner.discover import _candidate_matches_family, _extract_ggsel_products
from scripts.build_pages_data import normalize_csv


FIXTURE = Path(__file__).parent / "fixtures" / "minimax_plan_aliases.json"


@pytest.mark.parametrize("text,tier", [
    ("GO (Subscription Renewal)", "GO"),
    ("Explore 1 Month", "Explore"),
    ("Build - 1 год", "Build"),
])
def test_new_minimax_selected_tiers_are_classified(text, tier):
    assert classify_tier(text) == tier


def test_go_navigation_is_not_a_subscription_tier():
    assert classify_tier("Go to order") == ""


def test_collector_enumerates_plain_new_minimax_tier_buttons():
    click_path = Path(__file__).resolve().parents[1] / "click.py"
    script = r'''
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('const PAGE_FN = `'), end = src.indexOf('\n`;\n', start);
const sandbox = {};
vm.runInNewContext(src.slice(start, end + 3) + '\nthis.source = PAGE_FN;', sandbox);
const texts = ['GO', 'Explore', 'Build', 'Ultra'];
const buttons = texts.map(innerText => ({innerText, className:'', getAttribute:()=>null, querySelector:()=>null, matches:()=>false}));
const document = {querySelectorAll: selector => selector === 'button' ? buttons : []};
const result = new Function('document', sandbox.source + '\nreturn collectVariantControls();')(document);
if (JSON.stringify(result.controls.map(x=>x.text)) !== JSON.stringify(texts)) throw new Error(JSON.stringify(result));
'''
    subprocess.run(["node", "-e", script, str(click_path)], check=True)


@pytest.mark.parametrize("tier,canonical", [("go", "GO"), ("explore", "Explore"), ("build", "Build")])
def test_llm_path_normalizes_new_minimax_tier_names(tier, canonical):
    from analyzer.llm_extract import _row_to_offer
    pack = {"mp": "ggsel", "pid": "fixture", "url": "fixture", "title": "MiniMax M Plan", "opts": [{"t": f"{tier} 1 month", "c": 1, "strong": 5000, "p": []}], "init_strong": [], "init": []}
    row = _row_to_offer(pack, {"opt": f"{tier} 1 month", "tier": tier, "duration": "1m", "delivery": "own_account", "price_rub": 5000}, None)
    assert row["tier"] == canonical


def test_saved_ggsel_new_tiers_survive_analysis_alongside_token_plan():
    raw = json.loads(FIXTURE.read_text())
    offers, _ = _analyze(raw, MINIMAX, _parse_args(["--family", "minimax", "--analyzer", "regex"]))

    assert {(o["pid"], o["tier"], o["duration"], o["price_rub"]) for o in offers} == {
        ("4696379", "Max", "1m", 5193),
        ("102369748", "Explore", "1m", 4800),
        ("102369748", "GO", "1m", 1800),
        ("102358305", "Build", "12m", 168637),
    }


@pytest.mark.parametrize("tier", ["GO", "Explore", "Build"])
def test_family_accepts_new_m_plan_tiers(tier):
    assert MINIMAX.matches_offer({
        "title": "MiniMax API Platform-M Plan | GO/EXPLORE/BUILD | 1 Month",
        "option_text": f"{tier} (Subscription Renewal)", "tier": tier,
        "duration": "1m", "delivery": "own_account", "price_rub": 5000,
    })


def test_minimax_m_plan_listing_with_topups_keeps_only_subscription_variant():
    title = "MiniMax API Platform-M Plan | GO/EXPLORE/BUILD | Credits | 1 Month"
    good = {"title": title, "option_text": "Explore (Subscription Renewal)"}
    assert MINIMAX.eligibility_extra(good)
    for selected in ("Top-Up 5,000 Credits", "Top Up Balance: 25$", "API key 1 month"):
        assert not MINIMAX.eligibility_extra({**good, "option_text": selected})
    assert not MINIMAX.eligibility_extra({**good, "option_text": "FLAT"})
    assert not MINIMAX.eligibility_extra({"title": "MiniMax API Platform", "option_text": "Max 1 month"})


def test_m_plan_and_legacy_token_plan_discovery_keep_numeric_and_slug_cards():
    html = '''
    <a href="/catalog/product/102438200" title="MiniMax API Platform-M Plan GO/EXPLORE/BUILD 1 Month"></a>
    <a href="/catalog/product/102000003"></a>
    <a href="/catalog/product/minimax-token-plan-m3-max-1-month-102927393"></a>
    <a href="/catalog/product/minimax-audio-starter-1-month-102000001"></a>
    <a href="/catalog/product/unrelated-m-plan-1-month-102000002"></a>
    '''

    assert [o["native_id"] for o in _extract_ggsel_products(html, MINIMAX)] == ["102438200", "102927393"]
    assert _candidate_matches_family("MiniMax M3.1 M Plan Explore subscription 1 month", MINIMAX)


def test_site_export_keeps_new_tiers_from_mixed_api_platform_listing(tmp_path):
    path = tmp_path / "2026-10-23-minimax.csv"
    fields = ["pid", "title", "option_text", "tier", "duration", "delivery", "price_rub"]
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for pid, tier in (("go", "GO"), ("explore", "Explore"), ("build", "Build")):
            writer.writerow(dict(pid=pid, title="MiniMax API Platform-M Plan | GO/EXPLORE/BUILD | Credits | 1 Month", option_text=f"{tier} Subscription Renewal", tier=tier, duration="1m", delivery="own_account", price_rub="5000"))
        writer.writerow(dict(pid="topup", title="MiniMax M Plan", option_text="Top-Up 5000 Credits", tier="GO", duration="1m", delivery="own_account", price_rub="100"))

    offers, _ = normalize_csv(path, "minimax", docs_root=tmp_path)

    assert [o["pid"] for o in offers] == ["go", "explore", "build"]
