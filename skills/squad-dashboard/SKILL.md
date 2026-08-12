---
name: squad-dashboard
description: >-
  Use when a squad wants its own outcome / SLT / status dashboard — a
  filterable web page of their KPIs, campaigns, workstreams, experiments, or
  metrics, deployed to Netlify. Use to stand one up from scratch, refresh the
  numbers on an existing one, or edit its narrative content. Triggers: "build
  our squad's dashboard", "squad dashboard", "outcome dashboard", "SLT update
  page", "our reporting page", "refresh the dashboard", "add a campaign/
  workstream to the dashboard", "/squad-dashboard". Each squad declares its own
  data sources, KPIs, sections, and L3/LOP goals — nothing is hard-coded to one
  team.
---

# squad-dashboard

> **If `gws` fails (403 naming a project other than `nsls-gdocs-skill`, or exit 2):**
> run the doctor — it provisions/repairs the toolkit's own gws profile without touching
> any other tool's files, and computes the right scope union automatically:
> `python3 <plugin>/skills/gws/scripts/gws_doctor.py --services docs,drive,sheets`
> (Windows: use the real Python at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.)
> **The doctor heals its own profile, not your default gws setup** — so after
> `DOCTOR: HEALTHY`, run this skill's `gws` commands against that profile, chained in
> the SAME shell command (each agent Bash call is a fresh shell):
> `export GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws-profiles/nsls-gdocs-skill; gws …`
> (Windows: `$env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$env:USERPROFILE\.config\gws-profiles\nsls-gdocs-skill"; gws …`)
> Details: `../gws/references/multi-secret-profiles.md`.


## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — reading a squad's `config.json`/`content.json`, reading source data
   (Google Sheets via gws, PostHog, HubSpot, Hex, Slack), reading presets and patterns.
2. **Configuration** — writing `config.json`/`content.json`, building/editing `index.html`,
   staging the publish dir. Explain what changes and where. **Never write a `human`-owned
   field (narratives, statuses, judgment classifications) on the squad's behalf — that's theirs.**
3. **Publish / external** — deploying to Netlify (live site), optional SSO gating (registers an
   OIDC client; tier-3, handed off — see `/nsls-auth`). Always preview and get "publish it?"
   before the first deploy. **Confirm every number before it goes live** (pull-and-confirm gate).
   **Never auto-publish on a schedule** — scheduled refresh prepares a draft and notifies; a human confirms.

## Purpose

Lets any NSLS squad get the enrollment Test Outcomes gallery's craft and reliability for its
*own* work — without an engineer building a bespoke page per team. The squad declares what it
tracks (sources, KPIs, sections, L3 goals) and Claude assembles a clean, filterable,
Netlify-hosted dashboard from confirmed data — while the squad's judgment (the "read",
operational statuses, win/loss calls) stays human-written, never AI-concluded. The intelligence
is in the split: hard numbers are pulled and *confirmed* with provenance; narrative is
*protected*; the page is *reproducible* run to run. It turns "make us a dashboard like
enrollment's" from a week of HTML into a guided conversation.

## How it works (architecture)

Reliability comes from **what Claude builds from**, not from removing Claude as builder. Claude
crafts the HTML (the craft); three things keep it reliable:

- **Section-pattern library** (`sections/section-patterns.html`) + **base shell** (`shell/base.css`)
  — proven, copy-and-adapt blocks. Claude assembles and tailors these, never from a blank page.
- **`config.json`** — the squad's declaration: brand, Netlify site, sources + how to pull each
  metric, ordered section composition, L3/LOP goals, classification schemes, `human`-owned fields.
- **`content.json`** — the data store: pulled-and-confirmed metrics (each with `source` +
  `pulled_at` + the source's own `as_of` when it has one), list items, and human narratives/
  statuses. **A refresh writes only `metrics`; `human` fields change only via the edit flow.**

```
<this skill>/  SKILL.md · sections/section-patterns.html · shell/base.css
               presets/{enrollment,shop}.json · deploy.sh · references/
~/squad-dashboards/<squad>/  config.json · content.json · index.html · assets/
```

Start every squad from the closest **preset** and customize. Presets are example *configs*, not
built-in domain sections — the engine knows only generic primitives.

## Section primitives (generic — nothing names a metric)

Full HTML in `sections/section-patterns.html`. The squad instantiates these with their own data.

| Primitive | What it is | Example instance |
|-----------|-----------|------------------|
| `metric-card` | KPI tile up top: value + chosen comparisons + unit + LOP + optional classification badge | Revenue YTD; FOL rate; ARPM |
| `metric-group` | cluster of related metric cards under a heading | Email block; funnel-stats block |
| `item-list` | repeatable entries: title, date, body, optional result/next-step, metrics, LOP | Campaigns; releases |
| `status-board` | item-list with classification pills | Operational workstreams |
| `narrative` | human-written prose — **always human** | The "read" / exec summary |
| `test-outcomes` | (opt-in) experiment cards: control/variant, exposures, screenshots | Enrollment A/B tests |

**Shared shell:** hero (title, "Updated <date>"), LOP legend (maps each L3 goal to a chip),
optional filter/search (list-heavy sections), brand theme (`nsls`/`society`), responsive CSS,
provenance footer (each metric's source + pulled-at). The human/AI split is **ingestion
metadata, never a rendered label** — viewers see clean content.

## Choosing a meaningful composition (information hierarchy)

Help the squad tell their story, don't just list blocks. Order top→bottom by what an SLT reader
needs first:
1. **Headline KPIs** (2–4 `metric-card`s) — the numbers that define success, each tied to an L3.
2. **Supporting metrics** (`metric-group`) — context behind the headline.
3. **What we did** (`item-list`) — campaigns/releases that moved the numbers.
4. **Operational status** (`status-board`) — what's in flight / at risk.
5. **The read** (`narrative`) — the squad's human interpretation.
Resist sprawl: more than ~6 sections or >4 headline KPIs buries the signal. Every section ties to
an L3 goal or it probably doesn't belong.

## Classification schemes (optional, per-type vocabulary)

The squad defines schemes whose vocabulary fits the *type*: experiments → Won/Lost/Mixed;
metric-vs-goal → Exceeded/Met/Missed (or Ahead/On-track/Behind); campaigns →
Overperformed/In-line/Underperformed; launches → Shipped/Delayed/Blocked. Any item/KPI can carry
a status → color badge; none → no badge.
- **Objective (metric vs a numeric goal)** → auto-derive from the math, human-overridable.
- **Judgment (Won/Lost, campaign success)** → human-set.
- **The narrative read is always human — never AI-concluded.** A human field may hold a neutral
  placeholder ("Pending squad review") that asserts no winner/loser/cause — but never an
  AI-authored interpretation dressed up as a placeholder.

## Prerequisites (check FIRST — don't start a build you can't finish)

A squad member needs three things before their first build. Surface these up front:
- **NSLS Netlify team access** — the dashboard deploys to the shared **NSLS Netlify team**
  (account slug `kprentiss-ryj1oi0`). **Contact Kevin to be added to the NSLS Netlify team**,
  then run `! netlify login`. Without access, the deploy step can't create or publish the site.
- **Connectors for their data sources** — if a declared source's tools aren't available
  (Sheets/`gws`, PostHog, HubSpot, Slack…), run `/connect`. A source with no connector
  (Looker/Tableau/Snowflake/vendor dashboard) uses the export-to-Sheet or `manual` fallback.
- **`gws`** set up for Google Sheets reads (see `/gws`).

If any are missing, resolve them first — flag it to the squad rather than starting and stalling.

## Setup interview (the question script)

Ask ONE topic at a time, conversationally. Offer the closest preset first ("Shop-style metrics
+ ops, or enrollment-style experiments, or from scratch?"). Then walk:
1. **"What does success look like for your squad this quarter?"** → their L3/LOP goals (capture id + label).
2. **"What are the 2–4 numbers you'd put at the very top?"** → headline KPIs. For each: the metric, its unit, and what to compare against (prior period / target-or-budget / YoY).
3. **"Where does each of those numbers live, and can you give me the link?"** → sources. For each, immediately do a **reachability check** (below) before trusting it.
4. **"Beyond the headline numbers, what else should this page show?"** → supporting metrics, campaigns/releases, operational workstreams.
5. **"What part is your judgment to write — not something I should conclude?"** → mark `human` (almost always the read + operational statuses + win/loss calls).
6. **"How will people classify outcomes here?"** → classification schemes that fit their work.
Then: pull + confirm → capture human content → build → preview → "happy?" → deploy.

## Data infrastructure: making any squad's data work

Squads differ wildly here. Handle it explicitly — this is where reliability is won or lost.

**Reachability check (do this during setup, per source).** Actually read the source once before
relying on it. Three outcomes:
- ✅ Reachable + clean → declare the pull.
- ⚠️ Reachable but messy (merged cells, shifting layout) → use a **label-anchored or named-range**
  pull, never brittle coordinates (see below).
- ❌ Not reachable (no connector — Looker/Tableau/Metabase/Snowflake/a vendor dashboard; or no
  access) → **fallback:** ask the squad to export the figures into a Google Sheet tab the skill
  *can* read, OR set the metric `source: "manual"` and have them paste the number each cycle.
  Don't pretend a source is wired when it isn't.

**Anchor sheet pulls to labels, not coordinates.** `Weekly Squad Reporting!B9` breaks the moment
a row is inserted. Prefer: read the tab, find the row whose label cell matches "YTD Revenue", take
the adjacent value; or have the squad define a **named range**. Store the anchor (label/named
range) in `config`, resolve to the current cell at pull time. If the label can't be found → fail
loud, keep the last confirmed value.

**Computed/aggregated metrics.** If a number must be derived (e.g. summing sends across
campaigns), prefer a pre-computed cell if one exists. If you must compute: show the inputs AND the
arithmetic to the squad and get confirmation. Never publish an averaged-percentage or a sum the
squad hasn't seen. Don't average percentages that have different denominators.

**Source staleness.** Capture the source's own as-of date (e.g. the sheet's "day of month" /
"report date") as `as_of` in `content.json` and show it. If `as_of` is older than the refresh
date, flag it: "the source itself is N days stale — refresh it first?"

Per-source pull recipes (gws Sheets, PostHog, HubSpot, Hex-via-Slack-bridge, Slack, manual):
`references/data-sources.md`.

## Mode 1 — Setup
Interview (script above) → write `config.json` → **first pull + confirm** (pull each declared
metric, show the numbers + provenance, get confirmation, write `content.json`) → capture human
content → build `index.html` from config + content + patterns → preview → run the **pre-publish
checklist** → "happy?" → deploy walkthrough.

## Mode 2 — Refresh
Load config → re-pull declared metrics → show a **before/after diff** (and any staleness/anchor
failures) → on confirm, update **only** `metrics`. Human narratives + items untouched.
**Edit the new values into the EXISTING `index.html` in place — do NOT regenerate the page from
scratch** (regenerating risks silent restyling/drift). Only re-render a section if its
*composition* changed in `config`. Then redeploy → verify.

## Mode 3 — Edit
The squad updates campaigns / statuses / the read conversationally → write **only** `human`
fields → rebuild → redeploy. The only path that writes human text.

## Deploy walkthrough
1. Netlify auth → if needed: "run `! netlify login`" (NSLS team).
2. Create the site on the **NSLS** team (slug `kprentiss-ryj1oi0`), named from the squad; save `site_id` to config.
3. **Deploy via `deploy.sh <squad-dir>`** — stages a clean publish dir, deploys with **`--no-build`**
   (fresh NSLS-team sites auto-assign a `hugo` build command that otherwise fails the deploy), and
   verifies the SSO gate if the site is gated. Verify load + content-types.
4. Hand back the URL.
5. Offer optional "Sign in with NSLS" gating (`/nsls-auth`; tier-3 client registration handed to
   People-Ops). Optional, not default.

## Pre-publish quality checklist
Before the first publish (and worth re-checking on big changes):
- [ ] Every headline KPI confirmed by the squad, with `source` + `pulled_at` recorded.
- [ ] Every section ties to an L3/LOP goal (or is intentionally an exception).
- [ ] Human fields (read, statuses) filled by the squad — or intentionally left blank, not AI-filled.
- [ ] No brittle coordinate pulls; anchors resolve; no unconfirmed computed numbers.
- [ ] Source `as_of` shown; no silent staleness.
- [ ] Run **`/ux-audit`** on the previewed page — brand/a11y/clarity pass before it goes to SLT.
  Required on first publish and whenever the **composition or narrative** changes. A numbers-only
  in-place refresh (Mode 2) of an already-audited page does not need a full re-audit.

## Refresh cadence (for squads that update regularly)
Most squads refresh weekly/monthly. **Do not auto-publish** — refresh needs the pull-and-confirm
human gate. Recommended patterns, best first:
- **`/schedule` (recommended)** — a cron remote agent runs even when the member is away. Schedule a
  **refresh-prep**: re-pull metrics, build a draft, and **notify the member (Slack DM / email) to
  review, confirm, and publish.** It prepares; the human publishes. E.g. "every Monday 8am ET,
  pull the Shop numbers and DM me the diff to confirm." Set it up with `/schedule`.
- **Calendar reminder** — lighter: a recurring Google Calendar event "Refresh <squad> dashboard
  (`/squad-dashboard refresh`)". No automation; pure nudge.
- **`/loop`** — only for *active, same-session* polling (e.g. waiting on a deploy). Not for a
  multi-day cadence; it doesn't fit weekly refresh.
Whichever: the publish step always has a human confirming the numbers.

## Reliability guarantees
- **Pull-and-confirm gate** — no number ships unconfirmed; provenance in the footer.
- **Fail loud** — broken pull / missing anchor / unfound label → flag it, keep the last confirmed
  value, never blank/wrong/fabricated.
- **Human text is sacred** — written only in setup/edit, never by refresh, never AI-concluded.
- **No layout drift** — refresh edits values into the existing `index.html` in place; the page is
  only regenerated when the squad changes the composition in `config`.
- **No silent staleness** — surface the source's as-of date; flag drift.

## Diagnostic Loop
TRY → OBSERVE → DIAGNOSE → ADAPT → TRY AGAIN.

| Symptom | First thing to check |
|---|---|
| First Netlify deploy fails (`hugo: command not found`) | Fresh NSLS-team sites auto-assign a `hugo` build cmd. Deploy with `--no-build` (deploy.sh does). |
| A pulled number is wrong/zero | The coordinate moved (row inserted, tab renamed). Switch to a label-anchored pull; never publish the bad value. |
| gws read has a `Using keyring backend:` line before JSON | Slice from the first `{` before JSON.parse. |
| Source can't be reached (Looker/Tableau/Snowflake/vendor) | No connector. Fallback: export to a readable Sheet, or `source: "manual"` + paste. Don't fake the wiring. |
| Hex won't pull | Hex MCP blocked → Slack bridge (slow), or prefer a mirroring source (e.g. the Sheet). Declare precedence in config. |
| Numbers look current but feel off | Check the source's own `as_of` — the source may be stale. Flag, don't publish silently. |
| Deploy ok but page 404s briefly | CDN propagation. Wait ~5s, re-check. |
| Refresh overwrote a narrative | Bug — refresh touches only `metrics`. `human` is off-limits. |
| (Gated) a deploy removed the login | Edge functions didn't bundle. Deploy from the repo root; deploy.sh verifies. |

## Service awareness
Connections missing → `/connect`. Cross-system data questions → `/data-intel`. Source depth →
`/posthog` `/hubspot` `/airtable` `/slack` `/gws`. Quality gate → `/ux-audit`. Recurring refresh →
`/schedule` (not auto-publish). Optional SSO → `/nsls-auth`. This skill owns *assembling and
deploying a squad's dashboard*, not the analytics behind it.

## Rationalization table (do not talk past these)

| Excuse | Reality |
|---|---|
| "The numbers I pulled look right, I'll publish." | Pull-and-confirm is the promise. Show the squad; confirm; then publish. |
| "The read's empty — I'll write a sharp line." | The read is `human`. Leave a prompt; never AI-conclude it. |
| "This squad needs the same sections as Shop." | Each squad declares its own. Interview; start from a preset; don't assume. |
| "A1 coordinates are simpler than label anchors." | Coordinates break on the next row insert and publish wrong numbers. Anchor to labels/named ranges. |
| "I'll just compute the aggregate and publish it." | Show the inputs + arithmetic and confirm. Never average percentages across different denominators. |
| "The source is probably current." | Check its `as_of`. Flag staleness; don't publish old numbers as new. |
| "I'll deploy from /tmp like a static site." | Gated sites lose the gate; even ungated, the first deploy fails on auto-hugo. Use deploy.sh. |
| "I'll schedule it to refresh and publish automatically." | Scheduled refresh prepares a draft + notifies; a human confirms + publishes. Never auto-publish. |
| "I'll label which parts are human vs AI." | That's config metadata, not a viewer label. Clean content only. |
| "Their data's in Tableau, I'll approximate." | No connector = export-to-Sheet or manual paste. Never approximate a number. |

## Red Flags — STOP
- Publishing a metric the squad hasn't confirmed.
- Writing into a `human` field (narrative, status, judgment call).
- Assuming a squad's sections/KPIs instead of interviewing.
- Pulling by brittle coordinate instead of a label/named-range anchor.
- Publishing a computed/aggregated number the squad hasn't seen.
- Scheduling a refresh that auto-publishes without a human confirm.
- `netlify deploy` by hand instead of deploy.sh.
- Rendering a "human-written"/"AI" label on the page.
- Treating an unreachable source as if it's wired.

## Quick Start
1. `cp presets/<closest>.json ~/squad-dashboards/<squad>/config.json`; customize (brand, sources,
   sections, LOPs, schemes, human flags). Run the reachability check on each source.
2. Pull each declared metric → confirm with the squad (incl. any computed numbers) → write `content.json`.
3. Collect human content (narrative, statuses).
4. Build `index.html`; preview; run the pre-publish checklist (incl. `/ux-audit`).
5. "Happy?" → `deploy.sh` → return URL. Offer `/nsls-auth` gating + a `/schedule` refresh-prep.
