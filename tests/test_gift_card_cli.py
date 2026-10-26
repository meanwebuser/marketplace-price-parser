"""The gift-card CLI keeps useful captures when final verification fails."""
import json
import csv

from cli import _parse_args, _run_gift_card_scan
from scanner.final_verify import FinalVerificationError


def _offer():
    return {
        "marketplace": "ggsel", "pid": "listing-1", "url": "https://ggsel.net/listing-1",
        "denomination": 50, "denomination_currency": "USD", "price_rub": 4200,
        "price_per_unit": 84, "price_verified": True, "available": None,
        "availability_status": "unknown", "option_text": "50 USD",
    }


def test_verification_failure_preserves_csv_markdown_and_raw(tmp_path, monkeypatch):
    import cli

    args = _parse_args([
        "--family", "apple_gift_card", "--region", "US", "--workers", "1",
        "--raw", str(tmp_path / "raw.json"), "--csv", str(tmp_path / "offers.csv"),
        "--md", str(tmp_path / "report.md"),
    ])
    monkeypatch.setattr(cli, "discover_gift_cards", lambda *a, **k: {
        "product": "apple_gift_card", "region": "US", "candidates": [{"native_id": "1"}],
        "plati_found": 1, "ggsel_found": 0, "status": "ok", "sources": {},
        "coverage": "bounded", "errors": [],
    })
    monkeypatch.setattr(cli, "collect", lambda *a, **k: {"listings": [{"pid": "listing-1"}]})
    monkeypatch.setattr(cli, "gift_card_offers_from_raw", lambda *a, **k: [_offer()])
    monkeypatch.setattr(cli, "verify_winners", lambda *a, **k: (_ for _ in ()).throw(
        FinalVerificationError("variant selection not independently confirmed", [], "selected state missing")
    ))

    assert _run_gift_card_scan(args) == 2
    raw = json.loads((tmp_path / "raw.json").read_text())
    assert raw["finalVerification"]["failed"] is True
    assert raw["finalVerification"]["results"] == []
    assert raw["finalVerification"]["excludedOffers"] == [{
        "marketplace": "ggsel", "pid": "listing-1", "optionText": "50 USD",
    }]
    assert "variant selection not independently confirmed" in raw["finalVerification"]["error"]
    with (tmp_path / "offers.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    assert rows[0]["pid"] == "listing-1"
    assert rows[0]["price_verified"] == "False"
    report = (tmp_path / "report.md").read_text()
    assert "Final browser verification: failed" in report
    assert "affected offer is unverified and excluded from the site" in report


def test_gift_card_raw_replay_preserves_prior_failure(tmp_path, monkeypatch):
    import cli

    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps({
        "listings": [{"pid": "listing-1"}],
        "discovery": {"plati_found": 1, "ggsel_found": 1, "status": "partial", "coverage": "bounded"},
        "finalVerification": {"skipped": False, "failed": True, "error": "prior failure", "results": [],
                              "excludedOffers": [
                                  {"marketplace": "ggsel", "pid": "listing-1", "optionText": "50 USD"}
                              ]},
    }))
    args = _parse_args([
        "--family", "apple_gift_card", "--region", "US", "--skip-discover", "--skip-final-verify",
        "--raw", str(raw_path), "--csv", str(tmp_path / "offers.csv"), "--md", str(tmp_path / "report.md"),
    ])
    monkeypatch.setattr(cli, "discover_gift_cards", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected discovery")))
    monkeypatch.setattr(cli, "collect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected collection")))
    monkeypatch.setattr(cli, "gift_card_offers_from_raw", lambda *a, **k: [_offer()])

    assert _run_gift_card_scan(args) == 2
    raw = json.loads(raw_path.read_text())
    assert raw["finalVerification"]["failed"] is True
    assert raw["finalVerification"]["error"] == "prior failure"
    with (tmp_path / "offers.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    assert rows[0]["price_verified"] == "False"
    assert "Final browser verification: failed" in (tmp_path / "report.md").read_text()


def test_successful_reverification_replaces_prior_failure(tmp_path, monkeypatch):
    import cli

    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps({
        "listings": [{"pid": "listing-1"}],
        "discovery": {"plati_found": 1, "ggsel_found": 1, "status": "partial", "coverage": "bounded"},
        "finalVerification": {"skipped": False, "failed": True, "error": "prior failure", "results": []},
    }))
    args = _parse_args([
        "--family", "apple_gift_card", "--region", "US", "--skip-discover",
        "--raw", str(raw_path), "--csv", str(tmp_path / "offers.csv"), "--md", str(tmp_path / "report.md"),
    ])
    monkeypatch.setattr(cli, "gift_card_offers_from_raw", lambda *a, **k: [_offer()])
    monkeypatch.setattr(cli, "verify_winners", lambda targets, offers, **kwargs: [
        {"marketplace": "ggsel", "pid": "listing-1", "verified": True, "observedPrice": 4200}
    ])

    assert _run_gift_card_scan(args) == 0
    raw = json.loads(raw_path.read_text())
    assert raw["finalVerification"] == {
        "skipped": False,
        "results": [{"marketplace": "ggsel", "pid": "listing-1", "verified": True, "observedPrice": 4200}],
    }
    assert "Final browser verification: failed" not in (tmp_path / "report.md").read_text()
