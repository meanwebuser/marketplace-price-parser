"""MiniMax M Plan and historical Token Plan subscriptions."""

import re

from families.base import FamilyConfig

_BRAND_RE = re.compile(r"mini\s*max|мини\s*макс", re.IGNORECASE)
_PLAN_RE = re.compile(r"\b(?:token[\s-]*plan|m[\s-]*plan)\b", re.IGNORECASE)
_TIER_RE = re.compile(r"\b(?:go|explore|build|plus|max|ultra)\b", re.IGNORECASE)
_NEW_TIER_RE = re.compile(r"\b(?:go|explore|build)\b", re.IGNORECASE)
_TOPUP_RE = re.compile(r"api[\s_-]*key|credit|кредит|top[\s_-]*up|пополн|баланс", re.IGNORECASE)


def is_subscription_candidate(text: str) -> bool:
    """Discover both names broadly; selected options decide eligibility later."""
    if not _BRAND_RE.search(text):
        return False
    if _PLAN_RE.search(text):
        return True
    if re.search(r"\baudio\b|\bаудио\b", text, re.IGNORECASE):
        return False
    tiers = set(m.group(0).lower() for m in _TIER_RE.finditer(text))
    if _TOPUP_RE.search(text) and len(tiers) < 2:
        return False
    has_term = re.search(r"\d+\s*(?:[-/–]\s*\d+)*\s*(?:m\b|month|месяц|мес)|month|месяц|год|year", text, re.IGNORECASE)
    return bool(tiers and has_term)


def _is_minimax_offer(offer: dict) -> bool:
    """Keep subscription variants even when their mixed listing says API/credits."""
    title = str(offer.get("title") or "")
    selected = " ".join(str(offer.get(field) or "") for field in ("option_text", "raw_option_text"))
    product_text = f"{title} {selected}"
    if not _BRAND_RE.search(product_text) or _TOPUP_RE.search(selected):
        return False
    if _TOPUP_RE.search(title) and not _TIER_RE.search(selected):
        return False
    if re.search(r"\baudio\b|\bаудио\b", title, re.IGNORECASE) and not _PLAN_RE.search(product_text):
        return False
    if re.search(r"\bapi\b|api[_-]", title, re.IGNORECASE) and not _PLAN_RE.search(product_text):
        # Sellers call the subscription platform "API" too. Require an
        # explicit plan name, a plan group, or a selected new M Plan tier.
        title_tiers = set(m.group(0).lower() for m in _TIER_RE.finditer(title))
        if len(title_tiers) < 2 and not _NEW_TIER_RE.search(selected):
            return False
    return True

CONFIG = FamilyConfig(
    name="minimax",
    search_terms=["MiniMax", "MiniMax M Plan", "MiniMax Token Plan", "Mini Max", "Минимакс"],
    marketplaces=["plati", "ggsel"],
    tier_filter=["GO", "Explore", "Build", "Plus", "Max", "Ultra"],
    duration_filter=["1m"],
    delivery_filter=["own_account", "new_account"],
    purpose_preset="renew",
    ggssel_category="minimaxhailuo",
    # Public subscription URLs found in GGSEL/search evidence on 2026-10-25.
    # Category discovery is partial; verify each selected option on capture.
    ggsel_ids=["102438200", "102358305", "102359533", "102107986", "102369748",
               "102697420", "101642596", "102443754", "102608819"],
    eligibility_extra=_is_minimax_offer,
    description="MiniMax M Plan (GO/Explore/Build) and Token Plan (Plus/Max/Ultra)",
)
