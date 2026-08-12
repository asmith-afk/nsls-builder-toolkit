# Content decisions — the instructional-design pass

The reader is a non-technical person, alone, possibly anxious, following
instructions on a screen or printout. Every decision below optimizes for one
thing: they keep moving forward and always know whether the last thing
worked. That single idea — observable progress — drives all of it.

## The step template (non-negotiable shape)

Every step has exactly this shape, because the reader learns the rhythm on
step 1 and then stops reading structure and starts reading content:

- **Number + time estimate** — "Step 2 · about 4 min". Times must sum to
  the total promised in the header. A guide that can't count its own steps
  loses the reader's trust before step 1.
- **Verb-first title** — "Download the installer", never "The installer" or
  "Installation". The title alone should tell a returning reader where they
  left off.
- **Icon** — one simple glyph depicting the *action* (download arrow, key,
  paper plane). Scanning readers navigate by icon; a mismatched icon
  (a magnifier on a sign-in step) actively misleads them.
- **Do this** — 1–3 micro-actions max. Literal on-screen labels go in
  monospace chips exactly as they appear (`Download for Mac`, `Keep`).
- **You're done when…** — see below. Every step. No exceptions.

## "You're done when…" — writing completion checks

This is the single highest-value element in the system, and the one source
docs almost never contain — expect to write these yourself.

A good check is **observable**: something the reader can see on their screen
right now, not a state they must take on faith.

- Good: "you see your own name in the top-right corner of the app"
- Good: "a file appears in your Downloads folder"
- Bad: "the installation is complete" (restates the step, verifies nothing)
- Bad: "the app is configured correctly" (how would they know?)

If you cannot write an observable check for a step, that's a signal the step
is either too abstract (split it) or unnecessary (cut it).

## Chunking and the split decision

- **3–7 steps.** Under 3, it doesn't need this treatment. Over 7, the trail
  stops feeling finishable — split.
- **Split when**: more than ~7 real steps; more than one audience
  (admin vs. end-user); more than one starting condition (fresh install
  vs. upgrade); or platform differences that touch most steps.
  Each split gets its own guide with its own finish flag.
- **Don't split for platform differences that touch only one step** — handle
  those inline ("On a Mac… / On Windows…") or in a callout.
- A "step" can contain 2–3 micro-actions if they're one gesture in the
  reader's mind (open browser + go to URL + click download = one step:
  "Download the installer").

## What to cut (and where it goes instead)

Source docs written by experts carry passengers. Default dispositions:

| Source material | Disposition |
|---|---|
| Background, history, architecture, "why we chose X" | Cut entirely |
| Alternative methods ("you can also…") | Cut — the happy path is ONE path |
| Edge cases and failure handling | Move to troubleshooting section |
| Warnings about scary-but-normal moments | Keep — as a callout, reframed as reassurance |
| Prerequisites scattered through the doc | Consolidate into the pack list up top |
| Reference material (settings tables, config options) | Cut, or link out; it's a different document |

Cutting is the job. A happy-path guide is defined by what it refuses to
include. If the owner of the source doc needs the cut material to live
somewhere, that somewhere is a second document, not this one.

## Callouts — a budget, not a decoration

Two kinds, used sparingly (roughly one per step, max):

- **Tip** (info tone): smooths a moment of hesitation. "If your browser asks
  whether to keep the file, choose Keep. It's checking, not warning."
- **Heads up** (warning tone): pre-announces a scary-but-normal moment
  *before* it happens — password prompts, security dialogs, long waits.
  The formula: what they'll see + "that's normal" + what it actually means.

Anxious readers quit at unexplained scary moments. The heads-up callout is
how you spend design budget preventing that. If a step needs three callouts,
the step is hiding complexity — restructure it.

## Screenshots and diagrams — when they earn their place

Add an annotated screenshot when the reader must **locate** something that
words describe poorly: an unlabeled icon button, one control among many, a
region of a busy window. ("Press the + button at the bottom" → show it.)

Skip the screenshot when the action is unambiguous ("type your email and
press Enter") — gratuitous screenshots bloat the page, go stale on every UI
change, and train readers to skip images.

Diagrams (flow, architecture) almost never belong in a happy-path guide —
if the reader needs to understand a system to follow the steps, the steps
are wrong. The one exception: a physical setup ("plug cable A into port B")
where spatial arrangement is the content.

See `screenshots.md` for capture and annotation mechanics.

## The troubleshooting section

Keeps the happy path pristine by giving failures somewhere else to live.

- **Phrase entries as symptoms in the reader's own words**, quoted:
  "The download never showed up." — not "Download failures" or root causes.
  Non-technical readers can't diagnose; they can only recognize what their
  screen looks like.
- **Tag each entry with its step** ("(Step 2)") so readers connect it back.
- **Collapsed by default** (progressive disclosure) — visible failure modes
  make the happy path look dangerous.
- **Fixes are short detours**: 1–2 moves, then back to the trail. Anything
  longer belongs with the escalation path.
- **Always end with an escalation card**, and include explicit permission to
  stop: "Still stuck after two tries? Stop there — you haven't broken
  anything." Then exactly one contact channel and what to include (a photo
  of the screen beats any description a non-technical user can write).
  The "you haven't broken anything" line matters: fear of having caused
  damage is why people stop asking for help.

Source the entries from: failure modes in the source doc, plus the 2–4
most likely real-world snags for each step type (downloads → blocked file;
installers → OS security dialogs; sign-in → wrong-password-for-this-screen;
network checks → still connecting vs. offline). Don't exceed ~5 entries —
a long troubleshooting list reads as "this usually fails."

## The pack list ("Before you set off")

Everything the reader must have *before* step 1, so nothing ambushes them
mid-trail: physical items, credentials (say which step needs them), and a
realistic uninterrupted-time estimate. 3–5 items. If there's nothing to
gather, the section can be omitted — but credentials are almost always
needed and almost always forgotten.

## Tone

- Second person, active voice, present tense. "Click", not "the user
  should click".
- Name things what the reader sees, not what the system calls them.
- Reassure at scary moments; celebrate at the end (the finish flag is not
  decoration — completion needs to be *felt* or the reader stays unsure).
- No jargon without an immediate plain-word gloss. When two similar
  credentials exist (computer password vs. email password), disambiguate
  explicitly at every point of possible confusion.
