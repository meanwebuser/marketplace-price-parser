"""Ensure a failed winner check is recorded before the CLI propagates it."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli
from scanner import final_verify
from scanner.final_verify import FinalVerificationError


def test_cli_persists_structured_failed_final_verification_before_raising(monkeypatch, tmp_path):
    raw_path = tmp_path / "family.raw.json"
    raw = {"listings": [{"pid": "seller-item"}]}
    failed_results = [{
        "marketplace": "ggsel",
        "pid": "seller-item",
        "verified": False,
        "selected": True,
        "stable": False,
        "observedPrice": 8200,
        "error": "price mismatch",
    }]
    failure = FinalVerificationError(
        "final browser verification failed: example.test: price mismatch",
        failed_results,
    )

    def fail_verification(_targets, _offers):
        raise failure

    monkeypatch.setattr(cli, "verify_winners", fail_verification)

    with pytest.raises(FinalVerificationError, match="price mismatch"):
        cli._verify_winners_and_persist_failure(raw, [{}], [{}], raw_path)

    saved = json.loads(raw_path.read_text(encoding="utf-8"))
    assert saved["finalVerification"] == {
        "skipped": False,
        "failed": True,
        "error": str(failure),
        "results": failed_results,
    }


def test_cli_persists_top_level_verifier_startup_error_with_no_results(monkeypatch, tmp_path):
    raw_path = tmp_path / "family.raw.json"
    raw = {"listings": []}
    stack = "Error: browser binary failed to start\n  at launch (/verify.js:12:3)"
    winner = {
        "marketplace": "ggsel", "pid": "native-id", "url": "https://example.test/item",
        "option_text": "Pro 1 месяц", "tier": "Pro", "duration": "1m",
        "delivery": "own_account", "price_rub": 7999,
    }

    def subprocess_run(command, **_kwargs):
        output_path = Path(command[command.index("--out") + 1])
        output_path.write_text(json.dumps({"results": [], "error": stack}), encoding="utf-8")
        return type("Proc", (), {"returncode": 1, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(final_verify, "FINAL_VERIFY_TMP_DIR", tmp_path / "verify-temp")
    monkeypatch.setattr(final_verify.subprocess, "run", subprocess_run)
    monkeypatch.setattr(cli, "verify_winners", final_verify.verify_winners)

    with pytest.raises(FinalVerificationError) as caught:
        cli._verify_winners_and_persist_failure(raw, [winner], [winner], raw_path)

    assert caught.value.verifier_error == stack
    saved = json.loads(raw_path.read_text(encoding="utf-8"))
    assert saved["finalVerification"]["results"] == []
    assert saved["finalVerification"]["verifierError"] == stack
    assert stack in saved["finalVerification"]["error"]


def test_cli_persists_verifier_process_launch_os_error(monkeypatch, tmp_path):
    raw_path = tmp_path / "family.raw.json"
    raw = {"listings": []}
    winner = {
        "marketplace": "ggsel", "pid": "native-id", "url": "https://example.test/item",
        "option_text": "Pro 1 месяц", "tier": "Pro", "duration": "1m",
        "delivery": "own_account", "price_rub": 7999,
    }
    launch_error = FileNotFoundError(2, "No such file or directory: node")

    def failed_launch(*_args, **_kwargs):
        raise launch_error

    monkeypatch.setattr(final_verify, "FINAL_VERIFY_TMP_DIR", tmp_path / "verify-temp")
    monkeypatch.setattr(final_verify.subprocess, "run", failed_launch)
    monkeypatch.setattr(cli, "verify_winners", final_verify.verify_winners)

    with pytest.raises(FinalVerificationError, match="verifier launch failed") as caught:
        cli._verify_winners_and_persist_failure(raw, [winner], [winner], raw_path)

    assert caught.value.verifier_error == str(launch_error)
    saved = json.loads(raw_path.read_text(encoding="utf-8"))
    assert saved["finalVerification"]["results"] == []
    assert saved["finalVerification"]["verifierError"] == str(launch_error)
    assert str(launch_error) in saved["finalVerification"]["error"]
