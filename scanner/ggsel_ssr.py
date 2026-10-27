"""Fast, no-browser GGSEL detail collection from server-rendered option data.

Only explicit RUB base prices and RUB variant modifiers are accepted. Stock
fields are intentionally ignored; unsupported pages go to the Playwright
fallback in scanner.collect.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import unescape
from typing import Any
from urllib.parse import urlparse

from parsel import Selector

MAX_HTTP_WORKERS = 10
_ID_RE = re.compile(r"(\d+)(?:\D*)$")


def _product_data(html: str, expected_id: str) -> dict[str, Any] | None:
    selector = Selector(text=html)
    for script in selector.css("script"):
        text = "".join(script.xpath(".//text()").getall())
        if "price_brl" not in text or "options" not in text:
            continue
        start = text.find("{")
        if start < 0:
            continue
        try:
            payload, _ = json.JSONDecoder().raw_decode(text[start:])
        except (json.JSONDecodeError, TypeError):
            continue
        for query in payload.get("queries", []) if isinstance(payload, dict) else []:
            state = query.get("state") if isinstance(query, dict) else None
            data = state.get("data") if isinstance(state, dict) else None
            if not isinstance(data, dict) or data.get("price_brl") is None or not isinstance(data.get("options"), list):
                continue
            native_id = str(data.get("id_goods") or data.get("id") or "")
            expected_digits = _ID_RE.search(str(expected_id))
            actual_digits = _ID_RE.search(native_id)
            if expected_digits and actual_digits and expected_digits.group(1) != actual_digits.group(1):
                continue
            return data
    return None


def _plain_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = unescape(value)
    return " ".join(Selector(text=value).xpath("string(.)").get(default=value).split())


def _ggsel_url(candidate: dict[str, Any]) -> str | None:
    url = str(candidate.get("url") or f"https://ggsel.net/catalog/product/{candidate.get('native_id')}")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"ggsel.net", "www.ggsel.net"}:
        return None
    return url


def parse_ggsel_ssr_listing(html: str, candidate: dict[str, Any], *, checked_at: str) -> dict[str, Any] | None:
    """Normalize a supported GGSEL SSR product page without reading stock."""
    data = _product_data(html, str(candidate.get("native_id") or candidate.get("pid") or ""))
    if data is None:
        return None
    try:
        base_price = Decimal(str(data["price_brl"]))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return None
    if not base_price.is_finite() or base_price <= 0 or base_price > Decimal("1000000"):
        return None

    groups: list[tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]] = []
    for group in data.get("options", []):
        if not isinstance(group, dict):
            return None
        variants = group.get("variants")
        if not variants:
            continue
        if not isinstance(variants, list) or str(group.get("type", "radio")).lower() not in {"radio", "select"}:
            return None
        defaults = [variant for variant in variants if isinstance(variant, dict) and variant.get("default") is True]
        if len(defaults) != 1:
            return None
        default = defaults[0]
        if str(default.get("modify_type", "")).upper() != "RUB":
            return None
        try:
            default_modifier = Decimal(str(default.get("modify_value", "0")))
        except (InvalidOperation, TypeError, ValueError):
            return None
        # The base price is the proven page-load price. Non-zero default
        # modifiers make the site's effective-total convention ambiguous.
        if default_modifier != 0:
            return None
        groups.append((group, variants, default))
    if not groups:
        return None

    options = []
    default_selection = []
    for group, variants, default in groups:
        label = _plain_text(group.get("label") or group.get("name") or "").strip()
        default_text = _plain_text(str(default.get("text") or ""))
        if default_text:
            default_selection.append(default_text)
        for variant in variants:
            if not isinstance(variant, dict) or not variant.get("text"):
                return None
            if str(variant.get("modify_type", "")).upper() != "RUB":
                return None
            try:
                modifier = Decimal(str(variant.get("modify_value", "0")))
            except (InvalidOperation, TypeError, ValueError):
                return None
            total = (base_price + modifier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            if total <= 0 or total > Decimal("1000000"):
                return None
            variant_text = _plain_text(str(variant["text"]))
            text = variant_text
            options.append({
                "kind": "select-option" if str(group.get("type")).lower() == "select" else "button",
                "text": text,
                "value": variant.get("value"),
                "clicked": False,
                "priceVerified": True,
                "priceEvidenceMethod": "ggsel_ssr_modifier",
                "priceEvidence": {
                    "checkedAt": checked_at,
                    "basePriceRub": float(base_price),
                    "modifierRub": float(modifier),
                    "totalPriceRub": float(total),
                    "variantValue": str(variant.get("value", "")),
                    "groupLabel": label,
                },
                "prices": [{"text": f"{total:.0f} ₽", "cls": "id_product_price"}],
            })

    title = _plain_text(str(data.get("name") or candidate.get("label") or ""))
    description = " ".join(filter(None, (_plain_text(str(data.get("info") or "")),
                                         _plain_text(str(data.get("add_info") or "")))))
    page_text = " ".join(filter(None, (description, *default_selection)))
    url = _ggsel_url(candidate)
    if not url:
        return None
    return {
        "marketplace": "ggsel",
        "pid": str(candidate.get("native_id") or candidate.get("pid") or data.get("id_goods") or ""),
        "url": url,
        "title": title,
        "template": "ggsel_ssr_http",
        "initialPrices": [{"text": f"{format(base_price, 'f')} ₽", "cls": "id_product_price"}],
        "pageText": page_text,
        "descText": description,
        "options": options,
        "priceCollectionMethod": "ggsel_ssr_modifier",
        "priceCheckedAt": checked_at,
        "availabilityNotChecked": True,
    }


async def collect_ggsel_ssr(
    candidates: list[dict[str, Any]],
    *,
    workers: int = MAX_HTTP_WORKERS,
    proxy_urls: list[str] | tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Fetch GGSEL pages concurrently with Impit, then curl_cffi fallback.

    Returns (collected, browser_fallback, transport_counts). No stock or
    availability fields are read from the response or written to raw data.
    """
    if not candidates:
        return [], [], {"impit": 0, "curl_cffi": 0, "browser_fallback": 0}
    workers = max(1, min(int(workers), MAX_HTTP_WORKERS))
    checked_at = datetime.now(timezone.utc).isoformat()
    proxy_list = list(proxy_urls)
    impit_results: list[tuple[dict[str, Any], dict[str, Any] | None, str, bool]] = []
    from impit import AsyncClient

    async with AsyncClient(browser="chrome", timeout=20, follow_redirects=True) as client:
        semaphore = asyncio.Semaphore(workers)

        async def fetch(candidate: dict[str, Any], index: int) -> None:
            async with semaphore:
                url = _ggsel_url(candidate)
                if not url:
                    impit_results.append((candidate, None, "", False))
                    return
                proxy = proxy_list[index % len(proxy_list)] if proxy_list else None
                try:
                    response = await client.get(url, **({"proxy": proxy} if proxy else {}))
                    parsed = parse_ggsel_ssr_listing(response.text, candidate, checked_at=checked_at) if response.status_code == 200 else None
                    retry_with_curl = response.status_code == 200 or response.status_code in {401, 403, 429} or response.status_code >= 500
                    impit_results.append((candidate, parsed, "impit" if parsed else "", retry_with_curl))
                except Exception:
                    impit_results.append((candidate, None, "", True))

        await asyncio.gather(*(fetch(candidate, index) for index, candidate in enumerate(candidates)))

    collected = [listing for _, listing, transport, _ in impit_results if listing and transport == "impit"]
    remaining = [(candidate, index) for index, (candidate, listing, _, retry_with_curl) in enumerate(impit_results)
                 if listing is None and retry_with_curl]
    direct_fallback = [candidate for candidate, listing, _, retry_with_curl in impit_results
                       if listing is None and not retry_with_curl]
    curl_results: dict[int, dict[str, Any] | None] = {}
    if remaining:
        try:
            from curl_cffi.requests import AsyncSession
            async with AsyncSession(max_clients=workers, impersonate="chrome", timeout=20, allow_redirects=True) as session:
                semaphore = asyncio.Semaphore(workers)

                async def retry(candidate: dict[str, Any], index: int) -> None:
                    async with semaphore:
                        url = _ggsel_url(candidate)
                        if not url:
                            curl_results[index] = None
                            return
                        proxy = proxy_list[index % len(proxy_list)] if proxy_list else None
                        kwargs = {"proxies": {"http": proxy, "https": proxy}} if proxy else {}
                        try:
                            response = await session.get(url, **kwargs)
                            curl_results[index] = parse_ggsel_ssr_listing(response.text, candidate, checked_at=checked_at) if response.status_code == 200 else None
                        except Exception:
                            curl_results[index] = None

                await asyncio.gather(*(retry(candidate, index) for candidate, index in remaining))
        except ImportError:
            curl_results = {}

    browser_fallback = list(direct_fallback)
    curl_count = 0
    for candidate, index in remaining:
        listing = curl_results.get(index)
        if listing:
            collected.append(listing)
            curl_count += 1
        else:
            browser_fallback.append(candidate)
    impit_count = sum(1 for _, listing, transport, _ in impit_results if listing and transport == "impit")
    return collected, browser_fallback, {"impit": impit_count, "curl_cffi": curl_count, "browser_fallback": len(browser_fallback)}
