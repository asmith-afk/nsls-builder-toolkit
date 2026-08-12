# QA Layer — functional build checks

The other three layers ask *"will this be hard to use?"* This one asks *"does it actually work?"* A page can score well on usability, UX and accessibility and still ship broken links, a layout that collapses at 768px, or a form with no error state.

Run these against the artifact you were given. For each check, **quote the result — never paraphrase.** If a check could not be run against this input, mark it `not auditable from this input` rather than passing it silently.

Finding prefix: `QA.<area>` — e.g. `QA.links`, `QA.responsive`, `QA.forms`.

**Say which kind of finding it is.** Most checks here are house standard, not conformance
minimums, and calling a house preference a "WCAG failure" is a correctness bug in the audit
itself — it burns the author's trust on the findings that *are* failures, and it pressures
them into changes the spec never asked for.

| Label | Means |
|---|---|
| **Build defect** | The page is functionally broken, independent of any standard — a dead link or missing route, a failed asset request, a console exception, an unresolved `{{ }}`/`undefined`/`NaN` rendered to the user, a control that does nothing. Cite the observed break (status code, console message, the literal rendered string). Usually the highest-priority thing in the report. |
| **AA failure** | Cites a specific success criterion AND the page actually fails it, exceptions considered. Blocking. |
| **House standard** | Our bar, above the spec (44px targets, `rem` typography, token colors). Real, but not a conformance claim. |
| **Best practice** | Widely-recommended, not in the spec at any level (single `<h1>`, unskipped heading levels). |

**Build defect is the label most of this layer produces** — QA.links, QA.errors, QA.forms'
missing states, and QA.consistency are mostly hunting functional breakage, not conformance.
It is a separate axis from the WCAG question: a dead primary CTA is a build defect whether
or not any success criterion mentions it, and it does not become a "house standard" just
because no criterion covers it. Only **AA failure** may name a criterion as failed.

---

## QA.links — destinations resolve and behave

- Every `href` resolves. **Branch on the form of the value first** — only `http(s)` has a status code to quote, and every branch has its own pass/fail, not just the fetched one:
  - **Root-relative (`/checkout`) or relative (`products/1`)** — the most common kind on a real app page, and there is nothing to fetch. Resolve against the app's route table (Next.js `app/`/`pages/`, the router config, or the framework's manifest); if you only have a base URL, join and fetch that. A value resolving to no route is a broken internal destination — **P0 on a primary CTA**, P1 elsewhere. If neither the route table nor a base URL is available from this input, say `not auditable from this input` and name what you'd need; never let these pass silently just because they can't 404 in a fetch.
  - **`mailto:` / `tel:` / `sms:`** — no fetch, no status, but they still pass or fail. Parse the payload:
    - `mailto:` — a syntactically valid address, and a domain that looks real (not `example.com`).
    - `tel:` — a valid **RFC 3966** telephone URI. Visual separators are legal and common, so `tel:+1-201-555-0123`, `tel:+1.201.555.0123`, `tel:(201)555-0123` and a `;ext=`/`;phone-context=` parameter all **pass**. Don't apply a digits-only or strict-E.164 pattern — real, working links use the readable forms, and rejecting them is a false positive at 404 severity.
    - `sms:` — the same RFC 3966 recipient grammar, optionally followed by `?body=`.
    - Only a genuinely unusable payload fails: `mailto:not-an-address`, `tel:abc`, `tel:` with no number, an empty value.
    A failure here is a **`QA.links` build defect at the same severity as a 404**, because it is equally dead when tapped. What you must not do is report a *well-formed* one as broken merely because you couldn't fetch it — and when you're unsure whether an exotic-but-plausible form is legal, say so rather than filing it.
  - **`#fragment`** — covered by the anchor-target check below, not by fetching.
  - **`http(s)`** — fetch and quote the code. 200 passes; a 3xx needs the final destination checked; 4xx/5xx on a primary CTA is P0.
  - **Anything else** (`javascript:`, `data:`, an unknown scheme) — don't fetch it. Report what it is and let the author confirm it's intentional; `javascript:` hrefs are also a keyboard/AT smell worth noting.
- **A 401/403 is usually the audit's problem, not the page's.** Authenticated, session-bound, and geo/bot-gated destinations return them to an unauthenticated fetch while working perfectly for a signed-in member. Same for a 405 on a HEAD-only probe and a 429 from rate limiting. Report these as `not auditable from this input` with the code quoted, and say what would settle it (a signed-in check, or asking the author). Do not file a P0 against a link you couldn't legitimately reach.
- No `href="#"`, `href=""`, or placeholder URLs (`example.com`, `TODO`, `lorem`) left in.
- External links carry `target="_blank"` with `rel="noopener"` (**house standard**, not a security finding). Every evergreen browser has implied `noopener` on `target="_blank"` since 2021, so the reverse-tabnabbing hole this used to guard is closed by default — write it for explicitness and old-browser reach, and report a missing `rel` as a house-standard nit. Do **not** file it as a vulnerability. `noreferrer` is a separate, opt-in decision: it strips the `Referer` header, which can break partner attribution and analytics, so only require it where the destination shouldn't learn the origin.
- Internal links use the app's client-side routing rather than forcing a full page reload, where the framework supports it.
- Anchor targets exist — every `href="#section"` has a matching `id`.

```bash
grep -oE 'href="[^"]*"' <file> | sort -u
```

## QA.responsive — real breakpoint logic, not doc-wrapper stacking

- **The layout adapts across the range — judge the outcome, not the mechanism.** Verify behaviour at mobile ≤767px, tablet 768–1023px, and desktop ≥1024px: content reflows, nothing is clipped or overlapped, nothing needs sideways scrolling. `@media` queries are the common way to get there, but a fluid layout (`clamp()`, `minmax()`, flex/grid wrapping) or container queries can satisfy every width with **zero** `@media` rules — and flagging that as a failure is a false positive against a working page.
- Absence of `@media` is a prompt to test harder, not a finding. If the layout holds at all three ranges, it passes; if it breaks, report the observed break (the width and what broke), not the missing rule.
- Where the artifact is static and you cannot actually render it at width, say `not auditable from this input` and name what you'd need — don't infer a break from the CSS, and don't infer a pass either.
- No horizontal scroll at 320px, 375px and 768px.
- Content parity across breakpoints — mobile is not a truncated desktop. No dropped bullets, links, or pricing. Differences must be deliberate and stated.
- Images carry `max-width: 100%`. Wide content (tables, code blocks, diagrams) scrolls inside its own container rather than pushing the page.
- If the artifact is a *demonstration* (side-by-side device frames) rather than production code, it must carry an explicit breakpoint specification block so engineers have unambiguous intent. See F14.

## QA.errors — nothing broken at runtime

- No console errors or warnings on load and on primary interaction.
- No failed network requests (404s on assets, blocked mixed content, CSP violations).
- No unresolved template variables rendered to the user (`{{ }}`, `undefined`, `NaN`, `[object Object]`).
- Images have real `src` values that load; none are broken.

## QA.targets — hit areas are usable

- Interactive targets ≥ **44×44 CSS px** — WCAG 2.5.5 is AAA, so this is a **house standard**, and the practical mobile floor.
- Under 24×24 is an **AA failure under 2.5.8 only after you've ruled out its exceptions.** Check them before writing the finding, because most real undersized controls land in one:
  - **Spacing** — a 24px-diameter circle centered on the target intersects no other target's circle. Small but well-separated passes.
  - **Inline** — the target sits in a sentence, or its size is constrained by the line-height of surrounding non-target text. Body-copy links pass.
  - **Equivalent** — another control on the same page does the same job at conforming size.
  - **User agent** — the size comes from the UA and the author hasn't modified it.
  - **Essential** — the presentation is legally required or essential to the information (a map pin, an image-hotspot).
  
  Quote which exception you checked. An undersized-but-exempt target can still be a house-standard finding — just don't call it a 2.5.8 failure.
- Adjacent targets have ≥ 8px separation so a thumb can't hit two.
- Nothing interactive sits under a fixed header/footer at any breakpoint.

## QA.forms — the unhappy path is designed

- Error and invalid states defined: `.error` / `:invalid` styling, a real error-message container, `aria-invalid` and `aria-describedby` wiring the message to the failing input. Missing them is a **house standard** finding by default. It becomes an **AA failure** under 3.3.1 only where the form *automatically detects* an input error and fails to identify/describe it in text — so a static mockup with no demonstrated validation doesn't qualify; say `not auditable from this input` instead of asserting the criterion. 3.3.3 adds a suggestion requirement only when a correction is known and offering it wouldn't jeopardize security or purpose (don't demand one for a failed password or a card number). See F16.
- `aria-required` on required fields; `autocomplete` and `inputmode` set correctly (`email`, `tel`, `numeric`, `one-time-code`).
- Submit is guarded against double-fire while a request is in flight.
- Labels are real `<label for>` elements, not placeholder text doing double duty.

## QA.semantics — structure is machine-readable

- Exactly one `<main>` landmark wrapping the content; `<nav>`, `<header>`, `<footer>` used where they apply.
- Exactly one `<h1>`, and **no skipped levels in document order** (h1→h3 without h2). Both are **best practice**, not conformance minimums: WCAG nowhere requires a single `<h1>`, and W3C treats skipped ranks as advisory — a page with correctly marked-up headings satisfies 1.3.1 whether or not the ranks are contiguous. Report these as best-practice findings and do not cite 1.3.1 as failed. What *would* fail 1.3.1 is a visual heading that isn't a heading element at all (a styled `<div>` or a bolded `<p>`) — that removes structure from the accessibility tree, and it's the thing actually worth hunting here. This still fails by ORDER even when the COUNT passes. See F11.
- `aria-live` regions for status messages (confirmations, error toasts).

```bash
grep -oE "<h[1-6]" <file> | sort | uniq -c    # count
```
Then walk the headings in document order and flag any `level > last + 1`.

## QA.code — handoff-ready, not demo-ready

- Inline `style="..."` attributes < 10; styling lives in the stylesheet. See F18.
- Colors reference tokens (`var(--token)`) rather than scattered hex literals. Third-party marks (Apple/Google/PayPal) are the legitimate exception. See F19.
- Critical typography and spacing in `rem`, not `px` — **house standard**, not a 1.4.4 failure. 1.4.4 is outcome-based (text resizes to 200% without loss of content or function), and browser zoom scales CSS-pixel text just fine, so a `px` page routinely passes it. The real argument for `rem` is the one thing zoom doesn't cover: `px` ignores a user's browser font-size preference, so someone who set 20px default text still gets your 14px. Make that case; don't cite the criterion. Only file 1.4.4 when you've actually observed loss at 200% — clipped text, overlap, a control scrolled out of reach. See F15.
- No orphans after any removal — grep for stale references to removed elements, and for CSS class definitions whose HTML consumers are gone. See F13.

## QA.consistency — the artifact agrees with itself

- Rationale blocks, legends, tables of contents and annotations match the current state of the design, not a previous revision.
- Repeated components (cards, buttons, form rows) are actually consistent — same spacing, same weights, same corner radii.
- Adjacent components in a group can be told apart at a one-second glance. Two buttons at identical visual weight read as one control regardless of their labels. See F4.
- Terminology is used correctly and consistently for the moment it appears at. If a domain term's meaning is uncertain, ask rather than guess — mislabelling a state the user hasn't reached yet is a content-correctness bug, not a copy preference. See F5.

---

## What this layer is not

- **Not an automated scan.** axe-core, Lighthouse and WAVE catch programmatic issues this cannot. Run them alongside.
- **Not cross-browser testing.** Findings here are structural. Real Safari/Firefox/Chrome behavior needs real browsers.
- **Not a test suite.** This checks the artifact in front of you. It does not replace unit, integration or e2e tests.
