#!/usr/bin/env python3.12
"""Tests for the report. Degraded sources must be announced, never silent."""

import io
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


if __name__ == "__main__":
    print("Running run tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll run tests passed.")
