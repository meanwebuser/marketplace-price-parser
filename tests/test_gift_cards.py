import csv
from pathlib import Path
from analyzer.output import gift_card_offers_from_raw
from cli import best_gift_card_value, rank_gift_card_offers
from scripts import build_pages_data
from scripts.build_pages_data import normalize_csv


def _raw_listing(*, title="Apple Gift Card USA", region_text="Region: USA", option="$4 (USD)",
                 selected_after=True, price_verified=True, price="458 ₽"):
    return {"listings": [{
        "marketplace": "ggsel", "pid": "5211966",
        "url": "https://ggsel.net/catalog/product/5211966", "title": title,
        "descText": f"Apple Account redemption code. {region_text}",
        "options": [{
            "text": option, "clicked": True, "selectedAfter": selected_after,
            "priceVerified": price_verified,
            "prices": [{"text": price, "cls": "id_product_price"}],
        }],
    }]}


def test_gift_card_parser_uses_selected_amount_and_has_no_subscription_fields():
    offer, = gift_card_offers_from_raw(_raw_listing())

    assert (offer["region"], offer["denomination"], offer["denomination_currency"]) == ("US", 4, "USD")
    assert offer["price_rub"] == 458
    assert offer["price_verified"] is True
    assert offer["available"] is None
    assert offer["availability_status"] == "unknown"
    assert offer["delivery"] == "digital_code"
    assert "tier" not in offer and "duration" not in offer


def test_cli_best_gift_card_uses_verified_rub_per_dollar_and_same_markdown_order():
    cards = [
        {"pid": "2", "denomination": 2, "price_rub": 159, "available": True, "price_verified": True},
        {"pid": "100", "denomination": 100, "price_rub": 6000, "available": True, "price_verified": True},
        {"pid": "50-soldout", "denomination": 50, "price_rub": 2000, "available": False, "price_verified": True},
        {"pid": "5-stock-unknown", "denomination": 5, "price_rub": 289, "available": None, "price_verified": True},
    ]

    assert [offer["pid"] for offer in rank_gift_card_offers(cards)] == ["50-soldout", "5-stock-unknown", "100", "2"]
    assert best_gift_card_value(cards)["pid"] == "5-stock-unknown"


def test_gift_card_parser_rejects_region_mismatch_and_currency_only_evidence():
    assert list(gift_card_offers_from_raw(_raw_listing(region_text="Region: Turkey"), "US")) == []
    assert list(gift_card_offers_from_raw(_raw_listing(title="Apple Gift Card", region_text="USD gift code"), "US")) == []
    assert list(gift_card_offers_from_raw(_raw_listing(option="€4"), "US")) == []


def test_gift_card_price_stays_unverified_when_option_selection_failed():
    offer, = gift_card_offers_from_raw(_raw_listing(selected_after=False))
    assert offer["price_rub"] == 458
    assert offer["price_verified"] is False


def test_gift_card_purchase_stock_uses_buy_button_state_not_variant_control_disabled():
    raw = _raw_listing()
    listing = raw["listings"][0]
    listing["buyButtonDisabled"] = True
    listing["options"][0]["disabled"] = False
    offer, = gift_card_offers_from_raw(raw)

    assert offer["price_verified"] is True
    assert offer["available"] is False
    assert offer["availability_status"] == "out_of_stock"

    listing["buyButtonDisabled"] = None
    listing["options"][0]["disabled"] = True
    offer, = gift_card_offers_from_raw(raw)
    assert offer["available"] is None
    assert offer["availability_status"] == "unknown"


def test_selected_gift_card_surcharge_is_included_in_total_and_unit_price():
    raw = _raw_listing(option="$2 (USD) + 100 ₽", price="159 ₽", price_verified=False)
    listing = raw["listings"][0]
    listing["initialPrices"] = [{"text": "159 ₽", "cls": "id_product_price"}]
    listing["options"][0]["priceChanged"] = False

    offer, = gift_card_offers_from_raw(raw, "US")

    assert offer["price_rub"] == 259
    assert offer["price_delta"] == 100
    assert offer["price_verified"] is True
    assert offer["price_rub"] / offer["denomination"] == 129.5


def test_gift_card_normalizer_can_parse_turkish_lira_without_running_a_turkey_scan():
    raw = {"listings": [{
        "marketplace": "ggsel", "pid": "turkey", "title": "Apple iTunes Gift Card Turkey",
        "descText": "Region: Turkey; code delivery", "options": [{
            "text": "100 TL", "clicked": True,
            "prices": [{"text": "300 ₽", "cls": "id_product_price"}],
        }],
    }]}

    offer, = gift_card_offers_from_raw(raw, "TR")

    assert (offer["region"], offer["denomination"], offer["denomination_currency"]) == ("TR", 100, "TRY")
    assert "tier" not in offer and "duration" not in offer


def test_gift_card_site_normalization_requires_matching_region_and_verified_price(tmp_path):
    csv_path = tmp_path / "2026-10-25-apple_us.csv"
    fields = ["marketplace", "pid", "url", "title", "option_text", "region",
              "denomination", "denomination_currency", "delivery", "price_rub",
              "available", "price_verified", "final_verified", "final_observed_price"]
    rows = [
        ["ggsel", "us", "https://example.test/us", "Apple Gift Card USA", "$4 USD", "US", 4, "USD", "digital_code", 458, "True", "True", "False", ""],
        ["ggsel", "tr", "https://example.test/tr", "Apple Gift Card Turkey", "100 TRY", "TR", 100, "TRY", "digital_code", 300, "True", "True", "False", ""],
        ["ggsel", "unchecked", "https://example.test/unchecked", "Apple Gift Card USA", "$5 USD", "US", 5, "USD", "digital_code", 500, "True", "False", "False", ""],
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(fields)
        writer.writerows(rows)

    offers, metadata = normalize_csv(csv_path, "apple_us", docs_root=tmp_path)

    assert [item["pid"] for item in offers] == ["us"]
    assert offers[0]["region"] == "US"
    assert offers[0]["denomination"] == 4
    assert offers[0]["pricePerUnit"] == 114.5
    assert "tier" not in offers[0] and "duration" not in offers[0]
    assert metadata["publishedRows"] == 1


def test_gift_card_final_verification_can_rescue_only_the_exact_price(tmp_path):
    csv_path = tmp_path / "2026-10-25-apple_us.csv"
    csv_path.write_text(
        "pid,region,denomination,denomination_currency,price_rub,price_verified,final_verified,final_observed_price\n"
        "exact,US,4,USD,458,False,True,458\n"
        "mismatch,US,5,USD,500,False,True,501\n",
        encoding="utf-8",
    )

    offers, _ = normalize_csv(csv_path, "apple_us", docs_root=tmp_path)

    assert [item["pid"] for item in offers] == ["exact"]


def test_site_builder_loads_targeted_gift_card_snapshot_without_replacing_ai_roots(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    targeted = docs / "snapshots" / "targeted"
    targeted.mkdir(parents=True)
    path = targeted / "2026-10-25-apple-us.csv"
    path.write_text(
        "marketplace,pid,url,title,option_text,region,denomination,denomination_currency,delivery,price_rub,available,price_verified\n"
        "ggsel,verified,https://example.test,Apple Gift Card USA,$2 USD,US,2,USD,digital_code,159,True,True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(build_pages_data, "ROOT", tmp_path)

    product = build_pages_data.load_product(docs / "snapshots" / "data", "apple_us")

    assert product["kind"] == "gift_card"
    assert product["region"] == "US"
    assert product["metadata"]["sourcePath"] == "snapshots/targeted/2026-10-25-apple-us.csv"
    assert [offer["pid"] for offer in product["offers"]] == ["verified"]


def test_site_builder_publishes_only_source_verified_manual_snapshot_price(tmp_path):
    csv_path = tmp_path / "2026-10-25-apple-us.csv"
    fields = ["marketplace", "listing_id", "title", "url", "region", "default_denomination",
              "price_rub", "price_evidence_status", "delivery", "http_status"]
    rows = [
        ["ggsel", "102552039", "Apple Gift Card USA", "https://ggsel.net/catalog/product/102552039", "US", "2 USD", "159", "verified_ssr_offer_plus_default_variant_zero_modifier", "instant digital code", "200"],
        ["ggsel", "5211966", "Apple Gift Card USA", "https://ggsel.net/catalog/product/5211966", "US", "4 USD", "458", "listing_metadata_only", "unknown", "200"],
        ["ggsel", "old", "Apple Gift Card USA", "https://ggsel.net/catalog/product/old", "US", "2 USD", "159", "verified_ssr_offer_plus_default_variant_zero_modifier", "instant digital code", "404"],
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(fields)
        writer.writerows(rows)

    offers, _ = normalize_csv(csv_path, "apple_us", docs_root=tmp_path)

    assert [item["pid"] for item in offers] == ["102552039"]
    assert (offers[0]["denomination"], offers[0]["denominationCurrency"], offers[0]["priceRub"]) == (2, "USD", 159)
    assert offers[0]["pricePerUnit"] == 79.5


def test_stock_status_is_independent_from_verified_price_and_variant_control_enabled(tmp_path):
    csv_path = tmp_path / "2026-10-25-apple-us.csv"
    fields = ["marketplace", "listing_id", "title", "url", "region", "denomination_label",
              "face_value_usd", "face_evidence", "base_price_rub", "modifier", "modifier_currency",
              "effective_total_rub", "rub_per_usd", "comparison_status", "http_status", "disabled",
              "variant_id", "availability_status", "availability_evidence"]
    rows = [
        ["ggsel", "a", "Apple Gift Card USA", "https://ggsel.net/a", "US", "$5 (USD)", 5, "option label has USD/$", 250, 0, "RUB", 250, 50, "confirmed option mapping", 200, "false", "a5", "in_stock", "buy button enabled"],
        ["ggsel", "b", "Apple Gift Card USA", "https://ggsel.net/b", "US", "$50 (USDT)", 50, "option label has USD/$", 189, 100, "RUB", 289, 5.78, "confirmed option mapping", 200, "false", "b50", "out_of_stock", "user screenshot: selected buy button says Нет в наличии"],
        ["ggsel", "c", "Apple Gift Card USA", "https://ggsel.net/c", "US", "$5 (USD)", 5, "option label has USD/$", 289, 0, "RUB", 289, 57.8, "confirmed option mapping", 200, "false", "c5", "unknown", "SSR stock fields null"],
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(fields)
        writer.writerows(rows)

    offers, _ = normalize_csv(csv_path, "apple_us", docs_root=tmp_path)
    by_pid = {offer["pid"]: offer for offer in offers}

    assert by_pid["a"]["available"] is True
    assert by_pid["b"]["available"] is False
    assert by_pid["c"]["available"] is None
    assert all(offer["priceVerified"] is True for offer in offers)
    assert by_pid["b"]["availabilityEvidence"].startswith("user screenshot")
    assert by_pid["b"]["priceEvidenceStatus"] == "confirmed option mapping"


def test_current_gift_card_variant_snapshot_publishes_only_mapped_effective_totals():
    csv_path = Path(__file__).resolve().parents[1] / "docs/snapshots/targeted/2026-10-25-apple-us.csv"

    offers, metadata = normalize_csv(csv_path, "apple_us")
    best = min(offers, key=lambda item: item["pricePerUnit"])

    assert len(offers) == 157
    assert metadata["sourcePath"] == "snapshots/targeted/2026-10-25-apple-us.csv"
    assert (best["pid"], best["variantId"], best["denomination"], best["priceRub"], best["pricePerUnit"]) == (
        "102664570", "36715422", 5, 289, 57.8,
    )
    assert best["seller"] == "FiatPay"
    assert best["priceEvidenceStatus"] == "confirmed option mapping"
    assert best["priceEvidence"]["basePriceRub"] + best["priceEvidence"]["modifierRub"] == best["priceRub"]
    assert all(item["marketplace"] == "ggsel" for item in offers)
    assert all("tier" not in item and "duration" not in item for item in offers)
    assert best["available"] is None and best["availabilityStatus"] == "unknown"
    sold_out = next(item for item in offers if item["variantId"] == "36715426")
    assert sold_out["denomination"] == 50
    assert sold_out["available"] is False and sold_out["availabilityStatus"] == "out_of_stock"
    assert "user screenshot" in sold_out["availabilityEvidence"].lower()
    assert sold_out["availabilityCapturedAt"]
    assert sum(item["available"] is False for item in offers) == 1
    assert sum(item["available"] is True for item in offers) == 1
    assert sum(item["available"] is None for item in offers) == 155
    verified_50 = next(item for item in offers if item["pid"] == "102662580" and item["denomination"] == 50)
    assert verified_50["priceRub"] == 5150
    assert verified_50["available"] is True and verified_50["availabilityStatus"] == "in_stock"
    cli_rows = [{
        "pid": item["variantId"], "denomination": item["denomination"],
        "price_rub": item["priceRub"], "available": item["available"],
        "price_verified": item["priceVerified"],
    } for item in offers]
    assert best_gift_card_value(cli_rows)["pid"] == best["variantId"]
    assert rank_gift_card_offers(cli_rows)[0]["pid"] == best["variantId"]


def test_catalogue_builder_separates_gift_cards_and_can_preserve_ai_products_exactly():
    ai_products = [{"id": "minimax", "offers": [{"tier": "Max", "duration": "1m", "priceRub": 1}]}]
    card = {"id": "apple_us", "kind": "gift_card", "region": "US", "offers": [{"denomination": 2, "denominationCurrency": "USD", "priceRub": 159}]}

    output = build_pages_data.catalogue_data(
        [{"id": "minimax", "offers": [{"tier": "Max", "duration": "1m", "priceRub": 999}]}],
        [card], existing={"products": ai_products}, preserve_existing_products=True,
    )

    assert output["products"] == ai_products
    assert output["giftCards"] == [card]
    assert all(item["id"] != "apple_us" for item in output["products"])
