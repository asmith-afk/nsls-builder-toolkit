---
name: scorecard-builder
description: >-
  Use when a manager wants to create, draft, build, revise, or significantly edit
  an employee performance ScoreCard — "create a scorecard", "build a scorecard for
  [name]", "draft [name]'s scorecard", "update/revise [name]'s scorecard", "fix one
  thing on the scorecard", "the scorecard is out of date", "this card is way off",
  "revise it instead of rewriting it", "reweight the accountabilities", "scorecard
  for my report", "make a scorecard doc", "help me set [name]'s accountabilities" —
  including for a brand-new hire with no history yet. Revises an existing card in
  place of rewriting it whenever one exists. Produces a founder-template Google Doc
  auto-shared with HR, never an Airtable row.
version: 2.2.0
---

# ScoreCard Builder

> **If `gws` fails (403 naming a project other than `nsls-gdocs-skill`, or exit 2):**
> run the doctor — it provisions/repairs the toolkit's own gws profile without touching
> any other tool's files, and computes the right scope union automatically:
> `python3 <plugin>/skills/gws/scripts/gws_doctor.py --services docs,drive`
> (Windows: use the real Python at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.)
> **The doctor heals its own profile, not your default gws setup** — so after
> `DOCTOR: HEALTHY`, run this skill's `gws` commands against that profile, chained in
> the SAME shell command (each agent Bash call is a fresh shell):
> `export GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws-profiles/nsls-gdocs-skill; gws …`
> (Windows: `$env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$env:USERPROFILE\.config\gws-profiles\nsls-gdocs-skill"; gws …`)
> Details: `../gws/references/multi-secret-profiles.md`.


Turn a manager's real knowledge of a report into a clean **founder-template ScoreCard Google Doc** — weighted outcome accountabilities (Side A), core competencies (Side B), and a binary Core Values gate — that aligns manager and employee on what the role is *for* and how "meets" is judged. **The Doc is the deliverable.**

Two disciplines make this skill work, and both are easy to skip:

1. **If a card already exists, revise it — don't rewrite it.** Regenerating from scratch throws away language a manager and report already agreed to. Triage how far off the card is, then make the *smallest* change that fixes it.
2. **Every card is auto-shared with HR (Jenna Fontanez) the moment it's rendered.** A card that lives only in the manager's Drive is an orphan — it won't be in the system of record for the next scorecard round. This skill shares it for them and tells them it did.

## SAFETY: THREE-TIER PERMISSION MODEL

This skill is deliberately **standalone and read-only against every shared system.** NSLS runs a live scorecard → scoring → bonus system (an HR-owned bot + a shared people-ops Airtable). This skill must never touch that machinery — it is not part of HR's process and is not the thing that loads scorecards into the system of record.

1. **Read-only (free to do):** read the founder SOP + research `references/`; read the **existing scorecard Doc** when one exists (never edit it in place); *optionally* read the data sources below (LOP/KPIs, Signal Quick Notes, the Knowledge Base) as drafting inputs — **only if the manager running this has access.** All optional; degrade gracefully when absent.
2. **New-content write (OK — explain what and where first):** build a `.docx` locally and upload it as a **new** Google Doc owned by the manager running the skill, then **share that new Doc with HR (`jfontanez@nsls.org`) as commenter.** The HR share is a required part of the flow, not an optional extra — see *The HR handoff* below. Commenter, never writer: Jenna needs to flag problems, not rewrite accountabilities the manager and report agreed to.
3. **NEVER — hard boundary, not negotiable:**
   - **No writes to any people-ops Airtable / ScoreCards / scoring system.** Loading the card is HR's job. This skill hands over a Doc.
   - **No editing or overwriting the prior card.** Read it, render a new version. History is the point.
   - **No Slack/DM to the employee.** HR gets the Doc automatically; the *report* is the manager's to share with, personally.
   - **No comp math, bonus numbers, or payout bands** anywhere in the output.
   - **No pay figures at all** — keep compensation out of the Doc entirely.

## Purpose

A good scorecard is hard because the manager knows the person but not the *frame* — they write tasks instead of outcomes, list ten things instead of the vital few, reward the number instead of the judgment, and quietly forget the work that just keeps the lights on. This skill carries the frame so any NSLS manager doesn't have to: the founder's Topgrading structure, the research on why outcome-goals beat task-lists, the 2×2 portfolio lens (growth / efficiency / hygiene / reliability), and the reality-check discipline that grounds accountabilities in what the person *actually does* without letting activity masquerade as an accountability. It produces a Doc a manager and report can sit down over, every draft value bracketed for the two of them to confirm.

## Two modes — and the question that picks between them

**Ask this before drafting a single line:**

> **Is there an existing scorecard for this person?**

If yes, **get it first** — paste its text, or give the Drive URL to read read-only. Do not draft anything until you've read it. A manager who says "update Maria's scorecard" is asking you to *change* a document, not to produce a second, competing one.

| Mode | Trigger | Input |
|---|---|---|
| **Create** | No card exists — new role *or* brand-new hire | Role + whatever data exists (or a manager interview if none) |
| **Revise** | A card exists and needs changing — for *any* size of change | The current card + **drift triage** (below) to size the intervention |

Both modes end the same way: a rendered Google Doc, **auto-shared with HR**, plus an explanation of what the manager still owes. Revise mode also emits a **change summary** so HR sees exactly what moved.

## Quick Start

1. **Existing card? → get it.** Then: whose card, what is the role's one-sentence reason to exist, who manages them.
2. **If revising, run drift triage** (below) — Tune / Revise / Rebuild. This decides how much you touch. Default to the smallest change.
3. **Gather inputs** — pull whatever of the data sources below exists (all optional). If it's a **brand-new hire with no history, run the manager interview** (below) instead.
4. **Draft the card** section by section (Mission → Side A → Core Values → Side B → Growth Focus → open questions), applying the guardrails. In revise mode, **carry surviving lines over verbatim.** Leave every uncertain value as a `[bracket]` for the alignment conversation.
5. **Render the Doc.** Copy `references/build_doc_template.py` → `~/build_<name>_scorecard.py`, fill the BODY, run with python-docx; it derives the filename and prints **both** commands — upload, then the required HR share. Title carries `(DRAFT)` while brackets are live. (Mechanics: `/gdoc-build`.)
6. **Share it with HR — required, not a reminder.** Run the printed STEP 2 share command (also in *The HR handoff* below). If it fails, **stop and tell the manager** — don't hand back a card you couldn't route.
7. **Explain the flow.** Tell the manager the share already happened, why it matters, and what's still on them: align with the report → resolve brackets → come back and say "this card is final."

## Data sources (all optional — use what exists, degrade gracefully)

The card gets stronger with grounding data, but the skill must work for a manager who has none. Pull what's available; never block on a missing source.

| Source | What it gives | How to read (read-only) | Status |
|---|---|---|---|
| **Company strategy / KPIs** | The bonus-grade outcome menu + targets to anchor Side A | LOP base `appAcnl4o8AQVZR1j` → `L1 Goals` + `KPIs` tables | Live |
| **Signal Quick Notes** | Reality-check: where the person's time *actually* went (spot missing accountabilities / low-value work to cut) | `/signal` · `/person-intelligence` (`signal_person_history`, `signal_person_goals`) | Live (if manager has access) |
| **Knowledge Base — KPI nodes** | Canonical **KPI definitions** + their **mapping to outcomes** — the shared vocabulary to phrase measures consistently across cards | `kb.nsls.org` `/mcp` (read-only search) | **Growing** — use a KPI node when it exists; skip cleanly otherwise |
| **Manager interview** | The fallback when nothing exists (new hire) | Structured questions (below) | Always available |

*This list is meant to grow.* As the KB accumulates KPI definitions + mappings, it becomes the preferred source for phrasing Side A measures — and, downstream, the mapping HR pushes into ScoreCards. Add new sources here as the same kind of **optional, read-only, degrade-gracefully** input — never a hard dependency.

## The manager interview (brand-new hire / no data)

When there is no strategy linkage, no Quick Notes, no history, **don't invent** — interview the manager:

1. **Why does this role exist?** → the one-sentence Mission.
2. **What are the 3–6 outcomes you'll hold them to?** Walk the 2×2 to prompt: *What growth number do they move? What operating system do they make better? What must not break on their watch (hygiene)? What existing thing must not rot (reliability)?* Capture outcomes, not tasks.
3. **How will each be measured?** Get a binary "meets" bar where the manager has one; **bracket it** where they don't — it's set with the report later.
4. **Weights** — force the vital few (3–6), ≥ 10% each, summing to 100%.
5. **Which 5–8 competencies** from the bank matter most for this seat? Set a MAR each.
6. **One growth focus** — the development bet for the period + a specific observable action.

## The founder-template structure

One double-sided page. Four blocks, in order:

| Block | What it is | Rating |
|---|---|---|
| **Mission** | One sentence: why this role exists. | — |
| **Side A — Accountabilities** | 3–6 durable **outcomes**, weighted (≥ 10%, sum = 100%), each with a binary **Pass/Fail "Meets" measure**. | A = clearly beat the bar · B = met it · C = missed |
| **Core Values** | The 5 NSLS values, each with a Minimum Acceptable Rating (MAR). | **Binary Pass / Flag gate** (see below) |
| **Side B — Competencies** | 5–8 behaviors from the Topgrading Competency Bank, each with a MAR. | 4 Excellent · 3 Very Good · 2 Good · 1 Weak |

Plus a **Growth Focus** and an **Open Questions** + **Alignment Notes** section. Full template + render mechanics: `references/founder-sop-framework.md`, `references/build_doc_template.py`.

## Side A — the 2×2 portfolio frame

Accountabilities are **outcomes**; for operating/coordination roles the top accountability is often "run the right portfolio." Sort candidate work with the 2×2 (full explanation + how to align a report on it: `references/portfolio-2x2-framework.md`):

|  | **Output** — value produced | **Machine** — system that produces it |
|---|---|---|
| **Advance** | **① Growth driver** — move a number up | **② Operating efficiency** — make the machine leaner |
| **Protect** | **③ Hygiene** — sudden external harm (legal, security, FERPA) | **④ Reliability** — gradual internal decay of what works |

Rows = offense (①②) vs. defense (③④). The two floors (③④) are **cleared, not ranked** against upside. **Bottlenecks** — work that halts other priorities if undone — jump the queue regardless of quadrant.

## Drafting guardrails (from the research — `references/research-grounding.md`)

- **Outcomes, not tasks.** "Ship the automation model" not "work on automation." Specific hard goals beat "do your best" (Locke & Latham). Rewrite every activity into the outcome it serves.
- **The vital few.** 3–6 accountabilities, not 10. Metric sprawl is the #1 scorecard failure mode.
- **Controllability check.** Flag accountabilities largely outside the person's control. For a coordinator role a broad outcome is defensible (tag `[contributor]`), but name the tradeoff.
- **Quality counterweight.** Pair any quantity metric with a countervailing quality one, or the number gets gamed (Goodhart, Kerr).
- **Learning goal for novel work.** For genuinely new/complex work, a capability accountability beats a hard number (which causes tunnel vision).
- **Reality-check, never reality-source.** Quick Notes tell you where time *went* — the manager decides what becomes an outcome. Signal is a **drift detector, NEVER a source of accountabilities.**
- **Bracket everything uncertain.** Dates, thresholds, names → `[brackets]`, set *with the report* in the alignment conversation.

## Core Values — binary gate, NOT a modifier

Score the 5 NSLS values as a **binary Pass / Flag gate** against each MAR. **Do not implement a ±15% modifier** — it was retired as unworkable (Kevin, 2026-07-11), matching HR's production scoring convention (values are binary). This is a decided divergence from the founder SOP, documented in `references/sop-reconciliation-memo.md`. No comp multiplier, ever.

## Side B — competencies from the bank

Select **5–8** from the Topgrading Competency Bank (the org's canonical behavioral taxonomy, HR-owned). Set a MAR per competency by role. Don't invent competencies; consume the bank. Menu + groupings + the caveat that the offline list is partial: `references/competency-bank.md`.

## Revise mode — drift triage

A card that's slightly wrong and a card that's fundamentally wrong need completely different treatment. Regenerating from scratch is the tempting default and it is usually the wrong one: it silently discards wording a manager and report negotiated, and it hands HR a card that looks entirely new when two numbers moved.

**1. Get the current card and reflect it back.** Read it read-only. Show the manager what's there now — mission, accountabilities + weights, competencies + MARs, growth focus — before proposing anything. Confirm you're looking at the current version; ask if there's a newer one.

**2. Score the drift** across five dimensions. Ask the manager which of these no longer holds:

| Dimension | The question |
|---|---|
| **Mission** | Is this still why the role exists? |
| **Accountability set** | Are these still the right 3–6 outcomes? Anything missing, anything obsolete? |
| **Weights** | Does the relative importance still match reality? |
| **Competencies + MARs** | Still the behaviors that matter for this seat, at the right bar? |
| **Growth focus** | Is this still the live development bet, or was it already achieved? |

**3. Pick the smallest intervention that fixes it.**

| Verdict | Test | What you do |
|---|---|---|
| **Tune** | Mission intact · ≤2 dimensions off · ≤2 accountability lines wrong | Patch **only** those lines. Everything else carries over **verbatim** — same words, same order. Re-validate weights = 100%. |
| **Revise** | Mission intact, but 3+ dimensions off, or roughly half of Side A is wrong | Rebuild Side A from the 2×2. Keep the mission and Side B **unless the manager specifically named them** as wrong. |
| **Rebuild** | Mission is wrong · the role itself changed · most of Side A is task-shaped or obsolete | The old card is a **reference, not a base.** Run the manager interview fresh — then produce a **"carried forward from prior card"** list so nothing durable gets silently dropped. |

**A rebuild has to be earned.** "The old card is messy" is not a reason to rebuild; it's a reason to tune the messy lines. If the manager describes one or two problems, you are in Tune — do not escalate on your own judgment. If you think the card needs more work than the manager asked for, *say so and let them decide* rather than quietly doing it.

**4. Preserve agreed language.** Any line that survived the last alignment conversation is a **contract between manager and report.** Do not re-word it for style, tighten it, or "improve" it while you're in the file. Change it only when it's the thing being changed.

**5. Render a NEW Doc** — never overwrite the old one; a new file preserves history. Keep the prior card's URL so the change summary can reference it.

**6. Emit a change summary** — a short "what changed vs. the prior card" list (e.g., *"Accountability #3 reweighted 15% → 20%; added Reliability line at 10%; dropped Vendor Management; mission unchanged"*) so HR can update the system of record precisely rather than re-key the whole card. **This summary goes into the HR share note** (below) — that's what makes the handoff a patch instead of a re-type. Name the triage verdict in it, too: HR reads *Tune* very differently from *Rebuild*.

## The HR handoff (the seam) — REQUIRED, and the skill does it

**The failure this prevents:** a manager builds a good card, has a good conversation with their report, and the Doc sits in their personal Drive forever. It never reaches the system of record, so at the next scorecard round the person has no card — or an old one — and the work is done again from scratch. An unshared scorecard is an **orphan**. This is the single most-skipped step in the whole process, which is why the skill does it rather than reminding someone to.

**Jenna Fontanez (`jfontanez@nsls.org`) owns the scorecard process.** She is the one who gets the card into the right place in the system of record. Every card goes to her.

### Share it — at render, before you hand back the URL

```bash
# set -o pipefail is REQUIRED, not decoration: without it the exit status is
# `tail`'s (always 0), so a 403/400 from gws reads as a successful share — the
# silent orphan this whole section exists to prevent.
set -o pipefail
# fileId = the Doc you just uploaded. Note the split:
#   role/type/emailAddress -> --json (request body)
#   sendNotificationEmail/emailMessage -> --params (query params)
gws drive permissions create \
  --params '{"fileId":"<DOC_ID>","sendNotificationEmail":true,"emailMessage":"<SHARE NOTE>"}' \
  --json '{"role":"commenter","type":"user","emailAddress":"jfontanez@nsls.org"}' \
  | grep -v -i keyring | tail -5
```

**Then confirm the share actually landed** — don't trust the exit code alone. `gws drive permissions list --params '{"fileId":"<DOC_ID>"}'` should show `jfontanez@nsls.org` as `commenter`. If it doesn't, treat it as a failed share and use the fallback below.

**The share note must say**, in plain language: whose card it is, who the manager is, whether it is **DRAFT or FINAL**, and — in revise mode — the **change summary** plus the triage verdict and the prior card's URL. A draft note explicitly says *brackets are still open, please don't load yet.* Without that, Jenna can't tell a finished card from an in-progress one (see Gap E in `references/handoff-mapping.md` — **HR loads only confirmed values**).

**Commenter, not writer.** Jenna needs to flag problems on the card, not change accountabilities the manager and report agreed to.

### Then explain the flow — every time, even though it's automatic

Managers must not be surprised that HR has their draft, and must not think the share was the last step. Tell them, in the hand-back:

1. **What just happened** — "I've shared this with Jenna Fontanez in HR as a commenter and she's been notified. She owns getting scorecards into the system of record."
2. **Why** — "A card that only lives in your Drive won't exist for the next scorecard round. This is the step that normally gets missed."
3. **What's still on you** — "It's marked DRAFT: share it with your report, work through the `[brackets]` together, then come back and tell me it's final. Jenna won't load it until then."

### On FINAL — the second half of the handoff

When the manager says the brackets are resolved:

```bash
set -o pipefail   # same trap: without it a failed retitle looks like success
# swap (DRAFT) -> (FINAL) so HR can see at a glance that it's loadable.
# Keep the rest of the title byte-identical to what the renderer produced.
gws drive files update --params '{"fileId":"<DOC_ID>"}' \
  --json '{"name":"ScoreCard — <Name> — <Role> — <FY> (FINAL)"}' \
  | grep -v -i keyring | tail -3
```

**Confirm the retitle before telling HR anything** — `gws drive files get --params '{"fileId":"<DOC_ID>","fields":"name"}'` must come back `(FINAL)`. Telling Jenna a card is ready to load while it still reads `(DRAFT)` is worse than not telling her: she has no way to know which signal to trust.

Then send Jenna a short "ready to load" note. **Show the manager the text and get their go-ahead before sending** — it goes out under their name. Jenna already has access, so this is a notification, not a new share.

### If the share fails — STOP, don't paper over it

A silent share failure recreates the exact orphan problem this section exists to solve. Never report a card as done when it isn't routed. Hand the manager the fallback verbatim:

> "I couldn't share this automatically — **please share it yourself before you close this out**: open `<URL>` → Share → `jfontanez@nsls.org` → **Commenter** → add a note saying it's a draft for `<report>`."

### The structural contract

The Doc's structure maps 1:1 to the fields HR loads. Keep the render structurally consistent (stable headings, fixed table columns) so the handoff is a parse, not a re-type. The section-to-field mapping lives in `references/handoff-mapping.md` — **confirm it with HR before treating any card as loadable.** This skill produces and routes the Doc; loading it is HR's separate, HR-only step.

## Diagnostic loop — rendering the Doc

**TRY** build → upload → open the Doc. **OBSERVE / DIAGNOSE / ADAPT:**

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError: cannot import name 'Document' from 'docx'` | Corrupt/partial python-docx in `/tmp/pptx_deps` | `python3.12 -m pip install --upgrade --force-reinstall python-docx --target /tmp/pptx_deps -q` |
| Tables render borderless | `table.style` unset | `table.style = 'Light Grid Accent 1'` |
| `**bold**` shows literally in a cell | cell text added as a raw string | use the template's `add_runs()` parser (handles `**bold**`, `*italic*`, `` `code` ``, `\n`) |
| `gws --upload` rejects the path | file outside cwd | build in `~`, run `gws` from `~` |
| `gws` JSON parse fails | keyring line on stdout | pipe through `grep -v -i keyring \| tail` |
| Brand font missing after upload | Google Docs strips custom fonts | Calibri body; brand = navy `#1A2B4A` colors |
| Share returns `403 insufficientFilePermissions` | Doc isn't owned by the account `gws` is authed as | Confirm the upload succeeded under the manager's own account; re-check `gws drive files get` |
| Share returns `400` / `sharingRateLimitExceeded` | Notification flags sent in `--json` instead of `--params`, or Workspace sharing policy | Flags are **query params**. If policy blocks it, use the manual fallback above — never skip |
| Share "succeeds" but Jenna gets no email | `sendNotificationEmail` omitted or in the body | Must be `true` in `--params`; verify with `gws drive permissions list` |
| Command exits 0 but nothing happened | `\| grep \| tail` swallows the failure — exit status is `tail`'s | `set -o pipefail` before any piped `gws` write, then verify by re-reading the resource |
| Doc already shared (revise mode, same file) | Permission exists | Expected — you should be rendering a **new** Doc, not re-sharing the old one. Check you didn't overwrite |

Full render mechanics: `/gdoc-build`.

## Service awareness

- **`/gdoc-build`** — the underlying Google-Doc renderer; this skill is a scorecard-shaped wrapper.
- **`/signal` · `/person-intelligence`** — read-only Quick Notes for the reality-check (optional).
- **LOP base** `appAcnl4o8AQVZR1j` — read-only strategy/KPI cascade.
- **Knowledge Base** (`kb.nsls.org` `/mcp`) — read-only KPI definitions/mappings, growing.
- **`gws drive permissions`** — how the card reaches HR. Write access limited to sharing the *new* Doc this skill created.
- **HR's scorecard system** (people-ops Airtable + scoring bot) — the live system of record. **This skill never touches it.** It routes the Doc to Jenna; loading it is a separate, HR-only step.

## Output guidelines

- **Deliverable = the Doc URL** + a one-line section list. Don't dump the whole card into chat.
- **It's a discussion instrument** — brackets are a feature; say so.
- **Revise mode also returns the change summary** + the triage verdict (Tune / Revise / Rebuild) + the prior card's URL.
- **State the HR share as done, not as homework:** "shared with Jenna Fontanez (HR) as commenter, she's been notified." Then name the remaining steps: share with the report → align → resolve brackets → tell me it's final.
- **Never sign off without the share confirmed.** If it failed, lead with that, not with the URL.
- **Keep pay out.**

## Rationalizations you will have

| Excuse | Reality |
|---|---|
| "I'll just write the Airtable record too, to save HR a step." | No. Doc only. Writing HR's system is the one thing this skill must never do. |
| "The Quick Notes clearly show this is her job — I'll make it an accountability." | Signal is a reality-*check*, not a source. The manager decides. |
| "The SOP says ±15% values modifier, so I'll add the math." | Binary Pass/Flag. No comp multiplier. |
| "Ten accountabilities is more thorough." | #1 failure mode. Vital few: 3–6. |
| "I'll fill in the Sep 30 dates so the card looks finished." | Brackets are the point. Dates get set *with the report*. |
| "It's a new hire and I have no data, so I'll draft generic accountabilities." | Run the manager interview. Generic ≠ grounded. |
| "This role is unusual — I'll invent a competency." | Consume the bank; flag gaps to HR. |
| "I'll paste the whole card into chat." | Return the URL. |
| "The existing card is messy — a clean rebuild is faster." | Faster for you, lossy for them. Those words were negotiated. Tune first; a rebuild has to be earned. |
| "They said 'update the scorecard,' so I'll draft a fresh one." | "Update" means change *this* document. Read it first, then triage. |
| "While I'm in here I'll tighten the wording on the other accountabilities." | Agreed language is a contract, not a draft. Change only what's being changed. |
| "The manager will send it to Jenna themselves." | That is precisely the step that gets skipped. Share it now. |
| "It's only a draft — no need to bother HR yet." | Draft-shared-and-labeled beats finished-and-orphaned. Mark it DRAFT and send it. |
| "The share errored but the Doc is fine, I'll just mention it at the end." | An unrouted card is an orphan. Lead with the failure and the manual fallback. |
| "I'll give Jenna writer access so she can just fix it." | Commenter. She flags; the manager and report own the content. |

## Red Flags — STOP

- About to call the Airtable API / write the people-ops base → **STOP.** Doc only.
- About to DM the employee → **STOP.** The manager shares it.
- About to put a bonus %, band, or salary in the Doc → **STOP.** No comp.
- About to promote a Signal Quick Note straight into an accountability → **STOP.** Reality-check, not source.
- About to implement ±15% values math → **STOP.** Binary gate.
- About to overwrite the prior Doc in revise mode → **STOP.** Render a new version.
- About to hand back 7+ accountabilities or task-shaped lines → **STOP.** Vital few (3–6), outcomes.
- About to draft a card without asking whether one already exists → **STOP.** Ask first.
- About to regenerate a whole card when the manager named only 1–2 problems → **STOP.** That's Tune. Patch those lines.
- About to re-word accountabilities that already survived an alignment conversation → **STOP.** That language is a contract.
- About to hand back the Doc URL without sharing it with `jfontanez@nsls.org` → **STOP.** The card is an orphan.
- About to report the card as done when the share errored → **STOP.** Lead with the failure + manual fallback.
- About to retitle `(DRAFT)` → `(FINAL)` while `[brackets]` are still live → **STOP.** HR loads only confirmed values.

## References

- `references/founder-sop-framework.md` — the founder's methodology and full template.
- `references/portfolio-2x2-framework.md` — the growth/efficiency/hygiene/reliability 2×2 + how to align a report.
- `references/research-grounding.md` — the evidence base (Locke & Latham, Kerr, Goodhart, controllability).
- `references/sop-reconciliation-memo.md` — where NSLS diverges from the SOP, incl. the decided binary-values gate.
- `references/competency-bank.md` — the Topgrading competency menu + groupings (partial offline list).
- `references/handoff-mapping.md` — Doc section → Airtable field mapping for the HR handoff (confirm with HR).
- `references/build_doc_template.py` — copy-and-fill python-docx renderer (derives filename, prints the upload command).
