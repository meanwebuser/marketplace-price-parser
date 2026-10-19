"""MiniMax Token Plan Max — existing config (ported from minimax_max_prices.py)."""

import re

from families.base import FamilyConfig


def _is_minimax_offer(offer: dict) -> bool:
    """Keep a generic MAX chip from another service out of MiniMax results."""
    product_text = " ".join(
        str(offer.get(field) or "")
        for field in ("title", "option_text", "raw_option_text")
    )
    return bool(re.search(r"mini\s*max", product_text, re.IGNORECASE))

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
