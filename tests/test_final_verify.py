import json
from types import SimpleNamespace

import pytest

from scanner import final_verify


def _offer(price=1234):
    return {
        "marketplace": "market",
        "pid": "random-id",
        "url": "https://example.test/random-id",
        "option_text": "Arbitrary tier | 1 month",
        "raw_option_text": "Arbitrary tier | 1 month\n+999 RUB",
        "control_kind": "label",
        "control_dom_index": 7,
        "tier": "Arbitrary",
        "duration": "1m",
        "delivery": "own_account",
        "price_rub": price,
        "final_verified": False,
        "final_observed_price": None,
    }


def _fake_run(monkeypatch, *, observed, returncode=0, verified=True):
    def run(command, **kwargs):
        payload = json.loads(open(command[command.index("--input") + 1], encoding="utf-8").read())
        requested = payload["offers"][0]
        result = {
            **requested,
            "observedPrice": observed,
            "selected": True,
            "stable": True,
            "verified": verified,
            "error": None if verified else "price mismatch",
        }
        with open(command[command.index("--out") + 1], "w", encoding="utf-8") as target:
            json.dump({"results": [result]}, target)
        return SimpleNamespace(returncode=returncode, stderr="", stdout="")
    monkeypatch.setattr(final_verify.subprocess, "run", run)


def test_final_verifier_annotates_only_independently_confirmed_winner(monkeypatch):
    winner = _offer()
    rows = [winner, {**_offer(2000), "pid": "other"}]
    _fake_run(monkeypatch, observed=1234)

    results = final_verify.verify_winners([winner], rows)

    assert results[0]["verified"] is True
    assert winner["final_verified"] is True
    assert winner["final_observed_price"] == 1234
    assert rows[1]["final_verified"] is False


def test_final_verifier_rejects_price_mismatch_without_known_price_fixture(monkeypatch):
    winner = _offer(price=7319)
    _fake_run(monkeypatch, observed=8241, returncode=1, verified=False)

    with pytest.raises(RuntimeError, match="final browser verification failed"):
        final_verify.verify_winners([winner], [winner])

    assert winner["final_verified"] is False
