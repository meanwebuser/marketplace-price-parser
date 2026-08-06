#!/usr/bin/env python3
"""Unified marketplace price scanner entry point.

Stage 1 (YAGNI MVP): per-family pipeline.
Stage 2 (Normal): purpose presets, backward-compat wrappers.
Stage 3 (Ultimate): --llm, multi-family, output filters.

Examples:
    python cli.py --family zai                       # single family, fresh scan
    python cli.py --family zai,chatgpt               # multi-family
    python cli.py --family zai --tier Max --duration 1m
    python cli.py --family chatgpt --purpose renew
    python cli.py --family zai --llm                 # Gemma4 sanity check
    python cli.py --family zai --skip-discover --raw /tmp/zai_raw.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from families import FAMILY_REGISTRY
from scanner.discover import discover_all
from scanner.collect import collect
from analyzer.output import offers_from_raw, dedupe, cheapest_per_tier, write_csv, write_markdown


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Marketplace price scanner (Plati + GGSEL).")
    p.add_argument("--family", required=True,
                   help="Family: minimax, zai, chatgpt, claude (comma-separated for multi)")
    p.add_argument("--purpose", default=None,
                   help="ChatGPT only: renew | new-account | any")
    p.add_argument("--duration", default=None, choices=["1m", "3m", "12m", "6m"])
    p.add_argument("--tier", default=None)
    p.add_argument("--delivery", default=None)
    p.add_argument("--max", type=int, default=80)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--raw", default="/tmp/raw.json")
    p.add_argument("--csv", default="/tmp/table.csv")
    p.add_argument("--md", default="/tmp/table.md")
    p.add_argument("--skip-discover", action="store_true")
    p.add_argument("--llm", action="store_true",
                   help="Gemma4 sanity check on collected offers")
    p.add_argument("--llm-base-url", default=None)
    p.add_argument("--llm-model", default=None)
    p.add_argument("--llm-required", action="store_true")
    return p.parse_args(argv)


def _resolve_families(args: argparse.Namespace) -> list:
    families = []
    for name in args.family.split(","):
        name = name.strip()
        if name not in FAMILY_REGISTRY:
            print(f"ERROR: unknown family {name!r}. Choices: {list(FAMILY_REGISTRY)}", file=sys.stderr)
            sys.exit(2)
        fam = FAMILY_REGISTRY[name]
        if name == "chatgpt" and args.purpose:
            from families.chatgpt import _build
            fam = _build(args.purpose)
        families.append(fam)
    return families


def _run_one(family, args, raw_path: Path) -> dict:
    """Discover + collect for one family. Returns raw dict."""
    if args.skip_discover and raw_path.exists():
        raw = json.loads(raw_path.read_text())
        print(f"[{family.name}] reusing {raw_path}: {len(raw.get('listings', []))} listings")
        return raw
    print(f"[{family.name}] discovering...")
    discovery = discover_all(family, args.max)
    print(f"[{family.name}]   plati: {discovery['plati_found']}, ggsel: {discovery['ggsel_found']}")
    if discovery["plati_found"] + discovery["ggsel_found"] == 0:
        print(f"[{family.name}] WARNING: no candidates found", file=sys.stderr)
        return {"listings": []}
    print(f"[{family.name}] collecting via {args.workers} workers...")
    raw = collect(discovery["candidates"], raw_path, workers=args.workers,
                  ggsel_ids=family.ggsel_ids or None)
    print(f"[{family.name}]   collected {len(raw.get('listings', []))} listings → {raw_path}")
    return raw


def _print_table(cheapest: dict, args: argparse.Namespace, *, multi: bool) -> None:
    """Print the cheapest-per-tier table, applying output filters."""
    if args.duration or args.tier or args.delivery:
        filtered = {
            k: v for k, v in cheapest.items()
            if (not args.duration or k[-2] == args.duration)
            and (not args.tier or k[-3] == args.tier)
            and (not args.delivery or k[-1] == args.delivery)
        }
    else:
        filtered = cheapest
    if multi:
        header = "=== cheapest per (family, tier, duration, delivery) ==="
    else:
        header = "=== cheapest per (tier, duration, delivery) ==="
    print(f"\n{header}")
    for key in sorted(filtered.keys()):
        if multi:
            family_n, tier, dur, delivery = key
            offer = filtered[key]
            print(f"  {family_n:8s} {tier:5s} {dur:3s} {delivery:14s} {offer['price_rub']:>10.0f} ₽  {offer['marketplace']:5s}  {offer['url']}")
        else:
            tier, dur, delivery = key
            offer = filtered[key]
            print(f"  {tier:6s} {dur:3s} {delivery:14s} {offer['price_rub']:>10.0f} ₽  {offer['marketplace']:5s}  {offer['url']}")
    if args.duration or args.tier or args.delivery:
        if len(filtered) < len(cheapest):
            print(f"\n(filtered: {len(filtered)}/{len(cheapest)} matches --duration/--tier/--delivery)")


def _maybe_llm(offers: list, args: argparse.Namespace) -> None:
    if not (args.llm or os.environ.get("LLM_API_KEY")):
        return
    from analyzer.llm import review_with_gemma, apply_llm_reviews
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = args.llm_base_url or os.environ.get("LLM_BASE_URL", "https://llm.bezrabotnyi.com/v1")
    model = args.llm_model or os.environ.get("LLM_MODEL", "gemma4")
    if not api_key:
        if args.llm_required:
            print("ERROR: --llm-required but LLM_API_KEY not set", file=sys.stderr)
            sys.exit(2)
        print("note: --llm requested but LLM_API_KEY not set; skipping", file=sys.stderr)
        return
    reviews, meta = review_with_gemma(offers, api_key, base_url, model)
    apply_llm_reviews(offers, reviews, override_unknowns=True)
    mismatch = sum(1 for o in offers if o.get("warning"))
    print(f"\nLLM sanity check: {meta['called']} calls, {meta['failed']} failed, {mismatch} mismatches")
    for o in offers:
        if o.get("warning"):
            print(f"  WARN: {o['url']}\n    {o['warning']}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    families = _resolve_families(args)
    raw_path = Path(args.raw)
    csv_path = Path(args.csv)
    md_path = Path(args.md)

    all_offers: list = []
    all_cheapest: dict = {}
    for fam in families:
        fam_raw_path = raw_path if len(families) == 1 else Path(f"/tmp/{fam.name}_raw.json")
        raw = _run_one(fam, args, fam_raw_path)
        fam_offers = list(offers_from_raw(raw))
        fam_offers = dedupe(fam_offers)
        all_offers.extend(fam_offers)
        cheapest = cheapest_per_tier(fam_offers, fam)
        for k, v in cheapest.items():
            if len(families) == 1:
                all_cheapest[k] = v
            else:
                all_cheapest[(fam.name, *k)] = v

    primary = families[0]
    write_csv(all_offers, csv_path)
    write_markdown(all_offers, all_cheapest, primary, md_path, source_path=raw_path)

    _print_table(all_cheapest, args, multi=len(families) > 1)
    _maybe_llm(all_offers, args)

    print(f"\nCSV: {csv_path}  ({len(all_offers)} rows)")
    print(f"MD:  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
