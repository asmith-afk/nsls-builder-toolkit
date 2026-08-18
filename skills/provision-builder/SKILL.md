---
name: provision-builder
description: >-
  Use when a builder needs their app put on shared NSLS infrastructure (Railway +
  Doppler + Netlify) — "provision a builder", "set up [name] on Railway", "onboard
  [name]'s app", "get [name] able to deploy", "add [name] to Railway and Doppler",
  "add [name] to Netlify", "add [name] to the Netlify team", when a builder reports
  they "can't deploy", "can't see the Netlify sites", or hit "only the GitHub owner
  can do this" in Railway, or /provision-builder.
---

# /provision-builder — onboard a builder's app to Railway + Doppler + Netlify

## Safety — what this skill may do

1. **Read-only (no friction):** check GitHub org membership and repo access, read
   Railway projects (`railway list`), read Doppler projects (`doppler projects`),
   read the Netlify team roster, look up the builder in Slack. Run these freely to
   build the picture.
2. **Configuration (confirm first):** create a Railway project + GitHub-connected
   service, create a Doppler project. Show the full plan and get a yes before
   creating anything. These make real resources in the NSLS workspaces.
3. **External / human-in-the-loop (never automatic):** inviting the builder to the
   Railway team, Doppler workplace, or **Netlify team**, granting Doppler project
   access, and sending the builder a Slack message. The skill **prepares** these — a
   printed checklist and a Slack *draft* — but a human completes them. Never invite
   via API, never auto-send the Slack message. This holds for Netlify even though
   its member-add *is* a single documented API call (see Notes) — a seat invite emails
   a real person and adds a billable seat, so it stays a human's click.

## Purpose

Getting a builder's app onto shared infra used to mean re-deriving a playbook under
a misleading error. This skill turns that into a guided ~10-minute flow: it knows
the GitHub side is usually already fine, it knows which steps the CLIs can do and
which are dashboard-only, and it knows the one failure that masquerades as a
permissions problem. It does the mechanical creation itself and hands the human a
tight checklist for the parts that genuinely require a click. It also knows what each
platform costs to add someone to — Railway team membership exposes every project, a
Netlify seat exposes every site *and* bills monthly — so nobody grants more than the
builder asked for.

## The one thing to understand first

When a builder hits **"only the GitHub owner can do this"** in Railway, it is almost
never a GitHub problem. The Railway GitHub App is already installed org-wide on
`thensls` with access to **all** repos, and builders already have repo access. The
real cause: the builder is acting in a Railway account/team that does not hold the
org's GitHub connection. **The fix is to create the service under the NSLS Railway
team (which holds the connection) and add the builder to that team** — not to grant
anything on GitHub.

## Inputs (gather interactively, heartbeat each)

**Ask for the platforms first** — that answer decides which inputs and which preflight
checks are even relevant. Gathering repo data for a Netlify-only request, or demanding a
Railway login nobody needs, is how this skill stalls on a non-problem.

- **Platforms (ask first):** which does the builder actually need? Don't provision all
  three by reflex.
  - **Railway + Doppler** — apps: a running service, env vars, deploy on push.
  - **Netlify** — static sites, decks, one-off deploys. **Team membership only:** this
    skill never creates Netlify sites (see Notes).

  A builder can need one track, the other, or both. **Netlify-only is a normal request**
  ("add Davo to Netlify") and must run without any repo or Railway/Doppler input.
- **Builder:** name + **work email**, always. **GitHub username** only if the
  Railway/Doppler track is in scope — it's needed to verify repo access, and a
  Netlify-only run has no repo to check. Resolve email/Slack with
  `slack_search_users "<name>"` and confirm; don't guess an address you'll invite.
- **Repo(s)** — *Railway/Doppler track only, skip entirely for Netlify-only:* one or more
  `thensls/...`. If they give an app name, find matches with
  `gh repo list thensls --limit 200 | grep -i <name>` and confirm.
- **Confirm the plan** before any write — name only the platforms in scope:
  - both tracks: `Provisioning Josh Hrala (jhrala) → 2 apps (NSLS-Alumni-Tracker, invite-email-simulator) on Railway + Doppler under the NSLS team. Proceed?`
  - Netlify only: `Adding Davo Wood (davowood@nsls.org) to the NSLS Netlify team as Developer — no repos, no Railway/Doppler. Adds a per-seat Pro charge. Proceed?`

## Preflight — pick the mode

Check the runner's own access and **say what you found** (heartbeat). **Run only the
checks for the platforms in scope** — an unauthenticated Railway CLI is irrelevant to a
Netlify-only request and must not block it.

Always (both tracks) — who is the runner:

```bash
ME=$(gh api /user --jq .login)
gh api /orgs/thensls/memberships/$ME --jq .role     # owner/admin vs member
```

Railway/Doppler track only:

```bash
railway whoami                                       # logged in? (Kevin/Jenna = NSLS)
doppler me                                           # logged in? workplace = NSLS?
```

Netlify track only — **never** run `netlify status` or other Netlify CLI commands to
check this; the CLI hangs waiting on a prompt that never renders. Read the token the CLI
already stored and ask the API instead:

```bash
# The config path is OS-specific — pick it, don't hardcode. On macOS it is NOT
# ~/.config/netlify (that directory exists but is empty, which is the trap).
case "$(uname -s)" in
  Darwin)               NF_CFG=~/Library/Preferences/netlify/config.json ;;
  Linux)                NF_CFG=~/.config/netlify/config.json ;;
  MINGW*|MSYS*|CYGWIN*) NF_CFG="${APPDATA//\\//}/netlify/config.json" ;;
  *) echo "Unsupported OS for Netlify config lookup" >&2 ;;
esac
NF_TOKEN=$(python3 -c "
import json,os,sys
d=json.load(open(os.path.expanduser('$NF_CFG')))
me='<runner work email>'
print(next(u['auth']['token'] for u in d['users'].values() if u.get('email')==me))")
curl -s -H "Authorization: Bearer $NF_TOKEN" https://api.netlify.com/api/v1/accounts \
  | python3 -c "import json,sys; [print(a['slug'], '|', a['name'], '|', a['type_name']) for a in json.load(sys.stdin)]"
```

⚠️ That config file holds a token **per identity** — a runner may have personal and
former-employer accounts in it alongside their NSLS one. Select by matching work email;
never take the first token. Reference the variable only — never paste a token value into
a command, where it would land in the transcript.

- If a CLI **needed for a platform in scope** isn't authenticated, stop and point to
  `railway login` / `gh auth login` / `doppler login` (or `/connect`). Resume after.
  Ignore CLIs for platforms that aren't in scope. For Netlify, if no token matches the
  runner's work email, they need to log in to the Netlify CLI once (`netlify login`,
  which opens a browser) — that writes the token this skill reads.
- **Netlify-only runs skip execute-mode steps 1–3 entirely** — no GitHub repo check, no
  Railway service, no Doppler project. Go straight to step 4, then the Netlify line of
  the checklist and the handoff.
- **Execute mode** — runner is an org admin and the CLIs for the platforms in scope work:
  do the CLI creation below, then print the dashboard checklist + Slack draft.
- **Request mode** — runner is *not* an admin (e.g. Josh onboarding a new builder), or
  an execute-mode CLI call fails with a permission error: **create nothing.** Emit a
  clean *Provisioning request* covering only what's in scope — repos, services to create,
  Doppler projects, and the invites needed with access levels (for Netlify-only, that's
  just the team invite and its role) — and offer to drop it as a Slack draft to an admin
  (Kevin or Jenna). Don't thrash against a permission wall; hand it off.

## Execute-mode steps (idempotent — safe to re-run)

Steps **1–3 belong to the Railway/Doppler track** and are skipped wholesale on a
Netlify-only run. Step 4 is Netlify. Steps 5–6 apply to whatever was in scope.

### 1. Verify GitHub access — *Railway/Doppler track* (prerequisite, not something to grant)

```bash
gh api /orgs/thensls/memberships/<user> --jq .role          # must exist (member/admin)
gh api /repos/thensls/<REPO>/collaborators --jq '.[]|select(.login=="<user>")|.role_name'
```

The builder must be a `thensls` org member with at least `write` on each repo. If not,
**flag it** — that's a separate access grant, don't silently add them. (Context, if
asked: `gh api /orgs/thensls/installations --jq '.installations[]|select(.app_slug=="railway-app")|.repository_selection'` returns `all` — Railway already sees every repo.)

### 2. Railway — one GitHub-connected service per repo

Check first; skip-and-heartbeat if it already exists (a re-run after a timeout must not
double-create):

```bash
railway list        # does a project for this app already exist? say so if it does.
```

Otherwise, **work from a temp dir** so no Railway link files land in the runner's home:

```bash
cd "$(mktemp -d)"
railway init -n "<Project Name>" -w NSLS --json          # capture .id
railway link -p <projectId>
railway add --repo thensls/<REPO> --service <service-name> --json
railway status --json | grep -E '"name"|"repo"'          # confirm source.repo is set
```

- Use `--repo` — it creates a **GitHub-connected** service that auto-deploys on push.
  `railway up` only uploads a local snapshot; that is not what we want.
- `railway init`/`add` may echo interactive prompts even with `--json`; they still
  complete. The real risk is a transient `operation timed out` from backboard — if that
  happens, re-run `railway list` to see whether the project was created before retrying.

### 3. Doppler — one project per app

```bash
doppler projects --json     # already exists? skip and heartbeat.
doppler projects create <slug> --description "Env/secrets for <App> (Railway). Owner: <Builder>."
```

Default configs `dev` / `stg` / `prd` are created automatically; the Railway production
environment will sync from `prd`.

### 4. Netlify — check membership first (read-only)

Only if Netlify is in scope. Before asking anyone to send an invite, check whether the
builder is already on the team — a re-run must not produce a duplicate invite, and a
pending invite from a previous run looks identical to "not a member" if you don't read
the `pending` flag:

```bash
TEAM=kprentiss-ryj1oi0     # the NSLS team's slug — see gotcha below
curl -s -H "Authorization: Bearer $NF_TOKEN" \
  "https://api.netlify.com/api/v1/$TEAM/members" \
  | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    print(f\"{m.get('role'):10} {m.get('email'):28} {'PENDING INVITE' if m.get('pending') else 'active'}\")"
```

- ⚠️ **The NSLS team slug is `kprentiss-ryj1oi0`.** It looks like a personal account
  because the team grew out of one — it is the real NSLS team (Pro plan). Don't "correct"
  it to `nsls`, and don't create a second team. Confirm with `/accounts` in preflight.
- If the builder already appears **active** → nothing to do; say so and skip the Netlify
  line in the checklist.
- If they appear **PENDING INVITE** → the invite exists and is unaccepted. Don't re-invite;
  the action is to nudge them to accept, so put that in the Slack draft instead.
- **Pick the role from what the team already uses**, not from the docs. Read the roster
  above: at time of writing the NSLS team runs one **Owner** (Kevin), one **Publisher**,
  and everyone else **Developer**. Default to **Developer** — it grants deploy, build, and
  env-var access with `site_access: all`, but no billing and no member management. Only go
  higher if the builder is explicitly taking on publishing or billing duties.

### 5. Dashboard checklist — the CLIs cannot do these (print verbatim)

No CLI here can invite members or grant access — not Railway's, not Doppler's, and not
Netlify's. Hand the admin these exact steps:

- **Railway team:** railway.com → **NSLS** workspace → **Settings → Members → Invite** →
  `<builder email>`, role **Member**.
  ⚠️ **Blast radius:** Railway membership is team-wide, not per-project — the builder will
  see **every** NSLS project, not just their two. State this every run. (A per-builder
  Railway team is the tighter alternative; we deliberately default to the NSLS team.)
- **Doppler invite + access:** dashboard.doppler.com → **Workplace Settings → Team →
  Invite** → `<builder email>`. Then for **each** new project → **Access** → add the
  builder as **Admin** (so they manage their own secrets, scoped to just their projects).
- **Netlify team** (skip if step 4 showed them active or pending): app.netlify.com →
  **NSLS** team → **Team → Members → Invite members** → `<builder email>`, role
  **Developer**.
  ⚠️ **Blast radius:** a new member lands with `site_access: all` — they will see and can
  deploy **every** NSLS Netlify site, not just theirs. State this every run. It's the same
  team-wide exposure as Railway, and Netlify has no per-site equivalent of Railway's
  `projectMemberAdd` scoping to fall back on.
  ⚠️ **Cost:** the NSLS team is on **Pro, which bills per seat** — an accepted invite adds
  a recurring charge. Say so out loud in the run; a seat is not free the way a Railway
  project is.
- **Doppler → Railway sync (admin does this — NOT the builder):** for **each** project,
  open the **`prd`** config → **Integrations → Add Sync → Railway** → reuse the existing
  workplace Railway connection (in this workplace it's named **"SLT-Coach Bot"** — it
  already syncs non-SLT projects, so it's the general NSLS Railway connection) → pick the
  Railway **project**, **environment** = production, and **service**. **Why the admin:** a
  Doppler *connection* is a workplace-level resource; creating connections/syncs requires
  **workplace-admin** permission. A project-scoped **Admin** can edit secrets but cannot
  add a connection or sync — so the builder literally can't do this step (they'll see
  "no permission to add a new connection"). The CLI can't do it either; it's dashboard or
  the `POST /v3/configs/config/syncs` API, and the Railway `data` schema isn't publicly
  documented — prefer the dashboard.

### 6. Handoff — draft (never send) a Slack message to the builder

Look up the builder (`slack_search_users`), then `slack_send_message_draft` to their
user id. The draft tells them what's done and their remaining steps — include only the
platforms actually in scope:
1. Accept the **Railway team invite** (else they can't see their Railway projects).
2. Accept the **Doppler invite**.
3. Accept the **Netlify invite** (else the seat stays pending and they see no sites).
4. Put env vars in the **`prd`** config of each Doppler project.

The Doppler → Railway sync is set up **for** them by the admin (step 5) — do **not** tell
the builder to wire it themselves; their project-Admin role can't create the connection.

Then: push deploys with secrets pulled from Doppler.

## Red flags — STOP

Each of these is a shortcut that breaks the skill. If you catch yourself doing it, stop:

| Rationalization | Reality |
|---|---|
| "It's a GitHub permissions wall — I'll grant access on GitHub." | It isn't. The app has `all` repos and the builder has write. Create the service under the NSLS team + add them to the team. |
| "I'll just send the builder the Slack message to finish the job." | Never auto-send. Create a **draft** only; the runner sends it. |
| "I'll invite them to Railway/Doppler via the API to save a click." | Don't. Invites and project-access grants stay human-in-the-loop — print the checklist. |
| "I'll create the Railway project / Doppler project now." | Check first (`railway list`, `doppler projects`). A re-run after a timeout must not double-create. |
| "The plan's obvious, I'll skip the confirm." | Confirm the plan before any create. These are real resources. |
| "The runner isn't an admin, but I'll push the CLI through." | Fall back to request mode and hand off. Don't thrash a permission wall. |
| "The builder lacks repo write — I'll just add them." | Flag it as a prerequisite gap. Don't silently grant org/repo access. |
| "The builder has Doppler Admin, so they'll wire the Railway sync." | They can't. Creating a Doppler connection/sync is workplace-admin only; project-Admin edits secrets but can't add connections. The admin sets up the sync. |
| "The Netlify member-add is one API call — I'll just run it." | No. Netlify invites follow the same rule as Railway and Doppler: print the checklist, a human clicks. Being easy to automate isn't a reason to; it emails a person and starts a per-seat charge. |
| "They need Netlify too, I'll add it while I'm here." | Ask which platforms are actually needed. A Netlify seat costs money and exposes every site. Don't provision a platform nobody asked for. |
| "I'll check Netlify auth with `netlify status`." | The CLI hangs. Read the stored token and call the REST API (preflight). |
| "It's a Netlify-only ask, but I'll run the full preflight / ask for the repo anyway." | Don't. Netlify-only is a normal request — no repo, no GitHub username, no Railway or Doppler check. Running them invents a blocker out of an unauthenticated CLI nobody needs. |

## Diagnostic loop

- **"only the GitHub owner can do this" (the builder hit it):** not GitHub. Confirm the
  app is `repository_selection: all` and the builder has org membership + repo write
  (they will). The fix is creating the service under the NSLS team + adding them to the
  team — see top of skill.
- **`railway add` succeeds but nothing deploys:** the service is connected but has no
  build config / env vars yet. Expected until the `prd` vars exist and the admin's
  Doppler→Railway sync (step 5) has run. Not a provisioning bug.
- **Builder reports "no permission to add a new connection" / "only sees one connection"
  in Doppler:** working as designed — creating connections/syncs is workplace-admin only.
  The admin sets up the sync (step 5); the builder only adds `prd` vars. Confirm the
  builder also actually sees *their* projects in the project list — if not, their
  project-access grant didn't apply and needs re-granting.
- **Builder says "I can't see the Netlify sites":** read the roster (step 4). If they're
  `PENDING INVITE`, they never accepted — nudge, don't re-invite. If they're active and
  still see nothing, check `site_access` on their member record; anything other than `all`
  means they were added with a narrowed scope.
- **A Netlify CLI command hangs with no output:** expected — the CLI blocks on prompts in
  a non-interactive shell. Kill it and use the REST API. Never put `netlify <cmd>` on the
  critical path of this skill.
- **Netlify API returns 401:** the token you read belongs to a different identity in
  `config.json`, or that account was removed from the team. Re-select by work email.
- **Railway `operation timed out`:** transient backboard error. Re-run `railway list` to
  check whether the resource was created, then retry only the missing step.
- **Repo not visible to Railway:** verify the builder's org membership, not the GitHub
  App (the app already has `all`).
- **CLI permission error mid-execute:** the runner isn't sufficiently privileged for that
  step — fall back to request mode and hand the rest to an admin.

## Output

Close with a compact table — per app: Railway project/service ↔ repo, Doppler project,
Netlify team status (`active` / `pending` / `n/a`), and the access state — followed by the
dashboard checklist and the Slack draft link. Then the single next action ("builder accepts
invites, adds prd vars, admin wires sync"). If a Netlify seat was requested, name the
per-seat cost in the close; it's the one line item in this flow that recurs.

## Notes

- Setup of the runner's own connections lives in `/connect`, not here.
- Register the app(s) with `/register-automation` if they're org automations.
- **Scope.** Railway + Doppler cover apps end to end (create the service, create the
  secrets project, wire the sync). Netlify is deliberately narrower: **team membership
  only.** This skill does not create Netlify sites — sites get created by the deploy
  itself, so there is no provisioning step to own. For deploying a static site or deck,
  use `/netlify-deploy`; for putting it on a branded URL, `/add-domain`. **Vercel
  provisioning remains out of scope.**
- **Netlify member API (reference — the skill does not call it).** There is no write path
  for team members outside the REST API: the Netlify MCP server exposes only read
  operations for teams (`get-teams`, `get-team`), and the CLI can't manage members at all.
  The endpoint an admin *could* use is:

  ```
  POST https://api.netlify.com/api/v1/<team-slug>/members
  Authorization: Bearer <token>       body: {"email": "...", "role": "Developer"}
  ```

  It returns the new member record with `pending: true`. Documented here so nobody
  re-derives it under a misleading "the CLI can't do this, so it's impossible" — but per
  the safety model above, the invite itself stays a human's click in the dashboard.
- The recurring shape across all three platforms: **the vendor CLI (and MCP) can't manage
  members; the REST/GraphQL API can.** True of Railway (`projectMemberAdd`), Doppler
  (`PATCH /v3/projects/project/members/...`), and Netlify. Expect it on the next platform
  too — check for an API before concluding a grant is dashboard-only.
