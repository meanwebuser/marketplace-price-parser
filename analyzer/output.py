"""Build canonical (tier × duration × delivery) price table from a raw
collector JSON, apply family eligibility, and emit CSV + Markdown."""

from __future__ import annotations

import csv
import hashlib
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
    classify_availability,
    select_real_price,
    is_glitched,
    apply_delta_correction,
    option_price_delta,
)


def offers_from_raw(raw: dict) -> Iterable[dict]:
    """Walk all listings × options × prices; yield one row per (offer)."""
    for listing in raw.get("listings", []):
        initial_price, initial_strong = select_real_price(listing.get("initialPrices", []))
        for opt in listing.get("options", []):
            if not opt.get("clicked"):
                continue
            text = opt.get("text", "")
            title = listing.get("title", "")
            tier = classify_tier(text)
            duration = classify_duration(text) or classify_duration_from_title(title)
            delivery = classify_delivery(
                text,
                title,
                listing.get("descText", ""),
                page_text=listing.get("pageText", ""),
            )
            if not tier or not duration:
                continue
            available, availability_reason = classify_availability(
                text,
                disabled=bool(opt.get("disabled")),
                aria_disabled=bool(opt.get("ariaDisabled")),
                explicit_available=opt.get("available"),
            )
            price, strong = select_real_price(opt.get("prices", []))
            if price is None:
                continue
            price_changed = opt.get("priceChanged")
            delta = option_price_delta(text)
            price = apply_delta_correction(
                text,
                price,
                price_changed=price_changed,
                initial_price=initial_price,
            )
            price_verified = opt.get("priceVerified")
            # Old collectors trusted the page-load default selection even if
            # the return click failed and left another variant's price visible.
            if opt.get("selectedAfter") is False:
                price_verified = False
            elif price_verified is None:
                # Historical captures predate price-state verification.  Keep
                # them readable, while new captures must state it explicitly.
                price_verified = strong
            elif not price_verified and delta is not None and initial_price is not None and initial_strong:
                # A marketplace base price plus an option surcharge is an
                # independent, self-consistent proof even if the DOM stayed put.
                price_verified = True
            glitch, reason = is_glitched(price, duration, tier)
            yield {
                "marketplace": listing.get("marketplace"),
                "pid": listing.get("pid"),
                "url": listing.get("url"),
                "title": listing.get("title", ""),
                "option_text": text.replace("\n", " | ")[:200],
                "raw_option_text": text,
                "control_kind": opt.get("kind"),
                "control_dom_index": opt.get("domIndex"),
                "control_input_id": opt.get("inputId"),
                "control_value": opt.get("value"),
                "tier": tier,
                "duration": duration,
                "delivery": delivery,
                "price_rub": price,
                "strong_signal": strong,
                "glitched": glitch,
                "glitch_reason": reason,
                "available": available,
                "availability_reason": availability_reason,
                "price_changed": price_changed,
                "price_stable": opt.get("priceStable"),
                "price_verified": bool(price_verified),
                "final_verified": False,
                "final_observed_price": None,
            }


_REGION_PATTERNS = {
    "US": re.compile(r"(?:\busa\b|\bunited states\b|\bu\.?s\.?\b|сша)", re.I),
    "TR": re.compile(r"(?:\bturkey\b|\bturkiye\b|\btur\b|турц\w*)", re.I),
}
_REGION_CURRENCIES = {"US": "USD", "TR": "TRY"}
_GIFT_CARD_OUT_OF_STOCK_RE = re.compile(
    r"\b(?:нет\s+в\s+наличии|нет\s+в\s+продаже|недоступ(?:ен|на|но|ны)?|"
    r"out\s+of\s+stock|sold\s+out|unavailable|not\s+available)\b", re.I,
)
_GIFT_CARD_IN_STOCK_RE = re.compile(r"\b(?:in\s+stock|available\s+now|в\s+наличии)\b", re.I)


def _gift_card_availability(listing: dict, option: dict, option_text: str) -> tuple[bool | None, str, str]:
    """Read stock only from explicit selected-option or purchase-control evidence."""
    for owner in (option, listing):
        buy_text = str(owner.get("buyButtonText") or owner.get("buy_button_text") or "")
        if _GIFT_CARD_OUT_OF_STOCK_RE.search(buy_text):
            return False, "out_of_stock", f"buy button text: {buy_text.strip()}"
        for key in ("availabilityStatus", "availability_status", "stockStatus", "stock_status"):
            raw_status = str(owner.get(key) or "").strip().lower().replace("-", "_")
            if raw_status in {"in_stock", "available"}:
                return True, "in_stock", f"explicit {key}={raw_status}"
            if raw_status in {"out_of_stock", "unavailable", "sold_out"}:
                return False, "out_of_stock", f"explicit {key}={raw_status}"
            if raw_status == "unknown":
                return None, "unknown", f"explicit {key}=unknown"
        purchase_available = owner.get("purchaseAvailable")
        if isinstance(purchase_available, bool):
            status = "in_stock" if purchase_available else "out_of_stock"
            return purchase_available, status, "purchase control availability captured"
        buy_disabled = owner.get("buyButtonDisabled")
        if isinstance(buy_disabled, bool):
            status = "out_of_stock" if buy_disabled else "in_stock"
            return not buy_disabled, status, "buy button disabled state captured"
        if _GIFT_CARD_IN_STOCK_RE.search(buy_text):
            return True, "in_stock", f"buy button text: {buy_text.strip()}"
    if _GIFT_CARD_OUT_OF_STOCK_RE.search(option_text):
        return False, "out_of_stock", "selected option text explicitly says out of stock"
    if _GIFT_CARD_IN_STOCK_RE.search(option_text):
        return True, "in_stock", "selected option text explicitly says in stock"
    return None, "unknown", "purchase availability not captured"


_DENOMINATION_PATTERNS = {
    "US": (
        re.compile(r"\$\s*(\d+(?:[.,]\d{1,2})?)\s*(?:usd)?\b", re.I),
        re.compile(r"\b(\d+(?:[.,]\d{1,2})?)\s*(?:usd\b|\$(?!\w))", re.I),
    ),
    "TR": (
        re.compile(r"\b(\d+(?:[.,]\d{1,2})?)\s*(?:try|tl|₺)(?![a-z])", re.I),
        re.compile(r"₺\s*(\d+(?:[.,]\d{1,2})?)\b", re.I),
    ),
}


def _fixed_gift_card_option(listing: dict, evidence: str, region: str) -> dict | None:
    """Use a page-load price only for a demonstrably fixed product, never a default variant."""
    if listing.get("error") or listing.get("options") or listing.get("variantControlCount"):
        return None
    if region == "US" and not (
        re.search(r"\b(?:USA|United States)\b|сша", evidence, re.I)
        or re.search(r"\bUS\b|\bU\.S\.", str(listing.get("title") or ""))
        or re.search(r"\bregion\s*:?\s*US\b|регион\s*:?\s*US\b", evidence, re.I)
    ):
        return None
    # The collector records controls rejected by its click gate. They still
    # disprove that a listing has no denomination selector.
    for control in listing.get("skippedControls", []):
        if control.get("kind") in {"radio", "role-radio", "select-option", "label"} or re.search(
            r"\$|₺|\b(?:USD|TRY|TL)\b", str(control.get("text") or ""), re.I,
        ):
            return None
    currency_token = r"(?:USD|TRY|TL|\$|₺)"
    number = r"\d+(?:[.,]\d+)?"
    separator = r"(?:[-–—/]|\bto\b|\bдо\b)"
    if re.search(
        rf"(?:[$₺]\s*{number}\s*{separator}\s*[$₺]?\s*{number}|"
        rf"{number}\s*{separator}\s*{number}\s*{currency_token})", evidence, re.I,
    ):
        return None
    if re.search(r"[$₺]\s*\d+[.,]\d{3,}|\d+[.,]\d{3,}\s*(?:USD|TRY|TL)\b", evidence, re.I):
        return None
    foreign_currency = (r"\b(?:EUR|TRY|TL|USDT|CAD|AUD|GBP|CNY|RMB|AED|HKD|NZD)\b|[€£₺¥]"
                        if region == "US" else
                        r"\b(?:USD|EUR|USDT|CAD|AUD|GBP|CNY|RMB|AED|HKD|NZD)\b|[$€£¥]")
    if re.search(foreign_currency, evidence, re.I) or re.search(
        r"\b(?:Canada|Canadian|Australia|Australian|Europe|European|Germany|UK|Japan|China|Global)\b|"
        r"Канад\w*|Австрали\w*|Европ\w*|Германи\w*|Япони\w*|Кита\w*|глобальн\w*", evidence, re.I,
    ):
        return None
    amounts = {
        float(match.group(1).replace(",", "."))
        for pattern in _DENOMINATION_PATTERNS[region]
        for match in pattern.finditer(evidence)
    }
    if len(amounts) != 1 or next(iter(amounts)) <= 0:
        return None
    # select_real_price's ordinary fallback is intentionally insufficient here:
    # a card/catalog price and a foreign-currency price cannot prove a RUB total.
    prices = listing.get("initialPrices", [])
    strong_prices = []
    for candidate in prices:
        if not re.fullmatch(r"\s*\d[\d\s\xa0]*\s*(?:₽|руб\.?|RUB)\s*", str(candidate.get("text") or ""), re.I):
            continue
        price, strong = select_real_price([candidate])
        if price is not None and strong:
            strong_prices.append(price)
    if len(set(strong_prices)) != 1:
        return None
    amount = next(iter(amounts))
    return {
        "kind": "fixed-denomination", "text": f"{amount:g} {_REGION_CURRENCIES[region]}",
        "clicked": True, "selectedAfter": True, "priceVerified": True,
        "prices": [{"text": f"{strong_prices[0]:.0f} ₽", "cls": "id_product_price"}],
    }


def gift_card_offers_from_raw(raw: dict, region: str = "US") -> Iterable[dict]:
    """Extract region-locked Apple gift-card offers without subscription fields.

    A row is emitted only when the listing identifies Apple/iTunes, the page
    explicitly identifies the requested region, and the selected option names
    a denomination in that region's currency. Fixed products may use the
    initial buy-block total when no denomination selector/range is present.
    The listing's generic metadata price is ignored.
    """
    region = str(region).upper()
    if region not in _REGION_PATTERNS:
        raise ValueError(f"unsupported gift-card region {region!r}")
    for listing in raw.get("listings", []):
        initial_price, initial_strong = select_real_price(listing.get("initialPrices", []))
        title = str(listing.get("title") or "")
        desc_text = str(listing.get("descText") or "")
        page_text = f"{desc_text} {listing.get('pageText') or ''}"
        evidence = f"{title} {page_text}"
        product_evidence = f"{title} {desc_text}"
        if not re.search(r"\b(?:apple|itunes)\b", evidence, re.I):
            continue
        # Page-body text contains unrelated recommendations. Use the title and
        # seller description for product region, then require the chosen
        # denomination option below; a Turkey cross-sell must not erase a US
        # listing whose own title/description and option identify US/USD.
        if not _REGION_PATTERNS[region].search(product_evidence):
            continue
        # Do not infer the region from currency alone; storefronts can sell
        # denominations that use another region's currency.
        if any(code != region and pattern.search(product_evidence) for code, pattern in _REGION_PATTERNS.items()):
            continue
        options = listing.get("options", [])
        if not options:
            fixed = _fixed_gift_card_option(listing, product_evidence, region)
            options = [fixed] if fixed else []
        for opt in options:
            if not opt.get("clicked"):
                continue
            option_text = str(opt.get("text") or "").strip()
            if any(code != region and pattern.search(option_text) for code, pattern in _REGION_PATTERNS.items()):
                continue
            denomination = None
            currency = None
            for pattern in _DENOMINATION_PATTERNS[region]:
                match = pattern.search(option_text)
                if match:
                    value = match.group(1).replace(",", ".")
                    try:
                        denomination = float(value)
                    except ValueError:
                        continue
                    currency = _REGION_CURRENCIES[region]
                    break
            if denomination is None or currency is None:
                continue
            available, availability_status, availability_reason = _gift_card_availability(
                listing, opt, option_text,
            )
            price, strong = select_real_price(opt.get("prices", []))
            if price is None:
                continue
            price_changed = opt.get("priceChanged")
            delta = option_price_delta(option_text)
            price = apply_delta_correction(
                option_text, price, price_changed=price_changed, initial_price=initial_price,
            )
            if opt.get("selectedAfter") is False:
                price_verified = False
                # Some Plati variants do not expose selected styling/ARIA.
                # A successful exact-control click followed by a stable,
                # changed RUB buy-block price is independent price-state proof.
                if opt.get("priceChanged") is True and opt.get("priceStable") is True and strong:
                    price_verified = True
            elif opt.get("priceVerified") is None:
                price_verified = bool(strong)
            else:
                price_verified = bool(opt.get("priceVerified"))
                # A visible surcharge plus the live initial buy-block price
                # independently accounts for the selected variant total when
                # the option click did not refresh the price block.
                if not price_verified and delta is not None and initial_price is not None and initial_strong:
                    price_verified = True
            text = f"{title} {page_text} {option_text}"
            delivery = "digital_code" if re.search(r"\b(?:code|key|код|ключ)\b", text, re.I) else "unknown"
            automatic = bool(re.search(r"auto(?:matic)?\s*[- ]?delivery|автовыдач|автоматическ\w*", text, re.I))
            yield {
                "marketplace": listing.get("marketplace"),
                "pid": str(listing.get("pid") or ""),
                "url": listing.get("url", ""),
                "title": title,
                "option_text": option_text.replace("\n", " | ")[:200],
                "raw_option_text": option_text,
                "control_kind": opt.get("kind"),
                "control_dom_index": opt.get("domIndex"),
                "control_input_id": opt.get("inputId"),
                "control_value": opt.get("value"),
                "region": region,
                "denomination": denomination,
                "denomination_currency": currency,
                "price_per_unit": price / denomination,
                "delivery": delivery,
                "automatic_delivery": automatic,
                "price_rub": price,
                "price_changed": price_changed,
                "price_delta": delta,
                "strong_signal": strong,
                "available": available,
                "availability_status": availability_status,
                "availability_reason": availability_reason,
                "price_verified": price_verified,
                "final_verified": False,
                "final_observed_price": None,
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
    eligible = [
        o for o in offers
        if family.matches_offer(o) and o.get("price_verified", True)
    ]
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
            if source_path.exists():
                raw_bytes = source_path.read_bytes()
                raw = json.loads(raw_bytes)
                f.write(f"Raw SHA-256: `{hashlib.sha256(raw_bytes).hexdigest()}`\n\n")
                context = raw.get("scanContext", {})
                if context:
                    headless = context.get("headless")
                    mode = "headless" if headless is True else "visible browser" if headless is False else "unknown"
                    counts = context.get("listingCounts", {})
                    f.write(
                        f"Collection: {mode}, {context.get('workers', 'unknown')} workers; "
                        f"Plati {counts.get('plati', 0)}, GGSEL {counts.get('ggsel', 0)} listings.\n\n"
                    )
                    if context.get("collectionCommand"):
                        f.write(f"Collection command: `{context['collectionCommand']}`\n\n")
                verification = raw.get("finalVerification", {})
                verified = sum(1 for item in verification.get("results", []) if item.get("verified"))
                status = "skipped" if verification.get("skipped") else f"{verified} winner(s) verified"
                f.write(f"Final browser verification: {status}.\n\n")
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
            for tier in ("Build", "Explore", "GO", "Ultra", "Max", "Pro+", "Pro 20X", "Pro 5X", "Pro", "Plus", "Lite"):
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
