"""Fast Plati variant-price collection using its selected-option price endpoint."""

from __future__ import annotations

import asyncio
import itertools
import re
import sys
import time
from html import escape
from typing import Sequence

from parsel import Selector

PLATI_PRICE_METHOD = "plati_price_options"
PLATI_CATALOG_METHOD = "plati_catalog_price"
PLATI_PRICE_URL = "https://plati.market/asp/price_options.asp"
_BLOCKED_TITLE = re.compile(r"DDoS[- ]Guard|Access Denied|Attention Required|Just a moment", re.I)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _controls(selector: Selector) -> list[dict]:
    labels = {
        label.attrib.get("for", ""): label
        for label in selector.xpath('//label[contains(@for,"Selected2Option_")]')
        if label.attrib.get("for")
    }
    controls = []
    for node in selector.xpath('//input[contains(@id,"Selected2Option_")]'):
        input_id = node.attrib.get("id", "")
        group_match = re.search(r"Option_select_(\w+)$", node.attrib.get("name", ""))
        value = node.attrib.get("value", "")
        label = labels.get(input_id)
        text = _clean(" ".join(label.xpath(".//text()").getall())) if label is not None else ""
        text = re.sub(r"\bВыбран\b", "", text, flags=re.I).strip()
        if not (group_match and value and text):
            continue
        controls.append({
            "kind": "label", "text": text, "inputId": input_id,
            "inputName": node.attrib.get("name"), "value": value,
            "groupId": group_match.group(1), "selected": "checked" in node.attrib,
        })
    return controls


def _page_metadata(candidate: dict, html: str) -> tuple[dict, list[dict]]:
    selector = Selector(text=html)
    page_title = _clean(selector.css("title::text").get() or "")
    title = " | ".join(dict.fromkeys(filter(None, (page_title, _clean(candidate.get("label"))))))
    if _BLOCKED_TITLE.search(title):
        raise ValueError("blocked detail page")
    controls = _controls(selector)
    page_text = _clean(" ".join(selector.xpath("//body//text()").getall()))[:6000]
    desc_parts = []
    for node in selector.css('[itemprop="description"], [class*="escription"], [id*="escription"], [class*="desc"]'):
        text = _clean(" ".join(node.xpath(".//text()").getall()))
        if len(text) > 40 and text not in desc_parts:
            desc_parts.append(text)
    return {
        "marketplace": "plati", "pid": str(candidate.get("native_id") or ""),
        "url": candidate.get("url") or f"https://plati.market/itm/{candidate.get('native_id')}",
        "title": title, "template": "plati-http-options", "pageText": page_text,
        "descText": "\n---\n".join(desc_parts[:5])[:5000],
        "initialPrices": [], "options": [], "skippedControls": [],
        "variantControlCount": len(controls),
        "availabilityNotChecked": True,
    }, controls


class _ProxyCursor:
    def __init__(self, values: Sequence[str]):
        self.values = tuple(values)
        self._counter = itertools.count()

    def next(self, offset: int = 0) -> str | None:
        if not self.values:
            return None
        return self.values[(next(self._counter) + offset) % len(self.values)]


async def collect_plati_http(
    candidates: Sequence[dict], *, workers: int = 10,
    proxy_urls: Sequence[str] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """Collect option totals through Plati's XHR endpoint; return browser fallbacks.

    Only price and option metadata are read. Availability/stock is left unknown.
    Proxy addresses remain in memory and are never part of the returned rows.
    """
    from curl_cffi.requests import AsyncSession

    concurrency = max(1, min(int(workers), 10))
    proxies = tuple(proxy_urls or ())
    proxy_cursor = _ProxyCursor(proxies)
    semaphore = asyncio.Semaphore(concurrency)
    counts = {"pageRequests": 0, "optionRequests": 0, "priceOptions": 0, "failedOptions": 0}
    completed_pages = 0

    async with AsyncSession() as session:
        async def get(url: str, *, params: dict | None = None, referer: str | None = None):
            last_error = None
            attempts = min(3, max(1, len(proxies)))
            for attempt in range(attempts):
                proxy = proxy_cursor.next(attempt)
                headers = {"Accept": "text/html,application/json, text/javascript, */*; q=0.01",
                           "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"}
                if referer:
                    headers["Referer"] = referer
                    headers["X-Requested-With"] = "XMLHttpRequest"
                try:
                    async with semaphore:
                        response = await session.get(
                            url, params=params, headers=headers, proxy=proxy,
                            timeout=8, impersonate="chrome",
                        )
                    if response.status_code in {401, 403, 429, 503}:
                        last_error = f"HTTP {response.status_code}"
                        continue
                    if response.status_code >= 400:
                        last_error = f"HTTP {response.status_code}"
                        continue
                    return response
                except Exception as error:  # network/proxy failures are retried via a different proxy
                    last_error = type(error).__name__
            raise RuntimeError(last_error or "request failed")

        async def one(candidate: dict) -> tuple[dict | None, dict | None]:
            nonlocal completed_pages
            pid = str(candidate.get("native_id") or "")
            if not pid:
                completed_pages += 1
                return None, candidate
            url = candidate.get("url") or f"https://plati.market/itm/{pid}"
            try:
                page_response = await get(url)
                counts["pageRequests"] += 1
                listing, controls = _page_metadata(candidate, page_response.text)
            except Exception:
                completed_pages += 1
                if completed_pages % 10 == 0 or completed_pages == len(candidates):
                    print(f"[plati-http] {completed_pages}/{len(candidates)} pages; "
                          f"{counts['priceOptions']} option prices; fallback pending", file=sys.stderr, flush=True)
                return None, candidate

            defaults: dict[str, str] = {}
            for control in controls:
                if control["selected"] or control["groupId"] not in defaults:
                    defaults[control["groupId"]] = control["value"]

            async def price_option(control: dict) -> dict:
                selections = dict(defaults)
                if control.get("groupId"):
                    selections[control["groupId"]] = control["value"]
                option_xml = "<response>" + "".join(
                    f'<option O="{escape(group, quote=True)}" V="{escape(value, quote=True)}"/>'
                    for group, value in selections.items()
                ) + "</response>"
                params = {
                    "p": pid, "n": "0", "c": "RUB", "d": "true",
                    "x": option_xml, "rnd": str(time.time_ns() // 1_000_000),
                }
                try:
                    counts["optionRequests"] += 1
                    response = await get(PLATI_PRICE_URL, params=params, referer=url)
                    data = response.json()
                    amount = float(data.get("amount"))
                    if data.get("err") not in {0, "0"} or str(data.get("curr", "")).upper() != "RUB" or amount <= 0:
                        raise ValueError("price endpoint did not confirm a RUB amount")
                    counts["priceOptions"] += 1
                    evidence = {
                        "sourcePath": "/asp/price_options.asp", "productId": pid,
                        "optionGroupId": control.get("groupId"), "optionValueId": control.get("value"),
                        "amountRub": amount, "currency": "RUB", "error": str(data.get("err")),
                    }
                    return {
                        **control, "kind": control.get("kind", "fixed-price"),
                        "text": control.get("text") or listing["title"],
                        "clicked": False, "selectedAfter": None,
                        "priceEvidenceMethod": PLATI_PRICE_METHOD,
                        "priceVerified": True, "priceEvidence": evidence,
                        "prices": [{"text": f"{amount:g} ₽", "cls": "id_product_price"}],
                        "availabilityNotChecked": True,
                    }
                except Exception:
                    counts["failedOptions"] += 1
                    raise

            controls_to_price = controls or [{
                "kind": "fixed-price", "text": listing["title"],
                "selected": True, "groupId": None, "value": None,
            }]
            try:
                listing["options"] = await asyncio.gather(*(price_option(control) for control in controls_to_price))
            except Exception:
                # A search-catalog price is useful context, but is not exact
                # buy-block evidence; retain it as unverified and never rank it.
                catalog_price = candidate.get("catalog_price_rub")
                if not controls and catalog_price is not None and float(catalog_price) > 0:
                    listing["initialPrices"] = [{
                        "text": f"{float(catalog_price):g} ₽", "cls": "catalog_search_price"
                    }]
                    listing["catalogPriceRub"] = float(catalog_price)
                    listing["priceEvidenceMethod"] = PLATI_CATALOG_METHOD
                    listing["options"] = [{
                        "kind": "fixed-price", "text": listing["title"],
                        "clicked": False, "selectedAfter": None, "priceVerified": False,
                        "priceEvidenceMethod": PLATI_CATALOG_METHOD,
                        "priceEvidence": {
                            "sourcePath": "digiseller_catalog_search", "productId": pid,
                            "catalogPriceRub": float(catalog_price), "currency": "RUB",
                        },
                        "prices": [{"text": f"{float(catalog_price):g} ₽", "cls": "catalog_search_price"}],
                        "availabilityNotChecked": True,
                    }]
                    completed_pages += 1
                    return listing, None
                completed_pages += 1
                if completed_pages % 10 == 0 or completed_pages == len(candidates):
                    print(f"[plati-http] {completed_pages}/{len(candidates)} pages; "
                          f"{counts['priceOptions']} option prices; fallback pending", file=sys.stderr, flush=True)
                return None, candidate
            # The selected option's exact server-side amount is also the only
            # reliable initial total exposed by this endpoint.
            selected = next((o for o in listing["options"] if o.get("selected")), None)
            if selected:
                listing["initialPrices"] = list(selected["prices"])
            completed_pages += 1
            if completed_pages % 10 == 0 or completed_pages == len(candidates):
                print(f"[plati-http] {completed_pages}/{len(candidates)} pages; "
                      f"{counts['priceOptions']} option prices; {counts['failedOptions']} endpoint failures",
                      file=sys.stderr, flush=True)
            return listing, None

        results = await asyncio.gather(*(one(candidate) for candidate in candidates))
    listings = [listing for listing, fallback in results if listing is not None]
    fallbacks = [fallback for listing, fallback in results if fallback is not None]
    return listings, fallbacks, counts
