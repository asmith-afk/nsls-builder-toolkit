# HR Handoff Mapping — Doc → Airtable

*The seam between this manager-facing skill (produces a Doc) and HR's load step (writes Airtable). This file makes the Doc a clean parse target so HR isn't re-typing. It is also the artifact to review WITH HR (Jenna) before any card is loaded.*

> ⚠️ **CONFIRM WITH HR BEFORE RELYING ON THIS.** The field IDs below come from the archived v1 write flow (people-ops base `appnXPTu01esWWbrK`). Schema drifts — HR (Jenna) owns this base and had a Q2 launch in July 2026. **Verify every table/field against the live schema before any load, and resolve the "known gaps" section together.** This skill never writes Airtable; loading is HR's separate, HR-only step.

> 📬 **Delivery is automatic as of v2.2.0.** The skill shares every rendered card with **Jenna Fontanez (`jfontanez@nsls.org`) as commenter** at render time, so no card can be orphaned in a manager's Drive. Cards arrive titled `(DRAFT)` while `[brackets]` are unresolved and are retitled `(FINAL)` when the manager confirms alignment is done — so **Gap E below is visible in the title**: only `(FINAL)` cards are loadable. Revise-mode shares carry a change summary and triage verdict in the notification, so the load is a patch rather than a re-key.

## Base

`appnXPTu01esWWbrK` (people-ops) — HR-owned.

## Field-by-field (v1 IDs — verify)

### ScoreCards — `tblJzH5XrhQaPT956`
| Doc element | Field | Field ID |
|---|---|---|
| (link to employee record) | employee | `fldj7em5YOdyDAmrY` |
| Title year (e.g. FY2026) | fiscal_year | `fldTDribP10N5eEED` |
| **Mission** line | role_mission | `fldtr1xK2ozG4Q1yO` |
| The Google Doc URL | doc_url | `fldkmuKkhYZ93Iu7Y` |
| record status | status | `fldFXTmNKtWXes5CJ` |
| Growth Focus — action | growth_focus_action | `fldop1YYkGA18Mf2r` |
| Growth Focus — quarter | growth_focus_quarter | `fldDhxtyPJ8BNBJ2G` |
| Growth Focus — competency (link) | growth_focus_competency | `fldFXRXHKxjQRYjkp` |
| (LOP goals the card aligns to) | linked_lop_goals | `fldWo9ouUXrKmJFaA` |

### Accountabilities (Side A) — `tbls569Ee2AsXXAMy`, one row per accountability
| Doc column | Field | Field ID |
|---|---|---|
| Accountability (bold outcome) | accountability_name | `fldaJdKsKWyWlYF1N` |
| Accountability (detail) | description | `fldaqjt3eICZvB8G4` |
| Weight % | weight_pct | `fldvL9bNlDnJqZpWv` |
| (parent link) | scorecard | `fld35VhjqkK4aq3BC` |
| Pass/Fail "Meets" measure → **see gap A** | target / kpi | `fldT8i0ma3mQfM39K` / `fldBbs08LkrZGxwQI` |
| row status | status | `fld0DdRaJEGn1XI4m` |
| (LOP alignment) | lop_goal_alignment | `fldtzitJrQsgaZOak` |

### Competencies (Side B) — `tbl4gZlf443CM57AL`, one row per competency
| Doc column | Field | Field ID |
|---|---|---|
| Competency | competency_name | `fldgyzYqqOsg8kXGr` |
| Definition | description | `fldoXzKEJe3RjNw5O` |
| MAR / Rating → **see gap B** | rating | `fldlQnqUFkhv7ADzj` |
| (parent link) | scorecard | `fldmb3oPq5o2JD53T` |

## Known gaps — resolve WITH HR (the v2 Doc doesn't map 1:1 to the v1 schema)

These are the real coordination items. Don't paper over them; decide each with Jenna:

- **Gap A — Pass/Fail "Meets" measure.** The v2 Doc frames each accountability with a single binary **Pass/Fail measure** (+ A/B/C). The v1 schema splits this into `kpi` + `target` (and a separate quarterly `Goals` table `tblsjhOjJGE0NZ1mD` with `pass_fail_measure` `fld39dV3RS29MyYdu`). Decide: does the Doc's measure land in `target`, in the `Goals` table, or does HR add a dedicated field?
- **Gap B — Competency rating scale.** v2 uses a **1–4 MAR** (4 Excellent … 1 Weak). The v1 `rating` field used `Strength / Developing / Gap`. These don't map. Decide the canonical scale (v2's 1–4 matches the founder SOP) and whether the field's options need updating.
- **Gap C — Core Values.** v2 renders the 5 values as a **binary Pass / Flag gate**. The v1 write flow did **not** write values at all. HR's live system scores values as binary (per `cpm-constants`). Decide where the Pass/Flag lands (likely a Core Values table / field HR owns) — this skill only *renders* the gate, it computes no comp.
- **Gap D — Portfolio category.** v2 tags each accountability with a 2×2 category (growth / efficiency / hygiene / reliability). The v1 schema has **no field for this.** If HR wants to track/report by category (Kevin does, org-wide), add a `portfolio_category` single-select to Accountabilities. Optional but recommended.
- **Gap E — Brackets.** The Doc ships with `[bracketed]` placeholders that are confirmed in the manager↔report conversation. **HR loads only confirmed values** — a card with live brackets isn't ready to load.

## Keeping the Doc parseable

For the handoff to stay a parse rather than a re-type, the renderer (`build_doc_template.py`) holds these stable:
- Fixed section headings (Mission, Side A, Core Values, Side B, Growth Focus).
- Side A as a table with fixed columns: **# · Accountability · Weight · Pass/Fail Measure**.
- Side B as a table with fixed columns: **Competency · Group · Definition · MAR · Rating**.
- Core Values as a table: **Value · Definition · MAR · Pass/Flag**.

If HR builds a parser/loader against the Doc, these are the anchors. If those columns change, update this file in lockstep.
