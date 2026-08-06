"""ChatGPT Plus — ported from ggsel_plati/best_chatgptplus_prices.py.

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


def _build(preset_name: str = "renew") -> FamilyConfig:
    preset = _PURPOSE_PRESETS[preset_name]
    return FamilyConfig(
        name="chatgpt",
        search_terms=["ChatGPT", "GPT Plus", "chatgpt plus"],
        marketplaces=["plati", "ggsel"],
        tier_filter=["Plus", "Pro", "Plus/Pro"],
        duration_filter=["1m"],
        delivery_filter=preset["delivery_filter"],
        delivery_exclude=preset["delivery_exclude"],
        forbid_shared=preset["forbid_shared"],
        purpose_preset=preset_name,
        ggssel_category="chatgpt-all",
        description=f"ChatGPT Plus / Pro monthly subscription (purpose: {preset_name})",
    )


# Default to 'renew' — the most common use case.
CONFIG = _build("renew")
