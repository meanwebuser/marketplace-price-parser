#!/usr/bin/env python3
"""Backward-compat shim: the original best_chatgptplus_prices.py had its
own CLI / purpose-preset logic. The new family-aware pipeline replaces
it; this wrapper preserves the old CLI by delegating to cli.py."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cli import main as cli_main


def _translate_args(argv: list[str]) -> list[str]:
    out = ["--family", "chatgpt"]
    known = {"--top", "--delivery", "--purpose", "--exclude-delivery",
             "--exclude-shared", "--usd-rub", "--llm", "--llm-required",
             "--llm-base-url", "--llm-model", "--json", "--out"}

    # Map --purpose to family purpose preset
    purpose = None
    body = []
    unsupported = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--purpose":
            purpose = argv[i + 1] if i + 1 < len(argv) else "renew"
            i += 2
            continue
        if a in known:
            unsupported.append(a)
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                unsupported.append(argv[i + 1])
                i += 2
            else:
                i += 1
            continue
        body.append(a)
        i += 1
    if purpose:
        # FamilyConfig uses purpose_preset directly; we read it via env
        # import here to avoid circular
        import os
        os.environ["CHATGPT_PURPOSE"] = purpose
        out.extend(["--purpose", purpose])
    out.extend(body)
    if unsupported:
        print(f"note: legacy flags dropped: {unsupported}", file=sys.stderr)
        print("  use cli.py --family chatgpt --help for the new options", file=sys.stderr)
    return out


if __name__ == "__main__":
    sys.exit(cli_main(_translate_args(sys.argv[1:])))
