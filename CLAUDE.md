# NSLS Builder Toolkit — Conventions

## What This Plugin Is

This plugin contains **organization-standard skills** for NSLS builders. These skills are maintained via GitHub PRs — do not edit them locally. Updates flow automatically when `main` is updated.

**Personal productivity skills** (open-day, close-day, close-week, log, familiar, person-intelligence, obsidian-setup) are in a separate plugin: [nsls-personal-toolkit](https://github.com/thensls/nsls-personal-toolkit). Run `/setup` to install them — they're optional and fully yours to edit.

## What Gets Installed

The install script sets up three things:

1. **NSLS Builder Toolkit** (this plugin) — org skills for slides, automations, Google Workspace, focus groups, deployment, web research
2. **Superpowers** (marketplace plugin) — process discipline: planning, debugging, verification, TDD
3. **Compound Engineering** (marketplace plugin) — development pipeline: brainstorm, plan, work, review, git

## Skill Routing by Complexity

### Quick tasks (< 30 min, single-step)
- Use **Superpowers** skills: `systematic-debugging`, `verification-before-completion`, `test-driven-development`
- These are lightweight — find root cause, verify the fix, move on

### Feature work (multi-step, needs a plan)
- Use **Compound Engineering** pipeline: `ce-brainstorm` → `ce-plan` → `ce-work`
- Produces durable requirements docs and implementation plans
- Use `ce-code-review` for code review (parallel reviewer personas, structured findings); `ce-doc-review` for plan/requirements docs

### Data intelligence (any question about users, systems, or operations)
- If tools for a system aren't available, run `/connect` to set up the connection
- Use `/data-intel` for cross-system questions that span multiple services
- Use individual domain skills (`/posthog`, `/slack`, `/customerio`, `/n8n`, `/airtable`, `/braintrust-evals`) for deep single-system work
- `/connect` → provides connections. Domain skills → deep expertise. `/data-intel` → orchestrates across all of them.

### NSLS-specific tasks (always)
- Use **NSLS Builder Toolkit** skills for anything NSLS-domain: slides, automations, Google Workspace, focus groups, deployment, web research, expense receipts (`/receipts` — clears Ramp's missing-receipt queue, dry run by default)
- These override generic skills when the task is NSLS-related

### Git operations
- Use **Compound Engineering**: `ce-commit`, `ce-commit-push-pr` (and `ce-worktree` for isolated branches)
- `/feature-branch-protocol-template` — optional template for builders who want their own work-discipline skill (setup, checkpoints, irreversible-step rules, final handoff). Includes Red's developer version as a seed.

### Process discipline (always active)
- **Superpowers** `using-superpowers` fires every session — it ensures skills get checked before acting
- `verification-before-completion` — always verify before claiming done
- `finishing-a-development-branch` — merge/PR decision guide

## PR Review — Macroscope

Macroscope is a code review tool — it pays off when the PR contains claims about APIs, SDKs, query syntax, data system behavior, or other technical facts it can verify against documentation patterns. It has a per-review cost. Use it where it earns its keep.

**Run Macroscope before merging when the PR contains technical claims.** Examples that qualify:

- API behavior notes (request params, response shapes, flags, auth scopes)
- Query or filter syntax (SQL, HogQL, Airtable formulas, HubSpot associations)
- SDK or library usage patterns
- Data-system specs (table schemas, field types, pipelines)

These live anywhere: `_shared/learnings/` corrections, `agents/` or `skills/` reference material, `docs/` runbooks.

**Skip Macroscope when the content is non-technical.** Process playbooks, coaching patterns, org decisions, communication templates — these need human domain review, not a code reviewer.

**Precedent:** PR #18 merged a learning entry with a wrong Airtable API claim. Macroscope caught it post-merge → follow-up PR #19. Running it pre-merge on that kind of content is the right call; running it on every knowledge PR is not.

## Builder Guardrails

People can build anything they like for themselves. The moment other people's
data, workflows, customers or eyes are involved, pay closer attention.

| Tier | Scope | Before building |
|---|---|---|
| **1 · Personal** | Only the builder uses the output. No member data. Nothing others depend on. | Nothing. Build. |
| **2 · Team-useful** | Someone else would use it, or it touches internal NSLS data. | Register it · light 1-pager · mentor check past ~2 days' effort |
| **3 · Company-wide / member-facing** | Members see it, it wears NSLS's name, or it writes to a system of record at scale. | Register before code · full design doc · reviewer + platform check |

**Escalation.** Some builds stay Tier 1 forever. Speak up when a build starts
being useful to someone else, runs past about a week, reaches into shared
systems, or becomes customer-facing.

**Enforcement.** Tier 1 is suggestions only. Tier 2 is a strong suggestion the
builder can decline — take the first no gracefully and carry on.
**Tier 3 always hard-blocks. Plus four specific situations hard-block at any
tier**, including Tier 1:

1. **NSLS work in a personal repo** — the git remote isn't an NSLS org.
2. **Tier 3 ship with no tracker record** — deploying something member-facing that nobody owns.
3. **Production write at scale** — bulk writes to HubSpot / Customer.io / Airtable prod with no reviewer and no rollback.
4. **Off-platform at Tier 2+** — non-Anthropic platform on a team- or company-facing build without Kevin's sign-off.

**Every hard block has an authorization route.** State the policy, then offer to
draft the note to Kevin. The answer is never just "no".

**Data rule.** Raw school lists (e.g. NCO lead data) must run through the Bedrock
PII gate with zero data retention. NSLS's own member data — PostHog, HubSpot, Hex
— stays on Claude under a do-not-train policy. *(The gate itself is not built yet;
this is written policy, not yet enforced.)*

**Read `_shared/references/guardrail-voice.md` before raising any guardrail.**
Tone is not decoration here — a guardrail that reads as policing teaches builders
to route around the toolkit, and then it protects nobody.

## Automation Tracking

**Always register automations** with `/register-automation` when you build something new. This feeds the org-wide Automation Tracker so leadership has visibility into what's being built, by whom, and at what stage.

## Google Workspace
- **Always use `gws` for Google Docs, Sheets, Slides, Drive URLs** — never WebFetch, WebSearch, or Firecrawl for google.com URLs
- Use `google-drive` skill for file upload/download/sharing operations

## Skill Creation (3-phase cascade)
When building a new skill, use three tools in sequence. Each tests a different quality axis:
1. **`/skill-creation`** (this toolkit) — design rubric: purpose, safety, macro/micro, diagnostics, domain-specific gotchas
2. **`superpowers:writing-skills`** — pressure test: pure-trigger description, rationalization table, Red Flags list, TDD-for-documentation discipline
3. **`skill-creator`** (official Anthropic plugin) — spec audit: official frontmatter compliance, Quick Start, line count, writing style

**Optional Phase 4**: For broadly-released skills that need reliable auto-triggering across many sessions, run `skill-creator`'s eval/benchmark mode for quantitative trigger accuracy. Skip for personal / time-boxed / Kevin-only skills.

See `/skill-creation` for the full cascade including a worked example (gary-meeting-prep build, 2026-04-18).

## Presentations
- Always ask "NSLS branded or Society branded?" before creating slides
- **NSLS**: Lexend Deca + Avenir, navy/teal/gold
- **Society**: HW Cigars + Inter, cream/yellow
