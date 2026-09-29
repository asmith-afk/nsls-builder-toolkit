# Gate progress — the three gates bet-plan drives, rendered client-side

Self-contained copy for `bet-plan`: the entry-side summary of the
research→review gate (so a bet arriving here can be sanity-checked without
reading `bet-research`'s reference material), then the three gates this skill
actually drives — review→experiment, experiment→planned and planned→live. Shown after every section write and at
the end of every session (Step P5 is the final render before the advance
offer).

## The NEVER-probe rule (verbatim)

```
NEVER call advance_stage to "check progress". research→review has no
attestation — if the gate happens to pass, the probe MOVES the bet. Compute
progress from get_bet instead, using the checklist below. advance_stage is
called exactly once: when the owner says advance.
```

The same reasoning governs `bet-plan`'s own gates: **none of the three
carries an attestation on the normal path** — `advance_stage(bet_id,
to_stage: "experiment" | "planned" | "live", ...)` takes a `rationale`, never
an `attest` object, unless you are firing the `no_cheap_experiment` escape
(a deliberate, approver-restricted call, not a probe). So there is no safe
way to "peek" at any of these checklists by calling `advance_stage` — if the
checks below already pass, the call moves the bet on the spot. Compute the checklist from `get_bet` every time, and reserve
`advance_stage` for the one moment the owner actually says take it live.

## Entry check (research→review, summary)

A bet handed to `bet-plan` should already be at stage `review` or later —
meaning `bet-research` drove it through the research→review gate already. If
a bet arrives at stage `research` instead, it belongs to `bet-research`; the
quick tell is whether the six research→review checks are green. If any read
red, route back to `bet-research` with one sentence naming which check
failed — don't attempt to close research-stage gaps from inside `bet-plan`.

The six checks, one line each (numbers match `bet-research`'s
`references/gate-progress.md` exactly). `econ_complete` is NOT one of them —
it sits on experiment→planned below, so an empty econ page never sends a
research-stage bet back:

1. `market_complete` — all 5 `market.*` sections non-empty.
2. `top_assumptions_resolved` — the up-to-3 riskiest (lowest `priority`
   value) assumptions present are `validated` or `invalidated`; denominator
   is `min(3, assumption count)` — a bet with only 1 or 2 assumptions needs
   exactly those resolved, not a padded /3.
3. `conversations` — ≥5 interview/roadshow evidence rows, ≥4
   problem-confirmed, ≥3 distinct institutions.
4. `demand_signals` — ≥2 linked rows at `exploration`/`commitment`/`payment`.
5. `sizing_both_ways` — `market.obtainable` has both `data.top_down` and
   `data.bottom_up` as numbers, both DOLLAR figures (obtainable revenue) —
   see `bet-research`'s `references/self-serve-research.md` for how each is
   composed.
6. `rubric_scored` — all 5 criteria scored, none still `low` confidence.

If the checklist reads green but the bet was never advanced (an owner sat on
a ready bet), say so and offer the advance rather than silently starting
`bet-plan`'s own work on a research-stage bet.

## The review→experiment checklist (transcribed from `gates.ts` — keep exact)

1. **`cheapest_experiment_approved`** — ≥ 1 experiment on the bet carries
   EVERY sign-off it needs. Required kinds are `strategy` (always) plus
   `money` / `headcount` / `brand` / `operations` for each `needs_*` flag set
   on the row. The failure detail names them per experiment, e.g.
   `Landing page awaiting brand · Paid pilot awaiting strategy, money`.
   Cleared instead by `attest.no_cheap_experiment` — approver-restricted and
   rationale-required (see the SKILL).
2. **`sell_first`** — every experiment with `kind: "build"` has a non-empty
   `rationale`. (This check used to sit on planned→live; it moved here, where
   the answer still matters.)

## The experiment→planned checklist

1. **`econ_complete`** — all 5 `econ.*` sections have non-empty `content_md`.
   (Moved off the old research→planned gate: economics is a planning input,
   and asking for it before the cheapest test had run produced models built on
   nothing.)
2. **`experiment_tracked`** — among the FULLY SIGNED-OFF experiments, ≥ 1 has
   a verdict other than `running`, or ≥ 1 recorded metric. A reading from an
   unapproved experiment does not count. Also cleared by
   `attest.no_cheap_experiment`, on the same terms — but the attestation
   applies to ONE call only. A bet that took the escape into `experiment`
   has no approved experiment to track, so the experiment→planned advance
   must carry `attest: { no_cheap_experiment: true }` and a rationale AGAIN,
   fired by a strategy approver again. Without it this check reads red
   forever.

## The planned→live checklist (transcribed from `gates.ts` — keep exact)

1. **`exec_complete`** — all 5 `exec.*` sections have non-empty
   `content_md`: `capabilities`, `team`, `dependencies`, `top_risks`,
   `core_impact`.
2. **`proof_complete`** — all 6 `proof.*` sections have non-empty
   `content_md`: `experiment_2026`, `investment`, `milestones`,
   `threshold_continue`, `threshold_accelerate`, `threshold_stop`.

`experiment_defined` and `sell_first` used to be checks 3 and 4 here. They
moved UP to review→experiment — `sell_first` as its own check, and
`experiment_defined` folded into `cheapest_experiment_approved` (there is no
separate `experiment_defined` key any more; "no experiment defined" is that
check's failure detail). By the time a bet reaches live those questions were
answered two gates ago, and asking again was theatre.

## Rendering format

Render the checklist for the gate the bet is currently driving toward. Show
it after EVERY `add_experiment`, `approve_experiment` or `update_experiment`
write (review and experiment stages), after EVERY `econ.*`/`exec.*`/`proof.*`
write, and at the end of every session:

```
review → experiment gate
  [✗] cheapest experiment signed off
        Fall roadshow pre-sale awaiting money
  [✓] sell-first: 0 build experiments, nothing to check
Next cheapest unlock: …
```

```
experiment → planned gate
  [✗] econ page 3/5 (missing: model_2026_2028, cases)
  [✗] experiment tracked: Fall roadshow pre-sale still running, 0 metrics
Next cheapest unlock: …
```

```
planned → live gate
  [✓] exec page 5/5
  [✗] proof page 4/6 (missing: threshold_accelerate, threshold_stop)
Next cheapest unlock: …
```

Always close with the single next-cheapest unlock. If the adversarial
review hasn't run yet, say so explicitly alongside the checklist — the
review isn't one of the engine-checked boxes, but Step P4 makes it a
required step before the advance offer regardless of what the checklist
reads. Check for a completed round by looking for an "Adversarial review
round N" block in `exec.top_risks` — Step P4 writes one after every
completed round, even a clean one with no accepted fixes.
