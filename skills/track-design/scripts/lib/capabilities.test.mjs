import { test } from "node:test";
import assert from "node:assert/strict";
import { writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { loadCapabilities, aiContextOf } from "./capabilities.mjs";

const write = (obj) => {
  const dir = mkdtempSync(join(tmpdir(), "caps-"));
  const p = join(dir, "track-capabilities.json");
  writeFileSync(p, JSON.stringify(obj));
  return p;
};

const valid = {
  generatedAt: new Date().toISOString(),
  commit: "abc1234",
  fieldTypes: { declared: ["text", "textarea"], rendered: ["text"], aiContext: [] },
  runtimeCapabilities: { grounding: false },
  substepFields: ["prompt"],
  responseModel: ["answer"],
};

test("loadCapabilities: returns the manifest with no warnings when fresh and valid", () => {
  const r = loadCapabilities({ path: write(valid) });
  assert.deepEqual(r.warnings, []);
  assert.deepEqual(r.manifest.fieldTypes.rendered, ["text"]);
});

test("loadCapabilities: a missing file degrades to null with a warning, never throws", () => {
  const r = loadCapabilities({ path: "/nope/track-capabilities.json" });
  assert.equal(r.manifest, null);
  assert.match(r.warnings[0], /capability manifest not found/i);
});

test("loadCapabilities: malformed JSON degrades to null with a warning", () => {
  const dir = mkdtempSync(join(tmpdir(), "caps-"));
  const p = join(dir, "track-capabilities.json");
  writeFileSync(p, "{ not json");
  const r = loadCapabilities({ path: p });
  assert.equal(r.manifest, null);
  assert.match(r.warnings[0], /could not be read/i);
});

test("loadCapabilities: a wrong-shaped manifest degrades to null", () => {
  const r = loadCapabilities({ path: write({ generatedAt: "x", commit: "y" }) });
  assert.equal(r.manifest, null);
  // Wording changed with the Array.isArray hardening below: the warning now names
  // the offending field instead of saying "missing fieldTypes". The assertion is
  // updated rather than relaxed — it still pins that the field is identified.
  assert.match(r.warnings[0], /malformed "fieldTypes"/i);
});

test("loadCapabilities: a stale manifest still loads but warns with its date", () => {
  const old = { ...valid, generatedAt: "2020-01-01T00:00:00.000Z" };
  const r = loadCapabilities({ path: write(old), maxAgeDays: 30 });
  assert.ok(r.manifest, "stale must still load — never block authoring");
  assert.match(r.warnings[0], /2020-01-01/);
});

// --- shape validation must require ARRAYS (Macroscope, PR #113) ---------------
// The check was truthiness-only, so `{ declared: {}, rendered: {} }` passed as
// valid. Callers then hit `rendered.includes(ft)` — a TypeError, because a plain
// object has no .includes — which CRASHES validation. That is the exact opposite
// of this loader's contract: it must degrade to null + a warning, never throw.
//
// Validated for every field the contract promises as an array, not just the two
// Macroscope happened to name, because the cost engine downstream also reads
// substepFields and fieldTypes.aiContext the same way.

const shaped = (over) => ({
  generatedAt: new Date().toISOString(), commit: "abc1234",
  fieldTypes: { declared: ["text"], rendered: ["text"], aiContext: [] },
  runtimeCapabilities: { grounding: false },
  substepFields: ["prompt"], responseModel: ["answer"],
  ...over,
});

test("loadCapabilities: a non-array declared/rendered is rejected, not returned as valid", () => {
  for (const bad of [{}, "text", 42, null]) {
    const r1 = loadCapabilities({ path: write(shaped({ fieldTypes: { declared: bad, rendered: ["text"], aiContext: [] } })) });
    assert.equal(r1.manifest, null, `declared=${JSON.stringify(bad)} must be rejected`);
    const r2 = loadCapabilities({ path: write(shaped({ fieldTypes: { declared: ["text"], rendered: bad, aiContext: [] } })) });
    assert.equal(r2.manifest, null, `rendered=${JSON.stringify(bad)} must be rejected`);
  }
});

test("loadCapabilities: a non-array aiContext / substepFields / responseModel is rejected", () => {
  const cases = [
    shaped({ fieldTypes: { declared: ["text"], rendered: ["text"], aiContext: {} } }),
    shaped({ substepFields: {} }),
    shaped({ responseModel: "answer" }),
  ];
  for (const c of cases) {
    assert.equal(loadCapabilities({ path: write(c) }).manifest, null);
  }
});

test("loadCapabilities: a non-object runtimeCapabilities is rejected", () => {
  assert.equal(loadCapabilities({ path: write(shaped({ runtimeCapabilities: [] })) }).manifest, null);
});

test("loadCapabilities: the rejection warning names the offending field", () => {
  const r = loadCapabilities({ path: write(shaped({ substepFields: {} })) });
  assert.match(r.warnings[0], /substepFields/);
});

// --- forward compatibility with the aiContext shape change --------------------
// ignite-next is replacing `fieldTypes.aiContext: string[]` with
//   { customFormatting: string[], genericFallbackForUnlistedTypes: boolean }
// because the flat list read as "the field types the AI sees" while
// aiContextBuilder's switch has a `default` branch — so every other included
// answer also reaches the prompt, just with generic formatting.
//
// This loader validated Array.isArray(aiContext), so the new shape would have been
// rejected as malformed, the manifest degraded to null, and validate-track-json
// would have silently fallen back to its stale hardcoded field-type list. A
// warning, not a crash: it would have looked like it was working.

test("loadCapabilities: accepts the object-shaped aiContext", () => {
  const r = loadCapabilities({
    path: write({ ...valid, fieldTypes: { declared: ["text"], rendered: ["text"],
      aiContext: { customFormatting: ["education"], genericFallbackForUnlistedTypes: true } } }),
  });
  assert.ok(r.manifest, "the new shape must not be rejected");
  assert.deepEqual(r.warnings, []);
});

test("loadCapabilities: still accepts the legacy array-shaped aiContext", () => {
  const r = loadCapabilities({
    path: write({ ...valid, fieldTypes: { declared: ["text"], rendered: ["text"], aiContext: ["education"] } }),
  });
  assert.ok(r.manifest);
});

test("loadCapabilities: a genuinely malformed aiContext is still rejected", () => {
  for (const bad of [42, "education", { customFormatting: "nope" }]) {
    const r = loadCapabilities({
      path: write({ ...valid, fieldTypes: { declared: ["t"], rendered: ["t"], aiContext: bad } }),
    });
    assert.equal(r.manifest, null, `aiContext=${JSON.stringify(bad)} must be rejected`);
    assert.match(r.warnings[0], /aiContext/);
  }
});

test("aiContextOf: normalises both shapes", () => {
  assert.deepEqual(
    aiContextOf({ customFormatting: ["education"], genericFallbackForUnlistedTypes: true }),
    { customFormatting: ["education"], genericFallbackForUnlistedTypes: true },
  );
  // A legacy list asserts nothing about the fallback, so it reports false.
  assert.deepEqual(aiContextOf(["education"]),
    { customFormatting: ["education"], genericFallbackForUnlistedTypes: false });
});

// --- element types, not just container types (Macroscope on track-studio#66) ---
// Every array check was Array.isArray() only, so `declared: [42]` was returned as a
// valid manifest. Consumers compare these against field-type NAMES, so a number
// matches nothing and the type silently reads as unsupported — the same false
// negative this manifest exists to prevent, arriving via the validator itself.
// Macroscope flagged only customFormatting (it reviews the diff); the hole was
// everywhere, so it is fixed as a class.

test("loadCapabilities: rejects non-string elements in every string-array field", () => {
  const cases = [
    ["fieldTypes.declared", shaped({ fieldTypes: { declared: [42], rendered: ["t"], aiContext: [] } })],
    ["fieldTypes.rendered", shaped({ fieldTypes: { declared: ["t"], rendered: [null], aiContext: [] } })],
    ["fieldTypes.aiContext", shaped({ fieldTypes: { declared: ["t"], rendered: ["t"], aiContext: [42] } })],
    ["fieldTypes.aiContext", shaped({ fieldTypes: { declared: ["t"], rendered: ["t"],
      aiContext: { customFormatting: [42], genericFallbackForUnlistedTypes: true } } })],
    ["substepFields", shaped({ substepFields: [{}] })],
    ["responseModel", shaped({ responseModel: [7] })],
  ];
  for (const [field, obj] of cases) {
    const r = loadCapabilities({ path: write(obj) });
    assert.equal(r.manifest, null, `${field} with a non-string element must be rejected`);
    assert.match(r.warnings[0], new RegExp(field.replace(".", "\\.")));
  }
});

test("loadCapabilities: rejects non-boolean runtimeCapabilities values", () => {
  const r = loadCapabilities({ path: write(shaped({ runtimeCapabilities: { grounding: "yes" } })) });
  assert.equal(r.manifest, null, "a string where a boolean is promised must be rejected");
  assert.match(r.warnings[0], /runtimeCapabilities/);
});

test("loadCapabilities: an empty array is still valid — emptiness is not malformed", () => {
  const r = loadCapabilities({ path: write(shaped({ fieldTypes: { declared: [], rendered: [], aiContext: [] } })) });
  assert.ok(r.manifest, "an empty list is a legitimate manifest, not a broken one");
});
