import { test } from "node:test";
import assert from "node:assert/strict";
import { writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { loadCapabilities } from "./capabilities.mjs";

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
