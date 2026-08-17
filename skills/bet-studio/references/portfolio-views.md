# Portfolio views — tool-call recipes and rendering rules

Used by `bet-studio` step 2 (show the live portfolio) and by the interim
portfolio-review guidance. All calls are read-only, no confirmation needed.

## Recipe 1 — active bets, stack-ranked

```
get_stack_rank()   // no args
```

Returns every `status: "active"` bet, ordered by cached `rank_score` (0–100)
descending, with `ownerPerson` resolved (name + photo) on each row. This is
the primary listing — it already carries the ranking; don't re-sort it.

## Recipe 2 — the graveyard (parked / killed)

`get_stack_rank` only returns active bets, so the graveyard needs a separate
call:

```
list_bets({ status: "parked" })
list_bets({ status: "killed" })
```

(Two calls, not one `list_bets({})` — filtering client-side after a single
unfiltered call also works and costs the same round trip either way; either
is fine. `list_bets` takes `stage?` and `status?`, both optional, and returns
the same bet rows ordered by `rank_score` desc.)

**`handed_off` is NOT part of this recipe.** It is a fourth status and a
different story — see recipe 2b. Never fold it in here.

## Recipe 2b — handed down (squad work, not bets)

```
list_bets({ status: "handed_off" })
list_squads()                        // charter, roster, open load
```

Bets that left the board as WORK, not as losses: good ideas that weren't
bet-shaped, now owned by a squad or one named person. `get_bet` carries the
`handoffs` array (newest first) with each one's `assigneeLabel`, `workStatus`
(todo | active | done | dropped), `open` flag, and the rationale for why it
wasn't bet-shaped.

## Recipe 3 — taxonomy labels

```
list_taxonomy()   // no args
```

Returns `{ markets, segments, buyers }`. Bet rows carry `market_id` /
`segment_id` / `buyer_id` (uuids), not names — call this once per portfolio
view and build an id→name lookup so bets can render as human-readable chips
("Community College · Career Services") instead of raw ids.

## Recipe 4 — bet detail for hand-off

```
get_bet({ bet_id })
```

Full memo: bet row, all canvas + 5 memo-page sections, assumption chain,
evidence, per-criterion scores, experiments, latest status updates, stage
events, recent revisions. Called once, on the single bet chosen for hand-off
(step 4) — never in a loop over the whole portfolio; that's an N+1 pattern
this skill doesn't need.

## Rendering rules

**Group by stage cohort, in lifecycle order:** idea → research → planned →
live → running → scaling. Within each cohort, preserve the `rank_score`
ordering `get_stack_rank` already returned — don't re-rank across cohorts.

**Confidence beside rank — read it off the row.** Both `get_stack_rank` and
`list_bets` rows carry `confidence`: the server-computed aggregate — the
MINIMUM confidence across the latest score per rubric criterion — `low` /
`medium` / `high`, or `null` until all 5 criteria are scored. Render it
plainly next to the rank — e.g. `#2 · rank 74 · confidence: low` — and
render `null` as `unscored`. Never infer confidence from stage; the field is
authoritative (a rank is only as trustworthy as its least-confident
variable — 4×high + 1×low reads "low" by design). For per-criterion
confidence and notes on one bet, drill in with `get_bet` (recipe 4).

**Fallback (pre-engine-PR-#5 deployments only):** if a row has no
`confidence` field at all (not even `null`), the engine predates the
aggregate — render `—` rather than guessing from stage.

**Handed down before the graveyard, and NOT collapsed into it.** Handed-down
bets (recipe 2b) render after the active cohorts under their own "Handed
down" heading, each row naming the squad or person who has it and the work
status. Never list them under "Graveyard" and never count them in a kill
rate: nobody stopped believing in these, and a builder scanning the board
should be able to see at a glance that work is out there happening. If a
hand-down's `workStatus` is still `todo` months later, that's worth saying
out loud — the point of the tracking is to catch spun-out work that never
landed.

**Graveyard last, collapsed.** Parked and killed bets (recipe 2) render after
every active cohort AND after the handed-down section, under a single
"Graveyard" heading, collapsed to name + stage-at-exit + status by default —
expand only if asked. Killed bets keep their full history in the engine; this
view doesn't need to surface it unless the builder asks.

**Owner faces.** `get_stack_rank`'s `ownerPerson` is the only recipe here that
resolves a face — use it for the active cohorts. The graveyard listing
(`list_bets`) returns the raw `owner` email only; that's fine for a collapsed
view.
