# NSLS Builder Toolkit

Organization skills for every NSLS builder — building, tracking, deploying, presenting, and researching. Install once, get updates automatically.

Also installs **Superpowers** (planning, debugging, verification) and **Compound Engineering** (brainstorm, plan, review, git) plugins.
The NSLS Builder Toolkit gives every NSLS employee with Claude Code a set of skills for building, tracking, querying data, and deploying automations. Install once, get updates automatically.

## Install

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/thensls/nsls-builder-toolkit/main/install.sh | bash
```

**Windows (PowerShell):** `install.sh` needs `bash`, so Windows builders clone
the toolkit and run `install.ps1` instead. Clone it, then run the installer:
```powershell
$dst = "$HOME\.claude\local-plugins\nsls-builder-toolkit"
if (Test-Path "$dst\.git") {
    git -C $dst pull
} else {
    New-Item -ItemType Directory -Force "$HOME\.claude\local-plugins" | Out-Null
    git clone https://github.com/thensls/nsls-builder-toolkit.git $dst
}
powershell -NoProfile -ExecutionPolicy Bypass -File "$dst\install.ps1"
```
`install.ps1` installs the marketplace plugins (Superpowers + Compound
Engineering, migrating off Every's renamed marketplace), and registers the
Windows SessionStart hook (`hooks/session-start.ps1` — pull + sync + tracker
ping) and PreToolUse skill hook (`hooks/skill-event.ps1`) in `settings.json`,
since the bundled hooks use `python3`/`bash`. Idempotent; re-run anytime.
Restart Claude Code afterward.

Then open Claude Code and say `/setup` to connect your tools and optionally install personal productivity skills.

## Org Skills

| Skill | What it does |
|-------|-------------|
| **/setup** | Onboarding — connect tools, install personal skills |
| **/register-automation** | Track your work in the NSLS Automation Tracker |
| **/product-design** | UX guardrail — DESIGN.md, reviews, focus groups |
| **/nsls-focus-group** | Test ideas with simulated employee panels |
| **/nsls-slides** | Branded NSLS/Society presentations |
| **/frontend-slides** | Build HTML presentations |
| **/gdoc-build** | Build nicely-formatted NSLS/Society Google Docs — real Word tables, branded headers, headings, code blocks. Survives copy-paste into canonical docs. |
| **/google-drive** | Google Drive file management |
| **/google-slides-api** | Edit existing Google Slides via API |
| **/gws** | Google Workspace Sheets CLI |
| **/netlify-deploy** | Deploy and preview static pages |
| **/deployment-guide** | How to deploy to Railway, Airtable, GAS, Cloudflare |
| **/nsls-auth** | Wire "Sign in with NSLS" SSO into any NSLS-controlled app via auth.nsls.org (web, mobile, Netlify static sites) |
| **/pydoc-pipeline** | Generate documentation from Python code |
| **/web-research** | Structured web research |
| **/interrogate** | Deep-dive investigation skill |
| **/signal-setup** | Wire Claude Code into Signal — query Quick Notes, wins, friction, team summaries. Managers + execs only. |
| **/society-invite-llm-email-prompt** | Build the LLM-node prompt for personalized Society member-invitation emails — NSLS data fields and fill rates, life-stage resolution, voice rules, and the failure catalogue from real testing |
| **/llm-email-workflow** | The pipeline around an LLM email — data profiling, audience segmentation, node wiring, safety nodes, sandbox-to-live rollout |
| **/feature-branch-protocol-template** | Template for building your own work-discipline skill — setup, checkpoints, irreversible-step rules, final handoff. Copy to `~/.claude/skills/` and fill in your own preferences. Red's developer version included as a seed. |

## Strategy & Knowledge Work

For non-software work — campaigns, strategy docs, briefs, research synthesis. The four `kw:` skills form a pipeline: brain dump → structured plan → reviewed → learnings captured.

| Skill | What it does |
|-------|-------------|
| **/kw:brainstorm** | Brain dump and compile NSLS knowledge before structuring a plan. Use after a meeting or when you have scattered inputs that need organizing. |
| **/kw:plan** | Research what NSLS already knows, then structure a plan grounded in LOPs and past learning. Use after `/kw:brainstorm`. |
| **/kw:review** | Two-reviewer parallel check on a plan — one audits LOP grounding and goals, the other audits every number for source and freshness. P1/P2/P3 findings before you share. |
| **/kw:compound** | Extract 1–3 learnings from a finished session and route them to the right tier (personal Obsidian, team `_shared/learnings/`, SLT knowledge graph). |

Use these for strategy/knowledge work. For software features use `/ce-brainstorm` → `/ce-plan` → `/ce-work` → `/ce-code-review` from the Compound Engineering plugin. For new automations start with `/interrogate`.

## Strategy Studio

The Strategy Studio skills let you capture, interrogate, and stress-test business bets into the org's portfolio pipeline. Bets flow through two entry points:

| Skill | What it does |
|-------|-------------|
| **/bet-studio** | Portfolio front door and router — surface all open bets, filter by status/owner, navigate to detail |
| **/bet-idea** | Capture, interrogate, stress-test a business bet and push it into the funnel |
| **/bet-research** | Work a research-stage bet riskiest-assumption-first — self-serve market research, Customer Forces interviews, sizing both directions, roadshow sprints — to the research→planned gate |
| **/bet-plan** | Harden economics (downside/base/upside), execution & risk, and a sell-first proof plan with thresholds — then an adversarial review — to the planned→live gate |

**Setup:** Tokens are minted by Kevin — one per person, SLT authors only. To enable these skills, set your token in `~/.zshrc`:

```bash
export STRATEGY_MCP_TOKEN=<your-token-here>
```

The engine lives at `https://market.nsls.org/` (repo: `thensls/market-exploration`).

## Bundled Plugins

These are installed automatically by the install script:

| Plugin | What it gives you |
|--------|-------------------|
| **Superpowers** | `/brainstorm`, `/debug`, `/verify`, `/plan`, `/tdd` |
| **Compound Engineering** | `/ce-brainstorm`, `/ce-plan`, `/ce-work`, `/ce-code-review`, `/ce-commit` |

## Personal Productivity Skills (Optional)

During `/setup`, you can optionally install personal productivity skills — daily planning, weekly reviews, project logging, relationship tracking. These are Kevin's personal template — fork them, edit them, make them yours. They live in a [separate repo](https://github.com/thensls/nsls-personal-toolkit).
## First-Time Setup

After installing, run `/connect` in Claude Code to connect your data systems (PostHog, Airtable, Slack, Customer.io, n8n, and more). Each connection persists across sessions — you only do it once per system.

## Data Intelligence Architecture

```
Layer 4: DISCOVERY / SYNTHESIS
├── /full-shape              — Find the dimensions of unnamed things.
│                              Cast the net, explore every angle,
│                              discover what it IS.
├── /investigation           — Find ground truth across all sources.
│                              Query first, explain second. Report
│                              what you found and where you found it.
├── /data-model-discovery    — Map what's in a newly connected system.
│                              Explore objects, properties, join keys,
│                              and produce a landscape doc + platform
│                              skill + data-intel integration.
└── /skill-creation          — The rubric that grows by being used.
                               Codify a lived process into a
                               repeatable skill with safety, purpose,
                               diagnostic loops, and cross-references.

Layer 3: CROSS-SYSTEM ORCHESTRATION
└── /data-intel              — The synthesis of micro and macro. Join
                               data across all connected platforms,
                               translate plain English into cross-system
                               queries, deliver both high-level metrics
                               AND the human moments that give them
                               meaning.

Layer 2: PLATFORM SKILLS (one per data source)
├── /posthog                 — Query behavioral analytics, build
│                              dashboards, investigate errors, run
│                              HogQL, manage feature flags. Knows
│                              NSLS-specific gotchas and event shapes.
├── /hubspot                 — Search members by chapter/status, look
│                              up enrollment history, check induction
│                              milestones, explore chapter health,
│                              investigate support tickets. Knows NSLS
│                              custom properties and Feather sync.
├── /customerio              — Query campaign performance, message
│                              history, member lookup, segment analysis.
│                              Knows prefetch vs human opens, API
│                              distinctions, cio_id vs id.
├── /airtable                — Navigate 24+ bases across every
│                              department. Find the right table, query
│                              records, understand schema. Knows
│                              access limitations and change blast
│                              radius.
├── /slack                   — Read and search team conversations,
│                              threads, decisions, reactions. Find
│                              context that lives in people's words,
│                              not databases.
├── /n8n                     — Manage automation workflows. Create,
│                              validate, test, check executions. Knows
│                              destructive tool guardrails and trigger
│                              limitations.
├── /braintrust-evals        — Run LLM evaluations, compare models,
│                              build datasets, define scoring. Knows
│                              prompt-schema alignment failures and
│                              strict-mode issues.
├── /gws                     — Google Workspace CLI for Sheets, Docs,
│                              Slides, Drive, Gmail, and Calendar.
│                              Read, edit, and manage Google Workspace
│                              content. Authenticated and free.
├── /web-research            — Web research via Google AI Mode.
│                              Synthesized answers with citations from
│                              100+ sources. Use instead of raw
│                              WebSearch for any research question.
│
│   Seeds (auth available, not yet explored):
├── /snowflake               — (seed) Data warehouse. Historical data,
│                              cross-system joins, reporting.
├── /rippling                — (seed) HR / ATS. Headcount, departments,
│                              hiring pipeline, people operations.
├── /asana                   — (seed) Project management. Tasks,
│                              timelines, team workload.
├── /atlassian               — (seed) Jira/Confluence. Engineering
│                              tickets, documentation, sprint tracking.
├── /notion                  — (seed) Team wiki, docs, databases.
│                              Structured knowledge and planning.
├── /figma                   — (seed) Design files, components,
│                              prototypes. Visual decision history.
└── /hex                     — (seed) Data notebooks, SQL queries,
                               shared analytics. Collaborative
                               data exploration.

Layer 1: INFRASTRUCTURE
└── /connect                 — The bridge between credentials and data.
                               Detect what's connected, walk through
                               setup for what's missing, handle the
                               failures that will happen along the way.

Layer 0: THE SCHEMA
└── /system-of-record        — The unified data model made conversational.
                               9 domains, 95 tables, Person.id as
                               universal anchor. Knows both the target
                               schema AND the current fragmented reality.
                               The foundation everything maps onto.
```

**Layer 0** is the schema — the unified data model that defines what member data looks like when all systems agree. **Layer 1** gets the pipes connected. **Layer 2** knows how to use each pipe well — one skill per system, with safety tiers, diagnostic loops, and org-specific gotchas. The seeds are systems with auth available but not yet explored — each one is a `/data-model-discovery` run waiting to happen. **Layer 3** is cross-system intelligence — combining data from multiple Layer 2 skills to answer questions no single system can. **Layer 4** is the meta layer — skills that create new skills, discover unnamed patterns, map new data sources, and find ground truth.

They form a cycle: `/data-model-discovery` explores a new system → maps it against `/system-of-record` → produces a platform skill (via `/skill-creation` rubric) → feeds into `/data-intel` → which `/investigation` can query for ground truth → and `/full-shape` can use to define patterns nobody's named yet. Every seed that gets connected and explored adds another row to Layer 2 and another dimension to Layer 3.

## Builder Skills

| Skill | What it does |
|-------|-------------|
| **register-automation** | Track your work in the NSLS Automation Tracker |
| **product-design** | UX guardrail — generate DESIGN.md, review changes, run focus groups |
| **nsls-focus-group** | Test ideas with simulated employee panels |
| **nsls-slides** | Create branded NSLS/Society presentations |
| **frontend-slides** | Build HTML presentations |
| **gdoc-build** | Build nicely-formatted NSLS/Society Google Docs (real tables, branded headers) |
| **google-drive** | Google Drive file management |
| **google-slides-api** | Edit existing Google Slides via API |
| **netlify-deploy** | Deploy and preview static pages |
| **pydoc-pipeline** | Generate documentation from Python code |
| **gws** | Google Workspace Sheets CLI |
| **deployment-guide** | How to deploy to Railway, Airtable, GAS, Cloudflare |
| **nsls-auth** | Wire SSO via auth.nsls.org into any NSLS-controlled app |
| **web-research** | Web research with AI overview extraction |
| **macroscope** | Turn a Macroscope review bot's PR comments into one root-cause fix pass — fix the class, not each comment |
| **interrogate** | Scope a new project through structured conversation |
| **society-invite-llm-email-prompt** | LLM-node prompt for Society member-invitation emails — NSLS fields, life-stage buckets, tested failure catalogue |
| **llm-email-workflow** | End-to-end pipeline for LLM-generated emails — data, audience, node wiring, guardrails, rollout |
| **kw:brainstorm / kw:plan / kw:review / kw:compound** | Strategy & knowledge-work pipeline (non-software) |

## Updates

Skills auto-update when you start a Claude Code session. To update manually:

```bash
cd ~/.claude/local-plugins/nsls-builder-toolkit && git pull
```

## Skill Usage Tracking

Every time you invoke a skill (`/open-day`, `/log`, `/learn`, etc.) the toolkit
posts a deduped event to the Automation Tracker. We use this to measure skill
breadth and learning velocity across builders — not to grade you. One event
per builder per skill per day; no payload content is sent.

The ping fires from two places — the `PreToolUse` hook (CLI + desktop) and a
one-line `Bash` call embedded in each skill's pointer (works wherever skills
run). The server dedupes per builder/skill/day, so both producers can fire
without inflating counts.

On **Windows**, those producers (`python3`/`bash`) don't run; `install.ps1`
registers a PowerShell `PreToolUse` hook (`hooks/skill-event.ps1`) plus the
session ping (`hooks/session-start.ps1`) so Windows builders are covered too.

### Opt out

Set `BUILDER_EMAIL=""` in `~/.claude/local-plugins/nsls-personal-toolkit/.env`.
Both producers check this value before pinging; an empty email disables them
both, permanently, with no other side effects.

Editing `hooks/hooks.json` to remove the `PreToolUse` block doesn't work as a
durable opt-out — the file is overwritten on the next `git pull` of the
toolkit. Empty `BUILDER_EMAIL` is the canonical path.

### Known limitations

- **Tracking only fires for builders whose `BUILDER_EMAIL` is set.** Running
  `/personal-setup` writes it; running only the org-side `/setup` does not.
  Builders who skip personal-setup are invisible until they configure it or
  until a separate fix wires `BUILDER_EMAIL` into the builder-toolkit
  installer.
- **The `PreToolUse` hook only ships in this plugin.** Builders who install
  only the personal toolkit (no builder-toolkit) get no hook coverage — they
  rely solely on the pointer self-report, which won't fire for skills outside
  the personal toolkit's catalog.
- **Counts can occasionally exceed one row per builder/skill/day.** The
  dedupe is a read-then-write scan with no unique constraint, so two producers
  firing within ~100ms of each other can both pass the check before either
  writes. Use `COUNTUNIQUE(Builder)` for "% of builders" queries.

## Request a Skill

Open a [GitHub issue](https://github.com/thensls/nsls-builder-toolkit/issues) or message Kevin in Slack.
