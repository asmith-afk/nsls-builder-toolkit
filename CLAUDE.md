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

## Every PR to main bumps the plugin version

Builders run this toolkit from a **version-pinned plugin cache**. Their daily
`claude plugin update` compares the version string in `.claude-plugin/plugin.json`
and nothing else — a merge that leaves it alone is a merge nobody receives. The
`plugin-version-bump` check (required on `main`) refuses a PR whose version is not
strictly greater than main's. Patch for fixes, minor for a new skill or behavior,
major for breaking changes to how builders install or use the toolkit.

If two open PRs bump to the same number, the second lands unversioned; the
session hook catches that by comparing the installed commit with the marketplace
HEAD and reinstalls in place (`ensure_plugin_fresh` in `hooks/session-start.py`).

**Choose a number above main AND above every open PR's claim, then re-check it
right before you merge.** Main moves while a PR sits, so a version that cleared
the gate on Monday fails on Wednesday, and matching main exactly fails as well —
the check wants strictly greater, never equal. Read the field before choosing:

```bash
for n in $(gh pr list --repo thensls/nsls-builder-toolkit --state open --limit 200 --json number --jq '.[].number'); do
  info=$(gh pr view "$n" --repo thensls/nsls-builder-toolkit --json headRefName,headRefOid --jq '.headRefName + " " + .headRefOid')
  printf '#%s %s ' "$n" "${info%% *}"
  gh api "repos/thensls/nsls-builder-toolkit/contents/.claude-plugin/plugin.json?ref=${info##* }" \
    --jq '.content' | base64 -d | grep '"version"' || echo "(no plugin.json on that head)"
done
```

Read the head by its commit SHA rather than its branch name: a PR opened from a fork has a branch
this repository does not have, so a name-based lookup quietly returns nothing and that PR's claim
never enters the comparison. The explicit limit matters for the same reason — `gh pr list` stops at
30 by default, and a claim it never printed is one you cannot clear.

Sitting above the whole field means nothing landing ahead of you knocks your PR
back to a failing gate. Whoever merges after you bumps again — one of the two
always has to, and it may as well be the PR that is not ready yet.

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

### Enforcement — two different mechanisms, never confuse them

**Blocked automatically, by a hook you don't control.** `hooks/guardrail-gate.py`
runs before every Bash/Write/Edit call and matches specific command shapes:

1. **NSLS work in a personal repo** — the git remote isn't an NSLS org.
2. **Tier 3 ship with no tracker record** — deploying something member-facing that nobody owns.
3. **Production write at scale** — bulk writes to HubSpot / Customer.io / Airtable prod with no reviewer and no rollback.
4. **Off-platform at Tier 2+** — non-Anthropic platform on a team- or company-facing build without Kevin's sign-off.

**You never assert these yourself. If the hook did not deny the call, nothing
was blocked** — so never tell a builder that policy blocked something that
already ran, or that it "would be" blocked. The hook speaks for itself; your job
is to help with what it said, not to predict or paraphrase it.

**Raised by you, conversationally — advice, not enforcement.** Everything else:
tier escalation, registration, design-doc depth, bringing in a mentor. The
builder may decline any of it. Never phrase advice as "policy blocks" or "isn't
allowed" — it isn't true, and one false claim teaches builders the whole
vocabulary is noise.

**Every hard block has TWO ways out, and both must appear.** The *compliance*
route (register it, assign a reviewer, move the repo) is not "not a flat no" —
it's a no with homework. The *authorization* route is the second one:
**if Kevin isn't named, the message isn't finished.** Offer to draft the note.

**When a builder declines, record it so you don't ask again.** Run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/guardrail-memory.py" record <topic> --note "<their reason>"
```

`<topic>` is short and stable — `registration`, `mentor-check`, `design-doc`.
Session start reads these back for the current build, so a decline sticks across
sessions rather than resetting every time. Asking a third time about the same
script is how the toolkit becomes nagware. Anything already listed at session
start is closed unless the scope genuinely escalated since.

**Report the guardrail moments only you can see.** The hard gates report
themselves; the conversational ones vanish unless you record them:

```
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/guardrail-event.py" <label> "<what happened>" [--automation <name>]
```

| Label | The moment |
|---|---|
| `flagged` | you raised a tier, registration or reviewer question |
| `mentor` | a reviewer or mentor actually got brought in |
| `migrated` | the repo moved to `thensls`, or the platform moved to Anthropic |
| `authorized` | the authorization route was taken on a hard block |
| `disputed` | the builder says a gate misfired — record it before you reply |

`blocked` and `proceeded` are already automatic; don't send those by hand.
Record what happened, never an intention — a reviewer who was suggested is
`flagged`, not `mentor`. One line, plain, in terms the builder would recognise
as their own build. It exits 0 whatever happens, so it can never cost them
anything, and repeats within a day are collapsed.

Why it matters: three of the four tiles on the guardrail page are fed only by
these, so a session where the guardrails worked perfectly and nothing was
reported reads, to Kevin and Jenna, exactly like a session where they did
nothing. `disputed` is the load-bearing one — it is the only route by which a
gate that fires wrongly ever becomes visible.

**If a bulk-write block was against a test base**, take them at their word and
remember it:

```
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/guardrail-memory.py" trust-base appXXXXXXXXXXXXXX
```

Airtable sandboxes and real bases share a hostname and differ only by base ID,
so the gate can't tell them apart — which meant rehearsing a backfill against a
copy got blocked for being careful. One declaration per base, then it's silent.
Only the base IDs actually in the blocked command; never guess one.

**Ambiguous tier?** Ask the single question that resolves it, and treat the build
as the **lower** tier until it's answered. Never rule on an unsettled question.

**If they accept a repo transfer**, the steps are: repo Settings → Danger Zone →
Transfer ownership → `thensls`. History and their ownership both survive. Two
things worth doing in the same sitting — scan the git history for credentials
first (private repos get no secret scanning), and add reviewers explicitly
afterwards (the org default permission is none). Give this *after* they say yes;
it doesn't belong in the block itself.

**Reviewers.** Kevin — platform, architecture, anything member-facing; final say,
usually turns these round inside a day. Davo — Tier 2/3 design, skills, agentic
flows. Jenna — adoption, UX, HR-ops surfaces. Plus a domain reviewer when the
build crosses into their flow.

**Data rule.** Raw school lists (e.g. NCO lead data) must run through the Bedrock
PII gate with zero data retention. NSLS's own member data — PostHog, HubSpot, Hex
— stays on Claude under a do-not-train policy. *(The gate itself is not built yet;
this is written policy, not yet enforced.)*

**Read `_shared/references/guardrail-voice.md` before raising any guardrail.**
Tone is not decoration here — a guardrail that reads as policing teaches builders
to route around the toolkit, and then it protects nobody.

### The exploration log — "log it"

The tracker used to hear about builds only when they shipped: of 97 rows, just
8 ever entered at an early stage, none since mid-July. That is how Royce's
knowledge base and Dejeahn's BI tool got built in parallel. The exploration log
moves the first record to the moment a build becomes real — pitched as credit,
never as paperwork.

**The moment.** A build acquires an identity: it has a name or a clear purpose,
a repo exists, or they've returned to it a second time. Not ten minutes into
tinkering. Offer ONCE:

> This is turning into something. Want me to log it? You get builder credit for
> the exploration now, and I'll check whether anyone else at NSLS is circling
> the same ground — it takes one sentence from you.

**If they say no**, record it and never raise it again for this build:

```
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/guardrail-memory.py" record exploration-log --note "<their reason>"
```

**If they say yes** — three steps, ~15 seconds of their time:

1. **Check for neighbours first — in BOTH places, because they hold different
   things.** The registry knows what has been *registered*; the machine knows
   what has been *built*. Most skills never get a registry row, so for anything
   skill-shaped the second check is the one that finds the neighbour:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/similar-skills.py" "<name>" "<their one sentence>"
   ```

   It prints installed skills covering the same ground, or nothing. Treat a hit
   exactly like a registry hit below — an offer, never a wall. Then
   `POST /similar` with `{"name", "description"}` (their one sentence). Three
   outcomes:
   - A match with `from_idea_backlog: true` — someone already parked this exact
     idea in the registry. Offer to **claim that row** (update it: their builder
     link, Stage → `Exploring`, their description) instead of creating a twin.
     Framed as good news: the idea was already wanted.
   - Another live match — mention it as an offer, never a wall: *"Royce logged
     something adjacent in June — want me to draft him a quick
     we-might-overlap note before you sink more time?"* Their call entirely;
     parallel exploration is often fine. Never auto-send anything.
   - Nothing — say nothing about the check. Silence, not "no duplicates found".
     Together the two checks read **registered NSLS automations and the skills
     installed on this machine** — not Jira, not Asana, not repos nobody
     registered, not a colleague's unshipped work. A clean result is the
     absence of a signal, never evidence that nobody else is circling this
     ground. So never tell a builder their ground is clear: that sentence is
     not one these checks can support. Royce's NCO skill and the BI squad's
     Jira ticket for the same reporting are what it costs when someone
     believes it.
2. **Log it**: `POST /register-automation-with-builder` with their name, the one
   sentence as description, `stage: "Exploring"`, `scope: "Personal"`, repo URL
   if one exists. Skip every checklist, reviewer, and design-doc question —
   those belong to Tier 2/3 shipping, not to this.
3. **Close warm, one line**: logged, credit recorded, and they own the row.

**Graduation, not re-registration.** When the build later escalates — someone
else starts using it, it ships, it turns member-facing — the normal tier
conversation happens exactly as written below, but it UPDATES their existing
row (scope, stage, reviewer). Nobody who logged an exploration ever fills in a
registration form; their exploration grows up.

**What this never becomes:** a second nag channel. One offer per build, the
decline sticks across sessions, and a declined exploration log is NOT grounds
to re-raise registration later unless the scope genuinely escalates into
Tier 2/3 territory — that conversation stands on its own rules below.

## Automation Tracking

**Register Tier 2 and Tier 3 automations** with `/register-automation` — anything
someone else would use, anything touching NSLS data, anything member-facing. This
feeds the org-wide Automation Tracker so leadership has visibility into what's
being built, by whom, and at what stage.

**Tier 1 personal builds need nothing.** Offer registration once, lightly, only if
the builder would want credit or others might want the tool — then drop it. Don't
raise it again. Nagging someone about a script only they will ever run is how
builders learn to work outside the toolkit, which costs far more than the missing
row. See § Builder Guardrails above.

## Claude Usage Collector

Session start (`hooks/collector_bootstrap.py` on a Mac, `.ps1` on Windows)
quietly installs the NSLS Claude usage collector in the background when it's
missing. That's the same installer as the self-serve link, at most once a
day and five times in all. It prints nothing. The builder hears about it
through Signal's enrollment DM. If a builder asks what it is or how to stop
it: it reports session counts and skill names, never prompts, responses or
files. `NSLS_COLLECTOR_OPTOUT=1` stops the automatic install. Details are in
the README under "Claude Usage Reporter".

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
