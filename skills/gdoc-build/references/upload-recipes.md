# Upload Recipes

Copy-paste shell snippets for the upload flow. Tested 2026-05-01 on the builder-toolkit onboarding doc rebuild.

> **On Windows** the snippets below are macOS/Linux-shaped. Translate: `cd ~` →
> `cd $env:USERPROFILE`; `~/foo.docx` → `$env:USERPROFILE\foo.docx`; `tail -10` →
> `Select-Object -Last 10`. Use `$env:VAR`, **not** `%VAR%` — CMD-style `%VAR%` is
> passed through literally by PowerShell, so `gws --upload` gets a path containing
> the text `%USERPROFILE%` and can't find your file. (One exception: after the
> `--%` stop-parsing token in the JSON recipe below, the rule flips — `%VAR%` is
> the only expansion that works there.) The `gws --upload` cwd restriction is the same on
> every platform — build the `.docx` in your home dir and run `gws` from there.
>
> ⚠️ **Don't pipe `gws` straight into `Select-Object`.** PowerShell throws away a
> native command's exit code across a pipe, so the `set -o pipefail` rule below has
> no Windows equivalent — a failed upload (403, bad scope) yields a clean-looking
> pipeline. Assign, check, then trim:
> ```powershell
> # PS 5.1 strips the embedded quotes out of --json '{...}' at the native-command
> # boundary (gws sees {name:...} → `key must be a string at line 1 column 2`),
> # and escaping the quotes alone makes the binder skip quote-wrapping, so the
> # arg splits at the first space in the title (`unexpected argument ... found`).
> # Bypass the binder: escape quotes, park the JSON in an env var, pass it after
> # the stop-parsing token --% (only %VAR% expands there — no $vars or pipes):
> $env:GWS_JSON = (@{ name = 'YOUR DOC TITLE'; mimeType = 'application/vnd.google-apps.document' } | ConvertTo-Json -Compress) -replace '([\\]*)"','$1$1\"'
> $out = gws drive files create --% --json "%GWS_JSON%" --upload your_doc_name.docx --upload-content-type "application/vnd.openxmlformats-officedocument.wordprocessingml.document" --format json
> if ($LASTEXITCODE -ne 0) { throw "gws failed (exit $LASTEXITCODE)" }
> $out | Select-Object -Last 10
> ```

## Upload `.docx` as a new Google Doc

The `.docx` MUST be in `~` (or the cwd you're running `gws` from). `gws` rejects paths outside cwd.

```bash
set -o pipefail
cd ~ && gws drive files create \
  --json '{"name":"YOUR DOC TITLE","mimeType":"application/vnd.google-apps.document"}' \
  --upload your_doc_name.docx \
  --upload-content-type "application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  --format json | tail -10
```

Output looks like:

```json
{
  "id": "1abc...",
  "kind": "drive#file",
  "mimeType": "application/vnd.google-apps.document",
  "name": "YOUR DOC TITLE"
}
```

The file URL is `https://docs.google.com/document/d/<id>/edit`.

## Why `| tail -10`? And why `set -o pipefail` is mandatory with it

`gws` writes a `Using keyring backend: keyring` line to stderr that gets interleaved with stdout. Parsing the full output as JSON fails. `tail -10` skips past the keyring line cleanly. Alternative: `grep -v "keyring backend"`.

**The filter costs you the exit status.** A shell pipeline's exit code is its *last* command's, so `gws … | tail -10` reports `tail`'s status — 0 — even when `gws` failed with a 403 or 404. Without `set -o pipefail` the upload looks like it worked, and a script keyed on `$?` proceeds as if the Doc exists.

`gws` also signals failure a **second** way that no amount of `pipefail` catches: it prints a JSON error body to **stdout**. A bad `fileId` gives exit 1 *and* this on stdout:

```json
{ "error": { "code": 404, "message": "Requested entity was not found.", "reason": "unknown" } }
```

That parses as valid JSON. Any caller that reads stdout without checking the exit code — or that checks the exit code but not for an `error` key — gets the error object handed back as if it were a result.

**So: `set -o pipefail` before every piped `gws` call, check for an `error` key even on exit 0, and for writes verify by re-reading the resource.** Exit codes are weak evidence that a write landed.

## Trash an old draft (when iterating)

```bash
set -o pipefail
gws drive files update \
  --params '{"fileId":"<old_draft_id>"}' \
  --json '{"trashed":true}' 2>&1 | tail -5
```

This moves the file to Drive's trash (recoverable for 30 days). Don't use a hard-delete API call — soft-trash is the safer default.

⚠️ **`2>&1 | tail` is doubly deceptive here.** It merges the error text into the stream *and* hands you `tail`'s exit code, so a failed trash prints something that looks like output and exits 0. You then tell the user you cleaned up drafts that are still sitting in their Drive. With `pipefail` the failure surfaces; either way, confirm with `gws drive files get --params '{"fileId":"<old_draft_id>","fields":"trashed"}'` before claiming the cleanup happened.

## Verify the doc owner / link

```bash
set -o pipefail
gws drive files get \
  --params '{"fileId":"<id>","fields":"id,name,owners,webViewLink"}' \
  --format json 2>&1 | tail -20
```

Confirms the owner is the authed `gws` user (should be your `kprentiss@nsls.org`) and gives the share link.

## When the upload fails

| Error | Fix |
|---|---|
| `--upload '...' resolves to '/private/tmp/...' which is outside the current directory` | `cp /tmp/foo.docx ~/foo.docx && cd ~` and retry |
| `Bad Request` on the create call | Check `--upload-content-type` is exactly `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (not `application/msword` and not `application/docx`) |
| 401 / 403 | `gws` auth lapsed — re-auth via the gws login flow. This is `/gws`'s domain. |
| Doc uploads but tables have no borders | The `.docx` source didn't set `table.style` — fix the python-docx script, re-build, re-upload, trash the broken draft. |

## Don't replace canonical docs programmatically

There's a tempting recipe — use `gws docs documents batchUpdate` to replace an existing canonical doc's body content. **Don't.** The canonical doc's URL is shared broadly; the human controls what lives there. The right pattern:

1. Build the new draft as a separate Google Doc.
2. Give the user the URL.
3. Let them copy section-by-section into the canonical doc.

This preserves the canonical's existing fonts, comments, and revision history.
