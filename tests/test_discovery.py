"""Tests for family-specific marketplace candidate discovery."""

from pathlib import Path

from families.minimax import CONFIG as MINIMAX
from families.zai import CONFIG as ZAI
from scanner.discover import (
    GIFT_CARD_QUERIES,
    _extract_ggsel_gift_cards,
    _extract_ggsel_products,
    discover_gift_cards,
)


def test_ggsel_titleless_cards_fall_back_to_slug_and_filter_other_max_products():
    html = """
    <a href="/catalog/product/runway-ai-standard-pro-max-1-12m-102304393"></a>
    <a href="/catalog/product/minimax-token-plan-explore-1-month-102927393"></a>
    """

    offers = _extract_ggsel_products(html, MINIMAX)

    assert [offer["native_id"] for offer in offers] == ["102927393"]
    assert offers[0]["label"] == "minimax token plan explore 1 month"


def test_ggsel_numeric_cards_use_only_their_own_span_text_or_image_alt():
    html = """
    <a href="/catalog/product/102369748"></a>
    <a href="/catalog/product/102369748">
      <span>MiniMax M Plan Explore 1 Month</span>
    </a>
    <a href="/catalog/product/102438200">
      <img src="plan.webp" alt="MiniMax M Plan Build 1 Month">
    </a>
    <a href="/catalog/product/102000001"><span>Runway Max 1 Month</span></a>
    <span>MiniMax M Plan Explore 1 Month</span>
    <a href="/catalog/product/102000002"></a>
    <img src="outside.webp" alt="MiniMax M Plan Go 1 Month">
    <a href="/catalog/product/102000003"><img alt="Unrelated product"></a>
    <a href="/catalog/product/minimax-token-plan-max-1-month-102927393"></a>
    """

    offers = _extract_ggsel_products(html, MINIMAX)

    assert [offer["native_id"] for offer in offers] == ["102369748", "102438200", "102927393"]
    assert offers[0]["label"] == "MiniMax M Plan Explore 1 Month"
    assert offers[1]["label"] == "MiniMax M Plan Build 1 Month"


def test_saved_ggsel_overlay_links_use_sibling_metadata_from_the_same_card():
    html = (Path(__file__).parent / "fixtures" / "ggsel_zai_overlay_cards.html").read_text()

    offers = _extract_ggsel_products(html, ZAI)

    assert [offer["native_id"] for offer in offers] == ["102331610", "102109731"]
    assert offers[0]["label"] == "Подписка Z.ai MAX на 3 месяца –Z ai Премиум-подписка (ограниченное предложение)"
    assert offers[1]["label"] == "Апгрейд Z.AI Lite/Pro/Max: GLM 5.2, 1–12 месяца | F.A.S.T, FULL WARRANTY"
    # Numeric-only URLs use exactly the same card metadata, while retaining
    # the original fixture as evidence for the actual slug-ID regression.
    numeric = html.replace(
        "/catalog/product/podpiska-z-ai-max-na-3-mesiaca-z-ai-premium-podpiska-ogranicennoe-predlozenie-102331610",
        "/catalog/product/102331610",
    )
    assert [offer["native_id"] for offer in _extract_ggsel_products(numeric, ZAI)] == ["102331610", "102109731"]


def test_card_metadata_does_not_promote_topup_or_leak_between_product_ids():
    html = """
    <div data-testid="card">
      <a href="/catalog/product/zai-max-subscription-1-month-9001"></a>
      <img alt="Пополнение баланса Z.ai API">
    </div>
    <div data-testid="card">
      <a href="/catalog/product/9002">Z.ai MAX subscription 3 месяца</a>
      <a href="/catalog/product/9003"></a>
    </div>
    <div data-testid="card"><a href="/catalog/product/9004"></a></div>
    <div>Z.ai MAX subscription 3 месяца</div>
    """

    assert [offer["native_id"] for offer in _extract_ggsel_products(html, ZAI)] == ["9002"]


def test_gift_card_search_has_query_variants_and_does_not_collect_turkey_yet():
    tr = discover_gift_cards("TR")

    assert len(GIFT_CARD_QUERIES["US"]) >= 3
    assert any("Apple Gift Card" in query and "USA" in query for query in GIFT_CARD_QUERIES["US"])
    assert any("iTunes Gift Card" in query for query in GIFT_CARD_QUERIES["US"])
    assert tr["candidates"] == []
    assert tr["transport"] == "not-collected"
    assert "deferred" in tr["coverage"]


def test_ggsel_gift_card_discovery_uses_explicit_region_evidence():
    html = """
    <div data-testid="card"><a href="/catalog/product/apple-itunes-usa-102552039"></a>
      <img alt="Apple iTunes Gift Card $2-$100 USA"></div>
    <div data-testid="card"><a href="/catalog/product/apple-itunes-turkey-5211965"></a>
      <img alt="Подарочная карта Apple iTunes Turkey 10-4000 TL"></div>
    <div data-testid="card"><a href="/catalog/product/itunes-unknown-5000000"></a>
      <img alt="Apple iTunes Gift Card 2-100"></div>
    """

    us = _extract_ggsel_gift_cards(html, "US")
    tr = _extract_ggsel_gift_cards(html, "TR")

    assert [item["native_id"] for item in us] == ["102552039"]
    assert [item["native_id"] for item in tr] == ["5211965"]
