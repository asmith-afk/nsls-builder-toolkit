---
name: receipts
description: Find Ramp transactions missing receipts, fetch each receipt from Anthropic's billing API or Gmail, and upload it to Ramp against the exact transaction. Use when the user says "receipts", "/receipts", "missing receipts", "Ramp needs a receipt", "receipt cleanup", or forwards a Ramp "transaction needs a receipt" nag. Dry run by default.
---

# Receipts → Ramp

Clears Ramp's missing-receipt queue automatically instead of the manual
"find the email, download the PDF, open Ramp, attach it" ritual.

## What it does

1. Pulls every Ramp transaction in the date window and checks each one for
   a missing receipt (this is a per-transaction API call — see
   [Troubleshooting](#troubleshooting) for why).
2. Fetches candidate receipts from every configured source (Anthropic
   billing, Gmail) — each source degrades independently, see
   [Setup](#setup).
3. Matches receipts to transactions on merchant + amount + date
   (see [Match outcomes](#the-four-match-outcomes)).
4. Uploads the confident matches to Ramp and prints a report of everything
   else that needs a human.

**Default posture: dry run.** `/receipts` alone shows you the plan —
what would upload, what's ambiguous, what has no receipt anywhere — and
changes nothing in Ramp. Nothing is ever uploaded without `--send`.

## Usage

- `/receipts` — show the plan, change nothing
- `/receipts --send` — execute (upload the confident + balanced matches)
- `/receipts --since 2026-01-01` — widen the window (default: `2026-01-01`)
- `/receipts --until 2026-06-30` — narrow the window (default: today)
- `/receipts --login` — log in to the Anthropic billing source (opens a
  browser) and exit; does not build the queue, fetch, or upload anything.
  Not combinable with `--send`.

## Execution

**Everything below this section describes what the script does. None of it
happens unless you run the script.** This file is prompt content, not a
command definition — reading it executes nothing. Reciting the workflow from
these notes instead of running `run.py` produces a report of a run that never
happened, which is the worst possible output: a clean-looking audit of nothing.

Run it from the repository root, so the relative path resolves:

```bash
python3.12 skills/receipts/scripts/run.py
```

That is the dry run — it reaches Ramp and the receipt sources read-only and
uploads nothing. To execute the uploads, and only when the user has actually
asked to send:

```bash
python3.12 skills/receipts/scripts/run.py --send
```

Map the user's request onto the flags and pass them through verbatim:

| The user says | You run |
|---|---|
| "receipts", "what's missing", anything unqualified | the bare command above (dry run) |
| "send", "upload them", "do it", "go ahead" | add `--send` |
| any start date ("since June", "from 2026-06-01") | add `--since 2026-06-01` |
| any end date ("through June", "up to 2026-06-30") | add `--until 2026-06-30` |
| a month or range ("June receipts") | both: `--since 2026-06-01 --until 2026-06-30` |

Dates are ISO `YYYY-MM-DD`. `--since` defaults to `2026-01-01` and `--until`
to today; omit either flag when the user didn't ask for it. Both bounds are
inclusive.

Then **relay the script's own output** — the markdown report it prints on
stdout, plus any `SOURCE …: SKIPPED/TRUNCATED` lines and its exit code. Do not
paraphrase this document in place of that report, do not summarize a run you
did not make, and do not describe expected results. If the script exits
non-zero, show its stderr message and stop; the exit codes are explained under
[Troubleshooting](#troubleshooting). If the run was a dry run, say so
explicitly and tell the user that `--send` is what executes it.

## Setup

Three independent prerequisites. **None of them are required for the other
two to work** — a missing prerequisite skips only that piece and says so in
the report; it never fails the whole run.

### 1. Ramp (required — this is the queue itself)

```bash
curl -fsSL https://agents.ramp.com/install.sh | sh
ramp auth login
```

Install via the script above, not Homebrew. `brew install
ramp-public/ramp/ramp-cli` works in principle — the formula just fetches a
prebuilt binary, no compile step — but Homebrew's own preflight refuses to
run at all on a machine with outdated Xcode Command Line Tools (`Error:
Your Command Line Tools are too outdated` — observed 2026-08-01, before the
formula ever runs). The install script sidesteps that check entirely and
fetches the same prebuilt binary directly. Without this step,
`/receipts` can't even build the list of transactions that need a receipt —
this one isn't optional.

### 2. Gmail source (optional)

```bash
gws auth login -s gmail
```

Covers vendors that email a receipt PDF: Asana, Groq, OpenAI, Hex, and
others as your inbox has them. If `gws` isn't authenticated, the Gmail
source is skipped and announced in the report; every other source still
runs.

### 3. Anthropic source (optional)

Two things, both required for this source specifically:

```bash
export ANTHROPIC_ORG_UUID=<your-claude.ai-org-uuid>   # Settings > Organization
python3.12 -m pip install --user --break-system-packages playwright
python3.12 -m playwright install chromium
```

The two pip flags are not optional on a Mac. Homebrew's python3.12 is a PEP 668
"externally managed" interpreter, so the plain `pip install` form aborts before
installing anything:

```
error: externally-managed-environment
× This environment is externally managed
```

`--user --break-system-packages` is the documented escape and is what was
verified working on this toolkit's reference machine (2026-08-01). It installs
into your own user site-packages, not Homebrew's tree. A virtualenv works too,
but then every `python3.12` invocation in this skill has to run inside it.

Then log in once (opens a real browser window):

```bash
python3.12 skills/receipts/scripts/run.py --login
```

This source is how usage-credit auto-recharge charges get a receipt at
all — Anthropic does **not** email those (see the coverage note below). If
`ANTHROPIC_ORG_UUID` isn't set or Playwright isn't installed, this source is
skipped and announced; the rest of the run proceeds normally.

## The four match outcomes

Every outstanding transaction gets exactly one outcome. **Only the first two
ever upload anything to Ramp.**

A charge that appears in two sources at once (Anthropic subscription charges
arrive as both a billing-portal invoice and a receipt email) is not two
charges. Extra receipts identical on merchant, amount, and date collapse to
the number of transactions before the counts are compared — **but only when
no single source contributed two different documents.** Being identical on
merchant/amount/date is not proof of a duplicate: two same-price purchases
from one merchant on one day look exactly the same, and one of them may
already have its receipt and so not be in the queue. What separates the two
is which source each document came from:

- **One document per source** (portal invoice + emailed receipt) → one charge
  seen once per source → collapses.
- **Two different documents from the same source** (two Gmail receipt emails)
  → that source only sees each charge once, so those are two real charges →
  stays `AMBIGUOUS`, nothing binds.
- **Byte-identical documents** are the same document no matter how many
  sources carry them → always safe to collapse.

Fewer receipts than transactions never collapses either — that gap is real
and stays `AMBIGUOUS`.

| Outcome | Meaning | Uploads? |
|---|---|---|
| `CONFIDENT` | Exactly one receipt matches exactly one transaction (merchant + amount + within the date window) | Yes |
| `BALANCED` | N receipts match N transactions with the same merchant/amount (e.g. four identical $214.56 charges) — sorted by date and zipped 1:1 | Yes |
| `AMBIGUOUS` | The receipt and transaction counts don't line up at a given merchant/amount (e.g. 3 transactions, 2 receipts) — including a surplus one source alone accounts for — or the date-ordered assignment would hand some transaction a receipt outside the window | No — listed for you to resolve by hand |
| `UNFOUND` | No receipt in any configured source | No — listed as a gap |

## Coverage — the known ceiling, not a defect

Measured on the reference NSLS Ramp account, 2026-08-01: of 22 outstanding
transactions,

- **~15** are Anthropic usage-credit auto-recharge charges — Anthropic sends
  no receipt email for these; they're only reachable through the Anthropic
  billing source.
- **1** (Asana) binds through the Gmail source.
- **~6** (Neon Tech, Supabase, Zoom, and similar) send **no receipt email at
  all** — no portal API, no email, nothing this skill can fetch
  automatically. These need manual handling: download from the vendor's own
  billing portal and attach in Ramp directly.

That last group is the honest ceiling of what `/receipts` can do today, not
a bug to chase — there's no automated source for them because the vendor
doesn't produce one. Don't expect the skill to close 22/22; expect it to
close what has a source, and leave a short, correctly-labeled manual list
for the rest.

## Troubleshooting

- **`RampAuthError`** — Ramp auth is dead. Run `ramp auth login`.
- **`SOURCE ANTHROPIC: SKIPPED (...)`** — the reason is in the message: set
  `ANTHROPIC_ORG_UUID`, install Playwright, or re-run
  `python3.12 skills/receipts/scripts/run.py --login` if the
  claude.ai session expired.
- **`SOURCE ANTHROPIC: SKIPPED (… HTTP 403 … not an org admin …)`** — a
  different failure that looks similar and is not fixable the same way. The
  claude.ai session is fine; the account just can't read that organization's
  billing invoices. Logging in again cannot change it. Ask an org owner for
  admin access, or unset `ANTHROPIC_ORG_UUID` to run without this source. A
  401 or a redirect is the session-expiry case above and *does* want
  `--login`.
- **`SOURCE <NAME>: TRUNCATED (...)`** — the source ran and returned
  **partial** results. This is not a skip and not a failure; it is an
  incomplete search, and any `UNFOUND` below it may be an artifact of what
  wasn't searched. Both sources report it the same way:
  - Gmail — the 50-page pagination cap was hit with more results pending.
  - Anthropic — the 20-page cap was hit, or the invoice listing claimed more
    pages while returning no cursor, or one or more invoice PDFs failed to
    download (those are named, with date and amount, in the message).

  Narrow the date window (`--since`/`--until`) and re-run to get a query small
  enough to finish. Download failures are usually transient — re-running is
  often enough.
- **`SOURCES: N loaded, 0 searched (...)` + exit 2** — zero sources actually
  searched, even though `N` loaded. "Loaded" only means the module imported
  cleanly; it says nothing about whether `fetch()` ever ran. On a fresh,
  unconfigured install this is the normal first run: both sources import
  fine and then fail *inside* `fetch()` — `ANTHROPIC_ORG_UUID` unset, no
  `gws` CLI on PATH, a dead auth session — so `loaded` is nonzero while
  `searched` stays 0. The run refuses to list transactions as "no receipt
  found" when nothing was searched for them. The `SOURCE …: SKIPPED (...)`
  lines printed above it say why each source failed; fix those and re-run.
  Every report states both numbers, every run, so "loaded" can never be
  misread as "worked."
- **`SOURCES: N loaded, M searched (...)` where 0 < M < N** — a normal
  degraded run, not a failure. Some sources searched and some didn't; the
  report proceeds, and `UNFOUND` is legitimate for what the searching
  source(s) genuinely didn't find. The dead source is still named on its own
  `SOURCE …: SKIPPED (...)` line above.
- **`ERROR uploading <id> …`** — that one upload failed; the rest of the run
  continued and the ledger was still saved. Transport-level failures
  (timeouts, reset connections) are recorded but do **not** count toward the
  2-attempt escalation cap; only failures Ramp itself rejected do. The full
  report still prints, but **the run exits 1** — a send where some receipt
  never got attached is not a clean run, and anything reading the exit code
  (cron, CI, a wrapper script) has to see that.
- **`CorruptLedger`** — the error message names the exact ledger file path.
  It's safe to delete it: every upload carries an idempotency key derived
  from the transaction + receipt provenance, so a fresh ledger just re-does
  the bookkeeping, it never double-uploads. This fires for any ledger that
  isn't the shape every reader assumes — including a hand-edited row whose
  `transient` flag is a string (`"false"`) instead of a real boolean, which
  would otherwise read as truthy and silently disable the 2-attempt
  escalation cap for that transaction.
- **`ERROR: could not write the receipts ledger at …`** — uploads that
  reached Ramp this run were not recorded locally (read-only home, bad
  permissions, full disk). The full report prints first and the run exits
  non-zero; re-running is safe (uploads are idempotent), but the retry counts
  and escalations from that run are gone. A **dry run never writes the
  ledger at all** — it records nothing, so an unwritable path can't affect
  it.
- **`ERROR: could not read the ledger at …`** — an *existing* ledger file
  couldn't be opened (no read permission, an inaccessible home directory).
  This is different from `CorruptLedger`: the file's contents were never
  read, so it may be perfectly valid — fix the permissions rather than
  deleting it. This check happens before any upload work, so it fires — and
  exits nonzero — even on a dry run.
- **`ESCALATED`** — this transaction hit the retry cap (2 attempts) without
  uploading. The skill will not retry it again. Attach the receipt manually
  in Ramp.
- **The queue comes back empty, but the Ramp UI shows outstanding
  items.** This was a real bug during development and is the single most
  likely regression to reintroduce by accident: `transactions list`'s
  `missing_items` field is **always `null`** — it means "not computed," not
  "nothing missing." The only ground truth is calling
  `ramp transactions missing <transaction_uuid>` once per transaction (see
  `txn_queue.needs_receipt`). If the queue is empty while Ramp's own UI
  shows items, something upstream started trusting `missing_items` instead
  of calling `transactions missing` per transaction — that's the bug to
  look for.
