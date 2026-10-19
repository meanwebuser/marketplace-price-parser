"""Tests for family-specific marketplace candidate discovery."""

from families.minimax import CONFIG as MINIMAX
from scanner.discover import _extract_ggsel_products


def test_ggsel_titleless_cards_fall_back_to_slug_and_filter_other_max_products():
    html = """
    <a href="/catalog/product/runway-ai-standard-pro-max-1-12m-102304393"></a>
    <a href="/catalog/product/minimax-token-plan-explore-1-month-102927393"></a>
    """

    offers = _extract_ggsel_products(html, MINIMAX)

    assert [offer["native_id"] for offer in offers] == ["102927393"]
    assert offers[0]["label"] == "minimax token plan explore 1 month"
