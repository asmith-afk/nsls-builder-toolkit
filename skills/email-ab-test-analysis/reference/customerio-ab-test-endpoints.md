# Reading an A/B test out of Customer.io: endpoints and traps

Verified against a live production workspace, 2026-08.

Keep this file account-agnostic. Campaign IDs, arm names, subject lines and
result numbers belong in a private per-client note, never here — this reference
may sit in a shared toolkit for years after every campaign it could name has
been sunset.

## The big one: the test may not be a split test

Customer.io has a native split-test object, but plenty of accounts never use it.
The common hand-rolled pattern is a `random_cohort_branch_action` routing into
*separate, independent* `email_action`s, distinguished from one another only by
their names.

When a test is built that way:

- `GET /campaigns/{id}/split_metrics` returns `{}`. It is not broken.
- `GET /actions/{id}/split_metrics`, the native-split endpoint, is also empty.
- You must pair the arms yourself and run the statistics yourself.

Check the campaign's action graph first. If you see a cohort branch feeding two
email actions, stop hunting for a split-test object and go straight to the
actions.

## Endpoint map

| Need | Endpoint |
|---|---|
| List campaigns | `GET /v1/environments/{env}/campaigns` |
| Campaign detail + actions | `GET /v1/environments/{env}/campaigns/{id}` |
| Action detail (subject, template_id) | `GET /v1/environments/{env}/actions/{id}` |
| **Action metrics** | `GET /v1/environments/{env}/actions/{id}/metrics` |
| Template (body, links) | `GET /v1/environments/{env}/templates/{id}` |
| Per-link clicks | `GET /v1/environments/{env}/templates/{id}/tracked_link_metric` |
| **Per-send records** | `GET /v1/messages` on an App API key — see below; the `/deliveries` path is internal-only |

These are the internal paths an MCP connector uses. An App API key reaches the
public equivalents — `GET /v1/campaigns/{id}/actions/{id}` and so on — and the
two do not agree everywhere; see "Two APIs, two shapes" below.

Never call: `POST /actions/{id}/winner`, campaign start/stop. Read-only skill.

## Traps

**Campaign listing is paginated and one pass is not enough.** A single call can
return a small fraction of the campaigns that exist, and a filtered `page_all`
jq pass can miss the one being looked for entirely. Page explicitly and verify
the count before concluding something doesn't exist.

**The campaign response is wrapped.** Actions are at top-level `.actions`, not
`.campaign.actions` — `.campaign.actions` returns empty and looks like a real
answer. Template body is at `.template.body`, not `.body`.

**`body_plain` and `links` are usually null.** Parse the HTML in `.template.body`
for anchors and visible text. `body` on the *action* is ~4 chars (null); the
real body lives on the template.

**Subject is on the action, not the template** — though the template carries a
copy. Read the action's.

**Monthly metric arrays are fixed-length 13 regardless of the `steps`
parameter,** and index 12 is the current month. Align two arms by index before
comparing, and confirm the alignment against the campaign's name/date.

**`period` must be `months`, `weeks` or `days` — and a wrong value fails
silently.** Passing anything else returns the whole metric object with every
field null and every total 0, which reads exactly like a campaign that never
sent. If an action you know sent reports zeros, check the period value before
concluding anything.

**Only `months` reaches back far.** Weekly covers roughly the last quarter and
daily a short window; both return null for anything older, so a campaign that
ran a few months ago can only be seen in monthly buckets. That resolution is
usually coarser than the event being looked for — see below.

**A split branch's weighting is its CURRENT state, not its state during the
test.** The branch action carries the cohort weights live, so a concluded test —
one where a winner was picked and the rest of the traffic routed to it — reads
as all-to-one-arm today. Taking that as evidence no test ran inverts the truth.
The branch's `updated` timestamp is far more useful: it bounds when the
weighting last changed, which is usually the moment the test ended.

**Reconstruct the real window from the per-send records, not from the period
arrays.** This is the only way to separate the randomised part of a flight from
what was sent after a winner was declared, and it is required whenever one arm
stopped while another continued — not an optional refinement. Two wrong
verdicts came out of scoring the arrays instead.

**The endpoint depends on which API the credentials reach, and the two are not
the same path.** `GET /v1/environments/{env}/deliveries` is the internal API,
which is what an MCP connector uses. **On an App API key `/v1/deliveries` 404s.**
The public equivalent is `GET /v1/messages`, and it is the better of the two:

| Parameter | Effect |
|---|---|
| `action_id`, `campaign_id`, `newsletter_id` | Filter to one arm. Verified filtering, not ignored. |
| `type` | `email`, `push`, `in_app`, … |
| `metric` | Restricts to records carrying that metric, and makes it the basis of the window filter. |
| `start_ts`, `end_ts` | Window, in unix seconds. |
| `limit`, `start` | Page size and cursor. |

Each record carries `action_id`, `campaign_id`, `subject`, `recipient`,
`customer_identifiers`, `created`, and a `metrics` object that maps a metric
name to **the unix timestamp it happened at** — `sent`, `delivered`, `opened`,
`clicked`, `human_opened`, `human_clicked`, `prefetch_opened`, `machine_clicked`,
`converted`, `unsubscribed`, `bounced`, `spammed`, plus per-link `link:N` and
`human_link:N`. Every count this kind of analysis needs is therefore a matter of
counting records over a window, to the second, with no second metrics call.

Three mechanics, each of which fails silently rather than loudly:

- **Newest first, and `limit` caps at 1000.** Asking for 5000 returns 1000 and
  no error. Because the order is descending, a capped page is truncated at the
  OLD end — page one is the END of a flight, and reading it as the series loses
  the start, which is exactly where a short-lived challenger arm's whole life
  sits.
- **Page with the `next` cursor, and check that it advances.** It behaves on the
  public path; on the internal path naive auto-pagination was seen re-serving
  page one indefinitely. The fallback is to step `end_ts` back past the oldest
  record seen — which has its own edge: a batch send can put more than a page
  into a single second, and no narrower window exists to split those with. That
  case has to raise rather than return short counts.
- **Reconcile before scoring.** Summed per-record counts must match the arm's
  lifetime metric totals. This is the gate that catches a truncated pull, and it
  is the only one: a short pull produces a shorter flight, a smaller denominator
  and a cleaner-looking result, none of which reads as an error. Counting *more*
  than the totals report is normal rather than a fault — the metric series
  reaches back a fixed number of buckets and an older arm has sends it no longer
  covers.

Attribute engagement to the day the message was **sent**, not the day the click
happened. A click three days later belongs to the send that earned it; filing it
under its own day scores it against a different day's volume.

**Two APIs, two shapes.** The MCP connector exposes the internal
`/v1/environments/{env}/…` paths; the App API key works against the public
`https://api.customer.io/v1/campaigns/{id}/actions/{id}` paths. The public one
returns metrics as `{"metric": {"series": {...}}}` with **no `total_*` fields** —
sum the series yourself. `fetch_customerio.py` handles both shapes. The public
action detail also carries `body`, `subject` and `preheader_text` directly, so
you do not need a second call to `/templates/{id}`.

**Engagement is reported by source.** `human_opened` / `prefetch_opened` and
`human_clicked` / `machine_clicked` are separate fields, alongside the `opened`
and `clicked` totals. Score on the totals; read the split as a diagnostic. A
fall in prefetch share is a placement signal, since a client only prefetches
mail that reached an inbox on an account someone configured.

**Draft campaigns can be fully built and never have sent.** A campaign with
every arm, template and subject line in place may still have 0 sent. Check
`total_sent` before analysing anything.

**Arm names are not unique and are not keys.** A three-arm test can carry two
arms with the identical name. Key everything on `action_id`.

**Naming conventions drift across a series.** A campaign family renamed halfway
through means a name filter needs both the old and the new string, or you will
silently analyse a subset. Likewise, a campaign that looks like part of the
series may contain **no email actions** at all — scheduler campaigns that write
people into static segments are common, and the sends happen elsewhere.

## Per-account specifics

Campaign IDs, arm/action IDs, the naming convention in use, and which campaigns
are schedulers rather than senders are all account-specific. Keep that map in a
private note alongside the client's other working files, and keep the test
ledger there too.
