import subprocess
import json

from cli import _parse_args, _merge_scan_context
from cli import _apply_verification_results
from analyzer.output import write_markdown
from families import FAMILY_REGISTRY
from scanner.collect import collect


def test_cli_parses_headless_mode():
    assert _parse_args(["--family", "minimax", "--headless"]).headless is True


def test_collector_forwards_headless_flag(tmp_path, monkeypatch):
    out_path = tmp_path / "raw.json"
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        out_path.write_text('{"listings": []}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("scanner.collect.subprocess.run", run)
    collect([], out_path, workers=2, headless=True)

    assert "--headless" in commands[0]
    assert commands[0][commands[0].index("--workers") + 1] == "2"


def test_reanalysis_restores_only_matching_verified_rows():
    offer = {
        "marketplace": "plati", "pid": "1", "raw_option_text": "Max 1 month",
        "tier": "Max", "duration": "1m", "delivery": "own_account",
        "final_verified": False,
    }
    other = {**offer, "pid": "2"}

    _apply_verification_results([offer, other], [{
        "marketplace": "plati", "pid": "1", "optionText": "Max 1 month",
        "tier": "Max", "duration": "1m", "delivery": "own_account",
        "verified": True, "observedPrice": 5300,
    }])

    assert offer["final_verified"] is True
    assert offer["final_observed_price"] == 5300
    assert other["final_verified"] is False


def test_markdown_records_collection_mode_and_raw_hash(tmp_path):
    raw_path = tmp_path / "scan.raw.json"
    raw_path.write_text(json.dumps({
        "scanContext": {"headless": True, "workers": 2, "listingCounts": {"plati": 3, "ggsel": 1}},
        "finalVerification": {"skipped": True, "results": []},
    }), encoding="utf-8")
    markdown_path = tmp_path / "scan.md"

    write_markdown([], {}, FAMILY_REGISTRY["minimax"], markdown_path, source_path=raw_path)

    report = markdown_path.read_text(encoding="utf-8")
    assert "Raw SHA-256:" in report
    assert "Collection: headless, 2 workers; Plati 3, GGSEL 1 listings." in report
    assert "Final browser verification: skipped." in report


def test_analysis_only_rerun_preserves_original_headless_collection_context():
    raw = {"scanContext": {
        "collectionCommand": "PYTHONPATH=. node click.py --headless",
        "headless": True,
        "workers": 2,
        "listingCounts": {"plati": 3, "ggsel": 1},
    }}

    context = _merge_scan_context(
        raw,
        {"collectionCommand": "PYTHONPATH=. node click.py", "headless": False, "workers": 6},
        {"command": "PYTHONPATH=. python cli.py --skip-discover", "workers": 6},
        preserve_collection=True,
    )

    assert context["headless"] is True
    assert context["collectionCommand"].endswith("--headless")
    assert context["workers"] == 2
    assert context["listingCounts"] == {"plati": 3, "ggsel": 1}
    assert context["analysis"]["workers"] == 6


def test_legacy_analysis_only_rerun_does_not_invent_collection_mode():
    context = _merge_scan_context(
        {"listings": []},
        {"collectionCommand": "PYTHONPATH=. node click.py", "headless": False, "workers": 6},
        {"command": "PYTHONPATH=. python cli.py --skip-discover", "workers": 6},
        preserve_collection=True,
    )

    assert context["headless"] is None
    assert context["collectionCommand"] is None
    assert "unknown" in context["collectionContextSource"]


def test_plati_only_scan_records_effective_headless_mode():
    context = _merge_scan_context(
        {},
        {"collectionCommand": "PYTHONPATH=. node click.py", "headless": True,
             "collectionContextSource": "effective collector mode"},
        {"command": "PYTHONPATH=. python cli.py", "workers": 6},
        preserve_collection=False,
    )

    assert context["headless"] is True


def test_markdown_reports_unknown_legacy_collection_mode(tmp_path):
    raw_path = tmp_path / "legacy.raw.json"
    raw_path.write_text(json.dumps({
        "scanContext": {"headless": None, "workers": 2, "listingCounts": {"plati": 1, "ggsel": 0}},
        "finalVerification": {"skipped": True, "results": []},
    }), encoding="utf-8")
    markdown_path = tmp_path / "legacy.md"

    write_markdown([], {}, FAMILY_REGISTRY["minimax"], markdown_path, source_path=raw_path)

    assert "Collection: unknown, 2 workers" in markdown_path.read_text(encoding="utf-8")
