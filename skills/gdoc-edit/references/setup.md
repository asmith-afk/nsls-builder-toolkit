# gdoc-edit — setup

`gdoc-edit` talks to the Google Docs + Drive APIs through **`gws`** (the Google Workspace
CLI). The toolkit installer installs the `gws` binary for you — `install.sh` on
macOS/Linux, `install.ps1` on Windows; if you're on a machine where it isn't present, step
1 below installs it. Every call runs as **you** — your Google identity, your document
permissions. **No per-person deployment: you fetch one shared client file, then mint your
own token.** Setup is a one-time `gws auth login`.

**Everything below happens inside the toolkit's gws PROFILE** — its own config
directory, so this skill coexists with any other Google tool's client file on the same
machine (that collision is a real, recurring incident). Set it before every step here,
once per shell:

```bash
export GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$HOME/.config/gws-profiles/nsls-gdocs-skill"
```
```powershell
$env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR = "$env:USERPROFILE\.config\gws-profiles\nsls-gdocs-skill"
```

With that set: if `gws auth status` shows `storage` other than `none` **and** the file at
`client_config` is the canonical client (`client_id` starts with `598752584124-` — check
snippets in `../../gws/references/multi-secret-profiles.md`), you're done — skip to the
smoke test. A client file that exists but has a different `client_id` belongs to another
tool: **don't touch it**; continue below to provision the profile.

**Fast path — run the doctor instead of the manual steps:**
`python3 <plugin>/skills/gws/scripts/gws_doctor.py` does everything below (acquire,
validate, strip, verify, consent with the right scopes) and prints `DOCTOR: HEALTHY`
when done. The manual steps below remain as the fallback for when the doctor script
itself isn't on disk yet (plugin not installed). On Windows they are also the
no-Python path (Store-stub trap — see the smoke-test note at the bottom); the
macOS/Linux placement snippet needs the same `python3` the doctor does.

---

## Builder setup (the common case, ~2 min)

### 1. Make sure `gws` is installed

**macOS / Linux:**
```bash
gws --version || curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/googleworkspace/cli/releases/latest/download/google-workspace-cli-installer.sh | sh
```

**Windows** (the installer script above is bash-only). Download the release zip,
extract `gws.exe`, add it to PATH — `install.ps1` does this for you; this is the manual path:
```powershell
$dir = "$env:LOCALAPPDATA\Programs\gws"
New-Item -ItemType Directory -Force $dir | Out-Null
$zip = "$env:TEMP\gws-win.zip"
Invoke-WebRequest -UseBasicParsing `
  -Uri "https://github.com/googleworkspace/cli/releases/latest/download/google-workspace-cli-x86_64-pc-windows-msvc.zip" `
  -OutFile $zip
Expand-Archive -Force $zip "$env:TEMP\gws-extract"
$exe = (Get-ChildItem "$env:TEMP\gws-extract" -Recurse -Filter gws.exe | Select-Object -First 1).FullName
Copy-Item $exe "$dir\gws.exe" -Force
# Add to user PATH once (idempotent: no duplicate on re-run, no leading ';' when empty).
$u = [Environment]::GetEnvironmentVariable('Path','User')
if (($u -split ';') -notcontains $dir) { [Environment]::SetEnvironmentVariable('Path', (@($u, $dir) | Where-Object { $_ }) -join ';', 'User') }
```

> ⚠️ **Windows also needs the MS Visual C++ x64 runtime.** Without it `gws.exe`
> exits with `0xC0000135` and **prints nothing at all** — near-impossible to
> debug blind. If gws is silent or failing on Windows, install the runtime: open
> File Explorer → Downloads → double-click `VC_redist.x64.exe` → click Yes →
> Install (or download it from https://aka.ms/vs/17/release/vc_redist.x64.exe).
> `install.ps1` stages that file in your Downloads folder and prints the same step.

### 2. Get the NSLS OAuth client

`gdoc-edit` uses one shared OAuth **client** (a Desktop client in the `nsls-gdocs-skill`
GCP project). The client file is *not* something you type — you fetch it once and drop it
in place. It only lets you *start* a Google sign-in; the actual access is your own
per-user token, minted in the next step.

> Why a shared file and not "download it from the console"? Google only shows a client
> secret **once, at creation** — it can never be viewed or re-downloaded afterwards. So
> the client JSON is distributed as a file instead.

0. **Zero-download shortcut:** if a PRE-PROFILE install left the canonical client at the
   default `~/.config/gws/client_secret.json` (verify the `client_id` starts with
   `598752584124-`), copy that into the profile instead of downloading — then jump to the
   placement snippet below. Never move or modify the default-dir file, and never use it if
   its `client_id` differs (it's another tool's).
1. Download `client_secret.json` from the NSLS builders shared Drive location,
   signed in as your **@nsls.org** account:
   **https://drive.google.com/file/d/1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7/view**
   (file ID `1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7` — view-only; shared to
   `allstaff@nsls.org` and `gcp-builders@nsls.org`, unlisted and not discoverable by
   search). Access denied? Staff: ask in **#builders**. **Contractors: you're not in
   allstaff — ask to be added to `gcp-builders@nsls.org`** (that group also carries the
   API quota grant you'll need).
2. Place it in the **profile** (env var above still set) — confirm the target with
   `gws auth status` (it prints the `client_config` location) — **neutralizing
   `project_id` (set it to `""`) as you place it** (defends against gws bug #729, which
   otherwise 403s anyone not IAM-bound to the client's project). **Set to empty — never
   REMOVE the field:** gws's strict parser rejects the whole file if `project_id` is
   absent ("No OAuth client configured").

**Manual fallback (no working Python).** The placement below **validates the source** (Downloads can contain other tools' client
files too — never place on filename alone), **backs up** any foreign file squatting in
OUR profile (other tools' own directories are still never touched), **neutralizes
`project_id` to `""`**, and **verifies the result**.

**macOS / Linux:**
```bash
mkdir -p "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR"
# Choose exactly ONE source line:
SRC=$(ls -t ~/Downloads/*client_secret*.json | head -1)   # (a) fresh Drive download (common case)
# SRC="$HOME/.config/gws/client_secret.json"                # (b) step-0 copy from a pre-profile install
python3 - "$SRC" "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/client_secret.json" << 'EOF'
import json, os, sys, time
src, dest = sys.argv[1], sys.argv[2]
# Full-ID equality, not prefix: sibling clients in the same GCP project share the prefix
CANON = "598752584124-4t7bdffqchrt8b6nlv1uuhpkl1b24vtc.apps.googleusercontent.com"
d = json.load(open(src)); ins = d.get("installed", {})
cid = ins.get("client_id", "")
if cid != CANON:
    sys.exit(f"STOP: source is a FOREIGN client ({cid[:20] or 'no client_id'}…) — wrong file, pick the canonical one")
if os.path.islink(dest):  # never write THROUGH a link — its target may live in another tool's directory
    bak = dest + f".symlink-{int(time.time())}.bak"
    os.rename(dest, bak); print(f"note: dest was a symlink — moved the link aside to {bak} (target untouched)")
elif os.path.exists(dest):
    old = json.load(open(dest)).get("installed", {}).get("client_id", "")
    if old != CANON:
        bak = dest + f".foreign-{int(time.time())}.bak"
        os.rename(dest, bak); print(f"note: foreign file was in OUR profile — backed up to {bak}")
ins["project_id"] = ""  # NEVER pop: gws refuses the file if the field is absent
json.dump(d, open(dest, "w"))
chk = json.load(open(dest)).get("installed", {})
assert chk.get("client_id") == CANON and chk.get("project_id") == "", "verify failed — redo from a fresh download"
print("placed + verified: canonical client, project_id neutralized")
EOF
chmod 600 "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/client_secret.json"
```

**On Windows** — same `.config` shape (`gws auth status` reports
`C:\Users\<user>\.config\...`); no `chmod` (profile ACLs already restrict the user
profile); written **without a BOM** (a BOM breaks JSON consumers):
```powershell
New-Item -ItemType Directory -Force $env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR | Out-Null
# Choose exactly ONE source line:
$src = (Get-ChildItem "$env:USERPROFILE\Downloads\*client_secret*.json" | Sort-Object LastWriteTime | Select-Object -Last 1).FullName   # (a) fresh download (common case)
# $src = "$env:USERPROFILE\.config\gws\client_secret.json"  # (b) step-0 copy from a pre-profile install
$dest = "$env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR\client_secret.json"
# Full-ID equality, not prefix: sibling clients in the same GCP project share the prefix
$canon = "598752584124-4t7bdffqchrt8b6nlv1uuhpkl1b24vtc.apps.googleusercontent.com"
$d = Get-Content $src -Raw | ConvertFrom-Json
if ("$($d.installed.client_id)" -ne $canon) { throw "STOP: source is a FOREIGN client - wrong file, pick the canonical one" }
if ((Test-Path $dest) -and (Get-Item $dest -Force).LinkType) {
  # never write THROUGH a link - its target may live in another tool's directory
  Move-Item $dest "$dest.symlink.bak" -Force; "note: dest was a symlink - moved the link aside (target untouched)"
}
elseif (Test-Path $dest) {
  if ("$((Get-Content $dest -Raw | ConvertFrom-Json).installed.client_id)" -ne $canon) {
    Move-Item $dest "$dest.foreign.bak" -Force; "note: foreign file was in OUR profile - backed up to $dest.foreign.bak"
  }
}
# NEVER remove project_id - gws refuses the file if the field is absent; empty it instead
$d.installed | Add-Member -NotePropertyName project_id -NotePropertyValue "" -Force
[System.IO.File]::WriteAllText($dest, ($d | ConvertTo-Json -Depth 10), (New-Object System.Text.UTF8Encoding $false))
$chk = (Get-Content $dest -Raw | ConvertFrom-Json).installed
if (-not ("$($chk.client_id)" -eq $canon -and ($chk.project_id -eq ""))) { throw "verify failed - redo from a fresh download" }
"placed + verified: canonical client, project_id neutralized"
```

The file is low-sensitivity by design: it's a Desktop-type client on an **Internal**
consent screen, so it is useless to anyone without an @nsls.org Google account — all it
can do is start a sign-in that only NSLS accounts can complete. Still, don't commit it
to any repo.

### 3. Log in (per-user, minimal scopes)

```bash
gws auth login --services docs,drive
```

> ⚠️ **Check `gws auth status` first if this profile has ever been used by another skill.**
> A manual login stores exactly the services you name, replacing what was there — so a bare
> `--services docs,drive` strips a sheets or gmail scope `squad-dashboard`/`receipts` had
> granted. Request the **union**: everything `gws auth status` already lists, plus
> `docs,drive`. `gws_doctor.py` does this arithmetic for you and is the preferred path
> wherever Python works.

A browser opens for Google consent. Because the app is **Internal**, only a real
**`@nsls.org` Google Workspace account** can complete it — an **alias** address, or a
personal/consumer Google account that merely *uses* an nsls.org address, is **refused**
with an unhelpful error. `--services docs,drive` requests only the Docs + Drive scopes this
skill needs — not the full Workspace surface. Your refresh token is stored **encrypted**
inside the profile directory; you won't be asked again. (Builders who authed in the
default dir before profiles existed re-consent once here — ~20 seconds; their old
credentials are left untouched.)

### 4. Smoke test

```bash
S=~/.claude/local-plugins/nsls-builder-toolkit/skills/gdoc-edit/scripts/gdoc.py
python3 $S read     --doc <ANY_DOC_ID_YOU_CAN_OPEN> | head
python3 $S comments --doc <ANY_DOC_ID_YOU_CAN_OPEN>
```

> **On Windows**, use the FULL Python path — `python`/`python3` on stock Win11 are
> Microsoft Store stubs that print "Python was not found" and exit 0, so a naive
> check passes while nothing runs. Use the path `install.ps1` installs to:
> `& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" $S read --doc <ID>`.

`read` prints the doc text; `comments` prints a JSON array. If you get **exit 2 / auth
error**, re-run step 3. If you get a **project / permission** error, you're missing read
access to `nsls-gdocs-skill` (step 2.1).

---

## What changed from the old webhook

Earlier versions of this skill used a personal Apps Script web app (a `/exec` URL + a
`SHARED_SECRET` in `~/.config/gdoc-edit/config.json`). That was tied to one person's
identity and couldn't be shared safely. **It's retired.** You no longer need
`~/.config/gdoc-edit/config.json` — delete it if you have one. The old Apps Script is kept
for reference at `references/legacy/gas-doc-webhook.gs` only.

---

## Admin: creating the shared OAuth client (one-time, done once for the org)

Only needed once, by whoever stands up the `nsls-gdocs-skill` project. Requires GCP access
to that project. **Done 2026-07-12** (client `gdoc-edit desktop client`,
ID `598752584124-4t7bdffqchrt8b6nlv1uuhpkl1b24vtc.apps.googleusercontent.com`) — recorded
here in case it ever has to be recreated.

1. **Reauth gcloud** (interactive): `gcloud auth login` and
   `gcloud config set project nsls-gdocs-skill`.
2. **Enable the Workspace APIs**: `gws auth setup --project nsls-gdocs-skill`. This enables
   the APIs, then **stops with a validation error at OAuth-client creation** — that part is
   console-only (Google removed API/CLI creation of desktop clients). Expected; continue.
3. **Create the consent screen** (console → Google Auth Platform → Overview → Get started,
   project `nsls-gdocs-skill`): App name `NSLS gdoc-edit`, support email an NSLS address,
   **Audience: Internal** ← the critical choice: only `@nsls.org` can authorize, and the
   sensitive Docs/Drive scopes need no Google verification review. Agree + Create.
4. **Create the client** (Clients → Create client): Application type **Desktop app**, name
   `gdoc-edit desktop client`. **Download the JSON immediately from the creation dialog** —
   Google shows/downloads a client secret **only at creation**; there is no retrieval later.
   (Missed the window? Open the client → **Add secret** → capture the new secret in the same
   dialog, disable+delete the old one. A client holds max 2 secrets.)
5. **Distribute**: place the JSON into YOUR toolkit profile using the validated placement
   snippet above (**never the default `~/.config/gws` — it may hold another tool's client
   file, which must not be overwritten**), and put a copy in the NSLS builders shared
   Drive location (shared to `allstaff@nsls.org` + `gcp-builders@nsls.org` as readers) —
   that's what builder-setup step 2 points at.
6. **Log in and verify** (profile env var set): `python3 <plugin>/skills/gws/scripts/gws_doctor.py`
   (or, logging in by hand, `gws auth login --services <union of already-granted + docs,drive>`),
   then the smoke test. The `client_id` is the detail to register/track centrally — if it
   ever changes, update the canonical prefix in `multi-secret-profiles.md` and everywhere
   that validates it.

Do **not** commit `client_secret.json` (or the id/secret) to the toolkit repo. It's a
Desktop-type client — low sensitivity by Google's model, useless outside @nsls.org thanks
to the Internal consent screen — but the NSLS pattern is that no credential lives in git.
