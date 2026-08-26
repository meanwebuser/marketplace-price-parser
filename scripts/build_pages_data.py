#!/usr/bin/env python3
"""Build the GitHub Pages catalogue from the newest committed scan per product."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

PRODUCTS = {
    "minimax": {"label": "MiniMax Token Plan", "description": "Официальные уровни Token Plan: Plus, Max и Ultra.", "tiers": {"Plus", "Max", "Ultra"}},
    "chatgpt": {"label": "ChatGPT", "description": "Последний сохранённый скан предложений ChatGPT.", "tiers": None},
    "zai": {"label": "Z.ai GLM Coding", "description": "Последний сохранённый снимок Max-подписок Z.ai GLM Coding.", "tiers": {"Max"}},
}
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})-(minimax|chatgpt|zai)")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-root", type=Path, default=Path("docs/snapshots/data"))
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args()

def as_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}

def latest_csv(root: Path, product_id: str) -> Path | None:
    files = [p for p in root.glob(f"*-{product_id}*.csv") if DATE_PREFIX.match(p.name)]
    return max(files, default=None, key=lambda p: p.name)

def normalize_csv(csv_path: Path, product_id: str) -> tuple[list[dict], dict]:
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    offers = []
    allowed_tiers = PRODUCTS[product_id]["tiers"]
    for row in rows:
        title, tier = row.get("title", ""), row.get("tier", "unknown")
        if product_id == "minimax" and "minimax" not in title.lower():
            continue
        if allowed_tiers and tier not in allowed_tiers:
            continue
        try:
            price = float(row["price_rub"])
        except (KeyError, TypeError, ValueError):
            continue
        offers.append({"marketplace": row.get("marketplace", "unknown"), "pid": row.get("pid", ""), "url": row.get("url", ""), "title": title, "optionText": row.get("option_text", ""), "tier": tier, "duration": row.get("duration", "unknown"), "delivery": row.get("delivery", "unknown"), "priceRub": price, "strongSignal": as_bool(row.get("strong_signal")), "glitched": as_bool(row.get("glitched")), "glitchReason": row.get("glitch_reason", "")})
    raw_path = csv_path.with_suffix(".raw.json")
    raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
    return offers, {"scanDate": csv_path.name[:10], "sourcePath": str(csv_path).replace("docs/", ""), "scanStartedAt": raw.get("startedAt"), "scanCompletedAt": raw.get("lastUpdate"), "listings": len(raw.get("listings", [])) or None, "sourceRows": len(rows), "detailLevel": "full"}

def load_product(root: Path, product_id: str) -> dict | None:
    csv_path = latest_csv(root, product_id)
    if csv_path:
        offers, metadata = normalize_csv(csv_path, product_id)
    elif product_id == "zai":
        summary = max(root.glob("*-zai-summary.json"), default=None, key=lambda p: p.name)
        if not summary:
            return None
        data = json.loads(summary.read_text(encoding="utf-8"))
        offers, metadata = data["offers"], data["metadata"]
        metadata["sourcePath"] = str(summary).replace("docs/", "")
    else:
        return None
    allowed_tiers = PRODUCTS[product_id]["tiers"]
    return {"id": product_id, "label": PRODUCTS[product_id]["label"], "description": PRODUCTS[product_id]["description"], "allowedTiers": sorted(allowed_tiers) if allowed_tiers else None, "metadata": metadata, "offers": offers}

def main() -> int:
    args = parse_args()
    products = [item for product_id in PRODUCTS if (item := load_product(args.snapshots_root, product_id))]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"generatedAt": datetime.now(timezone.utc).isoformat(), "products": products}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Wrote catalogue: " + ", ".join(f"{p['id']}={len(p['offers'])}" for p in products))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
