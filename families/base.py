"""FamilyConfig — declarative spec for one product family."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class FamilyConfig:
    """One product family (e.g. Z.ai GLM Coding Max, MiniMax Token Plan
    Max, ChatGPT Plus). Drives discovery and eligibility filtering."""

    name: str
    search_terms: list[str]
    marketplaces: list[str]                       # ["plati", "ggsel"]
    tier_filter: list[str]                        # ["Max"], ["Pro", "Pro+", "Max"], ...
    duration_filter: list[str]                    # ["1m", "3m", "12m"]
    delivery_filter: list[str]                    # ["own_account", "new_account"]
    purpose_preset: str                           # "renew" | "new_account" | "any"
    ggssel_category: str | None = None
    ggsel_ids: list[str] = field(default_factory=list)  # manual GGSEL IDs
    eligibility_extra: Callable[[dict], bool] | None = None
    description: str = ""

    def matches_offer(self, offer: dict) -> bool:
        """Return True if an offer (post-pass-2 classification) passes
        this family's eligibility filter."""
        if offer.get("tier") not in self.tier_filter:
            return False
        if offer.get("duration") not in self.duration_filter:
            return False
        if offer.get("delivery") not in self.delivery_filter:
            return False
        if offer.get("glitched"):
            return False
        if self.eligibility_extra and not self.eligibility_extra(offer):
            return False
        return True
