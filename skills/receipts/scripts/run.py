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
from sources.anthropic import _set_session as anthropic_set_session
from sources.base import SourceUnavailable, load_sources
from upload import Ledger, upload

LEDGER_PATH = Path(os.path.expanduser("~/.claude-receipts-ledger.json"))
ACTIONABLE = (CONFIDENT, BALANCED)
# Upload outcomes that mean the transaction is no longer missing a receipt:
# UPLOADED (we attached one) and SKIPPED (Ramp already had one). Everything
# else — DRY_RUN, FAILED, ESCALATED, ERROR, PENDING — leaves the gap open.
RESOLVED = ("UPLOADED", "SKIPPED")


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
    # upload and Ramp doesn't already have one — regardless of outcome. A
    # BALANCED pairing (e.g. one of four indistinguishable $214.56 charges)
    # that uploaded fine must not be double-counted as still missing just
    # because it isn't CONFIDENT.
    #
    # The COUNT is computed from the same list as the dollar figure. Printing
    # len(pairings) beside a filtered total let a successful --send report
    # "1 transactions missing receipts — $0.00 outstanding": a headline that
    # contradicts itself and names cleared transactions as gaps.
    still_missing = [p for p in pairings
                     if results.get(p.transaction.id) not in RESOLVED]
    outstanding = sum(p.transaction.amount_cents for p in still_missing)
    lines.append(f"**{len(still_missing)} transactions missing receipts — "
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
    ap.add_argument("--set-session", action="store_true",
                     help="store a claude.ai session cookie for the Anthropic billing "
                          "source and exit — prompts for the value (hidden), validates "
                          "it live, and writes it 0600; does not build the queue, "
                          "fetch, or upload anything")
    ap.add_argument("--login", action="store_true",
                     help="deprecated alias for --set-session (there is no browser step "
                          "any more — the Anthropic source uses a stored session cookie)")
    args = ap.parse_args(argv)

    # `run.py` is the single documented entry point for everything this tool
    # does, authentication included — it already resolves imports correctly
    # (unlike running sources/anthropic.py as a bare script, which used to
    # crash with an ImportError on exactly the command SKILL.md told a user to
    # run for a dead claude.ai session).
    #
    # --login is kept as an alias because it is in shipped docs, in old error
    # strings, and in muscle memory — an unknown-flag error would be a dead
    # end for anyone following those. It explains the change and does the new
    # thing rather than silently accepting the old name.
    #
    # Either flag does ONE thing — store a session — and returns immediately:
    # no Ramp queue, no source fetch, no upload. Combining it with --send is
    # almost certainly a mistake (the user meant "authenticate, then
    # separately send"), so it's rejected explicitly rather than silently
    # picking one or doing both.
    if args.set_session or args.login:
        flag = "--set-session" if args.set_session else "--login"
        if args.send:
            print(f"ERROR: {flag} and --send cannot be combined. {flag} only stores a "
                  f"claude.ai session, then exits — it does not build the queue, fetch "
                  f"receipts, or upload anything, so there is nothing for --send to act "
                  f"on in the same invocation. Run {flag} by itself first, then run the "
                  f"tool again (add --send once you're ready to execute).",
                  file=sys.stderr)
            return 2
        if args.login:
            print("NOTE: --login is now --set-session. There is no browser step any more "
                  "— the Anthropic billing source authenticates with a stored session "
                  "cookie. Running --set-session for you.", file=sys.stderr)
        return anthropic_set_session()

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
    except OSError as exc:
        # Ledger.exists() or .read_text() can fail on permissions, a missing
        # home directory, or any other OS-level problem — distinct from
        # CorruptLedger (the file loaded but its contents were invalid).
        # Don't call it corrupt; it may not have been readable at all, and
        # "delete it, uploads are idempotent" is the wrong advice here.
        print(f"\nERROR: could not read the ledger at {LEDGER_PATH}: {exc}", file=sys.stderr)
        return 2

    results = {}
    exit_code = 0
    ledger_error: Exception | None = None
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
                # the report for everything else — the loop keeps going. But
                # the RUN did not do what it was asked to do: a receipt Ramp
                # still needs was not attached. Exiting 0 here tells anything
                # reading the exit code (cron, CI, a wrapper script) that a
                # partially-failed send was a clean run, and the failure is
                # never noticed because nobody reads the report.
                results[p.transaction.id] = "ERROR"
                exit_code = 1
                print(f"\nERROR uploading {p.transaction.id} "
                      f"({p.transaction.merchant}): {type(exc).__name__}: {exc}",
                      file=sys.stderr)
    except RampAuthError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        exit_code = 2
    finally:
        # Uploads already happened in Ramp. The ledger is the only record that
        # they did — it gets written whether the loop finished or not.
        #
        # Two conditions on that write, both about not turning a bookkeeping
        # problem into the user's whole result:
        #
        # 1. Only if something was actually recorded. A dry run attempts no
        #    upload and adds no entry, so it has nothing to persist — and a
        #    read-only home or a full disk must not make an otherwise perfect
        #    dry run die on a file it had no reason to open.
        # 2. Never as an escaping exception. An OSError out of save() here
        #    would replace the report with a traceback, and — worse — would
        #    fire from inside the `finally` while the auth-abort path is
        #    unwinding, replacing a controlled exit 2 with a crash. It is
        #    captured and reported below instead, after the report prints.
        if ledger.dirty:
            try:
                ledger.save()
            except OSError as exc:
                ledger_error = exc

    def _report_ledger_error() -> None:
        print(f"\nERROR: could not write the receipts ledger at {ledger.path}: "
              f"{type(ledger_error).__name__}: {ledger_error}\n"
              f"Uploads that reached Ramp this run are NOT recorded locally. Re-running is "
              f"safe — uploads are idempotent — but retry counts and escalations for this "
              f"run were lost. Fix write access to that path and re-run.", file=sys.stderr)

    # An auth abort is terminal: everything after it was skipped, so there is
    # no run to report on. A failed individual upload is not — the rest of the
    # run really happened and the user needs to see it, so the report still
    # prints and the nonzero code rides out alongside it.
    if exit_code == 2:
        # A failed ledger write is reported, but it must not downgrade (or
        # upgrade) the auth abort — exit 2 is what the caller is watching for.
        if ledger_error is not None:
            _report_ledger_error()
        return exit_code

    print(build_report(pairings, results, skipped, loaded, searched))
    if not args.send:
        print("\nDry run — nothing uploaded. Re-run with --send to execute.")

    # After the report, never instead of it. The run's findings are the thing
    # the user came for; a ledger the tool could not write is a real failure
    # that has to show up in the exit code, but it does not erase the results.
    if ledger_error is not None:
        _report_ledger_error()
        exit_code = exit_code or 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
