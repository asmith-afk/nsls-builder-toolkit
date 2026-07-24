import { test } from "node:test";
import assert from "node:assert/strict";
import { renderSubstep, safeUrl, computeAssessmentProgress, renderMarkdown } from "./render-substep.mjs";

test("safeUrl drops javascript: and other unsafe schemes, keeps safe ones", () => {
  assert.equal(safeUrl("javascript:alert(1)"), "");
  assert.equal(safeUrl("data:text/html,<x>"), "");
  assert.equal(safeUrl("/img/a.png"), "/img/a.png");
  assert.equal(safeUrl("https://x/y.png"), "https://x/y.png");
  assert.equal(safeUrl("intro.png"), "intro.png");
  assert.equal(safeUrl("data:image/png;base64,AAAA"), "data:image/png;base64,AAAA");
});

test("safeUrl strips control chars so a tab can't smuggle a javascript: scheme", () => {
  assert.equal(safeUrl("java\tscript:alert(1)"), "");
  assert.equal(safeUrl("java\nscript:alert(1)"), "");
});

test("option with a javascript: imageUrl emits no img tag", () => {
  const html = renderSubstep({ id: "x", slug: "v", title: "V", prompt: "Pick", type: "collect", fieldType: "image-multiselect",
    options: [{ text: "A", imageUrl: "javascript:alert(1)" }] }, {});
  assert.doesNotMatch(html, /javascript:/);
  assert.doesNotMatch(html, /<img/);
});

test("say/banner renders prompt + a Continue button", () => {
  const html = renderSubstep({ id: "x", title: "T", prompt: "Welcome", type: "say", fieldType: "banner" }, {});
  assert.match(html, /Welcome/);
  assert.match(html, /data-next/);
  assert.match(html, /class="[^"]*tp-btn/);
});

test("collect/text renders an input bound by data-input + data-slug", () => {
  const html = renderSubstep({ id: "x", slug: "name", title: "Name", prompt: "Your name?", type: "collect", fieldType: "text" }, {});
  assert.match(html, /data-input/);
  assert.match(html, /data-slug="name"/);
});

test("collect/multi-select renders one option button per option", () => {
  const sub = { id: "x", slug: "v", title: "V", prompt: "Pick", type: "collect", fieldType: "multi-select",
    options: [{ text: "A" }, { text: "B" }] };
  const html = renderSubstep(sub, {});
  assert.equal((html.match(/data-option/g) || []).length, 2);
});

test("dropdown-with-checkboxes with dropdownOptions and no options renders one button per dropdown option", () => {
  const sub = { id: "x", slug: "scale", title: "S", prompt: "Rate", type: "collect", fieldType: "dropdown-with-checkboxes",
    dropdownOptions: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"] };
  const html = renderSubstep(sub, {});
  assert.equal((html.match(/data-option/g) || []).length, 10);
});

test("checkboxOptions are appended after dropdownOptions", () => {
  const sub = { id: "x", slug: "scale", title: "S", prompt: "Rate", type: "collect", fieldType: "dropdown-with-checkboxes",
    dropdownOptions: ["1", "2"], checkboxOptions: ["Not sure"] };
  const html = renderSubstep(sub, {});
  assert.equal((html.match(/data-option/g) || []).length, 3);
  // checkbox option renders after the dropdown options
  assert.ok(html.indexOf('data-value="Not sure"') > html.indexOf('data-value="2"'));
});

test("optionsSourceSlug renders a data-options-source attribute on the grid", () => {
  const sub = { id: "x", slug: "narrow", title: "N", prompt: "Narrow down", type: "collect", fieldType: "multi-select",
    optionsSourceSlug: "strengths-12" };
  const html = renderSubstep(sub, {});
  assert.match(html, /data-options-source="strengths-12"/);
});

test("a substep without optionsSourceSlug renders no data-options-source attribute", () => {
  const sub = { id: "x", slug: "v", title: "V", prompt: "Pick", type: "collect", fieldType: "multi-select",
    options: [{ text: "A" }, { text: "B" }] };
  const html = renderSubstep(sub, {});
  assert.doesNotMatch(html, /data-options-source/);
});

test("generate renders the baked sample when provided", () => {
  const html = renderSubstep({ id: "x", slug: "cs", title: "CS", prompt: "Draft:", type: "generate", fieldType: "text" },
    { samples: { cs: "Your career statement draft." } });
  assert.match(html, /Your career statement draft\./);
});

test("generate without a sample renders a clearly-marked placeholder", () => {
  const html = renderSubstep({ id: "x", slug: "cs", title: "CS", prompt: "Draft:", type: "generate", fieldType: "text" }, {});
  assert.match(html, /tp-ai-placeholder/);
});

test("unknown fieldType falls back to a generic text screen (no throw)", () => {
  const html = renderSubstep({ id: "x", title: "T", prompt: "P", type: "collect", fieldType: "totally-new" }, {});
  assert.match(html, /P/);
});

test("chat renders data-chat-log, data-chat-input, data-chat-send and a seed bubble", () => {
  const html = renderSubstep({ id: "x", slug: "coach", title: "Coach", prompt: "Hello!", type: "chat", fieldType: "text" },
    { samples: { coach: "I am your coach." } });
  assert.match(html, /data-chat-log/);
  assert.match(html, /data-chat-input/);
  assert.match(html, /data-chat-send/);
  assert.match(html, /I am your coach\./);   // seed bubble present
});

test("chat without a sample still renders the interactive hooks with a fallback seed", () => {
  const html = renderSubstep({ id: "x", slug: "coach", title: "Coach", prompt: "Hello!", type: "chat", fieldType: "text" }, {});
  assert.match(html, /data-chat-log/);
  assert.match(html, /data-chat-input/);
  assert.match(html, /data-chat-send/);
});

// --- Fidelity pass: real ignite-next markup ----------------------------------

test("image-multiselect renders the real ImageMultiselectInput card classes, single-select", () => {
  const html = renderSubstep({ id: "x", slug: "q1", title: "Q", prompt: "Pick", type: "collect", fieldType: "image-multiselect",
    options: [{ text: "Plan it", imageUrl: "/img/a.png" }] }, {});
  assert.match(html, /data-multi="false"/);                    // single-select like the app
  assert.match(html, /rounded-xl overflow-hidden transition-all bg-medium/); // card
  assert.match(html, /h-48 bg-mediumPlus overflow-hidden aspect-square/);    // image section
  assert.match(html, /bg-green/);                              // selection badge (green circle)
  assert.match(html, /src="\/img\/a\.png"/);
});

test("image-multiselect with autoProgressOnSelect hides Continue and marks the grid", () => {
  const sub = { id: "x", slug: "q1", title: "Q", prompt: "P", type: "collect", fieldType: "image-multiselect",
    autoProgressOnSelect: true, options: [{ text: "A" }] };
  const html = renderSubstep(sub, {});
  assert.match(html, /data-auto-progress="true"/);
  assert.doesNotMatch(html, /data-next/);                      // app hides Continue here
});

test("image-multiselect without autoProgress keeps the sticky Continue row", () => {
  const sub = { id: "x", slug: "q1", title: "Q", prompt: "P", type: "collect", fieldType: "image-multiselect",
    options: [{ text: "A" }] };
  const html = renderSubstep(sub, {});
  assert.match(html, /data-next/);
  assert.match(html, /sticky bottom-0/);                       // app's sticky footer
});

test("collect/select renders a native <select data-input> styled like the app trigger", () => {
  const html = renderSubstep({ id: "x", slug: "age", title: "Age", prompt: "Age?", type: "collect", fieldType: "select",
    options: ["18", "19"] }, {});
  assert.match(html, /<select[^>]*data-input[^>]*data-slug="age"/);
  assert.match(html, /rounded-lg bg-medium px-4/);             // selectTriggerVariants (xl)
  assert.match(html, /<option value="18">18<\/option>/);
  assert.doesNotMatch(html, /data-option/);                    // no grid — walker uses the fill path
});

test("multi-select renders the 2-col grid with min/max status and real card classes", () => {
  const html = renderSubstep({ id: "x", slug: "vals", title: "V", prompt: "Pick", type: "collect", fieldType: "multi-select",
    multiselectMinSelections: 3, multiselectMaxSelections: 3,
    options: [{ text: "Alpha – the first" }, { text: "Beta" }] }, {});
  assert.match(html, /grid grid-cols-2/);
  assert.match(html, /Please select at least 3 options/);
  assert.match(html, /data-ms-status/);
  assert.match(html, /<span class="[^"]*font-semibold[^"]*">Alpha<\/span>/); // dash-split title
  assert.match(html, /the first/);                                           // dash-split description
});

test("say screens use the app page skeleton (substep-content + bg-light section)", () => {
  const html = renderSubstep({ id: "x", title: "T", prompt: "Welcome", type: "say", fieldType: "banner" }, {});
  assert.match(html, /id="substep-content"/);
  assert.match(html, /px-4 py-8 sm:px-8 sm:py-12 bg-light/);
  assert.match(html, /id="substep-content-inner"/);
});

test("substep imageUrl renders the app's rounded image block", () => {
  // The app only renders the image block for non-say substeps; use a collect substep here.
  const html = renderSubstep({ id: "x", title: "T", prompt: "P", type: "collect", fieldType: "text", imageUrl: "/img/intro/intro-1.png" }, {});
  assert.match(html, /society-max-h/);
  assert.match(html, /aspect-square rounded-xl overflow-hidden/);
  assert.match(html, /src="\/img\/intro\/intro-1\.png"/);
});

test("chat renders real ChatInterface rows/bubbles and keeps the contract hooks", () => {
  const html = renderSubstep({ id: "x", slug: "coach", title: "C", prompt: "Hi!", type: "chat", fieldType: "text" },
    { samples: { coach: "Seed." } });
  assert.match(html, /flex justify-start/);                     // bubble row
  assert.match(html, /tp-bubble tp-bubble-ai/);                 // walker contract class
  assert.match(html, /bg-medium text-dark hover:bg-medium\/90 rounded-tl-none!/); // app bubble classes
  assert.match(html, /border-2 border-mediumPlus bg-light rounded-lg/);           // app input box
  assert.match(html, /focus-within:border-mocha/);                                // focus state
  assert.match(html, /data-chat-send/);
  assert.match(html, /data-next/);                              // way to advance
});

test("generate renders the title pill + content card around .tp-ai-output", () => {
  const html = renderSubstep({ id: "x", slug: "cs", title: "Career Statement", prompt: "Draft:", type: "generate", fieldType: "text" },
    { samples: { cs: "Your draft." } });
  assert.match(html, /rounded-full text-sm font-medium bg-mocha text-dark/); // pill
  assert.match(html, /rounded-2xl px-6 pt-8 pb-6 -mt-5 bg-medium/);           // card
  assert.match(html, /tp-ai-output/);
  assert.match(html, /Your draft\./);
});

test("celebration: section-completion format renders Congrats + section name + Continue", () => {
  const html = renderSubstep({ id: "x", title: "Done", prompt: "", type: "say", fieldType: "celebration",
    celebrationCompletedSection: "Professional Environment", celebrationNextSection: "Interests" }, {});
  assert.match(html, /Congrats! You have completed/);
  assert.match(html, /Professional Environment/);
  assert.match(html, /Up Next: Interests/);   // app folds next section into the button label
  assert.match(html, /data-next/);
});

test("celebration with a /video/ imageUrl renders a <video> hero", () => {
  const html = renderSubstep({ id: "x", title: "Done", prompt: "Nice", type: "say", fieldType: "celebration",
    imageUrl: "/video/complete.mp4" }, {});
  assert.match(html, /<video src="\/video\/complete\.mp4"/);
  assert.match(html, /autoplay loop muted playsinline/);
});

test("dropdown-with-checkboxes renders the wheel svg + scale + checkbox rows", () => {
  const html = renderSubstep({ id: "x", slug: "dc", title: "Career Clarity Rating", prompt: "Rate.", type: "collect",
    fieldType: "dropdown-with-checkboxes", textFieldLabel: "What's unclear?",
    dropdownOptions: ["1", "2"], checkboxOptions: ["Industry"] }, {});
  assert.match(html, /tp-wheel/);
  assert.match(html, /Career Clarity/);                          // wheel label
  assert.match(html, /Very Unclear/);                            // clarity min label
  assert.equal((html.match(/data-option/g) || []).length, 3);    // 2 scale + 1 checkbox
});

test("education renders the real entry form; school field carries the data-input", () => {
  const html = renderSubstep({ id: "x", slug: "edu", title: "E", prompt: "School?", type: "collect", fieldType: "education" }, {});
  assert.match(html, /School Name/);
  assert.match(html, /Major \/ Field of Study/);
  assert.match(html, /Add Education/);
  assert.match(html, /data-input data-slug="edu"/);
  assert.match(html, /Skip \(edit in profile\)/);                // app's skip button
});

test("dream-job-select renders accordion items with data-option on header and select button", () => {
  const html = renderSubstep({ id: "x", slug: "dj", title: "DJ", prompt: "Pick", type: "collect", fieldType: "dream-job-select",
    options: [{ text: "Coach", shortDescription: "Helps people", detailedDescription: "Long detail ".repeat(12) }] }, {});
  assert.match(html, /<details/);
  assert.match(html, /Select This Job/);
  assert.equal((html.match(/data-option/g) || []).length, 2);    // summary + button (same value)
  assert.match(html, /Helps people/);
});

test("assessment-results renders the results shell with the carousel mount point", () => {
  const html = renderSubstep({ id: "x", title: "R", prompt: "", type: "say", fieldType: "assessment-results" }, {});
  assert.match(html, /Personality Assessment Results/);
  assert.match(html, /data-assessment-results/);
});

test("personality progress tracker renders when ctx.progress has this substep", () => {
  const sub = { id: "q9", slug: "q9", title: "Q", prompt: "P", type: "collect", fieldType: "image-multiselect", options: [{ text: "A" }] };
  const html = renderSubstep(sub, { progress: { q9: { section: 2, totalSections: 5, question: 3, questionsInSection: 10 } } });
  assert.match(html, /Personality Assessment/);
  assert.match(html, /Section 2 of 5/);
  assert.match(html, /Question 3 of 10/);
});

test("computeAssessmentProgress: sections split on celebrations, needs >= 40 questions", () => {
  const q = (i) => ({ id: `q${i}`, type: "collect", fieldType: "image-multiselect" });
  const cel = (i) => ({ id: `c${i}`, type: "say", fieldType: "celebration" });
  const subs40 = [...Array.from({ length: 20 }, (_, i) => q(i)), cel(1), ...Array.from({ length: 20 }, (_, i) => q(20 + i)), cel(2)];
  const p = computeAssessmentProgress(subs40);
  assert.deepEqual(p.q0, { section: 1, totalSections: 2, question: 1, questionsInSection: 20 });
  assert.deepEqual(p.q39, { section: 2, totalSections: 2, question: 20, questionsInSection: 20 });
  // below the 40-question threshold → no tracker
  assert.deepEqual(computeAssessmentProgress([q(1), q(2), cel(1)]), {});
});

test("text collect renders step-input + suggestion chips", () => {
  const html = renderSubstep({ id: "x", slug: "name", title: "N", prompt: "Name?", type: "collect", fieldType: "text",
    suggestions: ["Maya"] }, {});
  assert.match(html, /step-input w-full/);
  assert.match(html, /data-suggestion="Maya"/);
  assert.match(html, /border border-dashed border-mocha/);       // suggestion button variant (pill)
});

test("currency renders the $ prefix and pl-8 input", () => {
  const html = renderSubstep({ id: "x", slug: "sal", title: "S", prompt: "Salary?", type: "collect", fieldType: "currency" }, {});
  assert.match(html, />\$<\/div>/);
  assert.match(html, /step-input w-full pl-8/);
  assert.match(html, /inputmode="decimal"/);
});

// --- Markdown rendering for the substep PROMPT (mirrors ignite-next AIPrompt) ---
// Vendored plain-JS render module — the static transcription can't run
// react-markdown, so it ships a small dependency-free CommonMark-subset
// renderer for the substep PROMPT. These tests pin markdown rendering +
// injection safety so a future edit that drops it fails loudly.

test("renderMarkdown: heading (###) renders as <h3>, no literal ### survives", () => {
  const html = renderMarkdown("### How old are you?");
  assert.match(html, /<h3>How old are you\?<\/h3>/);
  assert.ok(!html.includes("###"));
});

test("renderMarkdown: all heading levels 1-6", () => {
  for (let n = 1; n <= 6; n++) {
    const html = renderMarkdown(`${"#".repeat(n)} Heading ${n}`);
    assert.match(html, new RegExp(`<h${n}>Heading ${n}</h${n}>`));
  }
});

test("renderMarkdown: bold via ** and __", () => {
  assert.match(renderMarkdown("**bold**"), /<strong>bold<\/strong>/);
  assert.match(renderMarkdown("__bold__"), /<strong>bold<\/strong>/);
});

test("renderMarkdown: italic via * and _", () => {
  assert.match(renderMarkdown("*x*"), /<em>x<\/em>/);
  assert.match(renderMarkdown("_x_"), /<em>x<\/em>/);
});

test("renderMarkdown: inline code", () => {
  assert.match(renderMarkdown("`c`"), /<code>c<\/code>/);
});

test("renderMarkdown: link renders target=_blank + rel=noopener noreferrer", () => {
  const html = renderMarkdown("[t](https://x.com)");
  assert.match(html, /<a href="https:\/\/x\.com" target="_blank" rel="noopener noreferrer">t<\/a>/);
});

test("renderMarkdown: link with unsafe scheme drops the href, keeps the text", () => {
  const html = renderMarkdown("[click](javascript:alert(1))");
  assert.ok(!html.includes("javascript:"));
  assert.ok(html.includes("click"));
});

test("renderMarkdown: unordered list", () => {
  const html = renderMarkdown("- a\n- b");
  assert.match(html, /<ul><li>a<\/li><li>b<\/li><\/ul>/);
});

test("renderMarkdown: ordered list", () => {
  const html = renderMarkdown("1. a\n2. b");
  assert.match(html, /<ol><li>a<\/li><li>b<\/li><\/ol>/);
});

test("renderMarkdown: blank-line-separated blocks become separate <p> tags", () => {
  const html = renderMarkdown("para one\n\npara two");
  assert.match(html, /<p>para one<\/p>/);
  assert.match(html, /<p>para two<\/p>/);
});

test("renderMarkdown: single newlines within a paragraph collapse to a space (soft break)", () => {
  const html = renderMarkdown("line one\nline two");
  assert.match(html, /<p>line one line two<\/p>/);
});

test("renderMarkdown: INJECTION — HTML in prompt is escaped, never emitted as a live tag", () => {
  const html = renderMarkdown("<img src=x onerror=alert(1)>");
  assert.ok(html.includes("&lt;img"));
  assert.ok(!html.includes("<img "));
});

test("renderMarkdown: TEMPLATE VARS — {slug} tokens survive verbatim for later interpolation", () => {
  const html = renderMarkdown("Hi {firstName}");
  assert.ok(html.includes("{firstName}"));
});

// --- inlineMd: code spans + links are extracted before emphasis -------------

test("renderMarkdown: markdown inside a code span renders VERBATIM, not as emphasis", () => {
  const html = renderMarkdown("`**not bold**`");
  assert.ok(html.includes("<code>**not bold**</code>"));
  assert.ok(!html.includes("<strong>"));
});

test("renderMarkdown: underscores inside a code span are preserved, not read as italic", () => {
  const html = renderMarkdown("`foo_bar_baz.py`");
  assert.ok(html.includes("<code>foo_bar_baz.py</code>"));
  assert.ok(!html.includes("<em>"));
});

test("renderMarkdown: markdown-looking characters in a link URL stay intact, not reinterpreted as emphasis", () => {
  const html = renderMarkdown("[t](https://x.com/**a**)");
  const hrefMatch = html.match(/href="([^"]*)"/);
  assert.ok(hrefMatch, "expected an href attribute");
  assert.equal(hrefMatch[1], "https://x.com/**a**");
  assert.ok(!html.includes("<strong>"));
  assert.match(html, /target="_blank" rel="noopener noreferrer"/);
});

test("renderMarkdown: INJECTION — quote in a link URL stays entity-encoded, no attribute breakout", () => {
  const html = renderMarkdown('[t](https://x.com/"onmouseover=alert(1))');
  const hrefMatch = html.match(/href="([^"]*)"/);
  assert.ok(hrefMatch, "expected an href attribute");
  // The href value itself must not contain a literal, un-escaped double quote —
  // that's what would let an attacker close the attribute and inject onmouseover=.
  assert.ok(!hrefMatch[1].includes('"'));
  assert.ok(html.includes("&quot;onmouseover=alert(1"));
});

test("renderMarkdown: link label containing a code span fully restores the nested placeholder", () => {
  const html = renderMarkdown("[`code`](https://example.com)");
  assert.ok(
    html.includes('<a href="https://example.com" target="_blank" rel="noopener noreferrer"><code>code</code></a>'),
    `expected fully-restored nested link+code, got: ${html}`
  );
  // A single non-recursive restore pass leaves the inner code-span token
  // (U+E000/U+E001) raw inside the already-restored link HTML.
  assert.ok(!/[\uE000\uE001]/.test(html), "no PUA sentinel chars should leak into output");
});

test("renderMarkdown: authored PUA sentinel look-alikes are stripped, not treated as real stash tokens", () => {
  // A fake "token" (OPEN + digit + CLOSE) authored directly in the source,
  // followed by a real code span. Pre-fix, this fake token survives to the
  // restore pass and is treated as a genuine stash reference — because it
  // happens to match index 0 here, it duplicates the real code span's output
  // instead of rendering as literal text.
  const fakeToken = "\uE000" + "0" + "\uE001";
  const html = renderMarkdown(`${fakeToken} \`x\``);
  assert.ok(!/[\uE000\uE001]/.test(html), "authored sentinel chars must never survive to output");
  assert.ok(!html.includes("undefined"), 'a collided/missing stash entry must never render as "undefined"');
  // Real code span still renders, and only once (no duplication from the fake token).
  const codeMatches = html.match(/<code>x<\/code>/g) || [];
  assert.equal(codeMatches.length, 1, `expected exactly one real <code>x</code>, got: ${html}`);
});

test("renderMarkdown: representative heading + link still renders correctly after hardening", () => {
  const html = renderMarkdown("### Read more\n\n[click here](https://example.com)");
  assert.match(html, /<h3>Read more<\/h3>/);
  assert.match(html, /<a href="https:\/\/example\.com" target="_blank" rel="noopener noreferrer">click here<\/a>/);
});

// --- promptBlock / renderSubstep integration --------------------------------

test("renderSubstep: prompt heading renders as HTML, not raw ###, and keeps data-tpl", () => {
  const html = renderSubstep({ id: "x", type: "say", prompt: "### How old are you?" }, {});
  assert.match(html, /<h3>How old are you\?<\/h3>/);
  assert.ok(!html.includes("###"));
  assert.match(html, /data-tpl/);
});

// --- link URLs carrying a template token: post-interpolate scheme bypass -----

test("renderMarkdown: a link whose URL is a {token} is dropped to plain text (post-interpolate scheme bypass)", () => {
  // `{answer}` passes safeUrl as a relative path, but interpolate() could later
  // swap it for `javascript:...`. Must NOT become an href.
  const html = renderMarkdown("[continue]({answer})");
  assert.ok(!html.includes("href"), "no href emitted for a token URL");
  assert.ok(!/<a\b/.test(html), "no anchor emitted for a token URL");
  assert.ok(html.includes("continue"), "link label is preserved as text");
});

test("renderMarkdown: a token anywhere in the URL is rejected (even with a safe-looking prefix)", () => {
  const html = renderMarkdown("[x](https://evil.example/{answer})");
  assert.ok(!/<a\b/.test(html) && !html.includes("href"), "token-bearing URL never becomes a link");
});

test("renderMarkdown: a normal (token-free) link still renders as an anchor", () => {
  const html = renderMarkdown("[docs](https://nsls.org/guide)");
  assert.match(html, /<a href="https:\/\/nsls\.org\/guide" target="_blank" rel="noopener noreferrer">docs<\/a>/);
});

test("renderSubstep: prompt is wrapped in the prose classes mirroring ignite-next AIPrompt", () => {
  const html = renderSubstep({ id: "x", type: "say", prompt: "Hello" }, {});
  assert.match(html, /class="prose max-w-none prose-inherit[^"]*"[^>]*data-tpl/);
});

test("renderSubstep: INJECTION via full pipeline — script/img tags in prompt never render live", () => {
  const html = renderSubstep({ id: "x", type: "say", prompt: "<img src=x onerror=alert(1)>" }, {});
  assert.ok(html.includes("&lt;img"));
  assert.ok(!html.includes("<img "));
});

test("renderSubstep: TEMPLATE VARS via full pipeline — {slug} token survives for interpolate()", () => {
  const html = renderSubstep({ id: "x", type: "say", prompt: "Hi {firstName}, welcome" }, {});
  assert.ok(html.includes("{firstName}"));
});

test("renderSubstep: banner-multiple prompt also renders markdown", () => {
  const html = renderSubstep({ id: "x", type: "say", fieldType: "banner-multiple", prompt: "**Nice work**", bannerTexts: [] }, {});
  assert.match(html, /<strong>Nice work<\/strong>/);
});
