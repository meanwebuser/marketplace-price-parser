"""Opt-in uncertainty gate for the ChatGPT LLM analyzer.

The deterministic analyzer remains the baseline. Only listings with concrete
classification or capture uncertainty are sent to the existing LLM extractor.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from analyzer.price import (
    classify_delivery,
    classify_duration,
    classify_duration_from_title,
    classify_tier,
    parse_price,
    select_real_price,
)

_CHATGPT_RE = re.compile(r"\bchat\s*gpt\b|\bchatgpt\b|\bgpt\b", re.I)
_SUBSCRIPTION_RE = re.compile(
    r"подпис\w*|subscription|renew\w*|продлен\w*|обновлен\w*|активац\w*", re.I
)
_GENERIC_PURCHASE_RE = re.compile(
    r"^(?:купить(?:\s+сейчас)?|buy\s+now|заказать|оплатить|в\s+корзину)\b.*$",
    re.I | re.S,
)
_DELIVERY_VARIANT_RE = re.compile(
    r"ваш\w*\s*(?:аккаунт|акк|почт\w*)|нов\w*\s*аккаунт|созда\w*\s*аккаунт|"
    r"со?\s*входом|по\s*токену|shared\s*account|общ\w*\s*(?:аккаунт|доступ)",
    re.I,
)
_TIER_TOKEN_RE = re.compile(
    r"\bpro\s*(?:[xх]\s*(?:5|20)|(?:5|20)\s*[xх])?\b|\bpro\s*\+|"
    r"\bplus\b|\bgo\b|\bmax\b|\bultra\b|\blite\b|плюс|макс(?:имум)?|гоу",
    re.I,
)


def _listing_key(listing: dict) -> tuple[str, str]:
    return str(listing.get("marketplace") or ""), str(listing.get("pid") or "")


def _context_text(listing: dict) -> str:
    return " ".join(
        str(listing.get(name) or "")
        for name in ("title", "descText", "pageText")
    )


def _has_price_evidence(listing: dict) -> bool:
    groups = [listing.get("initialPrices") or []]
    groups.extend(option.get("prices") or [] for option in listing.get("options") or [])
    for group in groups:
        if any(parse_price(item.get("text", "")) is not None for item in group):
            return True
    return False


def _offer_like_option(text: str) -> bool:
    """A skipped control is relevant only if its own text resembles a variant."""
    value = str(text or "").strip()
    if not value or _GENERIC_PURCHASE_RE.match(value):
        return False
    # A currency amount by itself is usually a generic purchase button or an
    # upsell. Require a plan, term, or account-variant marker.
    return bool(classify_tier(value) or classify_duration(value) or _DELIVERY_VARIANT_RE.search(value))


def _offer_like_listing(listing: dict) -> bool:
    context = _context_text(listing)
    if not _CHATGPT_RE.search(context):
        return False
    has_subscription_shape = bool(
        classify_tier(context)
        or classify_duration(context)
        or _SUBSCRIPTION_RE.search(context)
    )
    has_capture = bool(
        _has_price_evidence(listing)
        or any(_offer_like_option((item or {}).get("text", ""))
               for item in listing.get("options") or [])
        or any(_offer_like_option((item or {}).get("text", ""))
               for item in listing.get("skippedControls") or [])
    )
    return has_subscription_shape and has_capture


def _option_is_offer_like(text: str, listing: dict) -> bool:
    context = _context_text(listing)
    return bool(
        _CHATGPT_RE.search(context)
        and (
            _offer_like_option(text)
            or (_SUBSCRIPTION_RE.search(text or "") and _DELIVERY_VARIANT_RE.search(text or ""))
        )
    )


def _has_conflicting_classification(text: str, listing: dict) -> bool:
    title = str(listing.get("title") or "")

    option_tier = classify_tier(text)
    title_tiers = {
        tier for match in _TIER_TOKEN_RE.finditer(title)
        if (tier := classify_tier(match.group(0)))
    }
    # Sellers commonly put several plans in one title and expose them as
    # separate variants; that is not a contradiction. Only a single explicit
    # title tier can conflict with the selected option.
    if option_tier and len(title_tiers) == 1 and option_tier not in title_tiers:
        return True
    option_duration = classify_duration(text)
    title_duration = classify_duration_from_title(title)
    if option_duration and title_duration and option_duration != title_duration:
        return True
    option_delivery = _resolved_delivery(text, listing)
    title_delivery = classify_delivery(title)
    return bool(
        option_delivery != "unknown"
        and title_delivery != "unknown"
        and option_delivery != title_delivery
    )


def listing_uncertainty_reasons(listing: dict, offers: list[dict]) -> list[str]:
    """Return stable reason codes; an empty list means deterministic is enough."""
    reasons: list[str] = []
    if listing.get("error"):
        reasons.append("collector_error")

    if not offers and _offer_like_listing(listing):
        reasons.append("no_deterministic_rows")

    for option in listing.get("options") or []:
        if not option.get("clicked") or option.get("available") is False:
            continue
        text = str(option.get("text") or "")
        if not _option_is_offer_like(text, listing):
            continue

        option_tier = classify_tier(text) or classify_tier(str(listing.get("title") or ""))
        option_duration = classify_duration(text) or classify_duration_from_title(
            str(listing.get("title") or "")
        )
        option_delivery = _resolved_delivery(text, listing)
        if not option_tier:
            reasons.append("unknown_tier")
        if not option_duration:
            reasons.append("unknown_duration")
        if option_delivery == "unknown":
            reasons.append("unknown_delivery")
        if _has_conflicting_classification(text, listing):
            reasons.append("contradictory_signals")

        price, strong = select_real_price(option.get("prices") or [])
        initial_price, _ = select_real_price(listing.get("initialPrices") or [])
        unstable = (
            option.get("priceStable") is False
            or option.get("priceVerified") is False
            or (price is None)
            or not strong
            or (
                option.get("priceChanged") is False
                and initial_price is not None
                and price is not None
                and price != initial_price
            )
        )
        if unstable:
            reasons.append("unstable_price")

    for item in listing.get("skippedControls") or []:
        text = str((item or {}).get("text") or "")
        if _offer_like_option(text) and _option_is_offer_like(text, listing):
            reasons.append("unparsed_offer_option")
            break

    # Preserve ordering while making route explanations deterministic.
    return list(dict.fromkeys(reasons))


def select_uncertain_listings(
    raw: dict,
    deterministic_offers: list[dict],
) -> tuple[list[dict], dict[tuple[str, str], list[str]]]:
    """Select raw listing objects that merit LLM review, with reason codes."""
    offers_by_listing: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for offer in deterministic_offers:
        offers_by_listing[(str(offer.get("marketplace") or ""), str(offer.get("pid") or ""))].append(offer)

    selected: list[dict] = []
    reasons_by_listing: dict[tuple[str, str], list[str]] = {}
    for listing in raw.get("listings", []):
        key = _listing_key(listing)
        reasons = listing_uncertainty_reasons(listing, offers_by_listing.get(key, []))
        if reasons:
            selected.append(listing)
            reasons_by_listing[key] = reasons
    return selected, reasons_by_listing


def _norm_option(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


def _resolved_delivery(text: str, listing: dict) -> str:
    return classify_delivery(
        text,
        str(listing.get("title") or ""),
        str(listing.get("descText") or ""),
        page_text=str(listing.get("pageText") or ""),
    )


def _classify_evidenced_tier(text: str) -> str:
    tier = classify_tier(text)
    if tier:
        return tier
    # The deterministic general parser does not classify ChatGPT GO yet, but
    # the selective merge can validate this explicit product label from raw UI.
    if re.search(r"\bgo\b|\bгоу\b", text or "", re.I):
        return "GO"
    return ""


def _tier_evidence(option_text: str, listing: dict) -> tuple[str, bool]:
    """Resolve a tier from the selected control and title, rejecting conflicts."""
    title = str(listing.get("title") or "")
    title_tiers = {
        tier for match in _TIER_TOKEN_RE.finditer(title)
        if (tier := _classify_evidenced_tier(match.group(0)))
    }
    option_tier = _classify_evidenced_tier(option_text)
    if option_tier:
        if title_tiers and option_tier not in title_tiers:
            return "", False
        return option_tier, True
    if len(title_tiers) == 1:
        return next(iter(title_tiers)), True
    return "", False


def _duration_evidence(option_text: str, listing: dict) -> tuple[str, bool]:
    """Resolve duration from raw option/title and reject contradictory terms."""
    option_duration = classify_duration(option_text)
    title_duration = classify_duration_from_title(str(listing.get("title") or ""))
    if option_duration and title_duration and option_duration != title_duration:
        return "", False
    resolved = option_duration or title_duration
    return resolved, bool(resolved)


def _matching_clicked_option(offer: dict, listing: dict) -> dict | None:
    option_key = _norm_option(offer.get("option_text", ""))
    return next((
        option for option in listing.get("options") or []
        if option.get("clicked") and _norm_option(option.get("text", "")) == option_key
    ), None)


def _llm_price_verified(offer: dict, listing: dict) -> bool:
    """Only retain a rankable LLM row when its price is tied to its raw option."""
    price = float(offer.get("price_rub") or 0)
    option_key = _norm_option(offer.get("option_text", ""))
    if option_key == "flat":
        if listing.get("options"):
            return False
        initial, strong = select_real_price(listing.get("initialPrices") or [])
        return bool(strong and initial == price)

    option = _matching_clicked_option(offer, listing)
    if option is None:
        return False
    if option.get("available") is False or option.get("disabled") or option.get("ariaDisabled"):
        return False
    selected, strong = select_real_price(option.get("prices") or [])
    return bool(
        strong
        and selected == price
        and option.get("priceStable") is not False
        and option.get("priceVerified") is not False
    )


def merge_selective_offers(
    deterministic_offers: list[dict],
    llm_offers: list[dict],
    selected_listings: list[dict],
) -> list[dict]:
    """Keep deterministic rows and accept only evidence-aligned LLM rows.

    A known, verified deterministic row is never replaced. An uncertain row
    may be upgraded only by an exact option match with the same captured price.
    """
    listings_by_key = {_listing_key(listing): listing for listing in selected_listings}
    merged: dict[tuple[str, str, str], dict] = {}
    for offer in deterministic_offers:
        key = (
            str(offer.get("marketplace") or ""),
            str(offer.get("pid") or ""),
            _norm_option(offer.get("raw_option_text") or offer.get("option_text", "")),
        )
        merged[key] = offer

    for candidate in llm_offers:
        if candidate.get("glitched"):
            continue
        if not all(candidate.get(field) not in (None, "", "unknown") for field in ("tier", "duration", "delivery")):
            continue
        listing_key = (str(candidate.get("marketplace") or ""), str(candidate.get("pid") or ""))
        listing = listings_by_key.get(listing_key)
        if listing is None:
            continue

        candidate = dict(candidate)
        verified_price = _llm_price_verified(candidate, listing)
        if not verified_price:
            continue
        option = _matching_clicked_option(candidate, listing)
        option_text = option.get("text", "") if option else ""
        raw_tier, tier_resolved = _tier_evidence(option_text, listing)
        raw_duration, duration_resolved = _duration_evidence(option_text, listing)
        if (
            not tier_resolved
            or not duration_resolved
            or candidate.get("tier") != raw_tier
            or candidate.get("duration") != raw_duration
        ):
            continue
        resolved_delivery = _resolved_delivery(option_text, listing)
        if resolved_delivery != "unknown" and candidate.get("delivery") != resolved_delivery:
            continue
        candidate["price_verified"] = verified_price
        candidate["strong_signal"] = bool(candidate.get("strong_signal"))

        key = (*listing_key, _norm_option(candidate.get("option_text", "")))
        existing = merged.get(key)
        if existing and (
            existing.get("tier")
            and existing.get("duration")
            and existing.get("delivery") != "unknown"
            and existing.get("price_verified") is not False
            and existing.get("strong_signal")
            and not existing.get("glitched")
        ):
            continue
        merged[key] = candidate
    return list(merged.values())
