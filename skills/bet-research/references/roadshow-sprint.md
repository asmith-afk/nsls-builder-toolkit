# Roadshow sprint — the later-stage vetting instrument

Used by `bet-research` Step R4, an optional path when ad-hoc rep
conversations aren't reaching the conversation gate fast enough.

## What it is

A scoped listening tour over the bet's segment and buyer, run through the
**existing** campus-roadshow pipeline — proven at 37 schools: every
conversation Fathom-recorded, auto-summarized into per-school reports with
timestamped recording links, survey pages built from Airtable, and a
cross-school product-ideas grid with attribution and pilot-interest rollups.
This is infrastructure that already works; a roadshow sprint borrows it for
one bet's research agenda rather than building a parallel version.

## When to propose it

- The conversation gate is the bottleneck — the bet can't reach 5
  conversations across 3 distinct institutions through ad-hoc rep calls at a
  reasonable pace.
- The bet needs breadth across the segment rather than depth with the same
  known-friendly schools that keep answering the phone.

**Propose it, never launch it unilaterally.** A sprint costs rep time and
calendar — the owner decides whether that cost is worth paying right now.

## The routing rule (verbatim)

```
The sprint RUNS THROUGH the campus-roadshow skill — invoke it for all
pipeline mechanics (school onboarding, report generation, timestamps,
survey pages, ideas grid, deploy). bet-research NEVER duplicates that
pipeline. bet-research's job is only: (a) scope the sprint — segment,
buyer, N schools drawn from the bet's saved target shortlist; (b) supply
the interview guide (references/interview-guide.md) as the conversation
frame; (c) after each roadshow meeting ships its report page, log it back
into the engine.
```

In practice: this skill decides *what* to research and *who* to talk to
(segment, buyer, N schools pulled from `save_targets`' saved shortlist); the
`campus-roadshow` skill decides *how* the pipeline runs (onboarding a school,
generating the report, injecting timestamps, building the survey page,
updating the ideas grid, deploying). Never re-implement any of that
mechanics here — invoke `campus-roadshow` directly for it.

## Ingestion recipe

Per roadshow meeting, once its report page exists:

```
log_evidence(
  kind: "roadshow",
  title: "<school> roadshow meeting",
  link: "<Fathom ?t= timestamp URL — preferred; roadshow.nsls.org report page acceptable>",
  // Prefer the recording timestamp: the automated pipeline caps rows without
  // a recording link at "interest" because report-page links are
  // self-referential provenance. A human grading FROM the recording may still
  // use the report page, but the timestamp link is the stronger citation.
  data: { problem_confirmed: … },
  signal_strength: <graded by the ladder from the recording — never from the summary's politeness>,
  entity_type/entity_id,
  via: "bet-research")
```

Grade `signal_strength` from what was actually said and done in the
recording, using `references/interview-guide.md`'s commitment ladder — never
from how warmly the auto-generated summary reads. Roadshow meetings count
toward the same conversation gate as one-off interviews (`references/gate-progress.md`
check 4) — same kind bucket (`interview` or `roadshow`), same
`data.problem_confirmed` and distinct-`entity_id` rules apply.
