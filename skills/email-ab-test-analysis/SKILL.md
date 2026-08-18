---
name: email-ab-test-analysis
description: >-
  Use when someone asks who won an email A/B test, whether a result is real or
  just noise, why one variant beat another, what to test next, or why a campaign
  performed worse or better than an earlier one. Also when a test's arms were
  never formally split and nobody is sure how to read it, when two tests run
  months apart need comparing, when an email's performance moved up or down
  without an obvious cause, or when deciding whether a test has run long enough
  to call. Covers
  Customer.io, HubSpot, and any ESP whose numbers can be read off a screen. For
  tests where the arms are LLM prompts rather than fixed copy, see
  llm-email-workflow.
---

# Email A/B test analysis

## Safety — three tiers

1. **Read-only** (default, and where this skill lives) — reading campaigns,
   actions, templates, metrics; running the statistics and copy diff locally.
   No friction.
2. **Configuration** — writing payload files, creating an `esp.json`. Local
   files only. Say what will be written and where.
3. **Write to the ESP** — **never**. Not offered, not on request within this
   skill. Customer.io exposes `POST /actions/{id}/winner` ("choose split test
   winner") and campaign start/stop; HubSpot can declare a winner and send it.
   This skill computes the winner and hands over the trigger. It never pauses,
   stops, edits, or resolves anything that is sending. If someone asks it to
   act on a live campaign, stop and point them at the ESP UI.

## Purpose

Email tests can fail quietly. Not because the sends break, but because a
plausible story gets told about a difference that was never real, and that story
becomes the brief for the next test. This skill exists to make the informed read
cheap and the uninformed read hard: it joins the copy that actually shipped to
the outcomes it actually got, decides whether there is anything to explain
before explaining it, and refuses to name a cause the data cannot carry. What it
creates that did not exist before is a defensible "no" — the ability to say *the
spread is inside the noise, and here is the volume that would settle it* with
the same confidence as naming a winner.

## Quick Start

```bash
# Scripts live beside this file; payloads should not. Hold the one before
# changing to the other, or every command below is a file-not-found.
SKILL_DIR=<the directory holding this SKILL.md>
cd <a working directory outside this repo>

# Customer.io, by campaign. Send windows are rebuilt from per-send records by
# default (--windows auto); --windows periods accepts a coarse, labelled read.
python3 "$SKILL_DIR/scripts/fetch_customerio.py" --campaign <id> --out <prefix> \
    --key-file <path>

# Any ESP, from numbers read off the screen — no credentials needed.
# One row per arm; comma, tab-pasted, semicolon or pipe all parse.
python3 "$SKILL_DIR/scripts/fetch_manual.py" --csv arms.csv --out <prefix> \
    --esp hubspot --body-dir bodies

python3 "$SKILL_DIR/scripts/abdiff.py"  <prefix>.copy.json   # what differed — FIRST
python3 "$SKILL_DIR/scripts/abstats.py" <prefix>.stats.json  # does it mean anything
```

Read the diff before the numbers. Knowing how many elements changed constrains
what the verdict is allowed to say, and reading them in the other order invites
a story that fits the result.

## The rules that make it worth running

**Gate before reasoning.** A significant result is required before any winner
is named. A no-read stated in full — *no read yet; at this volume only a lift of
X% or larger could have been detected, and settling an effect the size of the
one observed would take about N per arm* — is a **first-class verdict**, not a
caveat. `abstats.py` computes both figures automatically; report them rather
than a bare "not significant".

**A p-value assumes one look at a fixed horizon.** Calling a live test the first
time it crosses the bar is a different procedure with a far worse false-positive
rate — peek often enough and almost anything crosses. The engine cannot see how
often it has been run, so ask what volume was planned and treat required-n as the
horizon. An interim read is *what the numbers say so far*, reported with the
volume still to come.

**The verdict leads; it is never a caveat.** Baseline testing of this task found
the failure is not ignorance of the statistics — agents compute the p-value
correctly and then demote it, opening with a confident rollout recommendation
and listing "not statistically significant" under caveats further down. A
no-read reported beneath a recommendation is a no-read nobody hears. State the
verdict first, in the same breath as any recommendation, every time.

A recommendation is not a result. Give them as two separate statements, the
verdict first and the recommended action second, so neither can be mistaken for
the other. Shipping the control because the challenger showed no measured upside
is a legitimate operational call. "The control won" is a different claim, and a
no read is exactly the state that cannot support it. Not finding a difference is
not the same as showing there is none — a real gap between the arms can go
undetected simply because the test was too small to see it. Never let the
recommendation stand in for a result the numbers did not produce.

**Check split integrity before reading anything.** Two arms with the same
subject line should open at about the same rate. When the gap is bigger than
noise, something other than the subject line moved. The usual cause is
deliverability: an image-heavy template, spam-triggering wording, or broken and
low-reputation links push one version toward the spam folder, where nobody opens
it. It can also be a non-random split, or a difference in send time or sending
domain. So this is an instruction to go and look at the template that opened
worse — not an automatic reason to throw the test out. It runs the other way
too: an arm earning many more clicks tends to gain inbox placement over time, so
the open gap can be a downstream effect of that arm genuinely being better.
`abstats.py` flags the gap. Work out which of those it is before reading
anything else, and say which.

**Count the changes before explaining them.** `abdiff.py` reads five elements —
sender name, subject, preheader, CTA and links, and body prose — and the sender
name counts, because it is read before the subject is and it moves opens. Pinning
the result on a single element is only safe when a single element differs. Two or more means a bundle
beat a bundle, which does not transfer to the next email. State every difference
in full. If one of them is the likely driver, say so and say why. Name the one
that would be cleanest to isolate in the next test, and state whatever can still
be concluded. If nothing stands out as the likely driver, say that as well —
"several things changed and none is an obvious candidate" is a real answer. Then
say plainly that the cause cannot be tied to one element. `abdiff.py` prints the
gate in plain words: *Is the difference in performance attributable to one
element? No — N elements changed.*

An element that could not be read is **unknown, not unchanged**. Without the body
markup — the credential-free path unless `--body-dir` was given — body, CTA and
links were never compared, so a lone subject change is not "one element changed".
`abdiff.py` names what it could not see and withholds attribution. Supply the
bodies to get an answer instead of a guess.

**Match the metric to the element, usually.** Subject and preheader are normally
read on opens; body and CTA on clicks and conversions. A body change read on open
rate is usually noise, and a subject change read on conversions is usually
laundering. But the boundary is not sealed. A body and offer that earn clicks
lift that send's inbox placement, and so its opens — placement is set per send,
out of the sender's reputation, the sending IP's reputation, the quality or
spamminess of the email itself, and the engagement it earns. And a subject that
brings in more of the right readers can raise the click rate on identical body
copy. Use the mapping as the default, and call out the crossover explicitly when
the numbers point at it.

**Pick the decision metric deliberately; raw clicks are the default.** The
engines score on `clicked` — every click, machine or human — unless told
otherwise; `--metric` and the payload's `primary_metric` are honoured, including
for the human-only fields. Falling back to `human_clicked` happens only when no
raw count was supplied at all, and the output says so. The best
metric is the business outcome the campaign exists to produce — signups,
renewals, revenue — attributed back to the email. That is rarely tracked well
enough to settle a test, which is why clicks are the working default rather than
the ideal. Count every click, machine or human. As of August 2026 that is the
sounder read rather than a compromise: prefetching clients and security gateways
act on both arms alike, so they cannot favour one, and a click they generate is
itself evidence the mail reached a real, inbox-placed account.

**That neutrality has one edge, and the engine checks it rather than assuming
it.** Machine activity is even-handed only while it treats both arms the same,
and it stops doing so when the arms differ in their links: a gateway or
prefetcher visits a changed URL, domain or redirect on its own schedule, and
those visits land in `clicked` looking exactly like a person acting. So where the
ESP separates the counts, `abstats.py` re-runs the comparison on human clicks as
a check. Agreement is reported and the verdict stands. Disagreement — raw
significant, human not, or the two pointing at different arms — **withholds** the
verdict rather than footnoting it, and points at the link diff. If the links do
differ, the raw spread is a machine artefact, not a result: score it on
`human_clicked`, and say which count the number came from either way. Where no
machine split is reported there is nothing to check.

Let the operator set the bar. If they name a conversion metric they actually
track, score on that. If they ask what to use, recommend clicks. If they sound
unsure and are asking for advice, it is fine to check their reasoning and push
back gently — but measuring lift well is a craft, and plenty of marketers are
better at it than this skill. Do not be more opinionated than the evidence
supports. If only one element changed and the operator wants each version
compared on one specific metric, do that.

**Count opens from any source; read the human/machine split as diagnosis.**
Filtering down to human opens throws away signal. A machine only prefetches mail
that reached the inbox, not the spam folder, and only for an address someone
actually configured in a mail client — so a machine open is real evidence about
both deliverability and the account. Where the ESP separates the two
(Customer.io gives `human_opened` and `prefetch_opened`), read the split as a
diagnostic: a drop in prefetch share points at placement rather than at copy.

This is a rule for *scoring a test*, where both arms carry the same machine
activity and only the comparison matters. It is not the rule for reporting how
many people read an email — that question wants `human_opened`, and
`/customerio` is right to say so. See it for the full metric taxonomy.

**Check the cohort before the calendar.** What decides whether two sends can be
compared is not whether they overlapped in time — it is whether they went to the
same population under the same rules. Same cohort rules and no major business
change in between, and a winner may be named, provided the caveat is stated
plainly: this was not a simultaneous randomised split. Where the sends do
overlap, that window is the stronger evidence and leads the report; a stretch
with no overlap can still be scored, but its weaknesses — list state,
seasonality, deliverability drift — belong beside the number, not in a footnote.

A difference in the cohort rules themselves is fatal, and this is a **gate, not
a warning**. `fetch_customerio.py` resolves each campaign's trigger segments —
not just their ids — and `abstats.py` compares the rules. Where the rules are
readable it decides: identical rules, or one campaign, and it proceeds; rules
differing only in their date window are one rule run twice, so it proceeds;
rules that plainly differ on anything else are two populations, and it says so
and withholds the verdict.

It asks only where it genuinely cannot see. A static list — built by hand or
imported from a CSV, what Customer.io calls a manual segment — carries no rule
at all, and a segment id alone is a pointer, since a rebuilt segment can carry
the same rule under a new id. There it prints what it
found on each side and withholds the verdict until the question is answered with
`--cohort-same` or `--cohort-differs`. The rates still print either way, because
they are facts; which one is *better* is not one until the populations match.
`abstats.py` finds the overlapping window and can rescope to it — from per-send
timestamps where they were pulled, and from the period arrays otherwise, saying
which; the cohort question it cannot answer, so ask it.

**How a test ends is the thing to look for.** Not both arms stopping together —
one arm stopping while the other carries on, because the test was called and the
rest of the traffic went to the winner. That shape is the reliable signal; the
volume ratio is not, since a deliberately uneven split produces the same ratio.
Two traps follow. A split branch read from the ESP shows its **current**
weighting, not the weighting during the test, so a concluded test reads as
all-to-one-arm and must never be taken as evidence no test ran. And the shared
window is only as narrow as the series provided: if the shift happened inside a
bucket, that bucket mixes randomised and post-declaration traffic. Where
per-delivery timestamps exist, rebuild the window from those and score it
directly.

**Treat a lopsided split as a signal.** One arm holding 65%+ of volume usually
means traffic was already shifted to a presumed winner — often correctly, but
everything after the shift is no longer randomised. `abstats.py` does not stop
at warning, because a warning printed above a confident verdict is not a check.
It rescores on the balanced stretch preceding the shift and reports it as dates
rather than as a count of periods, because a count reads as a measurement while
hiding the only thing that matters about a window — how wide the periods were.
Where the split was already uneven in the first period the series covers,
it reports that and does not conclude the arms were never randomised — either
there is no balanced stretch, or the series is too coarse to hold it, and only
the branch configuration and the send timestamps separate those. Where the payload carries no per-period series the
shift cannot be located, and the output states that the rescore did not happen
rather than implying it did.

**Rebuild the window from per-send records. Required, not an improvement.**
Whenever a declaration signal fires, or the period bucket is coarser than the
flight being read — which is any flight shorter than a month once a campaign is
a quarter old — reconstruct the window from individual send timestamps before
scoring anything. A period array is a summary, not the record, and treating it
as the record produces two distinct wrong verdicts. One is a **false winner**:
an arm whose whole life fits inside one bucket, scored against another arm that
ran the rest of that bucket alone, turns a dead heat into a decisive win. The
other is a **phantom overlap**: two arms whose sends never touched can share a
calendar bucket, and a bucket intersection reports them as concurrent. A shared
bucket is not an overlap — where the intersection is empty, say sequential,
score the lifetime numbers, and name what moved in between.

Two mechanics travel with this. Per-send records come back newest-first under a
hard page cap, so page one is the END of a flight and reading it as the series
silently loses the start. And the counted records must reconcile against the
reported totals before anything is scored — a pull that stopped early does not
look like an error, it looks like a shorter test. Where the records cannot be
read at all, the coarse read still runs and every line of output says the
window is unverified.

**A withheld verdict is a question, not a result.** When a gate cannot see what
it needs, it stops and prints what it would need to know. That output is
addressed to the operator. Put the question to them in plain words, say what
each answer changes, wait, then re-run with the answer supplied. Reporting
"verdict withheld" and moving on turns a five-second question into a report
nobody can act on, and reads as a conclusion when it is the absence of one.

## Macro and micro

| Macro | Micro |
|---|---|
| Which direction of copy wins for an audience, across many tests | Which of subject, preheader, body, CTA and links actually differ between two arms |
| Whether the testing programme is powered well enough to learn anything | That a lopsided split still reads, provided the smaller arm carries enough volume to reach significance |
| Whether the baseline is stable enough to test against | That two arms named "control" can be different emails |

The synthesis is the point: a winner without the copy diff is a leaderboard, and
a copy diff without significance is an opinion.

## Domain micro — Customer.io

Hard-won, and none of it visible from the UI. For general Customer.io metric
semantics and auth, use `/customerio`; what follows is specific to reading tests.

**Check for the native split test first, then fall back to arms.** Customer.io
has a native split-test object and some accounts use it — when they do,
`GET /campaigns/{id}/split_metrics` carries the comparison directly. Plenty of
accounts never use it, building the test instead as a `random_cohort_branch_action`
routing into *separate, independent* email actions distinguished only by name.
There, `split_metrics` returns `{}` — it is not broken, there is simply no
split-test object — so pair the arms and run the statistics manually. Check the
split object once, then stop hunting for it.

**Metrics live on the action, not the campaign.** `/actions/{id}/metrics`.

**The campaign response is wrapped.** Actions are at top-level `.actions`, not
`.campaign.actions` — the latter returns empty and looks like a real answer.
Template body is at `.template.body`, not `.body`.

**Campaign listing paginates, and one pass is not enough.** A single call can
return a small fraction of the campaigns that exist, and a filtered pass can miss
one entirely. Page fully and verify the count before concluding a campaign does
not exist.

**Monthly metric arrays are fixed-length 13 regardless of `steps`,** and index
12 is the current month. Align arms by index and sanity-check against the
campaign's own name or dates.

**Two APIs, two shapes.** The MCP connector exposes internal
`/v1/environments/{env}/…` paths; an App API key works against public
`api.customer.io/v1/campaigns/…` paths, which return metrics as
`{"metric": {"series": {…}}}` with **no `total_*` fields** — sum the series.
`fetch_customerio.py` handles both.

**Region is a different host.** EU workspaces answer on `api-eu.customer.io`;
calling the US host returns a redirect rather than an error anyone notices.
`--region eu`.

**Arm names are not reliable identifiers.** A test can have three arms, and two
of them can carry an identical name. Key on `action_id` always.

**Three arms is three comparisons, and the bar moves for all of them.** Three
pairwise tests at 0.05 each carry roughly a 14% chance of a false winner
somewhere; six arms carry better than even odds. `abstats.py` applies a Šidák
correction, prints the tightened per-comparison bar in its header, and sizes
required-n against it, so a multi-arm test needs more volume per arm to say the
same thing. Report the corrected bar with the verdict — a raw p-value read
against 0.05 is the mistake this prevents.

**Resend-to-non-opener legs are excluded by default** (matched on a configurable
name pattern). They send to an already-declined population, so the denominator is
not comparable to the initial send.

**Draft campaigns can be fully built and never have sent.** Check `total_sent`
before analysing anything.

## Domain micro — HubSpot

**Opens arrive as a single undifferentiated count.** There is no human/prefetch
split here, so that diagnostic is unavailable — the open rate itself still reads.
`fetch_manual.py --esp hubspot` marks arms `opens_not_split_by_source` and the
engine notes it in the output.

**HubSpot runs A/B tests natively — look for its test object first.** Variants
are separate marketing emails linked by a shared `abTestId`. Pair emails by hand
only when no test object links them. For CRM-side context use `/hubspot`.

**HubSpot auto-declares winners** and can send the winner to the remainder, so
the split-imbalance warning fires often and legitimately — post-declaration
sends are genuinely not randomised.

**Creating a private app token is an admin permission**, so in many portals it
means a request to whoever administers it rather than something the person
reading the test can do. This is why the credential-free path exists and is not
a lesser one: anyone who can open the performance screen has everything needed.

## Diagnostic loop

TRY → OBSERVE → DIAGNOSE → ADAPT → TRY AGAIN.

| Observation | Diagnosis | Adaptation |
|---|---|---|
| `split_metrics` returns `{}` | Not a native split test | Pair the email actions by `action_id`, score manually |
| Arms share a subject but open differently | Usually the deliverability of one template; sometimes the split, send time or domain | Resolve it before reading anything else, and say which it was |
| Every arm reports 0 delivered | Public API returns `series` with no `total_*` | Sum the series (already handled) |
| HTTP 301 / redirect notice | Wrong region | `--region eu` |
| A campaign "does not exist" | Listing paginated | Page fully, verify the count |
| Arms look wildly unequal | Traffic was shifted mid-flight, or the split was designed that way | Verify which. A designed split reads fine if the smaller arm has the volume; after a shift the engine rescores on the pre-shift window automatically |
| One arm sent months after the other | Sequential, not simultaneous | Confirm the cohort rules match, lead with any overlap, attach the weaknesses |
| A payload diffs to "nothing changed" | Copy arrived under a key the differ does not read | `abdiff.py` refuses and names the key — fix it, never report unknown as unchanged |
| Diff reports "UNKNOWN, not unchanged" | No body markup for an arm, so body, CTA and links were never compared | Pass `--body-dir`; until then attribution stays withheld, and it should |
| Verdict withheld with human clicks disagreeing | Machine clicks on links that differ between the arms | Compare the links and their domains; if they differ, score on `human_clicked` and say so |
| `--since/--until` refused with no records | The requested window is empty; only lifetime numbers remain | Widen the window, or drop the flags for a labelled read of the whole flight |
| Sources scored on different metrics | `abcompare.py` refuses to compose them | Re-fetch on one metric, or pass `--metric` naming one every arm carries |
| Verdict significant, diff shows 3 changes | Bundle vs bundle | Refuse single-element attribution; name the likely driver if there is one, and the cleanest one to isolate next |
| CSV column silently read as 0 | Header alias missed | Check the printed mapping; `--map "field=Header"` |
| A field is missing from an API response | Shape differs from expectation | The fetchers print the keys actually received — start there |

Never let the loop end at a screen doing nothing. There is always a path
through: worst case, read the numbers off the UI and use `fetch_manual.py`.

## Output guidelines

Structure every read in this order: **what shipped** (all arms, every
difference, and the cohort each went to), **what happened** (rates, absolute and
relative difference, z, p, and the basis), **verdict** (winner, or explicitly no
read with the sample needed), **what may be concluded** (bounded by the
attribution gate), **what to test next** (labelled generative).

Diagnosis and next-tests must stay in separate labelled sections. Speculation
placed beside measurement borrows its credibility.

By audience: leadership wants the decision and what it changes; marketing wants
the copy direction and the next test; engineering wants the p-value, the basis,
and the caveats. Never report a rate without its denominator, and never report a
cross-test comparison without saying it is observational.

## Cross-test comparison

Comparing two tests months apart is not a randomised split. Whether a winner can
be named depends on the cohort: same population under the same rules, no major
business change in between, and it can — with that caveat stated. A meaningful
difference in the cohort rules voids it. Either way, *why* one beat the other is
never a fact here, only that it did.

```bash
python3 scripts/abcompare.py --out cross <prefixA>:<armId> <prefixB>:<armId>
```

This marks the payload so the verdict downgrades itself rather than depending on
the writer to hedge.

**Diff control against control across consecutive tests.** Control versus test is
the comparison everyone already makes; control versus control is the one that
gets skipped, because teams treat the control as a fixed baseline and then
quietly edit it. Worth running for that reason alone.

Two arms can both be called "control", share a name and an identical subject
line, and still be different emails — an edit landed on one and not the other,
and every surface still says "control". Diffing the sends is what surfaces it.
An identical subject does not mean the opens are comparable: if they differ, work
through the open-gap check above first. If more than one element drifted,
attribution is refused here exactly as it would be inside a test. The lesson is
not the copy — it is that a baseline can move without anyone running it as a test.

## Rationalization table

| The shortcut | Why it is wrong | Do this instead |
|---|---|---|
| "p = 0.08 is basically significant" | The threshold is the whole mechanism; a near-miss is a no-read | Report no read and the sample needed |
| "It's still the right operational call — there's no scenario where B is safer" | Observed verbatim in baseline testing. Conflates a recommendation with a result | Verdict first — no read — then the recommendation: the control ships by default |
| "I'll lead with the recommendation and put the caveat below" | The most common observed failure. Nobody reads past the recommendation | Verdict in the opening sentence |
| "Directionally clear, conclusively no" as the headline | Softens a no-read into a soft yes | "No read" is the headline; direction is a footnote |
| "Three things changed but the subject obviously did it" | That is the story fitting the result | Refuse single-element attribution; say which is the likely driver and why, or that none stands out |
| "Open rate went up, the subject won" | Only if the subject is what changed; a better-placed email also opens more | Check what actually differed, and check placement |
| "Lifetime totals are the fuller picture" | The overlapping window is the stronger evidence | Lead with the overlap; score the rest separately, weaknesses attached |
| "The arms are 90/10, so it cannot be read" | An uneven ratio is not the problem; too little volume in the smaller arm is | Read it if the smaller arm reaches significance — but check the split was designed, not a mid-flight shift |
| "No body copy, so nothing changed in the body" | Not looking is not evidence | Report body and CTA as **unknown** |
| "This is a two-arm test" | Tests can have three arms, two identically named | Enumerate arms by ID |
| "I'll declare the winner in the ESP to save a step" | Irreversible, affects live sends | Never write; hand over the trigger |
| "Cross-test result is significant, so the copy caused it" | No randomisation between tests | Label observational |
| "The user needs an answer, so give the most likely one" | A fabricated lesson briefs the next test | "No read yet" is a complete answer |

## Red Flags — STOP

Stop if about to:

- Name a winner when `abstats.py` said NO READ.
- Open with a rollout recommendation and place NO READ in a caveats section.
- Report a verdict without resolving an open gap on an identical subject line.
- Explain *why* a variant won when `abdiff.py` answered NO to the attribution
  question.
- Score a test without confirming both arms went to the same cohort under the
  same rules.
- Lead with lifetime totals when an overlapping window exists.
- Call a cross-test difference causal.
- Describe unexamined copy as "unchanged".
- Call any write endpoint, or suggest declaring a winner inside the ESP.
- Pool resend-to-non-opener sends with initial sends.
- Analyse a campaign without checking it actually sent.

## Where this sits

- Setup and connections → `/connect`. Do not duplicate credential setup here.
- Customer.io metric semantics and auth → `/customerio`.
- HubSpot CRM context → `/hubspot`.
- Cross-system questions → `/data-intel`.
- LLM-generated emails: pipeline → `/llm-email-workflow`; the Society
  invitation prompt → `/society-invite-llm-email-prompt`.

Prompt-vs-prompt arms are **not** handled here. There is no fixed copy to diff,
so those need sampling and characterisation of N generated emails per arm, plus
a diff of the prompts themselves — a genuinely different procedure. Use
`/llm-email-workflow`.

## Files

- `scripts/fetch_manual.py` — CSV + pasted bodies, no credentials required
- `scripts/fetch_customerio.py` — Customer.io fetcher (`--region us|eu`,
  `--windows auto|messages|periods`)
- `scripts/abcompare.py` — build a cross-test payload from two fetches
- `scripts/abstats.py` — verdict engine: z-test, send-window verification,
  overlap window, cohort and split checks, MDE
- `scripts/abdiff.py` — element-level copy diff and attribution gate
- `scripts/espconfig.py` — config and payload plumbing shared by fetchers
- `scripts/esp.example.json` — non-secret defaults (region, workspace)
- `reference/customerio-ab-test-endpoints.md` — endpoint map and API traps

Pure Python 3 standard library — no third-party packages. Runs on macOS, Linux
and Windows. Use `python3`; macOS 12.3 and later ship no bare `python`.
Credentials come from `--key-file` or an environment variable, never from
config.
