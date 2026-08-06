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
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from families.base import FamilyConfig

DEFAULT_PLATI_API_URL = "https://api.digiseller.com/api/cataloguer/front/products"
DEFAULT_PLATI_BASE_URL = "https://plati.market"
DEFAULT_GGSEL_BASE_URL = "https://ggsel.net"
GGSEL_CATEGORY_URL = f"{DEFAULT_GGSEL_BASE_URL}/catalog/{{category}}"
GGSEL_SEARCH_URL = f"{DEFAULT_GGSEL_BASE_URL}/search?text={{q}}"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


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
    if re.search(r"audio|agent|credit|кредит|top\s*-?up|попол\w*|api\s*key", n):
        return False
    terms = [normalise(t) for t in family.search_terms] + [family.name]
    if not any(term in n for term in terms):
        return False
    has_plan = re.search(r"max|макс|plus|плюс|pro|про|lite|лайт|plan|тариф|подпис\w*", n)
    has_term = re.search(r"1\s*(?:month|месяц|мес)|1m\b|3\s*(?:month|месяц|мес)|12m|год|year|\d+\s*(?:month|месяц)", n)
    return bool(has_plan and has_term)


# ---- Plati discovery (no auth, GET API) ---------------------------------

def discover_plati(family: FamilyConfig, max_results: int = 80) -> tuple[list[dict], str]:
    api_url = os.getenv("PLATI_API_URL", DEFAULT_PLATI_API_URL)
    base_url = os.getenv("PLATI_BASE_URL", DEFAULT_PLATI_BASE_URL).rstrip("/")
    seen: set[str] = set()
    out: list[dict] = []
    transport = "urllib-fallback"
    for query in family.search_terms:
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
            with urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            transport = "urllib"
        except Exception as e:
            print(f"  plati search '{query}': {e}", file=sys.stderr)
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

def _extract_ggsel_products(html: str, family: FamilyConfig) -> list[dict]:
    """Extract unique product URLs from GGSEL page HTML, filter by family."""
    seen: set[str] = set()
    out: list[dict] = []
    for m in re.finditer(r'href="(/catalog/product/([a-z0-9-]+)-(\d+))"', html):
        href, slug, pid = m.group(1), m.group(2), m.group(3)
        if pid in seen:
            continue
        ctx = html[m.end():m.end()+800]
        title_match = re.search(r'title="([^"]{8,180})"', ctx)
        title = title_match.group(1) if title_match else ""
        if title and not _candidate_matches_family(title, family):
            seen.add(pid)
            continue
        seen.add(pid)
        out.append({
            "source": "ggsel",
            "native_id": pid,
            "label": title,
            "url": f"{DEFAULT_GGSEL_BASE_URL}{href}",
            "catalog_price_rub": None,
            "seller": None,
            "sales": None,
        })
    return out


async def _ggsel_crawl_async(family: FamilyConfig, max_results: int) -> list[dict]:
    """Single PlaywrightCrawler run: category + search fallback. Other
    crawlers (HttpCrawler with ImpitHttpClient) return 401 because GGSEL
    is behind Cloudflare bot detection — only a real browser gets through."""
    from crawlee.crawlers import PlaywrightCrawler
    start_urls = []
    if family.ggssel_category:
        start_urls.append(GGSEL_CATEGORY_URL.format(category=family.ggssel_category))
    # GGSEL /search returns 404 (they removed the public search endpoint).
    # Category page is the canonical discovery surface; fall back to
    # known URLs in family.ggsel_ids if it returns nothing.
    if not start_urls:
        return []
    products: list[dict] = []
    crawler = PlaywrightCrawler(
        max_requests_per_crawl=len(start_urls),
        browser_type="chromium",
        browser_launch_options={
            "executable_path": CHROME_PATH,
            "headless": True,
            "args": ["--no-sandbox"],
        },
    )
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


def discover_ggsel(family: FamilyConfig, max_results: int = 80) -> tuple[list[dict], str]:
    """Run Playwright-based GGSEL discovery. Returns (products, transport)."""
    try:
        products = asyncio.run(_ggsel_crawl_async(family, max_results))
        return products, "playwright"
    except Exception as e:
        return [], f"playwright-error: {e}"


def discover_all(family: FamilyConfig, max_results: int = 80) -> dict:
    plati, plati_t = discover_plati(family, max_results)
    ggsel, ggsel_t = discover_ggsel(family, max_results)
    return {
        "family": family.name,
        "candidates": plati + ggsel,
        "plati_found": len(plati),
        "ggsel_found": len(ggsel),
        "transports": {"plati": plati_t, "ggsel": ggsel_t},
        "errors": ([ggsel_t] if ggsel_t.startswith("playwright-error") else []),
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
