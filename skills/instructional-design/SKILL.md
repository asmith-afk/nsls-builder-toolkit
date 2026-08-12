---
name: instructional-design
description: >-
  Turn a functional step-by-step document (installation guide, onboarding or
  setup doc, training guide, any how-to) into a beautifully designed,
  easy-to-follow visual job aid for non-technical users. Not just styling —
  it makes real instructional-design decisions first (what to include or cut,
  whether to split, where a screenshot is needed, how to phrase completion
  checks), then applies the locked "Happy Path" design system — numbered
  trail steps with icons, one action per step, a green "You're done when…"
  checkpoint on every step, and symptom-phrased collapsible troubleshooting.
  Use whenever the user wants a guide or doc made "beautiful", "visual",
  "polished", or "easy to follow"; mentions instructional design, job aids,
  happy path guides, or quickstarts; wants a Google Doc, markdown, or pasted
  procedure turned into a designed HTML page or PDF; or invokes
  /instructional-design. Trigger even on just "make this installation doc
  look nice" or "design this for non-technical people".
---

# Instructional Design

Turn a functionally-correct procedure into a visual job aid a non-technical,
anxious, or hurried person can follow without help. Two passes, in order:

1. **Content pass** — decide what the guide says. This is the actual
   instructional design work and it is never optional.
2. **Design pass** — pour the decided content into the locked design system.

Never skip pass 1 and "just make it pretty." A beautiful guide with the wrong
chunking, missing completion checks, or buried warnings fails the reader
exactly as hard as an ugly one.

## Step 0 — Ingest and orient

Get the source: a Google Doc (read via Drive tools), a pasted text, a file,
or a URL. Then pin three facts before touching anything:

- **Audience**: how technical, how anxious, on what device/OS?
- **The single job**: what is true about the world when the reader finishes?
  (e.g. "the app is installed, signed in, and verified working")
- **The escalation path**: who does the reader contact when stuck? If the
  source doc doesn't say, ask the user — every guide ships with one.

If the source doc is not yet functionally complete (steps missing, order
wrong), say so and stop — this skill designs working procedures; it does not
invent missing steps. Send it back to whoever owns the content.

## Step 1 — Content pass

Read `references/content-decisions.md` and work through its decision
framework. It covers: chunking rules, the step template, what to cut,
when to split into multiple guides, when a screenshot or diagram earns its
place, callout budgets, how to write "You're done when…" checks, the
troubleshooting section, and time estimates. Produce a content outline
(steps + checks + callouts + troubleshooting entries) before writing any
HTML. Significant judgment calls (a split, a large cut) are worth one short
sentence to the user; small cuts don't need narration.

## Step 2 — Design pass

The design system is locked. Do not redesign it, restyle it, or "improve"
it per-document — its value is that every guide from this skill looks and
works the same. The user's explicit instructions are the only override.

1. Copy `assets/template.html` to a working file. It is the complete,
   approved reference implementation with sample content — every component
   you need (header, pack list, step card, done-strip, tip/heads-up
   callouts, finish flag, troubleshooting details, escalation card, footer)
   already exists in it. Replace the sample content with your outline;
   duplicate or delete step blocks as needed; keep the markup shapes.
2. Consult `references/design-spec.md` for the component rules, writing
   patterns, and the icon recipe (simple stroke SVGs, one per step,
   depicting the action).
3. Remove the `DESIGN DRAFT · SAMPLE CONTENT` tag once real content is in.
4. Splice the display font in:
   `python3 scripts/assemble.py <working-file>.html`
   (replaces the `__FONT_B64__` token using `assets/bricolage-latin.woff2`).

## Step 3 — Screenshots of real UI

When a step tells the reader to find a specific on-screen control (a plus
button, a menu item), a small annotated screenshot beats any sentence.
Read `references/screenshots.md` for: when a screenshot earns its place,
how to capture one in each environment (or when to ask the user for one),
the annotation style (ring in the path color), and how to embed as a data
URI. Never fabricate a picture of an app's UI — real capture or nothing.

## Step 4 — Verify

Run `python3 scripts/verify.py <working-file>.html` — it checks WCAG
contrast on the token pairs, renders full-page light + dark screenshots,
and (with `--sections`) emits readable section-by-section PNGs sized for
chat display. Then eyeball the renders: trail connected? callouts distinct?
nothing overlapping? step times sum to the stated total?

For anything the user will distribute, run a second-model review: spawn an
agent (a different model than yourself when the Agent tool offers one) with
the review checklist at the end of `references/design-spec.md`, and apply
what it confirms. This catches the marginal-contrast and phantom-semantics
class of bugs that the author reliably misses.

## Step 5 — Deliver

- Send the HTML plus the section PNGs (screenshots display reliably in chat;
  raw HTML files often don't render inline).
- Offer a hosted artifact page when the environment supports publishing —
  that is the best reading experience (clickable troubleshooting, theme
  aware, zoomable).
- PDF on request: `python3 scripts/verify.py <file>.html --pdf` (the print
  CSS already flattens the sheet, forces light tokens, and auto-opens the
  troubleshooting cards).
- Remind the user the source doc remains the source of truth: edit words
  there, re-run this skill to regenerate. Design fixes go in the skill's
  template so every future guide inherits them.
