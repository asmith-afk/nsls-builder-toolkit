---
name: track-optimize
description: >-
  Use when a live Society (ignite-next) track needs improvement — members are
  dropping off, a step underperforms, or a track is flagged for optimization.
  Finds where members leave (real PostHog data), diagnoses why (focus-group),
  proposes a concrete change, and produces a new version that re-enters the
  score→gate loop. Triggers: "optimize a track", "improve a live track", "why
  are members dropping off", "fix the weak step", "this track underperforms",
  "optimize <track>", "track is losing people at step".
---

# track-optimize

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — reading the live track's PostHog performance (Studio
   `PostHogActuals` + `/posthog`), its `track.json`, and its scores. Free.
2. **Configuration / new-content** — authoring a proposed new version
   (`track.json` edit) + previewing it in the demo. OK by default; say what changed.
3. **Ship** — a new version goes Live only through `track-prototype`'s score→gate
   and a human decision. **Never auto-ship an optimization.** The gate stays.

## Purpose

A live track is a hypothesis with real data attached. This skill closes the loop:
it reads where members actually leave, diagnoses why that step underperforms,
proposes a specific fix, and routes the fix back through the same quality gate a
new track passes — so optimization is evidence-driven, not opinion, and nothing
ships to members without clearing the bar. Signal says *where*; the focus-group
says *why*; the gate says *good enough*.

## When to use

- A track in the Studio's **Optimization** column, or any Live track a builder
  wants to improve.
- NOT for building a new track (that's `track-design`) or first-time scoring
  (that's `track-prototype`). This is the *live → better version* loop.

## Inputs

- The live track's **`track.json`** (the current shipped content).
- Its **live performance** — from the Studio `PostHogActuals` (base
  `appzDWu6GowvnACtv`), and `/posthog` for deeper funnels. See
  `references/reading-the-signal.md`.

## Process

### 0 — Flag it: move the card to Optimization
If the track is still in the **Live** column, flag the optimization work on the
board before digging in (heartbeat: report the transition). Prefer the Studio
MCP tool `set_stage`; script fallback:
```
AIRTABLE_API_KEY=… AIRTABLE_BASE_ID=appzDWu6GowvnACtv \
  node <track-prototype>/scripts/set-stage.mjs <slug> optimization
```

### 1 — Signal: find where members leave — and who (PostHog)
Prefer the Studio MCP tool `get_telemetry` (`society-studio` server) — latest +
previous measurement, week-over-week deltas, and the board's flag in one call.
Fallback: read the track's `PostHogActuals`: **`step_to_step_continuation`** (the primary
live metric — average share continuing step→step), **`dropoff_by_step`** (the
per-step counts), and `step1_dropoff`. **Pick the row for the *current* live
version** — a track may have several rows across versions; use the one whose
`live_track_version` matches the shipped build (else the latest `period`), so
you're optimizing what's actually live. Identify the **weakest step** — the
largest single continuation drop. Then apply the **segment lens**
(`references/segment-lens.md`): slice the weak step by Seeker / Explorer /
Doubter / Accelerator to find WHO is leaving — the target segment is the one
whose continuation falls furthest below its peers (report n; small segment
slices are directional, not significant). For depth or a fresh cut, use
`/posthog` on the track's events. Report the weak step and target segment with
their numbers (real, sourced — never a guessed figure). Caveat: Welcome's
per-segment numbers are survivorship — see the guardrail in the reference.

### 2 — Diagnose: why that step underperforms (focus-group)
Run `track-prototype`'s synthetic focus-group panel **on the current live
content**, focused on the weak step — with the panel overlaid as the target
segment (each persona keeps its register, adds the segment's ratings + 
job-to-be-done; see "Running the focus-group as a segment" in
`references/segment-lens.md`). If the track has prerequisites, pass their
assumed tokens (the track's `--assume` / `--prereq` set, as in `track-design`
Phase 0 / the demo build) so the walk doesn't error on token ordering. Read the
panel's friction notes against the four dimensions (Value / Pacing / Copy / Fit).
The signal says a step loses people; the panel says which dimension is failing
and why.

### 3 — The hypothesis workshop: pre-register the experiment
Walk the author through the five workshop questions in
`references/segment-lens.md` — outcome (the adoption → satisfaction → revenue
ladder), segment, sourced baseline, causal story, and a **pre-registered
prediction** (from X to Y, by when — committed before shipping). The change
itself: one concrete edit to the diagnosed step — reword (Copy), re-pace /
split / cut (Pacing), sharpen the payoff or **add/adjust a value moment**
(Value, via `value-moment`), or re-target (Fit). One change tied to one
diagnosed cause, not a rewrite. **Log the hypothesis** — prefer the Studio
MCP tool `record_hypothesis` (`society-studio` server; links the Tracks row
automatically), fields + template in the reference; direct Airtable write is
the fallback. Status `proposed`.
Every hypothesis names a segment.

**Onboarding tracks (Welcome, or any track that greets brand-new members):
read `references/onboarding-playbook.md` before the workshop.** It carries the
verified methodology — setup/aha/habit moments, benchmark tables with their
definitional traps, the endowed-progress / IKEA-completion / reciprocity
evidence and moderators, the contested labeling effect, and Welcome's
anti-patterns. Onboarding hypotheses that ignore it tend to re-propose
already-refuted patterns.

### 4 — New version → re-enter the gate
Author the change as a **new version** of the `track.json` and **`save_draft`
it immediately** (Studio MCP; note = the hypothesis one-liner; `parent_hash` =
the LIVE version's hash so lineage shows what this candidate is based on).
If the gate round produces further edits, each edit is re-saved (see
track-prototype's iteration loop) — **the LATEST save's returned hash** is the
one the final score must use, and the one `track-publish` will verify against what
is deployed; an earlier save's hash is stale the moment the content changes. Then preview it in the
demo (build-prototype, with the prompt-context note so the change is legible),
then hand to **`track-prototype`** to walk → focus-group → score → gate (set
the Hypotheses row to `in-gate`).

**On gate pass, route immediately to `track-publish`** — before anything is tagged
as shipped. It runs the handoff first (filing what ignite-next needs as an issue
for Red), Red builds and deploys, and only then does its `go_live` step verify
that the deployed content hash-matches the approved version and record the track
live. Routing after a "ship moment" instead would skip the handoff entirely — the
handoff has to precede the build, not follow it.

**Then** tag the version: once `go_live` succeeds, write the shipped
`content_hash` to the Hypotheses row's `version` field with status `shipped`.
Tagging before that marks a hypothesis shipped on the strength of an intention;
`go_live` is what establishes that it actually shipped.

Do not flip the stage yourself: `set_stage` and `set-stage.mjs` both refuse
`live`, because going live now requires proving the deployed content matches an
approved version. `go_live` writes the stage and both pin fields itself. Do not
bypass the gate.

## Guardrails

- **Ground the numbers.** Every drop-off / continuation figure comes from real
  PostHog data (Studio actuals or `/posthog`). No invented percentages — same
  faithfulness rule as `value-moment`.
- **One change at a time.** Optimization is causal: change the diagnosed step,
  re-measure. A scattershot rewrite can't teach you what worked.
- **The gate is non-negotiable.** A proposed version ships only after
  `track-prototype` clears it and a human approves.
- **Enough data first.** If `n_users` is small, say so — a drop on tiny N may be
  noise, not signal.

## Diagnostic loop

TRY (read the signal) → OBSERVE (weakest step + numbers) → DIAGNOSE (focus-group:
which dimension) → ADAPT (one targeted change) → RE-GATE (track-prototype) →
measure again once live: when the tagged version has enough n, re-run the
segment-sliced recipe against the **pre-registered prediction** and mark the
Hypotheses row `validated` or `refuted` (with the measured `result`). A refuted
prediction is a finding — return to step 2 with that knowledge.

## Reference index
- `references/reading-the-signal.md` — the `PostHogActuals` fields + `/posthog` cut for the weak step.
- `references/segment-lens.md` — the four segments, HogQL recipes (per-step × segment, next-track adoption), the focus-group segment overlay, the hypothesis workshop + `Hypotheses` Airtable log, guardrails (segment n, Welcome survivorship).
- `references/onboarding-playbook.md` — REQUIRED for Welcome / onboarding work: activation moments (setup/aha/habit), verified B2C benchmarks + definitional discipline, behavioral-science toolbox with evidence grades (endowed progress, IKEA completion boundary, reciprocity, contested labeling effect), EUREKA→NSLS mapping, anti-patterns, known evidence gaps.
- Hand-offs: `track-prototype` (focus-group + score→gate), `value-moment` (if the fix is a nugget), `track-design` (larger structural changes).
