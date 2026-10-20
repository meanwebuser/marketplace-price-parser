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
import shlex
import sys
from pathlib import Path

from families import FAMILY_REGISTRY
from scanner.discover import discover_all
from scanner.collect import collect
from analyzer.output import offers_from_raw, dedupe, cheapest_per_tier, write_csv, write_markdown
from analyzer.validate import validate_rankings
from scanner.final_verify import verify_winners


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Marketplace price scanner (Plati + GGSEL).")
    p.add_argument("--family", required=True,
                   help="Family: minimax, zai, chatgpt, claude, kimi (comma-separated for multi)")
    p.add_argument("--purpose", default=None,
                   help="ChatGPT only: renew | new-account | any")
    p.add_argument("--duration", default=None, choices=["1m", "3m", "12m", "6m"])
    p.add_argument("--tier", default=None)
    p.add_argument("--delivery", default=None)
    p.add_argument("--max", type=int, default=80)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--headless", action="store_true", help="force browser collection to stay hidden on both marketplaces")
    p.add_argument("--raw", default="/tmp/raw.json")
    p.add_argument("--csv", default="/tmp/table.csv")
    p.add_argument("--md", default="/tmp/table.md")
    p.add_argument("--skip-discover", action="store_true")
    p.add_argument("--skip-final-verify", action="store_true",
                   help="unsafe/offline mode: do not independently reopen and verify ranked winners")
    p.add_argument("--analyzer", default="auto", choices=["auto", "regex", "llm"],
                   help="pass-2 engine: llm = batched evidence packs, regex = offline heuristics, "
                        "auto = llm when LLM_API_KEY is set, else regex")
    p.add_argument("--llm-batch-chars", type=int, default=6000,
                   help="evidence-pack chars per LLM batch; local models stop "
                        "following the strict JSON schema above ~3 listings")
    p.add_argument("--llm-dry-run", action="store_true",
                   help="build LLM prompts, report context sizes, skip actual calls")
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
            preset = args.purpose.replace("-", "_")
            if preset not in ("renew", "new_account", "any"):
                print(f"ERROR: unknown purpose {args.purpose!r}. Choices: renew, new-account, any", file=sys.stderr)
                sys.exit(2)
            fam = _build(preset)
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
    raw = collect(discovery["candidates"], raw_path, workers=args.workers, headless=args.headless,
                  ggsel_ids=family.ggsel_ids or None)
    raw["discovery"] = {
        "platiFound": discovery["plati_found"],
        "ggselFound": discovery["ggsel_found"],
        "transports": discovery["transports"],
        "errors": discovery["errors"],
    }
    print(f"[{family.name}]   collected {len(raw.get('listings', []))} listings → {raw_path}")
    return raw


def _tier_matches(tier: str, wanted: str) -> bool:
    """Exact match, or variant prefix: --tier Pro covers "Pro 5X"/"Pro 20X"."""
    return tier == wanted or tier.startswith(wanted + " ")


def _merge_scan_context(raw: dict, collection_context: dict, analysis_context: dict,
                        *, preserve_collection: bool) -> dict:
    """Keep collection provenance immutable across analysis-only reruns."""
    previous = raw.get("scanContext", {})
    if preserve_collection and previous:
        context = dict(previous)
    else:
        context = dict(collection_context)
        if preserve_collection:
            context["collectionCommand"] = None
            context["headless"] = None
            context["collectionContextSource"] = "unknown: legacy raw has no saved collection context"
    context["analysis"] = dict(analysis_context)
    return context


def _apply_verification_results(offers: list[dict], results: list[dict]) -> None:
    """Restore stored winner flags when reanalyzing an existing raw snapshot."""
    by_identity = {
        (
            item.get("marketplace"), str(item.get("pid")),
            item.get("raw_option_text") or item.get("option_text"),
            item.get("tier"), item.get("duration"), item.get("delivery"),
        ): item
        for item in offers
    }
    for result in results:
        if not result.get("verified"):
            continue
        identity = (
            result.get("marketplace"), str(result.get("pid")), result.get("optionText"),
            result.get("tier"), result.get("duration"), result.get("delivery"),
        )
        offer = by_identity.get(identity)
        if offer is not None:
            offer["final_verified"] = True
            offer["final_observed_price"] = result.get("observedPrice")


def _print_table(cheapest: dict, args: argparse.Namespace, *, multi: bool) -> None:
    """Print the cheapest-per-tier table, applying output filters."""
    if args.duration or args.tier or args.delivery:
        filtered = {
            k: v for k, v in cheapest.items()
            if (not args.duration or k[-2] == args.duration)
            and (not args.tier or _tier_matches(k[-3], args.tier))
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


def _selected_winners(cheapest: dict, args: argparse.Namespace) -> list[dict]:
    """Apply the same user filters used by the printed result."""
    return [
        offer for key, offer in cheapest.items()
        if (not args.duration or key[-2] == args.duration)
        and (not args.tier or _tier_matches(key[-3], args.tier))
        and (not args.delivery or key[-1] == args.delivery)
    ]


def _maybe_llm(offers: list, args: argparse.Namespace) -> None:
    if args.analyzer == "llm" or (args.analyzer == "auto" and os.environ.get("LLM_API_KEY")):
        return  # LLM already produced the offers; a second pass adds nothing
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


def _analyze(raw: dict, family, args: argparse.Namespace) -> tuple[list, dict]:
    """Run pass 2 with the selected analyzer. Returns (offers, meta)."""
    use_llm = args.analyzer == "llm" or (args.analyzer == "auto" and os.environ.get("LLM_API_KEY"))
    if not use_llm:
        offers, meta = list(dedupe(offers_from_raw(raw))), {"analyzer": "regex"}
        if family.eligibility_extra:
            offers = [offer for offer in offers if family.eligibility_extra(offer)]
        return offers, meta
    from analyzer.llm_extract import extract_offers
    base_url = args.llm_base_url or os.environ.get("LLM_BASE_URL", "https://llm.bezrabotnyi.com/v1")
    model = args.llm_model or os.environ.get("LLM_MODEL", "gemma4")
    offers, meta = extract_offers(
        raw, api_key=os.environ.get("LLM_API_KEY", ""), base_url=base_url, model=model,
        batch_chars=args.llm_batch_chars, min_price_by_tier=family.price_floors or None,
        dry_run=args.llm_dry_run, dry_dir="/tmp/llm_prompts",
    )
    meta["analyzer"] = "llm-dry" if args.llm_dry_run else "llm"
    if args.llm_dry_run:
        # prompts are on disk; produce artifacts from the regex fallback
        offers = list(dedupe(offers_from_raw(raw)))
        if family.eligibility_extra:
            offers = [offer for offer in offers if family.eligibility_extra(offer)]
        return offers, meta
    if family.eligibility_extra:
        offers = [offer for offer in offers if family.eligibility_extra(offer)]
    return offers, meta


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
        fam_offers, meta = _analyze(raw, fam, args)
        if meta["analyzer"] == "llm-dry":
            sizes = meta.get("batch_bytes") or []
            print(f"[{fam.name}] analyzer=llm-dry: {meta['batches']} batches, "
                  f"total {sum(sizes)/1024:.0f} KB, max batch {max(sizes)/1024:.1f} KB "
                  f"(~{max(sizes)*0.4:.0f} tokens) → /tmp/llm_prompts")
        else:
            print(f"[{fam.name}] analyzer={meta['analyzer']}"
                  + (f", batches={meta.get('batches')}, called={meta.get('called')}, failed={meta.get('failed')}"
                     if meta["analyzer"] == "llm" else ""))
        all_offers.extend(fam_offers)
        cheapest = cheapest_per_tier(fam_offers, fam)
        validation_issues = validate_rankings(raw, fam_offers, cheapest, fam)
        if validation_issues:
            joined = "\n  - ".join(validation_issues)
            raise RuntimeError(f"zero-knowledge validation failed:\n  - {joined}")
        print(f"[{fam.name}] zero-knowledge validation: OK ({len(fam_offers)} offers)")
        prior_verification = raw.get("finalVerification")
        prior_results = prior_verification.get("results", []) if prior_verification else []
        if args.skip_final_verify:
            print(f"[{fam.name}] WARNING: final browser verification skipped", file=sys.stderr)
            final_report = prior_results
            _apply_verification_results(fam_offers, prior_results)
        else:
            targets = _selected_winners(cheapest, args)
            final_report = verify_winners(targets, fam_offers)
            print(f"[{fam.name}] final browser verification: OK ({len(final_report)} winners)")
        if not args.skip_final_verify or not prior_verification:
            raw["finalVerification"] = {
                "skipped": bool(args.skip_final_verify),
                "results": final_report,
            }
        collection_workers = int(raw.get("config", {}).get("workers", args.workers))
        plati_ids = [str(item.get("pid")) for item in raw.get("listings", []) if item.get("marketplace") == "plati"]
        ggsel_ids = [str(item.get("pid")) for item in raw.get("listings", []) if item.get("marketplace") == "ggsel"]
        collection_command = ["node", "click.py", "--workers", str(collection_workers), "--out", str(raw_path)]
        if args.headless:
            collection_command.append("--headless")
        if plati_ids:
            collection_command.extend(["--plati-pids", ",".join(plati_ids)])
        if ggsel_ids:
            collection_command.extend(["--ggsel-ids", ",".join(ggsel_ids)])
        listing_counts = {
            marketplace: sum(1 for listing in raw.get("listings", []) if listing.get("marketplace") == marketplace)
            for marketplace in ("plati", "ggsel")
        }
        discovery = raw.get("discovery", {})
        discovered_counts = {
            "plati": discovery.get("platiFound", listing_counts["plati"]),
            "ggsel": discovery.get("ggselFound", listing_counts["ggsel"]),
        }
        collection_context = {
            "collectionCommand": "PYTHONPATH=. " + shlex.join(collection_command),
            "headless": bool(args.headless or not ggsel_ids),
            "collectionContextSource": "effective collector mode",
            "workers": collection_workers,
            "maxResults": args.max,
            "discoveryCounts": discovered_counts,
            "discoveryCountsSource": "saved discovery result" if discovery else "reconstructed from collected raw listings",
            "listingCounts": listing_counts,
        }
        analysis_context = {
            "command": "PYTHONPATH=. " + shlex.join([sys.executable, *sys.argv]),
            "workers": args.workers,
            "analyzer": meta["analyzer"],
            "discoveryReused": bool(args.skip_discover),
            "finalVerificationReused": bool(args.skip_final_verify and prior_verification),
        }
        raw["scanContext"] = _merge_scan_context(
            raw, collection_context, analysis_context,
            preserve_collection=bool(args.skip_discover),
        )
        fam_raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
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
