#!/usr/bin/env python3.12
"""Tests for upload.py — idempotency, escalation cap, dry-run safety."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from match import CONFIDENT, Pairing
from txn_queue import Transaction
from sources.base import Receipt
from upload import MAX_ATTEMPTS, Ledger, idempotency_key, upload

T = Transaction("t1", "Anthropic", 21456, "2026-07-23")
R = Receipt("anthropic", 21456, "2026-07-23", b"%PDF-1.4", "anthropic:invoice A")
PAIR = Pairing(T, R, CONFIDENT, "")


def _ledger():
    return Ledger(Path(tempfile.mkdtemp()) / "ledger.json")


def test_idempotency_key_stable():
    assert idempotency_key("t1", "inv-A") == idempotency_key("t1", "inv-A")


def test_idempotency_key_differs_per_transaction():
    assert idempotency_key("t1", "inv-A") != idempotency_key("t2", "inv-A")


def test_dry_run_never_calls_ramp():
    calls = []
    with patch("upload.run", side_effect=lambda *a, **k: calls.append(a)):
        assert upload(PAIR, _ledger(), dry_run=True) == "DRY_RUN"
    assert calls == [], "dry run must not invoke the CLI"


def test_upload_passes_transaction_uuid_and_idempotency_key():
    seen = {}

    def fake(args, rationale):
        seen["args"] = args
        return [{"id": "r1"}]

    with patch("upload.needs_receipt", return_value=True):
        with patch("upload.run", side_effect=fake):
            assert upload(PAIR, _ledger(), dry_run=False) == "UPLOADED"

    assert "--transaction_uuid" in seen["args"]
    assert "t1" in seen["args"]
    assert idempotency_key("t1", "anthropic:invoice A") in seen["args"]


def test_already_receipted_is_skipped():
    with patch("upload.needs_receipt", return_value=False):
        with patch("upload.run") as r:
            assert upload(PAIR, _ledger(), dry_run=False) == "SKIPPED"
            r.assert_not_called()


def test_failure_never_marks_uploaded():
    led = _ledger()
    with patch("upload.needs_receipt", return_value=True):
        with patch("upload.run", side_effect=RuntimeError("ramp 500")):
            assert upload(PAIR, led, dry_run=False) == "FAILED"
    assert led.status("t1") != "UPLOADED"


def test_escalates_after_max_attempts():
    led = _ledger()
    for _ in range(MAX_ATTEMPTS):
        led.record("t1", "anthropic:invoice A", "FAILED")
    with patch("upload.needs_receipt", return_value=True):
        with patch("upload.run") as r:
            assert upload(PAIR, led, dry_run=False) == "ESCALATED"
            r.assert_not_called()


def test_ledger_persists():
    p = Path(tempfile.mkdtemp()) / "l.json"
    a = Ledger(p); a.record("t1", "pr", "UPLOADED"); a.save()
    assert Ledger(p).status("t1") == "UPLOADED"


def test_corrupt_ledger_raises_clear_error():
    p = Path(tempfile.mkdtemp()) / "corrupt.json"
    p.write_text("{invalid json")
    try:
        Ledger(p)
        assert False, "should have raised CorruptLedger"
    except Ledger.CorruptLedger as e:
        error_msg = str(e)
        assert str(p.resolve()) in error_msg, f"error must name the path: {error_msg}"
        assert "delete" in error_msg.lower(), f"error must mention deleting: {error_msg}"
        assert "idempotent" in error_msg.lower(), f"error must mention idempotency: {error_msg}"


def test_save_is_atomic_no_temp_files_left():
    tmpdir = Path(tempfile.mkdtemp())
    p = tmpdir / "ledger.json"
    led = Ledger(p)
    led.record("t1", "inv-A", "UPLOADED")
    led.save()
    # Verify no stray temp files (mkstemp creates files matching 'tmp*')
    stray = [f for f in tmpdir.iterdir() if f.name.startswith("tmp")]
    assert stray == [], f"stray temp files left: {stray}"
    # Verify round-trip works
    led2 = Ledger(p)
    assert led2.status("t1") == "UPLOADED"


if __name__ == "__main__":
    print("Running upload tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll upload tests passed.")
