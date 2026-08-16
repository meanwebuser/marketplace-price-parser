"""LLM-as-analyzer (pass 2): classify every offer with a batched LLM call
over evidence packs instead of regex heuristics.

Each batch is one independent chat completion (~24 KB ≈ ~9K tokens), so
the scan never accumulates context across listings. Regex analyzer stays
the offline fallback; deterministic guards (glitch detector, per-family
price floors) still run on LLM output — the LLM reads text, the guards
catch hallucinated or stale prices."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from analyzer.evidence import build_pack, build_batches
from analyzer.price import is_glitched
from analyzer.llm import _extract_json

DEFAULT_LLM_BASE_URL = "https://llm.bezrabotnyi.com/v1"
DEFAULT_LLM_MODEL = "gemma4"

VALID_DURATIONS = {"1m", "3m", "6m", "12m"}
VALID_DELIVERIES = {"own_account", "new_account", "shared_account", "unknown"}

SYSTEM_PROMPT = """You classify marketplace listings for ChatGPT-family subscriptions. \
For every listing in the input JSON array return classified rows.

Input listing fields: pid, mp, url, title, desc (seller description), page \
(product-area text), opts (variant chips: t=text, c=clicked, strong=buy-block \
price in RUB after clicking this chip, p=other prices seen on page), skipped \
(variant-looking chips the collector did not click), init_strong/init (listing \
buy-block prices before any click), err.

Rules:
- One row per real purchasable subscription variant. opts entries with c=1 \
usually have their own price: prefer that option's strong price. If an opt \
text contains "+N ₽" (a surcharge over the listing base), the real price is \
base + N when strong looks like the unmodified base. If an option's strong \
price equals another option's price or the listing base (stale buy block), \
say so in evidence and use the most plausible price for THAT variant.
- If there are no opts but init_strong/init carry a real price, the listing \
is a flat single offer: emit ONE row with "opt": "FLAT" using that price.
- tier: "GO" | "Plus" | "Pro 5X" | "Pro 20X" | "Pro" | "Pro+" | "Max" | \
"Lite" | other exact product word. PRO X5/X20 variants are distinct tiers. \
A chip listing several tiers at once (e.g. "PLUS | PRO | GO") is one row per \
tier ONLY if separate prices exist; otherwise classify the cheapest named \
tier and note ambiguity in evidence.
- duration: "1m" | "3m" | "6m" | "12m" from the option text, else the title, \
else the description. Never guess a duration absent everywhere.
- delivery: "own_account" (activated/extended on the BUYER's account: «на \
ваш аккаунт», «продление», «с/со входом», «через токен», «по токену», \
«через данные», upgrade) | "new_account" (ready/fresh account handed over, \
«готовый аккаунт», «новый аккаунт», «случайный email») | "shared_account" \
(общий доступ) | "unknown". Description (desc) is authoritative when the \
chip is silent.
- Unrelated products (not a ChatGPT subscription) or empty evidence → rows: [].
- price_rub: integer RUB a buyer pays for THAT variant; 0 if genuinely unknown.

Output STRICT JSON only, no prose: an array, one element per input listing:
{"pid": "<pid>", "rows": [{"opt": "<option text or FLAT>", "tier": "...", \
"duration": "...", "delivery": "...", "price_rub": 123, "evidence": "<=100 chars quote"}]}"""


def _chat(base_url: str, api_key: str, model: str, user_msg: str, timeout: int) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
    return body["choices"][0]["message"]["content"]


def _parse_llm_content(content: str) -> list | None:
    """Accept a JSON array, a bare single object, or either wrapped in
    markdown fences. Old _extract_json truncates arrays to the first
    {...} object, so parse here instead."""
    for candidate in (content.strip(), _extract_json(content)):
        if not candidate or not isinstance(candidate, str):
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    return None


def _row_to_offer(pack: dict, row: dict, min_price_by_tier: dict | None) -> dict | None:
    try:
        price = float(row.get("price_rub") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    tier = str(row.get("tier") or "").strip()
    duration = str(row.get("duration") or "").strip()
    delivery = str(row.get("delivery") or "").strip() or "unknown"
    if delivery not in VALID_DELIVERIES:
        delivery = "unknown"
    glitched, reason = is_glitched(price, duration if duration in VALID_DURATIONS else "", tier)
    if not glitched and min_price_by_tier and tier in min_price_by_tier and price < min_price_by_tier[tier]:
        glitched, reason = True, (
            f"LLM price {price:.0f} below plausible floor {min_price_by_tier[tier]} for {tier}"
        )
    return {
        "marketplace": pack["mp"],
        "pid": pack["pid"],
        "url": pack["url"],
        "title": pack["title"],
        "option_text": (row.get("opt") or "")[:200],
        "tier": tier,
        "duration": duration,
        "delivery": delivery,
        "price_rub": price,
        "strong_signal": True,
        "glitched": glitched,
        "glitch_reason": reason,
        "source": "llm",
        "llm_evidence": (row.get("evidence") or "")[:120],
    }


def extract_offers(
    raw: dict,
    api_key: str,
    base_url: str = DEFAULT_LLM_BASE_URL,
    model: str = DEFAULT_LLM_MODEL,
    batch_chars: int = 24000,
    timeout: int = 120,
    min_price_by_tier: dict | None = None,
    dry_run: bool = False,
    dry_dir: str | None = None,
) -> tuple[list[dict], dict]:
    """Classify all listings via batched LLM calls. Returns (offers, meta).
    dry_run=True skips network calls and instead writes the exact prompts
    to dry_dir (default /tmp/llm_prompts) so context size is verifiable."""
    packs = [build_pack(l) for l in raw.get("listings", [])]
    batches = build_batches(packs, batch_chars)
    meta = {"called": 0, "failed": 0, "batches": len(batches), "listings": len(packs)}
    offers: list[dict] = []

    if dry_run:
        out_dir = Path(dry_dir or "/tmp/llm_prompts")
        out_dir.mkdir(parents=True, exist_ok=True)
        sizes = []
        for i, batch in enumerate(batches):
            user_msg = json.dumps(batch, ensure_ascii=False)
            (out_dir / f"batch_{i:02d}.json").write_text(user_msg, encoding="utf-8")
            sizes.append(len(user_msg))
        meta["batch_bytes"] = sizes
        meta["total_bytes"] = sum(sizes)
        return offers, meta

    for i, batch in enumerate(batches):
        user_msg = json.dumps(batch, ensure_ascii=False)
        meta["called"] += 1
        try:
            content = _chat(base_url, api_key, model, user_msg, timeout)
        except Exception as e:
            meta["failed"] += 1
            print(f"  llm batch {i}: call failed: {e}", flush=True)
            continue
        parsed = _parse_llm_content(content)
        if parsed is None:
            meta["failed"] += 1
            print(f"  llm batch {i}: non-JSON response", flush=True)
            continue
        pack_by_pid = {p["pid"]: p for p in batch}
        for item in parsed:
            pack = pack_by_pid.get(str(item.get("pid", "")))
            if pack is None:
                continue
            for row in item.get("rows", []) or []:
                offer = _row_to_offer(pack, row, min_price_by_tier)
                if offer is not None:
                    offers.append(offer)

    # keep the first row per (marketplace, pid, option_text)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for o in offers:
        k = (o["marketplace"], o["pid"], o["option_text"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(o)
    return deduped, meta


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="LLM pass-2 analyzer")
    p.add_argument("--raw", default="/tmp/raw.json")
    p.add_argument("--batch-chars", type=int, default=24000)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL))
    p.add_argument("--model", default=os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL))
    args = p.parse_args()
    raw = json.loads(Path(args.raw).read_text())
    if args.dry_run:
        _, meta = extract_offers(raw, api_key="", dry_run=True, batch_chars=args.batch_chars)
        print(json.dumps({k: v for k, v in meta.items()}, ensure_ascii=False))
    else:
        key = os.environ.get("LLM_API_KEY", "")
        if not key:
            raise SystemExit("LLM_API_KEY not set")
        offers, meta = extract_offers(raw, key, args.base_url, args.model, args.batch_chars)
        print(json.dumps(meta, ensure_ascii=False))
        for o in offers[:10]:
            print(f"  {o['tier']:8s} {o['duration']:3s} {o['delivery']:13s} {o['price_rub']:>9.0f} ₽  {o['url']}")
