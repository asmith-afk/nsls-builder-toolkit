// Validates an ignite-next importable track JSON array against the schema
// contract and the ontology token-ordering rule.
// Usage (CLI): node validate-track-json.mjs <path-to-tracks.json> [--assume slugA,slugB] [--assume-clarity]

const VALID_TYPES = new Set(["say", "collect", "generate", "chat", "ai-process"]);
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

// ---- CLI ----
if (import.meta.url === `file://${process.argv[1]}`) {
  const { file, assume, assumeClarity } = parseArgs(process.argv.slice(2));
  if (!file) { console.error("Usage: node validate-track-json.mjs <tracks.json> [--assume a,b] [--assume-clarity]"); process.exit(2); }
  const { readFileSync } = await import("node:fs");
  let data;
  try { data = JSON.parse(readFileSync(file, "utf8")); }
  catch (e) { console.error(`Could not read/parse ${file}: ${e.message}`); process.exit(2); }
  const { errors, warnings } = validateTracks(data, { assume, assumeClarity });
  for (const w of warnings) console.warn(`WARN  ${w}`);
  for (const e of errors) console.error(`ERROR ${e}`);
  if (errors.length) { console.error(`\n${errors.length} error(s), ${warnings.length} warning(s).`); process.exit(1); }
  console.log(`OK — valid (${warnings.length} warning(s)).`);
}
