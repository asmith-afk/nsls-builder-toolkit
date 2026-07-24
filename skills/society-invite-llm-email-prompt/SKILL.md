---
name: society-invite-llm-email-prompt
description: >-
  Use when writing or revising the LLM-node prompt for personalized Society or
  member-invitation emails to NSLS members; when generated emails read generic,
  read like an upsell, or recite raw field values back as labels; when NSLS-alum
  standing gets confused with school graduation, or a chapter name gets read as
  current enrollment; when life-stage or graduation-date logic misbuckets past
  versus future graduates; when an output the template injects renders empty
  because the node's property name does not match; or when a subject line or
  preheader ships over its character limit. For the workflow the prompt lives in,
  use llm-email-workflow.
---

# NSLS Society invitation LLM email prompt

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — pulling field fill rates, profiling member data, reading the
   existing prompt, template, and past sends. Runs without friction.
2. **Configuration** — writing or editing the prompt in the LLM node, declaring
   the node's output properties, sandbox generation against seed profiles. Ask
   first and name what changes.
3. **Generating for real members** — never proactively offered. Explain,
   confirm, then proceed. Email cannot be recalled, and a bad generation reaches
   a member with their own data in it — a wrong life stage or a misread alum
   status is visible to the person it is wrong about. Gate every live send on
   the validation section below, and treat widening past a validated batch size
   as the same decision again.

## Purpose

The value here is the error-patching. A first-draft invitation prompt produces
plausible email that quietly fails a minority of real members: it tells a
graduate to prepare for exams, recites their major back as a data label, or reads
two true facts as a contradiction and retreats to generic.
Nearly every rule below exists because that happened in testing on real profiles;
where a rule is inference rather than something observed, it says so.

This skill builds the prompt that sits in an LLM node and composes a personalized
Society invitation email per NSLS member. It is a method with NSLS-specific
reference data attached. Apply the patterns to build a prompt; do not paste any
fragment as-is.

Members receive a high volume of marketing, so anything that pattern-matches to
an upsell gets discounted. The email must not read as one; it frames Society as
a benefit already theirs, with one specific personal reason to go talk to the
coach now. The single action is: open Society and start the conversation with the
coach (Society is the platform; the coach is the AI mentor inside it — never let
Society read as the coach).

## Build order

1. Pull current fill rates for all fields from wherever member records are mastered — today that is HubSpot (`/hubspot`), not the ESP; `/system-of-record` answers where a field lives if that moves. Measure coverage across the campaign's audience, not the whole CRM: a field that is sparse org-wide can be dense inside the segment you are mailing, and that difference is what decides whether it can carry the email or is only enrichment. Confirm graduation-date coverage and that the member-status field carries the NSLS-alum value.
2. Resolve life stage in Liquid (year/month integer math) into one label + relative timeframe. Read NSLS standing directly from member-status.
3. Assemble the resolved brief (name, chapter, NSLS standing if alum, life-stage label; major only if present and usable).
4. Write the prompt: brief up top; enrichment gated on presence; silence rules; the explicit alum-coexistence clause; coherence-then-fallback with the general potential angle; one-arc instruction; the exact four-output contract with the HTML/plain split; flat descriptions plus briefing-not-vocabulary.
5. Validate in sandbox on real profiles, on a weaker model, across all combinations, before live.

The rest of this skill is what each step needs: the method behind step 4, the
NSLS reference data behind steps 1–3, and the diagnosis and validation behind
step 5.

## Method (apply all of these)

**Decide in the data layer, write in the model.** Resolve every deterministic decision in Liquid before the model sees anything; leave the model only editorial choices (tone, phrasing, angle). This gives static-email consistency with generative specificity. Gate on presence in Liquid; put usability judgment in the prompt as natural language. This works because the LLM node's prompt field itself evaluates Liquid per profile before the prompt is sent to the model — that is what lets you resolve the brief per recipient right here in the prompt; confirm your platform does this.

**Resolve-then-write.** Compute the member's situation in Liquid and hand the model a plain resolved label to treat as fact and never re-derive. Do not leave past-versus-future to the model: date arithmetic across a whole audience is exactly the deterministic work the data layer should absorb, and a model asked to do it will misjudge a minority of profiles silently. Pass the resolved label and a relative timeframe only, never the raw graduation date or year, or the model will quote it. Passing today's date as context is fine — it is the arithmetic, not the date, that must not be delegated.

**Profile-first, dense-fields-carry-it.** Build the base email only on fields that are densely populated. Sparse fields are enrichment for the minority who have them; their absence must never be felt. See fill rates below.

**Voiced vs tone fields.** A field the member declared (their field of study) may be spoken to naturally. Passively tracked fields shape tone only and are never recited.

**Silence over guessing.** Use only provided fields. If absent, behave as if it does not exist — never reference it or gesture at a gap. Never quote a raw field value back as a label; speak to its meaning. When uncertain a claim is supported, leave it out.

A missing first name is the one absence that needs its own instruction, because the model's default is to paper over it: tell it to skip the salutation entirely and open the body differently rather than writing "Hi there" or "Hey there", which announces the gap in the first two words.

**Coherence, then fallback.** Read all details as one picture. If coherent, write specific. If not, fall back to the defined general angle (they were selected for NSLS because they have real potential; the coach is how they act on it) and write a clean generic email rather than force a story.

**One arc.** Choose one angle, then write subject, preheader, body, and CTA from it as one continuous thought — each part advancing the last, not restating it.

**Descriptions are briefing, not vocabulary.** Any situation description in the prompt must be flat and un-quotable, plus an explicit instruction that descriptions are context only and the model must write fresh language. Vivid description wording leaks into copy (see failure catalogue).

## NSLS reference data

### Fields and fill rates (observed in the CRM 2026-06-01 — re-pull, from the same system, before trusting)

Dense enough to build on:
- Preferred name / first name — ~99%
- Chapter name — ~96% (strong identity anchor; a static email cannot personalize per-chapter at scale)
- Membership status — ~96%
- Graduation date — populated enough to drive life stage, but check it against your own audience before relying on it; everyone without a usable date falls to the general angle

Populated but not usable:
- Number of core steps completed — 100%, and still worth leaving out of the prompt entirely. A field that can only shape tone and must never be stated rarely earns its space, and it tempts the model to leak it. Include it only if you have a specific, concrete tone use for an unambiguous extreme.

On the ESP profile these read as `first_name`, `chapter_name`, `graduation_date`, `major`, `nsls_member_status` and `nsls_role`. The CRM's own property names may differ — coverage is checked there, values are read here, and the two are worth reconciling before you trust a fill rate.

Sparse — enrichment only, never foundation:
- Major / field of study — ~14% (high value when present; absent is the normal case)
- School year, NSLS role, region — mid-teens percent
- Eboard positions, job title, self-reported aspirations — very low; treat as rare bonus

### The critical distinction: NSLS standing vs school graduation

These are INDEPENDENT and must never be conflated. "Alumni" means two different things:
- **NSLS standing** (from the member-status field) — whether they completed the NSLS program. "NSLS Alumni" vs "NSLS Member."
- **School life stage** (from graduation date) — whether they have graduated from school.

A person can be an NSLS alum still enrolled in school, or an NSLS member who graduated school years ago. One does not imply the other. Chapter names are named after schools and some contain the word "Alumni" — that is not evidence of either standing or enrollment.

The prompt MUST state, in plain terms, that being one and not the other is normal and not a contradiction. Under-explaining this causes the model to see a contradiction and fall back to generic (see failure catalogue). Read the NSLS-standing signal directly from the member-status field (`nsls_member_status`, carrying "NSLS Alumni" or "NSLS Member"); do not read the general role field first (`nsls_role` is the leadership field; where it is populated at all it reads "member" for nearly everyone, so it carries no standing signal and reading it first masks the field that does).

Once resolved, standing is almost always ignored. It is not a life-stage signal and it is not an angle. Show it to the model only when the member is an NSLS alum, and instruct that it earns at most one brief warm nod — "as an NSLS alum" is the whole treatment. Do not explain the program, do not build the email on it. Member is the default for nearly everyone, so it differentiates nothing: leave it out of the brief entirely rather than passing a value the model may feel obliged to use.

### Life-stage buckets (resolved in Liquid from graduation date)

Compute a whole-month distance from the date parts — `(grad_year - now_year) * 12 + (grad_month - now_month)` — and take past-versus-future from its sign. Work in integer year and month parts rather than subtracting timestamps or dividing days: that is the shipped approach, and it keeps the past/future boundary in plain integer arithmetic you can read off the number instead of relying on how a given templating language handles negative durations. Getting that boundary wrong is the most damaging error available here, because it inverts the whole email — a graduate told to prepare for exams. Resolve to one label; pass only the label and a relative timeframe.

The shape of the resolution, not the copy — the branch bodies and stage phrasing
are the campaign's, and the buckets below specify them:

```liquid
{%- comment -%}
  Life stage from graduation_date. Integer year/month parts only —
  no timestamp subtraction, no day division. The `| plus: 0` casts
  are what make these integers rather than strings; `%m` is zero-padded,
  so verify on your platform that "08" and "09" coerce before trusting
  it in August, and use `%-m` or strip the pad if they do not.
{%- endcomment -%}
{%- assign life_stage = 'unknown' -%}
{%- if customer.graduation_date -%}
  {%- assign now_year   = 'now' | date: '%Y' | plus: 0 -%}
  {%- assign now_month  = 'now' | date: '%m' | plus: 0 -%}
  {%- assign grad_year  = customer.graduation_date | date: '%Y' | plus: 0 -%}
  {%- assign grad_month = customer.graduation_date | date: '%m' | plus: 0 -%}
  {%- assign year_diff  = grad_year | minus: now_year -%}
  {%- assign months     = year_diff | times: 12 | plus: grad_month | minus: now_month -%}

  {%- comment -%} > 0, so the graduation month itself falls to the graduated side {%- endcomment -%}
  {%- if months > 0 -%}
    {%- assign life_stage = 'current_student' -%}
    {%- comment -%} future bucketing omitted here — see the buckets below.
      months drives the six-month gate; past it, production branches on
      year_diff (see the note under the buckets for why, and what it costs) {%- endcomment -%}
  {%- else -%}
    {%- assign life_stage = 'graduated' -%}
    {%- assign months_out = 0 | minus: months -%}
    {%- comment -%} bucket months_out at 24 / 60 / 120 {%- endcomment -%}
  {%- endif -%}
{%- endif -%}
```

Bucket the pre-graduation side finely — a student six months out and a student three years out need different emails, and collapsing them into "about a year or more" produces a bland message. The shipped buckets:

- Graduating within ~6 months (month count 1 to 6) — approaching the move into work; choosing a first direction, confident not pushy
- Graduating within about a year — has runway; prepare for what comes after, patiently, no pressure
- Graduating about two years out — early in the runway; patient preparation, direction over urgency
- Graduating about three years out — plenty of runway; long-view preparation, no urgency
- Graduating several years out — long runway; general forward preparation
- Recent graduate (up to 24 months since) — the school-to-work transition; only stage where "what comes next after school" fits
- Early career (25 to 60 months since) — building, next move; not fresh grads
- Established (61 to 120 months since) — career underway; direction, pivot, or advancement; no school references
- Experienced (beyond 120 months) — seasoned; high-level direction; no school or early-career framing
- Unknown (no usable date) — general potential angle

The past side buckets on the month count throughout. Past the six-month gate, the future side currently branches on the calendar-year difference instead, which is what is in production and works. Be aware of what it costs: with a calendar-year branch, a student eighteen months out reads as "about two years" while one sixteen months out reads as "about a year." Both are tone-setting phrases the model never prints, so the blast radius is small. Bucketing the future side on the same month count would remove the distortion — untested as of this writing, so treat it as a refinement to validate, not a correction to apply blind.

The life-stage line sets tone and angle only. Never state how long ago they graduated, never cite a graduation year.

### Major / field of study (the one enrichment field worth explicit rules)

Major is present for only a minority (~14%), but it is the highest-value personalization when it exists, so give it its own handling rather than leaving it to general judgment:
- Use it only if you can map it to a concrete direction that fits the member's resolved life stage — a skill to build or a role to aim for if still in school; the career they are building or already have if graduated (never coursework or exam prep for someone who has left school).
- If the value is vague, undeclared, or not confidently mappable to a real direction, ignore it. When in doubt, leave it out — a clean general email beats one forced onto a shaky field.
- Reference it naturally as part of a thought ("your work in nursing", "building a legal career"), never as a quoted data label ("as a Nursing major", "since you study Business").

### Output contract (must match the template exactly)

Each output name has to be the same string in three places: what the prompt tells the model to produce, what is declared as an output property on the node, and what the email template injects. Case is part of the string — pick either convention, but a property emitted as `CTA` and injected as `cta` renders empty with no error. Check all three before testing, not after. The shipped set:
- `subject_line` — plain text, no HTML, no quotes, ≤50 chars
- `preheader` — plain text, no HTML, ≤85 chars, advances the subject, must not start with "Society"
- `email_body` — HTML. Wrap each paragraph in its own `<p>...</p>`; those tags are what separate the paragraphs, so they are required. Use no other HTML tag. 2–3 short paragraphs, 80–100 words total, no single long paragraph, ends on a line leading toward starting the conversation with the coach
- `cta` — plain text label, no HTML, 3–6 words, points at what this member will discuss with the coach, not at the platform

Character limits are hard: models miscount, so verify actual lengths in QA and add a template-side backstop (e.g. `{{ subject_line | truncate: 50, "" }}`) so an over-long subject or preheader cannot ship.

### Voice and framing

- Frame Society as already theirs (ownership language). Never "free," "no cost," "complimentary." Never scarcity or time-limit words ("early access," "for now," "limited time," "spots," "claim," "act fast") — it is a standing benefit and those trigger the upsell suspicion. Giving the member a reason to act is motivational intent only, never a license for urgency wording: do not write "now," "today," or any deadline language in the copy.
- CTA points at starting the conversation with the coach, tied to the member's situation — not "learn more," not the platform's name.
- Tone: direct, warm, confident, phone-first, short sentences. Not corporate, not brochure, not hype.
- Do not open the body by telling the member they achieved or demonstrated something. Open by describing where they are.
- Chapter is their NSLS community, nothing more — never a place they currently study or are enrolled ("as a student at", "at [chapter]" are wrong). NSLS chapter names come from schools and some carry the word "Alumni"; that is not evidence the member is enrolled there now, nor that they are an NSLS alum. Keep the chapter and both alum meanings strictly separate.
- Maintain a banned-words list for hype/cliché; extend it as new tics appear in testing. Concrete starter list already earned in NSLS testing (do not ship without at least these): journey, unlock, excited to share, game-changer, next level, we're thrilled, take advantage of, dive in, elevate, navigate, achieve your goals, reach/realize your potential, incredible potential, incredible drive.

## Diagnosing a bad generation

When output is wrong, do not re-argue the prompt from scratch. Read the actual
four outputs for the profiles that failed, match the symptom to a class below,
apply that rule, and regenerate **on those same profiles**. A fix is confirmed
only when the profile that produced the failure produces a good email — not when
the average looks better. If a symptom matches nothing below, it is a new class:
add it here with its rule once you have the fix.

### Failure catalogue (each is a real failure found in testing; the rule prevents it)

- **Date blindness.** Model cannot tell past from future graduation. → Resolve life stage in Liquid, pass the label.
- **Incoherent four parts.** Subject/preheader/body/CTA generated independently, didn't tell one story. → One-arc instruction: one angle first, then all four.
- **Raw field recited.** "As a [field] major..." read like mail-merge. → Use the field's meaning naturally; never echo the raw value.
- **Alum contradiction → false generic.** Member who was one kind of alum but not the other read as contradictory data, model fell back to generic. → Spell out plainly that the two alum meanings are independent and coexisting is normal.
- **Vivid description leaked.** A phrase from a life-stage description appeared verbatim in subject lines across many recent grads. → Flatten descriptions; add briefing-not-vocabulary instruction.
- **Fallback firing.** Any unnecessary fall-through to generic was treated as unacceptable and root-caused (the cause was the alum under-explanation above). → Treat any needless fallback as a defect to fix at any volume, not the safety net "working."

## Red flags — STOP

The failure catalogue above is about the email going wrong. These two are about
misusing *this skill* — the only shortcuts not already covered by a rule
somewhere above.

- "The fill rates in this skill are close enough." → They drift. Pull current
  ones before writing; a field that was dense can thin out, and the entire
  dense-vs-sparse split depends on numbers that were only true when observed.
- "I'll paste this skill's wording into the prompt." → This is a method with
  reference data, not a prompt to copy. Write the prompt for the campaign in
  front of you.

## Rationalizations that show up under deadline

The rules above cost time, and the pressure to skip them arrives with a send
date attached. These are the four that have actually been argued.

| Excuse | Reality |
|--------|---------|
| "The model can work out from the graduation date whether they've graduated." | Date arithmetic across a whole audience is deterministic work, and a model asked to do it misjudges a minority silently — you find out when a graduate is told to prepare for exams. Resolve life stage in Liquid. |
| "It read well on the profiles I tested." | Test a spread of combinations, not a sample of profiles — junk-major, blank-chapter, and alum-but-still-enrolled are where it breaks, and each life-stage bucket behaves differently. |
| "The subject's about 50 characters." | Models miscount their own output. Measure the real length, and keep the template-side truncate backstop regardless. |
| "One member's email came out generic, but the rest are strong." | A needless fallback is a defect with a cause upstream, not an acceptable tail. Find what the data layer handed the model that it could not use. |

## Validation before any live send

1. Sandbox-test on real member profiles before any live send; read the actual four outputs. A prompt is validated by its output on real data, not by reading well.
2. Harden on a less capable model on purpose — a stronger model hides prompt weaknesses by inferring around them; a weaker model surfaces them (e.g. the false-generic fallback) so you fix the prompt. Model strength should be a bonus, not a crutch, and tuning only on the strong one means the errors it was absorbing surface the day the model changes.
3. Cover the combinations: each life-stage bucket, no-major, junk/vague-major, blank-chapter, and NSLS-alum-but-still-in-school (and its reverse).
4. Measure the actual character length of `subject_line` (≤50) and `preheader` (≤85) on the generated output. The model's self-report is not evidence.

## Related skills

- `/llm-email-workflow` — the pipeline this prompt sits inside: data profiling,
  audience segmentation, node wiring, safety nodes, rollout, and measurement
  against a champion email. Anything that is not the prompt itself belongs there.
- `/hubspot` — where member records are mastered today, and so where field fill
  rates come from. `/system-of-record` answers where a field lives if that moves.
- `/customerio` — go here to read the profile as the ESP actually sees it (which
  is what the prompt's Liquid resolves against, and may lag the CRM), and to pull
  delivery results after a send.
- `/connect` — if the Customer.io tools are not available.
