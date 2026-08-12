---
name: ux-audit
description: Conduct a heuristic UX audit of a web page, Figma frame, screenshot, or HTML snippet, OR run a Design Validation Layer that predicts member reaction to a proposed change before it ships. Produces (1) a Predicted SUS estimate against the 10 System Usability Scale dimensions, (2) findings against 21 Laws of UX, (3) WCAG 2.1 A/AA accessibility checks, (4) brand-style findings against NSLS or Society brand guidelines, and (5) optionally, a Design Validation readout — surface-area map, past-test cross-reference, member-fit persona panel, DESIGN.md alignment, and three views of impact confidence. Use when the user wants a UX review, usability audit, accessibility audit, brand audit, heuristic evaluation, design critique, or pre-test design validation. Audit triggers include "audit this", "review the UX of", "is this accessible", "WCAG check", "predict SUS", "heuristic eval", "brand audit", or pasting a URL / Figma link / screenshot with audit intent. Design-validation triggers include "validate this design", "design validate", "/design-validate", "QA this change", "predict member reaction", "what will members think", "is this safe to test", "test this hypothesis". Runs in two modes: full (all four layers plus optional Design Validation) or QA (usability + UX + accessibility + functional build quality — links resolve, responsive breakpoints, console errors, tap targets, form error states, semantic landmarks, code readiness — with no brand layer and no member research). QA-mode triggers include "QA this page", "QA this build", "is this ready to ship", "check the responsive behavior", "build-quality pass", "ux qa", or a call from /page-qa. Especially relevant for NSLS enrollment pages and Figma frames in the EE sprint.
---

# UX Audit Skill

Heuristic expert review covering four layers: SUS (usability), Laws of UX (design principles), WCAG 2.1 A/AA (accessibility), and brand-style alignment (NSLS or Society) — plus a functional-QA layer in QA mode. This is **expert review, not user testing**. Findings predict where users will struggle; they don't measure where they actually struggled.

## Modes — pick one in Step 1

| Mode | Layers | Use when |
|---|---|---|
| **Full** (default) | SUS · Laws of UX · WCAG · **Brand** · optional behavioral data + Design Validation | design review, pre-test validation, anything brand-facing |
| **QA** | SUS · Laws of UX · WCAG · **Functional QA** — no brand, no member research | a build-quality pass before handoff or merge, and every call from `/page-qa` |

Treat it as **QA mode** when the request says "QA this page", "QA this build", "is this ready to ship", "check the responsive behavior", "build-quality pass", or when the caller is `/page-qa`. Say which mode you're running in the report header.

**QA mode adds a fifth lens the heuristic layers cannot cover: does the thing actually work?** A page can pass SUS, Laws of UX, and WCAG and still ship a dead CTA, a layout that collapses at 768px, a form with no error state, or console errors. Read `references/qa-checks.md` and prefix those findings `QA.<area>`.

**QA mode deliberately drops brand and member research — do not improvise them.** No font, palette, or voice findings; no personas, past A/B outcomes, sentiment, or behavioral analytics. If a finding depends on brand rules or on what a past test showed, say so and note that full mode covers it, rather than guessing. In the pre-output gate and failure-mode catalog, skip **F2** (proxy fonts) and **F3** (validated wins) — both are brand/research-dependent — and apply every other entry.

## What this skill is NOT a substitute for

- **Real SUS scores.** Heuristic estimates are not validated SUS numbers. For ship/no-ship decisions, run the actual instrument (use `templates/sus-instrument.md`).
- **Automated accessibility scans.** axe-core, Lighthouse, WAVE catch programmatic issues this skill cannot. Run those alongside.
- **Assistive tech testing.** WCAG conformance claims require manual testing with NVDA/VoiceOver/JAWS, keyboard-only nav, and zoom. This skill flags likely issues; it does not certify conformance.
- **Past A/B test outcomes.** A heuristic recommendation may already have been tested by the team and lost. Before treating any P0/P1 as net-new, check Confluence outcome pages, Slack history, and Airtable test priorities. NSLS-specific: see `references/nsls-context.md`.
- **Member sentiment / audience-fit data.** Heuristics + behavioral analytics tell you WHERE users struggle, not WHAT specific solutions land for THIS audience. For audience-fit (CRM cohort variance, sentiment, past message-resonance), pair with `/data-intel`, HubSpot, and any audience research that exists.
- **Cohort / source segmentation.** A funnel drop reported globally may be concentrated in one chapter, source, or campaign. Segment before recommending a global fix.

State these limits in every report.

## Iteration discipline — guardrails must stay up

This skill exists because UX, accessibility, usability, and brand guardrails are easy to lose during chat iteration. Once the agent shifts into "make the edit, claim done" mode, the guardrails stop firing. This section is the explicit gate that prevents that.

### Before every design output (HARD GATE)

Before presenting ANY mockup, change, or design output to the user, verify each item below against the current state of the work. **Quote the verification result — never paraphrase.** If a check wasn't actually run, state that explicitly rather than claim completion.

1. **Brand guardrails** — correct fonts (real fonts > proxies; check `~/Library/Fonts/` and `~/Downloads/` first), correct palette, correct layout patterns. Reference: `references/brand-{nsls|society}.md`.
2. **WCAG AA contrast** — every text/background pairing in the new or changed content has been calculated, not estimated. Required: ≥4.5:1 (body), ≥3:1 (large text), ≥3:1 (UI components per 1.4.11). Quote the ratio.
3. **Validated wins** — if the surface is in `references/design-validate-surfaces.md` with a canonical learnings doc (e.g., enrollment funnel → Confluence 3602579458), every applicable validated principle is integrated or explicitly justified absent. Reference: `references/design-validate-encoded-principles.md`.
4. **Rejected patterns avoided** — scan against the rejected list in encoded-principles.md.
5. **Web/mobile parity** — same content on both platforms unless there's an explicit user-facing reason to differ. No truncated bullets, no dropped links/pricing on mobile.
6. **Adjacent visual distinction** — for component groups (payment buttons, social pills, CTA pairs), confirm each can be told apart at a one-second glance.
7. **Heading hierarchy — count AND order.** Count h1=1 with `grep -oE "<h[1-6]" <file> | sort | uniq -c`. **Also** verify no levels skipped in document order — h1 → h3 without h2, or h2 → h4 without h3. Use Python: `grep -oE "<h[1-6]" file` then walk and flag any `level > last + 1`. Gate-item-7 fails by ORDER even when COUNT passes — see F11 in failure-modes. Report both the single-`<h1>` and unskipped-levels items as **best practice**: neither is required by WCAG at any level, so don't cite 1.3.1 as failed. The genuine 1.3.1 failure to hunt alongside them is a visual heading marked up as a styled `<div>`/`<p>`, which keeps the structure out of the accessibility tree entirely.
8. **Real assets > placeholders** — check `~/Downloads/`, `~/Documents/`, `~/Desktop/` for any real asset (logos, badges, photos) before falling back to styled placeholders.
9. **Terminology accuracy** — domain terms (induction, membership, FOL, dashboard) verified against `references/nsls-context.md` for the specific funnel moment they appear at.
10. **No orphan references** — after any removal/change, grep for stale references to removed elements; rationale blocks + legend sections + TOCs are consistent with current state. ALSO grep stylesheet for orphan CSS class definitions whose HTML consumers were removed (F13).
11. **Responsive behaviour (code-ready)** — for any design claimed as production-ready: the CONTENT adapts (not just doc-wrapper stacking) at mobile (≤767px), tablet (768-1023px), desktop (≥1024px) — reflow, no clipping, no sideways scroll. `@media` queries are the usual mechanism, but a fluid or container-query layout can pass every width with none; judge the rendered outcome, not the presence of rules. If the design is a demonstration (side-by-side device frames), it MUST include an explicit breakpoint specification annotation block so engineers have unambiguous intent. See F14.
12. **Form error/invalid states** — if the design includes forms, error/invalid states must be defined: `.error` or `:invalid` CSS, error-message containers, `aria-invalid` + `aria-describedby` linking error text to the failing input. Missing these is a house-standard finding; it rises to a 3.3.1 failure only where the form automatically detects an error and doesn't describe it in text, and 3.3.3's suggestion requirement applies only when a safe, known correction exists. Don't assert either against a static mockup with no demonstrated validation. See F16.
13. **Semantic landmarks + ARIA form attrs** — exactly one `<main>` landmark wrapping content. `aria-required` on required form fields. `aria-describedby` linking helper text to inputs. `aria-live` regions for status messages (payment confirmation, error toasts). See F17.
14. **Code-readiness (low inline styles, tokenized colors, fluid units)** — inline `style="..."` attributes < 10. Color values use `var(--token)` references where the value is a brand or semantic color; hex literals reserved for one-off brand marks (Apple/Google/PayPal logos). Critical typography + spacing in `rem` (not px). This is a **house standard**, not a 1.4.4 failure — browser zoom scales `px` text, so a `px` page normally passes 1.4.4. The real gain from `rem` is respecting the user's browser font-size preference, which zoom doesn't cover. File 1.4.4 only on observed loss at 200% (clipping, overlap, a control scrolled out of reach). See F15, F18, F19.

The full failure-mode catalog (calibrated against real session failures) is in `references/design-validate-failure-modes.md` — read it before output.

### Mid-iteration re-checks

When the user requests a change in chat ("add X", "change Y", "remove Z"), do NOT make the change and immediately declare done. Re-run the relevant subset of the gate:

| Change type | Subset to re-run |
|---|---|
| New visual element | Contrast + brand alignment + adjacent-distinction |
| New CTA / button | Adjacent-distinction + terminology + brand alignment |
| New copy / labels | Terminology + brand voice |
| Removed element | Orphan-reference grep + cascade check |
| New step / form | Web/mobile parity + autocomplete/inputmode coverage |
| New asset | Real-vs-placeholder check + alt text |
| Cross-brand context (NSLS↔Society) | Brand-mention rule check (no Society on NSLS-branded surfaces unless user approves) |

The failure pattern this prevents: make the edit, claim success, miss what the change broke in adjacent elements.

### Red flags during iteration

These thoughts mean STOP — you're about to ship unvetted work:

| Thought | Reality |
|---|---|
| "I just changed one thing, no need to re-check everything" | Adjacent elements may now conflict — re-run the relevant subset |
| "The contrast looks fine visually" | Visual estimation fails. Calculate the ratio. Quote it. |
| "I used a similar pattern that worked before" | "Similar" ≠ "same." Verify on the current surface, not the analog. |
| "Mobile is just a smaller version of desktop" | No. Parity verified or differences justified. |
| "I'll add the validated wins as a follow-up" | The mockup IS the proof. Wins appear in v1 or v1 fails the gate. |
| "This proxy is close enough to the real font" | Check `~/Library/Fonts/` for the real font before falling back. |
| "Most pages have multiple h1s" | They shouldn't. Run the grep. |
| "The buttons are clearly different — they have different labels" | Different labels at the same visual weight read as identical to a one-second scanner. |
| "The user can replace placeholders later" | If the real asset exists in `~/Downloads/`, use it now. |
| "The rationale block can be updated separately" | Keep rationale + design consistent in the same edit pass. |

### Chain to verification-before-completion

After the gate passes and before the final "done" claim, invoke `superpowers:verification-before-completion`. That skill enforces evidence-before-assertion: run the verification commands, quote the output, never paraphrase. The design-validate gate is the *what to check*; verification-before-completion is the *evidence required*.

## Workflow

### Step 1 — Confirm scope (skip if user already specified)

1. **Input**: Live URL / Figma frame / Screenshot / HTML
2. **Layers**: SUS / Laws of UX / WCAG / Brand / all four (default: all four)
3. **Brand** (when Brand layer is enabled): **NSLS** (formal honor society — Brandon Grotesque + Avenir, navy/red/gold) or **Society** (modern member brand — Cigars + Inter, yellow/cream/black). If unclear, **ask the user before proceeding** — applying the wrong brand reference produces incorrect findings.
4. **Depth**: Quick exec summary or full audit
5. **Audience**: Engineering / Design / SLT / mixed

If a Figma link or URL is already in the message, use it without asking. **Brand selection is the one exception** — confirm NSLS vs Society up front since findings differ materially between the two brands.

### Step 2 — Gather the artifact

**Live URL:** `web_fetch` for HTML. Cannot audit: focus order, keyboard nav, screen reader behavior, JS-rendered states, hover/focus states, error states, animation. Flag in report.

**Figma frame:** Use `Figma:get_design_context`, `Figma:get_screenshot`, `Figma:get_metadata`. Cannot audit: real keyboard nav, screen reader output, error/loading states unless explicitly designed, motion accessibility. Flag in report.

**Screenshot:** `view` the image. Severely limited — visual heuristics only. No semantics, no precise contrast, no alt text check. Flag heavy limitations.

**HTML snippet:** Same as URL fetch result.

### Verify-before-flagging guard (for low-resolution static frames)

Mobile Figma frames at iPhone width (393px) often render at small image dimensions (~100-250px wide in screenshot output) where dropdown carets, missing fields, and other small affordances are easy to misread. Before flagging **structural form findings as P0 or P1** (missing fields, wrong input types, dropdown vs text affordance, button placement), do at least one of:

1. Request a higher-resolution Figma export (`get_design_context` returns the full code which lists every field unambiguously — preferred over screenshot inference for structural questions).
2. Request the live URL if it exists, and confirm the affordance there.
3. Explicitly mark the finding "low-confidence — confirm on live URL or higher-res export before treating as P0."

**Fabrications are easy here.** During this skill's first run, two structural P0/P1 findings turned out to be visual misreads of small mobile screenshots. If you can't see the affordance clearly, ask before flagging.

### Step 3 — Read the relevant references BEFORE generating findings

| Layer requested | Read this file |
|---|---|
| SUS estimate | `references/sus-dimensions.md` |
| Laws of UX | `references/laws-of-ux.md` |
| WCAG | `references/wcag-21-AA.md` |
| Brand — NSLS (full mode only) | `references/brand-nsls.md` |
| Brand — Society (full mode only) | `references/brand-society.md` |
| Functional QA (QA mode) | `references/qa-checks.md` |
| Severity (always) | `references/severity-rubric.md` |
| NSLS audience context (if NSLS member-facing page) | `references/nsls-context.md` |
| Design Validation Layer (Step 6, any design output) | `references/design-validate-surfaces.md`, `design-validate-personas.md`, `design-validate-confidence.md`, `design-validate-hubspot-retrieval.md`, `design-validate-encoded-principles.md` |
| Failure modes (any design output, mandatory) | `references/design-validate-failure-modes.md` |

Reading the reference is mandatory. Generating findings from memory leads to fabrication. **For brand findings, read ONLY the reference matching the user-confirmed brand** — don't apply NSLS rules to a Society surface or vice versa, since the typography, color, and voice rules diverge materially.

### Step 4 — Produce the report

Use `templates/report-full.md` (or `report-quick.md` for exec summary). Save to `/mnt/user-data/outputs/ux-audit-{descriptor}-{YYYY-MM-DD}.md` and call `present_files`.

Every finding follows this structure:
```
**[Severity] [Layer.Item] Title**
- Where: specific location/element
- Issue: what's wrong, plain language
- Impact: who is affected, how
- Recommendation: concrete fix
- Auditable from this input: yes / partial / no
```

The Layer prefix tells the reader which lens the finding came from:
- `SUS-N` (e.g., `SUS-3` = "Easy to use" item)
- `LoUX.<Law>` (e.g., `LoUX.Hick`, `LoUX.Fitts`, `LoUX.Jakob`)
- `WCAG.<criterion>` (e.g., `WCAG.1.4.3`, `WCAG.3.3.4`)
- `Brand.<area>` (e.g., `Brand.typography`, `Brand.color`, `Brand.logo`, `Brand.voice`) — full mode only
- `QA.<area>` (e.g., `QA.links`, `QA.responsive`, `QA.forms`, `QA.code`) — QA mode only

### Step 5 (optional) — Layer in behavioral data

Heuristic findings predict where users WILL struggle. Behavioral data shows where they ARE struggling. The audit is meaningfully stronger when behavioral evidence either confirms or refutes each P0/P1.

After the heuristic pass, ask the user: "Do you want me to query PostHog (or another analytics source) to validate these findings against actual user behavior?" If yes:

- For PostHog-instrumented products: invoke `/posthog` skill. Pull the funnel by device, time-on-step, error events on the affected URLs, and 3-5 sample session paths.
- For each P0/P1 in the heuristic report: confirm, refute, or note as inconclusive. Behavioral evidence may also reveal NEW findings invisible in static review (redirect loops, JS errors, ping-pong navigation patterns).
- Behavioral data may shift severity — a heuristic P2 that affects 30% of mobile users in PostHog should be reclassified P1.
- Behavioral data may shift the SUS estimate — note "behavioral-adjusted SUS" alongside the heuristic SUS.

Output as a separate behavioral-audit doc that cross-references the heuristic audit, OR as an inline section if the data fully validates the heuristic findings without surprises.

### Step 6 (optional) — Design Validation Layer

Trigger this step explicitly when the user says: "validate this design", "design validate", "/design-validate", "QA this change", "predict member reaction", "what will members think", "is this safe to test", "test this hypothesis". Surface these triggers in Step 1 if the user's intent is pre-ship validation rather than retrospective audit.

**Purpose.** Take a proposed change and produce a holistic validation readout — surface-area map, past-test cross-reference, member-fit prediction, brand + a11y check (reuses Steps 1-4), DESIGN.md alignment, and three views of impact confidence. This step REPLACES the older skeletal "recommend you query past tests" guidance; it is the operational version.

#### Sub-step 6.1 — Confirm surface + audience

Prompt the user (skip what's already stated):

- **Product surface**: enrollment funnel / invitee landing / member dashboard / Society app / marketing site / advisor tools / email lifecycle
- **Audience**: cold prospect / invitee / active enrollee / newly inducted / engaged inducted / disengaged inducted / Society user / advisor

Then read `references/design-validate-surfaces.md` for the full surface × audience matrix and the retrieval rules that apply to each combination.

#### Sub-step 6.2 — Surface map

Map every element the change touches:

- UI components affected (in scope + adjacent)
- Behaviors changed (clicks, transitions, defaults, copy, validation rules)
- Events touched (PostHog / GA / segment instrumentation)
- Downstream systems (HubSpot writes, Airtable, Customer.io triggers, n8n workflows, Moodle, payment)
- Member touchpoints upstream and downstream of the change

Output as a structured list. This is the "blast radius" view — it tells reviewers what else could move when this ships.

#### Sub-step 6.3 — Past-test cross-reference

Scope-aware retrieval:

- **IF surface = enrollment funnel OR invitee landing**: read Confluence page **3602579458** ("Experiment Learnings — Enrollment Funnel" at https://societyleadership.atlassian.net/wiki/spaces/EE/pages/3602579458). Check the proposed change against:
  - (a) Validated cross-cutting principles
  - (b) Rejected patterns
  - (c) The experiment outcome table for direct prior tests on the same element/copy/flow

  Then call PostHog `experiment-get-all` for in-flight tests not yet on the Confluence page.

- **IF surface = anything else** (member dashboard, Society app, marketing, advisor tools, email): state explicitly: *"No canonical learnings doc for this surface — net-new bet, no prior evidence."* Proceed with the other layers. The confidence framework in 6.7 downweights accordingly.

Read `references/design-validate-encoded-principles.md` for the auto-flag rules drawn from the Confluence learnings doc — these are the patterns the skill should automatically check the proposed change against (e.g., "removing trust signals from the start step has consistently lost").

#### Sub-step 6.4 — Member-fit panel

Select **3-6 personas** from `references/design-validate-personas.md` based on the audience(s) the surface serves. For each persona:

1. Retrieve real HubSpot ticket quotes filtered by surface (`hs_ticket_category`) × persona-specific filters (`lifecyclestage`, chapter, state, age band where available).
2. Read those quotes and synthesize the persona's likely reaction to the change.
3. Output **like / hate / confuse** signals per persona, each grounded in retrieved quoted ticket text with links back to the source ticket.

Reactions are grounded in retrieved quotes — never fabricate. If you cannot find ≥3 relevant quotes for a persona, say so and downweight that persona's contribution.

#### Sub-step 6.5 — DESIGN.md alignment

- If the target surface has a `DESIGN.md` in its repo, evaluate the change against the numbered UX principles in that file. This reuses `/product-design` Mode 2 — invoke that skill if it's not already loaded.
- If no `DESIGN.md` exists at a **Department+ scope** surface, flag this as a gap in the report and link to `/product-design` for remediation.
- Skip this sub-step entirely if the surface is **Personal scope**.

#### Sub-step 6.6 — Brand + a11y check

- If Steps 1-4 of `/ux-audit` have **not** already run on this artifact: run a lightweight pass for brand violations (using the correct brand reference — `brand-nsls.md` or `brand-society.md`, per the user-confirmed brand) and WCAG blockers. Surface P0/P1 only.
- If Steps 1-4 **have** already run: cross-reference the existing P0/P1 findings instead of duplicating. Pull them into the validation report under "Inherited from heuristic audit."

#### Sub-step 6.7 — Confidence prediction

Three views in the output — always all three, side by side:

1. **Directional verdict**: positive / neutral / negative / mixed. One word, with one-sentence rationale.
2. **Multi-factor score**: 0-100 with transparent weights. See `references/design-validate-confidence.md` for the factor list (past-test alignment, member-fit signal strength, DESIGN.md alignment, brand + a11y risk, surface map blast radius, etc.). Show the per-factor sub-scores so the reader can audit the math.
3. **Range estimate**: ONLY when ≥3 comparable past tests on the same surface provide a prior. Format as "expected effect range: -X% to +Y% on [primary metric], based on N prior tests." Otherwise: *"No prior; net-new bet."*

#### Sub-step 6.8 — Output

**Before saving the report or presenting any design output, run the Pre-output Gate at the top of this skill (`## Iteration discipline — guardrails must stay up`). Quote each verification result inline. Do not declare done until every applicable item in the gate has been verified or explicitly justified.**

Then save the report at `/mnt/user-data/outputs/ux-audit-{descriptor}-validate-{YYYY-MM-DD}.md` using the structure in `templates/design-validate-report.md`. Call `present_files`.

Finally, invoke `superpowers:verification-before-completion` before claiming "done" — that skill enforces evidence-before-assertion patterns the gate above doesn't capture (running tests, confirming output, etc.).

### Step 7 (optional) — Layer in member-fit data (lightweight, when not running full Step 6)

When the user wants a lighter touch than the full Design Validation Layer, recommend (or actively run) one or more of:

- **Past test outcomes:** search Confluence outcome pages, Slack channels, and Airtable test priorities for any test that has already addressed each P0/P1. Avoid re-running tests the team has already concluded.
- **Cohort variance:** segment the funnel by chapter, source, campaign, and traffic medium. The "global" issue may be one cohort.
- **Audience sentiment:** any survey, NPS, or qualitative member feedback on the affected pages.

For NSLS specifically, the saved audience-fit context is in `references/nsls-context.md`. For cross-system orchestration of these queries, use `/data-intel`. If the user wants the structured persona + confidence readout, use Step 6 instead.

### Step 8 (optional) — Generate deployable SUS instrument

If the user wants a real SUS survey, use `templates/sus-instrument.md`.

## Honesty constraints

1. **Predicted SUS is heuristic.** Always labeled "Predicted SUS — heuristic estimate, not user-validated." Show per-item scores and reasoning. Don't lead with a single number.
2. **Be explicit about input limits.** Don't speculate about hover/error/loading states unless visible.
3. **WCAG conformance ≠ accessibility.**
4. **Don't fabricate.** If a criterion can't be evaluated, mark "not auditable from this input." Smaller honest report > long speculative one.
5. **Severity must match impact.** P0 = blocks task completion or legal/safety risk. Don't inflate.
6. **Don't fabricate names or owners.** If a ticket needs sign-off from a stakeholder (finance, product leadership, etc.) and you don't know who that is, write "the owner of [domain]" and ask the user. Don't invent a name to make the recommendation feel grounded.
7. **Acknowledge what wasn't queried.** If the audit didn't pull past test outcomes / member sentiment / cohort segmentation, say so explicitly in the limits section. Recommendations from heuristic + behavioral alone are still partial.
8. **Brand findings require the right brand reference.** If the user hasn't confirmed NSLS or Society, ASK before generating brand findings. Applying NSLS rules to a Society surface (or vice versa) is a fabrication-class error. State the confirmed brand in the report header.
9. **Brand intent over brand rules in edge cases.** When a brand-rule violation is visible but the design is clearly leaning into a deliberate brand choice (e.g., Society's intentional yellow-heavy hero on a campaign), favor the brand pillars (Fresh Optimism, Approachable Authority, Textured Diversity, Vision-casting for Society; Institutional/Approachable Authority/Trust for NSLS) over a literal-rule violation. Note both in the finding.

### Design Validation Layer (Step 6) additional constraints

10. **Persona reactions are synthetic.** Retrieved HubSpot quotes are real, but the persona's read of them is generated. Never present a persona reaction as a direct member quote. Quote text gets attributed to the ticket it came from; the interpretation gets attributed to the skill.
11. **Multi-factor score is a rubric, not a statistic.** The 0-100 score is reproducible because the weights are transparent — it is not a probability or a predicted lift. Don't let it read like a forecast.
12. **Range estimate is a prior, not a forecast.** It only appears when ≥3 comparable past tests on the same surface exist. Frame it as "based on N prior tests" — never as the expected outcome of THIS test.
13. **Past-test cross-reference stays within surface.** Learnings transfer within the same surface by default. Cross-surface inference is allowed only when the principle is plausibly universal (WCAG, cognitive load, Fitts/Hick) and MUST be marked explicitly as a cross-surface inference in the report.
14. **Downweight thin member-fit evidence.** If quote retrieval returns <3 relevant quotes per persona, downweight the member-fit panel's contribution to the multi-factor score AND say so in the report. Don't paper over thin evidence.
15. **Learnings doc freshness.** The Confluence learnings doc (page 3602579458) is current as of the validation date. If the validation runs against a date earlier than 2026-05-11, double-check PostHog for newer experiments not yet rolled into the page.

## WCAG 2.2 considerations

This skill covers WCAG 2.1 A + AA. WCAG 2.2 added 9 criteria; three are relevant to enrollment:
- **2.5.8 Target Size (Minimum)** — AA — 24×24 CSS px minimum, subject to five exceptions (spacing, inline, equivalent control, user-agent-determined, essential). Rule them out before calling an undersized target a failure — body-copy links and well-separated small controls conform. Detail in `references/qa-checks.md` → QA.targets.
- **3.3.7 Redundant Entry** — A — don't re-ask info already entered
- **3.3.8 Accessible Authentication (Minimum)** — AA — no cognitive function tests for login

Mention these for checkout, login, or multi-step form audits.
