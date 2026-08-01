#!/usr/bin/env python3.12
"""Tests for upload.py — idempotency, escalation cap, dry-run safety."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from match import CONFIDENT, Pairing
from ramp import RampAuthError, RampError
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


# sha256(b"t1|inv-A") — pinned. Comparing two calls inside one process cannot
# tell a real digest apart from sha256(str(hash(...))), which is stable
# in-process and different on every run under hash randomization. That is
# exactly the failure that defeats Ramp's duplicate collapsing: the retry of
# a half-failed upload arrives with a fresh key and attaches a second copy.
EXPECTED_KEY_T1_INV_A = "014250b3e10fbd8f6847034232cf6d9f370dcdd0458965c25877b36db796c61a"


def test_idempotency_key_matches_the_pinned_digest():
    assert idempotency_key("t1", "inv-A") == EXPECTED_KEY_T1_INV_A


def test_idempotency_key_is_stable_across_processes():
    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    code = (
        "import sys; sys.path.insert(0, %r);"
        "from upload import idempotency_key; print(idempotency_key('t1', 'inv-A'))" % scripts
    )
    env = {**os.environ, "PYTHONHASHSEED": "random"}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == idempotency_key("t1", "inv-A"), (
        "the key must be identical in a fresh process, or every retry is a new upload"
    )


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


def test_structurally_invalid_ledgers_raise_corrupt_ledger_not_a_mid_run_crash():
    # A ledger can be valid JSON and still be the wrong shape — hand-edited,
    # truncated-then-repaired, written by an older version. Catching only
    # JSONDecodeError loads it cleanly and defers the blow-up to record() /
    # attempts() / status(), which fire mid-upload, after real receipts have
    # already been sent to Ramp. The failure must happen at load time, with
    # the documented CorruptLedger message contract.
    cases = {
        "null root": "null",
        "list root": '[{"provenance": "p", "status": "UPLOADED"}]',
        "string root": '"nope"',
        "rows are not a list": '{"t1": {"provenance": "p", "status": "UPLOADED"}}',
        "row is not a dict": '{"t1": ["UPLOADED"]}',
        "row missing provenance": '{"t1": [{"status": "UPLOADED"}]}',
        "row missing status": '{"t1": [{"provenance": "p"}]}',
        "rows are a bare string": '{"t1": "UPLOADED"}',
        "row is null": '{"t1": [null]}',
    }
    for label, content in cases.items():
        p = Path(tempfile.mkdtemp()) / "ledger.json"
        p.write_text(content)
        try:
            Ledger(p)
        except Ledger.CorruptLedger as e:
            msg = str(e)
            assert str(p.resolve()) in msg, f"{label}: error must name the path: {msg}"
            assert "delete" in msg.lower(), f"{label}: must say deletion is safe: {msg}"
            assert "idempotent" in msg.lower(), f"{label}: must say why: {msg}"
        else:
            raise AssertionError(
                f"{label}: a structurally invalid ledger must raise CorruptLedger, "
                "not load cleanly and crash later"
            )


def test_valid_ledger_shapes_still_load():
    for content in ("{}", '{"t1": []}',
                    '{"t1": [{"provenance": "p", "status": "FAILED", "transient": true}]}'):
        p = Path(tempfile.mkdtemp()) / "ledger.json"
        p.write_text(content)
        Ledger(p)  # must not raise


def test_a_different_receipt_candidate_gets_its_own_retry_budget():
    # The retry cap exists to stop a candidate that keeps failing. Counting
    # every historical row for the transaction instead makes it block a
    # candidate it never tried: two failures on one bad receipt retire the
    # transaction, so a later run that finds a genuinely different, valid
    # receipt is ESCALATED without an upload ever being attempted — even
    # though its idempotency key (transaction + provenance) is untouched.
    led = _ledger()
    for _ in range(MAX_ATTEMPTS):
        led.record("t1", "anthropic:invoice A", "FAILED")

    better = Receipt("anthropic", 21456, "2026-07-23", b"%PDF-1.4", "gmail:msg 19f9")
    with patch("upload.needs_receipt", return_value=True):
        with patch("upload.run", return_value=[{"id": "r1"}]) as r:
            result = upload(Pairing(T, better, CONFIDENT, ""), led, dry_run=False)
    assert result == "UPLOADED", (
        "a never-tried receipt candidate must not inherit another candidate's "
        f"exhausted retry budget (got {result})"
    )
    assert idempotency_key("t1", "gmail:msg 19f9") in r.call_args[0][0]


def test_skipped_rows_do_not_burn_a_candidates_retry_budget():
    led = _ledger()
    for _ in range(MAX_ATTEMPTS):
        led.record("t1", "anthropic:invoice B", "SKIPPED")
    with patch("upload.needs_receipt", return_value=True):
        with patch("upload.run", return_value=[{"id": "r1"}]):
            assert upload(PAIR, led, dry_run=False) == "UPLOADED", (
                "SKIPPED rows for another candidate are not failed attempts"
            )


def test_the_cap_still_stops_a_candidate_that_keeps_failing():
    # The provenance scoping must not quietly disable the cap: the SAME
    # candidate failing twice must still stop retrying.
    led = _ledger()
    with patch("upload.needs_receipt", return_value=True):
        with patch("upload.run", side_effect=RampError("ramp rejected the file")):
            for _ in range(MAX_ATTEMPTS):
                assert upload(PAIR, led, dry_run=False) == "FAILED"
        with patch("upload.run") as r:
            assert upload(PAIR, led, dry_run=False) == "ESCALATED"
            r.assert_not_called()


def test_attempts_are_counted_per_provenance():
    led = _ledger()
    led.record("t1", "anthropic:invoice A", "FAILED")
    led.record("t1", "anthropic:invoice A", "FAILED")
    led.record("t1", "gmail:msg 1", "FAILED")
    assert led.attempts("t1", "anthropic:invoice A") == 2
    assert led.attempts("t1", "gmail:msg 1") == 1
    assert led.attempts("t1", "gmail:msg 2") == 0


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


def test_auth_error_is_raised_not_recorded_as_failed():
    # Recording FAILED for an auth expiry burns an escalation attempt on a
    # transaction that was never actually rejected, and hides a dead session
    # behind a per-transaction failure. It must abort the run instead.
    led = _ledger()
    with patch("upload.needs_receipt", return_value=True):
        with patch("upload.run", side_effect=RampAuthError("auth dead")):
            try:
                upload(PAIR, led, dry_run=False)
            except RampAuthError:
                pass
            else:
                raise AssertionError("RampAuthError must propagate out of upload()")
    assert led.attempts("t1", R.provenance) == 0, "an auth expiry must not count as an attempt"


def test_transport_failures_do_not_burn_the_escalation_cap():
    # MAX_ATTEMPTS is 2. Two network blips used to retire a transaction
    # permanently, with no way to clear it but deleting the ledger.
    led = _ledger()
    with patch("upload.needs_receipt", return_value=True):
        with patch("upload.run", side_effect=ConnectionResetError("connection reset")):
            for _ in range(MAX_ATTEMPTS + 1):
                assert upload(PAIR, led, dry_run=False) == "FAILED"

        with patch("upload.run", return_value=[{"id": "r1"}]):
            assert upload(PAIR, led, dry_run=False) == "UPLOADED", (
                "transport blips must not escalate a transaction out of reach"
            )


def test_genuine_ramp_rejections_still_count_toward_the_cap():
    led = _ledger()
    with patch("upload.needs_receipt", return_value=True):
        with patch("upload.run", side_effect=RampError("ramp receipts upload: invalid file")):
            for _ in range(MAX_ATTEMPTS):
                assert upload(PAIR, led, dry_run=False) == "FAILED"
        with patch("upload.run") as r:
            assert upload(PAIR, led, dry_run=False) == "ESCALATED"
            r.assert_not_called()


if __name__ == "__main__":
    print("Running upload tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll upload tests passed.")
