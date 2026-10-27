import csv
import json
from pathlib import Path
import pytest

from scripts.build_pages_data import discovery_metadata, normalize_csv


def test_pages_workflow_preserves_existing_non_gift_card_products():
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/deploy-pages.yml"

    assert "python scripts/build_pages_data.py --out docs/data/latest.json --preserve-existing-products" in workflow.read_text()


def test_discovery_metadata_uses_snapshot_audit_path():
    raw = {"discovery": {"auditPath": "audits/2026-10-27-fast-scan.md"}}
    metadata = discovery_metadata(raw, Path("2026-10-27-2118-chatgpt.csv"))
    assert metadata["auditPath"] == "audits/2026-10-27-fast-scan.md"


def test_latest_csv_prefers_later_run_stamp_after_family_name(tmp_path):
    from scripts.build_pages_data import latest_csv

    older = tmp_path / "2026-10-27-chatgpt.csv"
    newer = tmp_path / "2026-10-27-chatgpt-2122.csv"
    older.write_text("old")
    newer.write_text("new")
    assert latest_csv(tmp_path, "chatgpt") == newer


def test_absolute_snapshot_source_path_is_relative_to_repository_docs_root():
    csv_path = (Path(__file__).resolve().parents[1] / "docs/snapshots/targeted/2026-10-25-zai-max.csv").resolve()

    _, metadata = normalize_csv(csv_path, "zai")

    assert metadata["sourcePath"] == "snapshots/targeted/2026-10-25-zai-max.csv"


def test_snapshot_source_path_cannot_escape_repository_docs_root(tmp_path):
    outside = tmp_path / "2026-10-25-zai.csv"
    outside.write_text("pid,title,tier,duration,price_rub\noutside,Z.ai GLM Max,Max,3m,37000\n")

    with pytest.raises(ValueError, match="outside docs root"):
        normalize_csv(outside, "zai")


def test_saved_static_zai_glm_max_offer_keeps_account_marketing_as_unverified_note():
    csv_path = Path(__file__).resolve().parents[1] / "docs/snapshots/targeted/2026-10-25-zai-max.csv"

    offers, _ = normalize_csv(csv_path, "zai")

    item = next(offer for offer in offers if offer["pid"] == "102331610")
    assert (item["tier"], item["duration"], item["priceRub"]) == ("Max", "3m", 37000)
    assert item["delivery"] == "unknown"
    assert item["priceVerified"] is True
    assert item["sellerNote"] == "Доступен только 1 аккаунт"
    assert item["sellerNoteVerified"] is False


def test_zai_seller_account_note_does_not_bypass_product_and_price_gates(tmp_path):
    csv_path = tmp_path / "2026-10-25-zai.csv"
    fields = ["pid", "title", "option_text", "tier", "duration", "delivery", "price_rub", "available", "price_verified", "seller_note"]
    base = dict.fromkeys(fields, "") | {"title": "Z.ai GLM Max 3 месяца", "option_text": "Z.ai GLM Max 3 месяца", "tier": "Max", "duration": "3m", "delivery": "unknown", "price_rub": "37000", "available": "True", "price_verified": "True", "seller_note": "Доступен только 1 аккаунт"}
    rows = [
        base | {"pid": "subscription"},
        base | {"pid": "mixed-subscription", "title": "Z.ai подписка + пополнение баланса/кредиты"},
        base | {"pid": "api", "option_text": "Z.ai GLM API key 3 месяца"},
        base | {"pid": "topup", "option_text": "Пополнение баланса Z.ai GLM"},
        base | {"pid": "unavailable", "available": "False"},
        base | {"pid": "unverified", "price_verified": "False"},
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    offers, _ = normalize_csv(csv_path, "zai", docs_root=tmp_path)

    # Marketplace inventory is intentionally not checked for this catalogue.
    assert [offer["pid"] for offer in offers] == ["subscription", "mixed-subscription", "unavailable"]
    assert offers[0]["delivery"] == "unknown"
    assert offers[0]["sellerNoteVerified"] is False


def test_new_snapshot_excludes_unverified_rows_but_ignores_inventory(tmp_path):
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

    offers, metadata = normalize_csv(csv_path, "chatgpt", docs_root=tmp_path)

    # `available` is not an input gate; only price evidence is.
    assert [offer["pid"] for offer in offers] == ["ok", "unavailable"]
    assert offers[0]["finalVerified"] is True
    assert metadata["sourceRows"] == 3
    assert metadata["publishedRows"] == 2
    assert metadata["finalVerifiedWinners"] == 1


def test_glm_coverage_summary_deduplicates_search_category_and_curated_ids(tmp_path):
    from scripts.build_pages_data import discovery_metadata, discovery_summary_text

    raw = {
        "listings": [
            {"marketplace": "ggsel", "pid": str(pid)} for pid in range(47)
        ] + [{"marketplace": "plati", "pid": str(pid)} for pid in range(33)],
        "discovery": {
            "auditPath": "audits/current.md",
            "coverage": {
                "ggsel": {
                    "status": "ok", "pagesFetched": 1, "candidateCount": 36,
                    "candidatesBeforeCap": 36, "queries": [{"query": "/catalog/zai"}],
                },
                "plati": {"status": "ok", "pagesFetched": 6, "candidatesBeforeCap": 33,
                          "queries": [{"query": "GLM"}]},
            },
            "ggselSearchSupplement": {
                "uniqueCandidates": 39,
                "additionalListingsCaptured": 3,
                "queries": [{"term": "GLM", "url": "https://ggsel.net/search/GLM"}],
                "coverageNote": "counts are not marketplace totals",
            },
        },
    }

    metadata = discovery_metadata(raw, tmp_path / "2026-10-27-zai-2122.csv")
    ggsel = metadata["marketplaces"]["ggsel"]
    summary = discovery_summary_text(metadata)
    assert ggsel["candidateCount"] == 36
    assert ggsel["capturedListings"] == 47
    assert ggsel["searchCandidateCount"] == 39
    assert ggsel["additionalCandidates"] == 3
    assert ggsel["curatedSeedListings"] == ggsel["seedListings"] == 8
    assert ggsel["supplementalSearch"]["routes"] == ["/search/GLM"]
    assert ggsel["supplementalSearch"]["status"] == "partial"
    assert "47 карточек" in summary and "39 совпадений" in summary


def test_historical_snapshot_without_safety_columns_remains_readable(tmp_path):
    csv_path = tmp_path / "2025-01-02-chatgpt.csv"
    csv_path.write_text("pid,tier,duration,delivery,price_rub\nlegacy,Plus,1m,own_account,999\n", encoding="utf-8")

    offers, _ = normalize_csv(csv_path, "chatgpt", docs_root=tmp_path)

    assert [offer["pid"] for offer in offers] == ["legacy"]


def test_minimax_product_excludes_api_listings(tmp_path):
    csv_path = tmp_path / "2026-01-02-minimax.csv"
    csv_path.write_text(
        "pid,title,option_text,tier,duration,delivery,price_rub\n"
        "subscription,MiniMax Token Plan,Max 1 month,Max,1m,own_account,5303\n"
        "api,MiniMax API Platform,Max 1 month,Max,1m,own_account,1000\n",
        encoding="utf-8",
    )

    offers, _ = normalize_csv(csv_path, "minimax", docs_root=tmp_path)

    assert [offer["pid"] for offer in offers] == ["subscription"]


def test_zai_product_excludes_unrelated_ai_listings(tmp_path):
    csv_path = tmp_path / "2026-01-02-zai.csv"
    csv_path.write_text(
        "pid,title,option_text,tier,duration,delivery,price_rub\n"
        "glm,Z.ai GLM Coding,Max 1 month,Max,1m,own_account,16590\n"
        "recraft,Recraft.AI PRO,Pro 1 month,Pro,1m,own_account,99\n",
        encoding="utf-8",
    )

    offers, _ = normalize_csv(csv_path, "zai", docs_root=tmp_path)

    assert [offer["pid"] for offer in offers] == ["glm"]


def test_kimi_product_excludes_glm_option_from_mixed_brand_listing(tmp_path):
    csv_path = tmp_path / "2026-10-23-kimi.csv"
    csv_path.write_text(
        "pid,title,option_text,tier,duration,delivery,price_rub\n"
        '6252740,"Подписка GLM Lite / Kimi Plus на 1 месяц",'
        '"Kimi Coding Plus — 1 месяц",Plus,1m,own_account,2037\n'
        '6252740,"Подписка GLM Lite / Kimi Plus на 1 месяц",'
        '"GLM Coding Lite — 1 месяц",Lite,1m,own_account,1709\n'
        'kimi-only,"Kimi Plus subscription 1 month",'
        '"Plus — 1 month",Plus,1m,own_account,2100\n',
        encoding="utf-8",
    )

    offers, metadata = normalize_csv(csv_path, "kimi", docs_root=tmp_path)

    assert [offer["optionText"] for offer in offers] == [
        "Kimi Coding Plus — 1 месяц", "Plus — 1 month",
    ]
    assert metadata["sourceRows"] == 3
    assert metadata["publishedRows"] == 2


def test_final_price_verification_can_rescue_failed_collection_only_on_exact_match(tmp_path):
    csv_path = tmp_path / "2026-10-23-kimi.csv"
    fields = ["pid", "title", "tier", "duration", "delivery", "price_rub",
              "available", "price_verified", "final_verified", "final_observed_price"]
    cases = [
        ("exact", "True", "4837"),
        ("mismatch", "True", "4838"),
        ("missing", "True", ""),
        ("invalid", "True", "unknown"),
        ("unsuccessful", "False", "4837"),
    ]
    with csv_path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for pid, verified, observed in cases:
            writer.writerow(dict(pid=pid, title="Kimi Pro", tier="Pro", duration="1m",
                                 delivery="unknown", price_rub="4837.0", available="True",
                                 price_verified="False", final_verified=verified,
                                 final_observed_price=observed))
    offers, _ = normalize_csv(csv_path, "kimi", docs_root=tmp_path)
    assert [offer["pid"] for offer in offers] == ["exact"]
    assert offers[0]["priceVerified"] is True
    assert offers[0]["finalVerified"] is True
