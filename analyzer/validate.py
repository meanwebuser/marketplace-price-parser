"""Product-agnostic consistency checks for scanner rankings.

The validator deliberately has no catalogue fixtures: no seller IDs, known
prices, expected winners, or product-specific text.  It proves only generic
capture and ranking invariants from the data produced by the current run.
"""

from __future__ import annotations

import math
from typing import Any

from families.base import FamilyConfig


def _offer_identity(offer: dict) -> tuple[Any, ...]:
    return (
        offer.get("marketplace"),
        str(offer.get("pid")),
        offer.get("option_text"),
        offer.get("tier"),
        offer.get("duration"),
        offer.get("delivery"),
        offer.get("price_rub"),
    )


def validate_rankings(
    raw: dict,
    offers: list[dict],
    cheapest: dict[tuple[str, str, str], dict],
    family: FamilyConfig,
) -> list[str]:
    """Return violations of generic capture, eligibility, and minimum rules."""
    issues: list[str] = []

    for index, offer in enumerate(offers):
        price = offer.get("price_rub")
        if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(price) or price <= 0:
            issues.append(f"offer[{index}] has no positive finite price")

    eligible = [offer for offer in offers if family.matches_offer(offer)]
    buckets: dict[tuple[str, str, str], list[dict]] = {}
    for offer in eligible:
        key = (offer["tier"], offer["duration"], offer["delivery"])
        buckets.setdefault(key, []).append(offer)

    if set(cheapest) != set(buckets):
        issues.append("ranking buckets differ from eligible-offer buckets")

    for key, candidates in buckets.items():
        winner = cheapest.get(key)
        if winner is None:
            continue
        if _offer_identity(winner) not in {_offer_identity(item) for item in candidates}:
            issues.append(f"winner for {key!r} is not an eligible candidate")
            continue
        minimum = min(item["price_rub"] for item in candidates)
        if winner.get("price_rub") != minimum:
            issues.append(f"winner for {key!r} is not the observed minimum")
        if winner.get("available") is False:
            issues.append(f"winner for {key!r} is unavailable")
        if winner.get("price_verified") is False:
            issues.append(f"winner for {key!r} has an unverified price")

    # schemaVersion gates strict raw-capture checks so historical JSON remains
    # readable.  Every newly collected capture is versioned and must obey them.
    if raw.get("schemaVersion", 0) >= 2:
        for listing_index, listing in enumerate(raw.get("listings", [])):
            for option_index, option in enumerate(listing.get("options", [])):
                where = f"listing[{listing_index}].option[{option_index}]"
                if option.get("clicked") and (
                    option.get("available") is False
                    or option.get("disabled")
                    or option.get("ariaDisabled")
                ):
                    issues.append(f"{where} clicked an unavailable control")
                if option.get("clicked") and not option.get("prices"):
                    issues.append(f"{where} has no post-click price snapshot")
                if option.get("priceChanged") and not option.get("priceStable"):
                    issues.append(f"{where} changed price but never became stable")
                if option.get("priceVerified") and not option.get("clicked"):
                    issues.append(f"{where} verifies a price without a click")

    return sorted(set(issues))
