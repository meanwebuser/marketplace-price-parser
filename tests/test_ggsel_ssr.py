import json
from scanner.ggsel_ssr import parse_ggsel_ssr_listing
from analyzer.output import gift_card_offers_from_raw, offers_from_raw


def _html(*, default_modifier="0", modifier="229", kind="radio"):
    payload = {"queries": [{"state": {"data": {
        "id_goods": 102829897,
        "name": "Apple iTunes Gift Card USA",
        "info": "Code for Apple account in United States",
        "price_brl": 180,
        "options": [{"label": "Choose gift card", "type": kind, "variants": [
            {"value": 1, "text": "2 USD", "default": True, "modify_type": "RUB",
             "modify_value": default_modifier, "modify_value_default": default_modifier, "num_in_stock": 999},
            {"value": 2, "text": "4 USD", "default": False, "modify_type": "RUB",
             "modify_value": modifier, "modify_value_default": "0", "num_in_stock": 999},
        ]}],
    }} }]}
    return f"<html><script>window.__STATE__ = {json.dumps(payload)};</script></html>"


def test_ggsel_ssr_parser_extracts_prices_but_does_not_copy_stock_fields():
    listing = parse_ggsel_ssr_listing(
        _html(),
        {"source": "ggsel", "native_id": "102829897", "url": "https://ggsel.net/catalog/product/102829897"},
        checked_at="2026-10-27T00:00:00Z",
    )

    assert listing is not None
    assert len(listing["options"]) == 2
    assert [option["prices"][0]["text"] for option in listing["options"]] == ["180 ₽", "409 ₽"]
    assert all(option["clicked"] is False for option in listing["options"])
    assert all(option["priceEvidenceMethod"] == "ggsel_ssr_modifier" for option in listing["options"])
    assert all("num_in_stock" not in option for option in listing["options"])
    assert "num_in_stock" not in repr(listing)
    assert listing["availabilityNotChecked"] is True

    raw = {"listings": [listing]}
    gift_cards = list(gift_card_offers_from_raw(raw, "US"))
    assert [(offer["denomination"], offer["price_rub"], offer["price_verified"]) for offer in gift_cards] == [
        (2.0, 180.0, True), (4.0, 409.0, True)
    ]
    assert all(offer["available"] is None and offer["availability_status"] == "unknown" for offer in gift_cards)


def test_ggsel_ssr_parser_falls_back_for_nonzero_default_or_non_radio_controls():
    candidate = {"source": "ggsel", "native_id": "102829897", "url": "https://ggsel.net/catalog/product/102829897"}
    assert parse_ggsel_ssr_listing(_html(default_modifier="10"), candidate, checked_at="now") is None
    assert parse_ggsel_ssr_listing(_html(kind="checkbox"), candidate, checked_at="now") is None
    assert parse_ggsel_ssr_listing(_html(), {**candidate, "url": "https://example.com/product"}, checked_at="now") is None


def test_subscription_ssr_options_enter_normal_pipeline_without_claiming_click_or_stock():
    listing = parse_ggsel_ssr_listing(
        _html(),
        {"source": "ggsel", "native_id": "102829897", "url": "https://ggsel.net/catalog/product/102829897"},
        checked_at="2026-10-27T00:00:00Z",
    )
    listing["title"] = "OpenAI ChatGPT Pro subscription USA"
    listing["descText"] = "One month subscription for your account"
    listing["options"] = [{
        **listing["options"][1],
        "text": "Pro — 1 month — на вашу почту",
    }]
    offers = list(offers_from_raw({"listings": [listing]}))
    assert len(offers) == 1
    assert offers[0]["price_rub"] == 409
    assert offers[0]["price_verified"] is True
    assert offers[0]["available"] is None
    assert offers[0]["delivery"] == "own_account"
