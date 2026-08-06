"""Optional Gemma4 sanity check for browser-collected offers.

Ported from minimax_max_prices.legacy.review_with_gemma and friends.
The browser-collected price is the source of truth; the LLM verdict is
a second opinion that flags mismatches (so a UI glitch or stale catalog
price doesn't slip through undetected).

Requires an OpenAI-compatible API. Defaults to the LLM_BASE_URL the
legacy code used; override via env / CLI."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Iterable

DEFAULT_LLM_BASE_URL = "https://llm.bezrabotnyi.com/v1"
DEFAULT_LLM_MODEL = "gemma4"

_LLM_PROMPT = """You are a price-detail validator. Given a marketplace
listing page excerpt, return JSON with these fields:
  product_family: short identifier (e.g. "minimax-token-plan", "glm-coding")
  tier: "Max" | "Pro+" | "Pro" | "Plus" | "Lite" | ""
  duration: "1m" | "3m" | "12m" | ""
  delivery: "own_account" | "new_account" | "shared_account" | "unknown"
  price_rub: integer RUB price as you read it, or 0 if unsure
  evidence: short quote (<=200 chars) supporting the price
Return ONLY the JSON object, no prose."""


def _extract_json(content: str) -> dict | None:
    content = content.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL | re.IGNORECASE)
    if m:
        content = m.group(1)
    else:
        s = content.find("{")
        e = content.rfind("}")
        if s >= 0 and e > s:
            content = content[s:e + 1]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def review_with_gemma(
    items: list[dict],
    api_key: str,
    base_url: str = DEFAULT_LLM_BASE_URL,
    model: str = DEFAULT_LLM_MODEL,
    timeout: int = 30,
) -> tuple[dict[str, dict], dict]:
    """Call Gemma4 (or any OpenAI-compatible model) once per item. Returns
    ({pid_url: review_dict}, meta). The browser-collected price is the
    source of truth; the LLM verdict is a sanity check."""
    meta = {"status": "ok", "model": model, "base_url": base_url, "called": 0, "failed": 0}
    reviews: dict[str, dict] = {}
    for item in items:
        if not item.get("url"):
            continue
        meta["called"] += 1
        try:
            verdict = _call_llm(item, api_key, base_url, model, timeout)
        except Exception as e:
            meta["failed"] += 1
            reviews[item["url"]] = {"error": str(e)}
            continue
        if verdict is None:
            meta["failed"] += 1
            reviews[item["url"]] = {"error": "non-JSON response"}
            continue
        reviews[item["url"]] = verdict
    return reviews, meta


def _call_llm(item: dict, api_key: str, base_url: str, model: str, timeout: int) -> dict | None:
    excerpt = (item.get("title") or "") + "\n\n" + (item.get("option_text") or "")
    if len(excerpt) > 1500:
        excerpt = excerpt[:1500]
    user_msg = f"Listing: {item.get('url', '')}\n\nExcerpt:\n{excerpt}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _LLM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
    }
    url = f"{base_url.rstrip('/')}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    return _extract_json(content)


_VALID_TIERS = {"Max", "Pro+", "Pro", "Plus", "Lite"}
_VALID_DELIVERY = {"own_account", "new_account", "shared_account"}


# Title-based fallback when both analyzer and LLM say "unknown". Most cheap
# marketplace listings without explicit "Требуется Вход" / "Upgrade" markers
# are pre-made accounts the seller activates on their own email.
_OWN_MARKERS = re.compile(
    r"обновлен\w*|продлен\w*|upgrade|renew|extend|"
    r"на\s*ваш\w*\s*аккаунт|со\s*входом|требуется\s*вход|"
    r"обновлен\w*\s*подписк|продлен\w*\s*подписк",
    re.I,
)


def _infer_delivery_unknown(item: dict) -> str:
    """Best-effort default for items both analyzer and LLM couldn't classify.
    If the title has own_account markers (e.g. "НА ВАШ АККАУНТ",
    "Требуется Вход"), infer own_account. Otherwise (most cheap
    marketplace listings without explicit own-account markers are
    pre-made accounts) infer new_account."""
    title = item.get("title", "") or ""
    if _OWN_MARKERS.search(title):
        return "own_account"
    return "new_account"


def apply_llm_reviews(items: list[dict], reviews: dict[str, dict], *, override_unknowns: bool = True) -> None:
    """Mutate each item in place: add llm_review + warning if mismatched.

    When override_unknowns=True (default) and the analyzer still left tier,
    duration or delivery as "unknown", the LLM verdict is applied (and a
    final heuristic inference kicks in for delivery when the LLM also said
    unknown — see _infer_delivery_unknown)."""
    for item in items:
        url = item.get("url", "")
        review = reviews.get(url)
        if review is None:
            continue
        item["llm_review"] = review
        error = review.get("error")
        if error:
            item["warning"] = f"Gemma returned error: {error}"
            continue
        llm_price = review.get("price_rub")
        try:
            llm_price_n = int(llm_price) if llm_price else 0
        except (TypeError, ValueError):
            llm_price_n = 0
        browser_price = item.get("price_rub")
        if llm_price_n and browser_price and abs(llm_price_n - browser_price) > 0.01 * max(llm_price_n, browser_price):
            item["warning"] = (
                f"Gemma reported {llm_price_n} ₽, browser shows {browser_price:.0f} ₽ (>10% delta)"
            )
        if override_unknowns:
            overrides = []
            llm_tier = review.get("tier", "")
            llm_dur = review.get("duration", "")
            llm_del = review.get("delivery", "")
            if item.get("tier") in ("", "unknown") and llm_tier in _VALID_TIERS:
                item["tier"] = llm_tier
                overrides.append(f"tier={llm_tier}")
            if item.get("duration") in ("", "unknown") and llm_dur in ("1m", "3m", "12m", "6m"):
                item["duration"] = llm_dur
                overrides.append(f"duration={llm_dur}")
            if item.get("delivery") in ("", "unknown") and llm_del in _VALID_DELIVERY:
                item["delivery"] = llm_del
                overrides.append(f"delivery={llm_del}")
            elif item.get("delivery") in ("", "unknown") and llm_del in ("unknown", "", None):
                # Both analyzer and LLM say unknown: apply title-based heuristic
                inferred = _infer_delivery_unknown(item)
                if inferred != "unknown":
                    item["delivery"] = inferred
                    overrides.append(f"delivery={inferred}*")
            if overrides:
                item["llm_overrode"] = True
                item["llm_overrode_fields"] = ",".join(overrides)
