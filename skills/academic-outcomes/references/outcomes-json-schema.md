# `academic_outcomes_json` — the structured shape

Two shapes: the **item** (one track/capability — stored on the Airtable `Tracks`
record's `academic_outcomes_json` field) and the **document** (what
`scripts/render_academic_outcomes.py` renders — one item for a per-track doc, or
many for a bundle). The document wraps items with framing; the item is the
reusable unit.

## Item (per track — stored in Airtable)

```json
{
  "num": 2,
  "title": "Career Clarity",
  "meta": "Track · Live · Estimated effort ~3.5 hours · Develops the Self-Awareness capability.",
  "description": "One or two sentences: what the experience is.",
  "comp_label": "Competencies",
  "comp_headers": ["Competency", "Evidence the member produces"],
  "comp_rows": [
    ["The member can determine a salary target from real cost inputs.", "A monthly and annual income target computed from six cost-of-living inputs (collect: cost-inputs; computed target)."],
    ["The member can compose a career statement that synthesizes their profile.", "A finalized career statement the member edits from an AI draft (generate: career-statement)."]
  ],
  "how_it_works": "The mechanics — the generate-then-review pattern, the loop, etc.",
  "excluded": "What this track deliberately does NOT cover (optional; omit or null).",
  "outputs": "The artifacts held in the member's profile afterward.",
  "status": "Status: live."
}
```

Field notes:
- `num` — optional ordering number shown as the heading prefix; omit for a lone doc.
- `meta` — `**bold**` spans render bold. Keep `maps-to` **internal** (a Society
  capability / power skill), NOT a partner framework — partner mapping lives in
  the separate `partner-crosswalk` skill.
- `comp_headers` — 2 columns normally; a **leveled** track uses 3
  (`["Level", "Competency", "Evidence the member produces"]`) and each
  `comp_rows` entry has 3 cells.
- `comp_rows` — each evidence string should name the real `track.json` substep it
  comes from (e.g. `(generate: career-statement)`), so the grounding is auditable.
- `excluded` / `status` — optional; omit or set `null` to skip.
- `**bold**` works in `description`, `how_it_works`, `excluded`, `outputs`,
  `status`, `meta`, and each `how_learning_works` bullet.

## Document (what the renderer consumes)

```json
{
  "title": "Society by NSLS · Academic Learner Outcomes",
  "subtitle": "Learning Outcomes · July 2026",
  "about": "The National Society of Leadership and Success (NSLS) has built Society, a new learning and community platform. …",
  "how_learning_works": [
    "**Cohort, not solo.** Members work alongside a group pursuing their own goals.",
    "**Learner-led, AI-assisted.** The AI offers questions and summaries; the member brings the judgment. The judgment is always the member's.",
    "**Real artifacts, not exercises.** Each step produces something the member keeps and uses.",
    "**Coach-aware.** Everything produced enters the AI coach's context.",
    "**Revisable.** Any step can be repeated, so outputs keep reflecting who the member is.",
    "**Gap-closing.** The work targets the distance between where the member is and where they want to go."
  ],
  "overlap": {
    "headers": ["Society track / capability", "Capability developed", "Status"],
    "rows": [["Career Clarity", "Self-Awareness", "Live"]]
  },
  "sections": [
    { "heading": "Learning Experiences", "items": [ { "…one ITEM…" } ] },
    { "heading": "Platform Capabilities", "items": [ ] }
  ]
}
```

- **Per-track doc:** one section, one item. `overlap` optional (usually omit for a
  single track). Keep `title`/`about`/`how_learning_works` so the standalone doc
  still frames Society for a reader.
- **Bundle:** many items across `Learning Experiences` / `Platform Capabilities`,
  with the `overlap` at-a-glance table populated from every item. Compose the
  document by pulling each track's stored `academic_outcomes_json` item and
  dropping it into the right section — the renderer does the rest, so the bundle
  and the per-track docs are the same content.

## Render

```bash
PYTHONPATH="$HOME/.local/lib/nsls-pydeps:/tmp/pptx_deps" python3.12 -c 'import docx' 2>/dev/null \
  || python3.12 -m pip install --upgrade python-docx --target "$HOME/.local/lib/nsls-pydeps" -q
python3.12 scripts/render_academic_outcomes.py document.json out.docx
```
Then upload `out.docx` as a Google Doc via gdoc-build's `gws drive files create
--upload …` step; put the resulting URL in the track's `outcomes_doc_url`.
