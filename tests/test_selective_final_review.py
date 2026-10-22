"""Regression cases for raw field evidence and empty-discovery provenance."""

from argparse import Namespace
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer.selective import merge_selective_offers


def _listing(title="ChatGPT Pro подписка 1 месяц", option_text="Pro 1 месяц | Со входом"):
    return {
        "marketplace": "ggsel",
        "pid": "raw-pid",
        "title": title,
        "descText": "",
        "pageText": "",
        "options": [{
            "text": option_text,
            "clicked": True,
            "priceVerified": True,
            "priceStable": True,
            "prices": [{"text": "7 999 ₽", "cls": "ProductBuyBlock__amount"}],
        }],
    }


def _baseline(option_text):
    return {
        "marketplace": "ggsel", "pid": "raw-pid", "option_text": option_text,
        "raw_option_text": option_text, "tier": "", "duration": "",
        "delivery": "unknown", "price_rub": 7999, "price_verified": False,
        "strong_signal": False,
    }


def _candidate(option_text, *, tier="Pro", duration="1m"):
    return {
        "marketplace": "ggsel", "pid": "raw-pid", "option_text": option_text,
        "tier": tier, "duration": duration, "delivery": "own_account",
        "price_rub": 7999, "strong_signal": True, "glitched": False,
    }


@pytest.mark.parametrize(
    ("listing", "candidate"),
    [
        (
            _listing(),
            _candidate("Pro 1 месяц | Со входом", tier="Plus"),
        ),
        (
            _listing(option_text="Pro 3 месяца | Со входом"),
            _candidate("Pro 3 месяца | Со входом", duration="3m"),
        ),
        (
            _listing(title="Подписка ChatGPT на месяц", option_text="1 месяц | Со входом"),
            _candidate("1 месяц | Со входом", tier="Pro"),
        ),
    ],
    ids=["tier-conflict", "duration-conflict", "tier-unresolved"],
)
def test_selective_merge_rejects_tier_or_duration_without_matching_raw_evidence(listing, candidate):
    deterministic = _baseline(listing["options"][0]["text"])

    merged = merge_selective_offers([deterministic], [candidate], [listing])

    assert merged == [deterministic]


def test_run_one_preserves_discovery_failure_metadata_when_no_candidates(monkeypatch, tmp_path):
    import cli

    discovery = {
        "candidates": [],
        "plati_found": 0,
        "ggsel_found": 0,
        "transports": {"plati": "error: 503", "ggsel": "playwright-partial"},
        "errors": ["Plati query failed: HTTP 503", "GGSEL request failed after retries: 404"],
    }
    monkeypatch.setattr(cli, "discover_all", lambda *_args: discovery)
    monkeypatch.setattr(
        cli, "collect",
        lambda *_args, **_kwargs: pytest.fail("collect must not run without candidates"),
    )

    raw = cli._run_one(
        SimpleNamespace(name="chatgpt"),
        Namespace(skip_discover=False, max=80, workers=1, headless=True),
        tmp_path / "raw.json",
    )

    assert raw == {
        "listings": [],
        "discovery": {
            "platiFound": 0,
            "ggselFound": 0,
            "transports": discovery["transports"],
            "errors": discovery["errors"],
        },
    }
