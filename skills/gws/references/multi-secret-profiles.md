# gws multi-secret profiles — how toolkit skills coexist with other Google tools

**The problem this solves (real incidents, 2026-07/08):** `gws` keeps ONE config
directory by default (`~/.config/gws/`). Any NSLS tool that uses gws writes its
OAuth client file to that same path — last writer wins. A builder who set up
another gws-based tool (e.g. one registered to project `nsls-knowledgebase`)
then runs `/gdoc-edit` and every call 403s with *"Caller does not have required
permission to use project nsls-knowledgebase…"* — because the toolkit is
speaking through the wrong client. Deleting or overwriting the other tool's
file just breaks the other tool instead. Machines legitimately hold **two or
more client secrets**; each tool must select its own.

**The rule:** toolkit skills never fight over the default directory. They run
gws from the toolkit's own **profile directory**, selected per-invocation with
the env var gws already supports:

```bash
# bash/zsh — set once per session, before any gws call
export GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$HOME/.config/gws-profiles/nsls-gdocs-skill"
```
```powershell
# PowerShell
$env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR = "$env:USERPROFILE\.config\gws-profiles\nsls-gdocs-skill"
```

Everything gws needs (client file, encrypted credentials, token cache) lives
inside that directory. Other tools keep the default directory or their own
profiles; nobody stomps anybody.

## The canonical toolkit client

The toolkit's shared OAuth client (Desktop type, Internal consent screen,
project `nsls-gdocs-skill`) is identified by its public client id:

```
598752584124-4t7bdffqchrt8b6nlv1uuhpkl1b24vtc.apps.googleusercontent.com
```

**Identify a client file by `client_id`, never by `project_id`** — the
toolkit neutralizes `project_id` to `""` at placement time (see below), and a
client id is the actual identity of a client. Validation one-liner (works with any file):

```bash
python3 - "$FILE" << 'EOF'
import json,sys
cid=json.load(open(sys.argv[1])).get('installed',{}).get('client_id','')
print("CANONICAL" if cid == "598752584124-4t7bdffqchrt8b6nlv1uuhpkl1b24vtc.apps.googleusercontent.com" else f"FOREIGN ({cid[:20]}…)")
EOF
```
```powershell
$cid = "$((Get-Content $FILE -Raw | ConvertFrom-Json).installed.client_id)"
if ($cid -eq "598752584124-4t7bdffqchrt8b6nlv1uuhpkl1b24vtc.apps.googleusercontent.com") { "CANONICAL" } else { "FOREIGN ($cid)" }
```
(The `"$( … )"` wrapper coerces a missing/`web`-shaped `client_id` to an empty string, so
non-`installed` JSON safely classifies as FOREIGN instead of throwing.)

## Provisioning the profile (the repair block)

Run this whenever the profile is missing, invalid, or a gws call fails with a
wrong-project 403. Idempotent; safe to re-run.

1. **Set the env var** (above), then `gws auth status`. If `client_config_exists`
   is true, **no `client_config_error` is reported** (gws rejecting the file it
   found — e.g. a legacy placement that REMOVED `project_id`), the client file
   validates as CANONICAL, and `storage` is not `none` → healthy, stop here.
2. **Get the canonical client file into the profile dir** (create the dir first;
   never touch any other directory's files):
   - If the DEFAULT dir's `~/.config/gws/client_secret.json` exists **and
     validates as CANONICAL** → **copy** it into the profile (do not move — leave
     the default in place for anything else using it).
   - Otherwise fetch from Drive, file ID `1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7`
     (shared to `allstaff@nsls.org` + `gcp-builders@nsls.org` as readers):
     connector-fetch the bytes if the builder's Drive connector is live, else
     have them download it in a browser **signed in as their real @nsls.org
     account** — `https://drive.google.com/file/d/1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7/view`
     — then **leave it in Downloads**; the step-3 placement reads it from there.
3. **Place with validation + neutralize** — use the complete end-to-end snippets in
   `skills/gdoc-edit/references/setup.md` § "Get the NSLS OAuth client" (both
   platforms). They: validate the SOURCE's `client_id` before writing (the
   Downloads glob can catch other tools' clients — never place on filename
   alone), back up any foreign file found squatting in OUR profile (other
   tools' own directories are still never touched), neutralize `project_id` to
   `""` — **set empty, never removed: gws's strict parser rejects the whole
   file if the field is absent** (defuses gws bug
   [googleworkspace/cli#729](https://github.com/googleworkspace/cli/issues/729),
   which stamps calls with `x-goog-user-project` and 403s anyone not IAM-bound
   to the project), write BOM-free on Windows, and re-verify the placed file.
4. **One-time consent into the profile** (per user, per profile — this is the
   security model, not a gap; the agent kicks it off, the human completes it):
   ```bash
   python3 <plugin>/skills/gws/scripts/gws_doctor.py
   ```
   `docs,drive` is the gdoc-family baseline the doctor requests by default; a
   skill that needs more passes `--services`. Prefer the doctor over a bare
   `gws auth login --services docs,drive` even on a first provision — if the
   profile already holds another skill's scopes, the raw login drops them,
   whereas the doctor applies the **union rule** below automatically. Real
   @nsls.org Workspace accounts only (the consent screen is Internal; aliases
   and consumer accounts are refused).
5. Re-run `gws auth status`: confirm `storage` ≠ `none` **and** the `scopes`
   list covers the services your skill needs (a canonical client with the
   wrong scopes is NOT healthy — re-login per the union rule).

**Migration note for pre-profile installs:** the gdoc skills use ONLY the
profile from this version on — default-dir credentials no longer count for
them (they stay untouched, and other tools can keep using them). A builder who
authed pre-profile runs `gws_doctor.py` once: it copies their canonical client
into the profile automatically and walks them through one ~20-second
re-consent. Until they do, gdoc skills report exit 2 with exactly that
instruction.

## Foreign client found? Leave it alone.

If the default dir (or any other profile) holds a FOREIGN client: **do not
delete, rename, move, or overwrite it.** Tell the builder: *"another Google
tool (project `<its project_id, if present>`) owns the default gws config;
the NSLS toolkit runs from its own profile, so both keep working."* That's the
whole point of profiles.

## 403 signature table (what an error actually means)

| Error contains | Meaning | Fix |
|---|---|---|
| `…use project nsls-gdocs-skill… serviceUsageConsumer…` | Right client; the caller isn't covered by the project's quota grant | Staff are covered via `allstaff@nsls.org`. **Contractors aren't in allstaff** — ask to be added to **`gcp-builders@nsls.org`** (group owner: kprentiss). |
| `…use project <anything else>…` | gws is using a FOREIGN client — the profile env var isn't set, or the profile was never provisioned | Run the repair block above. Never edit the foreign file. |
| Consent screen refuses / "access blocked" | Alias or consumer Google account | Sign in with the real @nsls.org org account. |
| `gws` exit 2 / "run gws auth login" | No credentials **in this profile** (default-dir auth doesn't count) | Repair block steps 4–5. |

## Scopes are per-profile — the UNION RULE

A profile's credentials carry ONLY the services requested at its **last**
`gws auth login` — a new login **replaces** the token. So any login into the
shared toolkit profile MUST request the union of (a) `docs,drive` (the gdoc
baseline — omitting it breaks /gdoc-edit and /gdoc-build for everyone on this
machine) and (b) whatever the invoking skill needs:

**Don't hand-compute the union — run the doctor**, which reads the live granted
scopes and logs in with `granted ∪ requested` automatically:

| Skill | command |
|---|---|
| gdoc-edit / gdoc-build / setup | `python3 <plugin>/skills/gws/scripts/gws_doctor.py` |
| squad-dashboard (sheets) | `python3 <plugin>/skills/gws/scripts/gws_doctor.py --services docs,drive,sheets` |
| receipts (gmail) | `python3 <plugin>/skills/gws/scripts/gws_doctor.py --services docs,drive,gmail` |

(Manual logins must follow the same rule by hand: request the union of what
`gws auth status` already shows plus what you need — a narrower login silently
breaks the other skills sharing the profile.)

Health check = canonical client **and** credentials present **and** the needed
services appear in `gws auth status`'s `scopes` list — `gws_doctor.py` checks
all three and its `DOCTOR: HEALTHY` line is the green light.

Skills outside the gdoc family may keep using a HEALTHY default dir; they
switch to the profile (via this union rule) only when repairing a
wrong-project 403.

## For scripts

Scripts that shell out to gws must **force** the profile into each spawned
process — never `setdefault`, which lets an ambient (possibly foreign)
`GOOGLE_WORKSPACE_CLI_CONFIG_DIR` leak in, and never a separate `export` step,
which doesn't survive between an agent's Bash calls. `gdoc.py` (gdoc-edit) and
`gws_doctor.py` both do exactly this:

```python
PROFILE = os.path.expanduser("~/.config/gws-profiles/nsls-gdocs-skill")
env = dict(os.environ, GOOGLE_WORKSPACE_CLI_CONFIG_DIR=PROFILE)
subprocess.run(["gws", *args], env=env, ...)
```
