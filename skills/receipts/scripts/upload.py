#!/usr/bin/env python3.12
"""Upload a matched receipt to Ramp and record the outcome."""

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

from txn_queue import needs_receipt
from ramp import RampAuthError, RampError, run

MAX_ATTEMPTS = 2
WHY = "Attach the receipt I located for this transaction so it clears Ramp's missing-items queue"


def idempotency_key(transaction_id: str, provenance: str) -> str:
    return hashlib.sha256(f"{transaction_id}|{provenance}".encode()).hexdigest()


class Ledger:
    class CorruptLedger(Exception):
        """The ledger file is corrupted and cannot be loaded."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, list[dict]] = {}
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text())
            except json.JSONDecodeError as e:
                raise self.CorruptLedger(
                    f"Ledger corrupted at {self.path.resolve()}\n"
                    f"It is safe to delete this file — uploads are idempotent and will retry.\n"
                    f"Error: {e}"
                ) from e

    def record(self, txn_id: str, provenance: str, status: str, transient: bool = False) -> None:
        entry = {"provenance": provenance, "status": status}
        if transient:
            # Kept in the ledger so the failure is visible, but flagged so it
            # does not count against the escalation cap. See attempts().
            entry["transient"] = True
        self.entries.setdefault(txn_id, []).append(entry)

    def attempts(self, txn_id: str) -> int:
        # Transient entries (network blips, a dead session, anything that never
        # reached Ramp's judgment) don't count. MAX_ATTEMPTS is 2 — counting
        # them means two unlucky timeouts retire a transaction permanently,
        # clearable only by deleting the ledger by hand.
        return sum(1 for e in self.entries.get(txn_id, []) if not e.get("transient"))

    def status(self, txn_id: str) -> str | None:
        rows = self.entries.get(txn_id)
        return rows[-1]["status"] if rows else None

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to temp file in same directory, then replace.
        # os.replace() is atomic on both POSIX and Windows.
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), text=True)
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(json.dumps(self.entries, indent=2))
            os.replace(tmp_path, str(self.path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise


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
    except RampAuthError:
        # Not this transaction's fault and not a rejection — the session died.
        # Let it out so the caller aborts the whole run cleanly; recording it
        # here would burn an escalation attempt and bury a dead login inside a
        # per-transaction FAILED line.
        raise
    except RampError:
        # Ramp looked at the request and refused it. That is a real attempt.
        ledger.record(txn.id, rec.provenance, "FAILED")
        return "FAILED"
    except Exception:
        # Transport-level: timeout, reset connection, unparseable response.
        # Reported as FAILED, but not counted toward MAX_ATTEMPTS.
        ledger.record(txn.id, rec.provenance, "FAILED", transient=True)
        return "FAILED"

    ledger.record(txn.id, rec.provenance, "UPLOADED")
    return "UPLOADED"
