import json
import subprocess
from pathlib import Path
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


def _fake_run(monkeypatch, *, observed, returncode=0, verified=True, selected=True, selection_evidence=None):
    def run(command, **kwargs):
        payload = json.loads(open(command[command.index("--input") + 1], encoding="utf-8").read())
        requested = payload["offers"][0]
        result = {
            **requested,
            "observedPrice": observed,
            "selected": selected,
            "selectionEvidence": selection_evidence,
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


def test_final_verifier_accepts_stable_price_change_when_site_has_no_selected_marker(monkeypatch):
    winner = _offer()
    _fake_run(monkeypatch, observed=1234, selected=False, selection_evidence="stable_price_change")

    results = final_verify.verify_winners([winner], [winner])

    assert results[0]["selected"] is False
    assert results[0]["selectionEvidence"] == "stable_price_change"
    assert winner["final_verified"] is True
    assert winner["final_observed_price"] == 1234


def test_final_verifier_sends_fixed_product_evidence_to_independent_browser(monkeypatch):
    winner = _offer()
    winner.update({
        "control_kind": "fixed-denomination", "region": "US",
        "denomination": 50, "denomination_currency": "USD",
    })
    captured = {}

    def run(command, **_kwargs):
        payload = json.loads(Path(command[command.index("--input") + 1]).read_text())
        captured.update(payload["offers"][0])
        report = {**payload["offers"][0], "observedPrice": 1234, "selected": True,
                  "selectionEvidence": "fixed_product", "stable": True, "verified": True}
        Path(command[command.index("--out") + 1]).write_text(json.dumps({"results": [report]}))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(final_verify.subprocess, "run", run)
    final_verify.verify_winners([winner], [winner])

    assert captured["controlKind"] == "fixed-denomination"
    assert captured["region"] == "US"
    assert captured["denomination"] == 50
    assert captured["denominationCurrency"] == "USD"


def test_final_verifier_rejects_price_mismatch_without_known_price_fixture(monkeypatch):
    winner = _offer(price=7319)
    _fake_run(monkeypatch, observed=8241, returncode=1, verified=False)

    with pytest.raises(RuntimeError, match="final browser verification failed"):
        final_verify.verify_winners([winner], [winner])

    assert winner["final_verified"] is False


def test_python_contract_rejects_forged_success_report(monkeypatch):
    winner = _offer(price=7319)
    _fake_run(monkeypatch, observed=8241, returncode=0, verified=True)

    with pytest.raises(RuntimeError, match="violates invariants"):
        final_verify.verify_winners([winner], [winner])


def test_final_verifier_uses_task_local_temp_directory(monkeypatch, tmp_path):
    winner = _offer()
    task_temp = tmp_path / "nested" / "final_verify"
    monkeypatch.setattr(final_verify, "FINAL_VERIFY_TMP_DIR", task_temp)
    observed_input_parents = []

    def run(command, **kwargs):
        input_path = Path(command[command.index("--input") + 1])
        output_path = Path(command[command.index("--out") + 1])
        observed_input_parents.append(input_path.parent.parent)
        requested = json.loads(input_path.read_text(encoding="utf-8"))["offers"][0]
        result = {
            **requested,
            "observedPrice": 1234,
            "selected": True,
            "stable": True,
            "verified": True,
            "error": None,
        }
        output_path.write_text(json.dumps({"results": [result]}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(final_verify.subprocess, "run", run)
    final_verify.verify_winners([winner], [winner])

    assert observed_input_parents == [task_temp]
    assert task_temp.is_dir()
    assert list(task_temp.iterdir()) == []


def test_verify_control_identity_ignores_trailing_rendered_separator():
    script = """
const {controlKey} = require('./scanner/variant_key');
const expected = controlKey('Тариф «Макс» | 1 месяц');
const rendered = controlKey('Тариф «Макс» | 1 месяц |');
if (expected !== rendered) process.exit(1);
"""
    subprocess.run(["node", "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
