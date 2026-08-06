"""Claude (Anthropic) Pro / Max — GGSEL has a /catalog/claudeai section
mirroring the structure of the ChatGPT category. Curated list of
top sellers as of 2026-08; discovery via the general pipeline picks
up new ones automatically."""

from families.base import FamilyConfig

# Top sellers from /catalog/claudeai (manual list, refreshed manually).
# GGSEL does not expose a stable /catalog/claudeai — verified via the
# Playwright crawler that /catalog/claudeai returns 200 OK with
# Claude Pro / Max listings.
GGSEL_TOP_SELLERS = [
    "claude-pro-1-mesiac-reshenie-vas-akkaunt-llm-ai-103188317",
    "obnovlenie-claude-pro-podpiska-1-mesiac-103188318",
    "claude-pro-max-1-mes-acc-102745891",
    "claude-pro-podpiska-s-garantiei-1m-103366929",
    "claude-ai-pro-max-1-mesiac-llm-chat-bot-103145687",
]

CONFIG = FamilyConfig(
    name="claude",
    search_terms=["Claude", "claude.ai", "Claude Pro", "Claude Max"],
    marketplaces=["plati", "ggsel"],
    tier_filter=["Pro", "Max"],
    duration_filter=["1m"],
    delivery_filter=["own_account", "new_account"],
    forbid_shared=True,
    purpose_preset="renew",
    ggssel_category="claudeai",
    ggsel_ids=GGSEL_TOP_SELLERS,
    description="Claude Pro / Max monthly subscription (1 month, own account)",
)
