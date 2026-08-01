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
python3.12 -m pip install playwright
python3.12 -m playwright install chromium
```

Then log in once (opens a real browser window):

```bash
python3.12 skills/receipts/scripts/sources/anthropic.py --login
```

This source is how usage-credit auto-recharge charges get a receipt at
all — Anthropic does **not** email those (see the coverage note below). If
`ANTHROPIC_ORG_UUID` isn't set or Playwright isn't installed, this source is
skipped and announced; the rest of the run proceeds normally.

## The four match outcomes

Every outstanding transaction gets exactly one outcome. **Only the first two
ever upload anything to Ramp.**

| Outcome | Meaning | Uploads? |
|---|---|---|
| `CONFIDENT` | Exactly one receipt matches exactly one transaction (merchant + amount + within the date window) | Yes |
| `BALANCED` | N receipts match N transactions with the same merchant/amount (e.g. four identical $214.56 charges) — sorted by date and zipped 1:1 | Yes |
| `AMBIGUOUS` | The receipt and transaction counts don't line up at a given merchant/amount (e.g. 3 transactions, 2 receipts) | No — listed for you to resolve by hand |
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
  `python3.12 skills/receipts/scripts/sources/anthropic.py --login` if the
  claude.ai session expired.
- **`SOURCE GMAIL: TRUNCATED (...)`** — the 50-page pagination cap was hit
  with more results still pending. This is not a skip — the source ran and
  returned partial results. Results are incomplete; narrow the date window
  (`--since`/`--until`) and re-run to get a query small enough to finish.
- **`CorruptLedger`** — the error message names the exact ledger file path.
  It's safe to delete it: every upload carries an idempotency key derived
  from the transaction + receipt provenance, so a fresh ledger just re-does
  the bookkeeping, it never double-uploads.
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
