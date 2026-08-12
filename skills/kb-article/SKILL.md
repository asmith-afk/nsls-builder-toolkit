---
name: kb-article
description: >-
  Create or update articles in the NSLS internal HubSpot Knowledge Base at
  info.nsls.org/internal by building a HubSpot import CSV from the latest live
  KB export. Use when the user says "create a kb article", "new knowledge base
  article", "draft a kb article", "update a kb article", "add to the internal
  kb", "publish to info.nsls.org", or wants to capture a process / SOP / how-to
  into the internal KB.
---

# KB Article

Create or update articles in the NSLS internal Knowledge Base (HubSpot Service
Hub, public-facing at `https://info.nsls.org/internal`). The registry is a
persistent **master Google Sheet** that holds every internal article in
HubSpot-import-ready form. Every new or edited article is written into that
sheet, so at any point the sheet can be downloaded and re-imported to bring
HubSpot fully in sync. There is no write API, no exporter app, and no
paste-driven tool — publishing is always: update the master sheet, download it,
import it.

The master sheet is the **authoring source of truth**. A HubSpot **export** is
still used to reconcile (confirm what exists, current slugs) but is never the
thing you edit.

## How publishing works (no write API)

HubSpot exposes **no API** for creating, updating, or deleting KB articles
(verified: `cms/v3/knowledge-base/articles` rejects Private App tokens by
design). So do not promise API publish. The two supported paths are the
built-in **CSV importer** (primary) and manual **in-editor paste** (one-offs).

**CSV importer:** In HubSpot go to **Content → Knowledge Base → Current view
dropdown → Import knowledge base**, upload the CSV, and map columns.
- **Create new articles:** leave "Overwrite existing content" unchecked.
- **Update existing articles in place:** check **"Overwrite any existing content
  with imported content"**. Matching is by the **Article URL** column, so the
  URL must exactly equal the live article URL (`https://info.nsls.org/internal/<slug>`).
- Limits: 400 articles per import; the importer **rejects `<table>`**.

## The master Google Sheet (registry)

- **Title:** `NSLS Internal KB — Master (HubSpot Import)`
- **ID:** `1vJ70z_fx_SQWPrJRBUyyptOoowJ1hbpm6iTEFLNEoF8`
- **URL:** https://docs.google.com/spreadsheets/d/1vJ70z_fx_SQWPrJRBUyyptOoowJ1hbpm6iTEFLNEoF8/edit
- **Tabs:**
  - `Articles` (sheetId `1111298109`) — every internal article whose body fits
    Google Sheets' 50,000-char/cell limit. This tab is the published set — it is
    downloaded whole only for a deliberate, reconciled mass sync; routine
    publishes import a changed-row CSV instead.
  - `Oversized (import separately)` (sheetId `977468579`) — articles whose body
    exceeds 50,000 chars. The body cell holds a pointer, not the HTML; the real
    import-ready row lives in a companion CSV in `~/Downloads`
    (`nsls_kb_import_<slug>.csv`). These are imported one file at a time.
- **Columns (both tabs), in HubSpot mapping order:**
  `Article URL, Article title, Category, Subcategory, Keywords, Meta description, Article body, Article subtitle`

**Read/write it with `gws` (Sheets scope is authed via keyring).** Strip the
leading `Using keyring backend` stdout line before parsing JSON. Pass request
bodies via `--json "$(cat file.json)"` (payloads are well under the 1 MB
ARG_MAX). Always write with `valueInputOption: RAW` so HTML bodies are stored
literally, never parsed as formulas.

Adding/updating one article:
1. Read the URL column on **both** tabs — an article lives on exactly one of
   them, and which one is a function of its body size, not its identity:
   ```
   gws sheets +read --spreadsheet <ID> --range "Articles!A:A"
   gws sheets +read --spreadsheet <ID> --range "'Oversized (import separately)'!A:A"
   ```
   Searching only `Articles!A:A` is how you get a duplicate: an existing
   oversized article isn't found, so step 3 appends a second row for a slug that
   already has one, and the next import ships two conflicting versions of it.
2. If the article's **Article URL already exists**, overwrite that row in place
   **on whichever tab holds it** — `values update` at `Articles!A<rownum>` or
   `'Oversized (import separately)'!A<rownum>` — with the 8-column row.
3. If it's **new**, append it: `values append` at `Articles!A1`
   (`{"insertDataOption":"INSERT_ROWS"}`).
4. **Body over 50,000 chars:** the row belongs on the
   `Oversized (import separately)` tab (body cell = a `[Body exceeds ...]`
   pointer), with the full row written to a companion
   `nsls_kb_import_<slug>.csv`.
5. **Crossing the threshold means MOVING the row, not writing a second one.**
   An edit that pushes a body past 50,000 chars — or back under it — changes
   which tab the article belongs on. Write the row to the new tab and
   **delete the row from the old one** (`batchUpdate` →
   `deleteDimension` on that row; clearing the cells leaves a blank row that
   downloads as an empty CSV record). Leaving the stale row behind puts the
   same slug on both tabs, and since both get imported, whichever lands last
   wins — silently, and differently depending on import order. Say out loud
   that you moved it.

## Critical gotchas of the importer

- **Import resets audience access to Public.** There is no audience-access
  column, so it cannot be set or preserved via CSV. After each import, bulk-select
  the affected articles and use **More → Control audience access → Private,
  single sign-on (SSO) required**. Tell the user this every time.
- **Never re-import an export file.** Files named `hubspot-knowledge-base-export-*`
  are the raw pull FROM HubSpot and still contain the original messy markup
  (checkboxes, tables, cruft). Only import files you built, named
  `nsls_kb_import_*`.
- **Category descriptions are not importable.** They live on the category and
  are set manually (Content → Knowledge Base → edit category → Description). The
  Category column only assigns an article to a category.
- **Drafts:** keep drafts in a separate CSV (`nsls_kb_draft_<slug>.csv`) and
  import them with "Import as draft" so an overwrite pass on published articles
  cannot flip a draft live. **This means a draft row never goes on the `Articles`
  tab** — that tab IS the publish set, so a draft parked there ships the next
  time anyone imports, including a colleague syncing something unrelated.

## The workflow

1. **Open the master sheet** (above) — read the `Articles` tab. It is the
   running registry of what exists and every article's real live slug. Ask for a
   fresh HubSpot export only when you need to reconcile the sheet against
   HubSpot-side edits (see the reconcile gotcha).
2. **Gather inputs** (for a new article) or **identify the target** (for an
   edit). For a new article: topic, audience, owning team, category, slug.
3. **Check for duplicates** against the master sheet's Article URL and title
   column before creating.
4. **Draft or edit** the body in the house style (below). Show the user the
   draft (new) or a change summary (edit) before writing anything.
5. **Establish whether this is a draft or a publish — before writing anything.**
   The two take different paths and the choice is not recoverable after an
   import. If the user said "draft", "write it up for review", "not live yet",
   or anything short of publish, it is a draft. Ask if it's genuinely unclear.
   - **Publish** → write the row into the master sheet: overwrite in place if the
     Article URL already exists, append if new, route to the
     `Oversized (import separately)` tab if the body is over 50,000 chars. This
     is the step that keeps the registry complete.
   - **Draft** → **keep the row OFF the `Articles` tab.** Anything on `Articles`
     is published by the normal overwrite import, so a draft parked there goes
     live the next time anyone syncs — including someone else, syncing something
     unrelated. Write the draft to a standalone
     `nsls_kb_draft_<slug>.csv` instead (same 8 columns), and hand it over with
     the draft import instructions below. The registry records it only when it
     publishes.
6. **Deliver the sync instructions** (see "Delivering and publishing"): for a
   publish, the changed-row CSV plus the audience-access reminder; for a draft,
   the draft CSV imported with **Import as draft**. Emit the companion CSV for an
   oversized article.

## House style for article bodies

Allowed HTML only: `h2`, `h3`, `h4`, `p`, `ul`, `ol`, `li`, `strong`, `em`,
`code`, `a`, `pre`. Never `<h1>` (HubSpot reserves it for the title). No
`<table>` (importer rejects it; use lists). No inline `style`/`class`/`div`/
`span`.

Heading hierarchy: `<h2>` top sections, `<h3>` subsections, `<h4>` deepest
detail. Every article should start at `<h2>`. Do not skip levels.

Structure most good NSLS articles share:
1. Why this matters / what this is (one short paragraph).
2. Source-of-truth pointer if there is a canonical doc, dashboard, or Figma.
3. The process / how-to: `<h2>` per major section, `<ol>` for steps, `<ul>` for
   properties or options.
4. What is automatic vs. manual, called out explicitly for any mixed process.
5. Related items / known gotchas at the bottom, brief.

Voice: direct, declarative, operator-readable. The reader is an internal NSLS
team member who needs to do the thing, not a customer. Keep it tight (most
articles are 200-600 words).

## Slugs and cross-links

- The slug is the article URL (`https://info.nsls.org/internal/<slug>`). For an
  **existing** article, use its **real live slug from the export URL column**,
  never a guess, or an overwrite import will not match and you create a duplicate.
- For a **new** article, follow the live **descriptive-slug convention**: spell
  the topic out, do not abbreviate. Examples of the live pattern:
  `associating-contacts-to-companies` (not `associations`), `tickets-overview`
  (not `mex-tickets`), `objects-and-records`, `email-bounce-procedure`,
  `nco-new-joins-process`.
- Cross-reference other articles with their real live slug:
  `<a href="https://info.nsls.org/internal/SLUG">Article Title</a>`. Look the
  slug up in the export by the target's title. Do NOT use the `/article/` or
  doubled `/internal/internal/` path forms.

## Categories (Category column must match one of these strings exactly)

| Category | Icon |
|---|---|
| Getting Started | 🚀 |
| HubSpot Core | ⚙️ |
| Program Development (PD) | 🏫 |
| Chapter Success (CS) | 🤝 |
| SPD & Intern Recruitment | 🎓 |
| Member Experience (MEX) | 💬 |
| Revenue Operations | ⚙️ |
| Marketing | 📣 |

If the topic fits none, ask whether to add a new category or file under the
closest one. A mismatched Category string creates a new (usually unwanted)
category on import.

## Preparing the article row

The row's eight fields, in HubSpot's mapping-screen order (also the master
sheet's column order):

`Article URL, Article title, Category, Subcategory, Keywords, Meta description, Article body, Article subtitle`

Build the row as clean, normalized HTML, then write it into the master sheet
(overwrite-in-place or append). **Every publish also produces a CSV** — the
changed-row `nsls_kb_import_<slug>.csv` the default publish path imports, since
the sheet itself is the registry and not something HubSpot reads. Which file you
emit depends on the case:

| Case | File to emit |
|---|---|
| Publish, any size | `nsls_kb_import_<slug>.csv` — header + the changed row(s) |
| Publish, body >50,000 chars | same filename; it carries the full body the `Oversized (import separately)` tab can't hold |
| Draft | `nsls_kb_draft_<slug>.csv`, and NO sheet row (see workflow step 5) |
| Deliberate mass sync | none — download the whole `Articles` tab, after reconciling |

Every CSV is quoted, UTF-8 with BOM (`utf-8-sig`) so accented characters
survive.

**Normalize every body to the house style** before writing it. Because bodies
are large and often pasted from Google Docs, do this with a script (Python +
BeautifulSoup), not by hand:
- Convert `<table>` to `<ul>` lists (importer rejects tables; house style has none).
- Strip editor cruft: remove `style`/`class`/`id` attributes, unwrap `<div>`
  and `<span>`, replace `&nbsp;` with a space, convert `<br>` runs to paragraph
  breaks (do not just delete them, or lines merge into run-ons), collapse
  whitespace (skip inside `<pre>`).
- Strip leading Markdown task-list checkboxes (`[ ]`, `[x]`) from list items
  only. Keep genuine bracket content such as `[First Name]`, `[DATE]`, or
  `[Custom language]` template placeholders.
- Fix cross-links to `https://info.nsls.org/internal/<real-slug>` (no `/article/`,
  no doubled `/internal/internal/`).
- Normalize headings to h2/h3/h4 (top/sub/detail); no `<h1>`; each article
  starts at `<h2>`.
- Fill the subtitle (a crafted one-sentence summary in the article's voice if
  the export has none). Default Meta description to the subtitle.
- Remove a leading heading that just repeats the article title or an "Owner:"
  line (that belongs to the title/owner fields).

Show the user the draft (for a new article) or a summary of changes (for a bulk
cleanup) before finalizing.

## Delivering and publishing

The article is already in the master sheet. **Default to shipping only the rows
you changed.** An overwrite import matches on Article URL and rewrites the body
of *every* row in the file — so a whole-sheet import to publish one new article
also pushes the sheet's stored body over every other article, reverting anything
edited in HubSpot since the sheet last saw it. That damage is silent, unrelated
to the change being made, and invisible until someone notices their edit is gone.

**Default path — one article (or the few you touched):**

> 1. Build a CSV with the header row plus **only the changed article's row(s)**,
>    named `nsls_kb_import_<slug>.csv`. Same 8 columns in the same order.
> 2. In HubSpot: **Content → Knowledge Base → Current view dropdown → Import
>    knowledge base**, upload that CSV, map the columns.
>    - Check **"Overwrite any existing content with imported content"** — it
>      matches by the Article URL column, so it updates the article if the slug
>      exists and creates it if not. Rows absent from the file are untouched.
> 3. After importing, the articles reset to **Public**. Re-select them and set
>    **Control audience access → Private, SSO required**.

**Whole-sheet path — only after reconciling.** A full `Articles`-tab import is
the right tool for a deliberate mass sync, and it is the ONLY way to guarantee
HubSpot matches the registry. It is not a routine publish step. Before running
it, do the reconcile pass (see the reconcile gotcha): pull a fresh
`hubspot-knowledge-base-export-*`, diff it against the sheet, and fold any
HubSpot-side edits into the sheet first. Then download the `Articles` tab as CSV
and import it with overwrite, plus each `Oversized (import separately)` article's
companion CSV separately.

If the user asks for "the usual import" and hasn't reconciled, say what a
whole-sheet overwrite would do and offer the single-row path instead. Don't
present the two as equivalent.

**Draft path — never touches `Articles`:**

> 1. Take the `nsls_kb_draft_<slug>.csv` produced for this draft (it is not on
>    the master sheet — that's deliberate).
> 2. In HubSpot: **Content → Knowledge Base → Current view dropdown → Import
>    knowledge base**, upload it, map the columns, and choose
>    **Import as draft**.
>    - Leave **"Overwrite any existing content"** UNCHECKED. Overwrite plus a
>      slug that already exists live would replace the live article with the
>      draft body.
> 3. Review in HubSpot and publish there when it's ready.

Once a draft is published, write its row into the master sheet (the publish path
above) so the registry stops being incomplete — an article live in HubSpot with
no sheet row is invisible to every future reconcile.

If the article was drafted from a project doc in the Obsidian vault, offer to
add a stub link from that doc to `https://info.nsls.org/internal/<slug>`.

## Gotchas recap

- The master Google Sheet is the registry and authoring source of truth; every
  **published** new/edited article must be written into it, or it drifts out of
  sync. Drafts are the one exception and stay off the `Articles` tab until they
  publish — that tab is the publish set, not a workspace.
- **Reconcile before a full re-import.** The sheet holds the body as *we* last
  authored it. If someone edits an article directly in HubSpot, a wholesale
  re-import will overwrite (clobber) their change with the sheet's older body.
  Before a big sync, pull a fresh export and update any rows edited in HubSpot,
  or import only the changed rows.
- Google Sheets caps a cell at 50,000 chars; bodies over that go on the
  `Oversized` tab + a companion CSV, never inline.
- No KB write API; publish is CSV import (download the sheet) or in-editor paste.
- Import always resets audience access to Public; fix with Control audience
  access after every import.
- Importer rejects `<table>`; 400 articles per import (the registry is ~50, so
  headroom is fine).
- Never import a raw `hubspot-knowledge-base-export-*` file; import the sheet
  download or a `nsls_kb_import_*` companion.
- Overwrite matches by Article URL, so slugs must equal the live slugs.
- Keep `[Placeholder]` tokens; only strip empty `[ ]`/`[x]` checkboxes.
- Category strings and category descriptions: match live strings exactly;
  descriptions are set manually on the category, not via CSV.
