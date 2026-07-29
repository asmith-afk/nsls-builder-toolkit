---
name: register-automation
description: >-
  Register, update, or check an NSLS automation in the Automation Tracker.
  Use when the user says "register automation", "register this", "track this
  automation", "update automation tracker", "check automation status", "list
  automations", or is working in an NSLS automation repo and wants to record it.
---

# Register Automation

Register or update NSLS automations in the Automation Tracker and automatically
link the builder as owner/maintainer. The proxy handles points, stage
advancement, and assignment creation.

**Proxy URL**: `https://web-production-6281e.up.railway.app`

## How It Works

This skill is a thin layer over a smart proxy. The proxy handles:
- Finding/creating the automation record
- Linking the builder as Owner/Maintainer
- Calculating points for stage changes and checklist completions
- Checking and applying builder stage advancement (Explorer → Maker → Builder → Architect → Steward)
- Logging all events for audit

The skill's job: detect context, gather data, call the proxy, present results.

## Step 1: Detect the Builder

Auto-detect who's registering. Try these in order:
1. `git config user.email` — most reliable
2. Read email from `~/.claude/local-plugins/nsls-personal-toolkit/.env` or `~/.claude/local-plugins/nsls-builder-toolkit/.env`
3. Ask: "What's your NSLS email?"

Verify the builder exists: `POST /find-builder` with `{"email": "<detected>"}`.
If not found, offer to register them: `POST /builder` with their details.

## Step 2: Detect the Automation

### In a git repo (auto-detect mode)

Scan the repo:
- `git remote -v` → GitHub URL, repo name
- **`code_on_github` means the NSLS org owns the code — not that git is in use.** Set
  `code_on_github: true` only when the `origin` remote is `github.com/thensls/<repo>`
  (SSH or HTTPS). A personal-account remote is `false`. Getting this wrong is how a
  Production automation ends up registered as org-owned while its code sits in someone's
  personal account — which is the exact governance gap the checklist exists to surface.

  When the remote is personal, say so plainly and hand over the fix:
  > Your remote is `<owner>/<repo>`, not in the `thensls` org, so this registers as *not*
  > org-owned. To transfer: repo **Settings → Danger Zone → Transfer ownership → `thensls`**.
  > Org members have repo-create rights, so you don't need an admin. Two things to do in
  > the same sitting:
  > - **Scan the git *history* for credentials before you transfer.** The org is on GitHub
  >   Team, which has no secret scanning for private repos — nothing will catch a key
  >   that's already sitting in an old commit. If history is dirty, squash to a fresh
  >   initial commit and push that instead of transferring.
  > - **Add your reviewers explicitly.** The org's default repository permission is `none`,
  >   so transferring alone gives teammates zero access — they'll get a 404 until you add
  >   them as collaborators.
- `README.md` exists? → `readme: true`
- `CLAUDE.md` exists (root or `.claude/`)? → `claude_md: true`
- `docs/runbook.md` or `runbook.md`? → `runbook: true`
- `docs/architecture.md` or `architecture.md`? → `architecture_doc: true`
- `DESIGN.md`? → `design_intent: true`
- `railway.toml` or `Procfile`? → `deployed_shared_infra: true`
- `gh api repos/{owner}/{repo}/collaborators --jq length` > 1? → `collaborators_on_repo: true`

Check if it's already tracked: `POST /find` with `{"name": "<repo name>"}`.

If found: note the current `stage` as `previous_stage`.
If not found: this is a new registration.

Ask the user only for fields you can't detect:
- **Required if new**: description
- **Recommended**: department, scope, type, stage
- **Optional**: everything else

### Not in a repo (manual mode)

Ask for:
- **Required**: name, description
- **Recommended**: department, scope, type, stage
- **Optional**: everything else

## Step 3: Register

Call `POST /register-automation-with-builder`:

```json
{
  "automation": {
    "name": "...",
    "stage": "...",
    "department": "...",
    "...all detected and user-provided fields"
  },
  "builder_email": "jdoe@nsls.org",
  "previous_stage": "Prototype"
}
```

## Step 4: Present Results

From the response, show:

**Always:**
> Registered **[Name]** at [Stage]. You're listed as owner/maintainer.

**If checklist items were updated:**
> Updated org-owned checklist: README, CLAUDE.md, GitHub repo confirmed.

**If stage_advanced is not null:**
> This moves you from [from] to **[to]** — [encouragement based on stage]:
> - Maker: "You're getting your hands dirty."
> - Builder: "You've shipped something real."
> - Architect: "You're building systems that outlast you."
> - Steward: "You own it. Others depend on it."

**Always — close with what's still open.** This is the part that makes the checklist
work. Registration currently ends on a completed note, so builders walk away thinking
they're done and the remaining items go untouched for weeks. Leave the loop open.

Call `GET /builder-stats/{builder_email}`, find the automation you just registered, and
read `checklist_complete`, `checklist_total`, and `checklist_remaining`. Then show:

> Checklist: **7 of 12.** Still open:
> - **Collaborators on Repo** — teammates can't review until you add them
> - **Service Account Creds** — so it isn't running on your personal credentials
> - **Deployed on Shared Infra** — off your own account, onto shared
> - **🎰 Won the Lottery** — could someone else run this if you disappeared tomorrow?
> - **DESIGN.md** — why this exists, for whoever inherits it

Two rules for how you say it:

1. **Frame these as what makes the automation survivable, not as a debt owed.** The
   builder just shipped something; this is the difference between a tool and an asset.
2. **Name which open items their current work already covers.** Most builders are
   mid-migration or mid-deploy, and two or three of the open items are things they're
   doing this week anyway — pointing that out converts a list into momentum. If a stage
   or scope answer implied upcoming work (a cutover, a handoff, a new environment), say
   which boxes it will tick.

**Key → label.** Mirrors the tracker's checkbox fields. Title-case any key not listed
here rather than dropping it — the field set grows.

| Key | Label |
|---|---|
| `code_on_github` | Code on GitHub (in the `thensls` org) |
| `readme` | README |
| `claude_md` | CLAUDE.md |
| `runbook` | Runbook |
| `architecture_doc` | Architecture Doc |
| `service_account_creds` | Service Account Creds |
| `deployed_shared_infra` | Deployed on Shared Infra |
| `env_vars_documented` | Env Vars Documented |
| `collaborators_on_repo` | Collaborators on Repo |
| `handoff_guide` | Handoff Guide |
| `won_the_lottery` | 🎰 Won the Lottery |
| `design_intent` | DESIGN.md |

**Do NOT show points to the builder.** Points are Kevin's internal metric. The checklist
count is different — **do** show that. Completion is the builder's own signal; points
are not.

## Checking Status

If the user asks "what automations do we have" or "show me the tracker":
- `GET /automations` to list all
- Present as a table: name, stage, department, type

If the user asks "what are my automations":
- `GET /builder-stats/{email}` to get their portfolio
- Show automations with checklist progress

## Scope Change Check

When updating scope to a higher level (Personal → Department, Department →
Company-wide, any → Customer Facing), check for `DESIGN.md`. If missing,
recommend: "Higher scope automations need a DESIGN.md. Run the `product-design`
skill in Generate Mode to create one."

## API Reference

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/find` | Search automations by name |
| POST | `/find-builder` | Find builder by email/Slack ID/GitHub |
| POST | `/register-automation-with-builder` | Main smart endpoint |
| GET | `/automations` | List all (optional `?stage=` or `?department=`) |
| GET | `/builder-stats/{email}` | Builder's automation portfolio |
| POST | `/builder` | Register a new builder |
