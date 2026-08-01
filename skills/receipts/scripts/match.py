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
    # This prevents double-binding when the same logical receipt appears multiple times
    # (e.g., emailed receipt from Gmail + billing-portal invoice from Anthropic source).
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

        if len(candidates) != len(txns):
            note = f"{len(txns)} transactions vs {len(candidates)} receipts at ${cents/100:,.2f}"
            pairs.extend(Pairing(t, None, AMBIGUOUS, note) for t in txns)
            continue

        outcome = CONFIDENT if len(txns) == 1 else BALANCED
        note = "" if outcome == CONFIDENT else f"{len(txns)} indistinguishable charges, zipped by date"
        for t, r in zip(txns, candidates):
            pairs.append(Pairing(t, r, outcome, note))

    return pairs
