import subprocess
import json

from cli import _parse_args, _merge_scan_context
from cli import _apply_verification_results
from analyzer.output import write_markdown
from families import FAMILY_REGISTRY
from scanner.collect import collect


def test_cli_parses_headless_mode():
    assert _parse_args(["--family", "minimax", "--headless"]).headless is True
    args = _parse_args(["--family", "minimax", "--http-workers", "10", "--workers", "2"])
    assert args.http_workers == 10
    assert args.workers == 2


def test_empty_collection_skips_browser_launch(tmp_path, monkeypatch):
    out_path = tmp_path / "raw.json"
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        out_path.write_text('{"listings": []}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("scanner.collect.subprocess.run", run)
    raw = collect([], out_path, workers=2, headless=True, http_workers=10)

    assert not commands
    assert raw["listings"] == []
    assert raw["config"]["httpWorkers"] == 10
    assert raw["config"]["headless"] is True


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


def test_markdown_reports_http_and_browser_worker_pools_separately(tmp_path):
    raw_path = tmp_path / "hybrid.raw.json"
    raw_path.write_text(json.dumps({
        "scanContext": {"headless": True, "workers": 2, "httpWorkers": 10,
                         "listingCounts": {"plati": 8, "ggsel": 10}},
        "finalVerification": {"skipped": True, "results": []},
    }), encoding="utf-8")
    markdown_path = tmp_path / "hybrid.md"

    write_markdown([], {}, FAMILY_REGISTRY["minimax"], markdown_path, source_path=raw_path)

    assert "Collection: headless, 10 HTTP workers + 2 browser workers; Plati 8, GGSEL 10 listings." in markdown_path.read_text(encoding="utf-8")


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
