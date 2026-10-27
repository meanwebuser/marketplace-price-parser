"""Stable capture-shape fingerprints for detecting marketplace UI drift.

Fingerprints contain only parser-relevant structure, never listing text,
prices, proxy addresses, or seller stock fields.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PARSER_VERSION = 1


def _bucket(value: object) -> str:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return "unknown"
    if number <= 0:
        return "0"
    if number <= 2:
        return "1-2"
    if number <= 8:
        return "3-8"
    return "9+"


def listing_schema_descriptor(listing: dict) -> dict:
    """Describe the control/evidence layout without seller or price values."""
    options = listing.get("options") or []
    kinds = sorted({str(row.get("kind") or "unknown") for row in options if isinstance(row, dict)})
    methods = sorted({str(row.get("priceEvidenceMethod") or "unknown") for row in options if isinstance(row, dict)})
    return {
        "marketplace": str(listing.get("marketplace") or "unknown").lower(),
        "template": str(listing.get("template") or "unknown"),
        "controlCount": _bucket(listing.get("controlCount")),
        "variantControlCount": _bucket(listing.get("variantControlCount")),
        "optionCount": _bucket(len(options)),
        "optionKinds": kinds,
        "priceEvidenceMethods": methods,
        "hasSkippedControls": bool(listing.get("skippedControls")),
        "storeCurrency": str(listing.get("storeCurrency") or "unknown").upper(),
    }


def _signature(descriptor: dict) -> str:
    payload = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _previous_schema_path(family: str) -> Path | None:
    if family == "apple_gift_card":
        folder, pattern = ROOT / "docs" / "snapshots" / "targeted", "*-apple-us.raw.json"
    else:
        folder, pattern = ROOT / "docs" / "snapshots" / "data", f"*-{family}*.raw.json"
    paths = list(folder.glob(pattern))
    def order(path: Path):
        run_match = re.search(r"-(\d{4,6})\.raw\.json$", path.name)
        run_stamp = int(run_match.group(1)) if run_match else 0
        return path.name[:10], run_stamp, path.name
    paths.sort(key=order)
    return paths[-1] if paths else None


def annotate_schema(raw: dict, family: str) -> dict:
    """Attach a run inventory and compare against the last published schema set."""
    counts: Counter[str] = Counter()
    descriptors: dict[str, dict] = {}
    for listing in raw.get("listings", []):
        descriptor = listing_schema_descriptor(listing)
        signature = _signature(descriptor)
        listing["schemaFingerprint"] = signature
        counts[signature] += 1
        descriptors[signature] = descriptor

    previous_path = _previous_schema_path(family)
    previous_signatures: set[str] = set()
    if previous_path is not None:
        try:
            previous_raw = json.loads(previous_path.read_text(encoding="utf-8"))
            saved = (previous_raw.get("siteSchema") or {}).get("signatures", {})
            if saved:
                previous_signatures = set(saved)
            else:
                # Older snapshots predate fingerprints. Derive their baseline
                # from the same structural-only descriptor instead of treating
                # every current layout as an unknown schema forever.
                previous_signatures = {
                    _signature(listing_schema_descriptor(listing))
                    for listing in previous_raw.get("listings", [])
                }
        except (OSError, json.JSONDecodeError, TypeError):
            previous_path = None

    signatures = sorted(counts)
    new_signatures = sorted(set(signatures) - previous_signatures) if previous_signatures else []
    status = "baseline_missing" if not previous_signatures else "changed" if new_signatures else "stable"
    raw["siteSchema"] = {
        "parserVersion": SCHEMA_PARSER_VERSION,
        "status": status,
        "baselinePath": previous_path.relative_to(ROOT / "docs").as_posix() if previous_path else None,
        "signatureCount": len(signatures),
        "signatures": {signature: {"count": counts[signature], "shape": descriptors[signature]}
                       for signature in signatures},
        "newSignatures": new_signatures,
        "driftDetected": status == "changed",
    }
    return raw
