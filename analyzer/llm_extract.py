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
import urllib.error
import urllib.request
from pathlib import Path

from analyzer.evidence import build_pack, build_batches
from analyzer.price import is_glitched
from analyzer.llm import _extract_json

DEFAULT_LLM_BASE_URL = "https://llm.bezrabotnyi.com/v1"
DEFAULT_LLM_MODEL = "gemma4"

VALID_DURATIONS = {"1m", "3m", "6m", "12m"}
VALID_DELIVERIES = {"own_account", "new_account", "shared_account", "unknown"}

# Models spell the same tier several ways ("Pro 5X"/"Pro X5"/"Go"); junk
# values ("undefined", "other") mean the row carries no information.
_TIER_ALIASES = {
    "go": "GO", "plus": "Plus", "pro": "Pro", "pro+": "Pro+",
    "pro 5x": "Pro 5X", "pro x5": "Pro 5X", "pro5x": "Pro 5X",
    "pro 20x": "Pro 20X", "pro x20": "Pro 20X", "pro20x": "Pro 20X",
    "max": "Max", "lite": "Lite",
}
_JUNK_TIERS = {"", "undefined", "null", "none", "other", "n/a", "-"}


def _norm_tier(t: str) -> str:
    t = (t or "").strip()
    return _TIER_ALIASES.get(t.lower(), t)


def _pack_evidence_prices(pack: dict) -> set[float]:
    allowed: set[float] = set()
    for p in ([pack.get("init_strong") or []] + [pack.get("init") or []]):
        allowed.update(float(x) for x in p)
    for o in pack.get("opts") or []:
        if o.get("strong") is not None:
            allowed.add(float(o["strong"]))
        allowed.update(float(x) for x in o.get("p") or [])
    return allowed

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

Output STRICT JSON only, no prose: an array with one element per input \
listing — {"pid": "<pid>", "rows": [{"opt": "<option text or FLAT>", \
"tier": "...", "duration": "...", "delivery": "...", "price_rub": 123, \
"evidence": "<=100 chars quote"}]}. If your API enforces a top-level \
object, wrap the array as {"items": [...]}."""


def _chat(base_url: str, api_key: str, model: str, user_msg: str, timeout: int,
          response_format: dict | None = None) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "max_tokens": 8192,
    }
    if response_format:
        payload["response_format"] = response_format
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


def _is_classification(parsed) -> bool:
    """True when parsed looks like classification items, not an echo of
    the input packs (gemma4 in json_object mode sometimes echoes input)."""
    if not isinstance(parsed, list) or not parsed:
        return False
    if any("opts" in it or "mp" in it for it in parsed if isinstance(it, dict)):
        return False  # packs echoed back
    return any(isinstance(it, dict) and "rows" in it for it in parsed)


def _parse_llm_content(content: str) -> list | None:
    """Accept a JSON array, a bare single object, an object wrapper like
    {"items": [...]}, or any of those in markdown fences."""
    import re as _re
    stripped = _re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", (content or "").strip()).strip()
    for candidate in (stripped, content.strip(), _extract_json(content)):
        if not candidate or not isinstance(candidate, str):
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "rows" in data:
                return [data]
            list_vals = [v for v in data.values() if isinstance(v, list)]
            if len(data) == 1 and list_vals:
                return list_vals[0]
    return None


def _row_to_offer(pack: dict, row: dict, min_price_by_tier: dict | None) -> dict | None:
    try:
        price = float(row.get("price_rub") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    tier = _norm_tier(str(row.get("tier") or ""))
    if tier.lower() in _JUNK_TIERS:
        return None
    duration = str(row.get("duration") or "").strip()
    delivery = str(row.get("delivery") or "").strip() or "unknown"
    if delivery not in VALID_DELIVERIES:
        delivery = "unknown"
    glitched, reason = is_glitched(price, duration if duration in VALID_DURATIONS else "", tier)
    if not glitched and price not in _pack_evidence_prices(pack):
        glitched, reason = True, (
            f"LLM price {price:.0f} not found in collected evidence (possible hallucination)"
        )
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
    batch_chars: int = 6000,
    timeout: int = 180,
    min_price_by_tier: dict | None = None,
    dry_run: bool = False,
    dry_dir: str | None = None,
    concurrency: int = 3,
) -> tuple[list[dict], dict]:
    """Classify all listings via batched LLM calls. Returns (offers, meta).
    Batches stay small (default ~6K chars ≈ 2-3 listings): local models
    (gemma4/qwen3.5) stop following the strict array schema on larger
    batches and echo input or answer in prose. dry_run=True skips network
    calls and instead writes the exact prompts to dry_dir (default
    /tmp/llm_prompts) so context size is verifiable."""
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

    def run_batch(i: int, batch: list[dict]) -> list[dict] | None:
        """One batch: structured call, echo/parse check, plain retry."""
        user_msg = json.dumps(batch, ensure_ascii=False)
        parsed = None
        try:
            content = _chat(base_url, api_key, model, user_msg, timeout,
                            response_format={"type": "json_object"})
            parsed = _parse_llm_content(content)
            if not _is_classification(parsed):
                parsed = None
        except urllib.error.HTTPError as e:
            if e.code != 400:
                print(f"  llm batch {i}: call failed: {e}", flush=True)
                return None
        if parsed is None:
            try:
                content = _chat(base_url, api_key, model, user_msg, timeout)
                parsed = _parse_llm_content(content)
                if not _is_classification(parsed):
                    parsed = None
            except Exception as e:
                print(f"  llm batch {i}: retry failed: {e}", flush=True)
                return None
        if parsed is None:
            print(f"  llm batch {i}: non-JSON response after retry", flush=True)
            return None

        pack_by_pid = {p["pid"]: p for p in batch}
        out: list[dict] = []
        for item in parsed:
            pack = pack_by_pid.get(str(item.get("pid", "")))
            if pack is None:
                continue
            for row in item.get("rows", []) or []:
                offer = _row_to_offer(pack, row, min_price_by_tier)
                if offer is not None:
                    out.append(offer)
        return out

    if concurrency <= 1:
        results = [run_batch(i, b) for i, b in enumerate(batches)]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            results = list(ex.map(lambda t: run_batch(*t), enumerate(batches)))

    for res in results:
        meta["called"] += 1
        if res is None:
            meta["failed"] += 1
        else:
            offers.extend(res)

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
    p.add_argument("--batch-chars", type=int, default=6000)
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
