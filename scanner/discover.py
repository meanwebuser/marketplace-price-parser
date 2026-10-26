"""Family-aware discovery: find candidate listings on Plati + GGSEL that
match a FamilyConfig.

Plati: scraped via the Digiseller API (no auth required).
GGSEL: scraped via Crawlee PlaywrightCrawler because the static HTML
behind Cloudflare returns 401 to plain HTTP and ImpitHttpClient.

Crawlee HTTP client options (per the crawlee docs):
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
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from families.base import FamilyConfig
from scanner.proxy_source import playwright_proxy_options

DEFAULT_PLATI_API_URL = "https://api.digiseller.com/api/cataloguer/front/products"
DEFAULT_PLATI_BASE_URL = "https://plati.market"
DEFAULT_GGSEL_BASE_URL = "https://ggsel.net"
GGSEL_CATEGORY_URL = f"{DEFAULT_GGSEL_BASE_URL}/catalog/{{category}}"
GGSEL_SEARCH_URL = f"{DEFAULT_GGSEL_BASE_URL}/search?text={{q}}"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Query variants are intentionally generic; never ship a dated listing-ID list
# as if it were a live marketplace inventory.
GIFT_CARD_QUERIES = {
    "US": ("Apple Gift Card USA", "Apple iTunes Gift Card USA", "Apple Gift Card US", "iTunes Gift Card US"),
}
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
    proxy_urls: tuple[str, ...] | list[str] = (),
) -> tuple[list[dict], str]:
    api_url = os.getenv("PLATI_API_URL", DEFAULT_PLATI_API_URL)
    base_url = os.getenv("PLATI_BASE_URL", DEFAULT_PLATI_BASE_URL).rstrip("/")
    seen: set[str] = set()
    out: list[dict] = []
    transport = "urllib-proxy" if proxy_urls else "urllib"

    def fetch_query(index: int, query: str) -> tuple[dict | None, str | None]:
        params = {
            "categoryId": "", "getProductsRecursive": "true",
            "sellerCategoryId": "", "productId": "",
            "productName": query, "ownerId": "plati",
            "ownerCategoryId": "", "sellerId": "", "sellerName": "",
            "currency": "RUB", "page": "1", "count": str(max_results),
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
            return payload, None
        except Exception as error:
            # Error strings can include proxy URLs/user-info. Keep evidence
            # useful without serializing any configured proxy value.
            failure = f"plati search '{query}': request failed" if proxy_urls else f"plati search '{query}': {error}"
            return None, failure

    indexed_queries = list(enumerate(family.search_terms))
    if proxy_urls and len(indexed_queries) > 1:
        with ThreadPoolExecutor(max_workers=min(2, len(indexed_queries), len(proxy_urls))) as pool:
            query_results = list(pool.map(lambda pair: fetch_query(*pair), indexed_queries))
    else:
        query_results = [fetch_query(index, query) for index, query in indexed_queries]

    for query, (payload, failure) in zip(family.search_terms, query_results):
        if failure:
            print(f"  {failure}", file=sys.stderr)
            if query_errors is not None:
                query_errors.append(failure)
            continue
        for item in (payload.get("content", {}) or {}).get("items", []) or []:
            label = name_from_locales(item)
            if not _candidate_matches_family(label, family):
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
) -> list[dict]:
    """Single PlaywrightCrawler category run. Other
    crawlers (HttpCrawler with ImpitHttpClient) return 401 because GGSEL
    is behind Cloudflare bot detection — only a real browser gets through."""
    from crawlee.crawlers import PlaywrightCrawler
    start_urls = []
    if family.ggssel_category:
        start_urls.append(GGSEL_CATEGORY_URL.format(category=family.ggssel_category))
    # GGSEL /search returns 404 (they removed the public search endpoint).
    # Curated family.ggsel_ids are merged by discover_ggsel, even when
    # the category is empty or unavailable.
    if not start_urls:
        return []
    products: list[dict] = []
    crawler_options = {
        "max_requests_per_crawl": len(start_urls),
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
            await ctx.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        body = await ctx.page.content()
        products.extend(_extract_ggsel_products(body, family))
    await crawler.run(start_urls)
    return products[:max_results]


def discover_ggsel(
    family: FamilyConfig,
    max_results: int = 80,
    *,
    request_failures: list[str] | None = None,
    proxy_urls: tuple[str, ...] | list[str] = (),
) -> tuple[list[dict], str]:
    """Merge category results with curated IDs, keeping live card metadata."""
    failures: list[str] = []
    try:
        products = asyncio.run(
            _ggsel_crawl_async(
                family, max_results, request_failures=failures, proxy_urls=proxy_urls
            )
        )
        transport = "playwright-partial" if failures else "playwright"
    except Exception as e:
        products = []
        transport = "playwright-proxy-error" if proxy_urls else f"playwright-error: {e}"
    if request_failures is not None:
        request_failures.extend(failures)
    merged = {str(p["native_id"]): p for p in products}
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
    return list(merged.values())[:max_results], transport


def discover_all(
    family: FamilyConfig,
    max_results: int = 80,
    *,
    proxy_urls: tuple[str, ...] | list[str] = (),
) -> dict:
    plati_query_errors: list[str] = []
    plati, plati_t = discover_plati(
        family, max_results, query_errors=plati_query_errors, proxy_urls=proxy_urls
    )
    ggsel_request_failures: list[str] = []
    ggsel, ggsel_t = discover_ggsel(
        family, max_results, request_failures=ggsel_request_failures,
        proxy_urls=proxy_urls,
    )
    errors = list(plati_query_errors)
    errors.extend(ggsel_request_failures)
    if ggsel_t.startswith("playwright-error"):
        errors.append(ggsel_t)
    return {
        "family": family.name,
        "candidates": plati + ggsel,
        "plati_found": len(plati),
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


async def _ggsel_gift_card_search_async(
    region: str,
    max_results: int,
    failures: list[str],
    proxy_urls: tuple[str, ...] | list[str] = (),
) -> list[dict]:
    """Search GGSEL's visible catalog search for query variants and load-more pages."""
    from crawlee import ConcurrencySettings, Request
    from crawlee.crawlers import PlaywrightCrawler

    queries = GIFT_CARD_QUERIES[region]
    crawler_options = {
        "max_requests_per_crawl": len(queries),
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
    found: dict[str, dict] = {}

    @crawler.failed_request_handler
    async def on_failure(ctx, error):
        if proxy_urls:
            failures.append("GGSEL gift-card query failed through configured proxy")
        else:
            failures.append(f"GGSEL gift-card query failed: {ctx.request.url}: {error}")

    @crawler.router.default_handler
    async def handle(ctx):
        query = str(ctx.request.user_data.get("gift_card_query", ""))
        try:
            search = ctx.page.get_by_placeholder(re.compile(r"Найти товар|Поиск по товарам", re.I)).first
            await search.fill(query)
            await search.press("Enter")
            await ctx.page.wait_for_load_state("domcontentloaded", timeout=10000)
            await ctx.page.wait_for_timeout(700)
            # Search results are progressively loaded. Stop at the bounded page
            # cap or when the visible show-more control disappears.
            for _ in range(6):
                for candidate in _extract_ggsel_gift_cards(await ctx.page.content(), region):
                    found.setdefault(candidate["native_id"], candidate)
                if len(found) >= max_results:
                    break
                more = ctx.page.get_by_role("button", name=re.compile(r"показать (?:больше|ещ[её])|load more", re.I)).first
                if await more.count() == 0 or not await more.is_visible():
                    break
                await more.click()
                await ctx.page.wait_for_timeout(500)
        except Exception as error:
            if proxy_urls:
                failures.append(f"GGSEL gift-card query {query!r} failed through configured proxy")
            else:
                failures.append(f"GGSEL gift-card query {query!r}: {error}")

    await crawler.run([
        Request.from_url(
            f"{DEFAULT_GGSEL_BASE_URL}/catalog?gift_card_query={index}",
            user_data={"gift_card_query": query},
        )
        for index, query in enumerate(queries)
    ])
    return list(found.values())[:max_results]


def discover_gift_cards(
    region: str = "US",
    max_results: int = 80,
    *,
    proxy_urls: tuple[str, ...] | list[str] = (),
) -> dict:
    """Search generic GGSEL queries for one region-locked Apple gift-card type."""
    region = str(region).upper()
    if region == "TR":
        return {
            "product": "apple_gift_card", "region": region, "candidates": [],
            "ggsel_found": 0, "queries": [], "transport": "not-collected",
            "errors": [], "coverage": "Turkey scan is intentionally deferred",
        }
    if region not in GIFT_CARD_QUERIES:
        raise ValueError(f"unsupported gift-card region {region!r}")
    failures: list[str] = []
    try:
        candidates = asyncio.run(
            _ggsel_gift_card_search_async(region, max_results, failures, proxy_urls)
        )
        transport = "playwright-search-partial" if failures else "playwright-search"
    except Exception as error:
        candidates = []
        failures.append("GGSEL gift-card search failed through configured proxy" if proxy_urls else str(error))
        transport = "playwright-proxy-error" if proxy_urls else f"playwright-error: {error}"
    return {
        "product": "apple_gift_card",
        "region": region,
        "candidates": candidates,
        "ggsel_found": len(candidates),
        "queries": list(GIFT_CARD_QUERIES[region]),
        "transport": transport,
        "errors": failures,
        "coverage": "visible catalog search query variants; bounded load-more pages, not exhaustive",
        "proxyMode": "configured" if proxy_urls else "direct",
        "proxyCount": len(proxy_urls),
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
