#!/usr/bin/env python3
"""Replay the selective analyzer offline using a saved all-LLM CSV.

No discovery, browser, or model calls are made. The current deterministic
rules and uncertainty gate run over ``--raw``; saved LLM rows are eligible only
for marketplace/PID pairs selected by that gate and still pass the exact raw
option-price check in ``merge_selective_offers``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzer.output import dedupe, offers_from_raw
from analyzer.selective import merge_selective_offers, select_uncertain_listings
from families.chatgpt import CONFIG as CHATGPT_CONFIG

CANONICAL_FIELDS = [
    "marketplace", "pid", "url", "title", "option_text", "raw_option_text",
    "control_kind", "control_dom_index", "control_input_id", "control_value",
    "tier", "duration", "delivery", "price_rub", "strong_signal", "glitched",
    "glitch_reason", "available", "availability_reason", "price_changed",
    "price_stable", "price_verified", "final_verified", "final_observed_price",
]


def _bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _load_llm_csv(path: Path) -> list[dict]:
    offers: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            try:
                price = float(row.get("price_rub") or 0)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            offer = dict(row)
            offer["pid"] = str(row.get("pid") or "")
            offer["price_rub"] = price
            offer["strong_signal"] = _bool(row.get("strong_signal"))
            offer["glitched"] = _bool(row.get("glitched"))
            offers.append(offer)
    return offers


def _write_canonical_csv(offers: list[dict], path: Path) -> None:
    extras = list(dict.fromkeys(
        key for offer in offers for key in offer if key not in CANONICAL_FIELDS
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=[*CANONICAL_FIELDS, *extras])
        writer.writeheader()
        writer.writerows(offers)


def replay(raw_path: Path, llm_csv_path: Path, out_path: Path) -> dict:
    """Run current deterministic rules and gate, then merge saved LLM rows."""
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    deterministic = list(dedupe(list(offers_from_raw(raw))))
    if CHATGPT_CONFIG.eligibility_extra:
        deterministic = [
            offer for offer in deterministic
            if CHATGPT_CONFIG.eligibility_extra(offer)
        ]

    selected, reasons = select_uncertain_listings(raw, deterministic)
    routed_keys = set(reasons)
    saved_rows = [
        offer for offer in _load_llm_csv(llm_csv_path)
        if (str(offer.get("marketplace") or ""), str(offer.get("pid") or "")) in routed_keys
    ]
    merged = merge_selective_offers(deterministic, saved_rows, selected)
    if CHATGPT_CONFIG.eligibility_extra:
        merged = [offer for offer in merged if CHATGPT_CONFIG.eligibility_extra(offer)]

    _write_canonical_csv(merged, out_path)
    return {
        "rawListings": len(raw.get("listings", [])),
        "deterministicRows": len(deterministic),
        "routedListings": len(selected),
        "savedRowsForRoutedListings": len(saved_rows),
        "acceptedLlmRows": sum(1 for offer in merged if offer.get("source") == "llm"),
        "outputRows": len(merged),
        "routeReasons": {
            reason: sum(reason in items for items in reasons.values())
            for reason in sorted({reason for items in reasons.values() for reason in items})
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path, help="Saved collector raw JSON")
    parser.add_argument("--llm-csv", required=True, type=Path, help="Saved all-LLM analyzer CSV")
    parser.add_argument("--out", required=True, type=Path, help="Canonical replay CSV destination")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = replay(args.raw, args.llm_csv, args.out)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print(f"Wrote selective replay CSV: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
