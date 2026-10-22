"""Regression coverage for delivery evidence and selective LLM merge guards."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer.output import offers_from_raw
from analyzer.price import classify_delivery
from analyzer.selective import merge_selective_offers, select_uncertain_listings


def _option(text, price, **over):
    return {
        "text": text,
        "clicked": True,
        "priceVerified": True,
        "priceStable": True,
        "prices": [{"text": f"{price:,}".replace(",", " ") + " ₽",
                    "cls": "ProductBuyBlock__amount"}],
        **over,
    }


def _candidate(pid, text, delivery, price):
    return {
        "marketplace": "ggsel", "pid": pid, "option_text": text,
        "tier": "Pro 5X", "duration": "1m", "delivery": delivery,
        "price_rub": float(price), "strong_signal": True, "glitched": False,
        "source": "llm",
    }


def test_page_ready_account_resolves_new_and_merge_rejects_own_upgrade():
    page_text = "Breadcrumb: Готовый аккаунт\nВаш email / Создание нового"
    listing = {
        "marketplace": "ggsel", "pid": "102635272",
        "title": "ChatGPT Pro X5 1 месяц", "descText": "", "pageText": page_text,
        "initialPrices": [],
        "options": [_option("Pro X5 1 месяц", 7999)],
        "skippedControls": [{"kind": "label", "text": "Pro X5 3 месяца | Со входом"}],
    }
    raw = {"listings": [listing]}

    baseline = list(offers_from_raw(raw))
    assert baseline[0]["delivery"] == "new_account"
    assert classify_delivery("", page_text="Ваш email / Создание нового") == "unknown"
    assert classify_delivery("Продлить на ваш email") == "own_account"

    selected, reasons = select_uncertain_listings(raw, baseline)
    assert selected == [listing]
    assert "unknown_delivery" not in reasons[("ggsel", "102635272")]
    merged = merge_selective_offers(
        baseline,
        [_candidate("102635272", "Pro X5 1 месяц", "own_account", 7999)],
        selected,
    )
    assert len(merged) == 1
    assert merged[0]["delivery"] == "new_account"
    assert merged[0].get("source") != "llm"


@pytest.mark.parametrize("blocked_state", [
    {"available": False},
    {"disabled": True},
    {"ariaDisabled": True},
])
def test_llm_merge_rejects_blocked_matching_option(blocked_state):
    listing = {
        "marketplace": "ggsel", "pid": "blocked-variant",
        "title": "ChatGPT Pro X5 1 месяц", "descText": "", "pageText": "",
        "initialPrices": [],
        "options": [
            _option("Pro X5 3 месяца", 7999),  # Conflicting duration routes the listing.
            _option("Pro X5 1 месяц", 8999, **blocked_state),
        ],
        "skippedControls": [],
    }
    raw = {"listings": [listing]}
    deterministic = list(offers_from_raw(raw))
    selected, reasons = select_uncertain_listings(raw, deterministic)
    assert reasons[("ggsel", "blocked-variant")]

    merged = merge_selective_offers(
        deterministic,
        [_candidate("blocked-variant", "Pro X5 1 месяц", "own_account", 8999)],
        selected,
    )
    blocked_row = next(item for item in merged if item["price_rub"] == 8999)
    assert blocked_row.get("source") != "llm"
    assert blocked_row["available"] is False
