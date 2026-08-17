---
name: bet-idea
description: >-
  Use when someone has a raw business idea for NSLS and it needs to become a
  full Lean Canvas + thesis, get its riskiest assumptions named out loud, get
  stress-tested, and — only if it earns it — get queued for research. The
  intake front door of the Strategy Studio pipeline; upstream of bet-research.
  Triggers: "I have a business idea", "new bet", "bet idea", "add a bet",
  "business model idea", "lean canvas this", "sketch a business", "should we
  sell X to Y", "capture this idea", "should we sell this thing we built",
  "we built this for ourselves — is it a product", "productize",
  "commercialize an internal tool", "finish my bet", "continue my bet idea",
  "resume a bet", "pick up where I left off on the bet", "capture Gary's
  idea", "drive a bet session for", "facilitated bet intake".
---

# bet-idea

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — `list_taxonomy`, `size_segment`, `get_bet` (resuming a
   partial capture). Free, no confirmation needed.
2. **Configuration / new-content** — `create_bet`, `update_section`,
   `upsert_assumption`, `score_rubric`. This bet belongs to nobody else yet;
   say out loud what's being written as you go (which field, what
   `evidence_tag`) but don't stop to confirm each individual call.
3. **Write to shared systems** — `upsert_taxonomy` (a new market/segment/
   buyer becomes visible to every other bet in the portfolio), `advance_stage`,
   `set_status`, `hand_off_bet` and `create_squad` (a hand-down assigns work to
   a real group or person, and a squad becomes visible portfolio-wide).
   **Confirm the exact values with the human before writing.**
   If no `STRATEGY_MCP_TOKEN` is available, print what WOULD be written and
   say so plainly — never fail silently, never fake a write.

Every write in every tier passes `via: "bet-idea"`.

## Purpose

Most business ideas at NSLS arrive as a sentence in a hallway or a Slack
message, and most of them die there — not because they're bad, but because
nobody ever forced them into a shape that could be argued with. `bet-idea` is
that forcing function: it drafts the full canvas and thesis in minutes so the
human is correcting instead of authoring, then spends the rest of the
conversation making the idea's weakest points visible — the assumption that
would collapse everything else if it's wrong, the box nobody can name a real
human for, the color that's red because the risk really is existential. It
ends with an honest, low-confidence score and an explicit ask: is this worth
one of our scarce research slots? Never assumed, always asked.

## When to use

- Someone has a business idea — a hallway pitch, a Slack message, a pasted
  doc — and it isn't a bet yet.
- **NOT** for an idea that's already a bet at Research stage or later (that's
  `bet-research` / `bet-plan` / `bet-review` / `bet-run` — route through
  `bet-studio` if unsure which).
- NOT for logging evidence against an existing bet, portfolio review, or
  experiment tracking — `bet-studio` hands those to their own places.

## Quick Start

Idea → **1** Sketch capture → **1.5** Board-worthiness gate (materiality —
below both bars, capture it and **hand it down** to a squad, then stop) →
**2** Taxonomy + growth vector + `create_bet` → **3**
Office-hours diagnostic → **4** Causal-chain interrogation → **5** Stress test
→ **6** Rubric → **7** The gate offer → a bet at Idea stage (or Research, if
earned) with a full canvas, an honestly-tagged assumption chain, and a
low-confidence score.

## Operating rules

- **Heartbeat every step.** Say what you're about to do, do it, then report
  what happened before moving on — "drafting all 9 canvas boxes now," "wrote
  `canvas.problem` tagged `assumption`," "taxonomy: no existing segment
  matches, proposing a new one." Never batch silently through steps 1–7.
- **AI-drafted content is never `data`.** Every section you draft — not the
  human — is written via `update_section` with `evidence_tag: "assumption"`
  (a reasoned guess) or `"opinion"` (a pure hunch). Only the human's own
  first-hand knowledge earns `data`, and only they can supply it. The one
  exception: internal-origin bets, where `data`/`estimate` on
  problem/solution content must cite the internal usage it's grounded in
  (Step 1) — still never for anything about the *external* market.
- **The human corrects; you don't author from nothing they said.** Draft from
  their one-liner/conversation/pasted material — extrapolate, don't invent
  facts that weren't implied.
- **The advance offer is explicit and never automatic.** `advance_stage`
  requires the human's own "yes" to the gate question in step 7. No amount of
  a high rubric score substitutes for asking.

## Red flags — STOP

- Tagging a drafted section `data` because it "sounds solid." → It's a guess
  until the human says otherwise. `assumption` or `opinion`, always.
- Accepting the first answer to a diagnostic question and moving on. →
  `references/diagnostic-questions.md` exists because the first answer is
  the polished one. Push once, then push again.
- Writing assumptions to `strategy_assumptions` without covering all three
  risk types. → `references/chain-interrogation.md`'s coverage check exists
  for a reason; flag any of customer/market/technical with zero assumptions.
- Calling `advance_stage` because the rubric score looked good. → The score
  is not the gate. The human's explicit yes to "worth a research slot?" is.
- Silently skipping the stress test's alternative-canvas offer or writing it
  to the engine without the human adopting it. → It's conversation-only
  scaffolding unless they say to keep it.
- Creating a new market/segment/buyer via `upsert_taxonomy` without saying so
  first. → Shared-system tier. Confirm, then write.

## Entry: resume vs. new

**Trigger:** the user names an existing bet, or bet-studio hands one over with
a `bet_id`. Call `get_bet` first — stage must be `idea` and status `active`;
anything else, send it back to bet-studio with one sentence why. **Skip
`create_bet` entirely.** Inventory what's incomplete (empty canvas/thesis
sections, missing assumptions, unscored rubric), announce the inventory
(heartbeat), then continue the normal workflow from the earliest incomplete
step, writing against the existing `bet_id`. Two steps leave no engine
trace and can't be inventoried: the office-hours diagnostic (step 3) and
the stress test (step 5). On resume, ALWAYS re-run the stress test (it's
fast, reads current content, and its fix-first list is the resume agenda),
and re-ask diagnostic questions only for boxes that are still weak. Ask the
origin question only if it can't be inferred from existing content.

**Starting a genuinely new bet:** before `create_bet`, check `list_bets` for a
same-name/one-liner match and surface it as a resume candidate first.

## Entry: facilitated intake

Also supported: a session where the IDEA OWNER (often an SLT member with no
Studio token) talks and a builder with Studio access drives. Confirm the
owner's email out loud before `create_bet` — `owner` is the idea owner's
email, never the driver's. Revisions still attribute the driver's token +
`via` automatically (correct — they typed it). Every attestation
(`worth_researching`, step 7) is the OWNER's spoken call in session; the
driver never attests on their behalf.

## Entry: autonomous mode (unattended agents only)

Triggered ONLY when the invoker explicitly states it is running unattended —
e.g. the weekly roadshow-intel clustering agent handing over an orphan-theme
cluster. A human present, however brief, gets the normal flow above. Read
`references/autonomous-mode.md` BEFORE any write. In brief: every drafted
section is tagged `assumption`, the materiality gate is cite-or-abort from
the cluster's own claims (no citable path → no bet, theme stays `brewing`),
the interactive checkpoints are skipped and recorded as skipped in the
first status update, and `advance_stage` / evidence attestation /
`upsert_taxonomy` are off-limits entirely.

## Step 1 — Sketch capture

**Purpose:** get the whole canvas + thesis on the page in minutes, not hours.

**Origin question, first.** Ask: *"Where does this bet come from — (a) a
market hypothesis (we think others will pay), or (b) an internal need (we
built/are building it for ourselves)?"*

- **Market-origin** — proceed exactly as the rest of this workflow is
  written.
- **Internal-origin (dogfood)** — problem/solution boxes may be tagged
  `data` or `estimate` *when grounded in our real internal usage* (name the
  internal system in the section content); log that usage as evidence —
  `log_evidence(bet_id, kind: "external"` or `"experiment_result", title:
  "<internal system> usage", evidence_tag: "data", via: "bet-idea")`, no
  `signal_strength` (internal use is not market demand). Step 4's chain then
  centers on the commercialization leap — "an institution outside NSLS has
  this problem" / "they'll pay rather than build or ignore it" get
  `priority` 1–2, `risk_type: customer`/`market` — and `thesis.right_to_win`
  should name NSLS as the first, live customer. **Guard: internal
  enthusiasm is `interest`, never demand — external evidence still climbs
  the commitment ladder.**

From whatever the person hands you — a one-liner, a rambling conversation, a
pasted doc — draft all **9 canvas boxes** (`canvas.problem`, `.segments`,
`.uvp`, `.solution`, `.channels`, `.revenue`, `.costs`, `.metrics`,
`.unfair_advantage`) and all **6 thesis fields** (`thesis.customer`,
`.problem`, `.offering`, `.why_now`, `.right_to_win`, `.ambition_2028`).
Nothing is written to the engine until step 2's `create_bet` returns a
`bet_id` — all 9+6 drafts live in conversation until then, and then become
the first `update_section(bet_id, field_key, content_md, evidence_tag)`
calls. Every box is `assumption` or `opinion` — never `data` — with ONE
exception: internal-origin problem/solution content grounded in cited
internal usage (see the origin fork above) may be `data` or `estimate`.

As you go, **note the order** in which the human actively engages with (adds
to, argues with, corrects) the first three boxes. Don't overthink this — it's
a light read of what they care about first — but keep it; the causal-chain
step below reuses it as the natural order to walk the chain of beliefs.

## Step 1.5 — Board-worthiness gate (materiality)

**Purpose:** keep the board for bets, and keep improvement work with the
LOPs/squads that own it — the test the SLT asked for (2026-07-23).

A bet earns board space when **being wrong is expensive** — the size of the
stakes, not the cost of finding out (finding out is deliberately cheap here).
With the step-1 sketch in hand, ask the owner both legs:

1. *"If this validates, does committing to it mean **≥ $500K of capital** —
   the build/scale/hire decision waiting at the end of the research?"*
2. *"Is there a **credible path to revenue material at NSLS scale** — rule of
   thumb, ≥ $1M/yr net-new or protected?"*

**Either yes → proceed to step 2.**

**Both no → hand it down. Do not stop with nothing on the record.** This is
real work that isn't bet-shaped, and the outcome for that is a **hand-down**,
not a shrug and not a kill. Say it in those words — *"that's a hand-down, not
a no"* — then:

1. `create_bet` with the name and one-liner from the step-1 sketch. **Skip
   the rest of this skill** — no canvas interrogation, no assumption chain, no
   rubric. Nobody should owe a lean canvas for a $120K idea.
2. Ask **who should own the work**: a standing squad (`list_squads` — offer
   `create_squad` with a charter if the right one doesn't exist yet) or one
   named person.
3. `hand_off_bet(bet_id, squad_id | individual_email, rationale)` where the
   rationale is the materiality answer in plain words — *"real but ~$120K/yr;
   nothing to prove through the gates."*
4. Tell the human two things: it's recorded and visible in the **Handed down**
   section of the portfolio (never the graveyard, never the kill rate), and
   **telling the squad is still their conversation to have** — the hand-down
   is a record, not a notification.

Why this replaces "write it up for that home and stop": an idea that ends the
conversation unrecorded evaporates, and so does the credit for raising it.
The one thing this gate must never produce is a good small idea that nobody
can find next quarter.

If the human is emphatic that it shouldn't be in the Studio at all, respect
that — but say what's being given up before you drop it.

Full definitions live in the Studio guide at
`market.nsls.org/strategy/guide` ("What belongs on the board").

## Step 2 — Taxonomy + growth vector

**Purpose:** place the bet in the taxonomy, classify which revenue vector it
grows, and create it.

Call `list_taxonomy` and help pick the market, segment, and buyer from what's
live (don't assume a fixed list — the taxonomy grows; it also now carries
jobs-to-be-done, which matter later in the pipeline, not at intake). B2B vs.
B2C follows directly from which buyer is picked — don't ask separately.

**Growth vector, asked in the owner's words:** *"Does this improve the
performance of the current business, or add a new revenue vector?"* Then pin
one of four values (they map onto the Ansoff matrix):

| `growth_vector` | Meaning |
|---|---|
| `core-performance` | Same product, same buyers — more yield from the current business |
| `segment-expansion` | New buyer/segment inside a current market |
| `market-expansion` | Current product into a new market |
| `new-product` | A net-new product line, wherever it lands |

Propose the value from the sketch; the owner confirms it. It renders as a
chip on the board and feeds the portfolio-mix line leadership reads — a
wrong vector misfiles the bet in every portfolio review.

If none of the seeded options genuinely fit, `upsert_taxonomy(kind, fields)`
creates a new one — **shared-system tier: confirm the fields first.** For a
new SEGMENT, validate BEFORE writing: run `size_segment(filter)` on the
proposed filter FIRST and show the computed size — only if the filter is
valid and the size sane does `upsert_taxonomy` create the segment (the
taxonomy is shared, leadership-visible reference data; never park an
invalid or unvetted filter in it). Don't take an unvalidated segment
forward.

`create_bet(name, one_liner, audience, market_id, segment_id, buyer_id,
motion, growth_vector)` happens here, once the taxonomy and vector are
settled — carry over the drafts from step 1 as the first `update_section`
calls against the new `bet_id`. (Resuming a bet that predates the vector
field? Ask the vector question and backfill it via
`update_bet(bet_id, growth_vector)`.)

## Step 3 — Office-hours diagnostic

**Purpose:** pressure-test the weakest boxes before they get load-bearing
assumptions built on top of them.

Read `references/diagnostic-questions.md` and run its forcing questions
against whichever canvas boxes are thinnest — usually segments, problem, or
UVP. Name the actual human the bet serves (not "colleges," a person with a
title). Get the status-quo workaround and what it costs today. Find the
smallest thing someone would pay for **this week**. Push past the first
polished answer — that's the whole point of the reference's anti-sycophancy
rule. Update the relevant sections with the sharpened content once the human
lands on something truer than the first draft.

## Step 4 — Causal-chain interrogation

**Purpose:** name every load-bearing belief and rank which one breaks the
model first if it's wrong.

Read `references/chain-interrogation.md` and walk the chain of beliefs in the
fill order recorded in step 1. For each load-bearing assumption, call
`upsert_assumption(bet_id, statement, source_field_key, belief_type,
risk_type, chain_position, priority)`:
- `belief_type`: `leap_of_faith` | `anecdote` | `fact`
- `risk_type`: `customer` | `market` | `technical`
- `priority`: 1 = riskiest. Ask the domino question — *"if this is wrong,
  what else collapses?"* — to propose the ranking; **the owner confirms it**,
  never you alone.

Check coverage before moving on: if any of customer/market/technical has zero
assumptions recorded, say so and go find one — an uncovered risk type is a
blind spot, not a clean bill of health.

## Step 5 — Stress test

**Purpose:** rate the bet across its 7 dimensions and produce a sequenced
fix-first list — not a scoreboard.

Read `references/stress-test-rubric.md`. Score **Clarity, Desirability,
Viability, Feasibility, Defensibility, Mission, Timing** red/yellow/green,
each with a one-line why. Then sequence, don't just list: reds first, and
among reds the one whose failure would invalidate the most of the rest of the
model — existential risk before nice-to-have risk. This is a prioritized
what-to-fix-first list, not a percentage or an average.

Optionally, draft **one** alternative canvas (a different segment, or a
different value proposition) as a comparison point — present it in
conversation only. Do not write it to the engine unless the human explicitly
adopts it as the new direction.

## Step 6 — Rubric

**Purpose:** produce the bet's first, honestly low-confidence, stack-rank
input.

Call `score_rubric(bet_id, scores)` for all 5 criteria — `market_size`,
`right_to_win`, `time_to_revenue`, `build_to_value_risk`,
`evidence_strength` (all 1–5, higher is always better) — every one at
`confidence: "low"`, each with a short note explaining the score. Show the
resulting rank position: this is deliberately the weakest data point the bet
will ever have, and it should look like it.

## Step 7 — The gate offer

**Purpose:** ask, explicitly, whether the idea has earned a scarce research
slot — and never move it without a real yes.

Ask in these or close to these words: **"Worth one of our research slots?"**

- **Yes** → `advance_stage(bet_id, to_stage: "research", rationale,
  attest: { worth_researching: true })`. Show the returned
  `{ moved, gate: { checks } }` regardless of outcome.
- **No** → leave the bet at Idea. If the human wants it explicitly shelved
  rather than just left idle, confirm the rationale and call
  `set_status(bet_id, status: "parked", rationale)`.

**Never call `advance_stage` without this explicit yes** — the attestation
*is* the point of the gate, not a formality around it.

## The pipeline (where this sits)

```
idea ──bet-idea──▶ Idea-stage bet: full canvas + thesis (assumption/opinion
                    tagged), ranked assumption chain, stress-test sequence,
                    low-confidence rubric score
                  ──▶ human says yes ──▶ Research stage (attest.worth_researching)
                  ──▶ human says no  ──▶ stays Idea, or parked with rationale
       owner picks up research ──▶ bet-research (works the chain riskiest-first
                                    toward the planned gate)
```

- Upstream of: `bet-research` (research stage — hand the bet over after the gate).
- Called by: `bet-studio`'s "add an idea" hand-off (carries over any concept
  already stated).
- Writes to: the `strategy-studio` MCP server (Strategy Studio engine behind
  `market.nsls.org`).

## Reference index

- `references/diagnostic-questions.md` — the office-hours forcing questions
  and the anti-sycophancy rule that keeps this step honest.
- `references/chain-interrogation.md` — Maurya's belief-chain procedure,
  operationalized against `upsert_assumption`.
- `references/stress-test-rubric.md` — our 7-dimension rubric, anchored to
  the engine's evidence tags and experiment kinds.
- `references/autonomous-mode.md` — the headless entry contract for
  unattended agents (weekly roadshow clustering): cite-or-abort
  materiality, skipped-and-recorded checkpoints, hard limits.
- `references/leanspark-stress-test-notes.md`,
  `references/customer-interview-playbook-notes.md` — the Phase 1 source
  notes these three references are built from.

## No token / server missing

If `strategy-studio` MCP calls fail or the tools aren't visible, don't guess
at what would have been written and don't fail silently — print the exact
values each call would have carried (field keys, evidence tags, assumption
statements, scores) so the human can enter them by hand, and point at
`/connect` or the README's Strategy Studio setup section
(`STRATEGY_MCP_TOKEN`, minted by Kevin, SLT authors only).

## Rationalization table

| Excuse | Reality |
|---|---|
| "This draft is basically certain, I'll tag it `data`." | You drafted it, the human didn't confirm it yet. `assumption` or `opinion` until they do. |
| "They already answered the diagnostic question, moving on." | The first answer is the polished one. Push once, then push again — that's the reference's whole design. |
| "I'll rank the assumption priorities myself, it's obvious which is riskiest." | Domino logic proposes the order. The owner confirms it — it's their bet. |
| "The rubric scored well, let's advance it." | The score isn't the gate. Ask the explicit gate question in step 7 regardless of score. |
| "The alternative canvas is good, I'll just write it in too." | Conversation-only unless the human adopts it. Writing it unasked pollutes the real bet's history. |
| "It's just a new segment, I'll create it and move on." | Shared-system tier — every other bet sees this taxonomy. Confirm first. |
| "No token, I'll skip the write and keep going quietly." | Print what would have been written. Silent skips lose the human's own idea. |
| "This is obviously a bet, skipping the materiality gate." | The gate exists because the SLT asked what qualifies. Ask both legs out loud — a great idea below both bars is squad work, and saying so is the skill working. |
| "Below both bars — I'll tell them it isn't a bet and we're done." | Half the job. Capture it and `hand_off_bet` to a squad or a person, with the reason on the record. An unrecorded idea evaporates, and so does the credit for raising it. |
| "It's too small, I'll park it / kill it to keep the board clean." | Neither. Park and kill are verdicts on the idea; this idea is fine and just isn't bet-shaped. A hand-down keeps it out of the graveyard AND out of the kill rate. |
| "I'll run the full canvas first, then hand it down." | Backwards. Once both materiality legs are no, skip to the hand-down — nobody owes a lean canvas for a $120K idea. |
| "The vector is obvious from the sketch, I'll just set it." | Propose it, but the owner confirms — the vector files the bet in every portfolio review. |
| "Running unattended, and the cluster is clearly material — I'll estimate the $ path." | Cite-or-abort. No citable path in the claims → no bet, theme stays `brewing`. A junk bet costs more than an abort. |
