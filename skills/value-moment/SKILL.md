---
name: value-moment
description: >-
  Use when authoring or improving a Society (ignite-next) learning track and you
  want to hand personalized value back to the member from data they already
  entered — turning a collected field (major, location, strengths, goal) into an
  insight nugget that teaches them something and pulls them deeper. Called by
  track-brief and track-design; also use directly to add or audit the value
  moments in an existing track. Triggers: "value moment", "insight nugget",
  "personalize this step", "make this field pay off", "what can we tell them
  after they enter X".
---

# value-moment

## Purpose

Every field a member fills in is an opening to hand value *back*. They tell us
their major — we can show them where that major leads. They tell us their state —
we can show them what changes if they're open to relocating. Done well, each
input visibly returns insight, so the member *wants* to keep going. This
sub-skill invents and ranks those moments for a track and emits them as authored
`generate` substeps. Its reason to exist is one hard rule most authors get wrong
under pressure: **a personalized insight is only valuable if it's true.** A
confident-sounding fabricated statistic doesn't build trust — it destroys the
exact trust the moment was meant to earn. This skill makes grounded the default
and makes ungrounded precision impossible to ship by accident.

## The faithfulness rule (the core constraint — read this first)

Every value-moment candidate MUST declare a `grounding`, and its
`prompt_template` MUST match that grounding. Three grounding levels, in
preference order:

- **grounded** — backed by a real data source (BLS OEWS by SOC/area, O*NET
  bright-outlook / growth, or a dataset we wire in). **Get the real figures now**
  by running the grounding lookup from **this skill's directory**:
  `node scripts/lookup-grounding.mjs "<major>"` (the script lives in this skill's
  `scripts/`; run it from there, or give its full path). It reads a snapshot
  bundled with this skill (`data/grounding-snapshot.json`, built from the NCES
  crosswalk + BLS OEWS; track-studio is the source of record) — or a live
  track-studio checkout / `--snapshot` override — and returns the
  actual careers + median wages you'll ground against. Use those numbers in the
  `example_output`, and emit a `grounding` spec so the runtime injects them (see
  `references/generate-substep-emission.md`). **Preferred.**
- **model-reasoned** — qualitative and defensible from general knowledge
  ("marketing majors commonly move into brand, growth, and product roles").
  Allowed, but framed as general — **no precise statistics.**
- **illustrative** — explicitly framed as an example or estimate ("roughly," "as
  an illustration," "in many markets") when no source exists. Never a bare,
  false-precise number presented as fact.

**The bright line:** a specific number (a percentage, a salary, a growth rate, a
ranking like "fastest-growing") may appear ONLY at `grounded` level, sourced to
real data supplied to the prompt. If you cannot supply the figure from a real
source, the candidate is not `grounded` — drop the number and reframe as
model-reasoned or illustrative, or cut the candidate. This is non-negotiable.

**Violating the letter of this rule violates its spirit.** A number that is
"probably about right," "a reasonable estimate," or "close enough to feel real"
is a fabrication. Plausibility is not grounding.

**Grounded but misleading is still wrong.** A real figure aimed at the wrong
frame deceives too — e.g. showing the *marketing-manager* median salary to a
first-year student as if it were a starting wage. When you supply a real number,
supply the one that matches the claim, and label what it is (role, year,
national vs. local, entry vs. experienced). Right number, wrong framing = still a
broken promise.

### Red flags — STOP

- Writing a percentage, salary, or "fastest-growing / most in-demand" claim you
  cannot point to a real source for.
- Telling yourself "the number just makes it feel credible" — that is the harm,
  not the value.
- "I'll mark it grounded and we'll wire the data later" — if the data isn't
  supplied to the prompt, it is NOT grounded. Mark it grounded only when `{data}`
  is real.
- Asserting a market trend ("digital roles are where the demand is," "Columbus is
  a marketing hub") as established fact with no source — that is a claim, not a
  vibe. Ground it or hedge it.
- A `prompt_template` that says "use specific figures" without supplying them —
  you have just instructed the model to fabricate.

If you catch yourself at any of these: downgrade the grounding, remove the
number, or cut the candidate.

## When to use

- Inside **track-brief** (Track Template Brief → "Value moments" section) or
  **track-design** (Phase 2 shape / Phase 5 authoring).
- Standalone, to add value moments to an existing track or audit the ones it has.
- NOT for the track's core teaching content — this is specifically the
  personalized, data-returning nuggets.

## Inputs

1. The track's **collected fields up to point N** — the answers known by the time
   a nugget would fire, in order (from the Track Template Brief's "what
   information will be collected," or by reading the track JSON's `collect`
   substeps).
2. The **audience** + value promise.
3. Optionally the existing track JSON, to place nuggets between real steps.

## Process

1. **List the capture points in order.** For each collected field (and each
   useful combination), ask: *what could we truthfully tell the member the moment
   they've entered this?*
2. **Draft candidates.** For each, fill the candidate table (below). Assign a
   grounding honestly at this step — decide where the facts come from before
   writing the prompt.
3. **Apply the faithfulness rule to every candidate.** Any precise number that
   isn't `grounded` with real supplied data gets removed or the candidate
   reframed. This is a gate, not a polish pass.
4. **Rank** by expected value to the member × groundedness × pull-along strength
   (fires right after the relevant capture). Prefer grounded over clever.
5. **Give each a rendered `example_output`** so a human can judge the value
   before it ships. The example must obey its own grounding — for a **grounded**
   candidate, run `node scripts/lookup-grounding.mjs "<major>"` and write the
   example with those **real** figures (and carry the attribution it prints); for
   model-reasoned/illustrative, no invented numbers. (`--list` shows covered
   majors; an uncovered major stays qualitative until it's added to the snapshot.)
6. **Propose the top 3–5.** The author picks; this skill proposes, never
   auto-inserts. **This ranked list — each candidate with its `example_output`
   and `grounding` — is the deliverable when called from `track-brief`.** Stop
   here in that context: the track structure doesn't exist yet, so there is
   nothing to emit `generate` JSON into. The list becomes the Track Template
   Brief's "Value moments" section.
7. **Emit the approved ones** as `generate` substeps — **only in `track-design`
   (Phase 5) or standalone track-editing, where the track structure already
   exists.** Open `references/generate-substep-emission.md` and the track schema;
   never author the JSON from memory.

## The candidate (output shape)

| Field | Meaning |
|---|---|
| `trigger` | the data known by this point, as tokens (e.g. `{major}`, `{location}`, `{major}+{strengths}`) — must be collected earlier or a prerequisite profile token |
| `insight_type` | career-options, demand-growth, salary-by-geo, peer-comparison, strength→role fit, … |
| `placement` | after which step it fires (the pull-along moment) |
| `prompt_template` | the authored AI prompt, using `{tokens}`, that generates the paragraph — carries the grounding contract in its own words |
| `example_output` | a rendered example so a human can judge the value |
| `grounding` | **REQUIRED** — `grounded` / `model-reasoned` / `illustrative`, plus where the facts come from and the exact honesty framing |
| `value_dim` | which focus-group **Value** sub-check it targets (`value.a` "returns something useful," `value.c` "personalized to me") |

## Worked example (career-clarity)

- **trigger:** `{major}` captured step 1.
- **insight_type:** career-options + demand-growth.
- **placement:** immediately after the major capture (pull-along).
- **grounding:** grounded — run `node scripts/lookup-grounding.mjs "Marketing"`,
  which returns the real careers + BLS median wages (e.g. Marketing Managers
  $161,030, May 2024). Emit a `grounding` spec so the runtime injects those
  figures; the template references the provided block, not `{slug}` tokens (see
  `references/generate-substep-emission.md`).
- **prompt_template:** *"The member's major is in the profile provided. Using ONLY
  the labor-market figures provided, write two short second-person paragraphs on
  the careers this major commonly leads to and their pay. Use only the provided
  figures; if one is missing, describe the trend qualitatively and invent no
  number."*  plus `grounding: { need: ["careers","salary"], from: { major: "major" } }`.
  (That `from` assumes a standalone major substep. When major is collected inside the
  `education` entry form — as Welcome does — address the subfield: `from: { major:
  "education.major" }`. See "Addressing the major" below.)
- **example_output:** *"A marketing degree opens a range of roles — Marketing
  Managers (national median $161,030), Sales Managers ($138,060), and Market
  Research Analysts ($76,950), among others…"* — real figures from the lookup.
- **value_dim:** value.a + value.c.

Contrast — the SAME idea done wrong (do not ship): *"Marketing grads earn
~$63,000 and the field is growing 19% — fastest in Ohio."* No source — fabricated.
Run the lookup and use the real numbers, or cut them and stay model-reasoned.

## The grounding companion (v1 shipped)

The data-fetch companion this sub-skill named now exists:
- **Authoring (here):** `scripts/lookup-grounding.mjs "<major>"` reads the baked
  snapshot (NCES CIP↔SOC crosswalk + BLS OEWS median wages) and hands you the real
  careers + figures to write into a grounded nugget's `example_output`.
- **Runtime:** the `grounding` spec you emit is honored by the Track Studio demo
  proxy, which injects the same figures into the AI call — so preview and (once
  wired into ignite-next) production show real numbers.

Coverage today: the **full CIP catalog (~2,143 majors)** with **national + per-state
median salary** (`--state "Ohio"`), **projected % growth** (BLS EP 2024–34), and
**popularity-ranked** matching (IPEDS degrees, so "Nursing" → Registered Nursing).
Fast-follow: metro-level wages, richer aliasing. For a genuinely uncovered major or
a missing figure, stay model-reasoned — never fabricate.

### The match is gated on confidence — an ambiguous major grounds to NOTHING

Free-text major names resolve via the matcher, but **not every term resolves**, and
that is deliberate. A loose match produces a confidently wrong figure with a BLS
citation attached, which is worse than no figure at all.

- **An exact catalogue title always MATCHES — which is not the same as grounding.**
  All 2,143 titles resolve exactly, so a picklist removes the *matching* risk
  entirely. It does not remove the *coverage* risk: a title whose CIP has no
  crosswalked occupation still returns an empty payload (see the ~194 below). So a
  picklist-fed moment is reliable in the sense that it never grounds against the
  WRONG major — but you still have to check the specific major returns figures.
- **A dominant common name grounds** — "Business Administration" → *Business
  Administration and Management, General.*, "Economics" → *Economics, General.*
- **An ambiguous name grounds to nothing.** "Communications" matches five unrelated
  programs (visual design, strategic comms, broadcast tech) with no clear winner, so
  the runtime returns an empty payload. "Criminal Justice" likewise. The lookup tells
  you when this happens and lists the alternatives — pick an exact title, or keep the
  nugget qualitative.
- **~194 majors have no crosswalked occupations** (mostly "…, Other." catch-all
  codes). These return an empty payload rather than a placeholder SOC.

The CLI and the runtime run the **same** matching rules against the **same**
snapshot, so what the lookup shows you is what a member gets. If the lookup says
a major is ambiguous, the track cannot ground it — do not author figures around it.

### Addressing the major: `grounding.from`

`from` maps a lookup input to where the answer lives. Supported shapes:

| ref | resolves against |
|---|---|
| `"major"` | a substep whose answer is a plain string |
| `"education.major"` | a subfield of the structured `education` / `work` entry form |
| `"education.major"` | …an entry **list** — the first entry with a non-empty value wins |
| `"education.major"` | …a JSON-encoded answer of either shape |

**Address the subfield, not the substep.** `from: { major: "education" }` does NOT
work: the entry form holds several fields, and the resolver refuses to guess which
one is the major rather than grounding on an arbitrary value. (It used to guess, and
picked School Name — so a member at MIT grounded against *Gunsmithing/Gunsmith.*)

## How it's scored

Value moments are scored by the focus-group rubric's **Value** dimension
(`value.a`, `value.c`) during the track-prototype walk, and calibrated by whether
they lift **per-step continuation** once live. A moment that tests well but can't
be grounded is a failed moment, not a shippable one.

## Rationalization table

| Excuse | Reality |
|---|---|
| "A specific number makes it feel credible." | A fabricated number makes it a lie that feels credible — the worst kind. Credibility comes from being right. |
| "It's probably about right / a reasonable estimate." | Probably-right precision is still fabrication. Ground it or drop the number. |
| "I'll mark it grounded and wire the real data later." | Grounded means the real figure is supplied to the prompt NOW. No data = not grounded. |
| "Everyone knows digital marketing is growing." | General trend, stated qualitatively = model-reasoned, fine. A percentage on it = needs a source. |
| "The prompt says 'use specific figures' — the model will know real ones." | The model will invent plausible ones. Supply the figures or forbid them. |
| "It's just an illustration, the number is fine." | Illustrative means explicitly framed as an example ("roughly," "for instance") — never a bare number presented as fact. |
