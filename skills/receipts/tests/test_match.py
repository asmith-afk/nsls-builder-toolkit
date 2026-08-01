#!/usr/bin/env python3.12
"""Tests for match.py — pure, no I/O.

Fixtures mirror shapes seen in a real Ramp queue: a four-way $214.56
collision on 2026-07-23 and a $1,085.00 single on 2026-07-19.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from match import AMBIGUOUS, BALANCED, CONFIDENT, UNFOUND, match
from txn_queue import Transaction
from sources.base import Receipt


def txn(i, cents, date="2026-07-23", merchant="Anthropic"):
    return Transaction(id=i, merchant=merchant, amount_cents=cents, date=date)


def rcpt(cents, date="2026-07-23", prov="p", merchant="anthropic"):
    return Receipt(merchant, cents, date, b"%PDF-1.4", prov)


def test_single_match_is_confident():
    p = match([txn("t", 108500, "2026-07-19")], [rcpt(108500, "2026-07-19", "inv-b")])
    assert p[0].outcome == CONFIDENT
    assert p[0].receipt.provenance == "inv-b"


def test_four_identical_charges_and_four_receipts_are_balanced():
    txns = [txn(f"t{i}", 21456) for i in range(4)]
    rs = [rcpt(21456, prov=f"inv-{i}") for i in range(4)]
    pairs = match(txns, rs)
    assert {p.outcome for p in pairs} == {BALANCED}
    assert len({p.receipt.provenance for p in pairs}) == 4, "each txn gets a distinct receipt"


def test_balanced_assignment_is_order_independent():
    txns = [txn(f"t{i}", 21456) for i in range(4)]
    rs = [rcpt(21456, prov=f"inv-{i}") for i in range(4)]
    a = [(p.transaction.id, p.receipt.provenance) for p in match(txns, rs)]
    b = [(p.transaction.id, p.receipt.provenance) for p in match(txns, list(reversed(rs)))]
    assert a == b


def test_four_transactions_three_receipts_assigns_nothing():
    txns = [txn(f"t{i}", 21456) for i in range(4)]
    rs = [rcpt(21456, prov=f"inv-{i}") for i in range(3)]
    pairs = match(txns, rs)
    assert {p.outcome for p in pairs} == {AMBIGUOUS}
    assert all(p.receipt is None for p in pairs), "AMBIGUOUS must never assign"


def test_no_receipt_is_unfound():
    p = match([txn("t9", 47838, "2026-06-17")], [])
    assert p[0].outcome == UNFOUND and p[0].receipt is None


def test_settlement_lag_inside_window_matches():
    p = match([txn("t", 21456, "2026-07-25")], [rcpt(21456, "2026-07-23")])
    assert p[0].outcome == CONFIDENT


def test_outside_window_does_not_match():
    p = match([txn("t", 21456, "2026-07-30")], [rcpt(21456, "2026-07-23")])
    assert p[0].outcome == UNFOUND


def test_different_merchant_never_matches():
    p = match([txn("t", 21456, merchant="Neon Tech")], [rcpt(21456, merchant="anthropic")])
    assert p[0].outcome == UNFOUND


def test_receipts_with_no_transaction_produce_no_pairings():
    assert match([], [rcpt(25908)]) == []


def test_same_charge_from_two_sources_binds_exactly_one_receipt():
    """The real cross-source duplicate: one charge, two sources, one receipt each.

    An Anthropic subscription charge produces BOTH a billing-portal invoice
    (provenance "anthropic:invoice …") and an emailed receipt (provenance
    "gmail:msg …"). Provenance is source-namespaced by construction, so the
    provenance dedup can never collapse these two — yet they are duplicate
    receipts for the same charge. Before this was fixed, adding the Gmail
    source turned a CONFIDENT Anthropic match into AMBIGUOUS
    ("1 txn vs 2 receipts") and the transaction went unreceipted.
    """
    txns = [txn("t1", 21456, "2026-07-23")]
    rs = [
        rcpt(21456, "2026-07-23", prov="anthropic:invoice 2026-07-23 21456 tok"),
        rcpt(21456, "2026-07-23", prov="gmail:msg 18f2c9ab7de"),
    ]
    pairs = match(txns, rs)

    assert len(pairs) == 1
    assert pairs[0].outcome == CONFIDENT, (
        f"two sources holding the same receipt must not read as ambiguous: {pairs[0].note}"
    )
    assert pairs[0].receipt is not None, "exactly one receipt must bind"


def test_two_charges_two_sources_each_binds_one_receipt():
    """Same collapse, N-wide: 2 identical charges seen by 2 sources = 4 receipts."""
    txns = [txn(f"t{i}", 21456, "2026-07-23") for i in range(2)]
    rs = [
        rcpt(21456, "2026-07-23", prov="anthropic:invoice A"),
        rcpt(21456, "2026-07-23", prov="anthropic:invoice B"),
        rcpt(21456, "2026-07-23", prov="gmail:msg A"),
        rcpt(21456, "2026-07-23", prov="gmail:msg B"),
    ]
    pairs = match(txns, rs)
    assert {p.outcome for p in pairs} == {BALANCED}
    bound = [p.receipt.provenance for p in pairs]
    assert len(set(bound)) == 2, "each transaction gets its own distinct receipt"


def test_same_provenance_twice_is_still_deduped():
    """The original guard: one source returning the same receipt twice.

    Two transactions, one real receipt duplicated in the list. After
    provenance dedup there is 1 receipt for 2 transactions — fewer receipts
    than transactions is real information and must stay AMBIGUOUS.
    """
    txns = [txn(f"t{i}", 21456) for i in range(2)]
    rs = [rcpt(21456, prov="anthropic:invoice A"), rcpt(21456, prov="anthropic:invoice A")]
    pairs = match(txns, rs)
    assert {p.outcome for p in pairs} == {AMBIGUOUS}
    assert all(p.receipt is None for p in pairs)


def test_more_receipts_than_transactions_but_not_identical_stays_ambiguous():
    """The collapse only fires for receipts identical on merchant/amount/date."""
    txns = [txn("t1", 21456, "2026-07-23")]
    rs = [rcpt(21456, "2026-07-22", prov="anthropic:invoice A"),
          rcpt(21456, "2026-07-23", prov="gmail:msg B")]
    pairs = match(txns, rs)
    assert pairs[0].outcome == AMBIGUOUS
    assert pairs[0].receipt is None


def test_balanced_never_binds_a_receipt_outside_the_window():
    """Group-wide window checks let a receipt bind to a transaction 9 days away.

    Two identical $214.56 charges nine days apart; two receipts both sitting
    next to the LATER one. The group passes an `any(...)` window test, then
    zip() hands the 2026-01-01 transaction a 2026-01-09 receipt — BALANCED,
    which is actionable, so `--send` attaches the wrong receipt in Ramp.
    Every pair must be inside the window on its own, or the group is
    AMBIGUOUS.
    """
    txns = [txn("t0", 21456, "2026-01-01"), txn("t1", 21456, "2026-01-10")]
    rs = [rcpt(21456, "2026-01-09", prov="anthropic:invoice A"),
          rcpt(21456, "2026-01-10", prov="gmail:msg B")]
    pairs = match(txns, rs)

    for p in pairs:
        if p.receipt is not None:
            assert _within(p.transaction.date, p.receipt.date, 3), (
                f"{p.transaction.id} ({p.transaction.date}) bound a receipt dated "
                f"{p.receipt.date} — outside the ±3 day window"
            )
    assert {p.outcome for p in pairs} == {AMBIGUOUS}


def _within(a: str, b: str, days: int) -> bool:
    import datetime
    return abs((datetime.date.fromisoformat(a) - datetime.date.fromisoformat(b)).days) <= days


if __name__ == "__main__":
    print("Running match tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll match tests passed.")
