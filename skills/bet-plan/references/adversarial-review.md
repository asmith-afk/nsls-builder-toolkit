# Adversarial review — the full protocol

Used by `bet-plan` Step P4. This is the last thing that happens before the
planned→live gate offer, and it's the one step in the whole Strategy Studio
pipeline that must NOT be run by the same mind that wrote the memo.

## When

After all `exec.*` and `proof.*` sections are drafted and the primary
experiment exists — before the advance offer, **always**. Skipping it must
be announced out loud and requires the owner's explicit "skip review"
(heartbeat: say what's being skipped and why before moving on).

## The reviewer must be fresh-context

Dispatch a subagent (general-purpose) whose prompt contains ONLY:

1. The full memo rendered from `get_bet` — every section with its evidence
   tag, the assumption chain with statuses, the evidence list with grades
   and links, the rubric scores with confidence, and the experiment(s).
2. The review instructions below, verbatim.

**Nothing else.** No conversation history, no author justifications for why
a section is written the way it is, no hints about which sections the
author is proud of or worried about. The reviewer reads the memo exactly
the way a board member would encounter it cold — that's the entire point of
dispatching a fresh subagent instead of grading it yourself.

## Review instructions (give the subagent this, verbatim)

```
You are reviewing a business-bet memo cold. Score 1-10, with the specific
failing sections named, on:
1. COMPLETENESS — are all pages substantively filled, or padded?
2. CONSISTENCY — do the numbers agree across pages (market size vs revenue
   model vs thresholds)? Does the experiment actually test the thesis?
3. EVIDENCE — does the demand evidence carry the claims? A memo whose
   sections are mostly tagged assumption/opinion cannot score above 4 here.
Then:
4. CHALLENGE THE PREMISE — argue the strongest case this bet should NOT
   exist: the status quo wins, the buyer has no budget, the core business
   is crowded out. Steelman it; don't strawman it.
5. FORCE ALTERNATIVES — propose at least two: a different segment or buyer,
   a different (cheaper/faster) first experiment, or a smaller wedge.
   "Do nothing" is always a valid alternative to price.
List every finding as: FINDING / WHY IT MATTERS / WHAT WOULD FIX IT.
Take positions. No hedging, no compliments.
```

## Surfacing — one decision per question

The reviewer is READ-ONLY — its findings come back to the session, and the
human decides each one. Convert every reviewer finding into exactly ONE
question to the owner: the reviewer's position, the fix, and the cost of
ignoring it. Never present the findings as a wall of text, and never resolve
them yourself on the owner's behalf.

Example form:

> "Reviewer: the base case assumes 12% pilot→paid conversion but the
> evidence shows zero commitment-grade signals. Fix: cut base-case 2027
> revenue to X or run the pre-sale first. Ignore-cost: the board will find
> this in one read. Your call?"

Work through the findings one at a time, in the order the reviewer scored
them worst-axis-first, not in the order they happen to appear in the
transcript.

## Fix rounds — how many, and never more than 2

For each accepted fix, apply it via the normal write tools —
`update_section` / `add_experiment` / `update_experiment` /
`upsert_assumption`, revision-logged, `via: "bet-plan"`.

**Whether a second round happens is Step P0's call, read from `rigor_band`:**

- **Band `small`** — round 1 is normally the whole review. Stop there and go
  straight to recording unresolved findings below. A second round is earned
  only by a round-1 finding that materially changes the bet, and taking it
  should be said out loud. Running two rounds by reflex on a cheap,
  reversible bet is the over-rigor Step P0 exists to prevent.
- **Band `material`** — once the accepted fixes for round 1 are all applied,
  dispatch a NEW fresh-context reviewer — **never the same context**, and
  never the same subagent conversation — it would be grading its own
  suggestions, which isn't review, it's rehearsal.

After the final round, any remaining disagreements are **RECORDED, not resolved**:
unresolved reviewer challenges land in `exec.top_risks` (or the proof plan,
whichever they concern) as named open risks. This is noted dissent, never
silent consensus — a memo that goes to `live` with a challenge quietly
dropped is worse than one that goes with the challenge written down.

## Score floor guidance

If, after the final round, any axis still scores below 5: say plainly that the memo
is not board-ready and recommend against advancing. The owner can still
overrule this — record the overrule and its rationale in the `advance_stage`
rationale, so the decision to advance over a low score is itself on the
record, not silently absorbed.

**One carve-out, band `small` only.** The EVIDENCE instruction above caps a
mostly-`assumption`-tagged memo at 4 — which is every pilot whose experiment
has not run yet. On a small, reversible bet that 4 is the rubric restating
the bet's stage, not a judgement on the work, and it must not by itself
carry a "not board-ready" verdict. Report the score, say why it is capped,
and let the owner decide. This does NOT extend to `completeness` or
`consistency` — those below 5 are real failures on any band — nor to an
`evidence` score that is low for reasons beyond the unrun experiment. Say
which case you're in; the carve-out is narrow on purpose, because a blanket
"scores don't apply to cheap bets" would hollow out the review entirely.
