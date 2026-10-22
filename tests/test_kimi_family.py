"""Offline coverage for Kimi catalogue discovery and subscription eligibility."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from analyzer.output import cheapest_per_tier, offers_from_raw
from analyzer.price import classify_tier
from cli import _parse_args, _resolve_families
from families import FAMILY_REGISTRY
from scanner.discover import _candidate_matches_family, _extract_ggsel_products, discover_ggsel


def kimi():
    return FAMILY_REGISTRY["kimi"]


@pytest.mark.parametrize("tier", ["Plus", "Pro", "Max", "Ultra"])
@pytest.mark.parametrize("duration", ["1m", "3m", "6m", "12m"])
@pytest.mark.parametrize("delivery", ["own_account", "new_account", "shared_account", "unknown"])
def test_kimi_catalogue_accepts_subscription_taxonomy(tier, duration, delivery):
    assert kimi().matches_offer({
        "title": f"Kimi AI K3 {tier} subscription",
        "tier": tier, "duration": duration, "delivery": delivery,
        "available": True, "price_verified": True,
    })


@pytest.mark.parametrize("title", [
    "KIMI K3 Ultra 1M", "Kimi AI Plus 6m", "Kimi K3 Pro 3m",
    "Kimi AI Plus/Pro/Max/Ultra 1/12M Подписка",
    "Кими Ультра подписка 1 месяц", "Kimi subscription 12 months",
])
def test_kimi_subscription_candidates(title):
    assert _candidate_matches_family(title, kimi())


@pytest.mark.parametrize("title", [
    "Kimi API key Pro 1 month", "Kimi API-key Ultra 1m",
    "Kimi API_ключ подписка 1 месяц", "Kimi API Pro 1m",
    "Kimi top-up Pro 1m", "Kimi topup Plus 1 month",
    "Kimi пополнение баланса Pro 1 месяц", "Kimi credits Max 1m",
    "Kimi кредиты подписка 1 месяц", "Runway Ultra 1 month",
    "Kimi sticker pack", "Kimi Ultra lifetime",
])
def test_kimi_rejects_non_subscription_candidates(title):
    assert not _candidate_matches_family(title, kimi())


@pytest.mark.parametrize("extra", ["API-key", "top-up", "credits", "пополнение баланса"])
def test_kimi_eligibility_rechecks_non_subscription_options(extra):
    assert not kimi().matches_offer({
        "title": "Kimi AI Plus subscription 1 month",
        "option_text": extra, "tier": "Plus", "duration": "1m",
        "delivery": "own_account",
    })


def test_kimi_eligibility_uses_option_brand_on_mixed_brand_titles():
    eligibility = kimi().eligibility_extra
    mixed_title = "Подписка GLM Lite / Kimi Plus на 1 месяц"

    assert eligibility({
        "title": mixed_title,
        "option_text": "Kimi Coding Plus — 1 месяц",
    })
    assert not eligibility({
        "title": mixed_title,
        "option_text": "GLM Coding Lite — 1 месяц",
    })
    assert not eligibility({
        "title": mixed_title,
        "option_text": "Lite — 1 месяц",
    })
    assert eligibility({
        "title": "Kimi Plus subscription 1 month",
        "option_text": "Plus — 1 month",
    })


@pytest.mark.parametrize("field,value", [
    ("available", False), ("price_verified", False), ("glitched", True),
    ("tier", "Lite"), ("duration", "7d"),
])
def test_kimi_retains_existing_validity_guards(field, value):
    offer = {"title": "Kimi AI Pro 1 month", "tier": "Pro", "duration": "1m", "delivery": "unknown"}
    assert not kimi().matches_offer({**offer, field: value})


def test_ultra_tier_does_not_change_existing_tier_priority():
    assert classify_tier("Kimi Ultra 1 месяц") == "Ultra"
    assert classify_tier("Kimi Ультра 1 месяц") == "Ultra"
    assert classify_tier("Max Pro Plus Ultra 1 month") == "Max"


def test_canonical_cli_resolves_kimi_and_ranks_synthetic_ultra_offer():
    family, = _resolve_families(_parse_args(["--family", "kimi"]))
    raw = {"listings": [{
        "marketplace": "plati", "pid": "fixture", "url": "fixture://kimi",
        "title": "Kimi AI Ultra subscription 1 month",
        "options": [{
            "text": "Ultra 1 месяц", "clicked": True,
            "prices": [{"cls": "id_product_price", "text": "4321 ₽"}],
            "priceVerified": True,
        }],
    }]}
    offers = list(offers_from_raw(raw))
    assert list(cheapest_per_tier(offers, family)) == [("Ultra", "1m", "unknown")]
    raw["listings"][0]["options"][0]["text"] += " credits"
    assert not cheapest_per_tier(list(offers_from_raw(raw)), family)


def test_kimi_titleless_category_cards_include_ultra_and_exclude_api():
    html = '''
    <a href="/catalog/product/kimi-k3-ultra-1m-123"></a>
    <a href="/catalog/product/kimi-api-key-pro-1-month-456"></a>
    '''
    assert [p["native_id"] for p in _extract_ggsel_products(html, kimi())] == ["123"]


def test_ggsel_merges_curated_ids_and_category_without_duplicates():
    family = replace(kimi(), ggsel_ids=["123", "kimi-pro-1m-456", "123"])
    discovered = [{"source": "ggsel", "native_id": "123", "label": "live title", "url": "live url"}]
    with patch("scanner.discover._ggsel_crawl_async", new=AsyncMock(return_value=discovered)):
        products, transport = discover_ggsel(family)
    assert [p["native_id"] for p in products] == ["123", "456"]
    assert products[0] == discovered[0]
    assert products[1]["url"] == "https://ggsel.net/catalog/product/kimi-pro-1m-456"
    assert products[1]["catalog_price_rub"] is None
    assert transport == "playwright"


@pytest.mark.parametrize("failed", [False, True])
def test_ggsel_curated_ids_survive_empty_or_failed_category(failed):
    family = replace(kimi(), ggsel_ids=["123", "456"])
    crawl = AsyncMock(side_effect=RuntimeError("offline fixture")) if failed else AsyncMock(return_value=[])
    with patch("scanner.discover._ggsel_crawl_async", new=crawl):
        products, transport = discover_ggsel(family)
    assert [p["native_id"] for p in products] == ["123", "456"]
    assert transport == ("playwright-error: offline fixture" if failed else "playwright")


def test_ggsel_merge_respects_result_limit():
    family = replace(kimi(), ggsel_ids=["123", "456"])
    with patch("scanner.discover._ggsel_crawl_async", new=AsyncMock(return_value=[])):
        products, _ = discover_ggsel(family, max_results=1)
    assert [p["native_id"] for p in products] == ["123"]


def test_family_without_curated_ids_keeps_category_results():
    family = FAMILY_REGISTRY["minimax"]
    discovered = [{"source": "ggsel", "native_id": "123", "label": "MiniMax Max 1 month"}]
    with patch("scanner.discover._ggsel_crawl_async", new=AsyncMock(return_value=discovered)):
        assert discover_ggsel(family) == (discovered, "playwright")
