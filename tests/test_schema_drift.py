import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanner import schema


def _listing(**over):
    row = {
        "marketplace": "ggsel", "template": "ggsel_ssr_http",
        "controlCount": 1, "variantControlCount": 2, "storeCurrency": "RUB",
        "options": [{
            "kind": "button", "priceEvidenceMethod": "ggsel_ssr_modifier",
            "text": "Max 1 month", "prices": [{"text": "1234 ₽"}],
        }],
        "title": "Claude Max subscription", "pid": "123", "initialPrices": [],
    }
    row.update(over)
    return row


def test_schema_signature_ignores_dynamic_listing_content():
    first = _listing(title="Claude Max subscription", pid="123")
    second = _listing(title="Claude Pro subscription", pid="999",
                      options=[{"kind": "button", "priceEvidenceMethod": "ggsel_ssr_modifier",
                                "text": "Pro 1 month", "prices": [{"text": "999 ₽"}]}])

    assert schema._signature(schema.listing_schema_descriptor(first)) == schema._signature(
        schema.listing_schema_descriptor(second)
    )


def test_schema_inventory_marks_new_shapes_and_then_stabilizes(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "ROOT", tmp_path)
    snapshots = tmp_path / "docs" / "snapshots" / "data"
    snapshots.mkdir(parents=True)
    baseline = _listing()
    signature = schema._signature(schema.listing_schema_descriptor(baseline))
    previous = snapshots / "2026-10-26-claude.raw.json"
    previous.write_text(json.dumps({"siteSchema": {"signatures": {signature: {"count": 1}}}}))

    current = {"listings": [_listing(pid="new") ]}
    schema.annotate_schema(current, "claude")
    assert current["siteSchema"]["status"] == "stable"
    assert current["siteSchema"]["newSignatures"] == []
    assert current["listings"][0]["schemaFingerprint"] == signature

    changed = {"listings": [_listing(template="unknown", pid="changed") ]}
    schema.annotate_schema(changed, "claude")
    assert changed["siteSchema"]["status"] == "changed"
    assert changed["siteSchema"]["driftDetected"] is True
    assert len(changed["siteSchema"]["newSignatures"]) == 1


def test_missing_baseline_is_explicit_not_reported_as_site_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "ROOT", tmp_path)
    result = schema.annotate_schema({"listings": [_listing()]}, "claude")
    assert result["siteSchema"]["status"] == "baseline_missing"
    assert result["siteSchema"]["driftDetected"] is False


def test_legacy_snapshot_is_used_as_a_schema_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "ROOT", tmp_path)
    snapshots = tmp_path / "docs" / "snapshots" / "data"
    snapshots.mkdir(parents=True)
    previous = snapshots / "2026-10-26-minimax.raw.json"
    previous.write_text(json.dumps({"listings": [_listing()]}), encoding="utf-8")

    result = schema.annotate_schema({"listings": [_listing(pid="current")]}, "minimax")
    assert result["siteSchema"]["status"] == "stable"
    assert result["siteSchema"]["baselinePath"] == "snapshots/data/2026-10-26-minimax.raw.json"


def test_schema_baseline_accepts_family_timestamp_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "ROOT", tmp_path)
    snapshots = tmp_path / "docs" / "snapshots" / "data"
    snapshots.mkdir(parents=True)
    previous = snapshots / "2026-10-27-chatgpt-2122.raw.json"
    previous.write_text(json.dumps({"listings": [_listing()]}), encoding="utf-8")
    (snapshots / "2026-10-27-chatgpt.raw.json").write_text(
        json.dumps({"listings": [_listing(template="old")] }), encoding="utf-8"
    )
    current = {"listings": [_listing(pid="current")]}
    schema.annotate_schema(current, "chatgpt")
    assert current["siteSchema"]["status"] == "stable"
    assert current["siteSchema"]["baselinePath"] == "snapshots/data/2026-10-27-chatgpt-2122.raw.json"


def test_adaptive_gate_samples_only_three_listings_per_new_shape(monkeypatch):
    import cli
    import analyzer.llm_extract

    listings = [_listing(pid=str(i)) for i in range(5)]
    for row in listings:
        row["schemaFingerprint"] = "new-layout"
    raw = {
        "listings": listings,
        "siteSchema": {"driftDetected": True, "newSignatures": ["new-layout"]},
    }
    sent = []

    def fake_extract(subset, **kwargs):
        sent.extend(row["pid"] for row in subset["listings"])
        return [], {"called": 1, "batches": 1, "failed": 0}

    monkeypatch.setenv("LLM_API_KEY", "unit-test-key")
    monkeypatch.setattr(analyzer.llm_extract, "extract_offers", fake_extract)
    args = cli._parse_args(["--family", "minimax"])
    _, meta = cli._analyze(raw, cli._resolve_families(args)[0], args)
    assert sent == ["0", "1", "2"]
    assert meta["routeReasons"]["new_schema_signature"] == 3
