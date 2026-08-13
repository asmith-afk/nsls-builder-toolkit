# Self-serve research — the five dimensions

Used by `bet-research` Step R2. Five things a bet needs answered before it
can honestly claim readiness for the planned gate. All five are answerable
in-house, wherever NSLS's own data can carry the weight — work them in the
order the assumption agenda demands (riskiest first), not the order below.

## 1. Competition

Competition research is **company-scoped, not bet-scoped**. Every finding
lands on a competitor page that any other bet can read, and the bet keeps only
its own synthesis. Research done here for one bet must not be work the next
bet has to redo.

### Read before you research

`list_competitors` first — it returns each company's **`key`**, and that key
(or the row's id) is what `get_competitor` accepts. It does NOT accept a display
name: `get_competitor("PathwayU")` returns `competitor not found`, because the
stored key is `pathwayu`. Take the key from the listing rather than guessing it
from the name. (The WRITE tools are the opposite — `competitor_name` and
`competitor_homepage` are exactly how you tag a company you have not looked up.)

Then `get_competitor(<key or id>)` for anything already tracked. Each page
reports computed `freshness`:

- **`fresh`** — the shared memo is done. Do NOT re-derive what a colleague
  already established; cite the existing evidence rows instead. But freshness
  is a property of the **company page, not of your bet**, and the two halves
  behave differently:
  - **Step 4 (stance) is always yours to write** — a stance is per-bet by
    definition, so a fresh page has none for the bet in hand. Same for the
    bet's own `market.alternatives` synthesis.
  - **Step 3 (coverage) is shared, and gated on the JOB, not on your bet** —
    a claim another bet's research already made still stands. Run it for the
    jobs THIS bet delivers that carry no claim yet; the grid's `unassessed`
    cells are that worklist.

  A fresh page you only read leaves the bet's competition view empty — which
  looks identical to having no competitors.
- **`stale`** (>180 days) or **`never`** — the page needs work. A `never`
  page is a stub that grew out of someone's evidence tagging and has no memo
  yet; that is the normal starting state, not a defect.
- Re-verified a stale page and nothing changed? `mark_competitor_reviewed`
  with a note saying what you checked. That is the only write besides a
  section edit that clears the stale badge, so use it honestly.

Also pull `get_competition_grid(side: "b2b" | "b2c")` — it shows which jobs
already have coverage claims and which have none, so the sweep spends its time
on genuinely unassessed cells.

### Per company

Identify it by `competitor_homepage` wherever you have a URL — the domain
outranks the name when matching, so a company that spells itself three ways
still resolves to one page. Then:

1. **Log each substantive finding as evidence, tagged to the company:**
   ```
   log_evidence(kind: "competitor", competitor_name: "Handshake",
                competitor_homepage: "joinhandshake.com",
                link: <source URL>, evidence_tag: "data"|"estimate")
   ```
   Works for ANY kind — competitive intel arrives in interviews at least as
   often as in `competitor`-kind rows, so tag those too. The row appears on
   both the bet and the company page from one record; never log it twice.

   If the result carries `created_stub: true`, **say so out loud** — you just
   created a company page, and the owner should know a new entity exists.

   Already-logged rows that turn out to be about a company get
   `tag_evidence_competitor` — an in-place update, not a second row.

2. **Write the five memo sections** with `update_competitor_section`:
   `competitor.business_model`, `competitor.pricing`,
   `competitor.entrenchment` (including reach — how hard they are to
   displace), `competitor.weaknesses`, `competitor.our_angle`. Same tag
   discipline as any section: `estimate` by default, `data` only with the
   source cited in the content itself. These writes refresh the page's
   last-reviewed date, because editing what we believe about a company IS
   reviewing it.

3. **Claim job coverage** with `map_competitor_job` — `owns` / `partial` /
   `absent`, per job.

   > **Record `absent` explicitly — but only when you have actually looked.**
   > `absent` is an assessment ("we looked, they do not serve this"), and it is
   > the ONLY thing that turns a cell into verified open water. Skipping it
   > leaves the cell `unassessed`, which the grid renders as ignorance rather
   > than opportunity — deliberately. A competition sweep that logs only what
   > competitors DO cover manufactures blank space nobody can act on.

   **What counts as having looked.** `absent` requires a source that would
   have mentioned the feature if it existed:

   | Source | Good enough for `absent`? |
   |---|---|
   | Support / help centre, developer docs, release notes, changelog | **Yes** |
   | The product itself (trial, licence, demo) | **Yes** — the strongest |
   | Third-party review sites with feature matrices | Weak yes; corroborate |
   | Marketing site, product page, pricing page | **No** |
   | "I searched and found nothing" | **No** — say where you searched |

   **Marketing pages are not feature inventories.** They sell a positioning,
   and they omit table-stakes features precisely *because* those features are
   unremarkable. Silence there is evidence of nothing. This is not
   hypothetical: on 2026-08-13 a competitor sweep graded three companies
   `absent` on job alerting from marketing-page silence and reported alerting
   as the market's open water. Two of the three documented the feature plainly
   in their help centres — Handshake's saved-search alerts and 12twenty's
   Daily/Weekly email alerts — and the conclusion had to be retracted the same
   day, after it had already been used to argue a bet's differentiation.

   **When marketing pages are all you have, leave the cell `unassessed` and
   say so out loud.** That is the correct, honest state — not a failure to
   finish. The pressure in this recipe is to record the negative; it is not to
   invent one. `unassessed` costs the grid nothing, and a wrong `absent` costs
   it credibility on every other cell.

   **In the claim note, name every surface you checked.** "No alerting on the
   product page or the help centre; also checked release notes and the API
   docs" is a claim the next researcher can weigh and challenge. "Absent" on
   its own is not. A negative claim whose note does not say where you looked
   should be treated as `unassessed` by whoever reads it next.

   **Positive claims from marketing copy establish existence, never quality.**
   "They ship fit-based ranking" is fair from a product page; "their ranking
   is weak" is not. Grade the feature's presence, and put the untested quality
   question in the note as the thing to test.

   Omit `segment_id`/`buyer_id` to claim all buyers; narrow to a buyer when
   the answer differs by side. Claims default to `hypothesis` — leave them
   there until something validates them.

4. **State the stance** with `link_competitor_bet`: `head-on` / `flank` /
   `not-competing` / `watching`, plus a note saying HOW we compete or why we
   don't. Pass `payer_type` when the two sides of the market differ — a
   company can be head-on for the institution's budget and not-competing on
   the student experience of the same bet. One stance cannot say that.

**The status quo is competitor zero** and it already exists as a page —
"keep doing the workaround" is a real competitor and usually the toughest.
Assess it like any other: a blue-ocean read that skips it is a lie. Where the
grid flags a job with no status-quo call, that flag is pointed at you.

### The bet's own layer

`market.alternatives` stays the **per-bet synthesis**: what this competitive
picture means for THIS bet's positioning and which assumption it resolves.
Point at the company pages; do not paste their dossiers back into it. Same
tag rule as before — `estimate` by default, `data` only with sources cited in
the content.

## 2. Market size, both directions — both in dollars

Both `top_down` and `bottom_up` MUST be obtainable-revenue dollar figures —
never raw institution/enrollment counts. The two numbers only mean anything
side by side if they share units; a count next to a revenue figure produces a
divergence ratio that's pure noise.

**Top-down:** `size_segment(filter)` returns `institutionCount`,
`totalEnrollment`, `relationshipCounts` — the outside-in counts. Those raw
counts are the evidence-row payload (see the `log_evidence` call below), NOT
what goes into `data.top_down`. Convert to revenue before it lands in
`market.obtainable`:

```
top_down = institutions_in_segment × annual_price × stated_capture_assumption
```

`stated_capture_assumption` is a NAMED assumption (e.g. "we could realistically
land 15% of this segment within 3 years") — it's what turns the raw
`size_segment` count into an obtainable-revenue read, and it's exactly the
kind of number that belongs in `strategy_assumptions`, not buried in prose.

**Bottom-up:** composed by this skill — **never by the engine.**

```
bottom_up = reachable_institutions × expected_conversion × annual_price
```

Every factor is a NAMED assumption. Each one that's load-bearing also lands
in `strategy_assumptions` — a bottom-up estimate resting on an unrecorded
conversion-rate guess is a leap of faith wearing a spreadsheet.

Write the result:
```
update_section("market.obtainable",
  content_md: <narrative with named assumptions>,
  data: { top_down: <dollar number>, bottom_up: <dollar number>, divergence_note: "<why they differ>" },
  evidence_tag: "estimate")
```

The gate checks `typeof data.top_down === "number" && typeof data.bottom_up
=== "number"` — both fields must literally be numbers, not strings, not
ranges, and both denominated in dollars.

**Divergence flag:** if the two directions differ by more than roughly 3×,
say so out loud and name which single assumption is driving the gap (usually
`stated_capture_assumption`, `expected_conversion`, or the reachable-
institutions count). A silent 5× divergence buried in prose is a red flag,
not a nuance.

Log the sizing pull itself — raw counts and enrollment live here, in the
evidence row's `data`, never inside `market.obtainable`'s `data.top_down`:
```
log_evidence(kind: "market_query", data: { filter, result }, evidence_tag: "data")
```

## 3. Our reach inside the market

`size_segment` gives the relationship rollup; `target_shortlist(filter,
buyer_title_buckets: <buyer's title_taxonomy_keys>, limit)` turns it into a
ranked outreach list — relationship counts, stakeholder coverage against the
bet's buyer title, member counts.

Write to `market.current_data` with `evidence_tag: "data"` — this IS our own
data, not an estimate.

Offer `save_targets` with per-entity reasons, **confirming with the owner
first** — it names real schools onto a rep-visible list, shared-systems
tier. For warm B2B bets, the saved shortlist doubles as the roadshow/rep call
list feeding Step R3 and R4.

## 4. Time to revenue

Months to first dollar, estimated with named assumptions: sales cycle length
for this buyer, procurement reality (RFP? single signature? committee?),
pilot-to-paid lag. Lands in `econ.revenue_drivers` content and feeds the
`time_to_revenue` rubric note directly — cite the same named assumptions in
both places rather than re-deriving the number twice.

## 5. Build-to-value risk

What has to exist before the value is even provable — in weeks and dollars.
Lands in `econ.cost_structure` content and the `build_to_value_risk` rubric
note. For internal-origin bets this is usually already low — say so plainly
and cite the internal system that already proves it works, rather than
re-estimating from zero.

## The `econ.*` first-draft rule

`bet-research` drafts **all five** `econ.*` fields to honest-estimate
completeness — `revenue_drivers`, `cost_structure`, `unit_economics`,
`model_2026_2028`, `cases` (the last two as clearly-labeled first-cut
estimates) — because the research→planned gate requires the econ page
non-empty. `bet-plan` hardens these into the full named-assumption model
later; this skill's job is an honest first draft, not a placeholder.

**Never leave an econ field empty "for bet-plan."** The gate checks for
non-empty `content_md` on all 5 `econ.*` keys — an empty field blocks the
gate regardless of intent to fill it later.

## `market.interviews` and `market.evidence_level`

- `market.interviews` — the rolling synthesis of Customer Forces Stories,
  updated after each logged conversation (Step R3). Not a re-paste of every
  story; a running synthesis of what they add up to.
- `market.evidence_level` — one honest paragraph on where the evidence
  stands, written in evidence-tag language: what's `data`, what's still
  `assumption` or `estimate`, and what would need to change to move a claim
  up a tag.
