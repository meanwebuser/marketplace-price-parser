"""Independent browser verification for the offers selected as winners.

This pass intentionally does not reuse the collector page or DOM state.  It
opens every winner in a fresh browser context, performs a native click, and
requires both a selected-state signal and a stable primary buy-block price.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
VERIFY_JS = ROOT / "verify_winners.js"


def _identity(offer: dict) -> tuple:
    return (
        offer.get("marketplace"), str(offer.get("pid")),
        offer.get("raw_option_text") or offer.get("option_text"),
        offer.get("tier"), offer.get("duration"), offer.get("delivery"),
    )


def verify_winners(winners: Iterable[dict], all_offers: list[dict]) -> list[dict]:
    """Verify winners and annotate their matching offer rows.

    Raises RuntimeError unless every requested winner is independently tied to
    the exact same price.  The contract contains no known product IDs, sellers,
    or expected market prices: the expected values are the current run's own
    ranking output.
    """
    requested = list(winners)
    if not requested:
        return []
    payload = {
        "offers": [
            {
                "marketplace": item.get("marketplace"),
                "pid": item.get("pid"),
                "url": item.get("url"),
                "optionText": item.get("raw_option_text") or item.get("option_text", ""),
                "controlKind": item.get("control_kind"),
                "controlDomIndex": item.get("control_dom_index"),
                "controlInputId": item.get("control_input_id"),
                "controlValue": item.get("control_value"),
                "tier": item.get("tier"),
                "duration": item.get("duration"),
                "delivery": item.get("delivery"),
                "expectedPrice": item.get("price_rub"),
            }
            for item in requested
        ]
    }
    with tempfile.TemporaryDirectory(prefix="price-final-verify-") as directory:
        input_path = Path(directory) / "input.json"
        output_path = Path(directory) / "output.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            ["node", str(VERIFY_JS), "--input", str(input_path), "--out", str(output_path)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        report = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else {}
        results = report.get("results", [])
        expected = {
            (
                item.get("marketplace"), str(item.get("pid")),
                item.get("raw_option_text") or item.get("option_text"),
                item.get("tier"), item.get("duration"), item.get("delivery"),
            ): item
            for item in requested
        }
        seen: set[tuple] = set()
        failures = []
        for item in results:
            key = (
                item.get("marketplace"), str(item.get("pid")), item.get("optionText"),
                item.get("tier"), item.get("duration"), item.get("delivery"),
            )
            wanted = expected.get(key)
            invariant_ok = bool(
                wanted is not None
                and key not in seen
                and item.get("verified")
                and item.get("selected")
                and item.get("stable")
                and item.get("observedPrice") == wanted.get("price_rub")
            )
            seen.add(key)
            if not invariant_ok:
                failed = dict(item)
                failed["error"] = failed.get("error") or "verification report violates invariants"
                failures.append(failed)
        if proc.returncode or len(results) != len(requested) or failures:
            details = "; ".join(
                f"{item.get('url')}: {item.get('error') or 'verification failed'}"
                for item in failures
            ) or (proc.stderr.strip() or "verifier returned an incomplete report")
            raise RuntimeError(f"final browser verification failed: {details}")

    by_identity = {_identity(item): item for item in requested}
    for result in results:
        key = (
            result.get("marketplace"), str(result.get("pid")), result.get("optionText"),
            result.get("tier"), result.get("duration"), result.get("delivery"),
        )
        winner = by_identity.get(key)
        if winner is None:
            raise RuntimeError("final browser verification returned an unknown offer")
        winner["final_verified"] = True
        winner["final_observed_price"] = result["observedPrice"]
        for offer in all_offers:
            if _identity(offer) == _identity(winner):
                offer["final_verified"] = True
                offer["final_observed_price"] = result["observedPrice"]
    return results
