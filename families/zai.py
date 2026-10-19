"""Z.ai GLM Coding Max — current focus product."""

from families.base import FamilyConfig

CONFIG = FamilyConfig(
    name="zai",
    search_terms=["z.ai", "GLM Coding", "Zhipu", "Z.AI"],
    marketplaces=["plati", "ggsel"],
    tier_filter=["Max"],
    duration_filter=["1m", "3m", "12m"],
    delivery_filter=["own_account", "new_account", "unknown"],
    purpose_preset="renew",
    ggssel_category="zai",
    # Supplement Playwright category discovery with manually curated
    # product IDs for known top sellers.
    ggsel_ids=[
        "102109731",
        "102458121",
        "102610634",
        "102438864",
        "102010339",
        "102358846",
        "102495696",
        "102483517",
        "102644827",
        "5327293",
        "102185754",
        "102234852",
        "102584986",
        "102662846",
        "102303683",
        "102618255",
        "102113607",
        "5413116",
        "102169054",
        "102651023",
        "102583131",
        "102457859",
        "102296362",
        "102495673",
        "102104408",
        "102528209",
        "102528064",
        "102611308",
    ],
    description="Z.ai GLM Coding Max, 1/3/12 months, own account or random email",
)
