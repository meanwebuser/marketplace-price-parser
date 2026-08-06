"""Claude (Anthropic) — stub. Real config to be added when listings surface."""

from families.base import FamilyConfig

CONFIG = FamilyConfig(
    name="claude",
    search_terms=["Claude", "claude.ai"],
    marketplaces=["plati", "ggsel"],
    tier_filter=["Pro", "Max"],
    duration_filter=["1m"],
    delivery_filter=["own_account", "new_account"],
    purpose_preset="renew",
    ggssel_category="claudeai",
    description="Claude Pro / Max subscription — placeholder",
)
