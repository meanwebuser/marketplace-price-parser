#!/usr/bin/env python3
"""Build the GitHub Pages catalogue from the newest committed scan per product."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from families.kimi import CONFIG as KIMI_CONFIG
from families.minimax import CONFIG as MINIMAX_CONFIG
from families.zai import CONFIG as ZAI_CONFIG

PRODUCTS = {
    "minimax": {"label": "MiniMax M Plan / Token Plan", "description": "M Plan: GO, Explore и Build. Сохранены прежние варианты Token Plan: Plus, Max и Ultra.", "tiers": {"GO", "Explore", "Build", "Plus", "Max", "Ultra"}},
    "chatgpt": {"label": "ChatGPT", "description": "Последний сохранённый скан предложений ChatGPT.", "tiers": None},
    "zai": {"label": "Z.ai GLM Coding", "description": "Сохранённые варианты GLM Coding с GGSEL и Plati.", "tiers": None},
    "kimi": {"label": "Kimi", "description": "Сохранённые предложения Kimi на GGSEL и Plati.", "tiers": None},
    "claude": {"label": "Claude", "description": "Сохранённые предложения Claude на GGSEL и Plati.", "tiers": {"Pro", "Max"}},
}
GIFT_CARDS = {
    "apple_us": {"kind": "gift_card", "label": "Apple Gift Card · США", "description": "Цифровые Apple gift cards для Apple Account региона США. Номинал и цена показываются отдельно; коды других регионов не смешиваются.", "region": "US", "tiers": None},
    "apple_tr": {"kind": "gift_card", "label": "Apple Gift Card · Турция", "description": "Цифровые Apple gift cards для Apple Account региона Турция. Номинал и цена показываются отдельно; коды других регионов не смешиваются.", "region": "TR", "tiers": None},
}
PRODUCT_CONFIGS = {**PRODUCTS, **GIFT_CARDS}
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})-(minimax|chatgpt|zai|kimi|claude|apple[-_]us|apple[-_]tr)")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-root", type=Path, default=Path("docs/snapshots/data"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--preserve-existing-products", action="store_true",
                         help="refresh the separate giftCards collection while retaining AI product rows exactly")
    return parser.parse_args()

def as_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}

def latest_csv(root: Path, product_id: str) -> Path | None:
    pattern_id = product_id.replace("_", "[-_]") if product_id.startswith("apple_") else product_id
    files = [p for p in root.glob(f"*-{pattern_id}*.csv") if DATE_PREFIX.match(p.name)]
    return max(files, default=None, key=lambda p: p.name)

def gift_card_price_check_supplements(csv_path: Path) -> list[tuple[Path, dict]]:
    """Load dated manual price checks that explicitly name this immutable scan."""
    match = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)\.csv$", csv_path.name)
    if not match:
        return []
    family = match.group(1)
    supplements = []
    for path in sorted(csv_path.parent.glob(f"*-{family}-price-checks.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("sourceSnapshot") == csv_path.name and isinstance(data.get("manualPriceChecks"), list):
            supplements.append((path, data))
    return supplements

def docs_source_path(source: Path, *, docs_root: Path | None = None) -> str:
    """Return a portable provenance path and reject traversal/symlink escapes."""
    root = (docs_root if docs_root is not None else ROOT / "docs").resolve()
    try:
        return source.resolve().relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"Snapshot source is outside docs root: {source}") from error

def normalize_csv(csv_path: Path, product_id: str, *, docs_root: Path | None = None) -> tuple[list[dict], dict]:
    if PRODUCT_CONFIGS[product_id].get("kind") == "gift_card":
        return normalize_gift_card_csv(csv_path, product_id, docs_root=docs_root)
    source_path = docs_source_path(csv_path, docs_root=docs_root)
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    offers = []
    allowed_tiers = PRODUCTS[product_id]["tiers"]
    for row in rows:
        title, tier = row.get("title", ""), row.get("tier", "unknown")
        if product_id == "minimax" and MINIMAX_CONFIG.eligibility_extra and not MINIMAX_CONFIG.eligibility_extra(row):
            continue
        if product_id == "zai" and ZAI_CONFIG.eligibility_extra and not ZAI_CONFIG.eligibility_extra(row):
            continue
        if product_id == "kimi" and KIMI_CONFIG.eligibility_extra and not KIMI_CONFIG.eligibility_extra({
            "title": title,
            "option_text": row.get("option_text", ""),
            "raw_option_text": row.get("raw_option_text", ""),
        }):
            continue
        if allowed_tiers and tier not in allowed_tiers:
            continue
        # Old snapshots predate these columns and remain readable.  New scans
        # explicitly state both invariants; unsafe rows must never be published.
        if row.get("available") not in (None, "") and not as_bool(row.get("available")):
            continue
        try:
            price = float(row["price_rub"])
        except (KeyError, TypeError, ValueError):
            continue
        if row.get("price_verified") not in (None, "") and not as_bool(row.get("price_verified")):
            # An independent final browser check can supersede failed
            # collection, but only for the exact price being published.
            try:
                final_price = float(row.get("final_observed_price", ""))
            except (TypeError, ValueError):
                continue
            if not as_bool(row.get("final_verified")) or not math.isfinite(final_price) or final_price != price:
                continue
        item = {"marketplace": row.get("marketplace", "unknown"), "pid": row.get("pid", ""), "url": row.get("url", ""), "title": title, "optionText": row.get("option_text", ""), "tier": tier, "duration": row.get("duration", "unknown"), "delivery": row.get("delivery", "unknown"), "priceRub": price, "strongSignal": as_bool(row.get("strong_signal")), "glitched": as_bool(row.get("glitched")), "glitchReason": row.get("glitch_reason", ""), "available": True, "priceVerified": True, "finalVerified": as_bool(row.get("final_verified"))}
        if seller_note := str(row.get("seller_note") or "").strip():
            item.update(sellerNote=seller_note, sellerNoteVerified=False)
        offers.append(item)
    raw_path = csv_path.with_suffix(".raw.json")
    raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
    final_results = raw.get("finalVerification", {}).get("results", [])
    return offers, {"scanDate": csv_path.name[:10], "sourcePath": source_path, "scanStartedAt": raw.get("startedAt"), "scanCompletedAt": raw.get("finishedAt") or raw.get("lastUpdate"), "listings": len(raw.get("listings", [])) or None, "sourceRows": len(rows), "publishedRows": len(offers), "finalVerifiedWinners": sum(1 for item in final_results if item.get("verified")), "detailLevel": "full"}


def normalize_gift_card_csv(csv_path: Path, product_id: str, *, docs_root: Path | None = None) -> tuple[list[dict], dict]:
    """Normalize gift cards with region and denomination, no fake tier/term."""
    source_path = docs_source_path(csv_path, docs_root=docs_root)
    spec = PRODUCT_CONFIGS[product_id]
    expected_currency = {"US": "USD", "TR": "TRY"}[spec["region"]]
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    raw_path = csv_path.with_suffix(".raw.json")
    raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
    final_results = raw.get("finalVerification", {}).get("results", [])
    price_check_supplements = gift_card_price_check_supplements(csv_path)
    manual_price_checks = [check for _, supplement in price_check_supplements for check in supplement["manualPriceChecks"]]
    price_check_by_offer = {
        (str(check.get("marketplace", "")).lower(), str(check.get("pid", "")), str(check.get("optionText", ""))): check
        for check in manual_price_checks
    }
    offers = []
    for row in rows:
        if str(row.get("region", "")).upper() != spec["region"]:
            continue
        variant_snapshot_verified = False
        variant_snapshot_evidence = None
        if "face_value_usd" in row:
            # Current manual option captures have one row per rendered variant.
            # Publish only explicitly mapped USD denominations with live RUB
            # totals, a live status, an enabled option, and a modifier sum that
            # independently matches the captured effective total.
            if (
                spec["region"] != "US"
                or row.get("comparison_status") != "confirmed option mapping"
                or row.get("http_status") != "200"
                or row.get("disabled", "").lower() != "false"
                or "USD/$" not in str(row.get("face_evidence", ""))
                or row.get("modifier_currency") != "RUB"
                or not str(row.get("variant_id", "")).strip()
            ):
                continue
            try:
                denomination = float(row["face_value_usd"])
                base_price = float(row["base_price_rub"])
                modifier = float(row.get("modifier") or 0)
                price = float(row["effective_total_rub"])
                reported_ratio = float(row["rub_per_usd"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not all(math.isfinite(value) and value > 0 for value in (denomination, base_price, price, reported_ratio))
                or not math.isfinite(modifier) or modifier < 0
                or not math.isclose(base_price + modifier, price, rel_tol=0, abs_tol=0.01)
                or not math.isclose(price / denomination, reported_ratio, rel_tol=0, abs_tol=0.0001)
            ):
                continue
            denomination_text = row.get("denomination_label") or f"{denomination:g} USD"
            currency_raw = "USD"
            verified = True
            variant_snapshot_verified = True
            variant_snapshot_evidence = {
                "variantId": row["variant_id"],
                "faceEvidence": row["face_evidence"],
                "basePriceRub": base_price,
                "modifierRub": modifier,
                "comparisonStatus": row["comparison_status"],
            }
        else:
            denomination_text = row.get("denomination") or row.get("default_denomination") or ""
            currency_raw = str(row.get("denomination_currency", "")).upper()
            if not currency_raw:
                currency_match = re.search(r"\b(USD|TRY|TL)\b|\$|₺", denomination_text, re.I)
                if currency_match:
                    currency_raw = currency_match.group(1).upper() if currency_match.group(1) else ("USD" if "$" in currency_match.group(0) else "TRY")
            if currency_raw == "TL":
                currency_raw = "TRY"
        # The manual snapshot collector records default options in a compact
        # denomination field and an explicit evidence status; the normal CLI
        # writes parsed fields. Accept both formats without treating a listing
        # card's generic metadata price as a selected variant price.
        if currency_raw != expected_currency:
            continue
        if not variant_snapshot_verified:
            try:
                amount_text = row.get("denomination", "") or denomination_text
                amount_match = re.search(r"\d+(?:[.,]\d{1,2})?", str(amount_text))
                denomination = float(amount_match.group(0).replace(",", ".")) if amount_match else 0
                price = float(row.get("price_rub", ""))
            except (TypeError, ValueError):
                continue
            verified = as_bool(row.get("price_verified"))
        check_key = (
            str(row.get("marketplace", "")).lower(),
            str(row.get("pid") or row.get("listing_id", "")),
            str(row.get("option_text") or row.get("denomination_label", "")),
        )
        manual_price_check = price_check_by_offer.get(check_key)
        if manual_price_check:
            try:
                price = float(manual_price_check["observedPriceRub"])
            except (KeyError, TypeError, ValueError):
                manual_price_check = None
            else:
                verified = True
        if not math.isfinite(denomination) or denomination <= 0 or not math.isfinite(price) or price <= 0:
            continue
        if row.get("available") not in (None, "") and not as_bool(row.get("available")):
            continue
        manual_snapshot_verified = (
            row.get("price_evidence_status") == "verified_ssr_offer_plus_default_variant_zero_modifier"
            and str(row.get("http_status", "")) == "200"
        )
        final_price = None
        try:
            final_price = float(row.get("final_observed_price", ""))
        except (TypeError, ValueError):
            pass
        final_verified = bool(manual_price_check) or (as_bool(row.get("final_verified")) and final_price == price)
        if not verified and not final_verified and not manual_snapshot_verified:
            continue
        availability_status = str(row.get("availability_status") or "").strip().lower()
        if availability_status not in {"in_stock", "out_of_stock", "unknown"}:
            if row.get("available") in (None, ""):
                availability_status = "unknown"
            else:
                availability_status = "in_stock" if as_bool(row.get("available")) else "out_of_stock"
        available = {"in_stock": True, "out_of_stock": False, "unknown": None}[availability_status]
        offers.append({
            "marketplace": str(row.get("marketplace") or ("ggsel" if "ggsel.net" in str(row.get("url", "")).lower() else "unknown")).lower(),
            "pid": row.get("pid") or row.get("listing_id", ""), "url": row.get("url", ""),
            "title": row.get("title", ""), "optionText": row.get("option_text") or row.get("denomination_label", ""),
            "region": spec["region"], "denomination": denomination,
            "denominationCurrency": expected_currency, "pricePerUnit": price / denomination,
            "delivery": row.get("delivery", "unknown"),
            "automaticDelivery": as_bool(row.get("automatic_delivery")),
            "priceRub": price, "strongSignal": as_bool(row.get("strong_signal")),
            "available": available, "availabilityStatus": availability_status,
            "availabilityEvidence": row.get("availability_evidence") or row.get("availability_reason") or "stock status not captured",
            "priceVerified": True, "finalVerified": final_verified,
            **({"manualPriceCheckDate": manual_price_check.get("checkedDate")} if manual_price_check else {}),
            **({"seller": row["seller"]} if row.get("seller") else {}),
            **({"variantId": row["variant_id"]} if row.get("variant_id") else {}),
            **({"priceEvidence": variant_snapshot_evidence} if variant_snapshot_evidence else {}),
            **({"priceEvidenceStatus": row["comparison_status"]} if variant_snapshot_verified else {}),
            **({"availabilityCapturedAt": row["availability_captured_at_utc"]} if row.get("availability_captured_at_utc") else {}),
            **({"priceEvidenceStatus": row["price_evidence_status"]} if manual_snapshot_verified else {}),
        })
    metadata = {
        "scanDate": csv_path.name[:10], "sourcePath": source_path,
        "scanStartedAt": raw.get("startedAt"),
        "scanCompletedAt": raw.get("finishedAt") or raw.get("lastUpdate"),
        "listings": len(raw.get("listings", [])) or None,
        "sourceRows": len(rows), "publishedRows": len(offers),
        "finalVerifiedWinners": sum(1 for item in final_results if item.get("verified")),
        "manualPriceChecks": len(manual_price_checks),
        "manualPriceChecksDate": max((item.get("checkedDate", "") for item in manual_price_checks), default="") or None,
        "priceCheckSourcePath": docs_source_path(price_check_supplements[-1][0], docs_root=docs_root) if price_check_supplements else None,
        "detailLevel": "full",
    }
    return offers, metadata

def load_product(root: Path, product_id: str) -> dict | None:
    csv_path = latest_csv(root, product_id)
    if csv_path is None and PRODUCT_CONFIGS[product_id].get("kind") == "gift_card":
        # Targeted prepaid scans live beside, not inside, the AI subscription
        # snapshots. Fall back only for gift cards so a one-off tier refresh
        # can never replace a whole service-family snapshot.
        csv_path = latest_csv(ROOT / "docs/snapshots/targeted", product_id)
    if csv_path:
        offers, metadata = normalize_csv(csv_path, product_id)
    elif product_id == "zai":
        summary = max(root.glob("*-zai-summary.json"), default=None, key=lambda p: p.name)
        if not summary:
            return None
        data = json.loads(summary.read_text(encoding="utf-8"))
        offers, metadata = data["offers"], data["metadata"]
        metadata["sourcePath"] = docs_source_path(summary)
    else:
        return None
    allowed_tiers = PRODUCT_CONFIGS[product_id]["tiers"]
    item = {"id": product_id, "label": PRODUCT_CONFIGS[product_id]["label"], "description": PRODUCT_CONFIGS[product_id]["description"], "allowedTiers": sorted(allowed_tiers) if allowed_tiers else None, "metadata": metadata, "offers": offers}
    if PRODUCT_CONFIGS[product_id].get("kind"):
        item["kind"] = PRODUCT_CONFIGS[product_id]["kind"]
        item["region"] = PRODUCT_CONFIGS[product_id].get("region")
    return item


def catalogue_data(products: list[dict], gift_cards: list[dict], *, existing: dict | None = None,
                   preserve_existing_products: bool = False) -> dict:
    """Keep prepaid offers structurally separate; optionally preserve AI rows byte-for-byte."""
    if preserve_existing_products and existing is not None:
        products = existing.get("products", products)
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "products": products,
        "giftCards": gift_cards,
    }

def main() -> int:
    args = parse_args()
    products = [item for product_id in PRODUCTS if (item := load_product(args.snapshots_root, product_id))]
    gift_cards = [item for product_id in GIFT_CARDS if (item := load_product(args.snapshots_root, product_id))]
    existing = json.loads(args.out.read_text(encoding="utf-8")) if args.preserve_existing_products and args.out.exists() else None
    catalogue = catalogue_data(products, gift_cards, existing=existing,
                               preserve_existing_products=args.preserve_existing_products)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = [f"{p['id']}={len(p['offers'])}" for p in catalogue["products"]]
    counts.extend(f"giftCards.{item['id']}={len(item['offers'])}" for item in gift_cards)
    print("Wrote catalogue: " + ", ".join(counts))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
