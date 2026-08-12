---
name: academic-outcomes
description: >-
  Use when you need a formal, college- or accreditor-facing summary of what a
  Society (ignite-next) track teaches — measurable competencies and the evidence
  each learner produces, in an academic format a university recognizes. Produced
  in the design phase so every prototype carries one alongside its brief, and
  bundleable into one package across tracks to share with a partner or
  accreditation body. Partner-neutral; a partner crosswalk is a separate skill.
  Triggers: "academic outcomes", "learner outcomes", "competencies and
  evidence", "outcomes summary", "accreditation summary", "share outcomes with a
  college", "bundle outcomes", "what does this track teach, formally".
---

# academic-outcomes

> **If `gws` fails (403 naming a project other than `nsls-gdocs-skill`, or exit 2):**
> run the doctor — it provisions/repairs the toolkit's own gws profile without touching
> any other tool's files, and computes the right scope union automatically:
> `python3 <plugin>/skills/gws/scripts/gws_doctor.py --services docs,drive`
> (Windows: use the real Python at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.)
> **The doctor heals its own profile, not your default gws setup** — so after
> `DOCTOR: HEALTHY`, run this skill's `gws` commands against that profile, chained in
> the SAME shell command (each agent Bash call is a fresh shell):
> `export GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws-profiles/nsls-gdocs-skill; gws …`
> (Windows: `$env:GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$env:USERPROFILE\.config\gws-profiles\nsls-gdocs-skill"; gws …`)
> Details: `../gws/references/multi-secret-profiles.md`.


## SAFETY: THREE-TIER PERMISSION MODEL

1. **Read-only** — reading a track's brief, its `track.json`, existing outcomes
   JSON, and this skill's references. Free.
2. **Configuration / new-content** — building the `.docx` locally and uploading a
   **new** Google Doc draft via `gdoc-build`. OK by default; say what's created.
3. **Write to shared systems** — writing `academic_outcomes_json` +
   `outcomes_doc_url` to the `Tracks` record (base `appzDWu6GowvnACtv`), and
   sharing/bundling for a partner. Confirm before writing; **never auto-send a
   package to a partner** — a human decides what to share.

## Purpose

Colleges and accreditation bodies speak one language fluently: **measurable
competency → the evidence that proves it.** This skill states, in exactly that
language, what a Society track teaches and the artifact each learner walks away
having produced — a document a university reads as authoritative because it is
*true and checkable*, not because it is dressed up. It's the formal, external
face of a track: produced in the design phase so every prototype has one, and
bundled across tracks into a single package NSLS can hand a partner. Its whole
value rests on one discipline: **every claim is grounded in what the track
actually does.** One inflated row and the document loses the standing it exists
to create.

## When to use

- In the **design phase**, when a track moves from idea to a worked-on prototype
  (called by `track-design`) — every prototype gets an academic-outcomes summary.
- **Standalone**, to produce or refresh the summary for any existing/live track.
- To **bundle** several tracks' summaries into one college/accreditor package.
- NOT for mapping to a specific partner's curriculum — that's the separate
  `partner-crosswalk` skill (this doc is partner-neutral).
- NOT for the design brief (that's `track-brief`) — this is the formal outcomes,
  a distinct, more rigorous artifact.

## Quick Start

A track → an academic-outcomes summary through these phases, in order:

**0 Frame** → **1 Read the track** (brief + `track.json`) → **2 Draft
competencies** (measurable, evidence-gated) → **3 Write the sections** → **4 Emit
the JSON** → **5 Render the doc** → **6 Store + report**. Bundle = repeat 1–4 per
track, then render them together.

## Operating rules

- **Never work from memory — read the track.** Open the brief and `track.json`
  and inventory the real `collect`/`generate` substeps before writing a single
  competency. Every evidence claim maps to a real step.
- **Accuracy over impressiveness.** If a summary feels thin, the fix is more real
  detail (rubric criteria, how a number is computed) — never added scope.
- **Design-tense for unbuilt.** A capability that isn't built yet is described as
  designed, in a status note — never claimed in Competencies or Outputs.
- **Grounded numbers.** Any figure (effort, cohort size) is real or omitted.

## Red flags — STOP

- A competency that starts with "Understands" / "Is aware of" / "Appreciates," or
  is a noun phrase ("Financial literacy applied to…"). → Not measurable. Rewrite
  as "The member can [observable verb]…"
- Evidence you can't point to a specific `track.json` substep for. → It's
  aspirational. Tie it to a real step or cut the row.
- A "synthesis" competency whose evidence is "the whole artifact set, taken
  together." → Usually invented. Tie to one artifact or drop it.
- Putting a designed-but-unbuilt step in the Competencies or Outputs. → Move it
  to a future-tense status/"Planned enhancements" note.
- Reaching for adjectives ("robust," "cutting-edge," "world-class") to sound
  authoritative. → Authority comes from accuracy. Cut them.

**Violating the letter of these rules violates their spirit.**

## Inputs

- The track's **brief** (track-brief's Creative Content Brief outcomes are the
  *seed* — competency→evidence starts here).
- The built **`track.json`** — the real steps. Open the `track-design` skill's
  `references/track-json-schema.md` to read it; inventory every `collect`
  (data the member enters) and `generate` (artifact the AI+member produce).
- **Track metadata** — audience, level(s), Live/Designed status, estimated effort.

## Phases

### 0 — Frame
Confirm the track's value promise and its type: Track / leveled Track / Platform
capability. One line: *what a learner has or can do at the end that they couldn't
before.*

### 1 — Read the track
Open the brief and `track.json`. Build an **evidence inventory**: list every
`collect` substep (what the member enters) and every `generate` substep (what the
member produces), by slug. This inventory is the *only* source of evidence
claims. Note anything marked designed/not-built.

Also pull, for the meta line: the **internal capability** the track develops
(from the brief's outcome *alignment* column, or track metadata) and the
**estimated effort**. Do NOT invent either — if the brief/metadata doesn't name
the capability or effort, ask, or omit effort (grounded-numbers rule). Some
steps both collect input *and* generate a reviewable draft (generate-then-review);
tag the evidence to the step's slug and describe the draft mechanic in "How it
works" rather than forcing it into one bucket.

### 2 — Draft competencies (the gate)
For each meaningful capability, write one row: **competency (verb-led,
measurable) → evidence (a real artifact from the inventory, named to its step).**
See `references/academic-template.md` for good/bad examples. **Gate:** every
row's evidence must map to a step in the inventory. A row whose evidence isn't in
the inventory is cut or moved to a designed-status note. Do not leave this phase
with an ungrounded or noun-phrase competency.

### 3 — Write the sections
Description, How it works (the mechanics), Excluded by design (optional),
Outputs, Status. Live in present tense; designed parts in design-tense with a
status note.

### 4 — Emit the JSON
Write the track's `academic_outcomes_json` **item** per
`references/outcomes-json-schema.md`. This is the structured source of truth.

### 5 — Render the doc
Wrap the item in a document (title, About, the How-learning-works tenets, the one
item) and render:
```bash
PYTHONPATH="$HOME/.local/lib/nsls-pydeps:/tmp/pptx_deps" python3.12 -c 'import docx' 2>/dev/null \
  || python3.12 -m pip install --upgrade python-docx --target "$HOME/.local/lib/nsls-pydeps" -q
python3.12 scripts/render_academic_outcomes.py document.json out.docx
```
Upload `out.docx` as a Society Google Doc via `gdoc-build`'s `gws drive files
create --upload …` step (this renderer is already Society-branded — no separate
template build needed).

### 6 — Store + report
Confirm the values with the user (Tier-3 write), then PATCH the `Tracks` record
(base `appzDWu6GowvnACtv`, table `Tracks`) with `academic_outcomes_json` (the
item) and `outcomes_doc_url` (the gdoc URL). Use `typecast: true`. Report the doc
link. If no write token, print the values for manual entry. (Token setup:
`/airtable` or `/connect`.)

### Bundle (on demand)
Given a set of tracks, pull each one's stored `academic_outcomes_json` item, drop
each into the right section (`Learning Experiences` / `Platform Capabilities`),
populate the `overlap` at-a-glance table, and render one combined document with
the same script. Because the bundle renders from the same items as the per-track
docs, they never drift. This is the college/accreditor package.

## The `partner-crosswalk` skill (separate, deferred)

When a partner hands you *their* goals/curriculum and asks how Society maps, use
`partner-crosswalk` (to be built). It takes this skill's
`academic_outcomes_json` as the left-hand side and the partner framework as the
right, producing `Competency → Partner alignment → Depth (Introduce/Develop) →
Note`. Keep partner mapping out of *this* skill — the academic-outcomes doc
stands alone, and the same outcomes map to many partners.

## Rationalization table

| Excuse | Reality |
|---|---|
| "Make it impressive for the accreditor." | Accreditors verify. Impressive-but-false loses standing instantly. Compelling = true and specific. |
| "'Understands X' is a fine outcome." | Not observable, not assessable. "The member can [verb] X." |
| "This evidence is basically what the track does." | If you can't name the substep, it's aspirational. Tie it to a real `collect`/`generate` or cut it. |
| "Include the designed step — it's basically done." | Not built = no learner evidence. Future-tense status note only. |
| "Add a synthesis competency to round it out." | Invented synthesis with no single artifact erodes trust. Tie to one artifact or drop. |
| "It reads thin — add more competencies." | Add real detail, not scope. Depth from rubric criteria, not invented rows. |
| "Just write the WGU-style crosswalk while I'm here." | Different artifact, different skill. This doc is partner-neutral. |

## Reference index

- `references/academic-template.md` — the doc anatomy + good/bad competency examples.
- `references/outcomes-json-schema.md` — the `academic_outcomes_json` item + document shapes.
- `scripts/render_academic_outcomes.py` — JSON → Society-branded `.docx` (single + bundle).
- `gdoc-build` — upload the `.docx` as a Google Doc.
- `track-design` skill's `references/track-json-schema.md` — read `track.json`.
