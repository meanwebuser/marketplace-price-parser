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
    python cli.py --family zai --skip-discover --raw .tmp/zai_raw.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from families import FAMILY_REGISTRY
from scanner.discover import discover_all
from scanner.discover import discover_gift_cards
from scanner.collect import collect
from scanner.schema import annotate_schema
from scanner.proxy_source import ProxySourceError, fetch_proxy_urls, discovery_proxy_urls
from analyzer.output import offers_from_raw, gift_card_offers_from_raw, dedupe, cheapest_per_tier, write_csv, write_markdown, redact_availability_text
from analyzer.validate import validate_rankings
from scanner.final_verify import FinalVerificationError, verify_winners

ROOT = Path(__file__).resolve().parent
LLM_PROMPTS_DIR = ROOT / ".tmp" / "llm-efficiency" / "llm_prompts"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Marketplace price scanner (Plati + GGSEL).")

    def browser_workers(value: str) -> int:
        try:
            workers = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError("browser workers must be an integer from 1 to 2") from error
        if workers < 1 or workers > 2:
            raise argparse.ArgumentTypeError("browser workers must be between 1 and 2 under the reviewed local budget")
        return workers

    def http_workers(value: str) -> int:
        try:
            workers = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError("HTTP workers must be an integer from 1 to 10") from error
        if workers < 1 or workers > 10:
            raise argparse.ArgumentTypeError("HTTP workers must be between 1 and 10 under the measured Impit budget")
        return workers

    def positive_int(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError("value must be a positive integer") from error
        if parsed < 1:
            raise argparse.ArgumentTypeError("value must be a positive integer")
        return parsed

    def capture_retries(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError("capture retries must be an integer from 0 to 4") from error
        if parsed < 0 or parsed > 4:
            raise argparse.ArgumentTypeError("capture retries must be an integer from 0 to 4")
        return parsed

    def family_workers(value: str) -> int:
        try:
            workers = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError("parallel family workers must be 1 or 2") from error
        if workers < 1 or workers > 2:
            raise argparse.ArgumentTypeError("parallel family workers must be 1 or 2 under the reviewed browser budget")
        return workers

    p.add_argument("--family", required=True,
                   help="Family: minimax, zai, chatgpt, claude, kimi, apple_gift_card (comma-separated for multi)")
    p.add_argument("--region", default="US", choices=["US", "TR"],
                   help="Apple gift-card account region (currently collected seeds exist only for US)")
    p.add_argument("--purpose", default=None,
                   help="ChatGPT only: renew | new-account | any")
    p.add_argument("--duration", default=None, choices=["1m", "3m", "12m", "6m"])
    p.add_argument("--tier", default=None)
    p.add_argument("--delivery", default=None)
    p.add_argument("--max", type=int, default=80)
    p.add_argument("--max-pages", type=positive_int, default=6,
                   help="maximum result/load-more pages per query (default: 6)")
    p.add_argument("--max-candidates", type=positive_int, default=None,
                   help="optional candidate cap per marketplace; capped results are marked partial")
    p.add_argument("--full-discovery", action="store_true",
                   help="use up to 100 pages and 10,000 candidates per marketplace; coverage still reports any cap")
    p.add_argument("--allow-direct-discovery-fallback", action="store_true",
                   help="after five proxy 401/block failures, allow headless direct category discovery and record it")
    p.add_argument("--workers", type=browser_workers, default=2)
    p.add_argument("--parallel-families", type=family_workers, default=2,
                   help="scan up to two product families concurrently while sharing worker budgets")
    p.add_argument("--capture-retries", type=capture_retries, default=2,
                   help="retry a blocked/unverified listing through another proxy (0..4)")
    p.add_argument("--http-workers", type=http_workers, default=10,
                   help="headless Impit/curl_cffi concurrency for GGSEL SSR price options")
    p.add_argument("--headless", action="store_true", help="force browser collection to stay hidden on both marketplaces")
    p.add_argument("--require-proxy", action="store_true",
                   help="fail before discovery if no proxy source is configured")
    p.add_argument("--raw", default=None,
                   help="output raw snapshot; fresh scans default to a unique .tmp/scans run directory")
    p.add_argument("--csv", default=None)
    p.add_argument("--md", default=None)
    p.add_argument("--skip-discover", action="store_true")
    p.add_argument("--skip-final-verify", action="store_true",
                   help="unsafe/offline mode: do not independently reopen and verify ranked winners")
    p.add_argument("--analyzer", default="adaptive", choices=["adaptive", "auto", "regex", "llm", "selective"],
                   help="adaptive = deterministic first, LLM only for uncertain captured rows; auto/regex = zero LLM; "
                        "llm = all listings; selective = legacy ChatGPT-only uncertainty gate")
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
    args = p.parse_args(argv)
    if args.raw is None:
        if args.skip_discover:
            args.raw = ROOT / ".tmp" / "raw.json"
        else:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ") + f"-{os.getpid()}"
            args.raw = ROOT / ".tmp" / "scans" / run_id / "raw.json"
    else:
        args.raw = Path(args.raw)
    raw_path = Path(args.raw)
    if args.csv is None:
        args.csv = raw_path.parent / "table.csv"
    else:
        args.csv = Path(args.csv)
    if args.md is None:
        args.md = raw_path.parent / "table.md"
    else:
        args.md = Path(args.md)
    if args.full_discovery:
        args.max_pages = max(args.max_pages, 100)
        args.max_candidates = max(args.max_candidates or 0, 10_000)
    args.proxy_urls = []
    return args


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


def _family_raw_path(raw_path: Path, family_count: int, family_name: str) -> Path:
    if family_count == 1:
        return raw_path
    return raw_path.with_name(f"{raw_path.stem}.{family_name}{raw_path.suffix or '.json'}")


def _ensure_parent_dirs(*paths: Path) -> None:
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)


def _strip_availability(raw: dict) -> None:
    """Keep price scans free of seller inventory and purchase-state data."""
    keys = {
        "available", "unavailableReason", "availabilityStatus", "availability_status",
        "stockStatus", "stock_status", "purchaseAvailable", "buyButtonDisabled",
        "buyButtonText", "buyButtonCount", "disabled", "ariaDisabled",
    }
    for listing in raw.get("listings", []):
        for key in keys:
            listing.pop(key, None)
        for key in ("title", "pageText", "descText"):
            if key in listing:
                listing[key] = redact_availability_text(listing[key])
        for option in listing.get("options", []):
            for key in keys:
                option.pop(key, None)
            if "text" in option:
                option["text"] = redact_availability_text(option["text"])


def _run_one(family, args, raw_path: Path) -> dict:
    """Discover + collect for one family. Returns raw dict."""
    scan_started = time.perf_counter()
    if args.skip_discover and raw_path.exists():
        raw = json.loads(raw_path.read_text())
        print(f"[{family.name}] reusing {raw_path}: {len(raw.get('listings', []))} listings")
        _strip_availability(raw)
        return raw
    if not args.skip_discover and raw_path.exists():
        raise FileExistsError(
            f"fresh scan output already exists: {raw_path}; choose a new --raw path instead of mixing old captures"
        )
    print(f"[{family.name}] discovering...")
    discovery_started = time.perf_counter()
    detail_proxy_urls = getattr(args, "proxy_urls", []) or []
    discovery_urls = getattr(args, "discovery_proxy_urls", detail_proxy_urls)
    http_workers = getattr(args, "http_workers", 10)
    browser_workers = getattr(args, "workers", 2)
    discovery_kwargs = {"http_workers": http_workers}
    if discovery_urls:
        discovery_kwargs["proxy_urls"] = discovery_urls
    discovery = discover_all(
        family, args.max, max_pages=getattr(args, "max_pages", 6),
        max_candidates=getattr(args, "max_candidates", None),
        allow_direct_fallback=getattr(args, "allow_direct_discovery_fallback", False),
        **discovery_kwargs,
    )
    discovery_ms = round((time.perf_counter() - discovery_started) * 1000)
    print(f"[{family.name}]   plati: {discovery['plati_found']}, ggsel: {discovery['ggsel_found']}")
    discovery_metadata = {
        "platiFound": discovery["plati_found"],
        "ggselFound": discovery["ggsel_found"],
        "coverage": discovery.get("coverage", {}),
        "transports": discovery["transports"],
        "errors": discovery["errors"],
        "proxyMode": discovery.get("proxyMode", "direct"),
        "proxyCount": discovery.get("proxyCount", 0),
    }
    if discovery["plati_found"] + discovery["ggsel_found"] == 0:
        print(f"[{family.name}] WARNING: no candidates found", file=sys.stderr)
        raw = {"listings": [], "discovery": discovery_metadata,
               "scanTimingsMs": {"discovery": discovery_ms,
                                 "collection": 0,
                                 "total": round((time.perf_counter() - scan_started) * 1000)}}
        return annotate_schema(raw, family.name)
    print(f"[{family.name}] collecting via {http_workers} HTTP workers and {browser_workers} browser fallback workers...")
    # discover_all already merges curated GGSEL IDs into canonical candidates.
    # Passing slugs separately would collect the same listing twice because
    # collect deduplicates the slug and numeric native ID as different strings.
    collect_kwargs = {"proxy_urls": detail_proxy_urls} if detail_proxy_urls else {}
    collection_started = time.perf_counter()
    raw = collect(
        discovery["candidates"], raw_path, workers=browser_workers, http_workers=http_workers,
        capture_retries=getattr(args, "capture_retries", 2),
        headless=getattr(args, "headless", False), **collect_kwargs,
    )
    collection_ms = round((time.perf_counter() - collection_started) * 1000)
    raw["discovery"] = discovery_metadata
    raw.setdefault("config", {})["proxyCount"] = len(detail_proxy_urls)
    raw["config"]["parallelFamilies"] = getattr(args, "parallel_families", 1)
    raw["scanTimingsMs"] = {
        "discovery": discovery_ms,
        "collection": collection_ms,
        "total": round((time.perf_counter() - scan_started) * 1000),
    }
    annotate_schema(raw, family.name)
    _strip_availability(raw)
    print(f"[{family.name}]   collected {len(raw.get('listings', []))} listings → {raw_path}")
    return raw


def _budget_shares(total: int, count: int) -> list[int]:
    """Split a reviewed global worker budget across concurrent family scans."""
    if count < 1 or total < count:
        raise ValueError("worker budget must provide one slot per concurrent family")
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _scan_families(families: list, args: argparse.Namespace, raw_path: Path) -> dict[str, dict]:
    """Run discovery+collection concurrently without multiplying project limits."""
    requested = min(args.parallel_families, len(families), args.workers, args.http_workers)
    detail_proxies = list(getattr(args, "proxy_urls", []) or [])
    discovery_proxies = list(getattr(args, "discovery_proxy_urls", detail_proxies) or [])
    if detail_proxies:
        requested = min(requested, len(detail_proxies))
    if discovery_proxies:
        requested = min(requested, len(discovery_proxies))
    requested = max(1, requested)
    if requested > 1:
        print(f"[scanner] family parallelism={requested}; aggregate budget="
              f"{args.http_workers} HTTP / {args.workers} browser workers")

    outputs: dict[str, dict] = {}
    for start in range(0, len(families), requested):
        batch = families[start:start + requested]
        count = len(batch)
        http_shares = _budget_shares(args.http_workers, count)
        browser_shares = _budget_shares(args.workers, count)
        tasks = []
        for index, family in enumerate(batch):
            family_args = copy.copy(args)
            family_args.http_workers = http_shares[index]
            family_args.workers = browser_shares[index]
            family_args.proxy_urls = detail_proxies[index::count] if detail_proxies else []
            family_args.discovery_proxy_urls = discovery_proxies[index::count] if discovery_proxies else []
            family_raw_path = _family_raw_path(raw_path, len(families), family.name)
            _ensure_parent_dirs(family_raw_path)
            tasks.append((family, family_args, family_raw_path))

        if count == 1:
            family, family_args, family_raw_path = tasks[0]
            outputs[family.name] = _run_one(family, family_args, family_raw_path)
            continue

        with ThreadPoolExecutor(max_workers=count, thread_name_prefix="marketplace-family") as pool:
            futures = {
                family.name: pool.submit(_run_one, family, family_args, family_raw_path)
                for family, family_args, family_raw_path in tasks
            }
            for family, _, _ in tasks:
                outputs[family.name] = futures[family.name].result()
    return outputs


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


def _verify_winners_and_persist_failure(
    raw: dict, targets: list[dict], offers: list[dict], raw_path: Path,
    *, proxy_urls: list[str] | tuple[str, ...] = (),
) -> list[dict]:
    try:
        if proxy_urls:
            return verify_winners(targets, offers, proxy_urls=proxy_urls)
        return verify_winners(targets, offers)
    except FinalVerificationError as error:
        failure_record = {
            "skipped": False,
            "failed": True,
            "error": str(error),
            "results": error.results,
        }
        requested_target = targets[0] if len(targets) == 1 else None
        if raw.get("discovery", {}).get("product") == "apple_gift_card" and requested_target is not None:
            failure_record["excludedOffers"] = [{
                "marketplace": requested_target.get("marketplace"),
                "pid": str(requested_target.get("pid")),
                "optionText": requested_target.get("raw_option_text") or requested_target.get("option_text"),
            }]
        if error.verifier_error:
            failure_record["verifierError"] = error.verifier_error
        raw["finalVerification"] = failure_record
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        raise


def _reject_failed_final_prices(raw: dict, offers: list[dict], results: list[dict]) -> int:
    """Fail closed on exact winner prices rejected by the independent browser.

    Keep the captured evidence and rejection reason, but remove that exact
    option/price from ranking so another candidate can become the winner.
    """
    failed = [item for item in results if item.get("verified") is not True]
    rejected = 0
    for result in failed:
        marketplace, pid = result.get("marketplace"), str(result.get("pid"))
        option_text = str(result.get("optionText") or "")
        expected = result.get("expectedPrice")
        matched = False
        for listing in raw.get("listings", []):
            if listing.get("marketplace") != marketplace or str(listing.get("pid")) != pid:
                continue
            for option in listing.get("options") or []:
                if str(option.get("text") or "") == option_text:
                    option["priceVerified"] = False
                    option["finalVerificationRejected"] = result.get("error") or "price or selection did not verify"
                    matched = True
        for offer in offers:
            if (offer.get("marketplace") == marketplace and str(offer.get("pid")) == pid
                    and str(offer.get("raw_option_text") or offer.get("option_text") or "") == option_text
                    and (expected is None or float(offer.get("price_rub") or 0) == float(expected))):
                offer["price_verified"] = False
                matched = True
        if matched:
            rejected += 1
    return rejected


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


def gift_card_unit_price(offer: dict) -> float:
    return float(offer["price_rub"]) / float(offer["denomination"])


def _exclude_failed_gift_card_verifications(
    offers: list[dict], results: list[dict], excluded_offers: list[dict] = (),
) -> bool:
    excluded = False
    failures = [result for result in results if result.get("verified") is not True]
    failures.extend(excluded_offers or [])
    for result in failures:
        identity = (
            result.get("marketplace"), str(result.get("pid")),
            result.get("optionText") or result.get("raw_option_text") or result.get("option_text"),
        )
        for offer in offers:
            offer_identity = (
                offer.get("marketplace"), str(offer.get("pid")),
                offer.get("raw_option_text") or offer.get("option_text"),
            )
            if identity == offer_identity:
                offer["price_verified"] = False
                excluded = True
    return excluded


def rank_gift_card_offers(offers: list[dict]) -> list[dict]:
    """Sort current rows by RUB per one unit of face value, retaining unchecked offers."""
    return sorted(
        (offer for offer in offers if float(offer.get("denomination") or 0) > 0),
        key=lambda item: (gift_card_unit_price(item), float(item.get("price_rub") or 0)),
    )


def best_gift_card_value(offers: list[dict]) -> dict | None:
    """Choose the lowest verified RUB cost per one unit of card face value."""
    eligible = [
        offer for offer in offers
        if offer.get("available") is not False and offer.get("price_verified")
        and float(offer.get("denomination") or 0) > 0
        and float(offer.get("price_rub") or 0) > 0
    ]
    return min(eligible, key=gift_card_unit_price, default=None)


def _run_gift_card_scan(args: argparse.Namespace) -> int:
    """Run the separate prepaid path; never invent subscription tier/term."""
    proxy_urls = getattr(args, "proxy_urls", [])
    raw_path, csv_path, md_path = Path(args.raw), Path(args.csv), Path(args.md)
    _ensure_parent_dirs(raw_path, csv_path, md_path)
    if args.skip_discover:
        if not raw_path.exists():
            print(f"[apple_gift_card/{args.region}] cannot reuse missing raw snapshot: {raw_path}", file=sys.stderr)
            return 2
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        discovery_metadata = raw.get("discovery", {})
        print(f"[apple_gift_card/{args.region}] reusing {raw_path}: {len(raw.get('listings', []))} listings")
    else:
        discovery_kwargs = {"http_workers": args.http_workers}
        discovery_proxy_urls = getattr(args, "discovery_proxy_urls", proxy_urls)
        if discovery_proxy_urls:
            discovery_kwargs["proxy_urls"] = discovery_proxy_urls
        discovery = discover_gift_cards(
            args.region, args.max, max_pages=args.max_pages,
            max_candidates=args.max_candidates,
            allow_direct_fallback=args.allow_direct_discovery_fallback,
            **discovery_kwargs,
        )
        print(f"[apple_gift_card/{args.region}] plati: {discovery.get('plati_found', 0)}, "
              f"ggsel: {discovery['ggsel_found']}; discovery: {discovery.get('status', 'unknown')}")
        discovery_metadata = {key: value for key, value in discovery.items() if key != "candidates"}
        discovery_metadata.update(platiFound=discovery.get("plati_found", 0), ggselFound=discovery["ggsel_found"])
        for error in discovery.get("errors", []):
            print(f"  {error}", file=sys.stderr)
        if not discovery["candidates"]:
            raw_path.write_text(json.dumps({"listings": [], "discovery": discovery_metadata}, ensure_ascii=False, indent=2), encoding="utf-8")
            write_csv([], csv_path)
            with md_path.open("w", encoding="utf-8") as target:
                target.write(f"# Apple gift cards — region {args.region}\n\n")
                target.write(f"No candidates; discovery status: {discovery.get('status', 'unknown')} ({discovery.get('coverage', 'coverage unavailable')}).\n\n")
                target.write("No tier or subscription duration is inferred for gift cards.\n\n")
                for error in discovery.get("errors", []):
                    target.write(f"- Discovery error: {error}\n")
            print(f"[apple_gift_card/{args.region}] no candidates; discovery status: {discovery.get('status', 'unknown')}")
            return 2 if discovery.get("status") in {"failed", "partial"} or discovery.get("errors") else 0
        # The top-up path is always headless; on hosts where variant controls do
        # not react in headless mode those options remain unverified and are not
        # published as a confirmed price.
        collect_kwargs = {"proxy_urls": proxy_urls} if proxy_urls else {}
        raw = collect(
            discovery["candidates"], raw_path, workers=args.workers, http_workers=args.http_workers,
            capture_retries=args.capture_retries, headless=True, **collect_kwargs,
        )
        raw["discovery"] = discovery_metadata
    # This scan is deliberately price-only; discard legacy stock evidence.
    _strip_availability(raw)
    raw.setdefault("config", {})["proxyCount"] = len(proxy_urls)
    annotate_schema(raw, "apple_gift_card")
    offers = list(gift_card_offers_from_raw(raw, args.region))
    winner = best_gift_card_value(offers)
    results = []
    verification_failed = bool(args.skip_final_verify and raw.get("finalVerification", {}).get("failed"))
    if verification_failed:
        _exclude_failed_gift_card_verifications(
            offers, raw.get("finalVerification", {}).get("results", []),
            raw.get("finalVerification", {}).get("excludedOffers", []),
        )
        winner = None
    if winner and not args.skip_final_verify:
        try:
            results = _verify_winners_and_persist_failure(
                raw, [winner], offers, raw_path, proxy_urls=proxy_urls
            )
            verification_failed = False
            raw["finalVerification"] = {"skipped": False, "results": results}
        except FinalVerificationError as error:
            verification_failed = True
            results = error.results
            failed_identity = (
                winner.get("marketplace"), str(winner.get("pid")),
                winner.get("raw_option_text") or winner.get("option_text"),
            )
            for offer in offers:
                offer_identity = (
                    offer.get("marketplace"), str(offer.get("pid")),
                    offer.get("raw_option_text") or offer.get("option_text"),
                )
                if offer_identity == failed_identity:
                    offer["price_verified"] = False
            winner = None
            raw["finalVerification"] = {
                "skipped": False, "failed": True, "error": str(error), "results": results,
                "excludedOffers": [{
                    "marketplace": failed_identity[0], "pid": failed_identity[1],
                    "optionText": failed_identity[2],
                }],
            }
            print("[apple_gift_card] final verification failed; affected offer marked unverified and excluded from the site", file=sys.stderr)
    elif args.skip_final_verify:
        print(f"[apple_gift_card/{args.region}] final verification skipped")
        if not verification_failed:
            raw["finalVerification"] = {"skipped": True, "results": []}
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(offers, csv_path)
    with md_path.open("w", encoding="utf-8") as target:
        target.write(f"# Apple gift cards — region {args.region}\n\n")
        target.write(
            f"Candidates: Plati {discovery_metadata.get('plati_found', discovery_metadata.get('platiFound', 0))}, "
            f"GGSEL {discovery_metadata.get('ggsel_found', discovery_metadata.get('ggselFound', 0))}; "
            f"status {discovery_metadata.get('status', 'unknown')} "
            f"({discovery_metadata.get('coverage', 'coverage unavailable')}).\n\n"
        )
        target.write("No tier or subscription duration is inferred for gift cards.\n\n")
        if verification_failed:
            target.write("Final browser verification: failed; the affected offer is unverified and excluded from the site.\n\n")
        elif raw.get("finalVerification", {}).get("skipped"):
            target.write("Final browser verification: skipped.\n\n")
        target.write("| Denomination | Price | RUB per unit | Price verified | Marketplace | Listing |\n|---|---:|---:|---|---|---|\n")
        for offer in rank_gift_card_offers(offers):
            target.write(
                f"| {offer['denomination']:g} {offer['denomination_currency']} | "
                f"{offer['price_rub']:.0f} ₽ | {offer['price_per_unit']:.2f} ₽ per unit | {offer['price_verified']} | "
                f"{offer['marketplace']} | [{offer['pid']}]({offer['url']}) |\n"
            )
    print(f"[apple_gift_card/{args.region}] parsed {len(offers)} selected variants; "
          f"{sum(bool(offer.get('price_verified')) for offer in offers)} price-verified")
    if winner:
        unit = "$1" if winner["denomination_currency"] == "USD" else f"1 {winner['denomination_currency']}"
        print(f"best verified rate: {winner['price_rub'] / winner['denomination']:.2f} ₽ per {unit}; "
              f"{winner['denomination']:g} {winner['denomination_currency']} for {winner['price_rub']:.0f} ₽ "
              f"— {winner['url']}")
    print(f"CSV: {csv_path}\nMD: {md_path}")
    return 2 if verification_failed else 0


def _maybe_llm(offers: list, args: argparse.Namespace) -> None:
    if args.analyzer in {"llm", "selective"}:
        return  # LLM already produced or selectively reviewed the offers.
    if not args.llm:
        return  # An API key alone must not trigger an LLM call.
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
    analyzer = args.analyzer
    if analyzer == "auto":
        analyzer = "regex"

    if analyzer in {"adaptive", "selective"}:
        if analyzer == "selective" and family.name != "chatgpt":
            raise ValueError("--analyzer selective currently supports only the ChatGPT family")
        from analyzer.selective import merge_selective_offers, select_uncertain_listings

        deterministic = list(dedupe(offers_from_raw(raw)))
        if family.eligibility_extra:
            deterministic = [offer for offer in deterministic if family.eligibility_extra(offer)]
        selected, reason_map = select_uncertain_listings(raw, deterministic, family=family)
        reason_counts: dict[str, int] = {}
        for reasons in reason_map.values():
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

        meta = {
            "analyzer": analyzer,
            "totalListings": len(raw.get("listings", [])),
            "routedListings": len(selected),
            "routeReasons": reason_counts,
            "called": 0,
            "batches": 0,
            "failed": 0,
        }
        if not selected or (not os.environ.get("LLM_API_KEY") and not args.llm_dry_run):
            if selected and not os.environ.get("LLM_API_KEY"):
                meta["llmSkipped"] = "LLM_API_KEY is not set"
            return deterministic, meta

        from analyzer.llm_extract import extract_offers
        base_url = args.llm_base_url or os.environ.get("LLM_BASE_URL", "https://llm.bezrabotnyi.com/v1")
        model = args.llm_model or os.environ.get("LLM_MODEL", "gemma4")
        llm_offers, llm_meta = extract_offers(
            {**raw, "listings": selected},
            api_key=os.environ.get("LLM_API_KEY", ""),
            base_url=base_url,
            model=model,
            batch_chars=args.llm_batch_chars,
            min_price_by_tier=family.price_floors or None,
            dry_run=args.llm_dry_run,
            dry_dir=str(LLM_PROMPTS_DIR),
        )
        meta.update(llm_meta)
        meta["analyzer"] = f"{analyzer}-dry" if args.llm_dry_run else analyzer
        offers = merge_selective_offers(deterministic, llm_offers, selected)
        if family.eligibility_extra:
            offers = [offer for offer in offers if family.eligibility_extra(offer)]
        return offers, meta

    if analyzer != "llm":
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
        dry_run=args.llm_dry_run, dry_dir=str(LLM_PROMPTS_DIR),
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


def _print_dry_run_summary(family_name: str, meta: dict) -> None:
    routed = (
        f", {meta.get('routedListings', 0)}/{meta.get('totalListings', 0)} listings routed"
        if meta.get("analyzer") in {"selective-dry", "adaptive-dry"} else ""
    )
    sizes = meta.get("batch_bytes") or []
    print(f"[{family_name}] analyzer={meta['analyzer']}: {meta['batches']} batches{routed}, "
          f"total {sum(sizes)/1024:.0f} KB, max batch {max(sizes)/1024:.1f} KB "
          f"(~{max(sizes)*0.4:.0f} tokens) → {LLM_PROMPTS_DIR}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    needs_proxy = not (args.skip_discover and args.skip_final_verify)
    try:
        args.proxy_urls = fetch_proxy_urls() if needs_proxy else []
        args.discovery_proxy_urls = discovery_proxy_urls(args.proxy_urls)
    except ProxySourceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if args.require_proxy and not args.proxy_urls:
        print("ERROR: --require-proxy was set but no runtime proxy source is configured", file=sys.stderr)
        return 2
    if not args.skip_discover and Path(args.raw).exists():
        print(f"ERROR: refusing to append a fresh scan to existing raw data: {args.raw}; choose a new --raw path",
              file=sys.stderr)
        return 2
    if args.proxy_urls:
        print(f"Proxy source: {len(args.proxy_urls)} HTTP proxies loaded (addresses hidden)")
    else:
        print("Proxy source: not configured; direct requests")
    if args.family == "apple_gift_card":
        return _run_gift_card_scan(args)
    families = _resolve_families(args)
    raw_path = Path(args.raw)
    csv_path = Path(args.csv)
    md_path = Path(args.md)
    _ensure_parent_dirs(raw_path, csv_path, md_path)

    all_offers: list = []
    all_cheapest: dict = {}
    primary_raw_path: Path | None = None
    raw_by_family = _scan_families(families, args, raw_path)
    for fam in families:
        fam_raw_path = _family_raw_path(raw_path, len(families), fam.name)
        _ensure_parent_dirs(fam_raw_path)
        if primary_raw_path is None:
            primary_raw_path = fam_raw_path
        raw = raw_by_family[fam.name]
        analysis_started = time.perf_counter()
        fam_offers, meta = _analyze(raw, fam, args)
        analysis_ms = round((time.perf_counter() - analysis_started) * 1000)
        if meta["analyzer"] in ("llm-dry", "selective-dry", "adaptive-dry"):
            _print_dry_run_summary(fam.name, meta)
        else:
            print(f"[{fam.name}] analyzer={meta['analyzer']}"
                  + (f", {meta.get('routedListings', 0)}/{meta.get('totalListings', 0)} listings routed, "
                     f"{meta.get('batches', 0)} batches, {meta.get('called', 0)} calls, "
                     f"{meta.get('failed', 0)} failed"
                     if meta["analyzer"].startswith(("selective", "adaptive")) else "")
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
        verification_started = time.perf_counter()
        if args.skip_final_verify:
            print(f"[{fam.name}] WARNING: final browser verification skipped", file=sys.stderr)
            final_report = prior_results
            _apply_verification_results(fam_offers, prior_results)
        else:
            final_report = [item for item in prior_results if item.get("verified") is True]
            rejected_results: list[dict] = list(
                prior_verification.get("rejectedResults", []) if prior_verification else []
            )
            if prior_verification and prior_verification.get("failed"):
                rejected_results.extend(item for item in prior_results if item.get("verified") is not True)
            targets = [item for item in _selected_winners(cheapest, args)
                       if not item.get("final_verified")]
            for _attempt in range(len(fam_offers) + 1):
                if not targets:
                    break
                try:
                    batch = _verify_winners_and_persist_failure(
                        raw, targets, fam_offers, fam_raw_path, proxy_urls=args.proxy_urls
                    )
                    final_report.extend(batch)
                    break
                except FinalVerificationError as error:
                    successful = [item for item in error.results if item.get("verified") is True]
                    failed = [item for item in error.results if item.get("verified") is not True]
                    if not failed:
                        raise
                    _apply_verification_results(fam_offers, successful)
                    newly_rejected = _reject_failed_final_prices(raw, fam_offers, failed)
                    if not newly_rejected:
                        raise
                    rejected_results.extend(failed)
                    fam_offers = [item for item in fam_offers if item.get("price_verified") is not False]
                    cheapest = cheapest_per_tier(fam_offers, fam)
                    validation_issues = validate_rankings(raw, fam_offers, cheapest, fam)
                    if validation_issues:
                        joined = "\n  - ".join(validation_issues)
                        raise RuntimeError(f"zero-knowledge validation failed after rejecting unverified prices:\n  - {joined}")
                    targets = [item for item in _selected_winners(cheapest, args)
                               if not item.get("final_verified")]
                    print(f"[{fam.name}] rejected {newly_rejected} final-verification failure(s); "
                          f"rechecking {len(targets)} remaining winners")
            else:
                raise RuntimeError(f"[{fam.name}] final verification rejection loop exceeded offer count")
            raw["finalVerification"] = {
                "skipped": False,
                "failed": False,
                "results": final_report,
                "rejectedResults": rejected_results,
            }
            print(f"[{fam.name}] final browser verification: OK ({len(final_report)} winners, "
                  f"{len(rejected_results)} rejected price(s))")
        verification_ms = round((time.perf_counter() - verification_started) * 1000)
        if args.skip_final_verify and not prior_verification:
            raw["finalVerification"] = {
                "skipped": True,
                "results": final_report,
            }
        timings = raw.setdefault("scanTimingsMs", {})
        timings["analysis"] = analysis_ms
        timings["finalVerification"] = verification_ms
        timings["total"] = sum(int(timings.get(key, 0) or 0)
                               for key in ("discovery", "collection", "analysis", "finalVerification"))
        collection_workers = int(raw.get("config", {}).get("workers", args.workers))
        plati_ids = raw.get("config", {}).get("httpFallbackPlatiIds")
        if plati_ids is None:
            plati_ids = [str(item.get("pid")) for item in raw.get("listings", []) if item.get("marketplace") == "plati"]
        ggsel_ids = raw.get("config", {}).get("httpFallbackGGSELIds")
        if ggsel_ids is None:
            ggsel_ids = [str(item.get("pid")) for item in raw.get("listings", []) if item.get("marketplace") == "ggsel"]
        collection_command = ["node", "click.py", "--workers", str(collection_workers), "--out", str(fam_raw_path)]
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
            "collectionContextSource": "hybrid HTTP and browser collector",
            "workers": collection_workers,
            "httpWorkers": raw.get("config", {}).get("httpWorkers", args.http_workers),
            "transportCounts": raw.get("config", {}).get("transportCounts", {}),
            "transportDurationsMs": raw.get("config", {}).get("transportDurationsMs", {}),
            "httpPlatiIds": raw.get("config", {}).get("httpPlatiIds", []),
            "httpFallbackPlatiIds": raw.get("config", {}).get("httpFallbackPlatiIds", []),
            "httpGGSELIds": raw.get("config", {}).get("httpGGSELIds", []),
            "proxyMode": "configured" if getattr(args, "proxy_urls", []) else "direct",
            "proxyCount": raw.get("config", {}).get("proxyCount", len(getattr(args, "proxy_urls", []))),
            "parallelFamilies": raw.get("config", {}).get("parallelFamilies", 1),
            "maxResults": args.max,
            "maxPages": args.max_pages,
            "maxCandidates": args.max_candidates,
            "discoveryCounts": discovered_counts,
            "discoveryCountsSource": "saved discovery result" if discovery else "reconstructed from collected raw listings",
            "listingCounts": listing_counts,
        }
        analysis_context = {
            "command": "PYTHONPATH=. " + shlex.join([sys.executable, *sys.argv]),
            "workers": raw.get("config", {}).get("workers", args.workers),
            "httpWorkers": raw.get("config", {}).get("httpWorkers", args.http_workers),
            "analyzer": meta["analyzer"],
            "llmCalls": meta.get("called", 0),
            "llmRoutedListings": meta.get("routedListings", 0),
            "schemaStatus": raw.get("siteSchema", {}).get("status", "unknown"),
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
    write_markdown(all_offers, all_cheapest, primary, md_path, source_path=primary_raw_path or raw_path)

    _print_table(all_cheapest, args, multi=len(families) > 1)
    _maybe_llm(all_offers, args)

    print(f"\nCSV: {csv_path}  ({len(all_offers)} rows)")
    print(f"MD:  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
