// Render one substep to static HTML that mirrors the REAL ignite-next app.
//
// FIDELITY CONTRACT: the emitted DOM structure and class names are transcribed
// from the production components (pinned commit in prototype/SYNC.md):
//   - screen skeleton .... SubStepRenderer.tsx (layoutMode="page") + page.tsx
//   - inputs ............. src/components/fields/*.tsx
//   - buttons ............ src/components/ui/button.tsx (cva variants)
//   - chat ............... ChatInterface.tsx
//   - celebration ........ DeviceEmulator/CelebrationContent.tsx
//   - results carousel ... AssessmentResults.tsx + StackedCarousel.tsx
//   - progress tracker ... PersonalityProgressTracker.tsx
// The classes are compiled into design-kit/app.css by scripts/build-design-kit.mjs
// (real Tailwind v4 + the app's theme). Re-run that script after editing markup here.
//
// PLAYER CONTRACT (do not break): the player + walkers wire behavior via
//   [data-next] [data-input][data-slug] [data-option][data-value] grids with
//   data-multi, [data-chat]/[data-chat-log]/[data-chat-input]/[data-chat-send],
//   [data-assessment-results], .tp-ai-output/.tp-ai-placeholder,
//   [data-options-source], [data-tpl], plus marker classes .tp-screen .tp-title
//   .tp-celebration .tp-options .tp-bubble-*. Real app classes coexist with these.

import {
  CHAT_ROW_AI, CHAT_BUBBLE_AI, MS_OPTION, MS_TITLE, MS_DESC,
  MS_CHECK_WRAP, MS_CHECK_BADGE, MS_CHECK_SVG,
} from "./runtime-classes.mjs";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Prototypes deploy to public URLs, so drop any imageUrl whose scheme isn't safe
// (blocks javascript:/vbscript:/data:text). Allows http(s), protocol-relative,
// root/relative paths, and data:image/. Returns "" for anything else.
export function safeUrl(u) {
  // Strip control chars/whitespace first — browsers do this before resolving a URL, so
  // "java\tscript:" would otherwise sneak past the scheme check.
  const s = String(u ?? "").replace(/[\u0000-\u001f]/g, "").trim();
  if (s === "") return "";
  if (/^(https?:\/\/|\/\/|\/|\.\/|\.\.\/)/i.test(s)) return s;
  if (/^data:image\//i.test(s)) return s;
  if (/^[a-z][a-z0-9+.-]*:/i.test(s)) return ""; // any other explicit scheme -> drop
  return s; // bare relative filename (e.g. "intro.png")
}

// --- Markdown rendering for the substep PROMPT (mirrors ignite-next AIPrompt) --
//
// ignite-next's AIPrompt.tsx renders the prompt via react-markdown (CommonMark)
// inside a Tailwind Typography `prose` wrapper:
//   <div className="prose max-w-none prose-inherit"><Markdown>{prompt}</Markdown></div>
// and its ChatMarkdown opens links in a new tab (target="_blank" rel="noopener
// noreferrer"). This static transcription can't run react-markdown at build
// time, so it ships a small, DOCUMENTED DIVERGENCE: a dependency-free
// CommonMark-SUBSET renderer covering what authors actually put in prompts —
// headings, bold/italic, inline code, links, and simple lists.
//
// SAFETY (injection-safe by construction): the raw prompt is HTML-escaped
// FIRST via `esc`, and only THEN is markdown syntax applied to the escaped
// text. Markdown syntax characters (# * _ ` [ ] ( )) are not in esc's
// replacement set, so escaping never disturbs them — but any literal HTML in
// the prompt (e.g. `<img onerror=...>`) is neutralized (`&lt;img ...`) before
// any markdown transform runs, so it can never re-form a live tag. `{slug}`
// template tokens are untouched by both esc and the markdown patterns below,
// so they survive verbatim for the later interpolate() pass over the baked
// screen HTML (see public/preview-kit/interpolate.mjs).
//
// SUPPORTED (the subset authors use): `#`..`######` headings (line start);
// **bold**/__bold__; *italic*/_italic_; `inline code`; [text](url) links
// (dropped to plain text if safeUrl() rejects the scheme); "- "/"* " unordered
// lists; "1. " ordered lists; blank-line-separated paragraphs; single
// newlines inside a paragraph collapse to a space (CommonMark soft break).
//
// OUT OF SUBSET (intentionally — not used in authored prompts): tables,
// blockquotes, fenced code blocks, images, footnotes, nested/mixed lists,
// raw HTML passthrough, hard breaks (trailing double-space).
export function renderMarkdown(src) {
  const raw = String(src ?? "").replace(/\r\n/g, "\n").trim();
  if (!raw) return "";
  const escaped = esc(raw); // ESCAPE FIRST — the injection-safety boundary.
  const lines = escaped.split("\n");
  const out = [];
  let para = [];   // buffered soft-wrapped paragraph lines
  let list = null; // { type: "ul"|"ol", items: string[] }

  const flushPara = () => {
    if (para.length) { out.push(`<p>${inlineMd(para.join(" "))}</p>`); para = []; }
  };
  const flushList = () => {
    if (list) {
      out.push(`<${list.type}>${list.items.map((i) => `<li>${inlineMd(i)}</li>`).join("")}</${list.type}>`);
      list = null;
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed === "") { flushPara(); flushList(); continue; }

    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushPara(); flushList();
      const level = heading[1].length;
      out.push(`<h${level}>${inlineMd(heading[2].trim())}</h${level}>`);
      continue;
    }

    const ul = trimmed.match(/^[-*]\s+(.*)$/);
    if (ul) {
      flushPara();
      if (!list || list.type !== "ul") { flushList(); list = { type: "ul", items: [] }; }
      list.items.push(ul[1]);
      continue;
    }

    const ol = trimmed.match(/^\d+\.\s+(.*)$/);
    if (ol) {
      flushPara();
      if (!list || list.type !== "ol") { flushList(); list = { type: "ol", items: [] }; }
      list.items.push(ol[1]);
      continue;
    }

    flushList();
    para.push(trimmed);
  }
  flushPara();
  flushList();
  return out.join("");
}

// Inline-level transforms, applied to already-escaped text (see renderMarkdown).
//
// Genuine extract-and-restore: code spans and links are pulled out FIRST and
// replaced with placeholder tokens, so the emphasis passes below only ever
// see plain text — they can no longer reach inside a code span's content or a
// link's URL. Placeholders use U+E000/U+E001 (Private Use Area control
// points) as delimiters. Any such chars in the authored text are stripped
// up front (see inlineMd's first line) so a generated token can never
// collide with look-alike authored content or be re-authored by an
// attacker. Code-span content is restored VERBATIM (CommonMark rule:
// `` `**not bold**` `` must render as literal text, not <strong>). A link's
// visible label still gets emphasis applied to it, but its URL does not, so
// `**`/`_`/`` ` `` inside a URL can never be reinterpreted as markup.
// Restore runs in a loop (not a single pass) so a stashed link whose label
// itself contains a stashed code span -- `` [`code`](url) `` -- gets fully
// unwound rather than leaking an inner token.
function inlineMd(text) {
  const OPEN = "\uE000";
  const CLOSE = "\uE001";
  const TOKEN_RE = /\uE000(\d+)\uE001/g;

  // Strip any authored occurrences of our sentinel chars FIRST, before any
  // tokenization happens. Without this, authored text containing OPEN/CLOSE
  // followed by digits (however unlikely) could collide with a
  // later-generated token and get swapped for the wrong stash entry (or
  // "undefined" if it doesn't match any real entry) during restore. These are
  // non-printing Private-Use-Area control points with no legitimate use in
  // authored prompt text, so dropping them is harmless.
  text = text.replace(/[\uE000\uE001]/g, "");

  const stash = [];
  const stow = (html) => {
    const token = `${OPEN}${stash.length}${CLOSE}`;
    stash.push(html);
    return token;
  };
  const emphasize = (s) => s
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\b_([^_]+)_\b/g, "<em>$1</em>");

  // 1) Code spans first, restored VERBATIM later (CommonMark: content inside
  //    `` `...` `` is never itself markdown).
  let work = text.replace(/`([^`]+)`/g, (_, code) => stow(`<code>${code}</code>`));

  // 2) Links next — the label gets emphasis applied now (baked into the
  //    stashed HTML), but the URL is captured as-is and never touched by the
  //    emphasize() pass in step 3.
  work = work.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
    // Reject any URL carrying a `{token}` template placeholder. safeUrl runs
    // HERE, at render time, but a bare token like `{answer}` passes as a
    // relative path — then the later interpolate() pass swaps it for a user
    // answer that could be `javascript:...`, producing a live scheme the
    // render-time check never saw. Escaping the URL doesn't neutralize a
    // scheme, so the only safe move is to drop the link to plain text when the
    // destination is token-controlled. (Authored prompt links with a literal
    // `{}` in the URL are effectively nonexistent; the label is preserved.)
    const href = url.includes("{") ? "" : safeUrl(url);
    const labelHtml = emphasize(label);
    return stow(href ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${labelHtml}</a>` : labelHtml);
  });

  // 3) Emphasis passes run only on what's left — plain text, with code spans
  //    and links already swapped out for opaque tokens.
  work = emphasize(work);

  // 4) Restore code spans and links verbatim, last. A single pass isn't
  //    enough: a link label containing a code span (e.g. [`code`](url))
  //    stashes the code span first, then stashes the link (whose HTML
  //    contains the inner code-span token). One restore pass would replace
  //    the outer link token but leave the inner code-span token raw in the
  //    output. So restore in a loop until no tokens remain. Termination is
  //    guaranteed: every restore either replaces at least one token (shrinking
  //    the token count) or leaves the string unchanged (loop exits), and
  //    because step 0 already stripped authored sentinel chars, every token
  //    left in `work` is one WE generated and stashed — never an authored
  //    look-alike. The stash.length+1 cap is just a defensive backstop.
  let restored = work;
  for (let i = 0; i <= stash.length; i++) {
    const next = restored.replace(TOKEN_RE, (_, n) => stash[Number(n)]);
    if (next === restored) break; // no tokens left (or none matched) — stable, stop
    restored = next;
  }
  return restored;
}

// --- Icons (phosphor, inlined as the app renders them) ----------------------
const ICON_ARROW_RIGHT = '<svg width="24" height="24" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M224.49,136.49l-72,72a12,12,0,0,1-17-17L187,140H40a12,12,0,0,1,0-24H187L135.51,64.48a12,12,0,0,1,17-17l72,72A12,12,0,0,1,224.49,136.49Z"/></svg>';
const ICON_PLUS_CIRCLE = '<svg width="20" height="20" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Zm48-88a8,8,0,0,1-8,8H136v32a8,8,0,0,1-16,0V136H88a8,8,0,0,1,0-16h32V88a8,8,0,0,1,16,0v32h32A8,8,0,0,1,176,128Z"/></svg>';
const ICON_CARET_DOWN = '<svg class="h-4 w-4 opacity-50 shrink-0" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M213.66,101.66l-80,80a8,8,0,0,1-11.32,0l-80-80A8,8,0,0,1,53.66,90.34L128,164.69l74.34-74.35a8,8,0,0,1,11.32,11.32Z"/></svg>';
const ICON_CHECK_PHOSPHOR = '<svg class="w-5 h-5 overflow-hidden text-grey tp-check-inline" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M232.49,80.49l-128,128a12,12,0,0,1-17,0l-56-56a12,12,0,1,1,17-17L96,183,215.51,63.51a12,12,0,0,1,17,17Z"/></svg>';
const ICON_CHECK_BOLD_WHITE = '<svg class="w-4 h-4 text-white" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M232.49,80.49l-128,128a12,12,0,0,1-17,0l-56-56a12,12,0,1,1,17-17L96,183,215.51,63.51a12,12,0,0,1,17,17Z"/></svg>';
const ICON_INFO = '<svg class="w-4 h-4" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M128,20A108,108,0,1,0,236,128,108.12,108.12,0,0,0,128,20Zm0,192a84,84,0,1,1,84-84A84.09,84.09,0,0,1,128,212Zm12-44a12,12,0,0,1-24,0V128a12,12,0,0,1,24,0Zm-28-56a16,16,0,1,1,16,16A16,16,0,0,1,112,112Z"/></svg>';
// Send affordance inside the chat input (phosphor ArrowCircleUp).
const ICON_ARROW_CIRCLE_UP = '<svg class="h-6 w-6" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm45.66,109.66a8,8,0,0,1-11.32,0L136,107.31V168a8,8,0,0,1-16,0V107.31L93.66,133.66a8,8,0,0,1-11.32-11.32l40-40a8,8,0,0,1,11.32,0l40,40A8,8,0,0,1,173.66,133.66Z"/></svg>';
// Bold phosphor check used inside the celebration success badge (CelebrationContent's CheckIcon weight="bold").
const ICON_CHECK_CELEBRATION = '<svg class="w-7 h-7 text-white" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M232.49,80.49l-128,128a12,12,0,0,1-17,0l-56-56a12,12,0,1,1,17-17L96,183,215.51,63.51a12,12,0,0,1,17,17Z"/></svg>';

// --- Buttons — mirrors src/components/ui/button.tsx cva ---------------------
const BTN_BASE = "tp-btn inline-flex items-center gap-2 cursor-pointer whitespace-nowrap rounded-xl text-sm font-medium transition-all duration-300 ease-in-out disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-6 [&_svg]:shrink-0";
const BTN_VARIANT = {
  default: "bg-primary text-primary-foreground hover:bg-primary/90 font-cigars font-bold",
  secondary: "bg-medium text-dark hover:bg-mediumPlus/80",
  light: "bg-light text-dark hover:bg-mediumPlus/80",
  outline: "border-2 border-mocha bg-light hover:bg-mediumPlus hover:text-dark",
  dashed: "border-2 border-dashed border-mocha bg-medium hover:bg-mediumPlus hover:text-dark",
  suggestion: "border border-dashed border-mocha text-dark text-sm font-[400] rounded-full! px-4! hover:border-mocha hover:bg-mediumPlus transition-colors disabled:opacity-40 disabled:pointer-events-none",
};
const BTN_SIZE = {
  default: "h-10 px-4 py-2",
  sm: "h-9 rounded-md px-3",
  lg: "rounded-lg px-6 py-4 text-base font-bold",
  xl: "h-14 rounded-lg px-8 py-6 text-lg font-bold",
};
// Default align mirrors the cva's center default; callers pass align:"left"/"between" etc.
export function buttonClass({ variant = "default", size = "lg", align = "center", extra = "" } = {}) {
  const alignCls = align === "left" ? "justify-start" : align === "right" ? "justify-end"
    : align === "between" ? "justify-between" : "justify-center";
  return [BTN_BASE, BTN_VARIANT[variant] || BTN_VARIANT.default, BTN_SIZE[size] || BTN_SIZE.lg, alignCls, extra]
    .filter(Boolean).join(" ");
}

// The real app's primary Continue is always a between-aligned button with a
// truncating label + bold ArrowRight (SubStepContinueButton / generate / celebration).
const continueBtn = (label = "Continue", { variant = "default", size = "lg", align = "between", extra = "w-full flex items-center justify-between", arrow = true } = {}) =>
  `<button class="${buttonClass({ variant, size, align, extra })}" data-next>` +
  (arrow ? `<span class="truncate text-left">${esc(label)}</span>${ICON_ARROW_RIGHT}` : esc(label)) +
  `</button>`;

// Sticky Continue row — mirrors the collect-type footer in SubStepRenderer (page mode):
// sticky bottom, light bg, gradient fade above, centered max-width column.
function stickyContinueRow(buttonsHtml) {
  return `<div class="sticky bottom-0 left-0 right-0 z-10 shrink-0 bg-light pt-2 pb-6 space-y-3 max-w-md lg:max-w-lg mx-auto w-full">${buttonsHtml}</div>`;
}

// --- Shared blocks (page-mode skeleton from SubStepRenderer.tsx) -------------

function titleBlock(sub) {
  if (!sub.showTitle || !sub.title) return "";
  return `<div class="mb-6"><h3 class="tp-title text-xl font-cigars font-bold mb-4 max-w-md lg:max-w-lg text-pretty">${esc(sub.title)}</h3></div>`;
}

function imageBlock(sub) {
  // The app only renders the image block for non-say substeps.
  if (sub.type === "say") return "";
  const url = safeUrl(sub.imageUrl);
  if (!url) return "";
  return `<div class="society-max-h mb-6 w-full max-w-md lg:max-w-lg mx-auto aspect-square rounded-xl overflow-hidden place-content-center"><img src="${esc(url)}" alt="${esc(sub.title || "")}" class="max-w-full w-full mx-auto h-full object-cover rounded-xl"></div>`;
}

// AIPrompt static-mode classes, per the clsx in SubStepRenderer.tsx.
function promptClasses(sub) {
  const hasVisual = sub.type !== "say" && !!safeUrl(sub.imageUrl);
  let c = "mb-4 sm:mb-8 max-w-md lg:max-w-lg mx-auto text-pretty";
  if (sub.type === "say") c += " font-base text-base text-left";
  else {
    c += " text-lg leading-snug";
    if (!hasVisual) c += " text-left";
  }
  // (The app's dream-job clsx has a precedence quirk; net effect is the
  //  dream-job-requirements override — mirrored here.)
  if (sub.fieldType === "dream-job-requirements") c += " text-left text-base! font-medium";
  if (sub.fieldType === "image-multiselect") c += " text-left text-lg md:text-xl font-bold";
  if (sub.fieldType === "multi-select") c += " text-left font-normal text-base!";
  if (sub.fieldType === "dropdown-with-checkboxes" || sub.fieldType === "wheel") c += " text-center!";
  return c;
}

function promptBlock(sub) {
  if (sub.fieldType === "banner-multiple") {
    // bannerTexts are separate plain-text lines (not the markdown-bearing
    // `prompt` field) — left esc-only + whitespace-pre-wrap, untouched.
    const lines = (sub.bannerTexts || []).map((t, i) =>
      `<div class="tp-banner-line text-base font-medium whitespace-pre-wrap transition-all duration-500 ease-in-out" style="animation-delay:${(i + 1) * 800}ms" data-tpl>${esc(t)}</div>`).join("");
    return `<div class="mb-6 space-y-2 sm:space-y-4 max-w-md lg:max-w-lg mx-auto"><div class="text-base font-medium prose max-w-none prose-inherit transition-all duration-500 ease-in-out" data-tpl>${renderMarkdown(sub.prompt)}</div>${lines}</div>`;
  }
  if (!sub.prompt) return "";
  // Prose wrapper mirrors ignite-next's AIPrompt.tsx; whitespace-pre-wrap is
  // dropped because renderMarkdown's <p>/<h*>/<ul> tags now govern block
  // spacing (prose supplies the vertical rhythm the app gets from Tailwind
  // Typography).
  return `<div class="prose max-w-none prose-inherit ${promptClasses(sub)}" data-tpl>${renderMarkdown(sub.prompt)}</div>`;
}

function calloutBlock(sub) {
  if (!sub.callout) return "";
  return `<div class="max-w-md lg:max-w-lg mx-auto"><div class="mb-6 p-4 bg-mocha/20 rounded-lg"><div class="text-sm text-dark prose prose-sm max-w-none" data-tpl>${esc(sub.callout)}</div></div></div>`;
}

// --- Field inputs (src/components/fields/*) ----------------------------------

function optionText(o, idx) {
  return typeof o === "string" ? o : (o.text || o.label || `Option ${idx + 1}`);
}

// step-input text field — TextFieldInput.tsx: a resizable <textarea> inside a
// rounded medium wrapper, with a horizontally-scrolling row of suggestion pills.
function textField(sub, slug) {
  const suggestions = (sub.suggestions || []).length
    ? `<div class="relative -mx-1"><div class="flex gap-2 overflow-x-auto pb-1 px-1 scrollbar-hide">${sub.suggestions.map((s) =>
        `<button type="button" class="${buttonClass({ variant: "suggestion", size: "sm", extra: "shrink-0" })}" data-suggestion="${esc(s)}">${esc(s)}</button>`).join("")}</div></div>`
    : "";
  return `${suggestions}<div class="relative bg-medium rounded-lg focus-within:bg-medium/90 transition-all duration-300 ease-in-out"><textarea rows="3" class="step-input w-full resize-none bg-transparent!" data-input data-slug="${slug}" placeholder="Type your answer"></textarea></div>`;
}

// CurrencyFieldInput.tsx
function currencyField(sub, slug) {
  const label = sub.textFieldLabel
    ? `<div class="flex items-center gap-2"><label class="block text-sm font-medium text-dark">${esc(sub.textFieldLabel)}</label></div>`
    : "";
  return `<div class="space-y-2">${label}<div class="relative"><div class="absolute left-4 top-1/2 -translate-y-1/2 text-grey font-medium text-base pointer-events-none select-none">$</div><input type="text" inputmode="decimal" class="step-input w-full pl-8" data-input data-slug="${slug}" placeholder="0" aria-label="${esc(sub.textFieldLabel || "Dollar amount")}"></div></div>`;
}

// SelectFieldInput.tsx — the app uses a Radix dropdown; the static mirror is a
// native <select> styled with the same selectTriggerVariants(xl) classes.
// It carries data-input (captureCurrent reads .value) instead of an option grid.
const SELECT_TRIGGER_XL = "flex w-full items-center justify-between rounded-lg bg-medium px-4 text-left focus:outline-mocha h-14 py-3 text-base";
function selectField(sub, slug) {
  const opts = (sub.options || []).map((o, i) => {
    const t = optionText(o, i);
    return `<option value="${esc(t)}">${esc(t)}</option>`;
  }).join("");
  return `<div class="relative tp-select-wrap"><select class="tp-select appearance-none ${SELECT_TRIGGER_XL} text-dark" data-input data-slug="${slug}"><option value="" disabled selected>Select an option</option>${opts}</select><span class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">${ICON_CARET_DOWN}</span></div>`;
}

// MultiselectFieldInput.tsx — checkbox rows. Selected state via aria-selected
// (proto.css maps it to border-mediumPlus bg-mediumPlus/50 + visible check).
function checkboxRow(value, idx, { name } = {}) {
  return `<button type="button" class="tp-row group flex w-full items-center gap-2 cursor-pointer p-2.5 rounded-xl border-2 border-medium hover:border-mocha hover:bg-mediumPlus bg-transparent text-left text-dark text-base" data-option data-value="${esc(value)}" data-index="${idx}"${name ? ` data-name="${esc(name)}"` : ""}>${ICON_CHECK_PHOSPHOR}<span>${esc(value)}</span></button>`;
}

function multiCheckboxField(sub, slug) {
  const rows = (sub.options || []).map((o, i) => checkboxRow(optionText(o, i), i)).join("");
  return `<div class="tp-options space-y-3" data-slug="${slug}" data-multi="true">${rows}</div>`;
}

// RadioFieldInput.tsx
function radioField(sub, slug) {
  const rows = (sub.options || []).map((o, i) => {
    const t = optionText(o, i);
    return `<button type="button" class="tp-radio-row flex w-full items-center gap-3 cursor-pointer bg-transparent border-0 p-0 text-left" data-option data-value="${esc(t)}" data-index="${i}"><span class="tp-radio w-5 h-5 rounded-full border-2 border-gray-300 shrink-0"></span><span class="text-dark">${esc(t)}</span></button>`;
  }).join("");
  return `<div class="tp-options space-y-3" data-slug="${slug}" data-multi="false">${rows}</div>`;
}

// MultiSelectInput.tsx — 2-col grid of selectable cards (+min/max status line).
// Title – Description splitting mirrors splitDashText().
function splitDashText(text) {
  const m = String(text).match(/^(.+?) [–—-] (.+)$/);
  return m ? { title: m[1], desc: m[2] } : { title: text, desc: undefined };
}

export function msOptionButton(option, idx) {
  const value = optionText(option, idx);
  let title, desc;
  if (typeof option === "object" && option.description) {
    title = value; desc = option.description;
  } else {
    ({ title, desc } = splitDashText(value));
  }
  const img = typeof option === "object" ? safeUrl(option.imageUrl) : "";
  const imgHtml = img
    ? `<div class="w-full h-20 mb-2 rounded-lg overflow-hidden bg-gray-100"><img src="${esc(img)}" alt="${esc(title)}" class="w-full h-full object-cover"></div>`
    : "";
  const descHtml = desc ? `<span class="${MS_DESC}">${esc(desc)}</span>` : "";
  return `<button type="button" class="${MS_OPTION}" style="min-height:120px" data-option data-value="${esc(value)}" data-index="${idx}">${imgHtml}<div class="flex flex-col items-start w-full"><span class="${MS_TITLE}">${esc(title)}</span>${descHtml}</div><div class="${MS_CHECK_WRAP}"><div class="${MS_CHECK_BADGE}">${MS_CHECK_SVG}</div></div></button>`;
}

function multiSelectField(sub, slug) {
  const min = sub.multiselectMinSelections;
  const max = sub.multiselectMaxSelections;
  let status = "";
  if (min != null || max != null) {
    const msg = min != null ? `Please select at least ${min} option${min !== 1 ? "s" : ""}`
      : `Please select at most ${max} option${max !== 1 ? "s" : ""}`;
    const range = min != null && max != null
      ? `Selected: <span data-ms-count>0</span> / ${min === max ? max : `${min}-${max}`} required`
      : min != null ? `Selected: <span data-ms-count>0</span> / Minimum: ${min}`
      : `Selected: <span data-ms-count>0</span> / Maximum: ${max}`;
    status = `<div class="pb-4 text-center ring-2 ring-light z-10 bg-light text-dark" data-ms-status data-min="${min ?? ""}" data-max="${max ?? ""}"><p class="text-sm font-medium" data-ms-msg>${msg}</p><p class="text-xs mt-1">${range}</p></div>`;
  }
  const source = sub.optionsSourceSlug ? ` data-options-source="${esc(sub.optionsSourceSlug)}"` : "";
  const buttons = (sub.options || []).map((o, i) => msOptionButton(o, i)).join("");
  return `<div class="space-y-4">${status}<div class="tp-options grid grid-cols-2 md:grid-cols-2 gap-3" data-slug="${slug}" data-multi="true"${source}>${buttons}</div></div>`;
}

// ImageMultiselectInput.tsx — SINGLE-select cards with image + success badge.
// autoProgressOnSelect hides the Continue row; the player advances ~300ms after pick.
function imageMultiselectField(sub, slug) {
  const auto = sub.autoProgressOnSelect ? ` data-auto-progress="true"` : "";
  const source = sub.optionsSourceSlug ? ` data-options-source="${esc(sub.optionsSourceSlug)}"` : "";
  const cards = (sub.options || []).map((o, i) => {
    const t = optionText(o, i);
    const img = typeof o === "object" ? safeUrl(o.imageUrl) : "";
    const imgHtml = img
      ? `<div class="flex-1 shrink-0 w-auto h-48 bg-mediumPlus overflow-hidden aspect-square max-h-[24dvh]"><img src="${esc(img)}" alt="${esc(t)}" class="w-full h-full object-cover aspect-square"></div>`
      : "";
    return `<button type="button" class="tp-im cursor-pointer relative flex flex-row md:flex-row mx-auto w-full items-stretch p-0 rounded-xl overflow-hidden transition-all bg-medium" data-option data-value="${esc(t)}" data-index="${i}">${imgHtml}<div class="flex-1 px-4 md:px-6 py-4 text-left flex items-center"><span class="text-base font-medium leading-relaxed">${esc(t)}</span></div><div class="${MS_CHECK_WRAP.replace("top-2 right-2", "top-3 right-3")}"><div class="w-6 h-6 rounded-full bg-green flex items-center justify-center shadow-lg">${ICON_CHECK_BOLD_WHITE}</div></div></button>`;
  }).join("");
  return `<div class="tp-options space-y-4 my-6" data-slug="${slug}" data-multi="false"${auto}${source}>${cards}</div>`;
}

// WheelWithCheckboxesInput.tsx — ProfileWheel + rating + reason checkboxes.
// The wheel is rendered as a STATIC svg (4 wedges, active category highlighted);
// the interactive slider is approximated by a 0-10 pill scale (the player treats
// the pills as options). Documented divergence — see SYNC.md.
const WHEEL_CATEGORIES = ["Personal Network", "Professional Network", "Career Clarity", "Job Acquisition Confidence"];
function wheelSvg(activeIndex, activeSecondary) {
  const cx = 150, cy = 150, r = 110;
  const wedge = (i, fill) => {
    const a0 = (-90 + i * 90) * Math.PI / 180, a1 = (-90 + (i + 1) * 90) * Math.PI / 180;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    return `<path d="M${cx},${cy} L${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)} Z" fill="${fill}" stroke="var(--color-light,#fff7f1)" stroke-width="3"/>`;
  };
  const wedges = WHEEL_CATEGORIES.map((_, i) =>
    wedge(i, i === activeIndex ? activeSecondary : "var(--color-medium,#f2e8e0)")).join("");
  const labelPos = [[225, 38], [225, 262], [75, 262], [75, 38]]; // NE SE SW NW quadrant labels
  const labels = WHEEL_CATEGORIES.map((name, i) =>
    `<div class="tp-wheel-label" style="left:${labelPos[i][0]}px;top:${labelPos[i][1]}px"><p class="text-xs font-medium text-dark">${esc(name)}</p></div>`).join("");
  return `<div class="tp-wheel relative mx-auto" style="width:300px;height:300px">` +
    `<svg width="300" height="300" style="position:absolute;top:0;left:0">${wedges}</svg>${labels}</div>`;
}

// showCheckboxes lets the standalone WheelInput (fieldType "wheel" — the
// slider half of the combined pair, see SubStepRenderer.tsx) reuse this same
// renderer without its reason-checkbox block. Default true preserves
// dropdown-with-checkboxes exactly (byte-identical — existing tests cover
// it). Passing false is stronger than just omitting checkboxOptions: a wheel
// substep is never supposed to show reason checkboxes, so this forces that
// even if the data happens to carry a stray checkboxOptions array.
// `multi` controls the wrapper's data-multi, which player.js reads as
// `dataset.multi === "true"` to decide whether a click toggles an option or
// replaces the current selection. `dropdown-with-checkboxes` is genuinely
// multi-select; a standalone `wheel` is a single 0-10 rating and must be false,
// or a member can select 3 AND 7 and both persist.
//
// It stays PRESENT-but-false rather than omitted: captureCurrent() locates the
// grid with `[data-slug][data-multi]`, which matches on attribute presence, so
// removing it would stop the answer being captured at all.
function wheelWithCheckboxesField(sub, slug, { showCheckboxes = true, multi = true } = {}) {
  const isClarity = String(sub.title || "").toLowerCase().includes("clarity");
  const isConfidence = String(sub.title || "").toLowerCase().includes("confidence");
  const activeIndex = isClarity ? 2 : isConfidence ? 3 : 2;
  // Active wedge highlight — mirror the app's warm accent (pink token #f3aee6).
  const secondary = "#f3aee6";
  const minLabel = isClarity ? "Very Unclear" : isConfidence ? "Very Low" : "0";
  const maxLabel = isClarity ? "Crystal Clear" : isConfidence ? "Very High" : "10";

  const scale = (sub.dropdownOptions || []).map((v, i) =>
    `<button type="button" class="tp-scale-opt w-9 h-9 rounded-full border-2 border-medium bg-medium/25 hover:border-mocha flex items-center justify-center text-sm font-semibold text-dark cursor-pointer transition-all" data-option data-value="${esc(v)}" data-index="${i}">${esc(v)}</button>`).join("");
  const scaleBlock = scale
    ? `<div class="max-w-sm mx-auto"><div class="flex justify-between pointer-events-none mb-2"><span class="text-sm text-mocha">${esc(minLabel)}</span><span class="text-sm text-mocha">${esc(maxLabel)}</span></div><div class="flex flex-wrap justify-center gap-1.5">${scale}</div></div>`
    : "";
  const label = sub.textFieldLabel
    ? `<div><p class="text-lg font-medium text-center">${esc(sub.textFieldLabel)}</p></div>`
    : "";
  const checks = showCheckboxes
    ? (sub.checkboxOptions || []).map((o, i) => checkboxRow(String(o), (sub.dropdownOptions || []).length + i)).join("")
    : "";
  const checksBlock = checks
    ? `<div class="space-y-2 grid grid-cols-1 gap-0.5 max-w-md mx-auto mb-8">${checks}</div>`
    : "";
  return `<div class="space-y-4 tp-options" data-slug="${slug}" data-multi="${multi}">${wheelSvg(activeIndex, secondary)}${scaleBlock}${label}${checksBlock}</div>`;
}

// MultiSelectListInput.tsx — checkbox rows sourced from checkboxOptions (the
// standalone half of the combined pair, split out so the wheel and the
// checkbox list can live on separate substeps — see wheelWithCheckboxesField
// above and SubStepRenderer.tsx). freeResponseEnabled adds a write-in row.
// The real component stores a JSON blob ({checkboxes, freeResponseSelected,
// freeResponse}) for the free-text answer; the static player's capture only
// reads aria-selected values off [data-option], so the free-text VALUE isn't
// captured here — documented divergence, same class as the AI-generate
// placeholder. The row still renders so a focus-group participant sees the
// real affordance instead of it silently vanishing.
function multiSelectListField(sub, slug) {
  const opts = sub.checkboxOptions || [];
  const rows = opts.map((o, i) => checkboxRow(String(o), i)).join("");
  // The "Other" checkbox toggle is captured via data-option like any other row
  // (its value is just the literal label string), but the typed text in the
  // input below it was never captured at all — no data-input/data-slug, so a
  // participant's written-in answer silently vanished. Reuse the entry-form
  // contract (data-entry-form="<slug>" on the container + data-subfield on the
  // field, see entryFormField/#48) rather than inventing a new capture shape:
  // captureCurrent() already scans for exactly this and stores it as
  // "<slug>.other", alongside the checkbox selections under the bare "<slug>"
  // key. Only added when the row itself exists — no entry-form container
  // when there's no subfield to capture.
  const otherRow = sub.freeResponseEnabled
    ? checkboxRow(sub.freeResponseLabel || "Other (please specify)", opts.length) +
      `<div class="px-2.5 pt-1"><input type="text" class="step-input w-full" placeholder="Type your response..." data-subfield="other" aria-label="${esc(sub.freeResponseLabel || "Other response")}"></div>`
    : "";
  const entryForm = sub.freeResponseEnabled ? ` data-entry-form="${slug}"` : "";
  return `<div class="tp-options space-y-3" data-slug="${slug}" data-multi="true"${entryForm}>${rows}${otherRow}</div>`;
}

// resume-upload — the real component EXISTS and does considerably more than a
// file input. `OnboardingResumeUploadSubstep` looks the member up on LinkedIn
// (via the crustdata router), offers the candidate profiles it found
// ("We found N jobs…"), and parses an uploaded resume; the capability manifest
// lists resume-upload under BOTH `declared` and `rendered`.
//
// This comment used to say "no ignite-next component exists for this fieldType
// yet". That was true when #51 shipped the stub and is not true now, and the
// stale version is why walkthroughs of the Welcome track were read as showing
// the real screen: a reviewer saw a grey file input, had no reason to doubt it,
// and concluded the LinkedIn flow simply wasn't in the track.
//
// A static prototype still cannot host any of it — no backend to receive the
// file, no LinkedIn lookup — so a stub remains correct. What was wrong is that
// the stub did not SAY it was a stub. It now discloses, following the
// .tp-ai-placeholder precedent used for generate screens with no baked sample:
// the player already tells a viewer when it is showing a stand-in rather than
// the real thing, and this is the same situation.
function resumeUploadField(sub) {
  const label = sub.textFieldLabel || "Upload your resume";
  return `<div class="space-y-2"><label class="block text-sm font-medium text-dark">${esc(label)}</label><input type="file" class="step-input w-full" accept=".pdf,.doc,.docx"><div class="tp-stub-note text-xs text-grey pt-1">Stand-in for the real screen: members are looked up on LinkedIn and can pick a found profile, or upload a resume to be parsed. Not reproducible in a static prototype.</div></div>`;
}

// Education / Work entry forms — SubStepRenderer EducationInput/WorkInput.
// The first field carries data-input (what the player captures); the rest of
// the form is faithful chrome.
function entryFormField(sub, slug, kind) {
  const field = (labelText, placeholder, attrs = "") =>
    `<div><label class="block text-sm font-medium mb-2">${esc(labelText)}</label><input type="text" class="w-full step-input" placeholder="${esc(placeholder)}"${attrs}></div>`;
  if (kind === "education") {
    return `<div class="space-y-6"><div class="space-y-4 max-w-md lg:max-w-lg mx-auto">` +
      field("School Name", "e.g., MIT", ` data-input data-slug="${slug}"`) +
      field("Major / Field of Study", "e.g., Computer Science") +
      `<div class="grid grid-cols-2 gap-4"><div><label class="block text-sm font-medium mb-2">School Type</label><div class="relative tp-select-wrap"><select class="tp-select appearance-none w-full step-input"><option value="" disabled selected>Select an option</option><option>Undergraduate</option><option>Graduate</option><option>Certificate</option><option>Other</option></select><span class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2">${ICON_CARET_DOWN}</span></div></div>` +
      field("Graduation Year", "2026") + `</div>` +
      `<button type="button" class="${buttonClass({ variant: "secondary", size: "xl", extra: "w-full mb-4" })}">${ICON_PLUS_CIRCLE}Add Education</button></div></div>`;
  }
  return `<div class="space-y-6"><div class="space-y-4">` +
    field("Company Name", "e.g., Google", ` data-input data-slug="${slug}"`) +
    field("Role / Job Title", "e.g., Software Engineer") +
    field("Years of Experience", "e.g., 2") +
    `<button type="button" class="${buttonClass({ variant: "secondary", size: "xl", extra: "w-full mb-4" })}">${ICON_PLUS_CIRCLE}<span>Add Work Experience</span></button></div></div>`;
}

// DreamJobSelectInput.tsx — accordion (native <details>), select via the header
// or the inner button (both carry data-option; selecting on header tap is a
// documented divergence — Radix accordions need React).
function dreamJobOptionFields(o, idx) {
  if (typeof o === "string") return { text: o, short: undefined, detail: undefined };
  const text = o.text || o.label || o.title || `Option ${idx + 1}`;
  const short = o.shortDescription || (o.description && !o.detailedDescription && o.description.length < 100 ? o.description : undefined);
  const detail = o.detailedDescription || (o.description && o.description.length >= 100 ? o.description : undefined);
  return { text, short, detail };
}

function dreamJobSelectField(sub, slug) {
  const items = (sub.options || []).map((o, i) => {
    const { text, short, detail } = dreamJobOptionFields(o, i);
    return `<details class="tp-acc w-full border-2 rounded-xl overflow-hidden transition-all border-medium bg-medium/25 hover:border-mocha">` +
      `<summary class="w-full px-4 py-4 text-left flex items-start justify-between gap-3 bg-transparent hover:bg-medium/50 transition-colors text-dark font-medium cursor-pointer list-none" data-option data-value="${esc(text)}" data-index="${i}">` +
      `<div class="flex-1 text-left min-w-0"><div class="flex items-center gap-2"><span class="font-semibold text-base">${esc(text)}</span><div class="tp-check w-5 h-5 rounded-full bg-dark flex items-center justify-center flex-shrink-0">${MS_CHECK_SVG}</div></div>` +
      (short ? `<div class="text-sm text-dark/70 font-normal mt-1.5 leading-relaxed">${esc(short)}</div>` : "") +
      `</div></summary>` +
      `<div class="px-4 py-0"><div class="pt-2 pb-4 border-t border-medium/50">` +
      (detail ? `<div class="prose prose-sm max-w-none text-dark"><p class="mb-3 last:mb-0 leading-relaxed">${esc(detail)}</p></div>`
        : `<p class="text-sm text-dark/60 italic">No detailed description available.</p>`) +
      `<button type="button" class="${buttonClass({ size: "lg", extra: "mt-4 w-full" })}" data-option data-value="${esc(text)}" data-index="${i}">Select This Job</button>` +
      `</div></div></details>`;
  }).join("");
  return `<div class="tp-options space-y-3" data-slug="${slug}" data-multi="false">${items}</div>`;
}

// DreamJobRequirementsInput.tsx — read-only numbered accordion + info banner.
function dreamJobRequirementsField(sub) {
  const banner = `<div class="p-3 bg-dark/10 rounded-xl text-sm text-dark"><div class="flex items-start gap-2"><span class="text-dark mt-0.5">${ICON_INFO}</span><div><p class="font-semibold">Review Your Career Requirements</p><p class="text-dark mt-1">Expand each section to see the typical requirements for your dream job. This information will be saved when you continue.</p></div></div></div>`;
  const items = (sub.options || []).map((o, i) => {
    const raw = typeof o === "object" ? { ...o, text: o.title || o.text || o.label } : o;
    const { text, short, detail } = dreamJobOptionFields(raw, i);
    return `<details class="tp-acc w-full border-2 rounded-xl overflow-hidden transition-all border-medium bg-medium/25 hover:border-mocha">` +
      `<summary class="w-full px-4 py-4 text-left flex items-start justify-between gap-3 bg-transparent hover:bg-medium/50 transition-colors text-dark font-medium cursor-pointer list-none">` +
      `<div class="flex-1 text-left min-w-0"><div class="flex items-center gap-2"><span class="w-6 h-6 rounded-full bg-dark/10 flex items-center justify-center text-xs font-semibold text-dark/70 flex-shrink-0">${i + 1}</span><span class="font-semibold text-base">${esc(text)}</span></div>` +
      (short ? `<div class="text-sm text-dark/70 font-normal mt-1.5 ml-8 leading-relaxed">${esc(short)}</div>` : "") +
      `</div></summary>` +
      `<div class="px-4 py-0"><div class="pt-2 pb-4 border-t border-medium/50 ml-8">` +
      (detail ? `<div class="prose prose-sm max-w-none text-dark"><p class="mb-3 last:mb-0 leading-relaxed">${esc(detail)}</p></div>`
        : `<p class="text-sm text-dark/60 italic">No detailed information available.</p>`) +
      `</div></div></details>`;
  }).join("");
  return `<div class="space-y-4">${banner}<div class="space-y-3">${items}</div></div>`;
}

// SelectWithCustomTimeInput.tsx — a single-choice list where one authored
// option is literally the string "Custom time" (the Self-Leadership
// morning-nudge-timing / evening-nudge-timing substeps encode it in `options`
// — see tracks-export.json). The real component is a Radix <Select> that
// conditionally reveals a native time <input> via React state once "Custom
// time" is picked. The static player has no such runtime, so — same
// documented-divergence class as other faithful-chrome fields — the time
// input is always rendered below the option list rather than toggled, and
// both are captured through the SAME contracts every sibling
// option-list/entry-form renderer already uses:
//   - data-slug + data-multi="false" + data-option (radioField's shape) for
//     the picked option, so player.js's existing generic [data-option] click
//     handler and captureCurrent() grid-read work with zero player.js changes.
//   - data-entry-form + data-subfield="customTime" (the entry-form shape) for
//     the typed time, so captureCurrent() stores it as "<slug>.customTime"
//     alongside the chosen option under the bare "<slug>" key.
// Fixes issue #51's 4th instance: this fieldType previously had no case in
// renderCollect and fell through to the plain "Type your answer" text box.
function selectWithCustomTimeField(sub, slug) {
  const rows = (sub.options || []).map((o, i) => {
    const t = optionText(o, i);
    return `<button type="button" class="tp-radio-row flex w-full items-center gap-3 cursor-pointer bg-transparent border-0 p-0 text-left" data-option data-value="${esc(t)}" data-index="${i}"><span class="tp-radio w-5 h-5 rounded-full border-2 border-gray-300 shrink-0"></span><span class="text-dark">${esc(t)}</span></button>`;
  }).join("");
  const timeRow = `<div class="px-2.5 pt-1"><input type="time" class="step-input w-full" data-subfield="customTime" aria-label="Custom time"></div>`;
  return `<div class="tp-options space-y-3" data-slug="${slug}" data-multi="false" data-entry-form="${slug}">${rows}${timeRow}</div>`;
}

// --- Collect assembly --------------------------------------------------------

function renderCollect(sub) {
  const slug = esc(sub.slug || "");
  let input;
  switch (sub.fieldType) {
    case "currency": input = currencyField(sub, slug); break;
    case "select": input = selectField(sub, slug); break;
    case "multi-checkbox": input = multiCheckboxField(sub, slug); break;
    case "multi-select": input = multiSelectField(sub, slug); break;
    case "radio": input = radioField(sub, slug); break;
    case "image-multiselect": input = imageMultiselectField(sub, slug); break;
    case "dropdown-with-checkboxes": input = wheelWithCheckboxesField(sub, slug); break;
    case "wheel": input = wheelWithCheckboxesField(sub, slug, { showCheckboxes: false, multi: false }); break;
    case "multi-select-list": input = multiSelectListField(sub, slug); break;
    case "resume-upload": input = resumeUploadField(sub); break;
    case "education": input = entryFormField(sub, slug, "education"); break;
    case "work": input = entryFormField(sub, slug, "work"); break;
    case "dream-job-select": input = dreamJobSelectField(sub, slug); break;
    case "dream-job-requirements": input = dreamJobRequirementsField(sub); break;
    case "select-with-custom-time": input = selectWithCustomTimeField(sub, slug); break;
    default: input = textField(sub, slug); // text / textarea / unknown
  }

  // Continue/Skip footer — hidden when image-multiselect auto-progresses (app parity).
  const autoProgress = sub.fieldType === "image-multiselect" && (sub.autoProgressOnSelect ?? false);
  let footer = "";
  if (!autoProgress) {
    const isEntryForm = sub.fieldType === "education" || sub.fieldType === "work";
    if (isEntryForm) {
      // Continue + Skip share one row (the entry-form footer). The sticky wrapper
      // is a stacked column, so nest the pair in their own flex row to keep parity.
      const cont = continueBtn("Continue", { align: "left", extra: "flex-1" });
      const skip = `<button class="${buttonClass({ variant: "secondary", size: "lg", extra: "flex-1" })}" data-next>Skip (edit in profile)</button>`;
      footer = stickyContinueRow(`<div class="flex gap-3">${cont}${skip}</div>`);
    } else {
      footer = stickyContinueRow(continueBtn("Continue"));
    }
  }
  return `<div class="space-y-4 max-w-md lg:max-w-lg mx-auto">${input}${footer}</div>`;
}

// --- Celebration (CelebrationContent.tsx) ------------------------------------

const CONFETTI_COLORS = ["#f2da4e", "#969bde", "#f3aee6", "#9bd778", "#8eaf86", "#c8beaa"];
function confettiHtml() {
  const bits = Array.from({ length: 14 }, (_, i) =>
    `<span class="tp-confetti-bit" style="--c:${CONFETTI_COLORS[i % CONFETTI_COLORS.length]};--dx:${(i % 7 - 3) * 34}px;--dr:${(i * 67) % 360}deg;animation-delay:${i * 45}ms"></span>`).join("");
  return `<div class="tp-confetti w-full flex justify-center" data-confetti aria-hidden="true">${bits}</div>`;
}

function renderCelebration(sub) {
  const isSection = !!sub.celebrationCompletedSection;
  const desc = sub.callout || sub.prompt || "";
  const head = isSection
    ? `<div class="text-center mb-2"><p class="text-sm text-pretty text-dark">Congrats! You have completed</p></div>` +
      `<div class="text-center mb-6"><h2 class="text-2xl font-cigars font-bold text-dark" data-tpl>${esc(sub.celebrationCompletedSection)}</h2></div>`
    : (desc ? `<div class="text-center mb-4"><p class="text-sm text-pretty text-dark" data-tpl>${esc(desc)}</p></div>` : "");

  const confetti = (sub.celebrationShowConfetti ?? true) ? confettiHtml() : "";

  const heroUrl = safeUrl(sub.imageUrl);
  let hero = "";
  if (heroUrl) {
    const isVideo = /\.(mp4|webm|ogg)$/i.test(heroUrl) || heroUrl.includes("/video/");
    const media = isVideo
      ? `<video src="${esc(heroUrl)}" autoplay loop muted playsinline class="w-full h-full object-cover"></video>`
      : `<img src="${esc(heroUrl)}" alt="Celebration" class="absolute inset-0 w-full h-full object-cover">`;
    // Badge: green circle centered at the bottom edge, overlapping the image (CelebrationContent.tsx).
    hero = `<div class="relative w-full mb-8"><div class="relative w-full aspect-4/3 rounded-lg bg-medium overflow-hidden">${media}</div><div class="absolute -bottom-8 left-1/2 -translate-x-1/2 w-16 h-16 bg-green border-6 border-light rounded-full flex items-center justify-center">${ICON_CHECK_CELEBRATION}</div></div>`;
  }

  let card = "";
  if (!isSection) {
    const tasks = (sub.celebrationTasks || []).map((t) =>
      `<li class="tp-task flex items-start gap-2"><span class="text-base leading-tight">✅</span><span class="text-sm text-dark leading-tight" data-tpl>${esc(t)}</span></li>`).join("");
    const title = sub.celebrationNextStepsTitle ? `<h3 class="text-lg font-semibold text-dark mb-1">${esc(sub.celebrationNextStepsTitle)}</h3>` : "";
    const sub2 = sub.celebrationNextStepsDescription ? `<p class="text-sm text-dark mb-3" data-tpl>${esc(sub.celebrationNextStepsDescription)}</p>` : "";
    if (title || sub2 || tasks) card = `<div class="w-full rounded-xl p-4">${title}${sub2}${tasks ? `<ul class="tp-tasks space-y-2">${tasks}</ul>` : ""}</div>`;
  }

  // The app folds "next section" into the button label ("Up Next: …") rather than a separate line.
  const label = isSection
    ? (sub.celebrationNextSection ? `Up Next: ${sub.celebrationNextSection}` : "Continue")
    : (sub.celebrationButtonText || "Okay, got it!");
  return `<div class="tp-celebration flex-1 flex flex-col h-full bg-light">` +
    `<div class="flex-1 overflow-y-auto px-4 pb-4 flex flex-col justify-center"><div class="flex flex-col items-center max-w-md lg:max-w-lg mx-auto">${head}${confetti}${hero}${card}</div></div>` +
    `<div class="px-4 pb-6 pt-2"><div class="flex flex-col gap-3 w-full max-w-md lg:max-w-lg mx-auto">${continueBtn(label, { extra: "w-full flex items-center justify-between", arrow: true })}</div></div></div>`;
}

// --- Generate (SubStepRenderer generate branch) -------------------------------

function renderGenerate(sub, ctx) {
  const sample = ctx.samples && ctx.samples[sub.slug];
  const title = sub.showTitle === true && sub.title
    ? `<h3 class="tp-title text-xl font-cigars font-bold mb-4 max-w-md lg:max-w-lg text-pretty">${esc(sub.title)}</h3>` : "";
  const prompt = sub.prompt
    ? `<div class="text-dark prose max-w-none"><p data-tpl>${esc(sub.prompt)}</p></div>` : "";
  const pill = `<div class="flex justify-center mb-0"><div class="capitalize px-5 py-2 rounded-full text-sm font-medium bg-mocha text-dark shadow-sm">${esc(sub.title || "Career Statement")}</div></div>`;
  const body = sample
    ? `<div class="tp-ai-output prose prose-sm max-w-none pt-2 whitespace-pre-wrap [&>p]:mb-4 [&>p]:last:mb-0 [&>p]:leading-relaxed">${esc(sample)}</div>`
    : `<div class="tp-ai-placeholder prose prose-sm max-w-none pt-2 whitespace-pre-wrap">AI would write this from your answers. (No sample baked in.)</div>`;
  const card = `<div class="mt-4"><div class="relative">${pill}<div class="rounded-2xl px-6 pt-8 pb-6 -mt-5 bg-medium">${body}</div></div></div>`;
  return `<div class="tp-generate h-full relative flex flex-col bg-light text-dark">` +
    `<div class="flex-1 overflow-y-auto p-4 pb-6">${title}${prompt}${card}${calloutBlock(sub)}</div>` +
    `<div class="px-4 mb-6">${continueBtn("Continue", { extra: "w-full flex items-center justify-between", arrow: true })}</div></div>`;
}

// --- Chat (ChatInterface.tsx) --------------------------------------------------

function renderChat(sub, ctx) {
  const slug = esc(sub.slug || "");
  const sample = (ctx.samples && ctx.samples[sub.slug]) || "Tell me what's on your mind.";
  const bubble = (content) =>
    `<div class="${CHAT_ROW_AI}"><div class="${CHAT_BUBBLE_AI}"><div class="prose max-w-none prose-inherit [&>p]:mb-2 [&>p]:last:mb-0 **:text-inherit" data-tpl>${esc(content)}</div></div></div>`;
  // Input: bordered box (focus-within recolors the border) with the send button
  // tucked at bottom-right — mirrors ChatInterface.tsx's form.
  const inputBox =
    `<div class="border-2 border-mediumPlus bg-light rounded-lg overflow-hidden transition-all duration-300 ease-in-out focus-within:border-mocha focus-within:bg-medium/50">` +
    `<textarea rows="1" class="w-full block resize-none overflow-y-auto bg-transparent outline-none px-4 py-4 text-base placeholder-grey" data-chat-input placeholder="Type your response..."></textarea>` +
    `<div class="flex justify-end px-4 pb-3"><button class="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-full" data-chat-send aria-label="Send message">${ICON_ARROW_CIRCLE_UP}</button></div>` +
    `</div>`;
  return `<div class="tp-chat h-full flex flex-col bg-light text-dark relative" data-chat data-slug="${slug}">` +
    `<div class="tp-chat-log flex-1 overflow-y-auto space-y-4 pt-4 max-w-md lg:max-w-xl mx-auto w-full" data-chat-log>${bubble(sub.prompt)}${bubble(sample)}</div>` +
    `<div class="shrink-0 py-4 sticky bottom-0 bg-light max-w-md lg:max-w-xl mx-auto w-full">` +
    inputBox +
    `<div class="flex justify-end mt-3"><button class="${buttonClass({ variant: "secondary", size: "sm", extra: "w-fit" })}" data-next>Finish Chat &amp; Continue</button></div>` +
    `</div></div>`;
}

// --- Assessment results (AssessmentResultsField + AssessmentResults) ----------

function renderAssessmentResults(sub) {
  // The player computes the real personality scores on render from
  // window.__ASSESSMENT__ + the user's answers, then builds the stacked
  // carousel inside [data-assessment-results]. Inner text is a fallback only.
  // Honor an authored prompt on the substep (data-tpl so {tokens} interpolate).
  const promptHtml = sub && sub.prompt ? `<p class="text-center text-mocha mb-3" data-tpl>${esc(sub.prompt)}</p>` : "";
  return `<div class="tp-results flex flex-col h-full max-w-md lg:max-w-lg mx-auto">` +
    `<div class="flex-1"><h4 class="text-lg text-center font-bold">Personality Assessment Results</h4>${promptHtml}` +
    `<div data-assessment-results>Computing your results…</div></div>` +
    `<div class="flex gap-3 px-4 pb-4">${continueBtn("Continue", { extra: "w-full" })}</div></div>`;
}

// --- Personality progress tracker (PersonalityProgressTracker.tsx fallback) ---

// Pure: compute per-substep section/question progress for one step's substeps.
// Mirrors the component's fallback: questions = collect/image-multiselect, needs
// >= 40 of them; sections bounded by say/celebration substeps.
export function computeAssessmentProgress(substeps) {
  const out = {};
  const questions = (substeps || []).filter((s) => s.fieldType === "image-multiselect" && s.type === "collect");
  if (questions.length < 40) return out;

  const boundaries = [];
  let current = [];
  let start = 0;
  let num = 1;
  for (const s of substeps) {
    if (questions.some((q) => q.id === s.id)) current.push(s);
    if (s.fieldType === "celebration" && s.type === "say" && current.length > 0) {
      boundaries.push({ start, end: start + current.length, number: num, count: current.length });
      start += current.length; num++; current = [];
    }
  }
  if (current.length > 0) boundaries.push({ start, end: start + current.length, number: num, count: current.length });

  const total = boundaries.length;
  questions.forEach((q, qi) => {
    const sec = boundaries.find((b) => qi >= b.start && qi < b.end) || boundaries[0];
    out[q.id] = { section: sec.number, totalSections: total, question: qi - sec.start + 1, questionsInSection: sec.count };
  });
  return out;
}

function progressTrackerBlock(sub, ctx) {
  const p = ctx.progress && ctx.progress[sub.id];
  if (!p) return "";
  return `<div class="fixed top-30 left-0 right-0 w-full max-w-md lg:max-w-lg mx-auto px-6 sm:px-0 z-10"><p class="border-b border-medium pb-1 text-mocha text-sm mb-1">Personality Assessment</p></div>` +
    `<div class="fixed bottom-6 left-0 right-0 w-full max-w-md lg:max-w-lg mx-auto px-6 sm:px-0 justify-between text-xs font-medium text-mocha z-10"><p class="border-t border-medium pb-1 flex items-end justify-between"><span class="mt-1">Section ${p.section} of ${p.totalSections}</span><span class="mt-1">Question ${p.question} of ${p.questionsInSection}</span></p></div>`;
}

// --- Top-level ----------------------------------------------------------------

export function renderSubstep(sub, ctx = {}) {
  const open = `<section class="tp-screen px-4 py-8 sm:px-8 sm:py-12 bg-light relative" id="substep-content" data-substep="${esc(sub.id)}">`;
  const close = `</section>`;

  // Full-screen substep types (the app early-returns these before page layout)
  if (sub.fieldType === "assessment-results") return open + renderAssessmentResults(sub) + close;
  if (sub.type === "chat") return open + renderChat(sub, ctx) + close;
  if (sub.type === "generate") return open + renderGenerate(sub, ctx) + close;
  if (sub.fieldType === "celebration") return open + renderCelebration(sub) + close;

  const tracker = sub.fieldType === "image-multiselect" && sub.type === "collect"
    ? progressTrackerBlock(sub, ctx) : "";

  const inner = `<div id="substep-content-inner">` +
    titleBlock(sub) + imageBlock(sub) + promptBlock(sub) + calloutBlock(sub) +
    (sub.type === "collect" ? renderCollect(sub) : "") +
    `</div>`;

  const sayFooter = (sub.type === "say" || sub.fieldType === "banner-multiple")
    ? `<div class="flex justify-start max-w-md lg:max-w-lg mx-auto">${continueBtn("Continue", { extra: "w-full" })}</div>`
    : "";

  return open + tracker + inner + sayFooter + close;
}
