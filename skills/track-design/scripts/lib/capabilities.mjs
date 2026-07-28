// Loads the ignite-next capability manifest (track-capabilities.json), vendored
// into this skill's data/ directory. NEVER throws and never blocks authoring: a
// missing, malformed or stale manifest degrades to null plus a warning, and the
// caller falls back to its previous behaviour.
import { readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_PATH = join(HERE, "..", "..", "data", "track-capabilities.json");
const DAY_MS = 86_400_000;

/**
 * An array of strings — ELEMENTS checked, not just the container. `Array.isArray`
 * alone let `declared: [42]` through as a valid manifest; consumers read these as
 * strings and compare them against field-type names, so a number matches nothing and
 * the type silently reads as unsupported. An empty array stays valid.
 */
const isStringArray = (v) => Array.isArray(v) && v.every((e) => typeof e === "string");

/** `fieldTypes.aiContext` on disk: a legacy string[] OR the object form. Both valid. */
const isValidAiContext = (v) => {
  if (isStringArray(v)) return true; // legacy flat form
  if (!v || typeof v !== "object" || Array.isArray(v)) return false;
  return isStringArray(v.customFormatting) && typeof v.genericFallbackForUnlistedTypes === "boolean";
};

/**
 * Normalise either shape to the object form. A legacy flat list says which types have
 * custom formatting and says NOTHING about the fallback, so it reports false — "not
 * asserted" rather than "asserted absent".
 */
export function aiContextOf(raw) {
  return Array.isArray(raw)
    ? { customFormatting: raw, genericFallbackForUnlistedTypes: false }
    : { customFormatting: raw.customFormatting, genericFallbackForUnlistedTypes: raw.genericFallbackForUnlistedTypes };
}

export function loadCapabilities({ path = DEFAULT_PATH, maxAgeDays = 30, now = Date.now() } = {}) {
  const warnings = [];
  if (!existsSync(path)) {
    warnings.push(
      `capability manifest not found at ${path} — field-type checks fall back to the built-in list. ` +
        `Refresh it with track-studio's scripts/sync-capabilities.mjs.`,
    );
    return { manifest: null, warnings };
  }
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch (err) {
    warnings.push(`capability manifest at ${path} could not be read: ${err.message}`);
    return { manifest: null, warnings };
  }
  // Validate the TYPES the contract promises, not merely that keys are present.
  // A truthiness check let `{ declared: {}, rendered: {} }` through as valid, and
  // the caller then hit `rendered.includes(ft)` — a TypeError, because a plain
  // object has no .includes. That CRASHES validation, which is the exact opposite
  // of this loader's job: it must always degrade to null + a warning.
  //
  // Every array field is checked, not just the two that surfaced the bug: the
  // downstream cost engine reads substepFields and fieldTypes.aiContext the same
  // way, so a wrong type there fails identically.
  const badField = (() => {
    const ft = parsed?.fieldTypes;
    if (!ft || typeof ft !== "object") return "fieldTypes";
    for (const k of ["declared", "rendered"]) {
      if (!isStringArray(ft[k])) return `fieldTypes.${k}`;
    }
    // aiContext accepts TWO shapes on purpose. The original flat string[] read as
    // "the field types the AI sees", but aiContextBuilder's switch has a `default`
    // branch, so every other included answer ALSO reaches the prompt with generic
    // formatting — so ignite-next is changing it to
    //   { customFormatting: string[], genericFallbackForUnlistedTypes: boolean }.
    // Rejecting that shape would degrade the manifest to null the moment it ships,
    // and because that only WARNS, this validator would silently fall back to its
    // stale hardcoded FALLBACK_FIELD_TYPES list while appearing to work. Accept both.
    if (!isValidAiContext(ft.aiContext)) return "fieldTypes.aiContext";
    for (const k of ["substepFields", "responseModel"]) {
      if (!isStringArray(parsed[k])) return k;
    }
    const rc = parsed.runtimeCapabilities;
    if (!rc || typeof rc !== "object" || Array.isArray(rc)) return "runtimeCapabilities";
    // Values are promised booleans. A string like "yes" is truthy everywhere it is
    // read, so an unwired capability could report as wired — the worst direction.
    if (!Object.values(rc).every((x) => typeof x === "boolean")) return "runtimeCapabilities";
    return null;
  })();
  if (badField) {
    warnings.push(
      `capability manifest at ${path} has a malformed "${badField}" — expected ` +
        `${badField === "runtimeCapabilities" ? "an object" : "an array"}. ` +
        `Falling back to the built-in field-type list; refresh the manifest with ` +
        `track-studio's scripts/sync-capabilities.mjs.`,
    );
    return { manifest: null, warnings };
  }
  const age = now - Date.parse(parsed.generatedAt ?? "");
  if (Number.isFinite(age) && age > maxAgeDays * DAY_MS) {
    warnings.push(
      `capability manifest is stale (generated ${String(parsed.generatedAt).slice(0, 10)}) — ` +
        `it may not reflect what ignite-next supports today.`,
    );
  }
  return { manifest: parsed, warnings };
}
