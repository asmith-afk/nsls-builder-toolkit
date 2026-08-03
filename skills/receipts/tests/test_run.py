#!/usr/bin/env python3.12
"""Tests for the report. Degraded sources must be announced, never silent."""

import io
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from match import AMBIGUOUS, BALANCED, CONFIDENT, UNFOUND, Pairing
from txn_queue import Transaction
from run import build_report, main
from sources.base import Receipt, SourceUnavailable
from upload import Ledger

T1 = Transaction("t1", "Anthropic", 108500, "2026-07-19")
R1 = Receipt("anthropic", 108500, "2026-07-19", b"%PDF", "anthropic:invoice A")
T2 = Transaction("t2", "Neon Tech", 55076, "2026-08-01")
T3 = Transaction("t3", "Widget Co", 21456, "2026-07-20")
R3 = Receipt("widgetco", 21456, "2026-07-20", b"%PDF", "gmail:invoice B")


def test_skipped_source_gets_its_own_line():
    text = build_report([], {}, ["ANTHROPIC: not authenticated"])
    assert "SOURCE ANTHROPIC: SKIPPED (not authenticated)" in text


def test_no_skip_line_when_nothing_skipped():
    text = build_report([Pairing(T1, R1, CONFIDENT, "")], {"t1": "DRY_RUN"}, [])
    assert "SKIPPED" not in text


def test_truncated_note_renders_as_truncated_not_skipped():
    # A source that hit its pagination cap ran successfully and returned
    # partial results — it was never skipped. Rendering it as "SKIPPED"
    # tells the user something untrue about what happened, and a user has
    # little reason to read past that word once they see it. The report
    # must say TRUNCATED, not wrap it inside SKIPPED (...).
    text = build_report(
        [], {},
        ["GMAIL: TRUNCATED (hit the 50-page cap, 5000 messages fetched, results incomplete)"],
    )
    assert "SOURCE GMAIL: TRUNCATED (hit the 50-page cap" in text
    assert "SKIPPED" not in text


def test_unfound_listed_with_merchant_and_amount():
    text = build_report([Pairing(T2, None, UNFOUND, "no receipt")], {}, [])
    assert "Neon Tech" in text and "$550.76" in text


def test_ambiguous_note_is_surfaced():
    pairs = [Pairing(T2, None, AMBIGUOUS, "4 transactions vs 3 receipts at $214.56")]
    text = build_report(pairs, {}, [])
    assert "4 transactions vs 3 receipts" in text


def test_totals_reported():
    pairs = [Pairing(T1, R1, CONFIDENT, ""), Pairing(T2, None, UNFOUND, "")]
    text = build_report(pairs, {"t1": "DRY_RUN"}, [])
    assert "$1,635.76" in text, "must report total dollars still outstanding"


def test_balanced_and_uploaded_is_not_outstanding():
    # Regression for the brief's `outstanding` bug: Python parses
    # `p.outcome != CONFIDENT or results.get(...) != "UPLOADED"` as
    # `(p.outcome != CONFIDENT) or (results.get(...) != "UPLOADED")`, so a
    # BALANCED pairing (the four-identical-$214.56-charges case) whose
    # receipt DID upload still trips the first clause and gets counted as
    # outstanding. A pairing must count as outstanding only if its receipt
    # did not successfully upload, full stop.
    pair = Pairing(T3, R3, BALANCED, "4 indistinguishable charges, zipped by date")
    text = build_report([pair], {"t3": "UPLOADED"}, [])
    assert "$0.00 outstanding" in text, (
        "a BALANCED pairing that uploaded must not be counted as outstanding: " + text
    )


def test_headline_count_excludes_what_the_run_actually_resolved():
    # `len(pairings)` counts transactions that uploaded fine, and ones upload
    # SKIPPED because Ramp already had a receipt. A successful --send then
    # prints "2 transactions missing receipts — $0.00 outstanding": a headline
    # that contradicts its own dollar figure, and claims cleared transactions
    # are still missing.
    pairs = [Pairing(T1, R1, CONFIDENT, ""), Pairing(T3, R3, CONFIDENT, "")]
    text = build_report(pairs, {"t1": "UPLOADED", "t3": "SKIPPED"}, [])
    assert "**0 transactions missing receipts — $0.00 outstanding**" in text, text


def test_headline_count_and_dollars_agree_on_the_remainder():
    pairs = [Pairing(T1, R1, CONFIDENT, ""), Pairing(T2, None, UNFOUND, "")]
    text = build_report(pairs, {"t1": "UPLOADED"}, [])
    assert "**1 transactions missing receipts — $550.76 outstanding**" in text, text


def test_skipped_amounts_are_not_counted_as_outstanding():
    # SKIPPED means Ramp says the transaction already has a receipt — it is
    # resolved, not outstanding, even though this run uploaded nothing for it.
    text = build_report([Pairing(T3, R3, CONFIDENT, "")], {"t3": "SKIPPED"}, [])
    assert "$0.00 outstanding" in text, text


def test_dry_run_notice_prints_when_not_sending():
    with patch("run.missing_receipts", return_value=[]), \
         patch("run.load_sources", return_value=[]), \
         patch("run.Ledger", return_value=Ledger(Path(tempfile.mkdtemp()) / "l.json")):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([])
    assert code == 0
    assert "Dry run" in out.getvalue()
    assert "--send" in out.getvalue()


def test_corrupt_ledger_caught_prints_message_and_exits_2():
    # Task 6's Ledger.CorruptLedger names the file and says it's safe to
    # delete — main() must surface that message and exit 2, not crash with a
    # raw traceback. Use a real corrupt file (like test_upload.py does) rather
    # than mocking run.Ledger itself: replacing the module-level `Ledger` name
    # with a Mock would also shadow `Ledger.CorruptLedger` in main()'s except
    # clause, which is not what production code sees.
    corrupt_path = Path(tempfile.mkdtemp()) / "corrupt.json"
    corrupt_path.write_text("{invalid json")

    with patch("run.missing_receipts", return_value=[]), \
         patch("run.load_sources", return_value=[]), \
         patch("run.LEDGER_PATH", corrupt_path):
        err = io.StringIO()
        with redirect_stderr(err):
            code = main([])
    assert code == 2
    assert "safe to delete" in err.getvalue().lower()
    assert str(corrupt_path.resolve()) in err.getvalue()


def _unreadable_ledger_path():
    """An existing ledger file this process has no permission to read.

    Returns (path, restore) or (None, None) when permission bits don't apply
    to this process (e.g. running as root, for whom chmod 000 doesn't block
    a read), so the caller can skip rather than get a false pass.
    """
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return None, None
    tmp_dir = Path(tempfile.mkdtemp())
    path = tmp_dir / "ledger.json"
    path.write_text("{}")
    os.chmod(path, 0o000)

    def restore():
        os.chmod(path, 0o600)
        path.unlink()
        tmp_dir.rmdir()

    return path, restore


def test_unreadable_ledger_caught_prints_message_and_exits_2():
    # Round 3's Macroscope finding: main() wrapped Ledger(LEDGER_PATH) in
    # `except Ledger.CorruptLedger` only. Ledger.exists()/.read_text() raise
    # plain OSError for a permissions problem (or a dead home directory) —
    # not CorruptLedger — so it propagated as a raw traceback, even on a dry
    # run that read nothing and would otherwise have changed nothing.
    ledger_path, restore = _unreadable_ledger_path()
    if ledger_path is None:
        return  # e.g. running as root, where chmod 000 doesn't restrict reads

    try:
        with patch("run.missing_receipts", return_value=[]), \
             patch("run.load_sources", return_value=[]), \
             patch("run.LEDGER_PATH", ledger_path):
            err = io.StringIO()
            with redirect_stderr(err):
                code = main([])
    finally:
        restore()

    assert code == 2, f"an unreadable ledger must exit 2, not crash, got {code}"
    assert "Traceback" not in err.getvalue(), err.getvalue()
    assert str(ledger_path) in err.getvalue(), (
        "must name the ledger path: " + err.getvalue()
    )
    # Unreadable is not the same problem as corrupt (invalid JSON) — the
    # message must not claim the file's contents are bad when it was never
    # read at all, and must not tell the user it's safe to delete on that
    # premise.
    assert "corrupt" not in err.getvalue().lower(), (
        "an unreadable file is not a corrupt one: " + err.getvalue()
    )


def test_truncated_source_reports_partial_results_not_a_clean_run():
    # A source can hit an internal cap (e.g. Gmail's pagination guard) and
    # return *normally* with a partial list rather than raising. If that
    # never reaches the report, the user sees a clean run with fewer
    # receipts and zero indication anything was truncated — the exact
    # "degradation that reads as a clean result" failure mode this codebase
    # treats as its recurring bug. The source signals this via a public
    # `truncated` attribute set during fetch(); main() must check it and
    # surface it through the same reporting channel as a skipped source,
    # while still using the partial results it did get (not discarding them).
    class PartialSource:
        def __init__(self):
            self.truncated = None

        def fetch(self, since, until):
            self.truncated = "hit the 50-page cap, 5000 messages fetched, results incomplete"
            return [R1]

    with patch("run.missing_receipts", return_value=[T1]), \
         patch("run.load_sources", return_value=[PartialSource()]), \
         patch("run.Ledger", return_value=Ledger(Path(tempfile.mkdtemp()) / "l.json")):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([])

    text = out.getvalue()
    assert code == 0
    assert "TRUNCATED" in text
    assert "results incomplete" in text
    assert "Anthropic" in text, "the partial receipts must still be used, not discarded"


def test_no_truncated_line_when_source_has_no_truncated_attribute():
    # Sources that never set `truncated` (i.e. every source before this
    # change, and any source that doesn't hit a cap) must not spuriously
    # trigger the new check — getattr(..., None) must default safely.
    class PlainSource:
        def fetch(self, since, until):
            return [R1]

    with patch("run.missing_receipts", return_value=[T1]), \
         patch("run.load_sources", return_value=[PlainSource()]), \
         patch("run.Ledger", return_value=Ledger(Path(tempfile.mkdtemp()) / "l.json")):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([])
    assert "TRUNCATED" not in out.getvalue()


def test_one_broken_source_does_not_take_down_the_run():
    # A source raising anything other than SourceUnavailable (network
    # timeout, JSON decode error, KeyError...) must be recorded in `skipped`
    # and the run must keep going with every other source's results intact.
    class OkSource:
        def fetch(self, since, until):
            return [R1]

    class UnavailableSource:
        def fetch(self, since, until):
            raise SourceUnavailable("not authenticated")

    class BrokenSource:
        def fetch(self, since, until):
            raise ValueError("boom: unexpected payload shape")

    with patch("run.missing_receipts", return_value=[T1]), \
         patch("run.load_sources", return_value=[OkSource(), UnavailableSource(), BrokenSource()]), \
         patch("run.Ledger", return_value=Ledger(Path(tempfile.mkdtemp()) / "l.json")):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([])

    text = out.getvalue()
    assert code == 0, "one broken source must not fail the whole run"
    assert "SOURCE UNAVAILABLE: SKIPPED (not authenticated)" in text
    assert "SOURCE BROKEN: SKIPPED" in text and "boom" in text
    assert "Anthropic" in text, "the OK source's receipt must still produce a result"


def test_report_always_says_how_many_sources_loaded():
    # "0 receipts found" and "we never looked" render identically unless the
    # report states, every run, how many sources actually loaded — and
    # separately, how many actually searched, so "loaded" can never be
    # mistaken for "worked."
    text = build_report([], {}, [], ["ANTHROPIC", "GMAIL"], ["ANTHROPIC", "GMAIL"])
    assert "SOURCES: 2 loaded, 2 searched (ANTHROPIC, GMAIL)" in text


def test_zero_sources_refuses_to_report_unfound_and_exits_nonzero():
    # With no source loaded, every transaction is UNFOUND with "no receipt in
    # any source" and the tool exits 0 — an empty result that means we didn't
    # look, reported as a clean run. It must say so plainly and fail.
    with patch("run.missing_receipts", return_value=[T1]), \
         patch("run.load_sources", return_value=[]), \
         patch("run.Ledger", return_value=Ledger(Path(tempfile.mkdtemp()) / "l.json")):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([])

    combined = out.getvalue() + err.getvalue()
    assert code != 0, "a run with zero sources loaded is not a clean run"
    assert "No receipt found" not in out.getvalue(), (
        "must not report UNFOUND when nothing was searched: " + out.getvalue()
    )
    assert "SOURCES: 0 loaded, 0 searched" in combined
    assert "no receipt source was able to search" in combined.lower()


def test_load_sources_skips_a_module_that_fails_to_import():
    # One source raising at import time (missing dependency, syntax error)
    # must not kill discovery for every other source — and the failure must
    # be reported, not swallowed.
    from types import SimpleNamespace

    import sources.base as base

    good = SimpleNamespace(SOURCE=object())

    def fake_import(name):
        if name.endswith("broken"):
            raise ImportError("No module named 'playwright'")
        return good

    errors: list[str] = []
    with patch.object(base.pkgutil, "iter_modules",
                      return_value=[SimpleNamespace(name="alpha"), SimpleNamespace(name="broken")]), \
         patch.object(base.importlib, "import_module", side_effect=fake_import):
        found = base.load_sources(errors)

    assert found == [good.SOURCE], "the healthy source must still load"
    assert len(errors) == 1 and "BROKEN" in errors[0].upper()
    assert "playwright" in errors[0], "the reason must survive into the report"


def test_import_failure_is_announced_in_the_report():
    def fake_load_sources(errors=None):
        if errors is not None:
            errors.append("BROKEN: import failed — boom")
        return [_OkSource()]

    with patch("run.missing_receipts", return_value=[T1]), \
         patch("run.load_sources", side_effect=fake_load_sources), \
         patch("run.Ledger", return_value=Ledger(Path(tempfile.mkdtemp()) / "l.json")):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([])
    text = out.getvalue()
    assert code == 0
    assert "SOURCE BROKEN: SKIPPED (import failed — boom)" in text


class _OkSource:
    def fetch(self, since, until):
        return [R1]


class _SecondSource:
    """Holds the receipt for T3 so both transactions are actionable."""

    def fetch(self, since, until):
        return [R1, R3]


def _send_run(fake_needs_receipt, ledger_path):
    # The failure is injected into needs_receipt() — the live Ramp re-check
    # upload() makes per transaction, OUTSIDE its own try/except. That is the
    # call that took the whole loop down mid-run.
    with patch("run.missing_receipts", return_value=[T1, T3]), \
         patch("run.load_sources", return_value=[_SecondSource()]), \
         patch("run.LEDGER_PATH", ledger_path), \
         patch("upload.needs_receipt", side_effect=fake_needs_receipt), \
         patch("upload.run", return_value=[{"id": "r1"}]):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--send"])
    return code, out.getvalue() + err.getvalue()


def test_mid_loop_upload_failure_still_persists_earlier_successes():
    # upload() calls needs_receipt() — a live Ramp call — per transaction
    # inside the send loop. One raise there used to abort the loop, suppress
    # the report, and lose every UPLOADED record from the run.
    ledger_path = Path(tempfile.mkdtemp()) / "l.json"

    def fake_needs_receipt(txn_id):
        if txn_id == "t3":
            raise RuntimeError("connection reset by peer")
        return True

    code, text = _send_run(fake_needs_receipt, ledger_path)

    assert Ledger(ledger_path).status("t1") == "UPLOADED", (
        "the upload that succeeded must survive a later failure"
    )
    assert code != 0, "a failed upload must not report a clean run"
    assert code != 2, "a failed upload is not the terminal auth-abort path"
    assert "Ready" in text, "the report must still print after a mid-loop failure"


def test_failed_upload_exits_nonzero_so_automation_sees_it():
    # The loop deliberately swallows a per-transaction failure so the rest of
    # the run continues. Swallowing the exit code with it made a partial
    # failure indistinguishable from a clean run to anything reading $?.
    ledger_path = Path(tempfile.mkdtemp()) / "l.json"

    def fake_needs_receipt(txn_id):
        raise RuntimeError("connection reset by peer")

    code, text = _send_run(fake_needs_receipt, ledger_path)

    assert code != 0, f"every upload failed and the run still exited {code}"
    assert "ERROR uploading" in text, "the failure must also be visible in the output"


def test_all_success_send_still_exits_zero():
    # The nonzero exit must be caused by the failure, not by --send itself.
    ledger_path = Path(tempfile.mkdtemp()) / "l.json"

    code, text = _send_run(lambda txn_id: True, ledger_path)

    assert code == 0, f"a send with no failures must exit 0, got {code}"
    assert "ERROR uploading" not in text
    assert Ledger(ledger_path).status("t1") == "UPLOADED"


def test_mid_loop_auth_expiry_exits_2_and_keeps_the_ledger():
    # A live auth expiry mid-run must abort cleanly through the same exit-2
    # path as an auth failure at queue-build time — not a raw traceback that
    # takes the ledger with it.
    from ramp import RampAuthError

    ledger_path = Path(tempfile.mkdtemp()) / "l.json"

    def fake_needs_receipt(txn_id):
        if txn_id == "t3":
            raise RampAuthError("Ramp auth failed — run `ramp auth login`")
        return True

    code, text = _send_run(fake_needs_receipt, ledger_path)

    assert code == 2, "auth expiry must exit 2, not traceback"
    assert "ramp auth login" in text
    assert Ledger(ledger_path).status("t1") == "UPLOADED", (
        "the ledger must be saved even when the run aborts"
    )


def test_zero_sources_searched_but_imported_refuses_and_exits_2():
    # Both real sources (anthropic.py, gmail.py) fail at *fetch* time, not
    # import time — ANTHROPIC_ORG_UUID unset, `gws` CLI missing. The old
    # guard only counted sources that *imported* (appended to `loaded`
    # before fetch() was ever called), so this exact path — the default
    # experience for an unconfigured install — slipped through: `SOURCES: 2
    # loaded` read as reassuring, and the tool still printed "no receipt
    # found" for transactions nothing had searched, and exited 0. Tracking
    # only sources that actually *searched* must catch this.
    class DeadAnthropic:
        def fetch(self, since, until):
            raise SourceUnavailable("ANTHROPIC_ORG_UUID is not set")

    class DeadGmail:
        def fetch(self, since, until):
            raise SourceUnavailable("`gws` CLI not found")

    with patch("run.missing_receipts", return_value=[T1]), \
         patch("run.load_sources", return_value=[DeadAnthropic(), DeadGmail()]), \
         patch("run.Ledger", return_value=Ledger(Path(tempfile.mkdtemp()) / "l.json")):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([])

    combined = out.getvalue() + err.getvalue()
    assert code != 0, "0 of 2 loaded sources actually searched — this must not exit 0"
    assert "No receipt found" not in out.getvalue(), (
        "must not assert 'no receipt found' about transactions nothing searched: " + out.getvalue()
    )
    assert "no receipt source" in combined.lower() and "search" in combined.lower()
    assert "2 loaded" in combined and "0 searched" in combined, (
        "the SOURCES line must distinguish loaded from searched: " + combined
    )


def test_one_of_two_searched_is_a_normal_degraded_run():
    # A partial run — one source dead at fetch time, one source working — is
    # NOT the zero-searched failure case. It must proceed normally, report
    # UNFOUND for what the working source genuinely didn't find, and exit 0.
    # The residual-fix guard must not overcorrect and treat every degraded
    # run as a failure.
    class DeadGmail:
        def fetch(self, since, until):
            raise SourceUnavailable("`gws` CLI not found")

    class WorkingAnthropic:
        def fetch(self, since, until):
            return [R1]

    with patch("run.missing_receipts", return_value=[T1, T2]), \
         patch("run.load_sources", return_value=[WorkingAnthropic(), DeadGmail()]), \
         patch("run.Ledger", return_value=Ledger(Path(tempfile.mkdtemp()) / "l.json")):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([])

    text = out.getvalue()
    assert code == 0, "one working source out of two is a normal degraded run, not a failure"
    assert "## No receipt found" in text
    assert "Neon Tech" in text, (
        "T2 genuinely has no receipt from the one source that did search — "
        "UNFOUND is legitimate here, not a suppressed finding: " + text
    )
    assert "1 searched" in text


def test_zero_sources_searched_with_no_transactions_is_not_a_false_alarm():
    # Nothing was missing, so nothing was missed — a dead source with an
    # empty transaction queue must not trip the refusal.
    class DeadAnthropic:
        def fetch(self, since, until):
            raise SourceUnavailable("ANTHROPIC_ORG_UUID is not set")

    with patch("run.missing_receipts", return_value=[]), \
         patch("run.load_sources", return_value=[DeadAnthropic()]), \
         patch("run.Ledger", return_value=Ledger(Path(tempfile.mkdtemp()) / "l.json")):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([])
    assert code == 0, "no transactions were in the queue, so there is nothing to fail about"
    assert "Nothing missing a receipt" in out.getvalue()


def _unwritable_ledger_path():
    """A ledger path whose parent directory cannot be created.

    Returns (path, restore) or (None, None) when the filesystem can't be made
    unwritable for this process (running as root), so the caller can skip.
    """
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return None, None
    parent = Path(tempfile.mkdtemp())
    os.chmod(parent, 0o500)  # r-x: mkdir inside fails with EACCES
    return parent / "nested" / "ledger.json", lambda: os.chmod(parent, 0o700)


def test_dry_run_does_not_write_the_ledger_and_survives_an_unwritable_path():
    # ledger.save() lives in a finally block so a mid-loop failure can't lose
    # already-recorded uploads. Running it unconditionally made a DRY RUN —
    # which attempts no upload and records nothing — depend on being able to
    # write a file it has no reason to touch. On a read-only home or a full
    # disk that raised an uncaught OSError *before* the report printed: the
    # user got a traceback instead of their results, from a run that changed
    # nothing.
    ledger_path, restore = _unwritable_ledger_path()
    if ledger_path is None:
        return

    saves = []
    real_save = Ledger.save

    def spy(self):
        saves.append(self.path)
        return real_save(self)

    try:
        with patch("run.missing_receipts", return_value=[T1]), \
             patch("run.load_sources", return_value=[_OkSource()]), \
             patch("run.LEDGER_PATH", ledger_path), \
             patch.object(Ledger, "save", spy):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main([])
    finally:
        restore()

    text = out.getvalue()
    assert code == 0, f"a dry run that changed nothing must exit 0, got {code}"
    assert "Receipts → Ramp" in text and "Anthropic" in text, (
        "the full report must still print: " + text + err.getvalue()
    )
    assert "Dry run" in text
    assert saves == [], "a dry run records nothing — it must not write the ledger at all"
    assert not ledger_path.exists()


def test_ledger_write_failure_on_send_still_prints_the_report_and_exits_nonzero():
    # The other half: on --send an upload really was recorded, so the write is
    # attempted — and if it fails, that is a genuine failure the exit code has
    # to carry. It still must not eat the report or escape as a traceback.
    ledger_path, restore = _unwritable_ledger_path()
    if ledger_path is None:
        return

    try:
        code, text = _send_run(lambda txn_id: True, ledger_path)
    finally:
        restore()

    assert code != 0, "a ledger the tool could not write is not a clean run"
    assert "Ready" in text, "the report must still print: " + text
    assert "Anthropic" in text
    assert str(ledger_path) in text, "the failure must name the ledger path: " + text
    assert "Traceback" not in text


def test_set_session_flag_stores_the_session_and_touches_nothing_else():
    # --set-session is the single documented entry point for authenticating
    # the Anthropic source. It must do exactly one thing — store a claude.ai
    # session via sources.anthropic._set_session() — and exit, never reaching
    # the Ramp queue, source fetch, or ledger.
    with patch("run.anthropic_set_session", return_value=0) as set_session, \
         patch("run.missing_receipts") as missing, \
         patch("run.load_sources") as loaded, \
         patch("run.Ledger") as ledger:
        code = main(["--set-session"])

    assert code == 0
    set_session.assert_called_once()
    missing.assert_not_called()
    loaded.assert_not_called()
    ledger.assert_not_called()


def test_set_session_returns_the_stores_own_exit_code():
    # A refused or unvalidatable session is a failed invocation. Swallowing
    # its exit code would report "stored" for a credential that was rejected.
    with patch("run.anthropic_set_session", return_value=2):
        with redirect_stderr(io.StringIO()):
            assert main(["--set-session"]) == 2


def test_login_still_works_as_an_alias_and_explains_the_change():
    # --login is in shipped docs, in old error strings, and in muscle memory.
    # An "unrecognized arguments" error would be a dead end for anyone
    # following those, so the old name keeps working — and says what changed.
    with patch("run.anthropic_set_session", return_value=0) as set_session, \
         patch("run.missing_receipts") as missing, \
         patch("run.load_sources") as loaded, \
         patch("run.Ledger") as ledger:
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["--login"])

    assert code == 0
    set_session.assert_called_once()
    missing.assert_not_called()
    loaded.assert_not_called()
    ledger.assert_not_called()
    note = err.getvalue()
    assert "--set-session" in note, "the alias must name its replacement: " + note
    assert "browser" in note.lower(), (
        "say the browser step is gone — that is the change a --login user "
        "needs to know about: " + note
    )


def test_set_session_and_send_together_is_rejected_explicitly():
    # --set-session only stores a session and exits; it never builds the
    # queue, fetches, or uploads, so there is nothing for --send to act on in
    # the same invocation. Silently picking one (or doing both) would be a
    # surprise either way — reject the combination with a clear message
    # instead.
    with patch("run.anthropic_set_session") as set_session:
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["--set-session", "--send"])

    assert code == 2
    set_session.assert_not_called()
    assert "--set-session" in err.getvalue() and "--send" in err.getvalue()


def test_login_and_send_together_is_still_rejected_the_same_way():
    # The --login-era rejection must not regress just because the flag became
    # an alias.
    with patch("run.anthropic_set_session") as set_session:
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["--login", "--send"])

    assert code == 2
    set_session.assert_not_called()
    assert "--login" in err.getvalue() and "--send" in err.getvalue()


def test_ledger_write_failure_does_not_downgrade_the_auth_abort():
    # The auth abort is the exit code automation watches for. An OSError out
    # of save() inside the finally, while that abort is unwinding, must not
    # replace exit 2 with a crash or with a different code.
    from ramp import RampAuthError

    ledger_path, restore = _unwritable_ledger_path()
    if ledger_path is None:
        return

    def fake_needs_receipt(txn_id):
        if txn_id == "t3":
            raise RampAuthError("Ramp auth failed — run `ramp auth login`")
        return True

    try:
        code, text = _send_run(fake_needs_receipt, ledger_path)
    finally:
        restore()

    assert code == 2, f"the auth abort must still exit 2, got {code}"
    assert "ramp auth login" in text
    assert str(ledger_path) in text, "the ledger failure must still be reported: " + text
    assert "Traceback" not in text


if __name__ == "__main__":
    print("Running run tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll run tests passed.")
