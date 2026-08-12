---
name: gws
description: >-
  Google Workspace CLI for Sheets, Docs, Slides, Drive, Gmail, and Calendar.
  Use when the user wants to read or edit Google Docs, work with spreadsheets,
  read or write Google Slides, manage Drive files, or any Google Workspace
  operation. ALWAYS prefer gws over WebFetch/WebSearch for any Google URL
  (docs.google.com, sheets, slides, drive) — it's free, authenticated, and
  returns structured data. Trigger on "google doc", "google sheet",
  "spreadsheet", "google slides", "gws", "read doc", "edit doc", "sheet data",
  "read sheet", "write to sheet", "google drive".
---

# gws — Google Workspace CLI

## IMPORTANT: Always Use gws for Google URLs

**Never use WebFetch or WebSearch to access Google Docs, Sheets, Slides, or Drive.** Those tools hit sign-in walls and return garbage HTML. Use `gws` instead — it's authenticated, free, and returns structured data you can actually work with.

- `docs.google.com/document/*` → `gws docs documents get`
- `docs.google.com/spreadsheets/*` → `gws sheets spreadsheets get` or `gws sheets +read`
- `docs.google.com/presentation/*` → `gws slides presentations get`
- `drive.google.com/*` → `gws drive files get`

## NSLS toolkit profile — required for gdoc work; the fix for wrong-project 403s

Machines can hold OAuth client files from several gws-based tools; the default config dir
is contested ground (a foreign client there 403s every call with "…required permission to
use project `<other-project>`…"). The gdoc skills (`/gdoc-edit`, `/gdoc-build`, `/setup`'s
turnkey step) ALWAYS run from the toolkit's own profile; for other gws work, a healthy
default dir is fine — but on any wrong-project 403, switch to the profile (and log in with
the services you actually need, e.g. `--services docs,drive,sheets`):

```bash
export GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$HOME/.config/gws-profiles/nsls-gdocs-skill"
```
```powershell
$env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR = "$env:USERPROFILE\.config\gws-profiles\nsls-gdocs-skill"
```

**One command does all of it** — provision, validate, strip, consent with the right
scope union (run with a generous timeout; the login step waits for a human):

```bash
python3 <plugin>/skills/gws/scripts/gws_doctor.py --services docs,drive
```

After `DOCTOR: HEALTHY`, run your gws commands with the profile — **agents: chain the
export and the command in ONE shell call** (each Bash call is a fresh shell):
`export GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws-profiles/nsls-gdocs-skill; gws <command>`

Background, manual fallback, and the 403-signature table:
[`references/multi-secret-profiles.md`](references/multi-secret-profiles.md).

## What This Does

Wraps the `gws` CLI to interact with all Google Workspace services from the command line. Supports Sheets, Docs, Slides, Drive, Gmail, Calendar, and more.

The CLI follows a consistent pattern: `gws <service> <resource> [sub-resource] <method> [flags]`.

Full reference: `references/gws-reference.md` (relative to this skill)

---

## Prerequisites — Auto-Install

If `gws` is not on the PATH, install it.

**macOS / Linux:**
```bash
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/googleworkspace/cli/releases/latest/download/google-workspace-cli-installer.sh | sh
```

**Windows** (the shell installer above is bash-only) — download the release zip,
extract `gws.exe` to `%LOCALAPPDATA%\Programs\gws`, add it to PATH:
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

This installs the latest release from https://github.com/googleworkspace/cli.

> ⚠️ **Windows needs the MS Visual C++ x64 runtime.** Without it `gws.exe` exits with
> `0xC0000135` and **prints nothing at all** — near-impossible to debug blind. Install it
> from https://aka.ms/vs/17/release/vc_redist.x64.exe (double-click → Yes → Install).
> `install.ps1` stages this in your Downloads folder and prints the step.

After install, authenticate — **mode-specific**:

- **Toolkit gdoc work** (gdoc-edit/gdoc-build/setup): run
  `python3 <plugin>/skills/gws/scripts/gws_doctor.py` — it forces the profile, validates the
  client, and logs in with `granted ∪ requested`, so credentials land inside the profile
  without disturbing scopes another skill already holds there. Do **not** hand-run
  `gws auth login --services docs,drive` against the profile: it stores only what you asked
  for, so a gdoc repair silently strips the sheets scope `squad-dashboard` needs (or gmail
  for `receipts`). If you must log in by hand, follow the union rule in
  [`references/multi-secret-profiles.md`](references/multi-secret-profiles.md) — request
  everything `gws auth status` already lists plus what you need.
- **Ad-hoc gws use:** a bare `gws auth login` stores credentials in the default dir
  (`~/.config/gws`). Fine when that dir is healthy — but don't use a bare login to fix a
  toolkit-skill auth error (it authenticates the wrong directory).

Either way a browser opens for Google OAuth2 consent.

---

## Authentication

`gws` uses Google OAuth2. Credentials are resolved in this order:

1. `GOOGLE_WORKSPACE_CLI_TOKEN` — pre-obtained OAuth2 access token (highest priority)
2. `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` — path to an OAuth credentials JSON file
3. Stored credentials in the **active config dir** — `GOOGLE_WORKSPACE_CLI_CONFIG_DIR`
   when set (e.g. the toolkit profile), else the default `~/.config/gws`

On exit code 2 (auth error), re-run `gws auth login` **in the same config dir the failing
call used** — for toolkit skills that means with the profile env var set (and
`--services docs,drive` at minimum). A bare re-login from a different dir "succeeds" while
the failing skill keeps erroring.

---

## Common Operations

### Read a range (helper — use this first)

```bash
gws sheets +read --spreadsheet SHEET_ID --range "Sheet1!A1:D10"
gws sheets +read --spreadsheet SHEET_ID --range Sheet1        # whole sheet
gws sheets +read --spreadsheet SHEET_ID --range "Sheet1!A1:D10" --format table
gws sheets +read --spreadsheet SHEET_ID --range "Sheet1!A1:D10" --format csv
```

`+read` is read-only and never modifies the spreadsheet. Prefer it over the raw `values get` for simple reads.

### Append a row (helper)

```bash
# Simple single-row append
gws sheets +append --spreadsheet SHEET_ID --values 'Alice,100,true'

# Multi-row bulk insert
gws sheets +append --spreadsheet SHEET_ID --json-values '[["Alice","100"],["Bob","200"]]'
```

Values are appended after the last row that contains data (Google Sheets "smart append" behavior).

### Read a range (raw API)

```bash
gws sheets spreadsheets values get \
  --params '{"spreadsheetId": "SHEET_ID", "range": "Sheet1!A1:D10"}'
```

### Write to a range

```bash
gws sheets spreadsheets values update \
  --params '{"spreadsheetId": "SHEET_ID", "range": "Sheet1!A1:B2", "valueInputOption": "USER_ENTERED"}' \
  --json '{"values": [["Name", "Score"], ["Alice", 95]]}'
```

`valueInputOption` options:
- `USER_ENTERED` — parses values like the Sheets UI (formulas, dates, numbers)
- `RAW` — stores values as-is (strings, no formula parsing)

### Batch read multiple ranges

```bash
gws sheets spreadsheets values batchGet \
  --params '{"spreadsheetId": "SHEET_ID", "ranges": ["Sheet1!A1:B5", "Sheet2!C1:D3"]}'
```

### Batch write multiple ranges

```bash
gws sheets spreadsheets values batchUpdate \
  --params '{"spreadsheetId": "SHEET_ID"}' \
  --json '{
    "valueInputOption": "USER_ENTERED",
    "data": [
      {"range": "Sheet1!A1", "values": [["Hello"]]},
      {"range": "Sheet2!B2", "values": [["World"]]}
    ]
  }'
```

### Clear a range

```bash
gws sheets spreadsheets values clear \
  --params '{"spreadsheetId": "SHEET_ID", "range": "Sheet1!A2:Z100"}'
```

### Create a new spreadsheet

```bash
gws sheets spreadsheets create \
  --json '{"properties": {"title": "My New Sheet"}}'
```

Returns the full spreadsheet object including the new `spreadsheetId`.

### Get spreadsheet metadata

```bash
# Metadata only (no grid data)
gws sheets spreadsheets get \
  --params '{"spreadsheetId": "SHEET_ID"}'

# Include grid data
gws sheets spreadsheets get \
  --params '{"spreadsheetId": "SHEET_ID", "includeGridData": true}'
```

### Format cells and apply structural changes (batchUpdate)

All formatting, adding/deleting sheets, freezing rows, resizing columns, etc. go through `batchUpdate` with a `requests` array:

```bash
gws sheets spreadsheets batchUpdate \
  --params '{"spreadsheetId": "SHEET_ID"}' \
  --json '{
    "requests": [
      {
        "repeatCell": {
          "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
          "cell": {
            "userEnteredFormat": {
              "textFormat": {"bold": true},
              "backgroundColor": {"red": 0.2, "green": 0.4, "blue": 0.8}
            }
          },
          "fields": "userEnteredFormat(textFormat,backgroundColor)"
        }
      }
    ]
  }'
```

Common `requests` types: `repeatCell`, `updateSheetProperties`, `addSheet`, `deleteSheet`, `mergeCells`, `updateDimensionProperties`, `updateBorders`.

### Copy a sheet to another spreadsheet

```bash
gws sheets spreadsheets sheets copyTo \
  --params '{"spreadsheetId": "SOURCE_ID", "sheetId": 0}' \
  --json '{"destinationSpreadsheetId": "DEST_ID"}'
```

---

## Tips and Patterns

**Extract the spreadsheet ID from a URL.**
The ID is the long string between `/d/` and `/edit` in the Sheets URL:
`https://docs.google.com/spreadsheets/d/SHEET_ID/edit`

**Use `--format table` for quick visual inspection.**
```bash
gws sheets +read --spreadsheet SHEET_ID --range "Sheet1!A1:E20" --format table
```

**Use `--format csv` to pipe into other tools.**
```bash
gws sheets +read --spreadsheet SHEET_ID --range Sheet1 --format csv | python3 -c "import sys,csv; ..."
```

**Dry-run before destructive writes.**
```bash
gws sheets spreadsheets values update --dry-run \
  --params '{"spreadsheetId": "SHEET_ID", "range": "Sheet1!A1", "valueInputOption": "RAW"}' \
  --json '{"values": [["test"]]}'
```

**Batch writes are faster and cheaper than single-cell updates.** Prefer `batchUpdate` or `+append --json-values` when writing multiple rows.

**Sheet names with spaces need quotes in range notation.**
`"My Sheet!A1:B10"` — always quote the whole `--range` value.

**`sheetId` in batchUpdate is an integer, not the spreadsheet ID.** Get it from `spreadsheets get` — it's `sheets[].properties.sheetId` (usually 0 for the first tab).

---

## Google Docs

### Read a document

```bash
# Get full document structure (JSON with content, styles, positions)
gws docs documents get --params '{"documentId": "DOC_ID"}'

# Extract plain text from a doc (pipefail so a failed fetch doesn't look like an empty doc)
set -o pipefail
gws docs documents get --params '{"documentId": "DOC_ID"}' | tail -n +2 | python3 -c "
import json, sys
doc = json.load(sys.stdin)
for elem in doc.get('body', {}).get('content', []):
    if 'paragraph' in elem:
        for e in elem['paragraph'].get('elements', []):
            print(e.get('textRun', {}).get('content', ''), end='')
"
```

The document ID is the long string between `/d/` and `/edit` in the URL:
`https://docs.google.com/document/d/DOC_ID/edit`

### Edit a document (find and replace)

```bash
gws docs documents batchUpdate --params '{"documentId": "DOC_ID"}' --json '{
  "requests": [
    {
      "replaceAllText": {
        "containsText": {"text": "old text", "matchCase": true},
        "replaceText": "new text"
      }
    }
  ]
}'
```

### Edit a document (insert/delete by position)

Use `insertText` and `deleteContentRange` with character indices from the document structure:

```bash
gws docs documents batchUpdate --params '{"documentId": "DOC_ID"}' --json '{
  "requests": [
    {"deleteContentRange": {"range": {"startIndex": 100, "endIndex": 150}}},
    {"insertText": {"location": {"index": 100}, "text": "New content here"}}
  ]
}'
```

**Important:** When mixing inserts and deletes in one batch, process from end to start so indices don't shift.

---

## Google Slides

### Read a presentation

```bash
gws slides presentations get --params '{"presentationId": "PRES_ID"}'
```

### Create a presentation

```bash
gws slides presentations create --json '{"title": "My Presentation"}'
```

---

## Google Drive

### List files

```bash
gws drive files list --params '{"pageSize": 10, "q": "name contains '\''report'\''"}'
```

### Download/export a file

```bash
# Export a Google Doc as PDF
gws drive files export --params '{"fileId": "FILE_ID", "mimeType": "application/pdf"}' --output doc.pdf
```

---

## Explore the Full API

Use `gws schema` to discover any method across all services:

```bash
gws schema docs.documents.batchUpdate --resolve-refs
gws schema sheets.spreadsheets.values.update --resolve-refs
gws schema slides.presentations.get --resolve-refs
gws schema drive.files.list --resolve-refs
```

---

## Exit Codes

- `0` — success
- `1` — API error (Google returned an error response)
- `2` — auth error (credentials missing or expired in the ACTIVE config dir — re-run `gws auth login` with the same `GOOGLE_WORKSPACE_CLI_CONFIG_DIR` the failing call used)
- `3` — validation error (bad arguments)

### Two ways gws reports failure — check both

`gws` prints a `Using keyring backend: keyring` line that breaks naive JSON parsing, so almost every recipe filters it. Both common filters destroy your ability to detect failure. **Writes are where this bites**: the call reports success, nothing changed, and you tell the user it worked.

**1. A piped filter replaces the exit status.** A shell pipeline exits with its *last* command's status, so `gws … | grep -v keyring | tail -5` gives you `tail`'s `0` — even on a 403.

```bash
set -o pipefail   # REQUIRED before any piped gws call
gws drive files create … | grep -v -i keyring | tail -5
```

Proof, against a nonexistent file:

```
without pipefail: exit=0    # failure invisible
with pipefail:    exit=1    # failure caught
```

**2. The error body is valid JSON on stdout.** `pipefail` doesn't help here. A bad `documentId` exits 1 *and* prints this to **stdout**:

```json
{ "error": { "code": 404, "message": "Requested entity was not found.", "reason": "unknown" } }
```

Any caller that parses stdout gets that dict back looking exactly like a result. In Python, check the return code *and* the payload — `returncode == 2` alone is not enough:

```python
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    raise RuntimeError(f"gws exit {r.returncode}: {(r.stderr or r.stdout)[:300]}")
parsed = json.loads(...)                    # tolerate the keyring line
if isinstance(parsed, dict) and "error" in parsed:
    raise RuntimeError(f"gws error payload: {parsed['error']}")
```

**After any write, verify by re-reading the resource.** An exit code is weak evidence that a write landed — re-read it and assert the change is actually there. See also the `--dry-run` flag, which prints the resolved body/query params without sending, for checking an unfamiliar call's shape before you run it.
