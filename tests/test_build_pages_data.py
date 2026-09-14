import csv
import json

from scripts.build_pages_data import normalize_csv


def test_new_snapshot_excludes_unavailable_and_unverified_rows(tmp_path):
    csv_path = tmp_path / "2026-01-02-chatgpt.csv"
    fields = ["marketplace", "pid", "url", "title", "option_text", "tier", "duration", "delivery", "price_rub", "strong_signal", "glitched", "glitch_reason", "available", "price_verified", "final_verified"]
    rows = [
        dict.fromkeys(fields, "") | {"pid": "ok", "tier": "Pro 20X", "duration": "1m", "delivery": "own_account", "price_rub": "17111", "available": "True", "price_verified": "True", "final_verified": "True"},
        dict.fromkeys(fields, "") | {"pid": "unavailable", "tier": "Pro 20X", "duration": "1m", "delivery": "own_account", "price_rub": "1", "available": "False", "price_verified": "True"},
        dict.fromkeys(fields, "") | {"pid": "unverified", "tier": "Pro 20X", "duration": "1m", "delivery": "own_account", "price_rub": "2", "available": "True", "price_verified": "False"},
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    csv_path.with_suffix(".raw.json").write_text(json.dumps({"finalVerification": {"results": [{"verified": True}]}}), encoding="utf-8")

    offers, metadata = normalize_csv(csv_path, "chatgpt")

    assert [offer["pid"] for offer in offers] == ["ok"]
    assert offers[0]["finalVerified"] is True
    assert metadata["sourceRows"] == 3
    assert metadata["publishedRows"] == 1
    assert metadata["finalVerifiedWinners"] == 1


def test_historical_snapshot_without_safety_columns_remains_readable(tmp_path):
    csv_path = tmp_path / "2025-01-02-chatgpt.csv"
    csv_path.write_text("pid,tier,duration,delivery,price_rub\nlegacy,Plus,1m,own_account,999\n", encoding="utf-8")

    offers, _ = normalize_csv(csv_path, "chatgpt")

    assert [offer["pid"] for offer in offers] == ["legacy"]
