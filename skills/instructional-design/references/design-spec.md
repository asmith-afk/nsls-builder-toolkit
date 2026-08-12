# Design spec — the Happy Path system

The template (`assets/template.html`) is the source of truth; this file
explains the intent behind it so edits stay coherent. The system is locked:
consistency across guides is the feature. Change it only on explicit user
instruction, and when you do, change the template so future guides inherit it.

## Concept

The "happy path" is rendered literally as a trail: a dashed path line
connects numbered trail-marker circles down a letter-width document sheet,
ending at a green finish flag. Troubleshooting is "Off the path?" territory,
visually and literally below the trail.

## Layout

- **Letter-width sheet**: 850px white-ish page on a gray "desk", like a
  Google Doc — chosen because it's the document shape non-technical users
  already trust. Don't narrow it back to blog width.
- Base font size 18px (`html { font-size: 112.5% }`); the audience skews
  older/less technical, so err large. Everything is rem-based and scales
  from that one declaration.
- Below 900px the sheet goes full-bleed; below 480px markers shrink and
  step icons hide.

## Tokens (light / dark)

| Token | Light | Dark | Role |
|---|---|---|---|
| `--desk` | #E9ECE6 | #0E1412 | gray surround behind the sheet |
| `--ground` | #F7F8F4 | #151D1A | the sheet |
| `--card` | #FFFFFF | #1D2723 | step cards, pack list |
| `--ink` | #22302B | #E6ECE7 | body text |
| `--ink-soft` | #5A6B63 | #9DAFA5 | secondary text |
| `--path` | #23617A | #7FB6CE | accent: markers, icons, eyebrows |
| `--trail` | #A9C4D2 | #3E545F | the dashed trail line |
| `--done` | #2A6E48 | #7CC79A | success green — "done" strips ONLY |
| `--warn` | #9A6318 | #D9A860 | heads-up callouts |

Rules that keep it working:

- Success green is **reserved** for completion. If green starts meaning
  other things, the checkpoint signal dies.
- Light `--done` is tuned to 5.45:1 contrast on `--done-ground` for the
  small uppercase label — do not lighten it (4.5:1 is the WCAG AA floor;
  the original #2F7D52 failed at 4.47:1).
- Theme architecture is token-level: `@media (prefers-color-scheme: dark)`
  redefines tokens, then `:root[data-theme="dark"]` and
  `:root[data-theme="light"]` redefine them again so a viewer's manual
  toggle beats the OS preference in both directions. Style components
  through tokens only — never hardcode colors inside components.

## Type

- Display: **Bricolage Grotesque** (variable, weights 200–800), inlined as
  a base64 data URI so it can never silently fall back. Used for h1/h2/h3,
  markers, eyebrows.
- Body: `'Seravek', 'Avenir Next', 'Segoe UI', system-ui, sans-serif`.
- Monospace chips (`.ui`, `kbd`): exclusively for text the reader will see
  on screen or must type, verbatim. Never for emphasis.

## Components (all present in the template)

- **Header**: eyebrow, h1, one-sentence lede, trip stats (total time /
  step count / reassurance). Total time must equal the sum of step times.
- **Pack list** (`.pack`): checkbox-style prerequisites.
- **Step card** (`.step`): marker + card. Card = meta line, verb-first h3,
  action icon top-right, `.do` action list, optional callout, `.done-strip`.
- **Trail line**: each `.step::before` draws its own dashed segment down to
  the next marker — never a single absolutely-sized line (it drifts when
  content changes height). The finish flag sits *outside* the `<ol>` so
  screen readers don't announce a phantom extra step.
- **Callouts** (`.callout`): amber ground; icon = circle-i for tips,
  triangle-! for heads-ups.
- **Finish flag** (`.finish`): green marker + celebration card.
- **Troubleshooting** (`.stuck`): "Off the path?" eyebrow, `<details>`
  cards — quoted symptom, gray `(Step N)` tag via `.aside`, chevron —
  then the `.escalate` card.
- **Screenshots** (`.shot`, see screenshots.md): figure with rounded border,
  shadow, optional annotation ring, caption.

## Icons

Simple stroke SVGs, 22×22 viewBox in step cards (16×16 in small contexts),
`stroke-width` 1.8, round caps/joins, `currentColor`, `aria-hidden="true"`.
Depict the *action*. Keep paths short and geometric — circles, lines, one
or two path segments. Test that the glyph reads at 22px; when in doubt,
simpler. (A key that reads as a magnifying glass is worse than no icon.)

## Accessibility / robustness checklist (built into the template — keep it)

- Doctype, `lang`, charset, viewport meta (without the viewport tag the
  mobile breakpoints never fire on real phones).
- Heading ladder with no skips (visually-hidden "The steps" h2 before the
  `<ol>`).
- `summary:focus-visible` outline; `prefers-reduced-motion` respected.
- Print: forces light tokens (dark-mode users otherwise print gray-on-white),
  flattens the sheet, and a tiny script auto-opens `<details>` on
  `beforeprint` so troubleshooting isn't blank on paper.

## Second-model review checklist

When spawning the reviewer agent, ask it to verify, against the actual file:

1. Step template consistency; every step has an observable "done when".
2. WCAG AA contrast on specific hex pairs, small text, BOTH themes.
3. Dark-theme correctness: token overrides beat the media query both ways.
4. Icon-to-action match on every step.
5. Internal consistency: times sum, step tags in troubleshooting match
   real step numbers, no unstyled classes, no heading-level skips.
6. Mobile (viewport meta + breakpoints) and print behavior.
7. Anything a best-practice job aid has that this guide lacks.

Ask for findings with severity + concrete fix, verified against the file,
not speculative. Apply what's confirmed; re-render; re-check contrast.
