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


def _source_of(provenance: str) -> str:
    """The source that produced a receipt, read off its provenance string.

    Provenance is source-namespaced by construction — "anthropic:invoice …",
    "gmail:msg …" — so everything before the FIRST ':' names the source. A
    provenance with no ':' is its own source rather than a shared empty
    namespace: two unnamespaced strings must never be read as one source.
    """
    head, sep, _ = provenance.partition(":")
    return head if sep else provenance


def _one_document_per_source(candidates: list[Receipt]) -> bool:
    """True when no single source contributed two DIFFERENT documents.

    This is the only signal available to tell the two meanings of a surplus
    apart:

    * One charge seen once per source. Anthropic emails a receipt AND exposes
      a portal invoice for the same subscription charge — two documents, two
      sources, one charge. Collapsing is correct; either document is a valid
      receipt.
    * Two genuinely different charges, only one of which is outstanding. Two
      same-price purchases from the same merchant on the same day, one of
      which already has a receipt. Collapsing here uploads the wrong document
      to a real financial record.

    A source returning two different documents for the same merchant/amount/
    date is the second case: its own view of that day holds two receipts, so
    there were two charges. Byte-identical documents are the same document no
    matter how many provenances or sources carry them, so they never count as
    a second document.
    """
    per_source: dict[str, set[bytes]] = defaultdict(set)
    for r in candidates:
        per_source[_source_of(r.provenance)].add(r.pdf_bytes)
    return all(len(docs) == 1 for docs in per_source.values())


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
        # transaction can attract two receipts that are the same charge seen
        # twice. Being identical on (merchant, amount, date) is NOT enough to
        # prove that: two same-price purchases from one merchant on one day
        # look exactly the same, and collapsing them attaches the wrong
        # document to a real financial record. The surplus only collapses when
        # it also reads as one document per source (see
        # _one_document_per_source) — then keep the first len(txns) in the
        # already deterministic sort order. Otherwise the surplus is evidence
        # of extra charges and falls through to AMBIGUOUS below. The reverse
        # asymmetry (FEWER receipts than transactions) is real information —
        # some charge genuinely has no receipt — and must still land as
        # AMBIGUOUS too.
        if len(candidates) > len(txns):
            keys = {(normalize_merchant(r.merchant), r.amount_cents, r.date) for r in candidates}
            if len(keys) == 1 and _one_document_per_source(candidates):
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
