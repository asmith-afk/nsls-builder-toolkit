# Autonomous mode — the headless entry for unattended agents

Used ONLY when the invoker explicitly states it is running unattended —
e.g. the weekly roadshow-intel clustering agent. A human in the loop,
however hurried, gets the normal interactive workflow. This mode exists
because the interactive skill reserves the materiality answers, the
growth-vector confirmation, and every attestation for a live human —
running it verbatim with nobody present would stall, or worse, self-answer
owner-only questions.

## Entry contract

Input is ONE orphan-theme cluster from `roadshow_claims`: the claims, their
`verbatim_quote`s, the schools involved, and the theme label — handed over
by a scheduled agent with no human present. No cluster in hand, or a human
present → not this mode; run the interactive flow.

## The rule (verbatim)

```
Every drafted canvas/thesis section is tagged evidence_tag: "assumption" —
NEVER "data". The materiality gate is answered ONLY from citable cluster
data — cite or abort. On ANY ambiguity, abort: create no bet, leave the
theme brewing, report why. Abort is cheap; a junk bet is not.
```

## What changes from the interactive flow

- **Every section is `assumption`.** The interactive rule stands: `data` is
  first-hand knowledge only a human can supply, and there is no human. The
  internal-origin `data`/`estimate` exception does not apply — nobody is
  present to ground it.
- **Materiality gate (step 1.5) is cite-or-abort.** Answer both legs
  strictly from the cluster's claims, citing the specific claims/quotes
  that establish a path to ≥ $500K committed capital or ~$1M/yr revenue.
  No citable path in the claims → ABORT: no `create_bet`, theme stays
  `brewing`, report states exactly what was missing. Never estimate around
  missing data — a plausible market number with no claim behind it is
  fabrication, not research.
- **Interactive checkpoints are skipped AND recorded as skipped** — by
  name, in the bet's first status update: the origin question (step 1),
  the growth-vector confirmation (step 2), the office-hours pushback
  (step 3), the owner's confirmation of assumption priorities (step 4),
  and the step-7 gate attestation. Never self-answer an owner-only
  attestation — recording a skip is honest; faking a yes is not.
- **Step 5's alternative-canvas offer: skip it.** It's conversation-only
  scaffolding and nobody is here to adopt it.
- **Taxonomy is read-only.** `upsert_taxonomy` is shared-system tier and
  requires a human confirm. No existing market/segment/buyer fits → that is
  ambiguity → abort to `brewing`.
- **The both-no hand-down (step 1.5) drafts; it never fires.** Same reason as
  taxonomy: `hand_off_bet` assigns real work to a real group or person, and
  `create_squad` stands up a team visible portfolio-wide. Both are
  shared-system tier and both need the owner's confirmation of the exact
  assignee and rationale — and there is no owner here. Nothing in this file
  may be read as licence for either call.

  So in autonomous mode a both-no idea:
  1. `create_bet` as normal (stage `idea`), skipping the rest of the skill.
  2. **Does NOT call `list_squads` to pick an assignee, and does NOT call
     `hand_off_bet` or `create_squad`.** Choosing who gets work is the
     owner's judgement, not a clustering agent's.
  3. Records the proposed hand-down in the FIRST status update instead —
     "materiality: both legs no (cite the claims); proposed outcome:
     hand-down, assignee NOT chosen, owner to confirm" — so the idea is on
     the board and findable, with the recommendation attached and the
     decision still open.
  4. Leaves `status` alone. `handed_off` is a state an owner puts a bet in;
     an agent must not put it there, or the Handed-down section starts
     showing assignments nobody made.

  This is the same shape as the growth vector: propose, mark it proposed,
  let the owner confirm interactively. Recording a skip is honest; a
  hand-down nobody authorised is an unauthorised assignment wearing a
  record's clothes.
- Heartbeats become run-output log lines; everything not listed here runs
  exactly as the interactive flow writes it, and every write still passes
  `via: "bet-idea"`.

## Bet creation

- Stage `idea`, always.
- `owner` comes from the invoker's config (the routine's configured owner
  email) — NEVER the agent's own identity.
- `growth_vector` is proposed from the cluster and marked proposed, not
  confirmed — the owner confirms it later, interactively.
- The FIRST status update flags: **"AI-authored, unreviewed — created by
  autonomous clustering from roadshow evidence"**, lists the skipped
  checkpoints, and cites the cluster's claims (claim ids + schools) that
  the materiality answer rests on.

## Hard limits

- NEVER call `advance_stage` — idea→research keeps its human
  `worth_researching` attestation, no exceptions.
- NEVER attest evidence.
- ONE bet per theme, maximum — a second run against the same theme resumes
  or stops, never duplicates.
- ANY ambiguity — school unclear, claims contradicting each other,
  taxonomy missing, quote unverifiable — abort to `brewing` with a stated
  reason.
