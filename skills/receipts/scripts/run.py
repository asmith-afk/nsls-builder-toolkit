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


def _source_lines(skipped_sources, sources_loaded, sources_searched=None) -> list[str]:
    lines = []
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

    # Stated every run, not just when something went wrong. "No receipt in any
    # source" and "there were no sources" print identically otherwise, and the
    # second one is a broken install reading as a clean audit.
    #
    # "loaded" and "searched" are deliberately kept as two separate numbers.
    # A source can *import* cleanly (its module has no syntax error, its
    # dependencies are installed) and still never *search* anything, because
    # it fails inside fetch() — missing ANTHROPIC_ORG_UUID, no `gws` CLI on
    # PATH, a dead auth session. "2 loaded" reads as reassuring; a reader
    # must not be able to mistake it for "2 searched".
    names = list(sources_loaded or [])
    searched_n = len(sources_searched) if sources_searched is not None else len(names)
    lines.append(f"SOURCES: {len(names)} loaded, {searched_n} searched "
                 f"({', '.join(names) if names else 'none'})")
    lines.append("")
    return lines


def build_report(pairings, results, skipped_sources, sources_loaded=None, sources_searched=None) -> str:
    lines = ["# Receipts → Ramp", ""]
    lines.extend(_source_lines(skipped_sources, sources_loaded, sources_searched))

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

    receipts, skipped, loaded, searched = [], [], [], []
    # A source that fails at import (missing dependency, syntax error) is
    # reported and skipped — it must not end discovery for the others.
    import_errors: list[str] = []
    sources = load_sources(import_errors) or []
    skipped.extend(import_errors)

    for src in sources:
        name = type(src).__name__.replace("Source", "").upper()
        loaded.append(name)
        try:
            receipts.extend(src.fetch(args.since, until))
            # fetch() returned without raising — this source actually
            # searched, even if (below) it turns out to have been a partial
            # search. `loaded` only proves the module imported; `searched` is
            # the one that matters for "did anything look."
            searched.append(name)
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

    # Zero sources *searched* means nothing was searched — not zero sources
    # *loaded*. Both real sources (anthropic.py, gmail.py) fail inside
    # fetch(), not at import: missing ANTHROPIC_ORG_UUID, no `gws` CLI, a
    # dead auth session. A guard keyed on "loaded" never fires for that path
    # — the default experience of an unconfigured install — because `loaded`
    # is populated before fetch() is ever called. Keying on `searched`
    # catches it: every transaction would otherwise come back UNFOUND — "no
    # receipt in any source" — and the run would exit 0 looking like a
    # completed audit that simply found nothing. That is an empty result
    # that means we didn't look, and it must not be reported as a finding.
    # (With no transactions in the window there is no UNFOUND to misreport,
    # so that case still exits 0 — but the SOURCES line above always shows
    # the true loaded/searched split. And a partial run — 1 of 2 sources
    # searched — is a normal degraded run, not this failure: it proceeds,
    # and UNFOUND is legitimate for what the working source genuinely didn't
    # find.)
    if not searched and pairings:
        print("\n".join(["# Receipts → Ramp", ""] + _source_lines(skipped, loaded, searched)))
        print(f"\nERROR: no receipt source was able to search — {len(pairings)} transactions "
              f"are missing a receipt and none of them were searched. Refusing to report them "
              f"as 'no receipt found'. Fix source setup (see the SOURCE lines above and "
              f"the Setup section of SKILL.md) and re-run.", file=sys.stderr)
        return 2

    try:
        ledger = Ledger(LEDGER_PATH)
    except Ledger.CorruptLedger as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2

    results = {}
    exit_code = 0
    try:
        for p in pairings:
            if p.outcome not in ACTIONABLE:
                continue
            try:
                results[p.transaction.id] = upload(p, ledger, dry_run=not args.send)
            except RampAuthError:
                # The session died mid-run. Nothing after this can succeed —
                # stop, but through the same clean exit-2 path as an auth
                # failure at queue-build time, with the ledger saved.
                raise
            except Exception as exc:
                # One transaction's upload blowing up must not discard the
                # ledger records of the ones that already worked, or suppress
                # the report for everything else.
                results[p.transaction.id] = "ERROR"
                print(f"\nERROR uploading {p.transaction.id} "
                      f"({p.transaction.merchant}): {type(exc).__name__}: {exc}",
                      file=sys.stderr)
    except RampAuthError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        exit_code = 2
    finally:
        # Uploads already happened in Ramp. The ledger is the only record that
        # they did — it gets written whether the loop finished or not.
        ledger.save()

    if exit_code:
        return exit_code

    print(build_report(pairings, results, skipped, loaded, searched))
    if not args.send:
        print("\nDry run — nothing uploaded. Re-run with --send to execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
