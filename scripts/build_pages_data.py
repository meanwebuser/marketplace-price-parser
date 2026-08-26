#!/usr/bin/env python3
"""Convert a scanner CSV snapshot into the data file consumed by GitHub Pages."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path, help="Scanner CSV artifact")
    parser.add_argument("--out", required=True, type=Path, help="Pages JSON output")
    parser.add_argument("--raw", type=Path, help="Optional scanner raw JSON for run metadata")
    parser.add_argument("--family", default="minimax", help="Product family shown by the page")
    return parser.parse_args()


def as_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def main() -> int:
    args = parse_args()
    with args.csv.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    offers = []
    for row in rows:
        title = row.get("title", "")
        # The MiniMax crawler searches a shared category, so reject unrelated
        # products such as Runway that happen to have a "Max" button.
        if args.family == "minimax" and "minimax" not in title.lower():
            continue
        try:
            price = float(row["price_rub"])
        except (KeyError, TypeError, ValueError):
            continue
        offers.append(
            {
                "marketplace": row.get("marketplace", "unknown"),
                "pid": row.get("pid", ""),
                "url": row.get("url", ""),
                "title": title,
                "optionText": row.get("option_text", ""),
                "tier": row.get("tier", "unknown"),
                "duration": row.get("duration", "unknown"),
                "delivery": row.get("delivery", "unknown"),
                "priceRub": price,
                "strongSignal": as_bool(row.get("strong_signal")),
                "glitched": as_bool(row.get("glitched")),
                "glitchReason": row.get("glitch_reason", ""),
            }
        )

    metadata: dict[str, object] = {
        "family": args.family,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceRows": len(rows),
        "visibleRows": len(offers),
    }
    if args.raw and args.raw.exists():
        raw = json.loads(args.raw.read_text(encoding="utf-8"))
        metadata["scanStartedAt"] = raw.get("startedAt")
        metadata["scanCompletedAt"] = raw.get("lastUpdate")
        metadata["listings"] = len(raw.get("listings", []))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"metadata": metadata, "offers": offers}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(offers)} offers to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
