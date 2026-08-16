"""Build canonical (tier × duration × delivery) price table from a raw
collector JSON, apply family eligibility, and emit CSV + Markdown."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable

from families.base import FamilyConfig
from analyzer.price import (
    classify_tier,
    classify_duration,
    classify_duration_from_title,
    classify_delivery,
    select_real_price,
    is_glitched,
    apply_delta_correction,
)


def offers_from_raw(raw: dict) -> Iterable[dict]:
    """Walk all listings × options × prices; yield one row per (offer)."""
    for listing in raw.get("listings", []):
        for opt in listing.get("options", []):
            if not opt.get("clicked"):
                continue
            text = opt.get("text", "")
            title = listing.get("title", "")
            tier = classify_tier(text)
            duration = classify_duration(text) or classify_duration_from_title(title)
            delivery = classify_delivery(text, title)
            if not tier or not duration:
                continue
            price, strong = select_real_price(opt.get("prices", []))
            if price is None:
                continue
            price = apply_delta_correction(text, price)
            glitch, reason = is_glitched(price, duration, tier)
            yield {
                "marketplace": listing.get("marketplace"),
                "pid": listing.get("pid"),
                "url": listing.get("url"),
                "title": listing.get("title", ""),
                "option_text": text.replace("\n", " | ")[:200],
                "tier": tier,
                "duration": duration,
                "delivery": delivery,
                "price_rub": price,
                "strong_signal": strong,
                "glitched": glitch,
                "glitch_reason": reason,
            }


def dedupe(offers: list[dict]) -> list[dict]:
    """Keep the LAST (post-click) state per (marketplace, pid, option_text).
    Prefer rows with strong_signal if duplicate."""
    seen: dict[tuple, dict] = {}
    for o in offers:
        k = (o["marketplace"], str(o["pid"]), o["option_text"])
        if k not in seen or (o["strong_signal"] and not seen[k]["strong_signal"]):
            seen[k] = o
    return list(seen.values())


def cheapest_per_tier(offers: list[dict], family: FamilyConfig) -> dict[tuple[str, str, str], dict]:
    """Return {(tier, duration, delivery): cheapest_offer}."""
    eligible = [o for o in offers if family.matches_offer(o)]
    out: dict[tuple[str, str, str], dict] = {}
    for o in eligible:
        k = (o["tier"], o["duration"], o["delivery"])
        if k not in out or o["price_rub"] < out[k]["price_rub"]:
            out[k] = o
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_markdown(
    offers: list[dict],
    cheapest: dict,
    family: FamilyConfig,
    path: Path,
    source_path: Path | None = None,
) -> None:
    title = f"# {family.name} price table ({family.description})"
    with path.open("w") as f:
        f.write(title + "\n\n")
        if source_path:
            f.write(f"Source: `{source_path.name}`\n\n")
        f.write(f"Rows: {len(offers)} ({sum(1 for o in offers if o['glitched'])} glitched, suppressed from ranking)\n\n")
        for dur in ("1m", "3m", "12m", "6m"):
            f.write(f"\n## Duration: {dur}\n\n")
            f.write("| Tier | Delivery | Price | Marketplace | PID | Title | Link |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            sub = [o for o in offers if o["duration"] == dur]
            for o in sorted(sub, key=lambda x: (x["tier"], x["glitched"], x["price_rub"])):
                flag = " ⚠️" if o["glitched"] else ""
                t_short = o["title"][:55].replace("|", "/")
                f.write(f"| {o['tier']}{flag} | {o['delivery']} | {o['price_rub']:.0f} ₽ | {o['marketplace']} | {o['pid']} | {t_short} | [link]({o['url']}) |\n")
            f.write("\n**Cheapest per tier (eligible, non-glitched):**\n\n")
            for tier in ("Max", "Pro+", "Pro 20X", "Pro 5X", "Pro", "Plus", "GO", "Lite"):
                for delivery in ("own_account", "new_account"):
                    k = (tier, dur, delivery)
                    if k in cheapest:
                        c = cheapest[k]
                        f.write(f"- **{tier} / {delivery}** — {c['price_rub']:.0f} ₽ — [{c['url']}]({c['url']})\n")
        glitched = [o for o in offers if o["glitched"]]
        if glitched:
            f.write("\n## Flagged as glitched\n\n")
            for o in glitched:
                f.write(f"- {o['tier']} {o['duration']} {o['price_rub']:.0f} ₽ — {o['glitch_reason']} ({o['marketplace']} {o['pid']})\n")
