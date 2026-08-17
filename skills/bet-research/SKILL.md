---
name: bet-research
description: >-
  Use when a Strategy Studio bet is at Research stage and its assumption
  chain needs to be worked riskiest-first into evidence — self-serve market
  research, warm-channel buyer interviews, market sizing both directions, and
  the drive toward the research→planned gate. Triggers: "research a bet",
  "bet research", "work the assumptions", "log an interview", "log evidence
  against the bet", "size the market for", "who should we talk to about",
  "target shortlist", "roadshow sprint", "is anyone actually paying for
  this", "validate the bet", "resume research on", "commercialization
  research", "research a competitor", "what do we know about <company>",
  "add a competitor", "update the competitor page", "does anyone cover this
  job".
---

# bet-research

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — `get_bet`, `list_assumptions`, `list_bets`,
   `list_taxonomy`, `size_segment`, `target_shortlist`, `get_stack_rank`,
   `list_competitors`, `get_competitor`, `get_competition_grid`.
   Free, no confirmation needed.
2. **Configuration / new-content** — `log_evidence`, `update_section`
   (`market.*`/`econ.*` on this bet), `upsert_assumption`,
   `resolve_assumption`, `score_rubric`, `upsert_move`, `link_move_bet`,
   `log_move_evidence`, `upsert_competitor`, `update_competitor_section`,
   `map_competitor_job`, `link_competitor_bet`, `tag_evidence_competitor`,
   `mark_competitor_reviewed`. Say out loud what's being written as you go —
   which field or evidence kind, what tag or grade, which bets a move links,
   or which company a claim lands on — no per-call confirmation.
   **Competitor pages are shared across bets**, so announce a page you create
   (`log_evidence` and `tag_evidence_competitor` return `created_stub: true`)
   the same way you announce a section write.
3. **Write to shared systems** — `save_targets` (names real schools onto a
   rep-visible call list), `advance_stage`, `set_status`, `hand_off_bet`
   (assigns the work to a real squad or person), `upsert_taxonomy`.
   **Confirm the exact values with the human before writing.**

Every write in every tier passes `via: "bet-research"`.

## Purpose

A bet arrives here with a full canvas and a ranked list of beliefs that might
be wrong — but nobody's actually gone and found out yet. `bet-research` is
the working session where that happens: the riskiest assumption sets the
agenda, self-serve market data closes what our own systems can already
answer, warm-channel buyer conversations close what only a human conversation
can, and every finding lands honestly tagged so the eventual gate reading
means something. It ends the way `bet-idea` does — with an explicit ask, not
an assumed yes — but the ask here is "does the evidence say advance," backed
by a checklist instead of a rubric score.

## When to use

- A bet already exists at Research stage (created by `bet-idea`, handed over
  by `bet-studio`) and needs its assumptions worked into evidence.
- Logging a buyer conversation, a roadshow meeting, a competitor finding, or
  a market-sizing pull against an existing bet.
- Checking research→planned gate progress, or deciding whether a bet has
  earned the advance.
- **NOT** for a bet still at Idea stage with no canvas yet — that's
  `bet-idea`. **NOT** for a bet already `planned`+ — that's `bet-plan` (or
  `bet-studio` if unsure which). **NOT** for portfolio-wide review or
  experiment tracking — those are `bet-review`/`bet-run`.

## Quick Start

Research-stage bet → **R1** Load the agenda → **R2** Self-serve sweep →
**R3** Buyer conversations → **R4** Roadshow sprint (optional) → **R5**
Resolve and re-rank → **R6** Rubric re-score → **R7** The gate drive → a
planned-ready bet (or an honest "not yet, here's the cheapest unlock").

## Operating rules

- **Riskiest first, always.** The `strategy_assumptions` list — ordered by
  `priority` — IS the research agenda. Never research in canvas order or
  "easiest first" without saying so and why out loud.
- **Show the gate progress bar** (per `references/gate-progress.md`) after
  EVERY evidence write and at the end of every session.
- **Never call `advance_stage` as a probe** — the verbatim rule from
  `references/gate-progress.md`: research→planned has no attestation, so a
  passing gate MOVES the bet the instant you call it. Compute progress from
  `get_bet` instead.
- **Evidence honesty.** Conversations are `data`; AI-drafted section content
  is `assumption`/`estimate`; demand grades climb the commitment ladder;
  `exploration`+ requires a link; internal enthusiasm is `interest`, never
  demand.
- **Rubric confidence is earned, not scheduled.** Re-score at `medium` only
  when the score cites evidence rows; `high` only for direct, strong
  evidence. Never bulk-upgrade all 5 to satisfy the gate.
- **Consume `staleAssumptions`** from every `update_section` response —
  announce it and re-interrogate the listed assumptions, never skip
  silently.
- **Heartbeat every step.** Say what you're about to do, do it, then report
  what happened before moving on. Never batch silently through the workflow.
- **Spot leverage moves.** When research turns up ≥2 bets sharing a buyer,
  a segment, or an assumption — same career-services buyer, same "will they
  reply to a cold campaign" question — that's a **move**, not two separate
  research threads: propose `upsert_move` + `link_move_bet` on each bet,
  and make the note name the specific hypothesis THAT bet is testing (not
  just the shared taxonomy anchor). When one conversation, campaign, or
  result de-risks several linked bets at once, log it **ONCE** via
  `log_move_evidence` — it fans out to every linked bet's evidence
  automatically. Never hand-log the same result against each bet
  separately; that silently doubles (or triples) a single data point.

## Entry: resume vs. route elsewhere

**Trigger:** the user names an existing bet, or `bet-studio`/`bet-idea` hands
one over with a `bet_id`. Call `get_bet` first.

- Stage must be `research`, status `active`.
- **If `idea`** → route to `bet-idea`. It resumes the bet; if the canvas is
  done and the owner judges it worth a slot, the advance happens THERE, with
  the attestation.
- **If `planned`+** → route to `bet-plan` (or `bet-studio` if unsure which).
- **If `parked`/`killed`** → say so, offer a confirmed `set_status` revive,
  or stop.
- **If `handed_off`** → say who has it and the work status (`get_bet`'s
  `handoffs[0]`). Research is over for this one: it left the board as squad
  work. Reviving it as a bet is a confirmed `set_status(active)` — which also
  closes the hand-down — and it needs a reason the materiality bars are now
  met, not just renewed enthusiasm.

**On resume:** inventory engine state — which `market.*`/`econ.*` fields are
empty, assumption statuses, evidence counts and distinct institutions,
rubric confidence per criterion — and announce it. The gate progress bar
(`references/gate-progress.md`) IS the resume agenda; don't re-derive a
different one.

## Step R1 — Load the agenda

Call `list_assumptions` (priority ascending) and `get_bet`. Render: the
assumption chain with status, then the gate progress bar.

**Detect origin.** Internal-origin bets show commercialization assumptions
at priority 1–2 and internal-usage evidence carried over from `bet-idea`. If
it's unclear, ask: *"market hypothesis, or something we built for
ourselves?"*

**Internal-origin variant.** The agenda centers the commercialization
leaps — "someone OUTSIDE NSLS has this problem badly enough to pay" and
"buyer budget/priority exists." The self-serve dimensions still run in full
(competition, sizing, and reach are external questions regardless of
origin); build-to-value is usually already strong — cite the internal system
rather than re-deriving it. **Internal usage evidence NEVER counts toward
the conversation or demand-signal gates** — external demand has to climb the
same ladder as any market-origin bet. There is no dogfood discount on the
gate itself.

## Step R2 — Self-serve sweep

Per `references/self-serve-research.md`: work the five dimensions
(competition, market size both directions, our reach, time to revenue,
build-to-value risk) in the order the assumption agenda demands, not fixed
order. Each dimension ends with sections written under an honest tag,
evidence logged where applicable, and — where it resolves an assumption —
`resolve_assumption` called with the evidence id linked.

**Competition is company-scoped.** Read the existing competitor pages before
researching anything: a `fresh` page is a colleague's finished work, and
re-deriving it is the waste this axis exists to end. New findings land on the
company page (memo sections, coverage claims, stance) with `market.alternatives`
keeping only this bet's synthesis. Record `absent` coverage explicitly — a
missing claim reads as unassessed, not as open water.

**`absent` has an evidence bar.** It means "we looked," so it needs a source
that would have named the feature if it existed: support docs, release notes,
developer docs, or the product. A marketing page is not one — it sells a
positioning and omits table-stakes features precisely because they are
unremarkable. When that is all you have, leave the cell `unassessed`, say so
out loud, and name the surfaces you checked in the note. And before turning a
row of `absent` cells into "this job is open water," check what tier of
evidence those cells rest on: the narrowest true claim beats the strongest
retractable one. See `references/self-serve-research.md` for the source table.

Freshness excuses re-deriving the **memo**, never the **per-bet layer**: a
fresh page still needs `map_competitor_job` coverage and a `link_competitor_bet`
stance for THIS bet, plus the bet's own `market.alternatives`. Skip those and
the bet reads as having no competitors at all.

Heartbeat each dimension: *"sizing next because assumption #1 is
market-risk…"* Never silently batch through all five.

## Step R3 — Buyer conversations

Per `references/interview-guide.md`: draft the interview guide tuned to this
bet's buyer and riskiest customer assumptions. The owner runs the actual
conversations through reps' regular buyer meetings (Fathom-recorded as a
matter of course); the owner returns with recordings or summaries, and this
skill logs each one as a Customer Forces Story via the `log_evidence`
recipe — grading `signal_strength` from behavior in the transcript, never
from enthusiasm in the summary.

After each conversation: show the gate progress bar; check saturation — have
the stories stopped changing? If so, say so; the ≥5 gate is a floor, not the
stopping point.

## Step R4 — Roadshow sprint (optional path)

Per `references/roadshow-sprint.md`: when the conversation gate is the
bottleneck — ad-hoc rep calls can't reach 5 conversations across 3 distinct
institutions fast enough — PROPOSE a sprint scoped to this bet's segment and
buyer, N schools drawn from the saved target shortlist. On the owner's yes,
hand all pipeline mechanics to the **campus-roadshow** skill — this skill
never duplicates that pipeline. Afterwards, log each meeting as `kind:
"roadshow"` evidence linked to its report page.

## Step R5 — Resolve and re-rank

Each resolved assumption flips via `resolve_assumption(status, evidence_id)`.

**An invalidated load-bearing assumption is the cheap kill signal.** Say it
plainly, present the fork:
- **Pivot** — revise the affected sections and re-interrogate the chain.
- **Kill** — `set_status(bet_id, status: "killed", rationale)`, rationale
  required, confirmed with the owner.
- **Hand it down** — `hand_off_bet(bet_id, squad_id | individual_email,
  rationale)`, confirmed with the owner. This is the RIGHT fork for the
  finding research produces most often and nobody plans for: the problem is
  real and the buyers confirmed it, but the ceiling is well under the
  materiality bars. That is not an invalidation and it is not a kill — the
  work is worth doing, it just isn't a bet. Killing it here is the single
  most common way a true finding gets filed as a failure. Read `list_squads`
  first so the work goes to a group that exists.

Never bury an invalidation in a progress summary — it's the headline of that
session, not a footnote.

## Step R6 — Rubric re-score

As evidence lands, `score_rubric` the affected criteria at `medium`+
confidence, with notes citing the specific evidence rows that earned the
upgrade. Show the new rank position and confidence alongside the score.

## Step R7 — The gate drive

End every session with the full checklist (`references/gate-progress.md`)
and the single next-cheapest unlock. When all 7 checks read green, draft the
exact `rationale` text the advance call would carry and put it in front of
the owner alongside the ask: **advance to planned with this rationale:
"<drafted rationale>"?** This is a Tier 3 write — the confirm has to cover
the whole call, not just the yes/no on the stage change; `rationale` is
audit text that lands in the shared system same as `to_stage` does.

- **Yes** → `advance_stage(bet_id, to_stage: "planned", rationale, via:
  "bet-research")` using the confirmed rationale text verbatim. Show the
  returned `{ moved, gate: { checks } }` either way.
- On `moved: true` → hand off to `bet-plan`.

**The owner decides** — a green checklist is necessary, never sufficient.

## The pipeline (where this sits)

```
bet-idea ──▶ bet-research (fills market.* + econ.* first drafts,
                            drives research→planned)
          ──▶ bet-plan (pages 4-5, drives planned→live)
          ──▶ bet-review / bet-run (Phase 5)
```

**Hand-off contracts:** receives bets from `bet-studio` (with `get_bet`
context loaded) or directly from `bet-idea` post-gate (`idea → research`
already attested); hands planned bets to `bet-plan` once `advance_stage`
returns `moved: true`. Called by `bet-studio`'s "Research a bet" hand-off.

## Red flags — STOP

- Grading a friendly "we'd love this!" as `commitment`. → It's `interest`.
  Commitment costs the buyer something — a budget line, a pilot agreement,
  an LOI.
- Logging exploration+ without a link. → Gate-invisible AND dishonest, go
  get the Fathom timestamp or roadshow report page first.
- Researching easiest-dimension-first silently. → The agenda is
  riskiest-first; say so if you deviate and why.
- Calling `advance_stage` "to see the checklist." → It moves the bet the
  moment the gate passes. Compute progress from `get_bet` instead.
- Upgrading rubric confidence to `medium` to clear the gate without citable
  evidence. → Confidence is earned by evidence rows, not scheduled by the
  gate's needs.
- Treating internal usage as demand evidence on a dogfood bet. → External
  demand climbs the same commitment ladder as any market-origin bet — no
  exceptions for internal-origin bets.
- Leaving `econ.*` empty "for `bet-plan`." → The gate checks non-empty
  content on all 5 `econ.*` fields now; draft honest first-cut estimates,
  don't wait.
- Grading a competitor `absent` on a feature because their marketing site
  doesn't mention it. → Marketing pages omit table-stakes features. Check
  support docs, release notes, developer docs, or the product; otherwise the
  cell is `unassessed` and you say so.
- Telling the owner "nobody does X, that's our opening" off a row of `absent`
  cells. → Check the evidence tier under those cells first. A market-level
  claim built on marketing-page silence gets retracted, and it takes the
  credibility of your other findings with it. Report the narrowest version
  the evidence supports, and name what would change it.

## No token / server missing

If `strategy-studio` MCP calls fail or the tools aren't visible, don't guess
at what would have been written and don't fail silently — print the exact
values each call would have carried (field keys, evidence tags, `kind`,
`signal_strength`, links, scores) so the human can enter them by hand, and
point at `/connect` or the README's Strategy Studio setup section
(`STRATEGY_MCP_TOKEN`, minted by Kevin, SLT authors only).

## Reference index

- `references/interview-guide.md` — the Customer Forces method for warm
  channels: who to talk to, the four forces, the anti-sycophancy and grading
  rules, the `log_evidence` recipe.
- `references/self-serve-research.md` — the five self-serve dimensions,
  exact tool recipes, where each lands, the `econ.*` first-draft rule, and
  the company-scoped competition recipe (read-before-research, the five memo
  sections, coverage claims, per-side stances).
- `references/gate-progress.md` — the research→planned checklist
  (transcribed from the engine's `gates.ts`), the never-probe rule, the
  rendering format.
- `references/roadshow-sprint.md` — when and how to propose a roadshow
  sprint, routed through the `campus-roadshow` skill.
- `references/customer-interview-playbook-notes.md` — the source Ash Maurya
  notes the interview guide is built from.

## Rationalization table

| Excuse | Reality |
|---|---|
| "They sounded really excited, that's commitment." | Enthusiasm is `interest`. Commitment is a named budget line, a pilot agreement, an LOI — something that costs them. |
| "I'll just call `advance_stage` to render the checklist." | It moves the bet when the gate passes. Compute progress from `get_bet` instead. |
| "Five chats with Mott CC = five conversations." | The gate counts DISTINCT institutions — ≥3. Same school, one institution, no matter how many people you talked to there. |
| "No link, but I know it was an exploration-grade conversation." | Unlinked grades are self-attested by the party that wants the bet to advance. Get the Fathom timestamp or it doesn't count. |
| "The econ page can stay thin, `bet-plan` will fill it in." | The gate checks `econ.*` non-empty NOW. Draft honest first-cut estimates before moving on. |
| "It's an internal tool everyone here loves, that's demand." | Internal enthusiasm is `interest`, never market demand — even on a dogfood bet, external evidence has to climb the same ladder. |
| "The rubric's been low confidence forever, I'll just bump it to medium." | Confidence is earned by citable evidence rows, not scheduled to clear a gate. Cite the row or leave it low. |
| "I'll just write the competitor findings into `market.alternatives`." | Then B-2, B-3 and B-9 each re-research the same company. Findings go on the company page; the bet keeps the synthesis. |
| "I only log what competitors DO cover — the gaps are obvious." | A cell with no claim renders `unassessed`, never open water. Unlogged `absent` findings manufacture blank space nobody can act on. Record the negative. |
| "Their site doesn't mention it, so it's `absent`." | Marketing pages sell a positioning, not a feature inventory — they omit table-stakes features BECAUSE those are unremarkable. `absent` needs support docs, release notes, developer docs, or the product. Otherwise leave it `unassessed` and say so. |
| "Nothing came up when I searched, that's good enough for `absent`." | Name the surfaces you checked in the note, or the next reader cannot weigh the claim. A negative whose note doesn't say where you looked should be read as `unassessed`. |
| "Every company I graded reads `absent` — this job is open water." | Check what tier of evidence those grades rest on before escalating cell-level calls into a market-level claim. One field-wide conclusion built on marketing-page silence had to be retracted the same day it was reported. State the narrowest version the evidence supports. |
| "There's already a page for them, I'll refresh the research anyway." | Check `freshness` first. A `fresh` page is a colleague's finished work — cite its evidence rows. Re-deriving it is exactly the waste this axis removes. |
| "The page came back `fresh`, so I read it and moved on." | Freshness is a property of the company page, not of your bet. Coverage claims and the `link_competitor_bet` stance have never been made for THIS bet — skipping them leaves the bet's competition view empty, which renders identically to having no competitors. |
| "One stance covers the bet, the b2b/b2c split can go in the note." | A note is not queryable and the bet page cannot show two stances. Pass `payer_type` when the sides genuinely differ. |
| "Sizing's close enough, I won't flag the divergence." | A >3× top-down/bottom-up gap gets named out loud, with the assumption driving it — silence there just hides the riskiest number. |
