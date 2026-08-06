"""Backward-compat shim: the original minimax_max_prices.py had its
own discovery + crawler + Gemma4 validation pipeline. The new
family-aware pipeline replaces it; this wrapper preserves the old CLI
by delegating to cli.py."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cli import main as cli_main


def _translate_args(argv: list[str]) -> list[str]:
    """Map old CLI flags to new ones. Unknown flags are dropped with a
    warning so the user can see what didn't translate."""
    out = ["--family", "minimax"]
    known = {"--usd-rub", "--top", "--skip-marketplaces", "--manual-candidates",
             "--search-query", "--max-discovered", "--llm", "--llm-required",
             "--llm-base-url", "--llm-model", "--json", "--out"}
    deprecated = set(known)
    dropped = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in known:
            dropped.append(a)
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                dropped.append(argv[i + 1])
                i += 2
            else:
                i += 1
            continue
        out.append(a)
        i += 1
    if dropped:
        print(f"note: legacy flags dropped (no equivalent in new pipeline): {dropped}", file=sys.stderr)
        print("  see minimax_max_prices.legacy for the original behavior", file=sys.stderr)
    return out


if __name__ == "__main__":
    sys.exit(cli_main(_translate_args(sys.argv[1:])))
