#!/usr/bin/env python3.12
"""Tests for match.py — pure, no I/O.

Fixtures are real: the four-way $214.56 collision on 2026-07-23 and the
$1,085.00 single on 2026-07-19, both from Kevin's live Ramp queue.
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


def test_duplicate_receipt_provenance_does_not_bind_to_multiple_transactions():
    """Receipts with identical provenance must not be bound to multiple transactions.

    This occurs when Task 8 adds Gmail source alongside Anthropic: subscription charges
    produce both an emailed receipt (Gmail) and a billing-portal invoice (Anthropic).
    Both are Receipt objects with the same logical receipt, but appear as separate list
    entries. Without dedup, one transaction binds to both while another goes unreceipted.
    """
    txns = [txn(f"t{i}", 21456) for i in range(2)]
    # Two Receipt objects with the same provenance (simulating the Gmail+Anthropic case)
    rs = [rcpt(21456, prov="invoice-A"), rcpt(21456, prov="invoice-A")]
    pairs = match(txns, rs)

    # Count how many times each provenance is bound
    provenance_to_txns = {}
    for p in pairs:
        if p.receipt:
            prov = p.receipt.provenance
            if prov not in provenance_to_txns:
                provenance_to_txns[prov] = []
            provenance_to_txns[prov].append(p.transaction.id)

    # Each unique provenance should be bound to at most one transaction
    for prov, txn_ids in provenance_to_txns.items():
        assert len(txn_ids) == 1, (
            f"Provenance {prov} bound to {len(txn_ids)} transactions: {txn_ids}. "
            "Dedup must ensure each receipt binds to at most one transaction."
        )


if __name__ == "__main__":
    print("Running match tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll match tests passed.")
