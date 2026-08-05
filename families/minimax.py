"""MiniMax Token Plan Max — existing config (ported from minimax_max_prices.py)."""

from families.base import FamilyConfig

CONFIG = FamilyConfig(
    name="minimax",
    search_terms=["MiniMax", "minimax"],
    marketplaces=["plati", "ggsel"],
    tier_filter=["Max"],
    duration_filter=["1m"],
    delivery_filter=["own_account", "new_account"],
    purpose_preset="renew",
    ggssel_category="minimaxhailuo",
    description="MiniMax Token Plan Max, 1 month, existing account delivery",
)
