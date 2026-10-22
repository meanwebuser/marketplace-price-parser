import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer.output import cheapest_per_tier
from families.minimax import CONFIG


def test_unverified_price_cannot_win_cheapest_ranking():
    unchecked = {"tier": "Max", "duration": "1m", "delivery": "new_account", "glitched": False, "price_rub": 1, "price_verified": False}
    verified = {"tier": "Max", "duration": "1m", "delivery": "new_account", "glitched": False, "price_rub": 4275, "price_verified": True}
    for offer in (unchecked, verified):
        offer["title"] = "MiniMax Token Plan"
    result = cheapest_per_tier([unchecked, verified], CONFIG)
    assert result[("Max", "1m", "new_account")]["price_rub"] == 4275


def test_default_variant_cannot_reuse_another_variants_stale_price():
    from analyzer.output import offers_from_raw

    raw = {"listings": [{
        "marketplace": "plati", "pid": "6131590", "title": "Kimi Plus Pro Ultra 1-12M",
        "initialPrices": [{"text": "2 312 ₽", "cls": "id_product_price"}],
        "options": [{
            "text": "Апгрейд/Продление: Kimi Plus - 1 Месяц (Требуется Вход)\nВыбран",
            "clicked": True, "selected": True, "selectedAfter": False,
            "priceChanged": False, "priceStable": True, "priceVerified": True,
            "prices": [{"text": "291 944 ₽", "cls": "id_product_price"}],
        }],
    }]}
    offer, = offers_from_raw(raw)
    assert offer["price_verified"] is False


def test_surcharge_cannot_override_explicit_failed_selection():
    from analyzer.output import offers_from_raw

    option = {
        "text": "Kimi Plus - 1 месяц на ваш аккаунт +500 ₽",
        "clicked": True, "priceChanged": False, "priceStable": True,
        "priceVerified": False,
        "prices": [{"text": "2 000 ₽", "cls": "id_product_price"}],
    }
    listing = {
        "marketplace": "plati", "pid": "delta", "title": "Kimi",
        "initialPrices": [{"text": "2 000 ₽", "cls": "id_product_price"}],
    }
    # True or absent selection evidence still permits the existing arithmetic
    # inference. An explicit failure must remain unverified.
    for selection in ({}, {"selectedAfter": True}, {"selectedAfter": False}):
        raw = {"listings": [{**listing, "options": [{**option, **selection}]}]}
        offer, = offers_from_raw(raw)
        assert offer["price_rub"] == 2500
        assert offer["price_verified"] is (selection.get("selectedAfter") is not False)
