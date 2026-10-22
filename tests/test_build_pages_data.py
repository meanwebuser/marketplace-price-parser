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


def test_minimax_product_excludes_api_listings(tmp_path):
    csv_path = tmp_path / "2026-01-02-minimax.csv"
    csv_path.write_text(
        "pid,title,option_text,tier,duration,delivery,price_rub\n"
        "subscription,MiniMax Token Plan,Max 1 month,Max,1m,own_account,5303\n"
        "api,MiniMax API Platform,Max 1 month,Max,1m,own_account,1000\n",
        encoding="utf-8",
    )

    offers, _ = normalize_csv(csv_path, "minimax")

    assert [offer["pid"] for offer in offers] == ["subscription"]


def test_zai_product_excludes_unrelated_ai_listings(tmp_path):
    csv_path = tmp_path / "2026-01-02-zai.csv"
    csv_path.write_text(
        "pid,title,option_text,tier,duration,delivery,price_rub\n"
        "glm,Z.ai GLM Coding,Max 1 month,Max,1m,own_account,16590\n"
        "recraft,Recraft.AI PRO,Pro 1 month,Pro,1m,own_account,99\n",
        encoding="utf-8",
    )

    offers, _ = normalize_csv(csv_path, "zai")

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

    offers, metadata = normalize_csv(csv_path, "kimi")

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
    offers, _ = normalize_csv(csv_path, "kimi")
    assert [offer["pid"] for offer in offers] == ["exact"]
    assert offers[0]["priceVerified"] is True
    assert offers[0]["finalVerified"] is True
