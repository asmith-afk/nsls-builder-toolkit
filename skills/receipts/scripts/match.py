#!/usr/bin/env python3.12
"""Bind receipts to transactions. Pure — no network, no filesystem, no clock."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from txn_queue import Transaction
from sources.base import Receipt, normalize_merchant

CONFIDENT = "CONFIDENT"
BALANCED = "BALANCED"
AMBIGUOUS = "AMBIGUOUS"
UNFOUND = "UNFOUND"


@dataclass(frozen=True)
class Pairing:
    transaction: Transaction
    receipt: Receipt | None
    outcome: str
    note: str


def _days_apart(a: str, b: str) -> int:
    return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)


def match(transactions: list[Transaction], receipts: list[Receipt],
          window_days: int = 3) -> list[Pairing]:
    # Dedupe receipts by provenance, keeping first occurrence and deterministic order.
    # This catches ONE source handing back the same receipt twice — a paginated
    # fetch that overlaps, a retry that appends. It cannot catch the same charge
    # arriving from two DIFFERENT sources: provenance is source-namespaced by
    # construction ("anthropic:invoice …" vs "gmail:msg …"), so those two strings
    # never collide. That case is handled inside the grouping loop below.
    seen_provenance: set[str] = set()
    deduped_receipts: list[Receipt] = []
    for r in receipts:
        if r.provenance not in seen_provenance:
            deduped_receipts.append(r)
            seen_provenance.add(r.provenance)
    receipts = deduped_receipts

    groups: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in transactions:
        groups[(normalize_merchant(t.merchant), t.amount_cents)].append(t)

    pairs: list[Pairing] = []

    for (merchant, cents), txns in groups.items():
        txns = sorted(txns, key=lambda t: (t.date, t.id))

        candidates = sorted(
            (r for r in receipts
             if r.amount_cents == cents
             and normalize_merchant(r.merchant) == merchant
             and any(_days_apart(r.date, t.date) <= window_days for t in txns)),
            key=lambda r: (r.date, r.provenance),
        )

        if not candidates:
            pairs.extend(Pairing(t, None, UNFOUND, "no receipt in any source") for t in txns)
            continue

        # Cross-source duplicates. An Anthropic subscription charge lands in
        # BOTH sources — the billing portal and the receipt email — so a single
        # transaction can attract two receipts that are the same document by any
        # measure the tool can see. If the surplus candidates are identical on
        # (merchant, amount, date), they are duplicates of one another, not
        # evidence of extra charges: keep the first len(txns) in the already
        # deterministic sort order. The reverse asymmetry (FEWER receipts than
        # transactions) is real information — some charge genuinely has no
        # receipt — and must still land as AMBIGUOUS.
        if len(candidates) > len(txns):
            keys = {(normalize_merchant(r.merchant), r.amount_cents, r.date) for r in candidates}
            if len(keys) == 1:
                candidates = candidates[:len(txns)]

        if len(candidates) != len(txns):
            note = f"{len(txns)} transactions vs {len(candidates)} receipts at ${cents/100:,.2f}"
            pairs.extend(Pairing(t, None, AMBIGUOUS, note) for t in txns)
            continue

        assignment = list(zip(txns, candidates))

        # The candidate filter above only proves each receipt is within the
        # window of SOME transaction in the group. After zipping, each pair has
        # to hold on its own — otherwise two identical charges nine days apart
        # with both receipts near the later one produce a BALANCED (and
        # therefore uploadable) pairing that attaches the wrong receipt in Ramp.
        far = [(t, r) for t, r in assignment if _days_apart(r.date, t.date) > window_days]
        if far:
            note = (f"{len(txns)} indistinguishable charges, but the date-ordered "
                    f"assignment puts {len(far)} of them more than {window_days} days "
                    f"from its receipt")
            pairs.extend(Pairing(t, None, AMBIGUOUS, note) for t in txns)
            continue

        outcome = CONFIDENT if len(txns) == 1 else BALANCED
        note = "" if outcome == CONFIDENT else f"{len(txns)} indistinguishable charges, zipped by date"
        for t, r in assignment:
            pairs.append(Pairing(t, r, outcome, note))

    return pairs
