// Validates an ignite-next importable track JSON array against the schema
// contract and the ontology token-ordering rule.
// Usage (CLI): node validate-track-json.mjs <path-to-tracks.json> [--assume slugA,slugB] [--assume-clarity]

const VALID_TYPES = new Set(["say", "collect", "generate", "chat", "ai-process"]);

/** The three arrays an author can put an option list in. Each fieldType reads at most
 *  one of them; the others are silently discarded (track-studio#60). */
const OPTION_ARRAYS = ["options", "checkboxOptions", "dropdownOptions"];

/** Celebration fields that a SIBLING field silently switches off (track-studio#41).
 *
 *  CelebrationContent.tsx renders two mutually exclusive layouts, chosen by
 *  `isSectionCompletion = !!completedSection`. Setting `celebrationCompletedSection`
 *  selects the section-completion layout, which gates out the entire next-steps card —
 *  and that card is the ONLY renderer for nextStepsTitle, nextStepsDescription and
 *  celebrationTasks. Separately, the button reads
 *  `effectiveNextSection ? "Up Next: <section>" : buttonText`, so once
 *  `celebrationNextSection` is set, `celebrationButtonText` is never consulted.
 *
 *  So the reported symptom ("copy renders that no JSON supplies, so it must be a
 *  hardcoded default") had a different cause: the fields ARE wired, and one authoring
 *  choice makes five others unreachable. Read off the component, not assumed. */
const CELEBRATION_SUPPRESSIONS = [
  {
    when: "celebrationCompletedSection",
    suppresses: [
      "celebrationNextStepsTitle",
      "celebrationNextStepsDescription",
      "celebrationTasks",
    ],
    because:
      "selects the section-completion layout, which does not render the next-steps card",
  },
  {
    when: "celebrationNextSection",
    suppresses: ["celebrationButtonText"],
    because: 'makes the button read "Up Next: <celebrationNextSection>"',
  },
];
// Fallback ONLY for when no capability manifest is available. The manifest
// (generated from ignite-next) is the source of truth; this list is known to go
// stale — it once omitted wheel/multi-select-list/resume-upload while all three
// were live in production.
const FALLBACK_FIELD_TYPES = new Set([
  "text", "textarea", "select", "multi-select", "image-multiselect",
  "dropdown-with-checkboxes", "currency", "education", "work", "banner",
  "banner-multiple", "celebration", "assessment-results", "dream-job-select",
  "dream-job-requirements", "",
]);
// Fields the seed manages positionally / automatically — must NOT appear in import JSON.
const AUTO_FIELDS = new Set([
  "order", "version", "isDraft", "isActive", "trackId", "stepId",
  "trackGroupId", "createdAt", "updatedAt"
]);
// Profile slugs produced by the Clarity track (available if Clarity is a prerequisite).
export const CLARITY_TOKENS = [
  "name", "age", "gender", "location", "education", "work-experience",
  "direction-clarity", "job-acquisition-confidence", "your-personality-profile",
  "strengths-selection", "inspirations-selection", "work-environment-result",
  "living-environment-result", "value-selection-3", "monthly-target",
  "annual-target", "dream-job-selection", "dream-job-requirements",
  "career-statement", "major"
];

const TOKEN_RE = /\{([a-z0-9][a-z0-9-]*)\}/g;

function slugify(s) {
  return String(s).toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

// Recursively collect every string value in an object/array.
function collectStrings(value, out) {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) for (const v of value) collectStrings(v, out);
  else if (value && typeof value === "object") for (const v of Object.values(value)) collectStrings(v, out);
  return out;
}

function tokensIn(substep) {
  // Exclude structural id/slug fields from token scanning.
  const { id, slug, ...rest } = substep;
  const strings = collectStrings(rest, []);
  const found = new Set();
  for (const s of strings) {
    for (const m of s.matchAll(TOKEN_RE)) found.add(m[1]);
  }
  return found;
}

export function validateTracks(tracks, opts = {}) {
  const errors = [];
  const warnings = [];
  const assumed = new Set([
    ...(opts.assume || []),
    ...(opts.assumeClarity ? CLARITY_TOKENS : [])
  ]);

  if (!Array.isArray(tracks)) {
    errors.push("Top level must be an array of track objects.");
    return { errors, warnings };
  }

  const allIds = new Map(); // id -> location label
  const seen = (id, label) => {
    if (allIds.has(id)) errors.push(`Duplicate id "${id}" (at ${label} and ${allIds.get(id)}).`);
    else allIds.set(id, label);
  };

  // Flat, ordered list of substeps to enforce token ordering.
  const orderedSubsteps = []; // { sub, slug, label }

  for (const [ti, track] of tracks.entries()) {
    const tlabel = `track[${ti}]`;
    if (!track || typeof track !== "object") { errors.push(`${tlabel} is not an object.`); continue; }
    if (!track.id) errors.push(`${tlabel} missing required "id".`);
    else seen(track.id, tlabel);
    if (!track.title) errors.push(`${tlabel} missing required "title".`);
    if (!Array.isArray(track.steps)) { errors.push(`${tlabel} missing required "steps" array.`); }
    for (const f of Object.keys(track)) if (AUTO_FIELDS.has(f)) errors.push(`${tlabel} has auto-managed field "${f}" — remove it (seed sets it).`);

    const stepSlugs = new Set();
    for (const [si, step] of (track.steps || []).entries()) {
      const slabel = `${tlabel}.step[${si}]`;
      if (!step || typeof step !== "object") { errors.push(`${slabel} is not an object.`); continue; }
      if (!step.id) errors.push(`${slabel} missing required "id".`); else seen(step.id, slabel);
      if (!step.title) errors.push(`${slabel} missing required "title".`);
      if (!Array.isArray(step.substeps)) errors.push(`${slabel} missing required "substeps" array.`);
      for (const f of Object.keys(step)) if (AUTO_FIELDS.has(f)) errors.push(`${slabel} has auto-managed field "${f}" — remove it.`);
      const sSlug = step.slug || slugify(step.title || "");
      if (sSlug) { if (stepSlugs.has(sSlug)) errors.push(`${slabel} duplicate slug "${sSlug}" within track.`); else stepSlugs.add(sSlug); }

      const subSlugs = new Set();
      for (const [bi, sub] of (step.substeps || []).entries()) {
        const blabel = `${slabel}.substep[${bi}] (id=${sub && sub.id})`;
        if (!sub || typeof sub !== "object") { errors.push(`${blabel} is not an object.`); continue; }
        for (const req of ["id", "title", "type"]) {
          if (sub[req] === undefined || sub[req] === null || sub[req] === "") errors.push(`${blabel} missing required "${req}".`);
        }
        // prompt is a non-nullable DB String, and "" is legitimate on say/celebration
        // substeps — their copy lives in other fields. It is NOT legitimate on a
        // `generate` substep: an empty prompt gives the AI nothing to work from and the
        // member sees the literal "New sub step — edit me in the editor panel"
        // placeholder. A null-only check let that through, which is the symptom reported
        // in track-studio#49.
        //
        // This one TRIMS on purpose, and must keep trimming — do not "unify" it with the
        // celebration `populated` helper below, which deliberately does not. The two ask
        // different questions. Here: "is there usable content for the model?", and a
        // whitespace-only prompt gives it nothing, so "   " is an error. There: "does the
        // renderer treat this field as set?", and the renderer's raw truthiness makes
        // "   " very much set. Making either match the other reintroduces a real bug.
        if (sub.prompt === undefined || sub.prompt === null) errors.push(`${blabel} missing required "prompt".`);
        else if (sub.type === "generate" && String(sub.prompt).trim() === "")
          errors.push(`${blabel} has an empty "prompt" — a generate substep needs one, or the member sees the editor placeholder.`);
        if (sub.id) seen(sub.id, blabel);
        if (sub.type && !VALID_TYPES.has(sub.type)) errors.push(`${blabel} invalid type "${sub.type}" (allowed: ${[...VALID_TYPES].join(", ")}).`);
        const ft = sub.fieldType;
        if (ft !== undefined && ft !== null && ft !== "") {
          const caps = opts.capabilities;
          if (caps) {
            const { declared, rendered } = caps.fieldTypes;
            if (rendered.includes(ft)) {
              /* supported */
            } else if (declared.includes(ft)) {
              errors.push(
                `${blabel} fieldType "${ft}" is declared but has no render path in ignite-next — ` +
                  `it will fall back to a plain text box for the member.`,
              );
            } else {
              errors.push(`${blabel} unknown fieldType "${ft}".`);
            }
          } else if (!FALLBACK_FIELD_TYPES.has(ft)) {
            warnings.push(`${blabel} unknown fieldType "${ft}".`);
          }
        }
        // Option-array ambiguity (track-studio#60). A substep has THREE places to put a
        // list — options / checkboxOptions / dropdownOptions — and each fieldType reads
        // exactly one of them (or none). Nothing at author time said which, so 18 CIP
        // majors went into `options` on a `multi-select-list`, which reads
        // `checkboxOptions`: the member was shown a career-needs list instead of majors,
        // and the draft still scored 16/16 because a synthetic panel reads design intent
        // rather than the rendered widget.
        const populatedOptionArrays = OPTION_ARRAYS.filter(
          (k) => Array.isArray(sub[k]) && sub[k].length > 0,
        );
        // Rule 1 — needs no knowledge of the app: whichever array is read, the others are
        // discarded. Measured against live content, no substep populates two, so this does
        // not fire on any existing authoring pattern.
        if (populatedOptionArrays.length > 1) {
          warnings.push(
            `${blabel} populates more than one option array (${populatedOptionArrays.join(", ")}) — ` +
              `a fieldType reads only one, so the rest are silently discarded. Keep the list in a single array.`,
          );
        }
        // Rule 2 — precise, and only when the capability manifest says which array this
        // fieldType reads. That is an ignite-next fact (SubStepRenderer.tsx); hard-coding it
        // here would recreate the duplicated truth the manifest exists to remove, so absent
        // the map this says nothing rather than guessing (ignite-next#985).
        const optionSource = opts.capabilities?.fieldTypes?.optionSource;
        if (optionSource && ft) {
          const reads = optionSource[ft];
          for (const k of populatedOptionArrays) {
            if (reads === undefined) continue; // manifest has no opinion on this fieldType
            if (k !== reads) {
              warnings.push(
                reads === null
                  ? `${blabel} populates "${k}", but fieldType "${ft}" reads no option array at all — it will be discarded.`
                  : `${blabel} populates "${k}", but fieldType "${ft}" reads "${reads}" — "${k}" is never read. Move the list.`,
              );
            }
          }
        }
        // Celebration fields suppressed by a sibling field (track-studio#41). Same class
        // as the option-array rules above — an author populates a field and the member
        // never sees it — but the cause is a layout branch rather than a fieldType
        // accessor, so it needs no capability manifest: both suppressions are visible in
        // CelebrationContent.tsx and hold for every fieldType that renders it.
        if (ft === "celebration") {
          // "Did the author set this" must mirror the RENDERER's own test for that field's
          // shape — per shape, because CelebrationContent does not use one test for all of
          // them:
          //   completedSection    `!!completedSection`            → raw truthiness
          //   nextStepsTitle      `{nextStepsTitle && …}`         → raw truthiness
          //   nextStepsDescription`{nextStepsDescription && …}`   → raw truthiness
          //   celebrationTasks    `celebrationTasks.length > 0`   → length
          //   buttonText          `buttonText || "Continue"`      → raw truthiness
          //
          // This originally trimmed strings, which under-warned in the one case the rule
          // exists for: `celebrationCompletedSection: "   "` is falsy after a trim, so no
          // warning — but it is TRUTHY to the renderer, which then suppresses three fields
          // silently. A validator that is more forgiving than the renderer reports success
          // on exactly the input that fails.
          //
          // Note it cannot be a single raw-truthiness check either: `[]` is truthy in JS,
          // so an array needs the length test or every cleared task list warns.
          const populated = (k) => {
            const v = sub[k];
            if (v === undefined || v === null) return false;
            if (Array.isArray(v)) return v.length > 0;
            if (typeof v === "string") return v !== "";
            return Boolean(v);
          };
          for (const rule of CELEBRATION_SUPPRESSIONS) {
            if (!populated(rule.when)) continue;
            const dead = rule.suppresses.filter(populated);
            if (dead.length === 0) continue;
            warnings.push(
              `${blabel} sets ${dead.join(", ")}, but "${rule.when}" ${rule.because} — ` +
                `${dead.length > 1 ? "those fields are" : "that field is"} never shown to the member. ` +
                `Either clear "${rule.when}" or drop ${dead.length > 1 ? "them" : "it"}.`,
            );
          }
        }
        for (const f of Object.keys(sub)) if (AUTO_FIELDS.has(f)) errors.push(`${blabel} has auto-managed field "${f}" — remove it.`);
        const bSlug = sub.slug || slugify(sub.title || "");
        if (bSlug) { if (subSlugs.has(bSlug)) errors.push(`${blabel} duplicate slug "${bSlug}" within step.`); else subSlugs.add(bSlug); }
        orderedSubsteps.push({ sub, slug: bSlug, label: blabel });
      }
    }
  }

  // Token-ordering pass over the flat ordered list.
  const producedBefore = new Set();
  for (const { sub, slug, label } of orderedSubsteps) {
    for (const tok of tokensIn(sub)) {
      const available = assumed.has(tok) || producedBefore.has(tok);
      if (!available) {
        errors.push(`${label} uses token {${tok}} before any earlier substep produces it (and it isn't an assumed prerequisite token). ` +
          `Collect {${tok}} earlier, or pass it via --assume.`);
      }
    }
    // This substep now produces its own slug for downstream tokens (collect/generate produce data).
    if (slug && (sub.type === "collect" || sub.type === "generate")) producedBefore.add(slug);
  }

  return { errors, warnings };
}

// ---- CLI arg parsing (exported for testing) ----
export function parseArgs(args) {
  const assumeClarity = args.includes("--assume-clarity");
  const eqArg = args.find((a) => a.startsWith("--assume="));
  const spaceIdx = args.indexOf("--assume");
  const assume = eqArg
    ? eqArg.split("=")[1].split(",").map((s) => s.trim()).filter(Boolean)
    : (spaceIdx !== -1 && args[spaceIdx + 1] && !args[spaceIdx + 1].startsWith("--")
        ? args[spaceIdx + 1].split(",").map((s) => s.trim()).filter(Boolean)
        : []);
  // file = last positional that isn't a flag and isn't the value consumed by `--assume <value>`
  const consumed = new Set();
  if (!eqArg && spaceIdx !== -1 && args[spaceIdx + 1] && !args[spaceIdx + 1].startsWith("--")) consumed.add(spaceIdx + 1);
  const file = args.findLast((a, i) => !a.startsWith("--") && !consumed.has(i));
  return { file, assume, assumeClarity };
}

/**
 * Load the vendored capability manifest that sits beside this script.
 *
 * The CLI used to call validateTracks WITHOUT capabilities, which quietly disabled every
 * manifest-driven check for anyone running the validator the documented way — including the
 * #51 protection (a fieldType that is declared but has no render path in ignite-next, i.e.
 * one that silently degrades to a text box for the member). The manifest was sitting in
 * data/ the whole time, unread.
 *
 * Degrades rather than throws: a missing or malformed manifest returns null and the caller
 * proceeds with the reduced checks, announcing it. A validator that refuses to run because a
 * capability file is absent is a validator people route around.
 */
export async function loadVendoredCapabilities(scriptUrl) {
  const { readFileSync } = await import("node:fs");
  const { fileURLToPath } = await import("node:url");
  const { dirname, join } = await import("node:path");
  const here = dirname(fileURLToPath(scriptUrl));
  const path = join(here, "..", "data", "track-capabilities.json");
  try {
    const caps = JSON.parse(readFileSync(path, "utf8"));
    // Validate the SHAPE, not just presence. `rendered: {}` is truthy, and the consumer calls
    // `rendered.includes(ft)` — which throws TypeError on a non-array and crashes the CLI,
    // the exact opposite of the degradation this function promises. Elements are checked too:
    // `rendered: [42]` would not throw, but no real fieldType could ever match it, turning
    // every field type into a spurious error.
    const isStringArray = (v) => Array.isArray(v) && v.every((e) => typeof e === "string");
    if (!caps || typeof caps !== "object" || !caps.fieldTypes ||
        !isStringArray(caps.fieldTypes.rendered) || !isStringArray(caps.fieldTypes.declared)) {
      return {
        caps: null,
        note: `${path} is not a usable manifest (fieldTypes.declared/rendered must be arrays of strings) — field-type checks are reduced.`,
      };
    }
    return { caps, note: null };
  } catch (e) {
    return { caps: null, note: `capability manifest not read (${e.message}) — field-type checks are reduced.` };
  }
}

// ---- CLI ----
if (import.meta.url === `file://${process.argv[1]}`) {
  const { file, assume, assumeClarity } = parseArgs(process.argv.slice(2));
  if (!file) { console.error("Usage: node validate-track-json.mjs <tracks.json> [--assume a,b] [--assume-clarity]"); process.exit(2); }
  const { readFileSync } = await import("node:fs");
  let data;
  try { data = JSON.parse(readFileSync(file, "utf8")); }
  catch (e) { console.error(`Could not read/parse ${file}: ${e.message}`); process.exit(2); }
  const { caps, note } = await loadVendoredCapabilities(import.meta.url);
  if (note) console.warn(`WARN  ${note}`);
  const { errors, warnings } = validateTracks(data, { assume, assumeClarity, capabilities: caps ?? undefined });
  for (const w of warnings) console.warn(`WARN  ${w}`);
  for (const e of errors) console.error(`ERROR ${e}`);
  if (errors.length) { console.error(`\n${errors.length} error(s), ${warnings.length} warning(s).`); process.exit(1); }
  console.log(`OK — valid (${warnings.length} warning(s)).`);
}
