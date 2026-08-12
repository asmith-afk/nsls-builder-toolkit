---
name: skill-creation
description: >-
  Use when you've just finished a complex, multi-step process with Claude
  Code and realize it could be a template others can follow. The experience
  is fresh, the micro details are still in context, the pattern is visible.
  This skill codifies the rubric for building skills that find their full
  shape — safety, purpose, diagnostic loops, cross-system awareness, and
  the micro/macro synthesis at every level.
---

# /skill-creation — The Rubric

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** (reading existing skills, analyzing patterns, researching MCP packages) — runs without friction.
2. **Configuration** (creating new skill files, modifying SKILL.md content) — ask permission, explain what will be created and where.
3. **Write to external systems** — never proactively offered. If explicitly requested: explain the risks, confirm, then proceed.

## Purpose

This skill codifies the fractal pattern that emerged from building `/data-intel`, `/connect`, `/slack`, and every other skill in this toolkit. Every well-built skill follows the same structure. This skill makes that structure followable by anyone — so the next person building a skill doesn't have to discover the pattern from scratch.

Every skill in the toolkit is an instance of this pattern — `/connect`, `/data-intel`, `/slack`, all of them. This skill codifies the pattern itself. And even this list of elements is not exhaustive — the rubric invites you to discover what's missing, not just follow what's here.

## The Pattern

A skill that finds its full shape has considered these elements — not as a checklist to follow blindly, but as dimensions to explore. Some won't apply. Some will matter more than others. The point is conscious consideration, not completeness for its own sake.

### 1. Safety Block (FIRST SECTION — when the skill interacts with external systems or modifies anything)

If the skill touches external services, files, or configuration, adapt the three-tier permission model to its domain. See `/connect` for a detailed example. The safety block goes FIRST — before purpose, before content. Each tier should name the specific operations that fall into it for THIS skill's domain. Not every skill needs all three tiers — a purely analytical skill may only need tier 1.

If the skill is purely informational (no tools, no external systems), a safety block may not be needed. Consider it consciously rather than including it by default.

### 2. Purpose (the soul)

One paragraph that says why this skill is alive — not just what it does, but what makes it more than a reference doc. What intelligence does it create that didn't exist before?

Bad: "Query PostHog analytics."
Good: "Makes PostHog's full analytical power accessible through conversation — not just running queries, but knowing which queries to run, what the results mean, and what to try next when the data doesn't look right."

The purpose statement is where the skill declares its reason to exist.

### 3. Trigger Moment (the frontmatter description)

The frontmatter `description:` field determines WHEN Claude invokes the skill. It should capture the moment — not summarize the workflow.

Bad: "Step 1: detect connections. Step 2: configure MCP. Step 3: verify."
Good: "Use when a skill says its tools aren't available, when MCP tools aren't loading, or when you want to add a new system."

The skill body describes HOW. The frontmatter description captures WHEN. Claude reads the description to decide whether to invoke the skill — if the description contains how-to steps, Claude may follow the description instead of reading the full SKILL.md.

### 4. Macro/Micro Synthesis

When relevant, a skill delivers both the big picture AND the grounding details. Macro without micro is a dashboard. Micro without macro is an anecdote. The synthesis — where the whole is greater than the sum of its parts — is intelligence.

What macro and micro look like depends on the domain:

| Skill | Macro | Micro |
|-------|-------|-------|
| `/data-intel` | Completion rates, funnel trends, cohort sizes, cross-system patterns | A user's actual words to the coach, the substep where people navigate backward 4x more, the chapter with 2x the enrollment rate |
| `/connect` | The three-tier permission model, environment detection, the service registry structure | Exact config JSON blocks, specific env var names, the precise error message from a failed MCP startup |
| `/posthog` | Dashboard management, funnel analysis, retention curves, experiment design | HogQL dialect gotchas, `$host` is null on server-side events, FunnelsQuery OR limitation |
| `/slack` | Channel landscape, team communication patterns, decision tracking | Specific channel names, reaction emoji counts, thread timestamps, who said what |
| `/n8n` | Automation health overview, workflow lifecycle, execution success rates | Telemetry suppression env var, partial vs full update protocol, trigger type limitations |
| `/airtable` | 24+ bases across departments, cross-base workflows, operational patterns | `filterByFormula` syntax, linked record ID resolution, the Railway proxy for Automation Tracker |
| `/skill-creation` | The 8 elements, the hierarchy, the fractal | This table you're reading — concrete examples from real skills |

Not every skill needs both. Some skills are primarily macro (big-picture frameworks). Some are primarily micro (reference docs with hard-won details). But always consider whether the other dimension would make the skill stronger.

### 5. Domain-Specific Micro

The deep, hard-won details that are unique to this skill's domain. These can't be invented — they come from actually using the system and hitting walls.

Examples of domain micro that can only come from real experience:
- PostHog's `$host` is null on server-side events (you discover this when your funnel returns 0 rows)
- n8n's tool names have an `n8n_` prefix (you discover this when your predicted permission entries don't match)
- Slack's first-party OAuth connector silently fails in VS Code (you discover this by sitting there for 10 minutes watching nothing happen)
- Customer.io's `opened` metric is inflated by email client pre-fetches (you discover this when open rates look impossibly high)

You can't write good domain micro from documentation alone. You have to use the system, fail, diagnose, and learn. That's why the best time to build a skill is right after you've been through that process.

### 6. Service Awareness (the hierarchy)

Skills that interact with external systems exist in a hierarchy:

```
/connect          → provides the connections
  /posthog        → deep PostHog expertise
  /slack          → deep Slack expertise
  /customerio     → deep Customer.io expertise
  /n8n            → deep n8n expertise
  /airtable       → deep Airtable expertise
  /braintrust-evals → deep Braintrust expertise
/data-intel       → orchestrates across ALL connected systems
/skill-creation   → the rubric that all skills follow
```

Domain skills that depend on external connections should:
- Reference `/connect` for setup: "If tools aren't available, run `/connect`"
- Reference `/data-intel` for cross-system intelligence: "For cross-system analysis, use `/data-intel`"
- Avoid duplicating setup instructions that belong in `/connect`
- Avoid duplicating cross-system orchestration that belongs in `/data-intel`

The general principle: setup → `/connect`. Domain expertise → individual skill. Cross-system intelligence → `/data-intel`.

### 7. Diagnostic Loop

**TRY → OBSERVE → DIAGNOSE → ADAPT → TRY AGAIN**

Skills that interact with external systems benefit from a diagnostic loop for when things don't work. Not a static troubleshooting FAQ — a live reasoning process. Not every skill needs one — but if things can fail at runtime, a loop helps.

The loop's character varies by domain:
- `/connect`: connection loop — try auth method → silent failure → diagnose environment → try different package
- `/data-intel`: query loop — run query → unexpected results → check filters → broaden → re-query
- `/posthog`: same as data-intel, plus HogQL-specific diagnostics
- `/n8n`: workflow loop — validate → find error → fix config → re-validate → test
- `/braintrust-evals`: eval loop — run experiment → low scores → check schema alignment → adjust → re-run
- `/slack`: search loop — channel not visible → try direct access → bot not invited → explain how to invite

The loop should never let the user stare at a screen that does nothing. It should never let them give up. There is always a path through.

### 8. Output Guidelines

Skills that produce output for humans (most of them) benefit from audience-aware formatting:
- Leadership wants narratives and decisions
- Engineering wants technical depth and reproducibility
- Marketing wants target lists and performance comparisons
- The board wants trends and revenue impact

Also: PII awareness, sample size warnings, source attribution when cross-referencing.

**House rule — question last, nothing trailing.** Any skill turn that ends by
asking the user something must put that question on the **last line**, with no
informational text after it. Silence after a question must unambiguously mean
"waiting on you," never "might still be talking." A buried question is the #1
way a guided flow reads as stalled — a real builder froze mid-`/setup` and asked
"did setup stall?" because a disclosure paragraph trailed the confirmation
question. Sweep for this whenever a skill scripts its own messages.

## Discovering the Full Shape

Before writing a skill, explore broadly at every level. The elements above are the columns (so far — you may discover more). The skill-creation process is about finding all the ROWS and all the CELLS.

For each element: cast the net wide. Find multiple examples. Each example is a seed. The more seeds you gather, the more complete the row. This is the micro/macro synthesis applied to the creation process itself — you can't write the macro (the pattern) until you've excavated enough micro (specific examples, edge cases, gotchas, things that surprised you).

The discovery IS the work. The breadth of the net determines the quality of the skill.

**How to know you've found the full shape:**
- Every element has been consciously considered (even if some don't apply)
- The domain micro comes from real experience, not documentation
- The diagnostic loop covers the actual failure modes you've encountered
- The cross-references point to the right skills in the hierarchy
- Setup lives in `/connect`, not duplicated in the skill
- The frontmatter description captures when to invoke, not how to use
- Someone who has never used this system could follow the skill and get real results

## The Fractal

The elements above are not a complete list. They're what emerged from the skills built so far. The next skill you build may reveal an element that isn't here yet — and that's by design. The rubric grows by being used.

The discipline is maintaining awareness of the whole web while working on any individual node — not losing sight of one level while focused on another. The pendulum swing between building the macro framework and testing it with micro examples IS the creation process. The system produces and maintains itself as a byproduct of doing the work.

## Practical Checklist

When building a new skill right now:

1. **Start with the experience.** What did you just do? What walls did you hit? What did you learn that isn't obvious?
2. **Draft the frontmatter.** Name and description. The description captures WHEN to invoke.
3. **Consider the safety block.** If the skill touches external systems or modifies anything, adapt the three-tier model to this domain. What's read-only? What's configuration? What's destructive? If it does, put it FIRST.
4. **Write the purpose.** One paragraph. Why is this skill alive?
5. **Pour in the domain micro.** Every gotcha, every failure, every non-obvious detail. This is the hard-won knowledge that makes the skill valuable.
6. **Structure the macro.** Organize the micro into sections that tell a coherent story.
7. **Add the diagnostic loop.** What goes wrong? What do you try? What's the next thing after that?
8. **Add output guidelines.** Who will read this output? What do they need?
9. **Wire up the hierarchy.** Reference `/connect` for setup, `/data-intel` for cross-system, other domain skills for related expertise.
10. **Check the full shape.** Walk through every element in The Pattern. Is anything missing? Is anything duplicated from another skill? Did you discover a new element that should be added to the rubric?
11. **Register it.** When the skill actually ships (merged / installed for real use), run `/register-automation` so it's on the org Automation Tracker — leadership visibility comes from that record, not from the merge. New skills, tools, and services count; pure bugfixes don't. Remind the builder of this at the end of any skill-creation session that produced a shippable skill.

## Recommended Creation Flow

Four tools sit in this space. Each tests a different quality axis. For most skills, use the **three-phase cascade** below (design → pressure test → audit). For broadly-released skills that need quantitative triggering reliability, add a fourth eval phase.

### The Three-Phase Cascade (default)

Run these in order. Each phase produces a real edit — not just a review.

**Phase 1: Design — `/skill-creation` (this skill)**
Walk through The Pattern above. Consider every element. Pour in domain micro while it's fresh. Produce a draft SKILL.md with the full shape — safety, purpose, macro/micro, domain-specific micro, service awareness, diagnostic loop, output guidelines.

**Phase 2: Pressure test — `superpowers:writing-skills`**
Run the Superpowers TDD-for-documentation gate:
- Rewrite the description to be **pure triggering conditions** — no workflow summary (Claude shortcuts workflows it finds in descriptions)
- Build the rationalization table — every shortcut Claude might take, with explicit counters
- Add the Red Flags — STOP list so Claude can self-check
- Close loopholes: "don't keep as reference," "don't adapt while testing"

This phase catches the class of bug where the skill reads fine but Claude talks its way around it.

Run this by saying: "pressure test this skill" or "review this skill for quality."

**Phase 3: Spec audit and polish — `skill-creator` (official Anthropic plugin)**
Final pass against the official Claude Code skill spec:
- Frontmatter compliance (name format, description length, field correctness)
- Standard markdown headings, not XML
- Under 500 lines, progressive disclosure for heavy reference
- `disable-model-invocation` for side-effect workflows *only if appropriate* (NSLS memory: usually avoid — makes skills invisible in new sessions)
- `allowed-tools` if specific tools are needed
- Imperative/infinitive writing style, not second person
- Quick Start section, concrete examples, one-level-deep references

Run this by saying: "audit this skill" or "check this skill against the spec."

### Optional Phase 4: Quantitative Eval — `skill-creator` eval/benchmark mode

For skills that will be triggered across many sessions and many users (broadly-released toolkit skills, not personal/time-boxed skills), run the same `skill-creator` plugin's eval loop:
- Subagents run the skill against real prompts
- Quantitative benchmarks with variance analysis
- Optimizes the frontmatter description for reliable auto-triggering

Skip this phase when: the skill is Kevin-personal, time-boxed, or used from a narrow set of trigger phrases Kevin controls. Run it when: the skill will be in the broader toolkit or personal-toolkit plugins and needs reliable auto-invoke.

Run this by saying: "evaluate my skill" or "run evals on this skill."

### Why Separate Tools?

| Tool | Quality axis | Sample failure it catches |
|------|--------------|---------------------------|
| `/skill-creation` (this) | Shape — is the pattern complete? | Missing wound/gotcha list, no diagnostic loop, generic instead of domain-micro |
| `superpowers:writing-skills` | Body hardness — does it survive rationalization? | Description summarizes workflow (Claude shortcuts), no rationalization table, no red flags |
| `skill-creator` (spec audit) | Spec compliance — does it conform to the Claude Code skill format? | XML tags, bad frontmatter, >500 lines, missing Quick Start, second-person drift |
| `skill-creator` (eval mode, optional) | Triggering reliability — does it auto-invoke for the right prompts? | Description matches too broadly (invokes for wrong topics) or too narrowly (misses obvious triggers) |

Skipping Phase 1 produces a skill that works but lacks depth. Skipping Phase 2 produces a skill that works in the happy path but breaks under pressure. Skipping Phase 3 produces a skill that violates the spec and may not load correctly. Skipping Phase 4 (when needed) produces a skill that's well-built but doesn't trigger reliably.

### Example: the `gary-meeting-prep` build

Run on 2026-04-18. Kevin's cascade: Phase 1 → 2 → 3 (no Phase 4 — personal skill, narrow trigger set Kevin controls).

- **Phase 1** surfaced: safety tiers, domain-specific wound patterns with dates, Gary's 8 mental models as a table, two-output discipline (brief vs. share-ready), composition over three existing skills.
- **Phase 2** caught: description was summarizing workflow (the CSO trap — Claude would have shortcut the skill). Added 9-row rationalization table, Red Flags — STOP list with 8 specific violations.
- **Phase 3** polished: pure-trigger description, Quick Start section, second-person drift fixed, confirmed <500 lines, honored NSLS memory rule against `disable-model-invocation`.

The build took ~30 minutes. A one-phase build would have shipped a skill with a fragile description and no rationalization defenses.
