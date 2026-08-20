---
name: posthog
description: >-
  Query PostHog analytics, build dashboards, create funnels, look up users,
  investigate errors, manage feature flags, and run HogQL queries. NSLS uses
  one PostHog project for all properties (FOL, Society, Shop, Marketing).
  Includes known gotchas: FunnelsQuery OR group limitation, server-side $host
  null, identity chain breaks, FOL error noise, UTC date math.
  Trigger phrases: posthog, analytics, dashboard, funnel, HogQL, insight,
  event, error tracking, feature flag, experiment, person lookup, user journey,
  who visited, how many users, conversion rate, drop-off, user behavior,
  session replay, session recording, watch recordings, replay vision, scanner,
  why did conversion drop, can't reproduce, screen recording.
---

# PostHog Analytics

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** (queries, lookups, listing) — runs without friction. No approval needed.
2. **Configuration** (creating dashboards, insights, feature flags) — ask permission, explain what will be created and where it will be visible.
3. **Destructive** (deleting insights, dashboards, experiments, feature flags) — never proactively offered. If explicitly requested: explain that deletion is permanent (no recycle bin for insights), confirm which specific item, confirm they understand it cannot be undone, then proceed.

## Purpose

This skill makes PostHog's full analytical power accessible through conversation — not just running queries, but knowing which queries to run, what the results mean in the NSLS context, and what to try next when the data doesn't look right. If PostHog tools aren't available, run `/connect` first. For cross-system intelligence that combines PostHog with Airtable, Slack, Customer.io, and more, use `/data-intel`.

## NSLS PostHog Landscape

One PostHog project (ID: 128379) covers all NSLS properties.

**Connection (current, as of 2026-08-19):** the official PostHog plugin is the supported path — it
bundles the MCP server, ~12 `/posthog:*` commands, and 130 PostHog-authored skills.

```
claude plugin install posthog@claude-plugins-official -s user
```

Then restart Claude Code and run `/mcp` → browser OAuth. **No API key to paste.** Prefer this over a
personal API key: PostHog ships tools fast enough that a static key's scopes go stale within
weeks, while OAuth re-scopes itself.

**Escalation path:** `#posthog-nsls` (C08RCKLTPAS) — PostHog's own staff answer questions directly in
that channel. That is how the `$session_id` diagnosis below was obtained. Use it before guessing.

| Domain | Product |
|--------|---------|
| `app.nsls.org` | FOL (legacy member platform) |
| `members.nsls.org` | Enrollment |
| `oursociety.org` | Society |
| `shop.nsls.org` | Shop |
| `www.nsls.org` | Marketing site |

**Always start by confirming the active project:**
```
mcp__posthog__projects-get
```

When querying for a specific product, filter by the `$host` property. Use `mcp__posthog__switch-project` if you need to change projects.

## Running Queries (HogQL)

`mcp__posthog__query-run` is the workhorse tool. It accepts HogQL — PostHog's SQL dialect.

### Common Query Patterns

**Count events by type (last 7 days):**
```sql
SELECT event, count()
FROM events
WHERE timestamp > now() - interval 7 day
GROUP BY event
ORDER BY count() DESC
```

**User activity timeline:**
```sql
SELECT distinct_id, event, timestamp
FROM events
WHERE person_id = '...'
ORDER BY timestamp
```

**Property analysis by domain:**
```sql
SELECT properties.$host, count()
FROM events
GROUP BY properties.$host
```

**Funnel conversion:** Build a FunnelsQuery JSON with ordered or unordered steps (see Dashboard section below).

### Natural Language to HogQL

Use `mcp__posthog__query-generate-hogql-from-question` to turn a plain English question into HogQL. Useful for complex queries — generate first, then refine the output.

### Date Filtering

- Relative: `timestamp > now() - interval N day`
- Absolute: `timestamp > toDateTime('2026-03-25')`
- Always include `$host` filter when the question is about a specific product.

## Dashboard & Insight Management

### Discovery

1. `mcp__posthog__dashboards-get-all` — list all dashboards
2. `mcp__posthog__dashboard-get` (with ID) — see all insights on a specific dashboard

### Creating & Managing Insights

- `mcp__posthog__insight-create-from-query` — pass a PostHog query JSON (TrendsQuery, FunnelsQuery, RetentionQuery, etc.)
- `mcp__posthog__insight-update` — modify the query, name, or description
- `mcp__posthog__add-insight-to-dashboard` — attach an insight to a dashboard
- `mcp__posthog__insight-delete` — permanently remove an insight (use when iterating)

**Recommended pattern:** Create → test → iterate → add to dashboard. Don't add to a dashboard until you're happy with the query.

### Funnel-Specific Notes

- **Ordered funnels:** Use when steps always happen in sequence.
- **Unordered funnels:** Use when step order varies across user populations (e.g., different product versions with different step ordering).
- **FunnelsQuery gotcha:** The `properties` field in EventsNode does NOT support OR property groups — only flat filter lists. For multi-pattern matching (e.g., matching both old and new URL structures), use the `regex` operator on a single property filter.

## Person Lookup & Investigation

- `mcp__posthog__persons-list` — search by email, distinct_id, or properties
- `mcp__posthog__persons-retrieve` — get full person profile with all properties and events
- `mcp__posthog__entity-search` — broader search across persons, events, sessions

**Investigation workflow:**
1. Get person by email
2. Check their events
3. Check their properties
4. Cross-reference with Customer.io for campaign attribution (see the `customerio` skill)

**Identity gotchas:** PostHog creates new anonymous distinct_ids on page navigations that reset cookies. Magic link flows and redirects can break the identity chain. `$identify` events merge persons — but only if PostHog sees both distinct_ids in the same session.

## Session Recordings & Replay Vision

Recordings are the capability people get excited about — "watch 15 recordings of people on this step
and tell me what's going wrong." It works, but it is the **fourth** move in an investigation, not the
first (see the investigation pattern below).

**Replay Vision** is the AI/OCR layer over recordings: a scanner is a standing LLM probe that runs
against each new matching recording and writes a queryable `$recording_observed` observation.
Scanner types: `monitor` (verdict), `classifier` (tags), `scorer` (numeric), `summarizer` (text).
`scanner_type` is locked after creation — delete and recreate to change it.

**Two prerequisites, both of which have bitten us:**

1. **AI data processing must be enabled in PostHog org settings.** Replay Vision is LLM-powered and
   will not run without it.
2. **Server-side events carry no `$session_id`, so they do not link to a recording.** PostHog support
   confirmed this for `payment_event` (sent via posthog-php) in March 2026 — the event associates to a
   *person* but not a *session*, so you cannot jump from that event to a replay. Tracked in HELP-11022;
   Evgeny added the `$session_id` requirement there. **Check this before promising any event → recording
   demo**, especially for welcome-track / enrollment steps.

**Quota discipline (read before creating a scanner):** scanners sweep on a Temporal schedule **every 5
minutes**, and every observation counts against a **monthly org quota**. Creation does *not* check
quota — the check happens at observation time, by which point the month's budget may already be gone.
Size the query and sampling rate first, and prefer one narrow scanner over a broad one. If several
people each spin up a permissive scanner, the org's month is spent in hours.

**The one rule for picking recordings:** never accept or produce an unfiltered recording list. Either
apply a goal-based filter or sort by a signal (activity, errors) so the first rows are worth a click.

## Error Tracking

- `mcp__posthog__list-errors` — see current exceptions
- `mcp__posthog__error-details` — drill into specific error fingerprints

**NSLS noise context:** The shared project sees ~260K total exceptions/week across all properties. Roughly 67% are FOL DOM CustomEvent errors misclassified by PostHog's error SDK. Always filter by `$host` to focus on the product you care about before drawing any conclusions.

**Setting up Slack alerts:** PostHog CDP destinations can POST to Slack on exception events. Filter by `$host` + `$exception_issue_id is set`.

## Feature Flags & Experiments

- `mcp__posthog__feature-flag-get-all` — list all flags
- `mcp__posthog__create-feature-flag` — create a new flag (percentage rollout, user targeting, etc.)
- `mcp__posthog__experiment-create` — set up A/B tests with metrics
- `mcp__posthog__experiment-results-get` — check experiment results

**Flag lifecycle:** create → test in dev → gradual rollout → full rollout → clean up

## Event Definitions & Properties

- `mcp__posthog__event-definitions-list` — see all events in the project
- `mcp__posthog__properties-list` — see what properties events carry

**Naming conventions:**
- NSLS custom events: snake_case (e.g., `step_start`, `ai_generation`)
- PostHog auto-captured: `$` prefix (e.g., `$pageview`, `$identify`)

Each product sends its own custom event properties — use `mcp__posthog__properties-list` to discover what's available for your domain.

## Observability Logs

- `mcp__posthog__logs-query` — query PostHog's internal log streams
- `mcp__posthog__logs-list-attributes` / `logs-list-attribute-values` — discover what's in the logs

Use these when debugging CDP destinations, checking webhook deliveries, or investigating data pipeline issues.

## Investigation Pattern That Works Here

This is the method that has actually found NSLS revenue bugs (reconstructed from Julia Botz's
enrollment-funnel work). Follow it in order; recordings come late.

1. **Let a detector tell you.** The highest-leverage layer is standing detection, not ad-hoc queries —
   e.g. the Funnel Watchdog bot posting *scored* anomalies to `#enrollment-watchdog` ("Medium 60/100 ·
   +15 for 6 payment attempts in ~2 min · 3rd distinct member in 30 days"), payment-failure email
   alerts, HELP-11488's daily Apple Pay check. Build the detector before building the habit.
2. **Segment until the split appears.** One metric, one dimension, two date windows. Keep cutting until
   there is a clean break rather than a vague decline.
3. **Then find what *didn't* move.** This is the move that does the real work. In the July 2026 payment
   drop: completed orders per payment-page visitor fell 9–11 points on *every* WebKit browser
   (Safari/macOS 59.4→48.8, Safari/iPhone 47.1→37.7, Chrome/iPhone 47.9→38.7) while every Chrome/Edge
   browser was flat or up. Chrome-on-iPhone uses Safari's engine, so it split on **browser engine, not
   device**. Meanwhile server-side `payment_failure` events *fell* (2.1%→1.4%) while non-completion
   *rose* ~10 points, and client-side JS exceptions did not rise — which proved the failure "doesn't
   throw an error or reach our servers." The counter-signal is what narrows a drop to a mechanism.
4. **Correlate to a deploy, then read the code path.** Find the only relevant change in the window and
   look for a real mechanism (there: a promise around `Accept.dispatchData` with no timeout, `onload` as
   the sole handler, no analytics on the tokenization failure branches).
5. **Pull recordings only for the segment that broke** — and only if the events actually link (see the
   `$session_id` prerequisite above).
6. **State it as a hypothesis and name the cheapest falsification.** "A possible explanation I'd like
   validated, not asserted… fastest check is a real card attempt in Safari with the network tab open."
   Size the impact (~5–14 core enrollments/day), file the ticket, post the explicit ask.

**QA loop version of the same thing:** bug report email → find that person → pull their session around
the report time → attach evidence to the ticket. This removes the "cannot replicate / check incognito"
round trip that costs days on reports like the nomination-code paste bug.

## Diagnostic Loop (When Queries Return Wrong Results)

When a query returns 0 rows, unexpected numbers, or doesn't match what you expected:

1. **Check the `$host` filter.** Are you filtering for the right product domain? Server-side events have `$host = null`.
2. **Check the event name.** Run `event-definitions-list` and search — event names are exact-match. `step_start` ≠ `stepStart` ≠ `step-start`.
3. **Check the date range.** HogQL uses UTC. "Today" for a US user started hours ago in UTC.
4. **Check the property name.** Run `properties-list` — property names vary by product and event type.
5. **Broaden, then narrow.** Remove all filters → confirm data exists → add filters one at a time to find which one eliminates results.
6. **Try `query-generate-hogql-from-question`** to get a different angle on the same question.
7. **Check if it's a funnel issue.** FunnelsQuery `properties` doesn't support OR groups — use `regex` operator instead.

## Output Guidelines

- **For leadership:** Lead with the insight, not the query. "Completion rate dropped 12% after the track split" not "SELECT count() FROM events WHERE..."
- **For engineering:** Include the exact HogQL query so they can reproduce and iterate.
- **For cross-team reports:** Include both the number AND a representative user story (see `/data-intel` for the micro/macro synthesis pattern).
- **PII awareness:** PostHog contains emails, names, IP addresses. Don't include PII in outputs unless specifically requested and the audience is appropriate.

## Gotchas & Trapdoors

- **FunnelsQuery `properties` doesn't support OR groups.** You MUST use `regex` operator for multi-pattern matching. This is undocumented and will silently return wrong results if you try OR property groups.
- **Server-side events have `$host = null`.** You can't filter server-side events (step_start, ai_generation, etc.) by domain. Use client-side $pageview events with `$current_url` patterns for domain-specific funnels.
- **`insight-delete` is permanent.** No recycle bin. If you delete an insight that's on a dashboard, it disappears from the dashboard too.
- **FOL noise overwhelms error tracking.** 260K exceptions/week, 91% crash-free rate. ~67% are FOL DOM CustomEvent errors. Always filter by `$host` before drawing conclusions.
- **Identity chain breaks on redirects.** Client-side redirects (like `router.push`) create new anonymous distinct_ids. Magic link flows are especially fragile — the landing page and the callback page may be different "persons" in PostHog.
- **`prefetch_opened` ≠ human opened.** Email clients pre-fetch images, triggering false opens. Always use `human_opened` and `human_clicked` for real engagement metrics.
- **Date math in HogQL is UTC.** If you're looking at "today's events," remember NSLS users are in ET/CT/PT but PostHog timestamps are UTC.
- **Deleting a dashboard does NOT delete its insights.** They become orphaned. Clean up insights separately.
- **Server-side events have no `$session_id`** — so they never link to a session recording, only to a
  person. Confirmed by PostHog support for `payment_event`; tracked in HELP-11022. Verify before
  building any event → replay workflow.
- **Replay Vision scanners bill against a monthly org quota and sweep every 5 minutes.** Creation does
  not check quota; only observation time does. Size before you enable.
- **Experiment bucketing: use `$device_id`, not distinct_id.** Distinct-ID bucketing lets users switch
  variants when they get identified, which shows up as a sample-ratio mismatch. Also: exposure logs
  under device ID while purchase logs under member UUID, so unlinked IDs mean exposures with no
  attributed revenue (HELP-11441). Identify before evaluating the flag, or evaluate server-side.
