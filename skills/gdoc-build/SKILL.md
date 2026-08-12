---
name: gdoc-build
description: >-
  Use when the user asks to "make a Google Doc", "build a doc", "draft an
  onboarding doc", "create a builder guide", "generate a report", "write a
  brief in Google Docs", or "update the canonical [doc]" — anytime the
  output is a polished Google Doc with real tables, headings, and NSLS
  branding (not slides, not markdown, not PowerPoint). Also use when
  iterating on an existing canonical doc by producing a draft for the
  user to copy-paste from. NSLS or Society branded.
---

# /gdoc-build

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — read existing Google Docs, list drives, inspect prior `.docx` artifacts. Free to do.
2. **Configuration / new-content writes** — build `.docx` locally, upload as a **new** Google Doc draft, trash drafts the skill itself created earlier in this session. OK by default; explain what's being created and where.
3. **Write to canonical / shared docs** — **never overwrite an existing canonical doc directly.** Always produce a separate draft and let the user copy-paste into the canonical doc themselves. The canonical URL stays stable; the human controls the merge. If the user explicitly asks "replace the content of doc X with this," confirm twice and document the rollback path before proceeding.

## Purpose

NSLS builders keep needing nicely-formatted Google Docs — onboarding guides, builder docs, board narratives, strategy briefs, reports. Markdown looks fine in a terminal but renders poorly in Google Docs. Pandoc-from-markdown produces tables that look correct as raw markdown but render without proper styling once converted. This skill codifies the only path that consistently works: build the document with `python-docx` using real Word table elements, heading styles, and NSLS brand colors, then upload through `gws drive` with conversion to a native Google Doc. Tables come through with cell borders, header rows stay styled, and the result survives copy-paste into a canonical doc.

This skill exists because we keep redoing docs we got wrong with pandoc. Codifying the pattern stops the loop.

## Quick Start

The fastest path for a builder asking for a Google Doc:

0. **Ensure the gws profile is healthy** (once per machine; ~1s when already set up):
   `python3 <plugin>/skills/gws/scripts/gws_doctor.py` — provisions the toolkit's own gws
   profile, validates the client, and runs the one-time consent if needed. A 403 naming a
   project other than `nsls-gdocs-skill`, or a gws exit 2, means run it (again).
1. **Confirm branding.** "NSLS or Society?" Default NSLS unless the doc is for `thesociety.org` audiences.
2. **Confirm install pattern.** `[ -d /tmp/pptx_deps/docx ]` — if missing, run `python3.12 -m pip install python-docx --target /tmp/pptx_deps -q`.
3. **Copy the template.** `cp templates/build_doc.py ~/build_<short-name>.py` (must be in `~`, not `/tmp` — see gws cwd gotcha below). Customize content sections.
4. **Build the docx.** `PYTHONPATH=/tmp/pptx_deps python3.12 ~/build_<short-name>.py` → produces `~/<short-name>.docx`.
5. **Upload as Google Doc.** `export GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$HOME/.config/gws-profiles/nsls-gdocs-skill"; set -o pipefail; cd ~ && gws drive files create --json '{"name":"<doc title>","mimeType":"application/vnd.google-apps.document"}' --upload <short-name>.docx --upload-content-type "application/vnd.openxmlformats-officedocument.wordprocessingml.document" --format json | tail -10` — the `pipefail` is load-bearing: without it `tail` swallows a failed upload and the command still exits 0.
6. **Return the URL.** `https://docs.google.com/document/d/<id>/edit` — give the user that link.
7. **Clean up local artifacts.** `rm ~/build_<short-name>.py ~/<short-name>.docx`

> **On Windows** — the Quick Start commands above are macOS/Linux-shaped. Translations:
> - **Write env vars as `$env:VAR`, never `%VAR%`.** PowerShell passes CMD-style
>   `%VAR%` through literally, so a path built that way arrives at `gws`/`Copy-Item`
>   containing the text `%USERPROFILE%` and resolves to nothing. `%VAR%` appears below
>   only when naming a location in prose; every command uses `$env:VAR`.
> - **Python:** use the full path `$env:LOCALAPPDATA\Programs\Python\Python312\python.exe`,
>   never `python`/`python3.12`. Stock Win11 `python`/`python3` are Microsoft Store stubs
>   that print "Python was not found" and **exit 0** — a naive check passes while nothing
>   runs. `install.ps1` installs Python 3.12 to that path *and* `python-docx` into it, so
>   on a toolkit machine you usually don't need the `--target /tmp/pptx_deps` install at all.
> - **Temp deps dir:** if you do need a target install, replace `/tmp/pptx_deps` with a
>   writable dir such as `%TEMP%\pptx_deps` (`$env:TEMP\pptx_deps`), and set `PYTHONPATH`
>   to it.
> - **`gws --upload` cwd restriction still applies:** build the `.docx` in your home dir
>   (`%USERPROFILE%`) and run `gws` from there — `--upload` rejects paths outside the cwd.
> - Home paths: `~/build_<name>.py` → `$env:USERPROFILE\build_<name>.py`.
>
> On a toolkit Windows machine the whole flow is:
> ```powershell
> $env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR = "$env:USERPROFILE\.config\gws-profiles\nsls-gdocs-skill"
> $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
> Copy-Item templates\build_doc.py "$env:USERPROFILE\build_mydoc.py"
> cd $env:USERPROFILE
> # EDIT build_mydoc.py FIRST: the template ships output_path = '/Users/k/your_doc_name.docx'
> # (a macOS path). Set it to "$env:USERPROFILE\mydoc.docx" and customize the content
> # sections. Run it unedited and it dies with FileNotFoundError on the missing /Users/k.
> & $py build_mydoc.py           # produces mydoc.docx in the home dir
> $gwsOut = gws drive files create --json '{"name":"My Doc","mimeType":"application/vnd.google-apps.document"}' --upload mydoc.docx --upload-content-type "application/vnd.openxmlformats-officedocument.wordprocessingml.document" --format json
> if ($LASTEXITCODE -ne 0) { throw "gws upload failed (exit $LASTEXITCODE)" }
> $gwsOut | Select-Object -Last 10
> ```
>
> The `$LASTEXITCODE` check is the PowerShell equivalent of the `set -o pipefail` rule
> above: piping `gws` straight into `Select-Object` swallows the exit code, so a 403 on
> upload produces a clean-looking pipeline and you proceed as if the doc exists.

## NSLS Brand Constants

Don't invent colors. Use these.

| Element | NSLS | Society |
|---|---|---|
| Table header background | `#1A2B4A` (navy) | `#3D2F1F` (deep brown) |
| Table header text | `#FFFFFF` | `#F5E6CB` (cream) |
| Alternating row band | `#F5F7FA` (light grey) / `#FFFFFF` | `#FAF4E8` / `#FFFFFF` |
| Heading 1 color | `#1A2B4A` | `#3D2F1F` |
| Heading 2 color | `#2B4A7A` | `#6B4F2F` |
| Code-block background | `#F5F7FA` | `#FAF4E8` |
| Body font | Calibri 11pt | Calibri 11pt |
| Code font | Consolas 9.5pt | Consolas 9.5pt |

**Why Calibri for body?** Custom brand fonts (Lexend Deca, HW Cigars) don't survive `.docx` → Google Doc conversion — they fall back to defaults silently. Calibri renders consistently. Brand colors carry through perfectly. For slides, the font story is different — see `/nsls-slides`.

## The Macro: How the pipeline works

```
content (in your script)
  ↓ python-docx (Document + add_heading + add_table + add_paragraph)
  ↓ doc.save("~/name.docx")
  ↓ gws drive files create with mimeType=application/vnd.google-apps.document
  ↓ Drive imports the .docx, converting to native Google Docs format
  ↓ tables become Google Docs tables with borders + styling preserved
  ↓ headings inherit Google Docs heading styles (TOC + outline work)
  ↓ user gets a URL to share or copy from
```

Three things make or break this pipeline:

1. **Real Word tables**, not text approximations. Use `doc.add_table()` with explicit cell shading via `OxmlElement`. Markdown pipe-tables converted by pandoc lose styling on import.
2. **Built-in style names**, not custom styles. `doc.add_heading(text, level=1)` produces Heading 1, which Google Docs maps cleanly. Made-up styles get flattened.
3. **`gws` cwd restriction.** `--upload` rejects paths outside the current working directory. Build the `.docx` in `~` and run `gws` from `~`, not `/tmp`.

## The Micro: Domain-specific gotchas

These are the wounds. Codified so we don't relive them.

| Gotcha | Symptom | Fix |
|---|---|---|
| `gws --upload` rejects `/tmp/foo.docx` | Error: `resolves to '/private/tmp/foo.docx' which is outside the current directory` | `cp /tmp/foo.docx ~/foo.docx && cd ~ && gws ...` |
| `gws` mixes stderr into stdout | JSON parse fails on `Using keyring backend: keyring` line | Pipe through `tail -10` or `grep -v "keyring"` before parsing — **but put `set -o pipefail` first**, or the pipe hides gws failures (next row) |
| A `gws` write "succeeds" but nothing changed | `\| tail`/`\| grep` makes the pipeline's exit status the *filter's* (always 0), so a 403/404 reads as success | `set -o pipefail` before any piped `gws` call, then verify by re-reading the resource. gws also returns a JSON `{"error":{...}}` body on **stdout** — check for an `error` key even on exit 0 |
| `python3.14` venv broken on this machine | `pip install` succeeds but `import` fails | Use `python3.12 -m pip install --target /tmp/pptx_deps`; run with `PYTHONPATH=/tmp/pptx_deps python3.12 ...` (see MEMORY.md "Python / PPTX / DOCX Environment") |
| Custom brand fonts disappear after upload | Lexend / HW Cigars fall back to system default in Google Docs | Use Calibri for body. Brand expression comes from colors, not fonts. |
| Table renders without borders in Google Docs | `table.style` not set | `table.style = 'Light Grid Accent 1'` (built-in name, gives borders) |
| Header row text invisible | Black text on dark navy fill | Set `run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)` after adding text |
| Cell text appears twice | Forgot to clear default cell content before adding run | Always `cell.text = ''` before `cell.paragraphs[0].add_run(...)` |
| Bullet list renders as plain paragraphs | Wrong style name | Use exact built-ins: `'List Bullet'` and `'List Number'` (case-sensitive, space included) |
| Pandoc-from-markdown was used | Tables look fine raw, render without borders / banding once in Google Docs | Don't. Build with python-docx. See `feedback_docx_pipeline` memory. |
| Old draft URL piles up after iterations | Drive fills with `DRAFT v1`, `DRAFT v2`, etc. | Trash old drafts: `gws drive files update --params '{"fileId":"<old_id>"}' --json '{"trashed":true}'` |
| Replacing canonical doc directly breaks shared link history | Shared URL changes if you delete + recreate | NEVER replace canonical content automatically. Always create a new draft, give the user the URL, let them copy-paste into the existing canonical doc. |

## Diagnostic Loop

When the upload doesn't produce what you expected:

**TRY:** Build → upload → open the resulting Google Doc.
**OBSERVE:** Tables borderless? Headings flat? Cell shading missing? Bullets plain? Some content missing entirely?
**DIAGNOSE:**
- Borderless tables → `table.style` not set, OR table.style was set to a name that doesn't exist (typo). Stick to `'Light Grid Accent 1'` until you have reason to change.
- Flat headings → using `doc.add_paragraph(text, style='Heading 1')` instead of `doc.add_heading(text, level=1)`. The latter is more reliable.
- Missing cell shading → forgot the `OxmlElement('w:shd')` block, or applied it before `cell.text = ''`. Order matters.
- Plain bullets → wrong style string. Must be exactly `'List Bullet'`.
- Content missing → check the script ran without error (`echo $?`) and the `.docx` file size is reasonable (>10KB for any real doc).
**ADAPT:** Fix the one thing. Re-run script. Trash the old draft. Re-upload.
**TRY AGAIN.** Iterate fast — each cycle is ~5 seconds locally and the upload takes another ~3.

For runtime errors:

| Error | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'docx'` | `PYTHONPATH` not set or pkg not installed | `python3.12 -m pip install python-docx --target /tmp/pptx_deps && PYTHONPATH=/tmp/pptx_deps python3.12 build.py` |
| `python3.12: command not found` | Older system Python | Check `ls /usr/local/bin/python3.1*`; install via `brew install python@3.12` if missing |
| gws CLI returns 401/403 | Auth expired | Re-auth via the gws login flow (this is `/gws`'s problem, not this skill's) |
| gws upload "Bad Request" | Wrong `--upload-content-type` | For `.docx`, use exactly `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |

## Output guidelines

What to return to the user when the doc is built:

- **Doc URL** — `https://docs.google.com/document/d/<file_id>/edit` is the canonical form.
- **What's in it** — one-line summary of sections so the user knows what to expect before opening.
- **Suggested merge path** — if it's a draft for an existing canonical doc, remind the user to **copy section-by-section** rather than full-doc-replace, so the canonical's existing fonts/spacing stay intact.
- **Cleanup hint** — local `.docx` and `.py` files should be deleted after the user confirms the doc looks right. Skill cleans up by default unless asked otherwise.
- **Don't dump the whole content** back into chat — the URL is the deliverable.

## Service Awareness

Where this skill sits:

- **Sibling skills:** `/nsls-slides` (PowerPoint → Google Slides, different format), `/board-deck` (Kevin's board-update slide pattern), `/frontend-slides` (HTML decks).
- **Adjacent (lower-level):** `/gws` is the underlying CLI; this skill is the high-level "make me a doc" wrapper. `/google-drive` handles general file ops. `/google-slides-api` handles existing Slides edits.
- **Different output, don't confuse:** `/pydoc-pipeline` produces markdown documentation FROM Python source code. `/gdoc-build` produces Google Docs FROM your content. Opposite directions.

If the user wants slides, route to `/nsls-slides`. If the user wants markdown for a repo, route to `/pydoc-pipeline`. If the user wants a Google Doc, this is the skill.

## Templates and References

- `templates/build_doc.py` — starter script with the helper functions (`add_heading`, `add_table`, `add_para`, `add_bullet`, `add_code`, `set_cell_bg`, `set_cell_borders`). Copy, customize the body section, run.
- `references/brand-styles.md` — full color and style reference, including Society variant and the canonical NSLS palette.
- `references/upload-recipes.md` — copy-paste shell snippets for the upload + trash-old-draft flow, including the keyring-stderr workaround.

## Worked Example

The "Becoming a Builder at NSLS" onboarding doc draft v2, 2026-05-01. The first attempt used pandoc-from-markdown — Kevin rejected it ("all wrong, real tables please"). The second attempt used python-docx with the patterns codified here. File ID `1TG670nsMpW3fKTUwNIs4sb2itApb5vLdn0jvaDP_a9g`. That build script is the seed for `templates/build_doc.py`.

## Common Mistakes

1. Reaching for pandoc because "I have markdown content already." Don't. The markdown→docx step strips the styling we need.
2. Building the `.docx` in `/tmp` and trying to upload from there. `gws --upload` rejects paths outside cwd.
3. Letting old drafts pile up in Drive. Trash them in the same session you create the new one.
4. Overwriting a canonical doc's content programmatically. Always create a new draft. The human owns the merge.
5. Trying to use brand fonts that aren't installed in Google Docs. Calibri for body, brand colors for everything else.
6. Forgetting `cell.text = ''` before adding a run — content duplicates.
7. Parsing `gws` output as JSON without filtering the keyring stderr line.
8. Putting all the content directly in SKILL.md instead of the template — keep SKILL.md as the rubric, put the code in `templates/`.

## Red Flags — STOP

- About to run pandoc to convert markdown to docx → STOP. Use python-docx.
- About to build the .docx in `/tmp` and upload → STOP. Move to `~` first.
- About to overwrite an existing canonical Google Doc by replacing its body content → STOP. Create a draft instead.
- About to leave four versions of the same draft in Drive → STOP. Trash old drafts.
- About to dump the full doc content as chat output along with the URL → STOP. URL is the deliverable.
- About to invent a new color or font → STOP. Use the brand constants.

## Rationalizations You Will Have

| Excuse | Reality |
|---|---|
| "I already have the content as markdown — pandoc is faster." | Pandoc tables render without borders in Google Docs. The fast path is the slow path here. Build with python-docx. |
| "I'll skip Calibri and use Lexend Deca for the body, it's our brand font." | Google Docs strips it on import. Calibri renders, brand colors do the brand work. |
| "It's just a draft, I won't bother trashing the old one." | Drive fills up; the user can't tell the latest. Trash old drafts in the same turn you create new ones. |
| "I'll just edit the canonical doc directly via the API to save the user a copy-paste." | The canonical doc has formatting the human controls. Replacing programmatically nukes that. Always create a draft. |
| "The cell text is showing twice but it'll probably be fine." | It won't. `cell.text = ''` before adding the run. |
| "I'll set the table style later, the table itself works." | Without `table.style`, the table renders without borders in Google Docs. Set it when you create the table. |
| "I don't need to test the upload — the .docx looks fine in Word." | Word and Google Docs handle some elements differently. Verify by opening the actual Google Doc. |
