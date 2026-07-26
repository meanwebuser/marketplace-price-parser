#!/usr/bin/env python3
"""Discover MiniMax subscription listings before browser detail parsing."""

from __future__ import annotations

import argparse
import json
import os
import re
import site
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
GGSEL_CRAWLER = ROOT / "minimax_browser_crawler.js"
DEFAULT_PLATI_API_URL = "https://api.digiseller.com/api/cataloguer/front/products"
DEFAULT_PLATI_BASE_URL = "https://plati.market"


def _load_impit():
    try:
        from impit import Client

        return Client
    except ImportError:
        for site_path in (ROOT / ".venv" / "lib").glob("python*/site-packages"):
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
                response = client.get(url, headers=headers)
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"HTTP {response.status_code}")
            negotiated = getattr(response, "http_version", "unknown")
            return response.json(), f"impit-http3-enabled/{negotiated}"
        except Exception as error:
            impit_error = error
        else:
            impit_error = None
    else:
        impit_error = ImportError("impit is not installed")

    response = urlopen(Request(url, headers=headers), timeout=30)
    if response.status < 200 or response.status >= 300:
        raise RuntimeError(f"HTTP {response.status}; impit error: {impit_error}")
    return json.loads(response.read().decode("utf-8")), "urllib-fallback"


def normalise(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def is_likely_minimax_candidate(text: str) -> bool:
    value = normalise(text)
    if not re.search(r"minimax|mini\s*max", value):
        return False
    if re.search(r"audio|agent|credit|кредит|top\s*-?up|попол\w*|api\s*key|\bm[23](?:\.\d+)?\b", value):
        return False
    has_plan = re.search(r"max|макс|plus|плюс|plan|тариф|подпис\w*|platform|api", value)
    has_term_or_subscription = re.search(r"1\s*(?:month|месяц|мес)|1m\b|подпис\w*|plan|тариф|platform|api", value)
    return bool(has_plan and has_term_or_subscription)


def plati_name(item: dict) -> str:
    names = item.get("name") if isinstance(item.get("name"), list) else []
    for name in names:
        if name.get("locale") == "ru-RU" and name.get("value"):
            return str(name["value"])
    return next((str(name.get("value")) for name in names if name.get("value")), "")


def discover_plati(query: str) -> tuple[list[dict], str]:
    api_url = os.getenv("MINIMAX_PLATI_API_URL", DEFAULT_PLATI_API_URL)
    base_url = os.getenv("MINIMAX_PLATI_BASE_URL", DEFAULT_PLATI_BASE_URL).rstrip("/")
    params = {
        "categoryId": "",
        "getProductsRecursive": "true",
        "sellerCategoryId": "",
        "productId": "",
        "productName": query,
        "ownerId": "plati",
        "ownerCategoryId": "",
        "sellerId": "",
        "sellerName": "",
        "currency": "RUB",
        "page": "1",
        "count": "100",
        "individual": "false",
        "video": "false",
        "image": "false",
        "attributes": "",
        "sortBy": "price-asc",
        "priceFrom": "",
        "priceTo": "",
        "includeAggregations": "true",
        "fuzzy": "false",
        "lang": "ru-RU",
    }
    payload, transport = request_json(f"{api_url}?{urlencode(params)}")
    items = payload.get("content", {}).get("items", [])
    candidates = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        name = plati_name(item)
        native_id = str(item.get("product_id") or "")
        if not native_id or native_id in seen or not is_likely_minimax_candidate(name):
            continue
        seen.add(native_id)
        slug = item.get("name_url") or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        candidates.append(
            {
                "source": "plati",
                "native_id": native_id,
                "label": name,
                "url": f"{base_url}/itm/{slug}/{native_id}",
                "catalog_price_rub": float(item.get("price") or 0) or None,
                "seller": item.get("seller_name"),
                "sales": item.get("total_sales"),
            }
        )
    return candidates, transport


def discover_ggsel() -> tuple[list[dict], dict]:
    environment = os.environ.copy()
    command = ["node", str(GGSEL_CRAWLER), "--discover-ggsel"]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, env=environment)
    if completed.returncode != 0:
        message = completed.stderr.strip() or "GGSEL discovery failed"
        raise RuntimeError(message)
    payload = json.loads(completed.stdout)
    return payload.get("candidates", []), payload.get("discovery", {})


def discover_marketplaces(query: str = "MiniMax", max_discovered: int = 30) -> tuple[list[dict], dict]:
    metadata = {
        "mode": "auto",
        "query": query,
        "plati_found": 0,
        "ggsel_found": 0,
        "candidates": 0,
        "errors": [],
        "http_client": "unknown",
    }
    candidates = []
    try:
        plati_candidates, transport = discover_plati(query)
        candidates.extend(plati_candidates)
        metadata["plati_found"] = len(plati_candidates)
        metadata["http_client"] = transport
    except Exception as error:
        metadata["errors"].append(f"plati: {error}")
    try:
        ggsel_candidates, ggsel_metadata = discover_ggsel()
        candidates.extend(ggsel_candidates)
        metadata["ggsel_found"] = len(ggsel_candidates)
        metadata["ggsel_category"] = ggsel_metadata.get("ggsel_category")
        metadata["errors"].extend(ggsel_metadata.get("errors", []))
    except Exception as error:
        metadata["errors"].append(f"ggsel: {error}")

    deduplicated = {}
    for candidate in candidates:
        key = f"{candidate.get('source')}:{candidate.get('native_id') or candidate.get('url')}"
        deduplicated[key] = candidate
    ordered = sorted(
        deduplicated.values(),
        key=lambda item: item.get("catalog_price_rub") if item.get("catalog_price_rub") is not None else float("inf"),
    )[: max(1, max_discovered)]
    metadata["candidates"] = len(ordered)
    return ordered, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=os.getenv("MINIMAX_SEARCH_QUERY", "MiniMax"))
    parser.add_argument("--max-discovered", type=int, default=30)
    args = parser.parse_args()
    candidates, metadata = discover_marketplaces(args.query, args.max_discovered)
    print(json.dumps({"discovery": metadata, "candidates": candidates}, ensure_ascii=False, indent=2))
    return 0 if candidates else 1


if __name__ == "__main__":
    sys.exit(main())
