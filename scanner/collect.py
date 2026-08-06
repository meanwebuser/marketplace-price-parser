"""Run click.py as a subprocess to collect raw price data for a list of
listings discovered by scanner/discover.py."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
CLICK_JS = ROOT / "click.py"


def collect(
    candidates: Sequence[dict] | None = None,
    out_path: Path | None = None,
    *,
    workers: int = 6,
    plati_pids: Sequence[int | str] | None = None,
    ggsel_ids: Sequence[str] | None = None,
) -> dict:
    """Invoke click.py with --plati-pids / --ggsel-ids derived from
    candidates (or from explicit plati_pids/ggsel_ids kwargs).
    Returns the parsed JSON result. Raises on subprocess failure."""
    if out_path is None:
        raise ValueError("out_path is required")
    plati = list(plati_pids or [])
    ggsel = list(ggsel_ids or [])
    if candidates:
        for c in candidates:
            if c.get("source") == "plati" and c.get("native_id"):
                plati.append(str(c["native_id"]))
            elif c.get("source") == "ggsel" and c.get("native_id"):
                ggsel.append(c["native_id"])
    # Dedupe while preserving order
    seen = set()
    plati_unique = []
    for p in plati:
        if p not in seen:
            seen.add(p)
            plati_unique.append(p)
    seen = set()
    ggsel_unique = []
    for g in ggsel:
        if g not in seen:
            seen.add(g)
            ggsel_unique.append(g)

    cmd = ["node", str(CLICK_JS), "--workers", str(workers), "--out", str(out_path)]
    if plati_unique:
        cmd.extend(["--plati-pids", ",".join(plati_unique)])
    if ggsel_unique:
        cmd.extend(["--ggsel-ids", ",".join(ggsel_unique)])

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"click.py failed: {proc.stderr or proc.stdout}")
    return json.loads(Path(out_path).read_text())


if __name__ == "__main__":
    import argparse
    from scanner.discover import discover_all
    from families import FAMILY_REGISTRY

    p = argparse.ArgumentParser()
    p.add_argument("--family", required=True, choices=list(FAMILY_REGISTRY))
    p.add_argument("--max", type=int, default=80)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--out", default="/tmp/raw.json")
    args = p.parse_args()

    family = FAMILY_REGISTRY[args.family]
    discovery = discover_all(family, args.max)
    print(f"discovery: plati={discovery['plati_found']}, ggsel={discovery['ggsel_found']}")
    result = collect(discovery["candidates"], Path(args.out), workers=args.workers)
    print(f"collected: {len(result['listings'])} listings → {args.out}")
