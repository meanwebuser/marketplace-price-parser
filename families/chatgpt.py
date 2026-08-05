"""ChatGPT Plus — stub. Real config ported in Stage 2 from ggsel_plati/."""

from families.base import FamilyConfig

CONFIG = FamilyConfig(
    name="chatgpt",
    search_terms=["ChatGPT", "GPT Plus", "chatgpt plus"],
    marketplaces=["plati", "ggsel"],
    tier_filter=["Plus", "Pro"],
    duration_filter=["1m"],
    delivery_filter=["own_account", "new_account"],
    purpose_preset="renew",
    ggssel_category=None,  # TODO: port from ggsel_chatgptplus_crawler.py
    description="ChatGPT Plus / Pro subscription — placeholder",
)
