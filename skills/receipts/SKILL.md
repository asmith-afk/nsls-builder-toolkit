---
name: receipts
description: Find Ramp transactions missing receipts, fetch each receipt from Anthropic's billing API, Neon's billing API, or Gmail, and upload it to Ramp against the exact transaction. Use when the user says "receipts", "/receipts", "missing receipts", "Ramp needs a receipt", "receipt cleanup", or forwards a Ramp "transaction needs a receipt" nag. Dry run by default.
---

# Receipts → Ramp

> **If `gws` fails (403 naming a project other than `nsls-gdocs-skill`, or exit 2):**
> run the doctor — it provisions/repairs the toolkit's own gws profile without touching
> any other tool's files, and computes the right scope union automatically:
> `python3 <plugin>/skills/gws/scripts/gws_doctor.py --services docs,drive,gmail`
> (Windows: use the real Python at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.)
> **The doctor heals its own profile, not your default gws setup** — so after
> `DOCTOR: HEALTHY`, run this skill's `gws` commands against that profile, chained in
> the SAME shell command (each agent Bash call is a fresh shell):
> `export GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws-profiles/nsls-gdocs-skill; gws …`
> (Windows: `$env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$env:USERPROFILE\.config\gws-profiles\nsls-gdocs-skill"; gws …`)
> Details: `../gws/references/multi-secret-profiles.md`.


Clears Ramp's missing-receipt queue automatically instead of the manual
"find the email, download the PDF, open Ramp, attach it" ritual.

## What it does

1. Pulls every Ramp transaction in the date window and checks each one for
   a missing receipt (this is a per-transaction API call — see
   [Troubleshooting](#troubleshooting) for why).
2. Fetches candidate receipts from every configured source (Anthropic
   billing, Neon billing, Gmail) — each source degrades independently, see
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
- `/receipts --set-session` — store the claude.ai session cookie the
  Anthropic billing source needs, then exit; does not build the queue, fetch,
  or upload anything. Not combinable with `--send`. (`--login` is the old
  name for this and still works — it now stores a cookie instead of opening a
  browser, and says so.)
- `/receipts --set-neon-key` — store the Neon API key the Neon billing source
  needs, then exit; does not build the queue, fetch, or upload anything. Not
  combinable with `--send`, and not combinable with `--set-session` (they are
  two different credentials for two different sources — run one, then the
  other).

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

Four independent prerequisites. **None of them are required for the others
to work** — a missing prerequisite skips only that piece and says so in the
report; it never fails the whole run.

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
others as your inbox has them — including vendors whose receipts are sent
**by Stripe on their behalf** (Macroscope, SendBird, Clay Labs, and similar),
where the vendor's name is in the sender's display name rather than its
domain. See [Coverage](#stripe-relayed-vendors--a-ceiling-that-turned-out-to-be-a-bug).
If `gws` isn't authenticated, the Gmail source is skipped and announced in
the report; every other source still runs.

### 3. Anthropic source (optional)

**No browser, and nothing to install.** This source is plain HTTP against
claude.ai's billing API using the standard library — there is no Playwright
prerequisite, no Chromium download, and no `pip install` step for this skill
at all. Two things are required:

```bash
export ANTHROPIC_ORG_UUID=<your-claude.ai-org-uuid>   # Settings > Organization
python3.12 skills/receipts/scripts/run.py --set-session
```

Run this from the root of your `nsls-builder-toolkit` checkout, same as
[Execution](#execution) — the relative path only resolves there. This is the
one place that relative form is handed to you directly, before any run has
happened yet to print something better: every session-recovery message
`/receipts` prints after this first run (expired session, unsafe file mode,
Cloudflare challenge, etc. — see [Troubleshooting](#troubleshooting)) quotes
the exact command as an **absolute path** instead, resolved at runtime from
where this skill is actually installed, so it works from whatever directory
you're in when you see it.

`--set-session` asks for your claude.ai session cookie. To find it:

1. Open https://claude.ai in Chrome, signed in to the right account.
2. Open DevTools (**⌥⌘I** on macOS, F12 elsewhere).
3. **Application** tab → **Storage** → **Cookies** → `https://claude.ai`
4. Find the row named **`sessionKey`** and copy its **Value** (it's long).
5. Paste it at the prompt.

The paste is hidden — it isn't echoed to the terminal and never enters your
shell history. The value is validated against claude.ai *before* it is stored,
so you find out immediately whether it works instead of on some later run.

**Treat that cookie like a password.** Anyone holding it can act as you on
claude.ai. It is written to `~/.claude-receipts-session` with mode `0600`
(only your account can read it), outside this repository so it cannot be
committed. Don't paste it into Slack, a ticket, or a commit. If the file's
permissions are ever loosened so that other accounts can read it, this skill
**refuses to use it** and tells you to fix or re-store it. `CLAUDE_SESSION_KEY`
in the environment takes precedence over the file if you'd rather supply it
that way (from a password manager, say).

**Sessions expire periodically.** That is normal, not a breakage. When it
happens the report says so in plain words — `the stored claude.ai session has
expired` — and the fix is to re-run `--set-session` with a freshly copied
cookie.

This source is how usage-credit auto-recharge charges get a receipt at
all — Anthropic does **not** email those (see the coverage note below). If
`ANTHROPIC_ORG_UUID` isn't set or no session is stored, this source is
skipped and announced; the rest of the run proceeds normally.

### 4. Neon source (optional)

**No browser, nothing to install, and no cookie.** Neon's billing API takes
a plain long-lived API key, so unlike the Anthropic source there is no
session here to expire. Two things are required:

```bash
export NEON_ORG_ID=org-your-organization-id
python3.12 skills/receipts/scripts/run.py --set-neon-key
```

`NEON_ORG_ID` is the `org-…` segment in the Neon Console URL
(`console.neon.tech/app/projects?org_id=org-…`). Run the second command from
the root of your checkout, same as [Execution](#execution) — every
Neon-recovery message `/receipts` prints later quotes the command as an
**absolute path** resolved at runtime, so it works from wherever you are.

`--set-neon-key` asks for a Neon API key. To create one:

1. Open the **Neon Console** (https://console.neon.tech) and sign in.
2. **Organization settings** → **API keys**.
3. Create an **organization** API key. A personal key cannot read the
   organization's billing invoices — this is the single most likely setup
   mistake, and it shows up as an HTTP 401/403 in the report.
4. Copy it (Neon shows it once) and paste it at the prompt.

The paste is hidden — it isn't echoed to the terminal and never enters your
shell history. The key is validated against Neon *before* it is stored, so
you find out immediately whether it works instead of on some later run.

**Treat that key like a password.** It is written to
`~/.claude-receipts-neon-key` with mode `0600` (only your account can read
it), outside this repository so it cannot be committed. If the file's
permissions are ever loosened, this skill **refuses to use it** and tells you
to fix or re-store it. `NEON_API_KEY` in the environment takes precedence over
the file if you'd rather supply it that way (from a password manager, say).

This source is the only way Neon charges get a receipt: Neon sends **no
invoice email at all** — the mailbox was searched unrestricted on 2026-08-01
and Neon sends product updates and usage recaps only. If `NEON_ORG_ID` isn't
set or no key is stored, this source is skipped and announced; the rest of
the run proceeds normally.

## What happens to your credentials

Two of these sources need a long-lived secret of yours (a claude.ai session, a
Neon API key). Three guarantees, all of them checkable in `skills/receipts/`:

- **They stay in your `$HOME`.** Each is read from an environment variable if
  you set one, otherwise from a file in your home directory at mode `0600` —
  never inside this repository, so neither can be committed. A file any other
  account can read is refused, not used.
- **They never reach a report, log, or the ledger.** No error message, report
  line, or ledger entry ever contains a credential; the value is stripped from
  any text that came from elsewhere (an OS error, an HTTP error body) before
  you see it.
- **They are never forwarded to a third-party host.** Python's `urllib`
  re-sends `Authorization` and `Cookie` headers when it follows a redirect to
  another origin ([CPython #77842](https://github.com/python/cpython/issues/77842)),
  so one redirect off `console.neon.tech` or `claude.ai` would hand your
  credential to whatever host the `Location` header names. Neon refuses
  redirects on the authenticated request outright. claude.ai has to follow
  same-origin redirects — its 302 to `/login` is how an expired session is
  detected — so it follows them with the cookie intact and strips the cookie on
  any hop to a different scheme, host, or port.

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
- **3** are Neon Tech charges ($1,293.73 total, billed monthly and growing:
  $317.61 → $425.36 → $550.76). Neon sends no receipt email either, but it
  *does* expose a billing API, so these are covered by the Neon source.
- **1** (Asana) binds through the Gmail source.
- **~3** (Supabase, Zoom, and similar) have **neither an email nor a
  reachable billing API** — nothing this skill can fetch automatically. These
  need manual handling: download from the vendor's own billing portal and
  attach in Ramp directly.

"Sends no receipt email" and "has no automated source" are two different
statements, and only the second one is a ceiling. Neon is the worked example:
no email, but a portal API that takes a plain API key, so it's automated.
Supabase and Zoom are the honest remainder — not a bug to chase, because
there's no source to build against. Don't expect the skill to close 22/22;
expect it to close what has a source, and leave a short, correctly-labeled
manual list for the rest.

### Stripe-relayed vendors — a ceiling that turned out to be a bug

That snapshot understated the Gmail source, and the gap is worth naming
because it looked exactly like a ceiling. Vendors that don't send their own
receipts — Stripe sends on their behalf — arrive as
`Macroscope <invoice+statements+acct_…@stripe.com>`: the vendor is the
**display name**, the domain is the relay's. Merchant resolution read the
domain, got `stripe` for every one of them, matched no Ramp transaction, and
the receipt was discarded without a word. Four vendors were affected, one of
them the highest-volume vendor in the account by a wide margin.

Fixed 2026-08-01: when the sending domain is a known **billing relay**
(`BILLING_RELAY_DOMAINS` in `sources/gmail.py`, currently just `stripe.com`),
the display name is the authoritative half of the header and is used instead.
Direct senders are unchanged — domain first, then the alias map — so Anthropic,
Zoom, and Asana resolve exactly as before. Adding the next relay (Paddle,
Chargebee, …) is a one-line change to that set.

These vendors were on the manual list and no longer need to be. Read the
22-transaction snapshot above as the measurement it was, not as a permanent
floor: "no receipt found" is sometimes a source bug wearing a ceiling's
clothes, and the way to tell them apart is to check what the source actually
did with the mail rather than trusting that it found nothing.

One residual case stays manual by design. A relayed message with **no display
name** names its vendor nowhere in the header, so there is nothing
authoritative to resolve and nothing is guessed — it resolves to a key that
can only equal itself, never binds, and is **counted and reported** as a
`SOURCE GMAIL: NOTE (…)` line so the miss is visible rather than silent.

## Troubleshooting

**The commands below are shown in their short, relative form for
readability.** The actual message `/receipts` prints for any of these
quotes the real, absolute path to `run.py` on your machine — resolved at
runtime, not this doc's relative shorthand — so copying it works from
whatever directory you're in, not just the repository root.

- **`RampAuthError`** — Ramp auth is dead. Run `ramp auth login`.
- **`SOURCE ANTHROPIC: SKIPPED (No claude.ai session is stored …)`** — nothing
  has been stored yet and `CLAUDE_SESSION_KEY` isn't set either. Run
  `python3.12 skills/receipts/scripts/run.py --set-session`.
- **`SOURCE ANTHROPIC: SKIPPED (The stored claude.ai session has expired …)`**
  — normal and expected; cookies don't last forever. Copy a fresh `sessionKey`
  value out of Chrome's DevTools and re-run
  `python3.12 skills/receipts/scripts/run.py --set-session`.
- **`SOURCE ANTHROPIC: SKIPPED (Refusing to use the stored claude.ai session …
  its mode is …)`** — the credential file became readable by other accounts on
  the machine. The skill will not read a secret in that state. `chmod 600
  ~/.claude-receipts-session`, or just re-run `--set-session`, which always
  writes it back at `0600`.
- **`SOURCE ANTHROPIC: SKIPPED (… HTTP 403 … not an org admin …)`** — a
  different failure that looks similar and is not fixable the same way. The
  claude.ai session is fine; the account just can't read that organization's
  billing invoices. Storing a new session cannot change it. Ask an org owner
  for admin access, or unset `ANTHROPIC_ORG_UUID` to run without this source.
  A 401 or a redirect to the logout page is the session-expiry case above and
  *does* want `--set-session`.
- **`SOURCE ANTHROPIC: SKIPPED (Cloudflare challenged the request …)`** — a
  third, distinct failure, and neither of the two above. Cloudflare answered
  instead of claude.ai, so the request never arrived: this is not your
  permissions and not (necessarily) a dead cookie. A freshly copied
  `sessionKey` usually clears it — re-run
  `python3.12 skills/receipts/scripts/run.py --set-session`. There is no
  browser in this path any more, so there is nothing to install and no
  "verify you are human" box to tick.
- **`SOURCE NEON: SKIPPED (No Neon API key is stored …)`** — nothing has been
  stored yet and `NEON_API_KEY` isn't set either. Run
  `python3.12 skills/receipts/scripts/run.py --set-neon-key`.
- **`SOURCE NEON: SKIPPED (NEON_ORG_ID is not set …)`** — a different, cheaper
  fix: the key may be perfectly fine, the source just doesn't know which
  organization to read. `export NEON_ORG_ID=org-…`, taken from the `org_id`
  segment of the Neon Console URL.
- **`SOURCE NEON: SKIPPED (Neon refused … HTTP 401/403 …)`** — the stored key
  is invalid or is a **personal** key. Organization billing invoices need an
  **organization** API key (Neon Console → Organization settings → API keys).
  Re-issue it as one and store the new key with `--set-neon-key`. Setting
  `NEON_ORG_ID` will not fix this.
- **`SOURCE NEON: SKIPPED (Neon answered HTTP 400 'method is deprecated' …)`**
  — **not your credentials.** This means the skill called the retired
  `/api/v2/billing/invoices?org_id=…` form instead of the org-scoped
  `/api/v2/organizations/<org>/billing/invoices`. It is a bug in
  `sources/neon.py` and needs a code change; re-issuing an API key will do
  nothing.
- **`SOURCE NEON: SKIPPED (Refusing to use the stored Neon API key … its mode
  is …)`** — the credential file became readable by other accounts. `chmod 600
  ~/.claude-receipts-neon-key`, or re-run `--set-neon-key`, which always
  writes it back at `0600`.
- **`SOURCE NEON: SKIPPED (console.neon.tech … tried to redirect … was NOT
  followed)`** — also **not your credentials**, and nothing was leaked. The
  authenticated Neon request does not follow redirects, because `urllib`
  forwards the `Authorization` header to the new host when it does — one
  redirect would hand your long-lived API key to whatever that host is. This
  endpoint has never redirected, so seeing this means something changed: the
  message names the target. If Neon really did move the endpoint,
  `sources/neon.py` needs the new URL.
- **`ERROR: Refusing to prompt for the … no controlling terminal`** (from
  `--set-neon-key` or `--set-session`) — you're running in something with no
  terminal at all: a CI job, an agent shell, `docker exec` without `-t`.
  Python's hidden-input prompt silently falls back to reading with **echo on**
  in that state, which would print your credential to the screen and into that
  job's log, so these commands refuse instead. Nothing was read and nothing
  was stored; any previously stored value is untouched.

  Note what this is *not*: a redirected stdin is fine. `--set-neon-key
  < /dev/null` run from a real terminal still gets a properly hidden prompt,
  because Python opens `/dev/tty` for it — only the absence of a terminal
  triggers this refusal.

  Either re-run from a terminal, or supply the value through the environment
  (`NEON_API_KEY` / `CLAUDE_SESSION_KEY`), which both sources check ahead of
  the stored file. Set it **without putting it in the command**, so it doesn't
  land in your shell history (works in zsh and bash):

  ```bash
  printf 'Neon API key: '; read -rs NEON_API_KEY; echo; export NEON_API_KEY
  ``

  Exporting it with the value written inline in the command would work too,
  and would also write the credential verbatim into `~/.zsh_history` and any
  shell audit log — a longer-lived leak than the echoed prompt this refusal
  exists to prevent. Use the form above. (Non-secrets like `NEON_ORG_ID` and
  `ANTHROPIC_ORG_UUID` are fine to `export` inline — there's nothing to leak.)
- **`SOURCE <NAME>: TRUNCATED (...)`** — the source ran and returned
  **partial** results. This is not a skip and not a failure; it is an
  incomplete search, and any `UNFOUND` below it may be an artifact of what
  wasn't searched. All three sources report it the same way:
  - Gmail — the 50-page pagination cap was hit with more results pending.
  - Anthropic — the 20-page cap was hit, or the invoice listing claimed more
    pages while returning no cursor, or one or more invoice PDFs failed to
    download (those are named, with date and amount, in the message).
  - Neon — an invoice PDF failed to download, a paid invoice couldn't be read
    from the listing, a paid invoice was **not in USD**, the listing came back
    without a usable `invoices` array, or the response grew a
    pagination-shaped field. Neon's listing is **not** paginated today (all
    invoices come back in one call), so that last one means the API changed
    shape and `sources/neon.py` needs updating — the skill notices rather than
    returning a quietly short list.

    Two of those want a word. A **non-USD** invoice is excluded on purpose:
    matching compares amounts as plain cents and never looks at currency, so a
    paid €550.76 invoice would happily attach itself to an unrelated $550.76
    Ramp charge. Attach those manually. And **no usable `invoices` array**
    means nothing was searched at all — every `UNFOUND` under it is
    meaningless, not evidence that a receipt is missing.

  Narrow the date window (`--since`/`--until`) and re-run to get a query small
  enough to finish. Download failures are usually transient — re-running is
  often enough.
- **`SOURCE <NAME>: NOTE (...)`** — the source ran **completely** (not a skip,
  not a truncation) and still found something you have to handle by hand.
  Today there is one: Gmail found a receipt sent by a billing relay
  (`stripe.com`) whose `From` header carried **no vendor display name**. The
  vendor is named nowhere in that message, so the skill refuses to guess one —
  guessing would risk attaching a receipt to the wrong merchant's charge —
  and the receipt is counted and reported here instead of vanishing. Find it
  in Gmail (search `from:stripe.com` over the same window), open the PDF to
  see which vendor it's for, and attach it in Ramp directly. If a whole vendor
  keeps landing here, that vendor is sending without a display name and
  nothing in `sources/gmail.py` can fix it.
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
- **A `~/.claude-receipts-profile/` directory exists.** Left over from an
  older version of this skill, which drove a real Chrome through Playwright to
  collect the Anthropic invoices. That path is gone — nothing in this skill
  reads or writes it any more — and the directory is a dead Chrome profile
  taking up roughly 40 MB. **It is safe to delete** (`rm -rf
  ~/.claude-receipts-profile`). It holds no credential this skill uses: the
  ones it does use are `~/.claude-receipts-session` and
  `~/.claude-receipts-neon-key`, which you should *not* delete unless you
  intend to re-store them.
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
