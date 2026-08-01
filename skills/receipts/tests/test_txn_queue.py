#!/usr/bin/env python3.12
"""Tests for txn_queue.py.

Guards the single most dangerous bug in this skill: trusting `missing_items`
from `transactions list`, which is ALWAYS null and means "not computed".
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ramp import RampError
from txn_queue import Transaction, missing_receipts, needs_receipt

PAGE = {
    "transactions": [
        {"transaction_uuid": "t1", "merchant_name": "Anthropic", "amount": "$214.56",
         "transaction_time": "2026-07-23T10:00:00+00:00", "missing_items": None},
        {"transaction_uuid": "t2", "merchant_name": "Macroscope", "amount": "$50.00",
         "transaction_time": "2026-07-30T10:00:00+00:00", "missing_items": None},
    ],
    "total_count": 2,
    "next_page_cursor": None,
}


def test_does_not_trust_missing_items_field():
    """missing_items is null for BOTH rows; only t1 actually needs a receipt."""
    def fake_run(args, rationale):
        if args[1] == "list":
            return [PAGE]
        return [{"missing_receipt": args[2] == "t1", "missing_memo": False,
                 "missing_accounting_items": []}]

    with patch("txn_queue.run", side_effect=fake_run):
        out = missing_receipts("2026-01-01", "2026-08-01")

    assert [t.id for t in out] == ["t1"], (
        "must use per-transaction `transactions missing`, not the null missing_items field"
    )


def test_returns_empty_when_nothing_needs_a_receipt():
    def fake_run(args, rationale):
        if args[1] == "list":
            return [PAGE]
        return [{"missing_receipt": False, "missing_memo": False, "missing_accounting_items": []}]

    with patch("txn_queue.run", side_effect=fake_run):
        assert missing_receipts("2026-01-01", "2026-08-01") == []


def test_parses_amount_to_integer_cents():
    def fake_run(args, rationale):
        if args[1] == "list":
            return [PAGE]
        return [{"missing_receipt": True, "missing_memo": False, "missing_accounting_items": []}]

    with patch("txn_queue.run", side_effect=fake_run):
        out = missing_receipts("2026-01-01", "2026-08-01")
    assert out[0].amount_cents == 21456
    assert isinstance(out[0].amount_cents, int)


def test_normalizes_date_to_iso():
    def fake_run(args, rationale):
        if args[1] == "list":
            return [PAGE]
        return [{"missing_receipt": True, "missing_memo": False, "missing_accounting_items": []}]

    with patch("txn_queue.run", side_effect=fake_run):
        out = missing_receipts("2026-01-01", "2026-08-01")
    assert out[0].date == "2026-07-23"


def test_follows_pagination_cursor():
    p1 = {"transactions": PAGE["transactions"][:1], "next_page_cursor": "CUR"}
    p2 = {"transactions": PAGE["transactions"][1:], "next_page_cursor": None}
    pages = [p1, p2]
    calls = []

    def fake_run(args, rationale):
        if args[1] == "list":
            calls.append(args)
            return [pages[len(calls) - 1]]
        return [{"missing_receipt": True, "missing_memo": False, "missing_accounting_items": []}]

    with patch("txn_queue.run", side_effect=fake_run):
        out = missing_receipts("2026-01-01", "2026-08-01")

    assert len(out) == 2
    assert any("CUR" in a for a in calls[1]), "second page must pass next_page_cursor"


def test_empty_data_from_list_raises_rampe_error_not_indexerror():
    # `run()` returns payload["data"], which can legitimately be []. Indexing
    # [0] on it is a raw IndexError — a traceback main() does not catch, and
    # inside the send loop it also aborts the run mid-upload.
    with patch("txn_queue.run", return_value=[]):
        try:
            missing_receipts("2026-01-01", "2026-08-01")
        except RampError as exc:
            assert "no data" in str(exc).lower(), f"message must say what happened: {exc}"
            return
        except IndexError:
            raise AssertionError("empty data must raise RampError, not IndexError")
    raise AssertionError("empty data must raise RampError")


def test_empty_data_from_missing_check_raises_ramp_error():
    with patch("txn_queue.run", return_value=[]):
        try:
            needs_receipt("t1")
        except RampError as exc:
            assert "no data" in str(exc).lower()
            return
        except IndexError:
            raise AssertionError("empty data must raise RampError, not IndexError")
    raise AssertionError("empty data must raise RampError")


if __name__ == "__main__":
    print("Running queue tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll queue tests passed.")
