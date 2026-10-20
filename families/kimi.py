"""Kimi AI / Kimi K3 subscriptions for the public marketplace catalogue."""

import re

from families.base import FamilyConfig


_BRAND = re.compile(r"\b(?:kimi|кими)\b", re.I)
_NON_SUBSCRIPTION = re.compile(
    r"\bapi\b|\bapi[_-]|\bапи\b|api\s*key|credit|кредит|"
    r"top[\s_-]*up|пополн|баланс",
    re.I,
)


def is_subscription(text: str) -> bool:
    """Reject unrelated products and API/balance/credit purchases."""
    return bool(_BRAND.search(text) and not _NON_SUBSCRIPTION.search(text))


def _eligible(offer: dict) -> bool:
    return is_subscription(" ".join(
        str(offer.get(key) or "")
        for key in ("title", "option_text", "raw_option_text")
    ))


CONFIG = FamilyConfig(
    name="kimi",
    search_terms=["Kimi", "Kimi AI", "Kimi K3", "Кими"],
    purpose_preset="any",
    marketplaces=["plati", "ggsel"],
    tier_filter=["Plus", "Pro", "Max", "Ultra"],
    duration_filter=["1m", "3m", "6m", "12m"],
    delivery_filter=["own_account", "new_account", "shared_account", "unknown"],
    forbid_shared=False,
    ggssel_category="kimi",
    # Listing identities from the 2026-10-02 snapshot, never historical prices.
    # Category discovery supplements these seeds; collection checks live state.
    ggsel_ids=[
        "102495504", "102523548", "103189142", "102328845",
        "102555752", "102359326", "102663576", "103132934",
        "103189145", "103132933", "103132937", "103132936",
    ],
    eligibility_extra=_eligible,
    description="Kimi AI / Kimi K3 Plus / Pro / Max / Ultra, 1/3/6/12 months, all delivery types",
)
