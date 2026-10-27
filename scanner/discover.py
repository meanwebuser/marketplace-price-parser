"""Family-aware discovery: find candidate listings on Plati + GGSEL that
match a FamilyConfig.

Plati: scraped via the Digiseller API (no auth required).
GGSEL category discovery uses Crawlee PlaywrightCrawler because category HTML
returns 401 to ordinary HTTP clients. Product-detail SSR option data is handled
separately by the fast Impit/curl_cffi collector, with Playwright fallback.

Crawlee HTTP client options:
  ImpitHttpClient            — browser-impersonating HTTP (impit)
  CurlImpersonateHttpClient  — curl-impersonate
  HttpxHttpClient            — plain httpx
  PlaywrightCrawler          — real browser for JS-rendered pages
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from families.base import FamilyConfig
from scanner.proxy_source import playwright_proxy_options, redact_proxy_details

DEFAULT_PLATI_API_URL = "https://api.digiseller.com/api/cataloguer/front/products"
DEFAULT_PLATI_BASE_URL = "https://plati.market"
DEFAULT_GGSEL_BASE_URL = "https://ggsel.net"
GGSEL_CATEGORY_URL = f"{DEFAULT_GGSEL_BASE_URL}/catalog/{{category}}"
GGSEL_SEARCH_URL = f"{DEFAULT_GGSEL_BASE_URL}/search?text={{q}}"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_GGSEL_DISCOVERY_LOCK = threading.Lock()

# Query variants are intentionally generic; never ship a dated listing-ID list
# as if it were a live marketplace inventory.
GIFT_CARD_QUERIES = {
    "US": ("Apple Gift Card USA", "Apple iTunes Gift Card USA", "Apple Gift Card US", "iTunes Gift Card US"),
}
GIFT_CARD_GGSEL_CATEGORIES = {"US": "itunes-10116"}
_GIFT_CARD_REGION_RE = {
    "US": re.compile(r"(?:\busa\b|\bunited states\b|\bu\.?s\.?\b|сша)", re.I),
    "TR": re.compile(r"(?:\bturkey\b|\bturkiye\b|\btürkiye\b|\btur\b|турц\w*)", re.I),
}


def normalise(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def name_from_locales(item: dict, locale: str = "ru-RU") -> str:
    names = item.get("name") if isinstance(item.get("name"), list) else []
    for n in names:
        if n.get("locale") == locale and n.get("value"):
            return str(n["value"])
    return next((str(n.get("value")) for n in names if n.get("value")), "")


def _candidate_matches_family(text: str, family: FamilyConfig) -> bool:
    """Loose keyword match — rejects obviously unrelated products, accepts
    anything that mentions the family or its search terms + a plan word."""
    n = normalise(text)
    if not n:
        return False
    if family.name == "zai":
        brand = re.search(r"\b(?:z[.\s-]*ai|glm|zhipu)\b|智谱", n)
        subscription = re.search(r"подпис\w*|subscription|coding\s*plan|тариф\w*", n)
        excluded = re.search(
            r"api\s*key|\bapi\b|top\s*-?up|попол\w*|\b(?:balance|credit|credits)\b|кредит\w*|баланс\w*",
            n,
        )
        # Search results often omit duration or the word "subscription" even
        # though the detail page exposes plan selectors. Keep mixed listings
        # when the title also advertises a subscription; the selected option
        # decides whether the captured variant is a subscription or top-up.
        return bool(brand and (subscription or not excluded))
    if family.name == "minimax":
        from families.minimax import is_subscription_candidate
        return is_subscription_candidate(n)
    if family.name == "kimi":
        from families.kimi import is_subscription
        if not is_subscription(n):
            return False
        has_plan = re.search(r"\b(?:plus|pro|max|ultra|плюс|про|макс|ультра)\b|subscription|подпис|тариф|plan", n)
        has_term = re.search(r"\b(?:1|3|6|12)\s*[mм]\b|month|мес|год|year|\b(?:30|90|180|365)\s*(?:дн|days)", n)
        return bool(has_plan and has_term)
    if re.search(r"audio|agent|credit|кредит|top\s*-?up|попол\w*|api\s*key", n):
        return False
    terms = [normalise(t) for t in family.search_terms] + [family.name]
    if not any(term in n for term in terms):
        return False
    has_plan = re.search(r"max|макс|plus|плюс|pro|про|lite|лайт|plan|тариф|подпис\w*", n)
    has_term = re.search(r"1\s*(?:month|месяц|мес)|1m\b|3\s*(?:month|месяц|мес)|12m|год|year|\d+\s*(?:month|месяц)", n)
    return bool(has_plan and has_term)


# ---- Plati discovery (no auth, GET API) ---------------------------------

def discover_plati(
    family: FamilyConfig,
    max_results: int = 80,
    *,
    query_errors: list[str] | None = None,
    max_pages: int = 6,
    max_total_results: int | None = None,
    coverage: dict | None = None,
    candidate_filter=None,
    proxy_urls: tuple[str, ...] | list[str] = (),
    http_workers: int = 2,
) -> tuple[list[dict], str]:
    api_url = os.getenv("PLATI_API_URL", DEFAULT_PLATI_API_URL)
    base_url = os.getenv("PLATI_BASE_URL", DEFAULT_PLATI_BASE_URL).rstrip("/")
    seen: set[str] = set()
    out: list[dict] = []
    transport = "urllib-proxy" if proxy_urls else "urllib"

    if max_results < 1 or max_pages < 1 or (max_total_results is not None and max_total_results < 1):
        raise ValueError("result limits and max_pages must be positive")
    # Digiseller rejects oversized `count` values (for example 1000) with
    # HTTP 400. Keep full-discovery candidate caps independent from page size.
    page_size = min(max_results, 80)

    def fetch_page(index: int, query: str, page: int) -> tuple[dict | None, str | None]:
        params = {
            "categoryId": "", "getProductsRecursive": "true",
            "sellerCategoryId": "", "productId": "",
            "productName": query, "ownerId": "plati",
            "ownerCategoryId": "", "sellerId": "", "sellerName": "",
            "currency": "RUB", "page": str(page), "count": str(page_size),
            "individual": "false", "video": "false", "image": "false",
            "attributes": "", "sortBy": "price-asc", "priceFrom": "", "priceTo": "",
            "includeAggregations": "true", "fuzzy": "false", "lang": "ru-RU",
        }
        try:
            url = f"{api_url}?{urlencode(params)}"
            req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            if proxy_urls:
                proxy = proxy_urls[index % len(proxy_urls)]
                opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
                response = opener.open(req, timeout=30)
            else:
                response = urlopen(req, timeout=30)
            with response as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("content"), dict) or not isinstance(payload["content"].get("items"), list):
                raise ValueError("invalid catalog response")
            return payload, None
        except Exception as error:
            # Error strings can include proxy URLs/user-info. Keep evidence
            # useful without serializing any configured proxy value.
            reason = redact_proxy_details(str(error), proxy_urls).strip()
            suffix = f": {reason}" if reason else " request failed"
            failure = f"plati search {query!r} page {page}: {type(error).__name__}{suffix}"
            return None, failure

    def fetch_query(index: int, query: str):
        items, failures = [], []
        info = {"query": query, "pagesFetched": 0, "itemsReceived": 0,
                "totalPages": None, "totalItems": None, "stopReason": "page_cap"}
        for page in range(1, max_pages + 1):
            payload, failure = fetch_page(index, query, page)
            if failure:
                failures.append(failure)
                info["stopReason"] = "error"
                break
            content = payload["content"]
            batch = content["items"]
            items.extend(batch)
            info["pagesFetched"] += 1
            info["itemsReceived"] += len(batch)
            for target, names in (("totalPages", ("total_pages", "totalPages")),
                                  ("totalItems", ("total_items", "totalItems", "total_count"))):
                value = next((content[key] for key in names if content.get(key) is not None), None)
                if value is not None:
                    try:
                        info[target] = max(0, int(value))
                    except (TypeError, ValueError):
                        pass
            has_next = content.get("has_next_page", content.get("hasNextPage"))
            if not batch or has_next is False or (info["totalPages"] is not None and page >= info["totalPages"]):
                info["stopReason"] = "exhausted"
                break
            if info["totalPages"] is None and has_next is None and len(batch) < max_results:
                info["stopReason"] = "short_page"
                break
        info["status"] = "failed" if not info["pagesFetched"] else "partial" if info["stopReason"] in {"error", "page_cap"} else "ok"
        info["errors"] = failures
        return items, info

    indexed_queries = list(enumerate(family.search_terms))
    query_workers = min(max(1, int(http_workers)), len(indexed_queries))
    if proxy_urls:
        query_workers = min(query_workers, len(proxy_urls))
    if query_workers > 1 and len(indexed_queries) > 1 and (proxy_urls or http_workers > 2):
        with ThreadPoolExecutor(max_workers=query_workers) as pool:
            query_results = list(pool.map(lambda pair: fetch_query(*pair), indexed_queries))
    else:
        query_results = [fetch_query(index, query) for index, query in indexed_queries]
    candidates_before_cap = 0
    if coverage is not None:
        infos = [info for _, info in query_results]
        coverage.update({"queries": infos, "pageSize": page_size, "maxPages": max_pages,
                         "pagesFetched": sum(info["pagesFetched"] for info in infos),
                         "status": "failed" if infos and all(info["status"] == "failed" for info in infos) else "partial" if any(info["status"] != "ok" for info in infos) else "ok"})
    for items, info in query_results:
        for failure in info["errors"]:
            print(f"  {failure}", file=sys.stderr)
            if query_errors is not None:
                query_errors.append(failure)
        for item in items:
            label = name_from_locales(item)
            if not (candidate_filter(label) if candidate_filter else _candidate_matches_family(label, family)):
                continue
            pid = str(item.get("product_id") or "")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            slug = item.get("name_url") or re.sub(r"[^a-z0-9]+", "-", normalise(label)).strip("-")
            out.append({
                "source": "plati",
                "native_id": pid,
                "label": label,
                "url": f"{base_url}/itm/{slug}/{pid}",
                "catalog_price_rub": float(item.get("price") or 0) or None,
                "seller": item.get("seller_name"),
                "sales": item.get("total_sales"),
            })
    candidates_before_cap = len(out)
    if max_total_results is not None and candidates_before_cap > max_total_results:
        out = out[:max_total_results]
        if coverage is not None:
            coverage["status"] = "partial"
            coverage["candidateLimit"] = max_total_results
            coverage["candidateCapReached"] = True
    elif coverage is not None and max_total_results is not None:
        coverage["candidateLimit"] = max_total_results
        coverage["candidateCapReached"] = False
    if coverage is not None:
        coverage["candidatesBeforeCap"] = candidates_before_cap
        coverage["candidatesReturned"] = len(out)
    return out, transport


# ---- GGSEL discovery via Crawlee PlaywrightCrawler --------------------

_GGSEL_PRODUCT_PATH_RE = re.compile(r"((?:/[a-z]{2})?/catalog/product/(?:([a-z0-9-]+)-)?(\d+))")
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _GGSELAnchorParser(HTMLParser):
    """Keep link evidence and its nearest GGSEL card separate from neighbors."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict] = []
        self.current: dict | None = None
        self.stack: list[tuple[str, dict | None]] = []

    def _current_card(self):
        return next((card for _, card in reversed(self.stack) if card is not None), None)

    @staticmethod
    def _is_card(attrs):
        if attrs.get("data-testid") == "card":
            return True
        # Match the product container, never a productList/leader-list wrapper.
        return any(
            (name.startswith("ProductCard-") and name.endswith("__card"))
            or (name.startswith("LeaderCard-") and name.endswith("__wrapper"))
            for name in (attrs.get("class") or "").split()
        )

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        card = {"titles": [], "text": [], "alts": [], "product_ids": set()} if self._is_card(attrs) else None
        if tag not in _VOID_TAGS:
            self.stack.append((tag, card))
        card = self._current_card()
        if tag == "a":
            href = attrs.get("href") or ""
            self.current = {"href": href, "titles": [], "text": [], "alts": [], "card": card}
            product = _GGSEL_PRODUCT_PATH_RE.fullmatch(href)
            if card is not None and product:
                card["product_ids"].add(product.group(3))
        for target in (self.current, card):
            if target is None:
                continue
            if attrs.get("title"):
                target["titles"].append(attrs["title"])
            if tag == "img" and attrs.get("alt"):
                target["alts"].append(attrs["alt"])

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)
        card = self._current_card()
        if card is not None:
            card["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.anchors.append(self.current)
            self.current = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if self.current is not None and not any(name == "a" for name, _ in self.stack):
            self.current = None


def _extract_ggsel_products(html: str, family: FamilyConfig) -> list[dict]:
    """Extract unique product URLs from GGSEL page HTML, filter by family."""
    seen: set[str] = set()
    out: list[dict] = []
    parser = _GGSELAnchorParser()
    parser.feed(html)
    for anchor in parser.anchors:
        m = _GGSEL_PRODUCT_PATH_RE.fullmatch(anchor["href"])
        if not m:
            continue
        href, slug, pid = m.group(1), m.group(2), m.group(3)
        if pid in seen:
            continue
        parts = [re.sub(r"\s+", " ", " ".join(anchor[key])).strip() for key in ("titles", "text", "alts")]
        candidates = parts + [" ".join(part for part in parts if part), (slug or "").replace("-", " ")]
        card = anchor.get("card")
        if card is not None and card["product_ids"] == {pid}:
            card_parts = [re.sub(r"\s+", " ", " ".join(card[key])).strip() for key in ("titles", "alts", "text")]
            card_text = " ".join(part for part in card_parts if part)
            if card_text:
                # Named card metadata is authoritative over an old slug. This
                # also prevents an API/top-up card borrowing subscription
                # identity from its URL or a nearby card.
                if not _candidate_matches_family(card_text, family):
                    continue
                candidates = card_parts + [card_text]
        candidate_text = next((text for text in candidates if _candidate_matches_family(text, family)), "")
        if not candidate_text:
            # A card can have separate empty image and named text anchors
            # with the same href. Deduplicate only after finding a match.
            continue
        seen.add(pid)
        out.append({
            "source": "ggsel",
            "native_id": pid,
            "label": candidate_text,
            "url": f"{DEFAULT_GGSEL_BASE_URL}{href}",
            "catalog_price_rub": None,
            "seller": None,
            "sales": None,
        })
    return out


async def _ggsel_crawl_async(
    family: FamilyConfig,
    max_results: int,
    *,
    request_failures: list[str] | None = None,
    proxy_urls: tuple[str, ...] | list[str] = (),
    max_pages: int = 6,
    coverage: dict | None = None,
) -> list[dict]:
    """Walk the matching GGSEL category and its load-more pages headlessly."""
    from crawlee import ConcurrencySettings, Request
    from crawlee.crawlers import PlaywrightCrawler
    category_url = GGSEL_CATEGORY_URL.format(category=family.ggssel_category) if family.ggssel_category else None
    if not category_url:
        return []
    request = Request.from_url(category_url)
    products: list[dict] = []
    seen: set[str] = set()
    info = {"query": category_url, "pagesFetched": 0, "status": "failed", "stopReason": "error"}
    crawler_options = {
        "max_requests_per_crawl": 1,
        "max_request_retries": 0,
        "retry_on_blocked": False,
        "use_session_pool": False,
        "request_handler_timeout": timedelta(minutes=5),
        "navigation_timeout": timedelta(seconds=30),
        "goto_options": {"wait_until": "domcontentloaded"},
        "concurrency_settings": ConcurrencySettings(
            min_concurrency=1, max_concurrency=1, desired_concurrency=1
        ),
        "browser_type": "chromium",
        "browser_launch_options": {
            "executable_path": CHROME_PATH,
            "headless": True,
            "args": ["--no-sandbox"],
        },
    }
    if proxy_urls:
        crawler_options["browser_new_context_options"] = {
            "proxy": playwright_proxy_options(proxy_urls[0])
        }
    crawler = PlaywrightCrawler(
        **crawler_options,
    )

    failures = request_failures if request_failures is not None else []

    @crawler.failed_request_handler
    async def handle_failed_request(ctx, error):
        if proxy_urls:
            failures.append("GGSEL request failed through configured proxy")
        else:
            failures.append(f"GGSEL request failed after retries: {ctx.request.url}: {error}")

    @crawler.router.default_handler
    async def handle(ctx):
        try:
            for page_number in range(1, max_pages + 1):
                try:
                    await ctx.page.wait_for_function(
                        "() => document.querySelector('a[href*=\"/catalog/product/\"]')",
                        timeout=10000,
                    )
                except Exception:
                    pass
                body = await ctx.page.content()
                for candidate in _extract_ggsel_products(body, family):
                    pid = str(candidate.get("native_id") or "")
                    if pid and pid not in seen:
                        seen.add(pid)
                        products.append(candidate)
                info["pagesFetched"] += 1
                if len(seen) >= max_results:
                    info.update(status="partial", stopReason="candidate_cap")
                    break
                more = ctx.page.get_by_role("button", name=re.compile(r"показать (?:больше|ещ[её])|load more|ещ[её]", re.I)).first
                if await more.count() and await more.is_visible():
                    if page_number == max_pages:
                        info.update(status="partial", stopReason="page_cap")
                        break
                    await more.click()
                    await ctx.page.wait_for_timeout(700)
                    continue
                info.update(status="ok", stopReason="exhausted")
                break
            else:
                info.update(status="partial", stopReason="page_cap")
        except Exception as error:
            info.update(status="partial" if info.get("pagesFetched") else "failed", stopReason="error")
            failures.append(f"GGSEL category discovery failed: {type(error).__name__}")
    await crawler.run([request])
    if coverage is not None:
        coverage.update({
            "queries": [info], "maxPages": max_pages,
            "pagesFetched": info["pagesFetched"],
            "candidateLimit": max_results,
            "candidateCapReached": info["stopReason"] == "candidate_cap",
            "status": info["status"],
            "candidatesBeforeCap": len(seen),
        })
    return products[:max_results]


def discover_ggsel(
    family: FamilyConfig,
    max_results: int = 80,
    *,
    request_failures: list[str] | None = None,
    proxy_urls: tuple[str, ...] | list[str] = (),
    max_pages: int = 6,
    coverage: dict | None = None,
    allow_direct_fallback: bool = False,
) -> tuple[list[dict], str]:
    """Merge category results with curated IDs, keeping live card metadata."""
    failures: list[str] = []
    attempts = list(proxy_urls[:5]) if proxy_urls else [None]
    if proxy_urls and allow_direct_fallback:
        attempts.append(None)
    products: list[dict] = []
    final_coverage: dict = {}
    attempts_used = 0
    for proxy in attempts:
        attempts_used += 1
        attempt_failures: list[str] = []
        attempt_coverage: dict = {}
        try:
            products = asyncio.run(
                _ggsel_crawl_async(
                    family, max_results, request_failures=attempt_failures,
                    proxy_urls=[proxy] if proxy else (),
                    max_pages=max_pages, coverage=attempt_coverage,
                )
            )
        except Exception as error:
            attempt_failures.append(f"GGSEL category discovery failed: {type(error).__name__}")
            attempt_coverage.update(status="failed", pagesFetched=0, maxPages=max_pages)
        final_coverage = attempt_coverage
        failures.extend(attempt_failures)
        if attempt_coverage.get("status") != "failed" or attempt_coverage.get("pagesFetched", 0) > 0:
            break
    category_coverage = dict(final_coverage)
    if coverage is not None:
        coverage.update(final_coverage)
        coverage["proxyAttempts"] = attempts_used
        coverage["directFallback"] = bool(proxy_urls and attempts_used > min(5, len(proxy_urls)) and final_coverage.get("status") != "failed")
    if final_coverage.get("status") == "failed":
        transport = "playwright-proxy-error" if proxy_urls else "playwright-error"
    else:
        transport = "playwright-partial" if final_coverage.get("status") == "partial" else "playwright"
        if proxy_urls and attempts_used > min(5, len(proxy_urls)):
            transport = "playwright-direct-fallback"
    merged = {str(p["native_id"]): p for p in products}
    category_ids = set(merged)
    search_coverage: dict = {}
    search_terms = list(getattr(family, "ggsel_search_terms", []) or [])
    search_ids: set[str] = set()
    if search_terms:
        try:
            searched = asyncio.run(_ggsel_search_async(
                family, search_terms, max_results=max_results,
                proxy_urls=proxy_urls[:1], max_pages=max_pages,
                coverage=search_coverage,
            ))
            for candidate in searched:
                candidate_id = str(candidate["native_id"])
                search_ids.add(candidate_id)
                merged.setdefault(candidate_id, candidate)
        except Exception as error:
            search_coverage.update(status="failed", error=type(error).__name__)
            failures.append(f"GGSEL search discovery failed: {type(error).__name__}")
    for curated in family.ggsel_ids:
        # Existing configs contain both numeric IDs and slug-ID paths.
        path = str(curated).strip()
        match = re.search(r"(?:^|-)(\d+)$", path)
        if not match:
            continue
        pid = match.group(1)
        if pid not in merged:
            merged[pid] = {
                "source": "ggsel", "native_id": pid, "label": "",
                "url": f"{DEFAULT_GGSEL_BASE_URL}/catalog/product/{path}",
                "catalog_price_rub": None, "seller": None, "sales": None,
            }
    if request_failures is not None:
        request_failures.extend(failures)
    if coverage is not None:
        coverage["category"] = category_coverage
        if search_terms:
            coverage["search"] = search_coverage
            coverage["combinedUniqueCandidates"] = len(merged)
            coverage["searchSupplement"] = {
                "uniqueCandidates": len(search_ids),
                "additionalListingsCaptured": len(search_ids - category_ids),
                "queries": search_coverage.get("queries", []),
                "categoryDiscoveryStatus": category_coverage.get("status", "unknown"),
                "coverageNote": "GGSEL rendered search aliases supplement the category; counts are not marketplace totals.",
            }
    return list(merged.values())[:max_results], transport


async def _ggsel_search_async(
    family: FamilyConfig,
    terms: list[str],
    *,
    max_results: int,
    proxy_urls: tuple[str, ...] | list[str] = (),
    max_pages: int = 6,
    coverage: dict | None = None,
) -> list[dict]:
    """Search GGSEL's rendered `/search/<term>` route for additional IDs.

    The regular category route is still collected first. Each search term gets
    its own page, and visible load-more is followed only while it adds new
    matching product IDs. This avoids treating recommendation cards or a
    category result count as an exhaustive marketplace inventory.
    """
    from crawlee import ConcurrencySettings, Request
    from crawlee.crawlers import PlaywrightCrawler

    queries = [str(term).strip() for term in terms if str(term).strip()]
    products: dict[str, dict] = {}
    query_info: list[dict] = []
    crawler_options = {
        "max_requests_per_crawl": len(queries),
        "max_request_retries": 0,
        "retry_on_blocked": False,
        "use_session_pool": False,
        "request_handler_timeout": timedelta(minutes=5),
        "navigation_timeout": timedelta(seconds=30),
        "goto_options": {"wait_until": "domcontentloaded"},
        "concurrency_settings": ConcurrencySettings(
            min_concurrency=1, max_concurrency=1, desired_concurrency=1
        ),
        "browser_type": "chromium",
        "browser_launch_options": {
            "executable_path": CHROME_PATH,
            "headless": True,
            "args": ["--no-sandbox"],
        },
    }
    if proxy_urls:
        crawler_options["browser_new_context_options"] = {
            "proxy": playwright_proxy_options(proxy_urls[0])
        }
    crawler = PlaywrightCrawler(**crawler_options)

    @crawler.router.default_handler
    async def handle(ctx):
        term = str(ctx.request.user_data.get("term") or "")
        info = {"term": term, "url": ctx.request.url, "pagesFetched": 0,
                "status": "failed", "stopReason": "error", "newCandidates": 0}
        query_info.append(info)
        before = len(products)
        try:
            for page_number in range(1, max_pages + 1):
                try:
                    await ctx.page.wait_for_function(
                        "() => document.querySelector('a[href*=\"/catalog/product/\"]')",
                        timeout=8000,
                    )
                except Exception:
                    pass
                before_content = await ctx.page.content()
                for candidate in _extract_ggsel_products(before_content, family):
                    products.setdefault(str(candidate["native_id"]), candidate)
                info["pagesFetched"] += 1
                if len(products) >= max_results:
                    info.update(status="partial", stopReason="candidate_cap")
                    break
                more = ctx.page.get_by_role(
                    "button", name=re.compile(r"показать (?:больше|ещ[её])|load more|ещ[её]", re.I)
                ).first
                if not await more.count() or not await more.is_visible():
                    info.update(status="ok", stopReason="exhausted")
                    break
                if page_number == max_pages:
                    info.update(status="partial", stopReason="page_cap")
                    break
                await more.click()
                await ctx.page.wait_for_timeout(1200)
                after_content = await ctx.page.content()
                if after_content == before_content:
                    info.update(status="partial", stopReason="load_more_no_page_change")
                    break
            if info["status"] == "failed":
                info.update(status="partial", stopReason="page_cap")
            info["newCandidates"] = len(products) - before
        except Exception as error:
            info.update(status="partial" if info["pagesFetched"] else "failed",
                         stopReason="error", error=type(error).__name__)

    @crawler.failed_request_handler
    async def failed(ctx, error):
        query_info.append({"term": ctx.request.user_data.get("term", ""),
                           "url": ctx.request.url, "pagesFetched": 0,
                           "status": "failed", "stopReason": "request_failed",
                           "error": type(error).__name__, "newCandidates": 0})

    requests = [Request.from_url(
        f"{DEFAULT_GGSEL_BASE_URL}/search/{quote(term, safe='')}",
        user_data={"term": term},
    ) for term in queries]
    if requests:
        await crawler.run(requests)
    if coverage is not None:
        coverage.update({"queries": query_info, "maxPages": max_pages,
                         "pagesFetched": sum(item["pagesFetched"] for item in query_info),
                         "status": "failed" if not query_info or all(item["status"] == "failed" for item in query_info)
                         else "partial" if any(item["status"] != "ok" for item in query_info) else "ok",
                         "candidatesReturned": len(products)})
    return list(products.values())[:max_results]


def discover_all(
    family: FamilyConfig,
    max_results: int = 80,
    *,
    proxy_urls: tuple[str, ...] | list[str] = (),
    http_workers: int = 2,
    max_pages: int = 6,
    max_candidates: int | None = None,
    allow_direct_fallback: bool = False,
) -> dict:
    plati_query_errors: list[str] = []
    plati_coverage: dict = {}
    ggsel_request_failures: list[str] = []
    ggsel_coverage: dict = {}

    def collect_plati():
        return discover_plati(
            family, max_results, query_errors=plati_query_errors, proxy_urls=proxy_urls,
            coverage=plati_coverage, http_workers=http_workers, max_pages=max_pages,
            max_total_results=max_candidates,
        )

    def collect_ggsel():
        # Crawlee/Playwright is not reliable when separate asyncio runners
        # launch Chromium concurrently from family worker threads. Keep its
        # single headless discovery browser serialized; Plati HTTP and later
        # collection continue in parallel under their separate budgets.
        with _GGSEL_DISCOVERY_LOCK:
            return discover_ggsel(
                family, max_candidates or max_results, request_failures=ggsel_request_failures,
                proxy_urls=proxy_urls, max_pages=max_pages, coverage=ggsel_coverage,
                allow_direct_fallback=allow_direct_fallback,
            )

    # The two marketplaces have independent discovery routes (Plati API and
    # GGSEL's rendered category). Overlap them per family to avoid waiting for
    # a slow category page after all Plati search terms have completed.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"discover-{family.name}") as pool:
        plati_future = pool.submit(collect_plati)
        ggsel_future = pool.submit(collect_ggsel)
        plati, plati_t = plati_future.result()
        ggsel, ggsel_t = ggsel_future.result()
    errors = list(plati_query_errors)
    errors.extend(ggsel_request_failures)
    if "error" in ggsel_t:
        errors.append("GGSEL category discovery failed" if proxy_urls else ggsel_t)
    return {
        "family": family.name,
        "candidates": plati + ggsel,
        "plati_found": len(plati),
        "coverage": {"plati": plati_coverage, "ggsel": ggsel_coverage},
        "ggselSearchSupplement": ggsel_coverage.get("searchSupplement"),
        "ggsel_found": len(ggsel),
        "transports": {
            "plati": plati_t,
            "platiQueryFailures": plati_query_errors,
            "ggsel": ggsel_t,
            "ggselRequestFailures": ggsel_request_failures,
        },
        "errors": errors,
        "proxyMode": "configured" if proxy_urls else "direct",
        "proxyCount": len(proxy_urls),
    }


def _extract_ggsel_gift_cards(html: str, region: str) -> list[dict]:
    """Extract Apple gift-card listings only when region is explicit in the card."""
    parser = _GGSELAnchorParser()
    parser.feed(html)
    seen: set[str] = set()
    out = []
    for anchor in parser.anchors:
        match = _GGSEL_PRODUCT_PATH_RE.fullmatch(anchor["href"])
        if not match:
            continue
        href, slug, pid = match.group(1), match.group(2), match.group(3)
        if pid in seen:
            continue
        parts = [" ".join(anchor[key]) for key in ("titles", "text", "alts")]
        card = anchor.get("card")
        if card is not None and card["product_ids"] == {pid}:
            parts.extend(" ".join(card[key]) for key in ("titles", "alts", "text"))
        evidence = normalise(" ".join([*parts, (slug or "").replace("-", " ")]))
        if not re.search(r"\b(?:apple|itunes)\b", evidence):
            continue
        if not _GIFT_CARD_REGION_RE[region].search(evidence):
            continue
        other_region = "TR" if region == "US" else "US"
        if _GIFT_CARD_REGION_RE[other_region].search(evidence):
            continue
        seen.add(pid)
        label = next((part.strip() for part in parts if re.search(r"apple|itunes", part, re.I)), evidence)
        out.append({
            "source": "ggsel", "native_id": pid, "label": label,
            "url": f"{DEFAULT_GGSEL_BASE_URL}{href}", "catalog_price_rub": None,
            "seller": None, "sales": None, "region": region,
        })
    return out


def _gift_card_matches_region(text: str, region: str) -> bool:
    text = normalise(text)
    other = "TR" if region == "US" else "US"
    return bool(re.search(r"\b(?:apple|itunes)\b", text)
                and _GIFT_CARD_REGION_RE[region].search(text)
                and not _GIFT_CARD_REGION_RE[other].search(text))


async def _ggsel_gift_card_search_async(
    region: str,
    max_results: int,
    failures: list[str],
    proxy_urls: tuple[str, ...] | list[str] = (),
    coverage: dict | None = None,
    max_pages: int = 6,
    allow_direct_fallback: bool = False,
) -> list[dict]:
    """Walk the Apple-cards catalog and retain only the requested region."""
    from crawlee import ConcurrencySettings, Request
    from crawlee.crawlers import PlaywrightCrawler
    category = GIFT_CARD_GGSEL_CATEGORIES.get(region)
    if not category:
        if coverage is not None:
            coverage.update(status="deferred", pagesFetched=0, maxPages=max_pages)
        return []
    category_url = GGSEL_CATEGORY_URL.format(category=category)
    proxy_attempts = list(proxy_urls[:5]) if proxy_urls else [None]
    if proxy_urls and allow_direct_fallback:
        proxy_attempts.append(None)
    final_found: dict[str, dict] = {}
    final_info: dict = {"query": f"category:{category}", "pagesFetched": 0,
                        "status": "failed", "stopReason": "error"}
    attempts_used = 0
    final_proxy = None
    for proxy in proxy_attempts:
        attempts_used += 1
        final_proxy = proxy
        found: dict[str, dict] = {}
        info = {"query": f"category:{category}", "pagesFetched": 0,
                "status": "failed", "stopReason": "error"}
        crawler_options = {
            "max_requests_per_crawl": 1,
            "max_request_retries": 0,
            "retry_on_blocked": False,
            "use_session_pool": False,
            "request_handler_timeout": timedelta(minutes=5),
            "navigation_timeout": timedelta(seconds=30),
            "goto_options": {"wait_until": "domcontentloaded"},
            "concurrency_settings": ConcurrencySettings(
                min_concurrency=1, max_concurrency=1, desired_concurrency=1
            ),
            "browser_type": "chromium",
            "browser_launch_options": {
                "executable_path": CHROME_PATH,
                "headless": True,
                "args": ["--no-sandbox"],
            },
        }
        if proxy:
            crawler_options["browser_new_context_options"] = {
                "proxy": playwright_proxy_options(proxy)
            }
        crawler = PlaywrightCrawler(**crawler_options)

        @crawler.failed_request_handler
        async def on_failure(ctx, error):
            info.update(status="failed", stopReason="request_failed")
            failures.append(f"GGSEL gift-card category failed: {type(error).__name__}")

        @crawler.router.default_handler
        async def handle(ctx):
            try:
                for page_number in range(1, max_pages + 1):
                    try:
                        await ctx.page.wait_for_function(
                            "() => document.querySelector('a[href*=\"/catalog/product/\"]')",
                            timeout=10000,
                        )
                    except Exception:
                        pass
                    info["pagesFetched"] += 1
                    for candidate in _extract_ggsel_gift_cards(await ctx.page.content(), region):
                        found.setdefault(candidate["native_id"], candidate)
                    if len(found) >= max_results:
                        info.update(status="partial", stopReason="candidate_cap")
                        break
                    previous_anchor_count = await ctx.page.locator('a[href*="/catalog/product/"]').count()
                    more = ctx.page.get_by_role(
                        "button", name=re.compile(r"показать (?:больше|ещ[её])|load more|ещ[её]", re.I)
                    ).first
                    if await more.count() and await more.is_visible():
                        if page_number == max_pages:
                            info.update(status="partial", stopReason="page_cap")
                            break
                        await more.click()
                        await ctx.page.wait_for_timeout(4000)
                        current_anchor_count = await ctx.page.locator('a[href*="/catalog/product/"]').count()
                        if current_anchor_count <= previous_anchor_count:
                            await ctx.page.wait_for_timeout(6000)
                            current_anchor_count = await ctx.page.locator('a[href*="/catalog/product/"]').count()
                        if current_anchor_count <= previous_anchor_count:
                            if await more.is_visible():
                                info.update(status="partial", stopReason="load_more_no_new_cards")
                            else:
                                info.update(status="ok", stopReason="exhausted")
                            break
                        continue
                    info.update(status="ok", stopReason="exhausted")
                    break
                else:
                    info.update(status="partial", stopReason="page_cap")
            except Exception as error:
                info.update(status="partial" if info["pagesFetched"] else "failed", stopReason="error")
                failures.append(f"GGSEL gift-card category {category!r}: {type(error).__name__}")

        try:
            await crawler.run([Request.from_url(category_url)])
        except Exception as error:
            info.update(status="failed", stopReason="request_failed")
            failures.append(f"GGSEL gift-card category failed: {type(error).__name__}")
        final_found, final_info = found, info
        if info["status"] != "failed" or info["pagesFetched"] > 0:
            break
    direct_supplement: dict = {}
    # A proxy can show a smaller or cached catalog page set while reporting
    # successful pagination. In full-search mode, cross-check the category
    # directly and union its candidate IDs rather than treating that response
    # as exhaustive by itself.
    if proxy_urls and allow_direct_fallback and final_proxy is not None and final_info.get("status") in {"ok", "partial"}:
        direct_found = await _ggsel_gift_card_search_async(
            region, max_results, failures, (), coverage=direct_supplement,
            max_pages=max_pages, allow_direct_fallback=False,
        )
        for candidate in direct_found:
            final_found.setdefault(candidate["native_id"], candidate)
        final_info = {
            **final_info,
            "queries": [*final_info.get("queries", []), *direct_supplement.get("queries", [])],
            "pagesFetched": final_info.get("pagesFetched", 0) + direct_supplement.get("pagesFetched", 0),
            "directSupplementCandidates": len(direct_found),
            "stopReason": direct_supplement.get("stopReason", "direct_supplement_partial"),
            "status": "ok" if direct_supplement.get("status") == "ok" else "partial",
        }
    if coverage is not None:
        coverage.update(queries=[final_info], pagesFetched=final_info["pagesFetched"], maxPages=max_pages,
                        status=final_info["status"], candidateLimit=max_results,
                        candidateCapReached=(final_info["stopReason"] == "candidate_cap"
                                             or direct_supplement.get("candidateCapReached", False)),
                        candidatesBeforeCap=len(final_found),
                        directFallback=bool(proxy_urls and allow_direct_fallback and (
                            attempts_used > min(5, len(proxy_urls))
                            or direct_supplement
                        )),
                        directSupplement=bool(direct_supplement),
                        directSupplementCandidates=direct_supplement.get("candidatesBeforeCap", 0),
                        proxyAttempts=attempts_used,
                        proxyPagesFetched=(final_info.get("pagesFetched", 0)
                                           - direct_supplement.get("pagesFetched", 0)) if proxy_urls else 0,
                        directPagesFetched=(direct_supplement.get("pagesFetched", 0)
                                             if direct_supplement else
                                             final_info.get("pagesFetched", 0) if not proxy_urls else 0))
    return list(final_found.values())[:max_results]


def discover_gift_cards(
    region: str = "US",
    max_results: int = 80,
    *,
    proxy_urls: tuple[str, ...] | list[str] = (),
    http_workers: int = 2,
    max_pages: int = 6,
    max_candidates: int | None = None,
    allow_direct_fallback: bool = False,
) -> dict:
    """Search both marketplaces for one region-locked Apple gift-card type."""
    region = str(region).upper()
    if region == "TR":
        return {
            "product": "apple_gift_card", "region": region, "candidates": [],
            "ggsel_found": 0, "plati_found": 0, "status": "deferred", "sources": {}, "queries": [], "transport": "not-collected",
            "errors": [], "coverage": "Turkey scan is intentionally deferred",
        }
    if region not in GIFT_CARD_QUERIES:
        raise ValueError(f"unsupported gift-card region {region!r}")
    plati_errors: list[str] = []
    plati_coverage: dict = {}
    gift_family = FamilyConfig(
        name="apple_gift_card", search_terms=list(GIFT_CARD_QUERIES[region]),
        purpose_preset="any", marketplaces=["plati", "ggsel"], tier_filter=[],
        duration_filter=[], delivery_filter=[],
    )
    candidate_limit = max_candidates if max_candidates is not None else max_results
    plati, plati_transport = discover_plati(
        gift_family, max_results, query_errors=plati_errors, proxy_urls=proxy_urls,
        max_total_results=candidate_limit, coverage=plati_coverage,
        http_workers=http_workers, max_pages=max_pages,
        candidate_filter=lambda label: _gift_card_matches_region(label, region),
    )
    for candidate in plati:
        candidate["region"] = region
    failures: list[str] = []
    ggsel_coverage: dict = {}
    try:
        ggsel = asyncio.run(
            _ggsel_gift_card_search_async(region, candidate_limit, failures, proxy_urls,
                                          coverage=ggsel_coverage, max_pages=max_pages,
                                          allow_direct_fallback=allow_direct_fallback)
        )
        ggsel_coverage.setdefault("status", "partial" if failures else "ok")
        transport = {"ok": "playwright-search", "partial": "playwright-search-partial",
                     "failed": "playwright-search-error"}[ggsel_coverage["status"]]
        if ggsel_coverage.get("directFallback"):
            transport = "playwright-search-direct-fallback"
    except Exception as error:
        ggsel = []
        failures.append(f"GGSEL gift-card search: {type(error).__name__} request failed")
        ggsel_coverage.update(status="failed", pagesFetched=0)
        transport = "playwright-search-error"
    sources = {"plati": plati_coverage, "ggsel": ggsel_coverage}
    statuses = [source["status"] for source in sources.values()]
    status = "failed" if all(value == "failed" for value in statuses) else "partial" if any(value != "ok" for value in statuses) else "ok"
    return {
        "product": "apple_gift_card", "region": region, "candidates": plati + ggsel,
        "plati_found": len(plati), "ggsel_found": len(ggsel),
        "queries": list(GIFT_CARD_QUERIES[region]), "status": status, "sources": sources,
        "transport": transport, "transports": {"plati": plati_transport, "ggsel": transport},
        "errors": plati_errors + failures,
        "coverage": "query variants on both marketplaces; exhaustive only when both source statuses are ok and no candidate/page cap was reached",
        "proxyMode": "configured" if proxy_urls else "direct", "proxyCount": len(proxy_urls),
    }


if __name__ == "__main__":
    import argparse
    from families import FAMILY_REGISTRY

    p = argparse.ArgumentParser()
    p.add_argument("--family", required=True, choices=list(FAMILY_REGISTRY))
    p.add_argument("--max", type=int, default=80)
    args = p.parse_args()
    result = discover_all(FAMILY_REGISTRY[args.family], args.max)
    print(json.dumps({k: v for k, v in result.items() if k != "candidates"}, indent=2, ensure_ascii=False))
    print(f"candidates: {len(result['candidates'])}")
    for c in result["candidates"][:5]:
        print(f"  [{c['source']}] {c['native_id']}  {c['url']}")
