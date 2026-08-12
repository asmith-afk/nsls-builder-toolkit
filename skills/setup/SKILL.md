---
name: setup
description: >-
  Onboarding for the NSLS Builder Toolkit. Confirms the builder email and
  GitHub username so the tracker can credit work (including merged PRs),
  connects org tools one at a time (Slack, Google Drive, Google Calendar,
  Gmail, Fathom), verifies plugins, registers Windows hooks, checks GCP/gws
  access, and offers personal productivity setup. Use when first setting up,
  or when a tool connection seems broken.
---

# NSLS Builder Toolkit — Setup

Walk the new builder through getting connected. **This is a guided, hand-held
experience, not a checklist you hand them.** Golden rules for the whole skill:

- **One thing at a time.** Ask one question, wait for the answer, then move on.
  Never print a wall of steps for the builder to execute themselves.
- **Open or link the exact page.** Never say "go to settings → MCP Servers."
  Instead, tell them precisely what to click, or (better) send them to the exact
  Connectors panel and wait.
- **Plain words, no jargon.** "the long code on that page," not "the OAuth
  bearer token." Describe what they'll see on screen.
- **Detect first, ask second.** If something is already done, say so and skip it.

Show the roadmap upfront so the builder knows the shape:

```
Welcome to the NSLS Builder Toolkit! Let's get you set up.

This takes about 5 minutes, and I'll do it with you one step at a time:
  1. Confirm your builder email + GitHub username (so the tracker credits your work and your merged PRs)
  2. Connect your tools — Slack, Google Drive, Calendar, Gmail, Asana, Fathom
  3. Check your plugins are working
  4. Register Windows hooks (Windows only — skipped on Mac/Linux)
  5. Personal productivity skills (optional, your call)

Ready?
```

## Step 1: Confirm Your Builder Email (~15 sec)

The session-start hook (daily session points + PR credit) and the skill-use
hook both read `BUILDER_EMAIL` from
`~/.claude/local-plugins/nsls-personal-toolkit/.env`. Without it, your work
shows up as "unknown" in the Automation Tracker and you don't get credit.

**Don't make the builder type their email.** You already know the email of the
signed-in Claude account from this session's context. Lead with the
transparency note as context, then ask — **the question is the LAST line of
the message, with nothing after it.** (A question buried mid-message reads as
"still loading"; a builder in this exact flow froze and asked "did setup
stall?" because the disclosure trailed the question.)

```
Quick transparency note first: each time you use a skill, the toolkit sends a
one-line ping to the NSLS tracker so you get credit for your work — the skill
name and your email, nothing about what you were doing. There's also a
once-per-launch sync that updates the toolkit and records your daily session
(email, GitHub username, platform) — same purpose: your work counts.

I'll credit your work to <signed-in account email>. Sound right? (yes / or paste a different email)
```

Only fall back to free-text entry if they say the signed-in address is wrong
(e.g. they use an alias). If `/personal-setup` already set BUILDER_EMAIL, this
is a no-op — check first:

```bash
ENV_FILE="$HOME/.claude/local-plugins/nsls-personal-toolkit/.env"
if [ -f "$ENV_FILE" ] && grep -q "^BUILDER_EMAIL=" "$ENV_FILE"; then
  echo "ALREADY_SET: $(grep '^BUILDER_EMAIL=' "$ENV_FILE" | cut -d= -f2-)"
fi
```

If not set (or they gave a different one), write it — preserving any other env
vars in the file (JSONB-style merge; never clobber the file):

```bash
ENV_FILE="$HOME/.claude/local-plugins/nsls-personal-toolkit/.env"
mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"
{ grep -v "^BUILDER_EMAIL=" "$ENV_FILE" || true; } > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
echo "BUILDER_EMAIL=<confirmed email>" >> "$ENV_FILE"
```

Confirm briefly: "Got it — your work is now credited to <email>." (If a
permission prompt for `skill-event.sh` ever appears later, that's the same
credit ping from the transparency note — safe to approve; the installer
allowlists it so it shouldn't recur.) If the builder ever asks you to review
or explain one of these hook scripts, give the accurate technical facts AND
restate in the same breath that this is the expected credit mechanism — facts
and framing travel together.

### Step 1.5: Reconcile early events (automatic, silent — no question)

The installer fires an install event (and skill events can fire) **before**
`/setup` runs, attributed to a fallback identity (git email → `$USER@host`).
Now that the real BUILDER_EMAIL is set, tell the tracker to merge those early
events onto the right builder. Read the *previous* identity the installer
recorded (`.install-identity`), then POST the reconcile. Skip silently if they
match, and never block setup on it:

```bash
NEW_EMAIL="<confirmed email>"
# Prefer the EXACT provisional identity the installer wrote to
# <toolkit>/.install-identity. Recomputing it here is unreliable on Windows Git
# Bash — $USER is empty and `hostname -s` has no -s flag, yielding
# `unknown@unknown`, which could NEVER match the identity install.ps1 actually
# used (`$USERNAME@$COMPUTERNAME`). Fall back to the old recompute only when the
# file is absent (a pre-.install-identity install).
ID_FILE="$HOME/.claude/local-plugins/nsls-builder-toolkit/.install-identity"
if [ -f "$ID_FILE" ]; then
  PREV_EMAIL=$(head -n1 "$ID_FILE" | tr -d '"\r')
else
  PREV_EMAIL=$(git config user.email 2>/dev/null || true)
  [ -z "$PREV_EMAIL" ] && PREV_EMAIL="${USER:-unknown}@$(hostname -s 2>/dev/null || echo unknown)"
fi
if [ -n "$NEW_EMAIL" ] && [ "$PREV_EMAIL" != "$NEW_EMAIL" ]; then
  # Contract matches the tracker service's handler (POST /reconcile-builder,
  # body {previous_email,new_email}) — do NOT change the shape. Server-side it's
  # idempotent and no-ops when the emails match or no provisional row exists, so
  # this is safe to re-run. Best-effort — a 404/timeout must never block setup.
  curl -s --max-time 40 -X POST \
    ${NSLS_TRACKER_URL:-https://web-production-6281e.up.railway.app}/reconcile-builder \
    -H 'Content-Type: application/json' \
    -d "{\"previous_email\":\"$PREV_EMAIL\",\"new_email\":\"$NEW_EMAIL\"}" \
    >/dev/null 2>&1 || true
fi
```

Don't mention this to the builder unless they ask — it's plumbing.

### Step 1.7: GitHub username (~20 sec)

The tracker credits **merged PRs** by GitHub author login, read as
`GITHUB_USERNAME` from the same `.env`. A wrong or empty value means merged
PRs silently earn no credit — this cost one builder six weeks of PR points.
**Never guess it from the email**: the email prefix has been wrong for every
known builder (grandmamischief, jfontanez-nsls, david-adams). Don't propose a
default — ask open-ended.

Check first; if a value exists, confirm it instead of re-asking:

```bash
ENV_FILE="$HOME/.claude/local-plugins/nsls-personal-toolkit/.env"
grep "^GITHUB_USERNAME=" "$ENV_FILE" 2>/dev/null | cut -d= -f2-
```

Ask (plain words): "Which GitHub account do you open pull requests as? (your
GitHub username, not your email)". If they don't use GitHub yet, skip cleanly —
leave the key unset and note they can re-run /setup after their first PR.

Validate before writing — never store an unverified guess:

1. **Does the account exist?**
   ```bash
   GH_USER="<their answer>"
   curl -s -o /dev/null -w '%{http_code}' "https://api.github.com/users/$GH_USER"
   ```
   (When `gh` is installed and authed, `gh api "users/$GH_USER" --jq .login`
   works too.) `200` → real account. `404` → typo or not a username — show
   them what you checked and re-ask. Anything else (rate limit, offline) →
   accept their answer but say you couldn't verify it right now.
2. **Sanity-check it's the right account** — any thensls PRs?
   ```bash
   curl -s "https://api.github.com/search/issues?q=type:pr+org:thensls+author:$GH_USER&per_page=1"
   ```
   Read `total_count`. Zero is expected for a brand-new builder — but if
   they've shipped NSLS work before, zero usually means the wrong account (an
   alt, a rename): say so and double-check with them. Treat this as a hint,
   not proof (private-repo PRs may not show unauthenticated).

Write it with the same merge pattern as BUILDER_EMAIL (preserve other keys):

```bash
ENV_FILE="$HOME/.claude/local-plugins/nsls-personal-toolkit/.env"
mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"
{ grep -v "^GITHUB_USERNAME=" "$ENV_FILE" || true; } > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
echo "GITHUB_USERNAME=<validated username>" >> "$ENV_FILE"
```

Confirm: "PR credit goes to github.com/<username>."

### Step 1.8: Git identity (~15 sec)

Commits are stamped with `git config --global user.email` / `user.name` — a
**separate mechanism from tracker credit**. Left unset, every commit the
builder pushes (to anything they build later) is authored as an unclickable
`user@COMPUTERNAME`, and GitHub attributes nothing to their profile. **Never
describe a missing git identity as bare "harmless"** — it's harmless for
tracker credit and broken for commit attribution; say which is which.

```bash
git config --global user.email; git config --global user.name
```

If either is empty, **ask — don't note**: "One more credit thing: commits you
push need a Git identity or GitHub won't show them as yours. Want me to set it
to <their name> / <builder email>?"

**Before writing `BUILDER_EMAIL`, check it actually earns attribution.** GitHub
links a commit to a profile only when the author email is an address *verified on
that account*. `BUILDER_EMAIL` is whatever they gave in Step 1.5 — often a work
alias that isn't on their GitHub — and setting it produces exactly the
unattributed orphan commit this step exists to prevent, while reporting success.
So ask: *"Is <builder email> one of the addresses on your GitHub account?"*

- **Yes** → use it.
- **No / not sure** → use the account's noreply address, which always attributes
  and never publishes their real email. Build it from the username validated in
  Step 1.7:

  ```bash
  GH_ID=$(curl -fsSL "https://api.github.com/users/<validated username>" | grep -o '"id": *[0-9]*' | grep -o '[0-9]*')
  echo "${GH_ID}+<validated username>@users.noreply.github.com"
  ```

  Say which you're using and why — a noreply address looks odd in `git log` if
  nobody explained it.

On yes:

```bash
git config --global user.email "<attributing email — BUILDER_EMAIL or the noreply address>"
git config --global user.name "<Full Name>"
```

Verify rather than assume: after the first push, the commit avatar links to their
profile. A plain-grey avatar with no link means the email still isn't on the
account.

Skippable, but asked — same pattern as the email and GitHub username above:
every credit-relevant identity field gets actively collected, none left as a
passing mention.

## Step 2: Connect Your Tools (~2 min) — guided, one at a time

This is the most important step and the one builders stall on. **Do NOT dump a
list of settings paths.** Connect the recommended starter bundle **one connector
at a time**, each a connect-now-or-defer choice: one line on *why*, send them to
the exact Connectors panel, wait for them to come back. **Collect them all
first — do not verify yet.** Verification happens after a single restart at the
end of this step.

All six are **one-click "Authorize" connectors** in the desktop app — no API
keys, no tokens to paste. The bundle, in order:

1. **Slack** — team channels, standups, searches
2. **Google Drive** — read/write docs and files
3. **Google Calendar** — powers `/open-day`'s daily schedule
4. **Gmail** — draft and triage email
5. **Asana** — your task list; without it `/open-day` has no tasks to pull and
   `/close-day` has nothing to update (the day-planner's task half is dead)
6. **Fathom** — meeting recordings and transcripts (`/close-day`, `person-intelligence`)

> **Do not rely on a programmatic MCP-registry probe to decide what's
> available** — a probe has missed Fathom even though its connector exists
> (user-verified 2026-07-21). Always send the builder to the Connectors panel.

> ⚠️ **Never verify a just-authorized connector in THIS session.** A connector
> authorized *during* a running session does not hot-add its MCP tools — they
> load only on the **next restart** (disconnecting drops tools live; connecting
> does not add them). A live read call right after Authorize gives a **false
> negative** and sends a builder who connected *correctly* into a pointless
> re-authorize loop. So: collect all connections, restart once, then verify.

### The connect loop (one at a time)

1. **One line on why**, then ask: "Want to connect **<tool>** now? (yes / skip)"
   - If skip: "No problem — run /setup again anytime to add it." Move on.
2. **If yes, send them to the panel.** Give the **full explanation for connector
   #1 (Slack) only** — and it must teach **where Settings actually is** (nothing
   else in the flow ever does; "Open Settings" with no path is where a
   non-technical builder stalls):
   ```
   First, open Settings: press Ctrl+, (that's Control and the comma key) — on
   Mac it's Cmd+, — or click your initials in the bottom-left corner and choose
   Settings. In Settings, click Connectors in the sidebar. Find Slack and click
   Authorize. A browser window opens — sign in and approve, then come back.
   Heads up: the app often drops you on the Home tab afterward and it looks like
   you lost this chat — you didn't. Click **Code** (top left) to return, and
   tell me when you're back.
   ```
   <!-- Maintainers: re-verify the click path against the current desktop build
        whenever the app UI shifts — the shortcut (Ctrl+,/Cmd+,) is the stable
        route; the initials/avatar location has moved between builds. -->
   For **connectors #2–#6**, collapse to a one-line breadcrumb (the Home-tab
   note folds into it — don't repeat the whole paragraph):
   ```
   Next: Google Drive → Settings › Connectors › Google Drive › Authorize, approve
   in the browser, click **Code** to come back. Tell me when you're done.
   ```
3. **Wait** for "done." Note it as connected (pending restart) and go to the
   next. **Do not run a live read call yet.**

### End of Step 2: one restart, then verify

Once they've connected (or skipped) all six:

```
That's the bundle. One thing makes them actually load: fully restart Claude Code
now (quit and reopen — on Windows, closing the window doesn't quit it, so
right-click the tray icon → Exit). When it reopens, click **Code**, then run
/setup again — I'll confirm each connection.
```

When `/setup` runs again (**after** the restart), verify each connector the
builder connected, with a **live read call** (not a registry probe):
- Slack: read your own identity from the Slack MCP tool ("…user_id is U…").
- Google Drive: a minimal Drive search/list call.
- Google Calendar: `list_calendars`.
- Gmail: `list_labels` (or a minimal thread search).
- Asana: the connector's `get_me` (your own user record).
- Fathom: `get_identity` / `list_meetings` (via the `api.fathom.ai` path).

Then summarize:
```
Connected: [verified] · Skipped: [deferred] — run /setup anytime to add these.
```
Only if a connector still isn't live **after a restart** is it worth
re-authorizing ("Slack didn't come through — let's redo just that one"). Never
offer a re-authorize as the first response in the same session it was connected.

Don't block on skipped tools — org skills that don't need them work right now.

**API keys are the fallback only for vendors with no connector.** If you ever
hit a key path for Fathom, note the old `fathom.video/settings/api` deep link
404s — say "open fathom.video → Settings → API Access" instead, and validate the
key with a live `api.fathom.ai` call.

## Step 3: Verify Plugins (~30 sec)

Check that superpowers is installed by looking for its skills (e.g.,
`verification-before-completion`, `brainstorming`).

- **Installed**: "Superpowers is working — you have /brainstorm, /debug, /verify, /plan."
- **Not installed** — offer to do it, don't hand them a terminal command to run
  blind:
  ```
  Superpowers isn't installed yet. I can install it for you — want me to?
  ```
  If yes, run `claude plugin install superpowers` for them, then tell them to
  restart Claude Code and run /setup again.

Do NOT check for compound-engineering — it's an optional power-up.

## Step 4: Register Windows Hooks (Windows only, ~10 sec)

On Windows the whole install runs through `install.ps1` (a full native
PowerShell installer mirroring `install.sh` — clone, enable, hooks, install-event,
MCP, pointers), because the bundled `hooks/hooks.json` uses `python3`/`bash`
which Windows lacks. A Windows builder installs with the PowerShell command
(see the guide), not `curl … | bash`. If they already installed but the hooks
seem missing, re-running `install.ps1` re-registers them idempotently.

Detect platform:

```bash
case "$OSTYPE" in
  msys*|cygwin*|win32*) echo "windows" ;;
  *) echo "not-windows" ;;
esac
```

**If macOS or Linux**: skip silently — the bash hooks work natively.

**If Windows**: run the installer for them:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\.claude\local-plugins\nsls-builder-toolkit\install.ps1"
```

Then tell the builder (one message, not a checklist):

```
Windows hooks registered — your session pings and skill use will show up in the
tracker after your next Claude Code restart.
```

Idempotent — re-running replaces only the NSLS entries, preserving everything
else. Safe any time the hooks seem broken.

## Step 5: GCP + Google Docs access (optional)

Ask (one question):

```
Do you need to create Google Cloud projects for your automations? (yes / no)
```

If yes:
```
You'll need to be in the gcp-builders@nsls.org group. Ask Kevin (or any group
owner) to add you. Once you're in, create projects under the "Builder Projects"
folder at console.cloud.google.com/projectcreate.
```

If no: move on.

### Google Docs editing (gws auth) — turnkey

`/gdoc-edit` and `/gdoc-build` run on `gws` (installed by the toolkit installer,
per platform). They need a one-time, per-user `gws auth login`. Make this close
to turnkey: detect state, place the shared OAuth client file for them, then hand
off the browser consent — only they can complete it (that's the security model,
not a gap).

One script drives the whole setup — the toolkit runs gws from its OWN profile so it
never collides with other Google tools' client files (background + manual fallback:
`skills/gws/references/multi-secret-profiles.md`).

**1. Run the doctor** (use a generous timeout — its login step waits for a human):

```bash
python3 ~/.claude/local-plugins/nsls-builder-toolkit/skills/gws/scripts/gws_doctor.py
```
```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" "$env:USERPROFILE\.claude\local-plugins\nsls-builder-toolkit\skills\gws\scripts\gws_doctor.py"
```
The doctor's login step **prints a consent URL and starts a local listener** — on
Windows it does **not** open a browser at all, and on Mac you can't verify from
your side that one opened. So, always, all three parts: run it in the background,
read the consent URL from its output, **open it yourself** (`open "<url>"` on
macOS, `Start-Process "<url>"` on Windows), **and print the same URL as a
clickable link in the same message** — "a Google sign-in page should now be open
in your browser — if it isn't, click here: <url>". Never phrase a browser launch
as a prediction. The URL is single-use and dies with the process: if nothing
opened or it shows "can't reach localhost", re-run the doctor and open + hand
over the **fresh** link, never the old one.

Don't hand-specify `--services` here. Scope selection is the doctor's job — it
requests `granted ∪ needed`, so a narrower manual login would strip scopes that
`squad-dashboard` (sheets) or `receipts` (gmail) already hold in this shared
profile.

**2. Act on its verdict:**

- **`DOCTOR: HEALTHY`** → "Google Docs skills are ready." Done.
- **`DOCTOR: ACTION_REQUIRED` — client file needed (exit 3)** → get the file, re-run the doctor:
  - *Primary:* fetch Drive file ID `1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7` via the builder's
    Google Drive connector and write the bytes to
    `~/.config/gws-profiles/nsls-gdocs-skill/client_secret.json` — the doctor validates and
    strips it on the re-run. If the connector errors, don't loop; use the fallback.
  - *Fallback:* the builder downloads
    `https://drive.google.com/file/d/1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7/view` **signed in as
    their @nsls.org account** — it lands in Downloads, where the doctor finds and validates
    it on the re-run.
  - *Access denied?* Staff: ask in **#builders**. **Contractors: ask to be added to
    `gcp-builders@nsls.org`** (that group also carries the API quota grant they'll need).
- **Browser consent opens** → the BUILDER completes it as their **real @nsls.org account**
  (aliases and personal Google accounts are refused — the consent screen is Internal;
  that's the security model, not a gap). The agent kicks it off; only the human can click.
- **`DOCTOR: ERROR`** → read its message. No working Python on Windows (the Store-stub
  trap)? Use the manual fallback in `skills/gdoc-edit/references/setup.md`.

Never commit `client_secret.json` to any repo — it stays Drive-distributed.

## Step 6: Personal productivity (optional)

Pitch it, then let them choose the depth. **Two tiers:**

```
Last thing — the builders who get the most out of this toolkit use the personal
productivity skills: morning planning, end-of-day summaries, weekly reviews.

There are two ways in:
  • Light (~3 min) — works immediately, just a notes folder. Recommended to start.
  • Advanced — full Obsidian vault + plugins + graph view. Great, but more setup;
    you can add it anytime.

Want to set up the light version now? (yes / later)
```

`/personal-setup` exists the moment the toolkit is installed (it ships as a thin
bootstrapper in this org kit), so **"say /personal-setup anytime later" is a
real, working command** — no "unknown command" trap for anyone who defers.

### If yes:
Invoke `/personal-setup` — it installs+enables the personal kit if needed, syncs
its pointer skills immediately, and runs the light config. If it needs the full
personal kit and a restart, tell them plainly and hand off.

### If later:
```
No problem. Say /personal-setup anytime — it works right now, no install needed
first.
```

## Edge Cases

- **Re-running /setup after everything is configured**: detect state, confirm
  it's all good, offer /personal-setup. Steps 1 and 4 are idempotent.
- **Personal-toolkit clone into a dir that already holds `.env`**: `/personal-setup`
  handles this by preserving the existing `.env` across the clone (Step 1 may
  have written BUILDER_EMAIL there before the toolkit was cloned). Never `git
  clone` into a non-empty dir and assume success.
- **User isn't an NSLS employee**: org toolkit still works; set the email anyway,
  hooks degrade gracefully.
- **Windows builder skipped Step 4**: zero pings / zero skill events, counters
  stuck at 0. Re-run /setup, or `install.ps1` directly.
