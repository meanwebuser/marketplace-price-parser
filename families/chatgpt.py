"""ChatGPT Plus / Pro — ported from ggsel_plati/best_chatgptplus_prices.py.

Uses purpose presets (renew / new-account / any) to filter delivery types
before ranking. The default preset is 'renew' (extend on existing
account) — the most common use case."""

from families.base import FamilyConfig

# Mirrors the PURPOSE_PRESETS from the original best_chatgptplus_prices.py.
# 'own-no-login' is treated as a subset of 'own_account' for our flow
# (both mean "activate on the buyer's account"), so the include list is
# just ['own_account'] — the analyzer maps both chatgptplus regex hits to
# our own_account label.
_PURPOSE_PRESETS = {
    "new_account": {
        "delivery_filter": ["new_account"],
        "delivery_exclude": ["shared_account"],
        "forbid_shared": True,
    },
    "renew": {
        "delivery_filter": ["own_account"],
        "delivery_exclude": ["shared_account"],
        "forbid_shared": True,
    },
    "any": {
        "delivery_filter": ["own_account", "new_account"],
        "delivery_exclude": ["shared_account"],
        "forbid_shared": True,
    },
}


def _reject_stale_base_prices(offer: dict) -> bool:
    """ChatGPT Pro grey prices start well above ~8K ₽ (X5) / ~16K ₽ (X20).
    A far lower 'Pro' price means the buy block didn't refresh after the
    variant click and still shows the listing's base variant."""
    if offer.get("duration") != "1m" or not str(offer.get("tier", "")).startswith("Pro"):
        return True
    floor = 3000 if offer["tier"] in ("Pro", "Pro 5X") else 5000
    return offer.get("price_rub", 0) >= floor


def _build(preset_name: str = "renew") -> FamilyConfig:
    preset = _PURPOSE_PRESETS[preset_name]
    return FamilyConfig(
        name="chatgpt",
        # "ChatGPT" / Plus terms alone sort price-asc and get crowded out by
        # cheap shared Plus offers before any Pro listing shows up in the
        # top-N; Pro-specific queries keep Pro coverage.
        search_terms=["ChatGPT", "GPT Plus", "chatgpt plus", "ChatGPT Pro", "GPT Pro"],
        marketplaces=["plati", "ggsel"],
        tier_filter=["Plus", "Pro", "Pro 5X", "Pro 20X"],
        duration_filter=["1m"],
        delivery_filter=preset["delivery_filter"],
        delivery_exclude=preset["delivery_exclude"],
        forbid_shared=preset["forbid_shared"],
        purpose_preset=preset_name,
        ggssel_category="chatgpt-all",
        eligibility_extra=_reject_stale_base_prices,
        description=f"ChatGPT Plus / Pro monthly subscription (purpose: {preset_name})",
    )


# Default to 'renew' — the most common use case.
CONFIG = _build("renew")
