"""Family-aware discovery: find candidate listings on Plati + GGSEL that
match a FamilyConfig. Replaces the MiniMax-specific minimax_discovery.py."""

from __future__ import annotations

import json
import os
import re
import site
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from families.base import FamilyConfig

DEFAULT_PLATI_API_URL = "https://api.digiseller.com/api/cataloguer/front/products"
DEFAULT_PLATI_BASE_URL = "https://plati.market"
DEFAULT_GGSEL_BASE_URL = "https://ggsel.net"
GGSEL_SEARCH_URL = f"{DEFAULT_GGSEL_BASE_URL}/search"
GGSEL_CATALOG_URL = f"{DEFAULT_GGSEL_BASE_URL}/catalog/{{category}}"


def _load_impit():
    try:
        from impit import Client
        return Client
    except ImportError:
        root = Path(__file__).resolve().parents[1]
        for site_path in (root / ".venv" / "lib").glob("python*/site-packages"):
            site.addsitedir(str(site_path))
        try:
            from impit import Client
            return Client
        except ImportError:
            return None


def request_json(url: str) -> tuple[dict, str]:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    client_type = _load_impit()
    if client_type is not None:
        try:
            with client_type(http3=True, browser="chrome", timeout=30) as client:
                resp = client.get(url, headers=headers)
            if resp.status_code < 200 or resp.status_code >= 300:
                raise RuntimeError(f"HTTP {resp.status_code}")
            return resp.json(), "impit-http3"
        except Exception:
            pass
    resp = urlopen(Request(url, headers=headers), timeout=30)
    return json.loads(resp.read().decode("utf-8")), "urllib-fallback"


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
    # Universal rejects: credits, top-ups, balance refills, API keys
    if re.search(r"audio|agent|credit|кредит|top\s*-?up|попол\w*|api\s*key", n):
        return False
    # Must mention at least one search term or family name
    terms = [normalise(t) for t in family.search_terms] + [family.name]
    if not any(term in n for term in terms):
        return False
    # Must mention a tier OR a duration marker (loose — covers monthly subs)
    has_plan = re.search(r"max|макс|plus|плюс|pro|про|lite|лайт|plan|тариф|подпис\w*", n)
    has_term = re.search(r"1\s*(?:month|месяц|мес)|1m\b|3\s*(?:month|месяц|мес)|12m|год|year|\d+\s*(?:month|месяц)", n)
    return bool(has_plan and has_term)


def discover_plati(family: FamilyConfig, max_results: int = 80) -> tuple[list[dict], str]:
    """Return (candidates, transport). Each candidate: {source, native_id,
    label, url, catalog_price_rub, seller, sales}."""
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
            payload, transport = request_json(f"{api_url}?{urlencode(params)}")
        except Exception as e:
            print(f"  plati search '{query}': {e}", file=__import__("sys").stderr)
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


def discover_ggsel(family: FamilyConfig, max_results: int = 80) -> tuple[list[dict], str]:
    """Discover GGSEL listings via category page (when known) + search."""
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ru-RU,ru;q=0.9"}
    seen: set[str] = set()
    out: list[dict] = []
    errors: list[str] = []

    # Strategy 1: known category page
    if family.ggssel_category:
        url = f"{DEFAULT_GGSEL_BASE_URL}/catalog/{family.ggssel_category}"
        try:
            body = urlopen(Request(url, headers=headers), timeout=30).read().decode("utf-8", "replace")
            for m in re.finditer(r'href="(/catalog/product/[a-z0-9-]+-(\d+))"', body):
                href, pid = m.group(1), m.group(2)
                if pid in seen:
                    continue
                seen.add(pid)
                # Extract nearby title
                title_match = re.search(r'title="([^"]{8,180})"', body[m.end():m.end()+800])
                title = title_match.group(1) if title_match else ""
                if title and not _candidate_matches_family(title, family):
                    continue
                out.append({
                    "source": "ggsel",
                    "native_id": pid,
                    "label": title,
                    "url": f"{DEFAULT_GGSEL_BASE_URL}{href}",
                    "catalog_price_rub": None,
                    "seller": None,
                    "sales": None,
                })
                if len(out) >= max_results:
                    break
        except Exception as e:
            errors.append(f"category {family.ggssel_category}: {e}")

    # Strategy 2: search API as fallback
    if len(out) < max_results:
        for query in family.search_terms[:2]:
            try:
                url = f"{GGSEL_SEARCH_URL}?text={query.replace(' ', '+')}"
                body = urlopen(Request(url, headers=headers), timeout=30).read().decode("utf-8", "replace")
                for m in re.finditer(r'href="(/catalog/product/[a-z0-9-]+-(\d+))"', body):
                    href, pid = m.group(1), m.group(2)
                    if pid in seen:
                        continue
                    seen.add(pid)
                    out.append({
                        "source": "ggsel",
                        "native_id": pid,
                        "label": "",
                        "url": f"{DEFAULT_GGSEL_BASE_URL}{href}",
                        "catalog_price_rub": None,
                        "seller": None,
                        "sales": None,
                    })
                    if len(out) >= max_results:
                        break
            except Exception as e:
                errors.append(f"search '{query}': {e}")
            if len(out) >= max_results:
                break

    return out, "; ".join(errors) if errors else "ok"


def discover_all(family: FamilyConfig, max_results: int = 80) -> dict:
    """Return full discovery result for both marketplaces."""
    plati, plati_t = discover_plati(family, max_results)
    ggsel, ggsel_e = discover_ggsel(family, max_results)
    return {
        "family": family.name,
        "candidates": plati + ggsel,
        "plati_found": len(plati),
        "ggsel_found": len(ggsel),
        "transports": {"plati": plati_t, "ggsel": ggsel_e},
        "errors": ([ggsel_e] if ggsel_e != "ok" else []),
    }


if __name__ == "__main__":
    import argparse
    from families import FAMILY_REGISTRY

    p = argparse.ArgumentParser()
    p.add_argument("--family", required=True, choices=list(FAMILY_REGISTRY))
    p.add_argument("--max", type=int, default=80)
    args = p.parse_args()
    result = discover_all(FAMILY_REGISTRY[args.family], args.max)
    print(json.dumps(result, indent=2, ensure_ascii=False))
