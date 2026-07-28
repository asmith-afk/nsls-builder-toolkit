#!/usr/bin/env node
/**
 * lookup-grounding.mjs — authoring-time preview of REAL grounding figures.
 *
 * When designing a value moment, run this to see the actual careers + BLS median
 * wages a major grounds against, so the candidate's `grounding` + `example_output`
 * use real numbers — not model-guesses. This reads the SAME baked snapshot the
 * runtime injects (`track-studio/data/grounding-snapshot.json`), so what you
 * preview here is what a member gets.
 *
 * Usage:
 *   node lookup-grounding.mjs "Marketing"            # figures for a major
 *   node lookup-grounding.mjs --list                 # majors currently covered
 *   node lookup-grounding.mjs "Marketing" --json     # structured output
 *   node lookup-grounding.mjs "Marketing" --snapshot /path/to/grounding-snapshot.json
 *
 * Snapshot resolution order: --snapshot → $GROUNDING_SNAPSHOT → a live
 * ~/code/track-studio checkout → the copy BUNDLED with this skill
 * (data/grounding-snapshot.json). track-studio's ingest is the source of record;
 * the bundled copy is refreshed from it (re-copy after re-ingesting), so the
 * lookup works in any toolkit checkout without track-studio present.
 */
import { readFileSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

const argv = process.argv.slice(2);
const flag = (f) => { const i = argv.indexOf(f); return i !== -1 ? argv[i + 1] : undefined; };
const has = (f) => argv.includes(f);
// The positional major must skip any token consumed as a flag VALUE (the arg
// right after any --flag), so `--state CA Marketing` picks "Marketing", not "CA".
const flagValueIdx = new Set(argv.map((a, i) => (a.startsWith("--") ? i + 1 : -1)));
const major = argv.find((a, i) => !a.startsWith("--") && !flagValueIdx.has(i));

function findSnapshot() {
  // An EXPLICIT --snapshot must exist — don't silently fall back to a different
  // (possibly stale) snapshot on a typo.
  const explicit = flag("--snapshot");
  if (explicit) return existsSync(explicit) ? explicit : { error: explicit };
  const candidates = [
    process.env.GROUNDING_SNAPSHOT,
    // A live track-studio checkout (freshest if the author maintains it)…
    join(homedir(), "code/track-studio/data/grounding-snapshot.json"),
    // …else the copy bundled with this skill, so the lookup always resolves.
    join(HERE, "..", "data", "grounding-snapshot.json"),
  ].filter(Boolean);
  return candidates.find((p) => existsSync(p)) || null;
}

const found = findSnapshot();
if (found && typeof found === "object") {
  console.error(`--snapshot path not found: ${found.error}. Fix the path or omit --snapshot to use the default.`);
  process.exit(1);
}
const path = found;
if (!path) {
  console.log(
    "No grounding snapshot found. Looked at: --snapshot, $GROUNDING_SNAPSHOT, " +
    "~/code/track-studio/data/grounding-snapshot.json.\n" +
    "Point at it with --snapshot <path>, or (re)build it: " +
    "`python3.12 scripts/ingest-grounding.py` in the track-studio repo.\n" +
    "Without it, keep the value moment qualitative (model-reasoned) — do NOT invent numbers.",
  );
  process.exit(0);
}

const snap = JSON.parse(readFileSync(path, "utf-8"));
const norm = (s) => (s ?? "").trim().toLowerCase().replace(/\.$/, "");
const primary = (t) => norm(String(t).split(/[/,;:]/)[0]);

// Minimal location → 2-letter state resolver, for --state (state-specific wages).
const STATES = { alabama:"AL",alaska:"AK",arizona:"AZ",arkansas:"AR",california:"CA",colorado:"CO",connecticut:"CT",delaware:"DE","district of columbia":"DC",florida:"FL",georgia:"GA",hawaii:"HI",idaho:"ID",illinois:"IL",indiana:"IN",iowa:"IA",kansas:"KS",kentucky:"KY",louisiana:"LA",maine:"ME",maryland:"MD",massachusetts:"MA",michigan:"MI",minnesota:"MN",mississippi:"MS",missouri:"MO",montana:"MT",nebraska:"NE",nevada:"NV","new hampshire":"NH","new jersey":"NJ","new mexico":"NM","new york":"NY","north carolina":"NC","north dakota":"ND",ohio:"OH",oklahoma:"OK",oregon:"OR",pennsylvania:"PA","rhode island":"RI","south carolina":"SC","south dakota":"SD",tennessee:"TN",texas:"TX",utah:"UT",vermont:"VT",virginia:"VA",washington:"WA","west virginia":"WV",wisconsin:"WI",wyoming:"WY","puerto rico":"PR" };
const ABBRS = new Set(Object.values(STATES));
function resolveState(loc) {
  const s = norm(loc);
  if (!s) return null;
  if (s.length === 2 && ABBRS.has(s.toUpperCase())) return s.toUpperCase();
  return STATES[s] || null;
}
const stateArg = flag("--state");
const st = resolveState(stateArg);
const stName = st ? Object.keys(STATES).find((n) => STATES[n] === st).replace(/\b\w/g, (c) => c.toUpperCase()) : null;

// Resolve free-text major → CIP (mirrors track-studio lib/grounding matchMajor):
// exact title → head-name tier → whole-word primary term → whole-word title.
// Returns { cip, confidence, alternatives }.
//
// MUST MIRROR track-studio `lib/grounding.ts` matchMajorDetailed(). This file is
// the authoring preview for the runtime injector, so a divergence here means an
// author designs a value moment around figures members will never see (or worse,
// different ones). track-studio is the source of record; both read the same
// snapshot, so identical logic gives identical answers.
//
// The previous version used bare `.includes()` and reported only exact/loose,
// which is how "Communications" matched "…Telecommunications" and previewed
// Information Security Analyst wages for a comms member.
const DOMINANCE_RATIO = 5;                     // top must lead the runner-up by this much
const PLACEHOLDER_SOC = "99-9999";             // ingest's "no crosswalk row" sentinel
const isPlaceholder = (c) => c.soc === PLACEHOLDER_SOC || /^NO MATCH/i.test(c.title ?? "");
const isCatchAll = (t) => /,\s*other\.?\s*$/i.test(t ?? "");
const isGeneral = (t) => /,\s*general\.?\s*$/i.test(t ?? "");
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const containsWord = (hay, needle) => new RegExp(`\\b${escapeRe(needle)}\\b`).test(hay);

function matchMajor(want) {
  want = norm(want);
  const none = { cip: null, confidence: "none", alternatives: [] };
  if (!want) return none;
  const entries = Object.entries(snap.majors);
  const rank = (list) => list.slice().sort((a, b) =>
    (b[1].popularity ?? 0) - (a[1].popularity ?? 0)          // most-awarded first (IPEDS)
    || (isCatchAll(a[1].title) ? 1 : 0) - (isCatchAll(b[1].title) ? 1 : 0)
    || (/general/i.test(a[1].title) ? 0 : 1) - (/general/i.test(b[1].title) ? 0 : 1)
    || a[1].title.length - b[1].title.length);

  const exactTitle = entries.find(([, m]) => norm(m.title) === want);
  if (exactTitle) return { cip: exactTitle[0], confidence: "exact", alternatives: [] };

  // Programs that HEAD-NAME the field, rather than specialize or apply it.
  // Excludes catch-alls, or "Business Administration" locks onto 52.0299
  // ("…, Other.", placeholder-only) instead of 52.0201 (332k grads, real wages).
  const anchored = (t) => containsWord(norm(t), want) && norm(t).startsWith(want);
  let cands = rank(entries.filter(([, m]) =>
    !isCatchAll(m.title) && (primary(m.title) === want || (isGeneral(m.title) && anchored(m.title)))));
  if (!cands.length) cands = rank(entries.filter(([, m]) => containsWord(primary(m.title), want)));
  if (!cands.length) cands = rank(entries.filter(([, m]) => containsWord(norm(m.title), want)));
  if (!cands.length) return none;

  const [top, runnerUp] = cands;
  const topPop = top[1].popularity ?? 0;
  const nextPop = runnerUp?.[1].popularity ?? 0;
  const dominant = !runnerUp
    || (topPop > 0 && topPop >= DOMINANCE_RATIO * nextPop)
    || (topPop === 0 && nextPop === 0 && primary(top[1].title) === want && !isCatchAll(top[1].title));

  return {
    cip: top[0],
    confidence: dominant ? "strong" : "weak",
    alternatives: cands.slice(1, 5).map(([cip, m]) => `${m.title} [${cip}]`),
  };
}

if (has("--list")) {
  const count = Object.keys(snap.majors).length;
  console.log(`Snapshot covers ${count} CIP majors (full catalog). Vintage: ${snap.vintage?.oews ?? "n/a"}.`);
  console.log(`Just look one up by name — free-text matching resolves it, e.g.:  node lookup-grounding.mjs "Marketing"`);
  const filter = flag("--list");
  if (filter) {
    const hits = Object.entries(snap.majors)
      .filter(([, m]) => m.title.toLowerCase().includes(filter.toLowerCase()))
      .slice(0, 40).map(([cip, m]) => `  ${m.title}  [${cip}]`);
    console.log(hits.length ? `\nTitles containing "${filter}":\n${hits.join("\n")}` : `\nNo titles contain "${filter}".`);
  }
  process.exit(0);
}

if (!major) {
  console.log('Pass a major, e.g.  node lookup-grounding.mjs "Marketing"   (or --list)');
  process.exit(0);
}

const m = matchMajor(major);
const hit = m.cip ? { cip: m.cip, ...snap.majors[m.cip] } : null;
if (!hit) {
  console.log(
    `No CIP match for "${major}" in the snapshot (${Object.keys(snap.majors).length} majors). ` +
    "Try a broader term, or run --list to browse. For a genuinely uncovered major, keep the " +
    "nugget qualitative (model-reasoned) — never fabricate a number.",
  );
  process.exit(0);
}

// The confidence gate — MUST match track-studio's `ground()`, which refuses to
// attach wages below "strong". Below the bar the runtime returns an EMPTY payload,
// so previewing figures here would show an author numbers members never see.
// A loose match is worse than no match: it produces a confidently wrong figure
// with a BLS citation attached.
if (m.confidence === "weak") {
  const jsonMode = has("--json");
  if (jsonMode) {
    console.log(JSON.stringify({ cip: null, major: null, confidence: m.confidence,
      groundable: false, closest: `${hit.title} [${hit.cip}]`, alternatives: m.alternatives }, null, 2));
    process.exit(0);
  }
  console.log(
    `"${major}" is AMBIGUOUS — the runtime will return NO figures for it.\n\n` +
    `Several programs match and none clearly dominates, so grounding is skipped rather than guessed.\n` +
    `  closest:      ${hit.title} [${hit.cip}]\n` +
    (m.alternatives.length ? `  also match:   ${m.alternatives.join("\n                ")}\n` : "") +
    `\nTo ground this value moment, use an EXACT catalogue title above (every one of the ` +
    `${Object.keys(snap.majors).length} titles resolves exactly), or browse with --list "${major}".\n` +
    `Otherwise keep the nugget qualitative — model-reasoned, no invented numbers.`,
  );
  process.exit(0);
}

// Drop the ingest's placeholder rows BEFORE anything else: "NO MATCH (SOC 99-9999)"
// is not an occupation, and the runtime never emits it.
const realCareers = hit.careers.filter((c) => !isPlaceholder(c));
if (!realCareers.length) {
  console.log(
    `"${hit.title}" (CIP ${hit.cip}) has NO crosswalked occupations in the snapshot — ` +
    `the runtime returns an empty payload, so this major cannot be grounded.\n` +
    `194 of ${Object.keys(snap.majors).length} majors are in this state (mostly "…, Other." catch-all codes).\n` +
    `Keep the nugget qualitative (model-reasoned) — never fabricate a number.`,
  );
  process.exit(0);
}

// Apply the state median wage (if --state resolved) ONCE, so JSON and human
// output agree. Careers keep national when no state figure exists.
const careersOut = realCareers.map((c) => {
  const sw = st ? snap.stateWages?.[c.soc]?.[st] : undefined;
  return sw != null
    ? { ...c, medianWageAnnual: sw, wageArea: stName }
    : { ...c, wageArea: c.wageArea ?? (c.medianWageAnnual != null ? "National" : null) };
});

if (has("--json")) {
  console.log(JSON.stringify({ cip: hit.cip, major: hit.title, state: st, confidence: m.confidence,
    groundable: true, careers: careersOut, vintage: snap.vintage, attribution: snap.attribution }, null, 2));
  process.exit(0);
}

console.log(`REAL grounding data for "${hit.title}" (CIP ${hit.cip}) — use these figures verbatim:\n`);
if (m.confidence === "strong" && m.alternatives.length) {
  console.log(`(Resolved "${major}" to the dominant program in its field. If you meant another, re-run with the exact title or CIP. Other matches: ${m.alternatives.join(", ")})\n`);
}
if (stateArg && !st) console.log(`(--state "${stateArg}" not recognized; showing national wages)\n`);
for (const c of careersOut) {
  const wage = c.medianWageAnnual != null
    ? `${c.wageArea && c.wageArea !== "National" ? c.wageArea + " median" : "national median"} $${c.medianWageAnnual.toLocaleString()} (${c.wageYear || snap.vintage?.oews || ""})`
    : "wage not available — describe qualitatively";
  const growth = c.growthPct != null ? `, projected ${c.growthPct}% growth` : "";
  console.log(`  • ${c.title} (SOC ${c.soc}): ${wage}${growth}`);
}
console.log(`\nVintage: ${snap.vintage?.oews ?? "n/a"}  |  Growth: ${snap.vintage?.growth ?? "not yet ingested"}`);
console.log(`Attribution (carry into the doc): ${snap.attribution.join(" ")}`);
console.log(
  "\nUse ONLY these figures in the nugget's example_output. Anything not listed → " +
  "describe qualitatively, invent no number (the faithfulness rule).",
);
