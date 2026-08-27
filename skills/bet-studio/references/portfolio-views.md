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
bet-shaped, now owned by a squad or one named person.

**Where the per-row fields actually come from — read this before rendering.**
The two calls above return bet rows and squad metadata. They do NOT return
`assigneeLabel`, `workStatus` (todo | active | done | dropped), `open`, or the
hand-down rationale: those live only in `get_bet`'s `handoffs` array (newest
first). So the "name the squad or person and the work status" rule below, and
the stale-`todo` flag, cannot be satisfied by recipe 2b's calls alone.

**The bounded drill-in.** Call `get_bet` once per handed-down bet, and only
for this cohort. That is not the N+1 the skill forbids: the ban is on looping
`get_bet` over the whole portfolio, and handed-down is a small terminal
cohort — typically a handful, and it only grows when an owner deliberately
hands something down.

- **≤ 10 handed-down bets** → drill in on each and render the full row.
- **More than 10** → drill in on the first 10 **in the order `list_bets`
  returned them**, and say which order that was. It is `rank_score` desc, the
  same as every other listing. It is **not** hand-off recency: the only
  timestamp for a hand-down lives inside `get_bet`'s `handoffs`, so "the 10
  most recent" cannot be selected without already having fetched all of them.
  Render the remainder name-only with a plain line — "+7 more handed down,
  assignee and status not fetched (top 10 by rank, not by recency)". Never
  render a row with an invented or blank assignee as though it were known,
  and never describe a rank-ordered slice as the newest.
- **No `STRATEGY_MCP_TOKEN` / `get_bet` unavailable** → render the cohort
  name-only and say the work status could not be read. A handed-down bet with
  an unknown assignee is still worth showing; a silent blank is not.

When the engine grows a bulk hand-off endpoint, replace the drill-in with it
and delete this note.

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
