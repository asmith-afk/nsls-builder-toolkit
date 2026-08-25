# Economics model — hardening the first-cut into the board memo

Used by `bet-plan` Step P1. `bet-research` already drafted all five `econ.*`
fields to honest-estimate completeness (the research→planned gate requires
non-empty `content_md` on all five). This reference is how `bet-plan` turns
that first cut into the model a board would actually read — sharper numbers,
named assumptions, three honestly-differentiated cases.

> **Scope — this document describes the `material` band only.** Step P0 sets
> `rigor_band` before any `econ.*` write. On a `small` band bet, the required
> output is a unit-economic sketch and a stated breakeven, and the three-case
> `data` shape below is explicitly NOT required — building it from invented
> drivers is the failure P0 exists to prevent, not compliance with this page.
> Two sections still apply to BOTH bands: **Named-assumption discipline** and
> **Reuse the research** — a cheap bet may carry fewer numbers, but every
> number it does carry still names its assumption and still starts from
> `market.obtainable` rather than a second market size invented here. The
> honest-tagging rule in *Case honesty rules* applies to both bands too.

## Named-assumption discipline

Every number in the model carries the assumption that produces it, inline —
in the sentence, not in a footnote three paragraphs down:

> "$40K ARR/school **assuming** $8K/yr price × 5 pilots convert."

A number without a named assumption attached is an opinion wearing a suit.
If a driver in `econ.model_2026_2028` or `econ.cases` can't be traced back to
a stated assumption, it isn't ready to write down yet — go name the
assumption first.

Every load-bearing model assumption surfaced this way also lands in
`strategy_assumptions` via `upsert_assumption`, tagged `risk_type: "market"`
or `risk_type: "customer"` (economics assumptions are rarely `technical`).
Don't let a new pricing or conversion assumption live only inside prose —
if the model breaks when it's wrong, it belongs in the assumption chain
where the rest of the bet's risk lives.

## Reuse the research — never invent a second market size

The revenue funnel STARTS from `market.obtainable`'s `data.top_down` and
`data.bottom_up` — obtainable-revenue dollar figures `bet-research` already
sized both ways (not raw institution/enrollment counts).
`bet-plan` does not re-derive market size from scratch; it builds the
revenue model on top of what's already there.

If the economics model needs a different top-line number than research
produced — the obtainable market doesn't support the case being built — say
so plainly. **That's a finding, not a footnote.** Either the model reflects
the research number (even if it's less flattering), or the divergence is
named out loud with the assumption driving it, the same way `bet-research`
names a top-down/bottom-up divergence.

## The 2026–2028 model (`econ.model_2026_2028`)

Per year (2026, 2027, 2028): revenue, costs, margin, and the 2–4 drivers that
move each year most (price, conversion rate, reachable institutions, cost to
serve, headcount — whichever actually drive this bet). Write it two ways in
the same `update_section` call:

- `content_md` — a table (year rows, revenue/costs/margin/drivers columns)
  plus the prose naming each driver's assumption.
- `data` — the same numbers, structured, so the engine and any future UI can
  read them without re-parsing prose.

## Three cases (`econ.cases`)

Canonical `data` shape — `content_md` carries the narrative, `data` carries
the numbers a dashboard would chart:

```json
{
  "cases": {
    "downside": {
      "2026": { "revenue": 0, "costs": 120000 },
      "2027": { "revenue": 40000, "costs": 150000 },
      "2028": { "revenue": 90000, "costs": 160000 },
      "assumptions": ["2 pilots, neither converts to multi-year", "..."]
    },
    "base": {
      "2026": { "revenue": 24000, "costs": 120000 },
      "2027": { "revenue": 160000, "costs": 180000 },
      "2028": { "revenue": 400000, "costs": 220000 },
      "assumptions": ["..."]
    },
    "upside": {
      "2026": { "revenue": 40000, "costs": 120000 },
      "2027": { "revenue": 320000, "costs": 200000 },
      "2028": { "revenue": 900000, "costs": 260000 },
      "assumptions": ["..."]
    }
  }
}
```

### Case honesty rules

- **Downside is not "base minus 20%."** Multiplying the base case down is
  decoration, not analysis. The downside case is the world where the
  riskiest still-unresolved assumption turns out to be wrong — trace it back
  to a specific `strategy_assumptions` row, not a percentage haircut. The
  downside case IS what `proof.threshold_stop` protects against — if the
  downside numbers and the stop threshold don't connect, one of them is
  wrong.
- **Upside must name what breaks in our favor** — a faster sales cycle, a
  second segment opening up, a competitor exiting — not just "multiply the
  base case by 2." If nothing specific would have to go right to reach the
  upside numbers, they're not an upside case, they're wishful arithmetic.
- **Tag the whole page honestly.** `estimate` is the default tag for the
  model; use `assumption` for any case whose driver is still genuinely
  untested. Reserve `data` only for costs NSLS actually pays today (current
  headcount cost, current tooling spend) — never for projected revenue.

## Unit economics (`econ.unit_economics`)

Per unit (per school, per seat, per pilot — whatever this bet's unit is):
price, cost to serve, payback period. For B2B bets specifically, name the
sales cost reality of the channel — rep time is not free. A warm-channel
sale that "costs nothing" because a rep already had the relationship still
consumes hours that could have gone to another account; price that time in,
even roughly, rather than treating warm-channel selling as economically free.
