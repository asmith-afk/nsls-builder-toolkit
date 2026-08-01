#!/usr/bin/env python3.12
"""`/receipts` entry point. Dry run by default."""

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from match import AMBIGUOUS, BALANCED, CONFIDENT, UNFOUND, match
from txn_queue import missing_receipts
from ramp import RampAuthError, RampError
from sources.base import SourceUnavailable, load_sources
from upload import Ledger, upload

LEDGER_PATH = Path(os.path.expanduser("~/.claude-receipts-ledger.json"))
ACTIONABLE = (CONFIDENT, BALANCED)


def build_report(pairings, results, skipped_sources) -> str:
    lines = ["# Receipts → Ramp", ""]

    for note in skipped_sources:
        name, _, reason = note.partition(": ")
        # A TRUNCATED note means the source ran successfully and returned
        # partial results — it was never skipped. Wrapping it as
        # "SKIPPED (TRUNCATED (...))" tells the user something untrue about
        # what happened, and "SKIPPED" is exactly the word that stops most
        # readers from reading further. Render it plainly instead.
        if reason.startswith("TRUNCATED"):
            lines.append(f"SOURCE {name}: {reason}")
        else:
            lines.append(f"SOURCE {name}: SKIPPED ({reason})")
    if skipped_sources:
        lines.append("")

    # A pairing only counts as outstanding if its receipt did NOT successfully
    # upload — regardless of outcome. A BALANCED pairing (e.g. one of four
    # indistinguishable $214.56 charges) that uploaded fine must not be
    # double-counted as still missing just because it isn't CONFIDENT.
    outstanding = sum(p.transaction.amount_cents for p in pairings
                      if results.get(p.transaction.id) != "UPLOADED")
    lines.append(f"**{len(pairings)} transactions missing receipts — "
                 f"${outstanding/100:,.2f} outstanding**")
    lines.append("")

    ready = [p for p in pairings if p.outcome in ACTIONABLE]
    if ready:
        lines.append(f"## Ready ({len(ready)})")
        for p in ready:
            t = p.transaction
            tag = f" [{p.outcome}]" if p.outcome == BALANCED else ""
            lines.append(f"- {t.date}  {t.merchant}  ${t.amount_cents/100:,.2f}  "
                         f"← {p.receipt.provenance}  {results.get(t.id,'PENDING')}{tag}")
        lines.append("")

    for outcome, title in ((AMBIGUOUS, "Needs your call"), (UNFOUND, "No receipt found")):
        rows = [p for p in pairings if p.outcome == outcome]
        if not rows:
            continue
        lines.append(f"## {title} ({len(rows)})")
        for p in rows:
            t = p.transaction
            suffix = f"  {p.note}" if p.note else ""
            lines.append(f"- {t.date}  {t.merchant}  ${t.amount_cents/100:,.2f}{suffix}")
        lines.append("")

    if not pairings:
        lines.append("Nothing missing a receipt in this window.")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="receipts")
    ap.add_argument("--send", action="store_true", help="execute (default is dry run)")
    ap.add_argument("--since", default="2026-01-01", help="ISO date; backlog reaches to 2026-02")
    ap.add_argument("--until", default=None, help="ISO date; default today")
    args = ap.parse_args(argv)

    until = args.until or dt.date.today().isoformat()

    def progress(i, n):
        print(f"\r  checking {i}/{n}…", end="", file=sys.stderr, flush=True)

    try:
        txns = missing_receipts(args.since, until, progress=progress)
    except RampAuthError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2
    except RampError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2
    print("", file=sys.stderr)

    receipts, skipped = [], []
    for src in load_sources():
        name = type(src).__name__.replace("Source", "").upper()
        try:
            receipts.extend(src.fetch(args.since, until))
            # A source can hit an internal cap (e.g. Gmail's pagination
            # guard) and return normally with a partial result instead of
            # raising. If that never reaches the report, the user sees a
            # clean run with fewer receipts and no sign anything was
            # truncated — announce it through the same channel as a skipped
            # source, while still using the partial results it did return.
            truncated = getattr(src, "truncated", None)
            if truncated:
                skipped.append(f"{name}: TRUNCATED ({truncated})")
        except SourceUnavailable as exc:
            skipped.append(f"{name}: {exc}")
        except Exception as exc:
            # A source blowing up on a network timeout, a bad JSON payload, or
            # anything else it didn't anticipate must never take down the
            # whole run — the user still gets results from every other source.
            skipped.append(f"{name}: unexpected error — {exc}")

    pairings = match(txns, receipts)

    try:
        ledger = Ledger(LEDGER_PATH)
    except Ledger.CorruptLedger as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2

    results = {}
    for p in pairings:
        if p.outcome in ACTIONABLE:
            results[p.transaction.id] = upload(p, ledger, dry_run=not args.send)
    ledger.save()

    print(build_report(pairings, results, skipped))
    if not args.send:
        print("\nDry run — nothing uploaded. Re-run with --send to execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
