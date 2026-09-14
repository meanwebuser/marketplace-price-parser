import random

from analyzer.output import cheapest_per_tier
from analyzer.validate import validate_rankings
from families.base import FamilyConfig


def _family() -> FamilyConfig:
    return FamilyConfig(
        name="opaque",
        search_terms=[],
        purpose_preset="any",
        marketplaces=["opaque-market"],
        tier_filter=["Opaque"],
        duration_filter=["1m"],
        delivery_filter=["own_account"],
    )


def _offer(opaque_id: str, price: float, **changes) -> dict:
    offer = {
        "marketplace": "opaque-market",
        "pid": opaque_id,
        "url": f"https://invalid.example/{opaque_id}",
        "title": "opaque",
        "option_text": opaque_id,
        "tier": "Opaque",
        "duration": "1m",
        "delivery": "own_account",
        "price_rub": price,
        "strong_signal": True,
        "glitched": False,
        "available": True,
        "price_verified": True,
    }
    offer.update(changes)
    return offer


def test_random_unknown_prices_validate_without_catalogue_knowledge():
    rng = random.Random(7349)
    offers = [_offer(f"seller-{i}-{rng.getrandbits(40):x}", rng.uniform(1, 1_000_000)) for i in range(100)]
    cheapest = cheapest_per_tier(offers, _family())

    assert validate_rankings({}, offers, cheapest, _family()) == []
    assert next(iter(cheapest.values()))["price_rub"] == min(o["price_rub"] for o in offers)


def test_tampered_winner_is_rejected_without_an_expected_price():
    offers = [_offer("alpha", 731.25), _offer("beta", 964.50)]
    key = ("Opaque", "1m", "own_account")

    issues = validate_rankings({}, offers, {key: offers[1]}, _family())

    assert any("not the observed minimum" in issue for issue in issues)


def test_unavailable_and_unverified_offers_cannot_enter_ranking():
    offers = [
        _offer("available", 900),
        _offer("unavailable", 1, available=False),
        _offer("unverified", 2, price_verified=False),
    ]
    cheapest = cheapest_per_tier(offers, _family())

    assert next(iter(cheapest.values()))["pid"] == "available"
    assert validate_rankings({}, offers, cheapest, _family()) == []


def test_schema_v2_rejects_impossible_capture_states():
    raw = {"schemaVersion": 2, "listings": [{"options": [
        {
            "clicked": True,
            "available": False,
            "disabled": True,
            "prices": [],
            "priceChanged": True,
            "priceStable": False,
        },
        {"clicked": False, "priceVerified": True},
    ]}]}

    issues = validate_rankings(raw, [], {}, _family())

    assert len(issues) == 4
    assert any("unavailable control" in issue for issue in issues)
    assert any("no post-click price" in issue for issue in issues)
    assert any("never became stable" in issue for issue in issues)
    assert any("without a click" in issue for issue in issues)
