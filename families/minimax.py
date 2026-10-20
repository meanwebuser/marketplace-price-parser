"""MiniMax Token Plan Max — existing config (ported from minimax_max_prices.py)."""

import re

from families.base import FamilyConfig


def _is_minimax_offer(offer: dict) -> bool:
    """Keep only MiniMax subscriptions, excluding API and balance products."""
    product_text = " ".join(
        str(offer.get(field) or "")
        for field in ("title", "option_text", "raw_option_text")
    )
    is_minimax = bool(re.search(r"mini\s*max", product_text, re.IGNORECASE))
    is_non_subscription = bool(re.search(
        r"\bapi\b|api[_-]|api\s*key|credit|кредит|top[\s_-]*up|пополн|баланс",
        product_text,
        re.IGNORECASE,
    ))
    return is_minimax and not is_non_subscription

CONFIG = FamilyConfig(
    name="minimax",
    search_terms=["MiniMax", "minimax"],
    marketplaces=["plati", "ggsel"],
    tier_filter=["Max"],
    duration_filter=["1m"],
    delivery_filter=["own_account", "new_account"],
    purpose_preset="renew",
    ggssel_category="minimaxhailuo",
    eligibility_extra=_is_minimax_offer,
    description="MiniMax Token Plan Max, 1 month, existing account delivery",
)
