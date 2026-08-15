---
name: product-design
description: >-
  Product thinking guardrail for NSLS automations. This skill should be used when
  the user says "product design", "design review", "run a focus group", "create
  DESIGN.md", "check the design intent", "review this change against the design",
  or is proposing a UX change in a repo that has a DESIGN.md. Also use when
  scanning a repo and DESIGN.md is missing for a Department+ scope automation.
  This skill helps builders without product experience make good UX decisions.
---

# Product Design

A teaching tool for product thinking in NSLS automation repos. Three modes: generate a design intent file, review proposed changes against it, or run a simulated focus group.

## Key Principle

The guardrail is about what the user sees and does, not how it works behind the scenes. Technical complexity is sometimes necessary. User experience complexity is almost always bad. The SLT bot can be technically sophisticated — the person using it should feel like it's simple.

## DESIGN.md

Each automation repo gets a `DESIGN.md` in its root that captures:
- What the automation does (from the user's perspective, no technical details)
- Who the customers are (segments with context and flows)
- UX principles (numbered rules that changes get evaluated against)
- What it should NOT become (explicit anti-patterns)
- How to measure success (adoption and satisfaction signals)

Read `references/design-md-template.md` for the complete template and a worked example.

---

## Mode 1: Generate

**When to use:** Repo has no DESIGN.md, or builder asks to create one.

### First — pick the depth

Depth follows the guardrail tier, which is the automation's `Scope` in the
tracker. Don't ask the builder to choose; infer it, say which you're using, and
let them push back.

| Depth | When | Time | Must contain |
|---|---|---|---|
| **Light** | Tier 2 (`Department`), or a Tier 1 build that escalated | 20–30 min | Purpose, who uses it, systems touched, ROI, effort, risks |
| **Standard** | Tier 2 with Medium/Large effort; Tier 3 internal-facing | 1–3 hrs | Light + stack components, data flow, success criteria, failure modes, rollout, reviewers |
| **Extensive** | Tier 3 (`Company-wide`) member-facing, or central to org value | half day+ | Standard + UI/message mockups, edge cases, sandbox/allowlist, monitoring + rollback |

Jenna's SSI design doc is the reference for **Extensive** — that's the bar when
work is member-facing and central to the org.

**Tier 1 needs no design doc at all.** If the build is genuinely personal, say so
and don't run this mode.

At Light depth, answer questions 1, 2, 5 and 6 below and skip the rest — a
1-pager that actually gets written beats a template that doesn't.

### Then — the conversation

Walk through it one question at a time:

1. **What does this do?** — In plain language, from the user's perspective. No technical details.
2. **Who uses it?** — Define customer segments. For each: who they are, their context when they encounter it, which flows they use.
3. **What should it feel like?** — Derive numbered UX principles. Each must be specific enough to say yes/no about a proposed change.
4. **What should it never become?** — Name the anti-patterns explicitly.
5. **Where does the user touch it?** — Channel, trigger, user actions, output they see.
6. **How will you know it's working?** — Define what adoption looks like, satisfaction signals, and red flags.

Read `references/design-md-template.md` and output a populated DESIGN.md in the repo root. The builder reviews and commits it.

### Then — link it back

Write the doc's URL to `Design Doc URL` on the automation's tracker record via
`/register-automation`, and set `Review Status` to `Requested` for Tier 2+. A
design doc nobody can find from the tracker doesn't close the guardrail.

For Tier 3, assign a `Reviewer` in the same pass — Kevin covers member-facing
and platform, Davo covers Tier 2/3 design and agentic flows, Jenna covers
adoption, UX and HR-ops surfaces.

**Read `_shared/references/guardrail-voice.md` before raising the depth
requirement.** Lead with what the doc buys them, not with what's required.

---

## Mode 2: Review

**When to use:** A builder proposes a change that touches what users see or do (new prompts, different flows, changed wording, new steps, removed features, changed timing).

**NOT triggered for:** Backend-only changes (new data source, refactored handler, performance fix, internal logging).

### Pre-checks

- **Missing DESIGN.md:** If the automation is Department+ scope, prompt the builder to run Generate Mode first. If Personal scope, skip review.
- **UX change detection:** If changes touch files commonly associated with user interaction (message templates, prompt strings, Slack handler responses, reminder text), ask the builder to confirm whether this is a UX change.

### Review Process

1. Read `DESIGN.md` from the repo root
2. Evaluate the proposed change against each numbered UX principle
3. Check for conflicts with "What This Should NOT Become"
4. Identify which customer segments are affected
5. Give a verdict:

**Go ahead** — Change aligns with design intent. Remind the builder to update DESIGN.md if the interaction surface, segments, or principles changed. Offer to draft the update and add a change log entry.

**Reconsider** — Specific conflict identified. Explain which principle is at risk, why, and suggest an alternative that preserves the intent of the change without breaking the principle.

**Run a focus group first** — Change is significant enough to warrant simulated user feedback. Offer to run Mode 3.

### Tone

Educational, not blocking. Be specific. Reference principle numbers. Example:

> "This adds a second decision point to the Friday flow. Your UX principle #1 says 'one question at a time.' Here's how you could keep the new feature without breaking that principle: [suggestion]"

The goal is to teach product thinking, not gatekeep. Kevin owns PRs and can always wind things back.

---

## Mode 3: Focus Group

**When to use:** Review Mode recommends it, or builder invokes directly.

Read `references/focus-group-protocol.md` for the full protocol.

### Quick summary:

1. Read customer segments from DESIGN.md
2. Generate 3-5 personas per affected segment, tuned to the segment description (not generic)
3. Present the proposed change: what changes, for whom, before vs. after
4. Run each persona through: gut reaction, friction, predicted behavior, one question
5. Synthesize across segments and map findings to UX principles
6. Produce a structured report with verdict: proceed as-is, modify, or rethink

### Scope-specific persona guidance:

- **All Employees** — span departments, tenure, tech comfort
- **Managers** — vary team size, management style, trust level
- **SLT** — vary strategic focus, time pressure, change fatigue
- **Customer Facing: Advisors** — school professionals, busy, managing many students, expect polished tools, low tolerance for confusion
- **Customer Facing: Members** — college students, mobile-first, short attention spans, expect consumer-app quality, will abandon if friction is high

---

## Scope-Based Enforcement

| Scope | DESIGN.md | Review Mode | Focus Group |
|-------|-----------|-------------|-------------|
| Personal | Optional | Not triggered | Not triggered |
| Department | Required | Triggered on UX changes | Recommended for major UX changes |
| Company-wide | Required | Always triggered on UX changes | Required before major UX changes |
| Customer Facing: Advisors | Required | Always triggered | Required for any UX change |
| Customer Facing: Members | Required | Always triggered | Required for any UX change |

**UX change** = any change to what the user sees or does.

**Major UX change** = new interaction flow, changed prompts that affect how users respond, removed features, or changes affecting more than one customer segment.

Customer-facing scopes use "any UX change" (not just major) because these users didn't choose to work at NSLS.

---

## Integration with CLAUDE.md

Recommend adding this line to each automation repo's CLAUDE.md:

```
When proposing changes that affect what users see or do, read DESIGN.md first
and evaluate the change against its UX principles before proceeding.
```

This provides a passive guardrail even without explicitly invoking the skill.
