#!/usr/bin/env python3.12
"""Build the missing-receipt queue from Ramp.

⚠️ `missing_items` in `transactions list` is ALWAYS null — it means "not computed",
not "nothing missing". Trusting it yields an empty queue while the Ramp UI shows 28
items. The only ground truth is `ramp transactions missing <uuid>`, one call per
transaction. Slow, but correct.
"""

from dataclasses import dataclass

from ramp import RampError, parse_amount, run

LIST_WHY = "Audit which of my transactions still need a receipt, to attach them automatically"
CHECK_WHY = "Verify whether this specific transaction still needs a receipt before attaching one"


@dataclass(frozen=True)
class Transaction:
    id: str
    merchant: str
    amount_cents: int
    date: str  # ISO yyyy-mm-dd


def _one(args: list[str], rationale: str) -> dict:
    """Run a Ramp command that must return exactly one result object.

    `run()` hands back `payload["data"]`, which can legitimately be empty —
    that is its contract, and list endpoints rely on it. Indexing [0] here
    without a guard turns an empty response into a raw IndexError: uncaught by
    main(), which only handles RampError, and fatal to the whole send loop
    when it happens on the per-transaction re-check.
    """
    rows = run(args, rationale=rationale)
    if not rows:
        raise RampError(f"ramp {' '.join(args)} returned no data")
    return rows[0]


def list_transactions(since: str, until: str) -> list[Transaction]:
    out, cursor = [], None
    while True:
        args = [
            "transactions", "list",
            "--transactions_to_retrieve", "my_transactions",
            "--from_date", since, "--to_date", until,
            "--page_size", "100",
        ]
        if cursor:
            args += ["--next_page_cursor", cursor]

        page = _one(args, LIST_WHY)
        for t in page.get("transactions", []):
            out.append(
                Transaction(
                    id=t["transaction_uuid"],
                    merchant=t.get("merchant_name") or "",
                    amount_cents=parse_amount(t.get("amount")),
                    date=(t.get("transaction_time") or "")[:10],
                )
            )
        cursor = page.get("next_page_cursor")
        if not cursor:
            return out


def needs_receipt(txn_id: str) -> bool:
    row = _one(["transactions", "missing", txn_id], CHECK_WHY)
    return bool(row.get("missing_receipt"))


def missing_receipts(since: str, until: str, progress=None) -> list[Transaction]:
    txns = list_transactions(since, until)
    out = []
    for i, t in enumerate(txns, 1):
        if progress:
            progress(i, len(txns))
        if needs_receipt(t.id):
            out.append(t)
    return out
