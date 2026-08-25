---
name: bet-plan
description: >-
  Use when a Strategy Studio bet has cleared research and needs its board-memo
  back half: hardened economics (2026–2028 model, downside/base/upside),
  execution & risk, and a sell-first proof plan with thresholds and an
  investment ask — ending in an adversarial review before the planned→live
  gate. Triggers: "plan the bet", "bet plan", "economics for this bet", "proof
  plan", "investment ask", "design the experiment", "downside base upside",
  "get this bet to live", "board memo pages 4 and 5", "adversarial review",
  "red-team this bet", "stress test the memo".
---

# bet-plan

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — `get_bet`, `list_assumptions`, `list_bets`,
   `get_stack_rank`. Free, no confirmation needed.
2. **Configuration / new-content** — `update_section` (`econ.*`/`exec.*`/
   `proof.*` on this bet), `add_experiment`, `update_experiment`,
   `upsert_assumption`, `score_rubric`. Say out loud what's being written as you go — which
   field, what tag or grade — no per-call confirmation.
3. **Write to shared systems** — `advance_stage`, `set_status`. **Confirm
   the exact values with the human before writing.** No-token/no-server
   branch prints the would-be calls instead of guessing or failing silently.

Every write in every tier passes `via: "bet-plan"`.

## Purpose

A bet arrives here with a canvas, a thesis, and a first-cut economics page
drafted honestly enough to clear the research→planned gate — but nobody has
yet built the model a board would trust, named the top five risks out loud,
or tried to sell the thing before building more of it. `bet-plan` is pages
4 and 5 of the memo: it hardens `bet-research`'s estimates into a
named-assumption model with three honestly-differentiated cases, forces the
execution and risk questions onto the page, designs a sell-first experiment
with thresholds the owner would actually act on, and — before any of that
goes to the board — puts the whole memo in front of a reviewer who has never
seen it before and owes the author nothing. It ends the way `bet-idea` and
`bet-research` do: an explicit ask, never an assumed yes.

## When to use

- A bet already at `planned` stage (handed over by `bet-research` or
  `bet-studio`) needs its economics hardened, execution/risk pages written,
  or a proof plan designed.
- Running or resuming the adversarial review before a planned→live advance.
- Checking planned→live gate progress, or deciding whether a bet has earned
  the advance to `live`.
- **NOT** for a bet still at `research` stage with `market.*`/`econ.*`
  incomplete or the conversation/demand checks unmet — that's
  `bet-research`. **NOT** for a bet already `live`+ — that's `bet-run`
  (Phase 5, not built; say so plainly). **NOT** for portfolio-wide review or
  experiment tracking — those are `bet-review`/`bet-run`.

## Quick Start

Planned-stage bet → **P0** Size the review to the bet → **P1** Economics
hardening → **P2** Execution & risk → **P3** Proof plan → **P4** Adversarial
review loop (max 2 rounds) → **P5** The advance offer → a live-ready bet (or
an honest "not board-ready yet, here's what's failing").

## Operating rules

- **Proportion the rigor to the ask (per Step P0).** Read the investment
  number BEFORE deciding how deep to go. A $5K reversible test and a $2M
  partnership get the same five gate checks and very different depth. Asking
  "does this memo meet board standard?" of a cheap pilot is the wrong
  question; "is this test worth its cost?" is the right one.
- **Show the gate progress bar** (per `references/gate-progress.md`) after
  every `exec.*`/`proof.*` write and at the end of every session.
- **Never call `advance_stage` as a probe** — planned→live carries no
  attestation either, so a passing gate MOVES the bet the instant you call
  it. Compute progress from `get_bet` instead (verbatim rule in
  `references/gate-progress.md`).
- **Named-assumption discipline on every number** (per
  `references/economics-model.md`) — a number without the assumption that
  produces it, stated inline, is an opinion wearing a suit.
- **Sell-first by default** (per `references/experiment-design.md`) — the
  channel picks the instrument; a build experiment always needs stated
  rationale, and a dogfood bet's internal-need rationale is first-class, not
  an apology.
- **The adversarial review is mandatory, not optional busywork** — it runs
  in a fresh subagent with zero shared context and cannot be silently
  skipped. How many rounds it runs is Step P0's call (never more than 2;
  normally one for a small, reversible bet) — the review happening at all
  is what's non-negotiable, not its length.
- **A `data` write REPLACES the whole object — never merge it in your head.**
  `update_section(..., data: {...})` overwrites the section's existing `data`
  wholesale, so any key already there and not repeated in the new call is
  gone. Every write to a section that carries durable keys — `rigor_band` on
  `proof.investment` (Step P0), `review_log` on `exec.top_risks` (Step P4) —
  reads the section first and carries the existing keys forward. The loss is
  silent: nothing errors, and the next resumed session simply finds the key
  missing and behaves as if it was never set.
- **Consume `staleAssumptions`** from every `update_section` response —
  announce it and re-interrogate the listed assumptions, never skip
  silently.
- **Heartbeat every step.** Say what you're about to do, do it, then report
  what happened before moving on. Never batch silently through the workflow.

## Entry: resume vs. route elsewhere

**Trigger:** the user names an existing bet, or `bet-research`/`bet-studio`
hands one over with a `bet_id`. Call `get_bet` first.

- **Normal path** — stage `planned`, status `active`.
- **Stage `research`** — check the research→planned summary in
  `references/gate-progress.md`. If any of the seven checks read red, route
  back to `bet-research` with one sentence naming which check failed. If the
  checklist reads green but the bet was never advanced (an owner sat on a
  ready bet), say so, offer the advance for the owner to confirm (`via:
  "bet-plan"`), and only then continue into `bet-plan`'s own work.
- **Stage `idea`** — route to `bet-idea`.
- **Stage `live`+** — `bet-run` territory (Phase 5 — say plainly it's not
  built); `bet-studio` for anything else that doesn't fit.
- **On resume:** inventory which `exec.*`/`proof.*` fields are still empty,
  and whether an adversarial review round is already on record — check the
  `exec.top_risks` section's `data.review_log` array (Step P4 appends an
  entry after every completed round, even when no fixes were accepted; the
  section's prose stays exactly the top five risks). The planned→live
  progress bar IS the resume agenda — don't re-derive a different one.

## Step P0 — Size the review to the bet

**Do this first, out loud, before any `econ.*` write.** Read the investment
ask — `proof.investment` if `bet-research` drafted one, otherwise ask the
owner for the number and the reversibility in one question. Then say which
band the bet is in and what that changes.

**Small and reversible** (roughly: under ~$25K all-in, no hire, no build, no
multi-year commitment, stoppable inside a quarter):

- `econ.*` at honest-estimate depth. A unit-economic sketch and a stated
  breakeven beat a three-case model built on invented drivers.
- ONE primary experiment, thresholds stated as **decision aids for the
  owner**, not automated tests. A directional read with the interval
  reported is the honest output of a small pilot; a significance bar it
  cannot clear is not.
- Empty `market.*`/`econ.*` from a force-advanced gate are **recorded gaps**,
  not launch blockers — say so plainly and put them in what a continue buys.
- One review round is usually enough.

**Material or irreversible** (a hire, a build, a multi-year commitment, or
enough spend that being wrong is expensive):

- Full `references/economics-model.md` treatment, three differentiated
  cases, named assumptions on every driver.
- Formal thresholds with inference rules, and the economics page as a real
  gate rather than an open item.
- Both review rounds, and the score floor in
  `references/adversarial-review.md` taken seriously.

### Record the band — the later steps read it, they don't re-derive it

The band is a decision, not a mood. Write it down as soon as you say it, on
the `proof.investment` section's DATA (`content_md` untouched) — **reading
the section first and carrying its existing `data` keys forward**, per the
replace-semantics rule in Operating rules:
`update_section(bet_id, "proof.investment", data: { ...existing data,
rigor_band: "small" | "material", band_basis: "<the ask and the
reversibility that decided it>" }, summary: "rigor band", via: "bet-plan")`.

**Step P3 writes this same section**, so its write must carry `rigor_band`
and `band_basis` forward too — dropping them there would silently erase the
band and send the next resumed session back to full rigor.

Steps P1 and P4 branch on this value explicitly. A resumed session reads it
rather than guessing — and a resumed session that finds no `rigor_band`
re-runs P0 rather than defaulting to full rigor, because defaulting silently
is exactly the failure this step exists to prevent.

### What NEVER scales down

The crowding-out test in `exec.core_impact`. A stop threshold that exists and
that the owner would honour. Sell-first. Honest evidence tagging. The review
happening at all. Cheap does not mean unexamined — it means examined at the
right altitude.

### Two failure modes this step exists to prevent

1. **Inventing a bar and then failing the work against it.** If a threshold
   comes from portfolio-scale ambition arithmetic rather than from the
   decision in front of you, say where it came from and whether it belongs.
   A pilot that cannot clear a bar you invented is not a broken pilot.
2. **Reporting tautologies as findings.** On a bet whose experiment has not
   run, the evidence axis is capped by construction and the completeness axis
   largely measures which stage gates were skipped. Both are category
   statements about where the bet sits, not discoveries. Name them as such
   instead of stacking them into a verdict.

## Step P1 — Economics hardening

**Read `rigor_band` from Step P0 first — it decides which of the two
paths below you run.** Where this step and P0 disagree, **P0 wins**; the
depth described below is the `material` path.

**Band `small`** — honest-estimate depth. `econ.model_2026_2028` gets a
single honest trajectory with its drivers named; `econ.cases` gets a stated
breakeven and the one assumption that would have to be wrong for the bet to
lose money, in `content_md`, with whatever `data` is genuinely known. The
three-case `data` shape is **not** required, and a three-case model built on
invented drivers is a worse answer than a sketch that admits what it doesn't
know. Skip to the tagging paragraph below — it applies to both bands.

**Band `material`** — the full treatment that follows.

Per `references/economics-model.md`: revise `econ.model_2026_2028` and
`econ.cases` from `bet-research`'s first-cut estimates into the full
named-assumption model, with the three-case `data` shape (downside connected
to what would actually have to go wrong, upside connected to what would
actually have to go right — never a flat percentage of the base case).
Reconcile against the `market.obtainable` numbers `bet-research` already
sized both ways — **divergence is a finding**, not something to paper over.
Update `econ.revenue_drivers`, `econ.cost_structure`, and
`econ.unit_economics` wherever the hardened model sharpened them.

Every write is honestly tagged (`estimate` by default, `assumption` where a
driver is still untested, `data` only for costs actually paid today). Any
new load-bearing model assumption gets `upsert_assumption`'d, not left to
live only in prose.

## Step P2 — Execution & risk

Write, all with named specifics rather than roles-in-the-abstract:

- `exec.capabilities` — what we have today vs. what must be acquired.
- `exec.team` — named people and fractions of their time, not "a PM."
- `exec.dependencies` — internal and external, each with an owner.
- `exec.top_risks` — exactly the top 5, each with likelihood, impact, and a
  stated mitigation-or-acceptance. Not a longer list trimmed for space —
  the actual top 5.
- `exec.core_impact` — what this bet crowds out in the core business. Apply
  the crowding-out test honestly; "none" is almost never true, and saying
  so anyway is the single easiest way to lose the board's trust in the rest
  of the page.

## Step P3 — Proof plan

Per `references/experiment-design.md`: determine the channel — warm B2B or
cold/B2C, read from the bet's motion, buyer, and relationship counts in
`market.current_data` — and the origin (market vs. dogfood, from the
assumption chain and thesis). Choose the instrument per the verbatim
sell-first doctrine block. Heartbeat the channel/origin reasoning out loud
before landing on an instrument — it's the step of this whole skill most
worth arguing with.

`add_experiment` with a falsifiable hypothesis (a hypothesis with a number
in it, not "we'll learn a lot"). Write `proof.experiment_2026`,
`proof.investment` — **reading it first and carrying `rigor_band` /
`band_basis` forward in `data`, since Step P0 recorded them there and a
`data` write replaces the whole object** — `proof.milestones`, and the three
thresholds
(`proof.threshold_continue`, `proof.threshold_accelerate`,
`proof.threshold_stop`) with numeric `data` where possible, prose-only only
when a metric genuinely resists a number — and say so explicitly when it
does.

## Step P4 — ADVERSARIAL REVIEW LOOP

Per `references/adversarial-review.md`:

1. **Announce it** — "dispatching a fresh-context reviewer — no shared
   history, no author justification." This step cannot be silently skipped;
   skipping requires the owner's explicit "skip review," said back to them
   before moving on.
2. **Dispatch** the subagent (general-purpose) with only (a) the full memo
   rendered from `get_bet` and (b) the review instructions, verbatim — never
   this conversation's history, never a hint about which sections the
   author is proud of.
3. **Surface findings one-decision-per-question** — the reviewer's
   position, the fix, and the cost of ignoring it. Never present findings as
   a wall of text; never resolve them yourself.
4. **Apply accepted fixes** via the normal write tools, revision-logged,
   `via: "bet-plan"`.
5. **Record the round — every time, regardless of outcome.** A round where
   every fix is accepted and folded into the memo leaves no different trace
   than a round where nothing was accepted — both need a durable record, not
   just the one with visible edits. The record lives in the section's DATA,
   never its prose (`exec.top_risks` content is contractually exactly the
   top five risks — audit blocks must not pollute it):
   `update_section(bet_id, "exec.top_risks", data: { review_log:
   [...existing entries, { round: N, scores: { completeness: X,
   consistency: Y, evidence: Z }, verdict: "<one line>",
   unresolved: ["<dissent>", ...] }] }, summary: "adversarial review
   record", via: "bet-plan")` — all three axis scores are stored (resume
   sessions need each of them for the per-axis <5 board-readiness rule in
   Step P5, not a blended number); read the section first and append to
   its existing `data.review_log` array, leaving `content_md` untouched. This is the
   only trace a clean round leaves in `get_bet` — skip it and a resumed
   session has no way to tell the review ran, and will re-run it
   needlessly.
6. **Decide whether round 2 happens — read `rigor_band` from Step P0.**
   - Band `small` — **stop after round 1.** One round is the expected end
     state, not a short-changed one. Go to item 7 and record the round's
     unresolved findings exactly as you would after round 2. Run a second
     round only if round 1 surfaced a finding that materially changes the
     bet, and say out loud why this cheap bet earned it.
   - Band `material` — **re-dispatch a NEW fresh-context reviewer.** Never
     the same subagent context; it would be grading its own suggestions.
7. **Never more than 2 fix rounds** (and for band `small`, normally one).
   After the final round, remaining disagreements are
   RECORDED, not resolved: a challenge that names a genuine RISK joins the
   top-five prose in `exec.top_risks` (displacing a lesser risk if needed);
   everything else lands in the round's `data.review_log` entry (`unresolved`
   list) from step 5. Noted dissent, never silent consensus.

## Step P5 — The advance offer

**Reading the review scores — apply the band before applying the floor.**
The board-readiness rule is: any axis below 5 after the final round means
say plainly the memo is not board-ready. On band `material` that stands as
written. On band `small` there is one carve-out, and only one: the reviewer
instructions cap `evidence` at 4 for a memo that is mostly `assumption`-
tagged, which every pre-experiment pilot is **by construction**. That score
is a statement about where the bet sits, not a finding about its quality —
report it, say why it is capped, and **do not let it alone block the advance
offer**. Everything else holds: a `completeness` or `consistency` below 5 is
a real failure on any band, and a small-band `evidence` score that is low
for some reason OTHER than the unrun experiment is a real finding too. Name
which of the two you are looking at rather than waving the axis through.

Render the planned→live checklist (client-side, per
`references/gate-progress.md` — never a probe). Draft the exact `rationale`
text — citing the review scores and any recorded dissent — and put it in
front of the owner alongside the ask: **take it live with this rationale:
"<drafted rationale>"?** This is a Tier 3 write — the confirm has to cover
the whole call, not just the yes/no on the stage change; `rationale` is
audit text that lands in the shared system same as `to_stage` does.

- **Yes** → `advance_stage(bet_id, to_stage: "live", rationale, via:
  "bet-plan")` using the confirmed rationale text verbatim. Show the
  returned `{ moved, gate: { checks } }` either way.
- **No** → the bet stays `planned`. Offer `set_status(bet_id, status:
  "parked", rationale)` (confirmed) if the owner wants it shelved instead of
  left active.

Force is available only to `STRATEGY_FORCE_APPROVERS`, with a mandatory
rationale. It is invoked via the `advance_stage` tool with `force: true` and a
`rationale` argument — the caller's email must be in `STRATEGY_FORCE_APPROVERS`
for the override to succeed. This skill never invokes it; an approver does so
deliberately, outside this workflow. It exists for a real edge case, never
suggest it as the easy path around a red checklist or an unresolved review.

## The pipeline (where this sits)

```
bet-research ──▶ bet-plan (pages 4-5, adversarial review,
                            drives planned→live)
             ──▶ bet-run (Phase 5, not built — interim: say so plainly)
```

**Hand-off contracts:** receives bets from `bet-research` (post
research→planned, `market.*`/`econ.*` first-drafted) or `bet-studio`;
hands `live` bets to `bet-run` once `advance_stage` returns `moved: true` —
Phase 5, not built yet, say so plainly rather than improvising a substitute.
Called by `bet-studio`'s "Plan economics / proof plan" hand-off.

## Red flags — STOP

- Downside case = base × 0.8. → The downside is the world where the
  riskiest still-unresolved assumption is wrong, traced to a specific
  assumption row — not a percentage haircut.
- Success thresholds stated in meeting counts for a warm-B2B experiment. →
  Warm partners take meetings for free. Commitment/payment signals only.
- Running the "adversarial review" in the same context that wrote the
  memo. → It must be a fresh subagent with zero shared history — no
  exceptions, no "I'll just be objective."
- A build experiment with no rationale — or a dogfood bet apologizing for
  its build instead of claiming the first-class internal-need rationale and
  testing external willingness to pay. → State the rationale; for dogfood
  bets, the internal need already justified the build.
- A stop threshold the owner wouldn't actually honor if it fired. → Ask
  directly before writing it down; decoration thresholds are worse than no
  threshold.
- More than 2 fix rounds. → Analysis paralysis. Record the dissent in
  `exec.top_risks` and let the owner decide.
- A power calculation, a three-case model, or a significance bar on a
  sub-$25K reversible pilot. → Step P0. The rigor is out of proportion to the
  decision, and the most likely outcome is failing the bet against a standard
  you introduced.
- Reporting "evidence 2/10" or "completeness 3/10" as a finding on a bet
  whose experiment has not run. → Those are restatements of "this is early,"
  not discoveries. Say so.
- A markdown on a rubric criterion that is really about a different
  criterion. → Real finding, wrong variable. It double-counts, and it moves
  the stack rank on a mis-mapping.
- Advancing to `live` without the review on record and without the owner's
  explicit skip. → The review is a required step, not a formality around
  one.

## No token / server missing

If `strategy-studio` MCP calls fail or the tools aren't visible, don't guess
at what would have been written and don't fail silently — print the exact
values each call would have carried (field keys, evidence tags, experiment
`kind`/hypothesis/thresholds, scores) so the human can enter them by hand,
and point at `/connect` or the README's Strategy Studio setup section
(`STRATEGY_MCP_TOKEN`, minted by Kevin, SLT authors only).

## Reference index

- `references/economics-model.md` — named-assumption discipline, the
  2026–2028 model, the three-case `econ.cases` shape and honesty rules,
  unit economics.
- `references/experiment-design.md` — the sell-first channel doctrine, the
  `add_experiment` recipe, the three thresholds, the investment ask.
- `references/adversarial-review.md` — the full fresh-subagent review
  protocol: instructions, surfacing, fix rounds, score-floor guidance.
- `references/gate-progress.md` — the research→planned entry-check summary,
  the planned→live checklist (transcribed from the engine's `gates.ts`), the
  never-probe rule, the rendering format.

## Rationalization table

| Excuse | Reality |
|---|---|
| "The memo is obviously ready; the review is a formality." | The reviewer is fresh-context for a reason. Every author thinks their memo is ready. |
| "I'll review it myself, a subagent is overhead." | You wrote it. You will grade your own homework kindly. Dispatch the subagent. |
| "Round 3 will finally settle it." | Max 2 rounds. Record the dissent in `exec.top_risks` and let the owner decide. |
| "The downside case is just the base case minus a fifth, close enough." | The downside is the world where the riskiest assumption is wrong — trace it, don't discount it. |
| "They're a warm partner, of course a meeting counts as a signal." | Warm partners say yes to meetings for free. The experiment measures what they'll give up. |
| "It's a dogfood bet, I'll just note the build wasn't really tested." | The internal need is a first-class rationale, not an apology — and it still doesn't excuse testing external willingness to pay. |
| "I'll just call `advance_stage` to see the planned→live checklist." | It moves the bet when the gate passes. Compute progress from `get_bet` instead. |
| "The core business impact is basically zero, I'll write 'none.'" | Apply the crowding-out test honestly — "none" is almost never true, and it's the fastest way to lose the board's trust in the rest of the page. |
| "More rigor is never wrong." | It is when it fails a cheap test against a bar you invented, and when it costs the owner review rounds on axes that only restate the bet's stage. Step P0. |
| "The pilot can't detect the threshold, so the pilot is broken." | Check which one you chose first. If the bar came from 2028 portfolio arithmetic and the pilot costs $5K, the bar is the broken part. |
| "The owner keeps pushing back on my framing; I should explain it better." | Repeated pushback on framing is evidence about the frame. Re-derive it before defending it. |
