---
name: setup
description: >-
  Onboarding for the NSLS Builder Toolkit. Confirms the builder email so the
  tracker can credit work, connects org tools one at a time (Slack, Google
  Drive, Google Calendar, Gmail, Fathom), verifies plugins, registers Windows
  hooks, checks GCP/gws access, and offers personal productivity setup.
  Use when first setting up, or when a tool connection seems broken.
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
  1. Confirm your builder email (so the tracker can credit your work)
  2. Connect your tools — Slack, Google Drive, Calendar, Gmail, Fathom
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
signed-in Claude account from this session's context — propose it and ask only
to confirm:

```
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

Confirm, and be transparent about the one bit of tracking so it never feels
hidden: "Got it — your work is now credited to <email>. Heads up: each time you
use a skill, the toolkit fires a tiny one-line ping to our NSLS tracker so you
get credit for it — just the skill name and your email, nothing about what you
were doing. You'll see it noted in the status line as it runs. That's the only
thing it phones home about." (If a permission prompt for `skill-event.sh` ever
appears, that's this same harmless ping — safe to approve; the installer
allowlists it so it shouldn't recur.)

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

## Step 2: Connect Your Tools (~2 min) — guided, one at a time

This is the most important step and the one builders stall on. **Do NOT dump a
list of settings paths.** Connect the recommended starter bundle **one connector
at a time**, each a connect-now-or-defer choice: one line on *why*, send them to
the exact Connectors panel, wait for them to come back. **Collect them all
first — do not verify yet.** Verification happens after a single restart at the
end of this step.

All five are **one-click "Authorize" connectors** in the desktop app — no API
keys, no tokens to paste. The bundle, in order:

1. **Slack** — team channels, standups, searches
2. **Google Drive** — read/write docs and files
3. **Google Calendar** — powers `/open-day`'s daily schedule
4. **Gmail** — draft and triage email
5. **Fathom** — meeting recordings and transcripts (`/close-day`, `person-intelligence`)

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
   #1 (Slack) only**:
   ```
   Open Settings → Connectors, find Slack, and click Authorize. A browser window
   opens — sign in and approve, then come back. Heads up: the app often drops you
   on the Home tab afterward and it looks like you lost this chat — you didn't.
   Click **Code** (top left) to return, and tell me when you're back.
   ```
   For **connectors #2–#5**, collapse to a one-line breadcrumb (the Home-tab
   note folds into it — don't repeat the whole paragraph):
   ```
   Next: Google Drive → Settings › Connectors › Google Drive › Authorize, approve
   in the browser, click **Code** to come back. Tell me when you're done.
   ```
3. **Wait** for "done." Note it as connected (pending restart) and go to the
   next. **Do not run a live read call yet.**

### End of Step 2: one restart, then verify

Once they've connected (or skipped) all five:

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

**1. Detect auth + the config path — never hardcode `~/.config/gws`.**

```bash
gws auth status 2>&1 || true
```
- If it shows a `storage` other than `none`, gws is already authed → "Google
  Docs skills are ready." Done.
- Otherwise read the **`client_config` path from that output** — it differs by
  platform (on Windows gws reports `C:\Users\<user>\.config\gws\...`). That
  directory is where `client_secret.json` must live. Do **not** assume
  `~/.config/gws`.

**2. If `client_secret.json` is missing at that path, place it for them.** It's
one shared OAuth *client* file — a Desktop client behind an **Internal** consent
screen — that only lets a sign-in *start*; the real token is minted per-user in
step 3. Two paths — try the connector, then a browser download that always
works:

- **Primary — the Google Drive connector** the builder connected in Step 2:
  fetch Drive file ID `1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7` and write its bytes to
  the client_config path from step 1. This works when the connector is the
  builder's own @nsls.org identity; if it returns not-found or the connector
  isn't live, go straight to the fallback (don't loop on the connector).
- **Guaranteed fallback — browser download:**
  1. Give them the link and tell them to open it **signed in as their @nsls.org
     account** and click **Download**:
     `https://drive.google.com/file/d/1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7/view`
  2. Find the downloaded file — glob the Downloads dir loosely (the Drive
     filename is long and quoted, so match `*client_secret*.json`):
     - macOS/Linux: `ls -t "$HOME/Downloads/"*client_secret*.json 2>/dev/null | head -1`
     - Windows: `Get-ChildItem "$env:USERPROFILE\Downloads\*client_secret*.json" | Sort-Object LastWriteTime | Select-Object -Last 1`
  3. Move+rename it to the EXACT client_config path from step 1 (create the dir
     if needed). On macOS/Linux `chmod 600` it; on Windows skip chmod (profile
     ACLs suffice).
  4. Re-run `gws auth status` and confirm the `client_config` file now exists
     before continuing — don't proceed to login until it's in place.
- **Last resort** — if the link is dead or access is denied, ask in **#builders**
  for the current link, then place the file and re-check as above.

**3. Kick off the per-user sign-in** (you may start it for them; they complete
the Google consent themselves):

```bash
gws auth login --services docs,drive
```
Exactly `docs,drive` — never broader. A browser opens for Google consent.

> ⚠️ **Real @nsls.org Workspace accounts only.** The consent screen is
> **Internal** to the nsls.org Workspace org, so an **alias** address, or a
> personal/consumer Google account that merely uses an nsls.org address, is
> **refused** with an unhelpful error. Use the actual org account.

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
