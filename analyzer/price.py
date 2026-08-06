#!/usr/bin/env python3
"""Pass 2: parse /tmp/zai_raw.json and build (tier × duration × delivery)
→ price table. Output CSV + Markdown summary.

Detects and flags likely price glitches (e.g. GGSEL 102109731 12-month Max
showing 1 541 999 ₽ instead of ~162 846 ₽). When a glitched price is the
cheapest for its tier/duration bucket, it is reported as 'glitched' rather
than ranked first."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

PRICE_RE = re.compile(r"(\d[\d\s\xa0]*)")


def parse_price(text: str) -> float | None:
    if not text:
        return None
    m = PRICE_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    n = float(m.group(1).replace(" ", "").replace("\xa0", ""))
    if n <= 0 or n > 1_000_000:
        return None
    return n


def select_real_price(prices: list[dict]) -> tuple[float | None, bool]:
    """Return (price, is_strong_signal). Strong signal means we matched
    the buy-block / id_product_price class explicitly (high confidence).
    Fallback means we picked from among decoys (medium confidence)."""
    if not prices:
        return None, False
    # 1. Strong signal: explicit buy-block / id_product_price class
    for p in prices:
        cls = (p.get("cls") or "").lower()
        if ("buyblock" in cls and "amount" in cls) or "id_product_price" in cls:
            n = parse_price(p.get("text", ""))
            if n is not None and n <= 1_000_000:
                return n, True
    # 2. Drop decoys: Steam refs, tiny upsells, sidebar recommendations
    cleaned = []
    for p in prices:
        t = p.get("text", "")
        if re.search(r"Steam\s*(RUB|KZT|UAH)", t) or "USD" in t:
            continue
        n = parse_price(t)
        if n is None or n < 3000:
            continue
        cleaned.append(n)
    if not cleaned:
        return None, False
    return max(cleaned), False


def classify_tier(text: str) -> str:
    if re.search(r"\bMax\b|макс", text, re.IGNORECASE):
        return "Max"
    if re.search(r"\bPro\s*\+|Pro\+|про\+", text, re.IGNORECASE):
        return "Pro+"
    if re.search(r"\bPro\b", text, re.IGNORECASE):
        return "Pro"
    if re.search(r"\bLite\b|лайт", text, re.IGNORECASE):
        return "Lite"
    return ""


def classify_duration(text: str) -> str:
    t = text.lower()
    if re.search(r"\b1\s*год\b|1\s*year|12\s*месяц|12\s*month|1\s*y\b|365\s*дн", t):
        return "12m"
    if re.search(r"\b6\s*месяц|6m\b|6\s*month|180\s*дн", t):
        return "6m"
    if re.search(r"\b3\s*месяц|3m\b|3\s*month|90\s*дн", t):
        return "3m"
    if re.search(r"\b1\s*месяц|1m\b|1\s*month|30\s*дн|\bмесяц\b", t):
        return "1m"
    return ""


_DELIV_PATTERNS = [
    ("shared_account", re.compile(r"\bобщ(ая|ий|ее|ee|ie|iy)?\b.{0,15}\b(доступ|аккаунт|подписк)|общ.{0,10}1\s*месяц|общ.{0,15}\b(plus|pro|max)", re.I)),
    ("own_account",   re.compile(r"на\s*ваш\w*\s*аккаунт|со\s*входом|на\s*вашем\s*аккаунте|продлен\w*|продлевается|апгрейд|требуется\s*вход|first\s*registration|ваш\s*акк|upgrade\s*on\s*your\s*personal\s*account|personal\s*account|renew\s*subscription", re.I)),
    ("own_account",   re.compile(r"без\s*входа|без\s*логина|по\s*токену|активация\s*по\s*токену", re.I)),  # own-no-login
    ("new_account",   re.compile(r"готов\w*\s*аккаунт|персональн\w+\s*аккаунт|случайн\w*\s*(?:почт|email)|выда\w*\s*аккаунт|полный\s*доступ\s*к\s*почте|random\s*email|pre.?made\s*account|ready\s*account|предложен\w*\s*на\s*перв\w*\s*месяц|first\s*month\s*offer", re.I)),
]

# Title hints used when the chip text doesn't say anything (e.g. "Max | 1 месяц").
# Most cheap listings fall into "new_account" — seller activates on their
# own email / hands you a ready account. "own_account" usually requires
# explicit "Upgrade" / "Требуется Вход" wording in the chip itself.
_TITLE_DELIV_HINTS = [
    ("new_account",   re.compile(r"мгновенн\w*\s*доступ|instant\s*access|официальн\w*\s*активация|official\s*activation|pre.?made|ready\s*account", re.I)),
    ("new_account",   re.compile(r"выда\w*\s*в\s*теч|персональн\w*\s*аккаунт|complete\s*account|full\s*access", re.I)),
    ("own_account",   re.compile(r"\bобновлен\w*|продлен\w*|upgrade|renew|extend|сохран\w*\s*истори|сохран\w*\s*рабоч", re.I)),
]


def classify_delivery(text: str, title: str = "") -> str:
    """Map (option text, listing title) to delivery type. Order matters:
    shared-account wins, then own-account, then new-account. The chip
    text is authoritative; title hints only kick in when chip text is
    silent (e.g. "Max | 1 месяц") so we don't misclassify an explicit
    "Требуется Вход" listing from its title alone."""
    text = text or ""
    for delivery, pat in _DELIV_PATTERNS:
        if pat.search(text):
            return delivery
    for delivery, pat in _TITLE_DELIV_HINTS:
        if pat.search(title or ""):
            return delivery
    return "unknown"


def is_glitched(price: float, duration: str, tier: str) -> tuple[bool, str]:
    """Return (is_glitch, reason)."""
    # 1m: Z.ai Max monthly should be ~15K–25K RUB on grey market.
    # Below 1K or above 60K for monthly is suspicious.
    if duration == "1m":
        if tier == "Max" and price > 60_000:
            return True, f"Max 1m price {price} exceeds 60K (likely UI glitch)"
        if price < 500:
            return True, f"Price {price} too low for subscription"
    if duration == "3m":
        if tier == "Max" and price > 200_000:
            return True, f"Max 3m price {price} exceeds 200K (likely UI glitch)"
    if duration == "12m":
        if tier == "Max" and price > 500_000:
            return True, f"Max 12m price {price} exceeds 500K (likely UI glitch)"
        if tier == "Max" and price < 50_000:
            return True, f"Max 12m price {price} suspiciously low (likely under-reporting)"
    return False, ""


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/zai_raw.json")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/zai_table.csv")
    data = json.loads(src.read_text())
    rows = []
    for listing in data.get("listings", []):
        market = listing.get("marketplace")
        pid = listing.get("pid")
        url = listing.get("url")
        title = listing.get("title", "")
        for opt in listing.get("options", []):
            if not opt.get("clicked"):
                continue
            text = opt.get("text", "")
            title = listing.get("title", "")
            tier = classify_tier(text)
            duration = classify_duration(text)
            delivery = classify_delivery(text, title=title)
            if not tier or not duration:
                continue
            price, strong = select_real_price(opt.get("prices", []))
            if price is None:
                continue
            glitch, reason = is_glitched(price, duration, tier)
            rows.append({
                "marketplace": market,
                "pid": pid,
                "url": url,
                "title": title,
                "option_text": text.replace("\n", " | ")[:200],
                "tier": tier,
                "duration": duration,
                "delivery": delivery,
                "price_rub": price,
                "strong_signal": strong,
                "glitched": glitch,
                "glitch_reason": reason,
            })
    # Dedupe by (marketplace, pid, option_text) — keep LAST (post-click state)
    seen = {}
    for r in rows:
        key = (r["marketplace"], str(r["pid"]), r["option_text"])
        if key not in seen or r["strong_signal"]:
            seen[key] = r
    rows = list(seen.values())
    rows.sort(key=lambda r: (r["duration"], r["tier"], r["delivery"], r["price_rub"]))

    with dst.open("w", newline="") as f:
        fieldnames = ["marketplace", "pid", "url", "title", "option_text",
                      "tier", "duration", "delivery", "price_rub",
                      "strong_signal", "glitched", "glitch_reason"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    md = dst.with_suffix(".md")
    with md.open("w") as f:
        f.write(f"# Z.ai GLM Coding price table (pass 2 from {src.name})\n\n")
        f.write(f"Rows: {len(rows)} ({sum(1 for r in rows if r['glitched'])} flagged as glitched)\n\n")
        for dur in ("1m", "3m", "12m"):
            f.write(f"\n## Duration: {dur}\n\n")
            f.write("| Tier | Delivery | Price | Marketplace | PID | Link |\n")
            f.write("|---|---|---|---|---|---|\n")
            sub = [r for r in rows if r["duration"] == dur]
            for r in sorted(sub, key=lambda x: (x["tier"], x["glitched"], x["price_rub"])):
                flag = " ⚠️" if r["glitched"] else ""
                f.write(f"| {r['tier']}{flag} | {r['delivery']} | {r['price_rub']:.0f} ₽ | {r['marketplace']} | {r['pid']} | [link]({r['url']}) |\n")
            f.write("\n**Cheapest per tier (non-glitched):**\n\n")
            for tier in ("Max", "Pro+", "Pro", "Lite"):
                tier_rows = [r for r in sub if r["tier"] == tier and not r["glitched"]]
                if not tier_rows:
                    continue
                cheapest = min(tier_rows, key=lambda x: x["price_rub"])
                f.write(f"- **{tier}** — {cheapest['price_rub']:.0f} ₽ ({cheapest['marketplace']}, {cheapest['delivery']}) — [{cheapest['url']}]({cheapest['url']})\n")
            f.write("\n**Flagged as glitched:**\n\n")
            glitched = [r for r in sub if r["glitched"]]
            if glitched:
                for r in glitched:
                    f.write(f"- {r['tier']} {r['duration']} {r['price_rub']:.0f} ₽ — {r['glitch_reason']} ({r['marketplace']} {r['pid']})\n")
            else:
                f.write("- none\n")

    print(f"CSV:  {dst} ({len(rows)} rows)")
    print(f"MD:   {md}\n")
    for dur in ("1m", "3m", "12m"):
        print(f"=== {dur} ===")
        for tier in ("Max", "Pro+", "Pro", "Lite"):
            tier_rows = [r for r in rows if r["duration"] == dur and r["tier"] == tier and not r["glitched"]]
            if not tier_rows:
                continue
            cheapest = min(tier_rows, key=lambda x: x["price_rub"])
            print(f"  {tier:6s} cheapest: {cheapest['price_rub']:>10.0f} ₽  {cheapest['marketplace']:5s}  {cheapest['url']}")
        glitched = [r for r in rows if r["duration"] == dur and r["glitched"]]
        if glitched:
            print(f"  ⚠️  glitched: {len(glitched)} rows suppressed")


if __name__ == "__main__":
    main()
