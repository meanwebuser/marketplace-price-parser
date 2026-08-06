"""Family registry. Each FamilyConfig describes one product we know how
to scan for: search terms, marketplace filters, eligibility rules."""

from families.base import FamilyConfig
from families import minimax, zai, chatgpt, claude

FAMILY_REGISTRY: dict[str, FamilyConfig] = {
    cfg.name: cfg
    for cfg in (minimax.CONFIG, zai.CONFIG, chatgpt.CONFIG, claude.CONFIG)
}

__all__ = ["FAMILY_REGISTRY", "FamilyConfig"]
