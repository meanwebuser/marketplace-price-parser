#!/usr/bin/env python3
"""Unified marketplace price scanner entry point.

Stage 1 (YAGNI MVP):
    python cli.py --family zai                 # scan all Z.ai listings
    python cli.py --family minimax --max 30    # limit discovery

Stage 2/3 will add:
    python cli.py --family zai --duration 1m   # filter output
    python cli.py --family zai --llm-check      # Gemma4 sanity check on listings
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from families import FAMILY_REGISTRY
from scanner.discover import discover_all
from scanner.collect import collect
from analyzer.output import offers_from_raw, dedupe, cheapest_per_tier, write_csv, write_markdown


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Marketplace price scanner (Plati + GGSEL).")
    p.add_argument("--family", required=True, choices=list(FAMILY_REGISTRY),
                   help="Product family: minimax, zai, chatgpt, claude")
    p.add_argument("--purpose", default=None,
                   help="ChatGPT only: which preset to apply (renew, new-account, any)")
    p.add_argument("--duration", default=None, choices=["1m", "3m", "12m", "6m"],
                   help="Filter analysis output to one duration")
    p.add_argument("--tier", default=None,
                   help="Filter analysis output to one tier (Max, Pro+, Pro, Lite, Plus)")
    p.add_argument("--delivery", default=None,
                   help="Filter analysis output to one delivery type (own_account, new_account, shared_account)")
    p.add_argument("--max", type=int, default=80, help="Max candidates per marketplace")
    p.add_argument("--workers", type=int, default=6, help="Parallel browser workers")
    p.add_argument("--raw", default="/tmp/raw.json", help="Pass-1 raw collector output path")
    p.add_argument("--csv", default="/tmp/table.csv", help="Pass-2 CSV output")
    p.add_argument("--md", default="/tmp/table.md", help="Pass-2 Markdown output")
    p.add_argument("--skip-discover", action="store_true",
                   help="Reuse existing --raw (skip pass-1 collection)")
    args = p.parse_args(argv)

    family = FAMILY_REGISTRY[args.family]
    # ChatGPT: honor --purpose by rebuilding the config with the chosen preset
    if args.family == "chatgpt" and args.purpose:
        from families.chatgpt import _build
        family = _build(args.purpose)
    raw_path = Path(args.raw)
    csv_path = Path(args.csv)
    md_path = Path(args.md)

    if args.skip_discover and raw_path.exists():
        raw = json.loads(raw_path.read_text())
        print(f"reusing {raw_path}: {len(raw.get('listings', []))} listings")
    else:
        print(f"== discovering candidates for {family.name} ==")
        discovery = discover_all(family, args.max)
        plati_n = discovery["plati_found"]
        ggsel_n = discovery["ggsel_found"]
        print(f"  plati: {plati_n}, ggsel: {ggsel_n}")
        if plati_n + ggsel_n == 0:
            print("ERROR: no candidates found", file=sys.stderr)
            return 1
        print(f"== collecting via {args.workers} workers ==")
        raw = collect(
            discovery["candidates"],
            raw_path,
            workers=args.workers,
            ggsel_ids=family.ggsel_ids or None,
        )
        print(f"  collected {len(raw.get('listings', []))} listings → {raw_path}")

    print("== analyzing ==")
    offers = list(offers_from_raw(raw))
    offers = dedupe(offers)
    cheapest = cheapest_per_tier(offers, family)
    write_csv(offers, csv_path)
    write_markdown(offers, cheapest, family, md_path, source_path=raw_path)

    # Apply output filters (filter only the printed table, not the raw CSV)
    filtered_cheapest = cheapest
    if args.duration or args.tier or args.delivery:
        filtered_cheapest = {
            (t, d, dl): offer
            for (t, d, dl), offer in cheapest.items()
            if (not args.duration or d == args.duration)
            and (not args.tier or t == args.tier)
            and (not args.delivery or dl == args.delivery)
        }
    print(f"\n=== {family.name} cheapest per (tier, duration, delivery) ===")
    for (tier, dur, delivery), offer in sorted(filtered_cheapest.items()):
        print(f"  {tier:6s} {dur:3s} {delivery:14s} {offer['price_rub']:>10.0f} ₽  {offer['marketplace']:5s}  {offer['url']}")
    print(f"\nCSV: {csv_path}  ({len(offers)} rows)")
    print(f"MD:  {md_path}")
    if args.duration or args.tier or args.delivery:
        filtered = len(filtered_cheapest)
        total = len(cheapest)
        if filtered < total:
            print(f"\n(filtered: {filtered}/{total} matches --duration/--tier/--delivery)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
