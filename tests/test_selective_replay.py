"""Offline replay coverage for saved all-LLM CSV candidates."""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.replay_selective_analyzer import replay


def _listing(pid, option_text, price):
    return {
        "marketplace": "ggsel",
        "pid": pid,
        "url": f"https://example.test/p/{pid}",
        "title": "ChatGPT Pro подписка 1 месяц",
        "descText": "",
        "pageText": "",
        "initialPrices": [],
        "skippedControls": [],
        "options": [{
            "text": option_text,
            "clicked": True,
            "priceVerified": True,
            "priceStable": True,
            "prices": [{"text": f"{price:,}".replace(",", " ") + " ₽",
                        "cls": "ProductBuyBlock__amount"}],
        }],
        "error": None,
    }


def _llm_row(pid, option_text, delivery, price):
    return {
        "marketplace": "ggsel", "pid": pid,
        "url": f"https://example.test/p/{pid}",
        "title": "ChatGPT Pro подписка 1 месяц", "option_text": option_text,
        "tier": "Pro", "duration": "1m", "delivery": delivery,
        "price_rub": price, "strong_signal": "True", "glitched": "False",
        "source": "llm", "llm_evidence": "captured option price",
    }


def test_replay_limits_saved_rows_to_routed_pid_and_exact_captured_price(tmp_path):
    raw_path = tmp_path / "scan.raw.json"
    llm_path = tmp_path / "all-llm.csv"
    output_path = tmp_path / "selective.csv"
    raw_path.write_text(json.dumps({"listings": [
        _listing("clean", "Pro 1 месяц | Со входом", 7999),
        _listing("uncertain", "Pro 1 месяц", 8999),
    ]}), encoding="utf-8")

    saved_rows = [
        # Non-routed listing must not be considered even though it has a CSV row.
        _llm_row("clean", "Pro 1 месяц | Со входом", "new_account", 7999),
        _llm_row("uncertain", "Pro 1 месяц", "own_account", 8999),
        # Routed PID alone is insufficient: the captured selected-option price must match.
        _llm_row("uncertain", "Pro 1 месяц", "new_account", 9000),
    ]
    with llm_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(saved_rows[0]))
        writer.writeheader()
        writer.writerows(saved_rows)

    summary = replay(raw_path, llm_path, output_path)
    with output_path.open(encoding="utf-8-sig", newline="") as source:
        offers = list(csv.DictReader(source))
    by_pid = {row["pid"]: row for row in offers}

    assert summary["routedListings"] == 1
    assert summary["savedRowsForRoutedListings"] == 2
    assert summary["acceptedLlmRows"] == 1
    assert summary["outputRows"] == 2
    assert by_pid["clean"]["delivery"] == "own_account"
    assert by_pid["clean"].get("source", "") != "llm"
    assert by_pid["uncertain"]["delivery"] == "own_account"
    assert by_pid["uncertain"]["price_verified"] == "True"
    assert by_pid["uncertain"]["source"] == "llm"
