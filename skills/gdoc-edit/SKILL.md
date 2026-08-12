---
name: gdoc-edit
description: >-
  Use when the user wants to change an EXISTING Google Doc in place rather than
  create a new one: "update the doc", "edit my Google Doc", "add a changelog to
  the top", "change X to Y in the doc", "insert a section after …", "remove the
  stale section", "append this to the doc", "what are the comments on this doc",
  "don't make a new version — edit this one". The complement to gdoc-build (which
  creates new branded docs). NSLS or Society.
---

# gdoc-edit

Edit an existing Google Doc in place — replace text, insert a section, drop a changelog
at the top, delete a stale section, read reviewer comments — as **you**, with **your** doc
permissions, and Google Docs **Version history** as the audit trail. Also creates simple
net-new docs; for polished tables/branding use `/gdoc-build`.

## RULE 0 — use the helper. Don't hand-roll `gws` batchUpdate JSON.

Every edit goes through `scripts/gdoc.py`. It reads the doc's structure, resolves anchors to
real character indices, orders deletes so indices don't shift, and re-reads to **verify**
edits landed. Hand-building a `gws docs documents batchUpdate` request means doing that index
math yourself — the #1 way to silently mangle a doc.

```bash
S=~/.claude/local-plugins/nsls-builder-toolkit/skills/gdoc-edit/scripts/gdoc.py
python3 $S read --doc <DOC_ID>        # <- shape of EVERY call: python3 $S <action> --doc ID
```

Dropping to raw `gws` is fine only for a plain read or a single literal `replaceAllText`.

## Prerequisite: `gws` authenticated **in the toolkit profile** (one-time)

This skill runs on `gws` (the Google Workspace CLI) **from the toolkit's own gws profile**,
so it can never collide with other Google tools' client files on the same machine
(`gdoc.py` selects the profile automatically; for raw `gws` calls set it yourself):

```bash
export GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$HOME/.config/gws-profiles/nsls-gdocs-skill"
```

**One-command setup/repair:** `python3 <plugin>/skills/gws/scripts/gws_doctor.py` —
provisions the profile, validates the client file, and runs the one-time consent with the
right scopes (details + manual fallback: [`references/setup.md`](references/setup.md)).
Errors decode as:
- **exit 2 / auth error** → no credentials in the profile → re-run
  `python3 <plugin>/skills/gws/scripts/gws_doctor.py`. Use the doctor, **not** a raw
  `gws auth login --services docs,drive`: the profile is shared with other toolkit skills,
  and a narrow login overwrites its stored scopes with only `docs,drive` — silently
  breaking `squad-dashboard` (sheets) or `receipts` (gmail) on that machine. The doctor
  logs in with `granted ∪ requested`.
- **403 naming `nsls-gdocs-skill`** → you're not covered by the project's quota grant —
  staff are covered via `allstaff@nsls.org`; **contractors ask to be added to
  `gcp-builders@nsls.org`**.
- **403 naming ANY OTHER project** → gws is using a foreign client (profile not active or
  never provisioned) → run the repair block in
  [`../gws/references/multi-secret-profiles.md`](../gws/references/multi-secret-profiles.md).
  **Never edit or delete the foreign client file — it belongs to another tool.**

No per-person webhook, no shared secret — every call is your own identity.

## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — `read` the doc text, `comments` to list reviewer comments. Free.
2. **In-place edits** — `replace`, `insert-top`, `insert-after`, `append`, `remove`, `create`.
   Allowed by default, but: (a) **read before you write**, (b) **preserve comment anchors** — a
   comment is attached to a substring; if you delete/alter that exact text the comment orphans,
   so keep the anchored phrase verbatim, (c) the rollback path is the Doc's **File → Version
   history** (every API edit is a timestamped revision). On a shared/canonical doc, state the
   scope of edits before applying.
3. **Bulk / risky rewrites** — a broad regex `replace` or a loose `remove` anchor can mangle a
   doc silently (`replaceAllText` reports success even when it matched nothing; `remove` deletes
   EVERY paragraph containing the anchor). Mitigate with anchored, verified edits (see Batch) and
   a read-back check. Never run an unanchored regex replace, or a `remove` with a short/common
   anchor, on a doc you haven't read.

Every edit runs as **your** Google identity and can touch **any** doc you can already access —
no more, no less. That is the security model: your permissions, your audit trail.

## When to use this vs gdoc-build

- **New doc, polished tables/branding** → `/gdoc-build` (python-docx → `gws drive` upload +
  convert; real tables, brand colors).
- **Change a doc that already exists** (URL must stay stable, comments must survive, iterating
  in place) → **this skill**.
- **New but simple** (a quick doc from text, no tables) → this skill's `create` is fine.

## Quick Start

```bash
S=~/.claude/local-plugins/nsls-builder-toolkit/skills/gdoc-edit/scripts/gdoc.py
DOC=<google-doc-id>                       # the part of the URL after /document/d/

python3 $S read   --doc $DOC              # full text (use to plan exact edits)
python3 $S comments --doc $DOC            # reviewer comments (address them; don't orphan)
python3 $S replace --doc $DOC --find "old text" --replace "new text"   # literal by default
python3 $S insert-top --doc $DOC --title "Changelog — v2.3" --text-file /tmp/changelog.txt
python3 $S insert-after --doc $DOC --anchor "Top questions for Kevin" --text "• New bullet"
python3 $S append --doc $DOC --text "One appended paragraph."
python3 $S remove --doc $DOC --anchor "What changed (v1.0"   # delete whole paragraphs w/ anchor
python3 $S create --title "Scratch notes" --text "First line."   # net-new simple doc → prints URL
```

`--find` is a **literal** by default; pass `--regex` to treat it as a pattern (resolved
client-side, since the Docs API has no regex replace). `insert-after`/`remove` target
**top-level paragraphs** — text inside tables isn't matched by anchors (build tables with
`/gdoc-build`).

## The reliable pattern: read → batch → verify

For anything beyond a single swap, drive it from a JSON edit file and let the helper apply
**and verify** in one pass. This is what survives smart-quote drift and silent no-ops.

```bash
python3 $S batch --doc $DOC --file /tmp/edits.json
```

`/tmp/edits.json`:

```json
{
  "edits": [
    {"label":"version", "anchor":"Version: 2.2", "replace":"Version: 2.3 · …", "marker":"Version: 2.3"},
    {"label":"liability", "anchor":"Improper re-disclosure", "replace":"… full new paragraph …", "marker":"uncapped bucket"}
  ],
  "remove": ["What changed (v1.0", "De-id is the interim path"],
  "changelog": {"title":"Changelog — v2.3 (changes since v2.2)", "lines":["• …","• …"]}
}
```

- **Prefer `anchor` over `find`.** The helper reads the doc, locates the UNIQUE line containing
  the anchor substring, and replaces that whole line — so you don't have to reproduce smart
  quotes, em dashes, or `§` exactly. If an anchor matches 0 or >1 lines it is skipped and reported.
- **`marker`** is a phrase from the replacement; after applying, the helper re-reads and reports
  any markers missing → that edit didn't land. `remove` items are checked too.

## The Micro: domain gotchas (the wounds)

| Gotcha | Symptom | Fix |
|---|---|---|
| **Hand-rolled `batchUpdate` JSON** | wrong indices → text inserted mid-word, wrong paragraph deleted | Use `python3 $S <action>`; it resolves indices from live structure and verifies. |
| Smart-quote / punctuation drift | a `find` silently matches nothing; `replace` returns ok anyway | Use `anchor` (line-from-the-doc) + `marker` verification, not hand-typed full sentences. |
| `replaceAllText` returns ok on **0 matches** | "ok" but nothing changed | Always read-back / use `batch` markers; an empty match is not an error to the API. |
| Regex expectation | `--find` didn't behave like a pattern | `replace` is **literal** by default; pass `--regex` (resolved client-side). |
| `replace` can't make paragraphs | `\n` in a literal `replace` won't create a new paragraph/bullet | New sections/bullets → `insert-top` or `insert-after`, not `replace`. |
| `replace` with '' leaves blank paragraphs | stale section "deleted" but gaps remain | Use `remove` (deletes whole paragraphs), not an empty `replace`. |
| Comment orphaned after an edit | reviewer's comment detaches | Keep the anchored substring verbatim; check `comments` first, and re-read after. |
| Anchor inside a table | `insert-after`/`remove` can't find it | Anchors match top-level paragraphs only. Edit table content via `/gdoc-build` or by index. |
| **exit 2 / auth error** | any action fails immediately | No credentials in the toolkit profile → run `python3 <plugin>/skills/gws/scripts/gws_doctor.py`. Not a raw `gws auth login --services docs,drive` — that overwrites the shared profile's scopes and breaks other skills using it. |
| **403 naming `nsls-gdocs-skill`** | every call 403s, auth looks fine | Caller not covered by the quota grant — contractors ask to join `gcp-builders@nsls.org` (staff are covered via allstaff). |
| **403 naming any OTHER project** | every call 403s with a foreign project name | gws is on a foreign client — profile not active/provisioned → repair block in `../gws/references/multi-secret-profiles.md`. Don't touch the foreign file. |

## Diagnostic Loop

**TRY → OBSERVE → DIAGNOSE → ADAPT → TRY AGAIN**

- **exit 2 / "auth error"** → no credentials in the toolkit profile → `python3 <plugin>/skills/gws/scripts/gws_doctor.py` (it sets the profile itself and preserves already-granted scopes; a raw narrow login would drop them).
- **403 naming `nsls-gdocs-skill`** → quota grant doesn't cover the caller → `gcp-builders@nsls.org` membership (contractors).
- **403 naming another project** → foreign client in use → profile repair (multi-secret-profiles.md); never modify the other tool's file.
- **edit ok but marker MISSING** → the `find`/`anchor` didn't match live text → re-`read`, copy
  the real line, switch to `anchor`, retry.
- **anchor matched x2** → not unique → lengthen it.
- **"ok" but nothing changed** → `replaceAllText` matched nothing → switch to `anchor` + `marker`.

There is always a path: read the doc, anchor on real text, verify by marker.

## Output Guidelines

- Return the **doc URL** + **"review via File → Version history"** (the diff + rollback).
- Summarize *what changed* (one line per edit); don't dump the whole doc back into chat.
- Note any comments you addressed or deliberately preserved.
- PII: the doc may contain regulated data — don't echo its contents into chat unnecessarily,
  and never put real student/member data in a test doc.

## Service Awareness

- **Engine:** `/gws` (the Google Workspace CLI). This skill is a thin, safe wrapper over
  `gws docs documents` (read/batchUpdate/create) + `gws drive comments`. Auth is `gws`'s,
  stored **per config dir**: this skill always authenticates in the toolkit profile (see
  Prerequisite), independent of the default dir other tools may use.
- **Sibling:** `/gdoc-build` — creates new branded docs (python-docx → upload). Net-new with
  tables → that; in-place edits → this. Deliberate complements. Both now run on `gws` auth.
- **Lower-level:** `/google-drive` (file ops).
- **Legacy:** the old personal Apps Script webhook is retired; kept at
  `references/legacy/gas-doc-webhook.gs` for history only.

## Red Flags — STOP

- About to hand-roll a `gws batchUpdate` request with your own indices → STOP; use the helper.
- About to run an unanchored regex `replace`, or a `remove` with a short/common anchor, on a doc
  you haven't `read` → STOP.
- About to delete/alter text that a comment is anchored to → STOP; preserve the phrase.
- About to build a brand-new doc to "edit" an existing one → STOP; that's the old copy-paste trap
  this skill exists to kill. Edit in place.
- About to put real student/member PII in a test doc → STOP; use dummy data.

## Rationalizations You Will Have

| Excuse | Reality |
|---|---|
| "I'll just hand-type the full sentence as `find`." | Smart quotes / em dashes won't match; `replace` returns ok and nothing changes. Use `anchor` + `marker`. |
| "I'll empty the stale section with `replace … ''`." | That leaves blank paragraphs. Use `remove` to delete the whole paragraphs. |
| "I'll make a fresh draft, it's easier than editing." | That orphans comments and breaks the shared URL — the exact pain this skill removes. Edit in place. |
| "It returned ok, so it worked." | `replaceAllText` returns ok on zero matches. Verify by marker / read-back, every time. |
| "I'll build the batchUpdate JSON myself, I know the indices." | Indices shift as you edit; a wrong index corrupts the doc silently. The helper resolves + verifies them. |
| "The comment text is still in the doc, so the comment is fine." | The comment object can detach even when the words remain. Preserve the exact anchored run; re-check `comments`. |
| "`remove` with anchor 'the' will be fine." | It deletes EVERY paragraph containing it. Anchors must be distinctive. |

## References

- [`references/setup.md`](references/setup.md) — `gws auth` setup (builder + one-time admin).
- [`scripts/gdoc.py`](scripts/gdoc.py) — the helper CLI (read/comments/create/replace/insert-top/insert-after/append/remove/batch).
- [`references/works-for-everyone-spec.md`](references/works-for-everyone-spec.md) — superseded design history (why gws, not a service).
- [`references/legacy/gas-doc-webhook.gs`](references/legacy/gas-doc-webhook.gs) — retired Apps Script webhook.
