---
name: llm-email-workflow
description: >-
  Use when building or operating the pipeline around LLM-generated personalized
  emails in an ESP such as Customer.io; when a generated field renders empty in
  the email template; when a fallback, exit, or safety path fires unexpectedly;
  when segmenting an audience or splitting experiment arms for a generative
  email; or when planning a sandbox-to-live rollout or measuring a generative
  email against an existing champion. Covers any LLM email type — invitations,
  re-engagement, lifecycle, activation. For the prompt inside the LLM node, use a
  campaign-specific prompt skill — for Society invitations,
  society-invite-llm-email-prompt.
---

# Managing LLM emails and workflows end to end

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — profiling fields and fill rates, reading existing workflows,
   templates, segments, and campaign results. Runs without friction.
2. **Configuration** — building or editing a workflow, declaring node output
   properties, defining segments, sandbox sends to seed profiles. Ask first and
   name which workflow changes and how.
3. **Anything that puts mail in front of real people** — never proactively
   offered. Explain, confirm, then proceed:
   - **Going live**, even a small batch. Email cannot be recalled, and a bad
     generation reaches a real person with their own data in it. Gate on Stage 5.
   - **Changing entry conditions or split allocation on a running campaign** —
     that changes who is receiving mail right now, not at the next review.
   - **Widening the audience** past the batch size that was actually validated.

### Send the model a brief, not a record

The LLM node hands whatever the brief names to a model outside the ESP's trust
boundary, which makes the brief the place that decision gets made. Keep it to
what writing the email actually requires. The Society invitation brief is first
name, chapter, NSLS standing when the member is an alum, life-stage label, and
field of study when it is usable — no email address, no surname, no account
identifiers, and not even the raw graduation date, since life stage is resolved
to a label before the model sees anything. Resolving in the data layer is what
makes that possible: a decision made in Liquid needs no underlying field passed
through. This is minimization rather than anonymization — a first name plus a
chapter still identifies someone within a chapter of a few dozen — so the
question to ask before adding any field is whether the copy genuinely needs it.

## Purpose

This is the operational layer: the pipeline an LLM email lives in, from raw data to a small live send. It assumes the prompt inside the LLM node is built with a prompt skill written for that campaign — for Society invitations, `/society-invite-llm-email-prompt`. Where this skill points there, take the method and leave the NSLS reference data — the patterns hold for any campaign. Here we cover everything else — data, audience, node wiring, safety valves, testing, and rollout — and it generalizes across email types.

Core mental model: an LLM email is not "a message," it is a small system with four moving parts — the data resolution, the generation, the injection into the template, and the send under guardrails. Most failures live in the seams between them, not in the prompt. Design the seams deliberately. (The numbered Stages below are the build sequence and do not map one-to-one onto those four.)

## Diagnosing a live symptom

Arriving mid-incident, start here rather than reading the build sequence end to
end. Match the symptom, go to the stage, run the check. The instinct to fix a
seam failure by editing the prompt is what this table exists to interrupt.

| Symptom | Where | First check |
|---------|-------|-------------|
| One field renders empty, the generation otherwise looks right | Stage 3 | Is that property declared on the node itself, not merely requested in the prompt? Count declared outputs against what the template injects. |
| Every field renders empty for a recipient | Stage 3 | Do the node's output names match the template's injection names character for character? |
| The output-verification branch fired | Stage 4 | Which property was unpopulated, and why did the node not emit it? Treat as a system accident, not a caught error: do not hard-code the field, and raise it with your ESP's support — in a correctly wired workflow nobody reaches this branch. |
| The generic fallback fired for someone with usable data | Stage 4 | What did the data layer hand the model that it could not use? Root-cause upstream first; only then look at the prompt. |
| People entered who the email cannot serve | Stage 2 | Decide first whether the audience is wrong — narrowing the entry condition is the cheaper fix and usually the right one. If the audience has to stay as it is, then the prompt owes every segment in it a good email, so extend the prompt until it can serve them rather than letting them fall through. |
| Copy reads well but the personalization is wrong for the person | The prompt | Deterministic resolution belongs in the data layer — see the campaign's prompt skill. |
| Results trail the champion email | Stage 6 | Slice by data-richness and decompose the funnel before concluding anything. |

## Stage 1 — Gather and profile the data

Before designing anything, get real fill rates for every candidate field. This governs every later decision: which fields carry the base email, which are enrichment, which are safe to voice, which only shape tone.

- Distinguish densely-populated fields (build on these) from sparse ones (enrichment only).
- Distinguish actively-declared fields (can appear in copy) from passively-tracked fields (tone only, never recited).
- Pass empty values through explicitly as null rather than omitting them, so the generation layer can distinguish "not populated" from "not fetched." Instruct the prompt to treat null as absent.
- Inspect real distinct values before writing any value-matching logic. Do not design against imagined values; design against the actual distribution in the file. Handle only what really appears.

## Stage 2 — Build and segment the audience

- Decide the audience's entry condition and make it precise. Over-broad entry pulls in people the email cannot serve (e.g. wrong membership type), which then forces awkward fallbacks or exits.
- Keep personalization branching (per-person, data-driven, deterministic) strictly separate from experiment branching (per-arm, random). Personalization decides "who is this person"; experiment assignment decides "which variant are we testing." Never merge them into one conditional.
- Segment upstream where a segment needs fundamentally different treatment the prompt cannot gracefully bridge. Let the prompt handle within-segment variation; use workflow segmentation for across-segment forks that would otherwise strain a single prompt.

## Stage 3 — Wire the LLM node to the template

- The LLM node's output property names must match exactly what the email template injects. A mismatch renders empty with no error. Confirm both sides use identical names.
- Know how each property is rendered. A body rendered through a render-liquid mechanism will interpret HTML/Liquid; plain-text fields (subject, preheader, button label) must be emitted without tags or quotes. State the split explicitly in the prompt so the model does not wrap plain fields or drop structure on the body.
- Liquid in the LLM node's prompt field evaluates per-profile before the prompt is sent to the model, exactly like Liquid in an email body. That is what lets the data layer resolve the brief per recipient. Confirm this on your platform before relying on it.
- The node emits its outputs as named workflow properties the downstream email consumes. Confirm the node emits separately-addressable properties (not one blob to parse) and name them to the template.
- Declare every output property on the node itself, not just in the prompt. Asking the model for a field in the prompt does NOT create the workflow property — the node surfaces only the outputs it is configured to emit, so a property you requested in the prompt but never declared on the node is silently dropped even when the model generated it correctly. After wiring, count the declared output properties and confirm the number equals the outputs the template consumes (e.g. all four: subject, preheader, body, CTA) before testing. The tell for this bug is a good generation with one field mysteriously blank that you end up adding by hand.

## Stage 4 — Safety valves and guardrails (workflow-level)

Guardrails live in two places: content guardrails inside the prompt (never invent, no scarcity, etc. — see `/society-invite-llm-email-prompt`), and structural guardrails in the workflow. The workflow ones:

- **Output-verification node (post-generation).** Right after the LLM node, verify the recipient has a populated workflow property for every property the template injects. Should be 100% of users — in a correctly wired workflow this branch should never fire, so anyone who lands there is a system accident worth raising with your ESP's support. Don't overthink it — either route them into a 2-week+ delay node (a holding pen so the case surfaces instead of sending broken), or send one hard-coded generic template and then route into that same 2-week+ delay. Two things about that delay. First, it holds people; it does not tell anyone. Pair it with something that makes a human look — an owner who checks that branch's membership on a schedule, or an alert when anyone lands there — otherwise the failure is a silent drop. Second, **the branch has to end after the delay.** A delay node continues to whatever follows it, so a holding pen wired into the normal path just sends the broken email two weeks late, which is the outcome the branch exists to prevent. The delay is time to diagnose, not a deferred send. Two weeks is a practical floor rather than a magic number: it has to outlast the time it takes you to notice, diagnose, and fix, because nobody should leave the pen before the fix lands.
- **Defined generic fallback.** Ensure the prompt has an explicit, good generic path for incoherent/insufficient data, so the worst case is "correct but generic," never "confidently wrong." (Prompt-side, but a workflow concern because you decide when to allow it.)
- **Treat any needless fallback or exit as a defect, at any volume.** A safety path that fires is a disaster averted, not a system working as designed — something upstream handed the generation layer data it could not use. Root-cause that reason and fix it; do not accept "the net worked" as the end state. Scale changes only how many people received the degraded version, never whether it was acceptable.

## Stage 5 — Test before sending

The tier-3 gate. Do not send to a real person until all three are true:

1. **Sandboxed on real recipient data**, and the actual outputs were read — reading the prompt is not testing it. Anything with a hard limit gets measured rather than eyeballed, since models miscount their own output.
2. **Hardened on a deliberately weaker model**, and whatever that surfaced has been fixed in the system rather than absorbed by model strength.
3. **The real combinations are covered**, not just the easy path: every resolved segment, the no-enrichment case, the junk-enrichment case, missing-identity-field cases, and any "one thing but not another" combination that could be misread as contradictory.

Rules 1 and 2 are stated in full, with the reasoning, in
`/society-invite-llm-email-prompt` → "Validation before any live send"; the
Society-specific version of rule 3's combination list is there too. They govern
any LLM email, not only invitations.

## Stage 6 — Measure and roll out

- Roll out from sandbox to a small live batch, scaling deliberately. Do not go from test to full volume. Size the first batch so you can read every generated email by hand, and read all of them before scaling — that is what "the batch size that was actually validated" means in the safety block, and it is the only claim that lets you widen. At each step apply the Stage 5 checks to the live output, not only to sandbox output; the distribution is what changes with volume.
- If a generative approach is replacing or competing with an existing human email, run it against the real best current version (not a strawman) on a downstream outcome metric — the real action you want — not opens or clicks alone. Opens are inflated by privacy-protection and bot activity and do not measure whether the copy worked.
- Expect a distribution, not a single verdict. Generative output is a spread of quality per recipient; a first-draft system may not immediately beat a heavily optimized single email. Slice results by data-richness (rich-data segments vs thin-data segments) rather than reading only the headline number, so a narrow average loss does not hide a real win in the data-rich slice.
- Decompose the funnel: subject/preheader drive opens; body/CTA drive clicks-given-opens. Read them separately so a subject-line effect is not mistaken for a body effect or vice versa.

## Experiment structure (when testing variants)

- Prefer many cheap arms with shifting allocation over a fixed two-way split, since adding a generative variant costs almost nothing. Reallocate toward winners as evidence accumulates.
- If reallocation is manual (no automated bandit), run a batched approach: run a batch, read results, shift allocation by hand for the next batch. The split-percentage control is the reallocation lever.
- At very low volume you are doing QA, not optimization — there is no signal to reallocate on. Use the early phase to kill broken variants by reading output, not to pick winners by metrics.
- Keep experiment arms as separate workflow branches off a random split, so the split-percentage dial is your allocation control. Keep personalization logic inside each arm; keep arm assignment out of the prompt.

## Red flags — STOP

Three shortcuts that sound like good engineering judgment and are not. Each one
is a seam failure the stages above are designed to prevent.

- "One field came back blank, I'll just hard-code it." → That blank is the tell
  for an output property requested in the prompt but never declared on the node.
  Hard-coding it hides the bug and it returns on the next field you add.
- "It works in the sandbox, let's send to everyone." → Small live batch first.
  Sandbox validates the seams; only real volume validates the distribution.
- "The exit path caught it, so the guardrail worked." → A fired guardrail is a
  disaster averted, not the system working. Root-cause it at any volume — a net
  that never catches anyone is the target, and scale changes only the headcount.

## Rationalizations that show up under deadline

Distinct from the red flags above: these are the arguments for skipping a stage
rather than for shipping a broken one.

| Excuse | Reality |
|--------|---------|
| "The campaign is already designed — profiling fill rates now is busywork." | Every later decision descends from the real numbers: which fields carry the email, which are enrichment, which may be voiced. Profiling afterwards means rebuilding the prompt around what you find. |
| "Arm assignment is one more conditional, it can live in the prompt." | Personalization is per-person and deterministic; arm assignment is random. Merged, no result tells you which one produced the effect. |
| "Opens are up, so it is working." | Opens are inflated by pre-fetch and bots. Read the downstream action, and read subject/preheader separately from body/CTA. |
| "Widening the audience is just a number in the entry condition." | It changes who is receiving mail right now, on data you validated at a different size. Same tier-3 decision as going live. |

## The operating loop (how the whole thing matures)

Every rule in a mature LLM-email system exists because something broke. The loop: see a failure → add a rule (in the prompt or the workflow) → test that it never returns. Version deliberately: do not call something "V1" until it produces a good email for everyone in the audience, not just the easy profiles. Then tune in small versioned steps, each validated the same way. The system's quality comes from accumulated error-patching, so treat every failure as a permanent fix, not a one-off.

## Related skills

- `/society-invite-llm-email-prompt` — the prompt that goes inside the LLM node,
  with the NSLS member fields, life-stage bucketing, failure catalogue, and the
  two testing rules Stage 5 defers to.
- `/customerio` — querying Customer.io for fill rates, segments, and delivery
  results.
- `/data-intel` — for the Stage 6 downstream metric, which spans systems:
  Customer.io has who clicked, PostHog has what they did next.
- `/connect` — if the Customer.io tools are not available.
