#!/usr/bin/env python3.12
"""Upload a matched receipt to Ramp and record the outcome."""

import base64
import hashlib
import json
from pathlib import Path

from txn_queue import needs_receipt
from ramp import run

MAX_ATTEMPTS = 2
WHY = "Attach the receipt I located for this transaction so it clears Ramp's missing-items queue"


def idempotency_key(transaction_id: str, provenance: str) -> str:
    return hashlib.sha256(f"{transaction_id}|{provenance}".encode()).hexdigest()


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, list[dict]] = {}
        if self.path.exists():
            self.entries = json.loads(self.path.read_text())

    def record(self, txn_id: str, provenance: str, status: str) -> None:
        self.entries.setdefault(txn_id, []).append({"provenance": provenance, "status": status})

    def attempts(self, txn_id: str) -> int:
        return len(self.entries.get(txn_id, []))

    def status(self, txn_id: str) -> str | None:
        rows = self.entries.get(txn_id)
        return rows[-1]["status"] if rows else None

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=2))


def upload(pairing, ledger: Ledger, dry_run: bool) -> str:
    txn, rec = pairing.transaction, pairing.receipt

    if dry_run:
        return "DRY_RUN"

    # Re-check Ramp: the receipt may have landed since the queue was built.
    if not needs_receipt(txn.id):
        ledger.record(txn.id, rec.provenance, "SKIPPED")
        return "SKIPPED"

    if ledger.attempts(txn.id) >= MAX_ATTEMPTS and ledger.status(txn.id) != "UPLOADED":
        ledger.record(txn.id, rec.provenance, "ESCALATED")
        return "ESCALATED"

    args = [
        "receipts", "upload",
        "--transaction_uuid", txn.id,
        "--idempotency_key", idempotency_key(txn.id, rec.provenance),
        "--filename", "receipt.pdf",
        "--content_type", "application/pdf",
        "--file_content_base64", base64.b64encode(rec.pdf_bytes).decode(),
    ]
    try:
        run(args, rationale=WHY)
    except Exception:
        ledger.record(txn.id, rec.provenance, "FAILED")
        return "FAILED"

    ledger.record(txn.id, rec.provenance, "UPLOADED")
    return "UPLOADED"
