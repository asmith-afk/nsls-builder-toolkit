# Gate progress — the research→planned checklist, rendered client-side

Used by `bet-research` throughout — shown after every evidence write and at
the end of every session (Step R7). This checklist mirrors the engine's
`gates.ts` exactly; the numbers below are transcribed from it and must stay
exact if the engine ever changes.

## The rule (verbatim)

```
NEVER call advance_stage to "check progress". research→planned has no
attestation — if the gate happens to pass, the probe MOVES the bet. Compute
progress from get_bet instead, using the checklist below. advance_stage is
called exactly once: when the owner says advance.
```

Unlike `idea → research` (which requires `attest.worth_researching`),
`research → planned` has no attestation gate. That means there is no safe
way to "peek" at the checklist by calling `advance_stage` — if all seven
checks already pass, the call moves the bet on the spot. Compute the
checklist yourself from `get_bet` (sections, assumptions, evidence, scores)
every time, and reserve `advance_stage` for the one moment the owner actually
says go.

## Effective weight (applies to checks 4 and 5)

Every evidence row carries `provenance` — `'human'` (the default, including
every legacy row) or `'auto'` (pipeline-captured) — and may carry an
attestation (`attested_by` + note). Effective weight, transcribed from
`effectiveWeight()`:

- `human` provenance, or ANY attested row → **1.0**
- unattested `auto` → **0.5**

So weighted totals can be fractional (`5.5/5` is normal), and "full weight"
below always means effective weight 1.0.

## The checklist (transcribed from `gates.ts` — keep the numbers exact)

1. **`market_complete`** — all 5 `market.*` sections have non-empty
   `content_md`.
2. **`econ_complete`** — all 5 `econ.*` sections have non-empty `content_md`.
3. **`top_assumptions_resolved`** — the engine takes `ranked.slice(0,3)`: the
   up-to-3 riskiest (lowest `priority` value) assumptions present are all
   `validated` or `invalidated`. The denominator is `min(3, assumption
   count)`, not a fixed 3 — a bet with only 1 or 2 assumptions needs exactly
   those resolved, no more. Fails only when zero assumptions exist ("nothing
   has been de-risked"). The client-side bar must never read red when this
   check would already pass.
4. **`conversations`** — evidence rows of kind `interview` or `roadshow`,
   counted per distinct MEETING, not per row: rows sharing a
   `data.fathom_recording_id` collapse into ONE conversation whose weight is
   the max effective weight among its rows; rows without the key (every
   hand-logged row today) are each their own conversation. Passes only when
   ALL FOUR hold:
   - weighted conversation count ≥ 5;
   - weighted problem-confirmed ≥ 4 — a meeting's confirmation weight is the
     max effective weight among its rows with `data.problem_confirmed ===
     true` ONLY. An unattested auto claim's confirmation contributes 0.5
     even inside a meeting that also has a full-weight human-logged row —
     the human row never launders the auto row's confirmation up to 1.0;
   - distinct `entity_id` values ≥ 3 (five meetings with one friendly
     school still can't satisfy it);
   - ≥ 1 FULL-WEIGHT conversation — the human floor. A bet can never reach
     `planned` on unattested auto evidence alone, however much of it exists.
5. **`demand_signals`** — per ROW, no meeting grouping: the weighted count
   of rows with `signal_strength` ∈ {exploration, commitment, payment} AND
   non-empty `link` is ≥ 2, AND ≥ 1 such row is full weight (same human
   floor). Interest never counts; unlinked grades never count. (A write-time
   rule keeps this check honest: pipeline rows without a recording link are
   capped at `interest`, so they can never enter it.)
6. **`sizing_both_ways`** — `market.obtainable` section `data.top_down` AND
   `data.bottom_up` are both numbers, and both are DOLLAR figures (obtainable
   revenue) — see `references/self-serve-research.md` for how each is
   composed. Raw counts never belong in either field.
7. **`rubric_scored`** — latest score per criterion exists for all 5 AND none
   is still `low` confidence.

## Attestation — how an auto row reaches full weight

`attest_evidence(evidence_id, note)` via MCP promotes an unattested auto row
to weight 1.0. The note (≥ 10 characters, required) asserts one specific
thing: the attester opened the linked recording/quote and agrees the grade
is honest. The pipeline identity and an auto row's own creator can NEVER
attest it — a service that could co-sign its own rows would make the human
floor self-defeating. When the floor is green, the engine's detail string
names its source: `human-logged` (a human logged the row directly) vs
`attested-auto` (a pipeline row a human co-signed) — surface that
distinction, don't flatten it.

## Rendering format

Show this after EVERY evidence write and at the end of every session:

```
research → planned gate
  [✓] market page 5/5        [✗] econ page 3/5 (missing: unit_economics, cases)
  [✗] top assumptions 1/3 resolved (denominator = min(3, assumption count))
  [✓] conversations 5.5/5 · confirmed 5.5/4 · institutions 10/3 · human floor ✓ (attested-auto)
  [✗] demand signals 1.5/2 · human floor 0/1
  [✓] sized both ways (top-down 1.4M / bottom-up 900K)
  [✗] rubric: evidence_strength still low confidence
Next cheapest unlock: …
```

Weighted counts render fractional as-is (`5.5/5`, never rounded). The human
floor renders `human floor ✓ (human-logged)` / `✓ (attested-auto)` when met,
`human floor 0/1` when not — mirror the engine's own detail strings.

Always close with the single next-cheapest unlock, tied to the riskiest
unresolved assumption — not just the check that happens to be closest to
green. A cheap unlock on a low-stakes check is a worse recommendation than a
harder unlock on the assumption that would collapse the most of the model if
wrong. One exception is genuinely cheap AND load-bearing: when a red human
floor is the blocker, the unlock is one owner attestation on the strongest
auto row — say so explicitly, naming the row.

## `staleAssumptions`

Every `update_section` response includes `staleAssumptions` — assumptions
anchored to that field via `source_field_key`. Rewriting a section can leave
its assumptions validated against text that no longer exists underneath
them. Re-interrogate any assumption listed there, and say so out loud
(heartbeat) — this is engine-provided; consume it, never skip it silently.
