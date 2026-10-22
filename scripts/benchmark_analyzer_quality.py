#!/usr/bin/env python3
"""Score offer analyzers against a small, source-backed partial gold set.

The gold set is intentionally partial: this reports recall and correctness on
annotated rows, never global precision/accuracy for the whole marketplace.
Rows are joined by marketplace + pid + exact captured price so duplicate
variants on the same product page stay distinguishable.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def _canonical(field: str, value: object) -> str:
    text = str(value or "").strip().lower().replace("х", "x")
    if field == "tier":
        return {
            "pro x5": "pro 5x", "pro5x": "pro 5x", "pro 5x": "pro 5x",
            "pro x20": "pro 20x", "pro20x": "pro 20x", "pro 20x": "pro 20x",
            "go": "go", "plus": "plus", "pro": "pro", "pro+": "pro+",
            "business": "business", "max": "max", "lite": "lite", "ultra": "ultra",
        }.get(text, text)
    if field == "duration":
        return {"30d": "1m", "30 days": "1m", "90d": "3m", "90 days": "3m",
                "180d": "6m", "365d": "12m", "365 days": "12m"}.get(text, text)
    if field == "delivery":
        return text
    return text


def _price(value: object) -> int | None:
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _read_csv(path: Path) -> dict[tuple[str, str, int], list[dict]]:
    rows: dict[tuple[str, str, int], list[dict]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            price = _price(row.get("price_rub"))
            if price is None:
                continue
            key = (str(row.get("marketplace", "")), str(row.get("pid", "")), price)
            rows[key].append(row)
    return rows


def score(gold: list[dict], predictions: dict[tuple[str, str, int], list[dict]]) -> dict:
    # Price participates in the join key, so a matched row is also an exact
    # price hit. Keep it explicit in field metrics to match the gold metadata.
    fields = ("tier", "duration", "delivery", "price_rub")
    totals = Counter()
    correct = Counter()
    exact_rows = 0
    details = []
    for expected in gold:
        key = (expected["marketplace"], str(expected["pid"]), int(expected["price_rub"]))
        candidates = predictions.get(key, [])
        best = None
        best_hits = -1
        for candidate in candidates:
            hits = sum(
                field == "price_rub"
                or _canonical(field, candidate.get(field)) == _canonical(field, expected.get(field))
                for field in fields
            )
            if hits > best_hits:
                best, best_hits = candidate, hits
        if best is not None and best_hits == len(fields):
            exact_rows += 1
        for field in fields:
            totals[field] += 1
            if best is not None and (
                field == "price_rub"
                or _canonical(field, best.get(field)) == _canonical(field, expected.get(field))
            ):
                correct[field] += 1
        details.append({
            "key": {"marketplace": key[0], "pid": key[1], "price_rub": key[2]},
            "source_case": expected.get("source_case"),
            "present": best is not None,
            "expected": {field: expected[field] for field in fields},
            "observed": ({**{field: best.get(field) for field in fields if field != "price_rub"},
                          "price_rub": key[2]} if best else None),
            "exact_fields": best_hits if best else 0,
        })
    return {
        "gold_rows": len(gold),
        "predicted_rows": sum(map(len, predictions.values())),
        "row_recall": {"correct": sum(item["present"] for item in details), "total": len(gold)},
        "exact_rows": {"correct": exact_rows, "total": len(gold)},
        "fields": {name: {"correct": correct[name], "total": totals[name]} for name in fields},
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--prediction", action="append", required=True, metavar="NAME=CSV")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    gold_obj = json.loads(args.gold.read_text(encoding="utf-8"))
    gold = gold_obj["rows"]
    result = {
        "gold_description": gold_obj.get("description"),
        "gold_rows": len(gold),
        "predictions": {},
    }
    for spec in args.prediction:
        name, sep, filename = spec.partition("=")
        if not sep or not name or not filename:
            parser.error(f"invalid --prediction {spec!r}; use NAME=CSV")
        result["predictions"][name] = score(gold, _read_csv(Path(filename)))
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
