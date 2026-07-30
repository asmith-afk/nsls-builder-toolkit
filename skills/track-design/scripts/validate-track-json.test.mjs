import { test } from "node:test";
import assert from "node:assert/strict";
import { loadVendoredCapabilities, validateTracks, parseArgs } from "./validate-track-json.mjs";

const goodTracks = [
  {
    id: "trk_demo",
    title: "Demo Track",
    steps: [
      {
        id: "stp_0",
        title: "Start",
        substeps: [
          { id: "ss_name", slug: "name", title: "Name", prompt: "What should we call you?", type: "collect", fieldType: "text" },
          { id: "ss_hi", slug: "hi", title: "Hi", prompt: "Hi {name}, welcome.", type: "say", fieldType: "banner" }
        ]
      }
    ]
  }
];

test("valid track passes with no errors", () => {
  const { errors } = validateTracks(goodTracks);
  assert.deepEqual(errors, []);
});

test("missing required substep field is an error", () => {
  const t = structuredClone(goodTracks);
  delete t[0].steps[0].substeps[0].prompt;
  const { errors } = validateTracks(t);
  assert.ok(errors.some((e) => /prompt/.test(e) && /ss_name/.test(e)));
});

test("leaked auto-managed field is an error", () => {
  const t = structuredClone(goodTracks);
  t[0].steps[0].substeps[0].order = 0;
  const { errors } = validateTracks(t);
  assert.ok(errors.some((e) => /order/.test(e) && /auto-managed/.test(e)));
});

test("duplicate substep slug within a step is an error", () => {
  const t = structuredClone(goodTracks);
  t[0].steps[0].substeps[1].slug = "name";
  const { errors } = validateTracks(t);
  assert.ok(errors.some((e) => /duplicate slug/i.test(e) && /name/.test(e)));
});

test("duplicate id anywhere is an error", () => {
  const t = structuredClone(goodTracks);
  t[0].steps[0].substeps[1].id = "ss_name";
  const { errors } = validateTracks(t);
  assert.ok(errors.some((e) => /duplicate id/i.test(e) && /ss_name/.test(e)));
});

test("invalid type is an error", () => {
  const t = structuredClone(goodTracks);
  t[0].steps[0].substeps[1].type = "speak";
  const { errors } = validateTracks(t);
  assert.ok(errors.some((e) => /invalid type/i.test(e) && /speak/.test(e)));
});

test("forward token reference is an error", () => {
  const t = structuredClone(goodTracks);
  t[0].steps[0].substeps[0].prompt = "Your dream job is {dream-job-selection}.";
  const { errors } = validateTracks(t);
  assert.ok(errors.some((e) => /token/i.test(e) && /dream-job-selection/.test(e)));
});

test("assumed token from a prerequisite track passes", () => {
  const t = structuredClone(goodTracks);
  t[0].steps[0].substeps[0].prompt = "Building on your {career-statement}...";
  const { errors } = validateTracks(t, { assume: ["career-statement"] });
  assert.deepEqual(errors, []);
});

test("unknown fieldType is a warning, not an error", () => {
  const t = structuredClone(goodTracks);
  t[0].steps[0].substeps[0].fieldType = "hologram";
  const { errors, warnings } = validateTracks(t);
  assert.deepEqual(errors, []);
  assert.ok(warnings.some((w) => /hologram/.test(w)));
});

test("top level must be an array", () => {
  const { errors } = validateTracks({ id: "x" });
  assert.ok(errors.some((e) => /array/i.test(e)));
});

// ---- parseArgs tests ----

test("parseArgs: space-form --assume picks correct file", () => {
  const result = parseArgs(["--assume", "a,b", "tracks.json"]);
  assert.deepEqual(result, { file: "tracks.json", assume: ["a", "b"], assumeClarity: false });
});

test("parseArgs: equals-form --assume=a,b picks correct file", () => {
  const result = parseArgs(["--assume=a,b", "tracks.json"]);
  assert.deepEqual(result, { file: "tracks.json", assume: ["a", "b"], assumeClarity: false });
});

test("parseArgs: --assume-clarity flag with file", () => {
  const result = parseArgs(["tracks.json", "--assume-clarity"]);
  assert.deepEqual(result, { file: "tracks.json", assume: [], assumeClarity: true });
});

test("parseArgs: file only", () => {
  const result = parseArgs(["tracks.json"]);
  assert.deepEqual(result, { file: "tracks.json", assume: [], assumeClarity: false });
});

// ---- capability-manifest-aware fieldType checks ----
// See track-studio#51: the hardcoded KNOWN_FIELD_TYPES list silently omitted
// wheel/multi-select-list/resume-upload while all three ran in production —
// this is why "declared but not rendered" must be an ERROR, not a warning.

const caps = {
  generatedAt: new Date().toISOString(),
  commit: "abc1234",
  fieldTypes: { declared: ["text", "wheel", "textarea"], rendered: ["text", "wheel"], aiContext: [] },
  runtimeCapabilities: {},
  substepFields: ["prompt"],
  responseModel: ["answer"],
};

const track = (fieldType) => [{
  id: "t", title: "T",
  steps: [{ id: "s", title: "S", substeps: [
    { id: "b", slug: "b", title: "B", type: "collect", prompt: "p", fieldType },
  ] }],
}];

test("a rendered field type passes", () => {
  const r = validateTracks(track("wheel"), { capabilities: caps });
  assert.deepEqual(r.errors.filter((e) => /fieldType/.test(e)), []);
});

test("declared but NOT rendered is an ERROR — it becomes a fallback text box for a member", () => {
  const r = validateTracks(track("textarea"), { capabilities: caps });
  assert.equal(r.errors.filter((e) => /textarea/.test(e)).length, 1);
  assert.match(r.errors.find((e) => /textarea/.test(e)), /declared but has no render path/);
});

test("a type in neither list is an ERROR", () => {
  const r = validateTracks(track("hologram"), { capabilities: caps });
  assert.match(r.errors.find((e) => /hologram/.test(e)), /unknown fieldType/);
});

test("with NO manifest, an unknown type stays a WARNING (today's behaviour)", () => {
  const r = validateTracks(track("hologram"), {});
  assert.deepEqual(r.errors.filter((e) => /hologram/.test(e)), []);
  assert.equal(r.warnings.filter((w) => /hologram/.test(w)).length, 1);
});

test("with a manifest, the three live types Julia hit no longer warn", () => {
  // wheel/multi-select-list/resume-upload are live in production yet the old
  // hardcoded KNOWN_FIELD_TYPES called them unknown (track-studio#51).
  const real = { ...caps, fieldTypes: { declared: ["wheel", "multi-select-list", "resume-upload"],
    rendered: ["wheel", "multi-select-list", "resume-upload"], aiContext: [] } };
  for (const ft of ["wheel", "multi-select-list", "resume-upload"]) {
    const r = validateTracks(track(ft), { capabilities: real });
    assert.deepEqual(r.warnings.filter((w) => /unknown fieldType/.test(w)), [], ft);
  }
});

// --- an empty prompt on a `generate` substep (track-studio#49) ----------------
// "" is legitimate on say/celebration substeps — their copy lives in other fields.
// It is NOT legitimate on `generate`: the AI has nothing to work from and the member
// sees the literal "New sub step — edit me in the editor panel" placeholder. That is
// the exact symptom reported in #49, and the null-only check missed it.

const oneSubstep = (type, prompt) => [{
  id: "t", title: "T",
  steps: [{ id: "s", title: "S", substeps: [{ id: "sub-1", slug: "x", title: "X", type, prompt }] }],
}];

test("an empty prompt on a generate substep is an error", () => {
  const r = validateTracks(oneSubstep("generate", ""), { assumeClarity: true });
  const hits = r.errors.filter((e) => /prompt/.test(e));
  assert.equal(hits.length, 1, `expected one prompt error, got ${JSON.stringify(r.errors)}`);
  assert.match(hits[0], /sub-1/);
});

test("a whitespace-only prompt on a generate substep is an error", () => {
  const r = validateTracks(oneSubstep("generate", "   \n "), { assumeClarity: true });
  assert.equal(r.errors.filter((e) => /prompt/.test(e)).length, 1);
});

test("an empty prompt is still allowed on say and celebration substeps", () => {
  for (const type of ["say", "celebration"]) {
    const r = validateTracks(oneSubstep(type, ""), { assumeClarity: true });
    assert.deepEqual(r.errors.filter((e) => /prompt/.test(e)), [], type);
  }
});

test("a null prompt is still an error on any substep type", () => {
  const r = validateTracks(oneSubstep("say", null), { assumeClarity: true });
  assert.equal(r.errors.filter((e) => /missing required "prompt"/.test(e)).length, 1);
});

// ---------------------------------------------------------------------------
// Option-array ambiguity (track-studio#60).
//
// There are THREE option arrays on a substep — options, checkboxOptions,
// dropdownOptions — and nothing at author time says which one a given fieldType
// actually reads. Welcome v7-draft.5 put 18 CIP majors in `options` on a
// `multi-select-list`, which reads `checkboxOptions`; the member was shown a
// career-needs list instead of majors, and the version still scored 16/16
// because a synthetic panel reads design intent, not the rendered widget.
//
// Two rules. The first needs no knowledge of the app: populating more than one
// option array means at least one is silently discarded, whichever is read.
// Measured against live content — 0 of 69 substeps with any option array
// populate two — so this has no false positives today.
// ---------------------------------------------------------------------------

const withFields = (fields) => [{
  id: "t", title: "T",
  steps: [{ id: "s", title: "S", substeps: [{ id: "sub-1", slug: "x", title: "X", type: "collect", prompt: "p", ...fields }] }],
}];

test("populating two option arrays warns that one will be discarded", () => {
  // Julia's repro shape: the intended list in `options`, a leftover list in `checkboxOptions`.
  const r = validateTracks(withFields({
    fieldType: "multi-select-list",
    options: ["Business Administration", "Registered Nursing", "Psychology"],
    checkboxOptions: ["Clearer goals", "Stronger professional network"],
  }), { assumeClarity: true });
  const hits = r.warnings.filter((w) => /option/i.test(w));
  assert.equal(hits.length, 1, `expected one option warning, got ${JSON.stringify(r.warnings)}`);
  assert.match(hits[0], /sub-1/);
  assert.match(hits[0], /options/);
  assert.match(hits[0], /checkboxOptions/);
});

test("one populated option array is fine, whichever it is", () => {
  for (const key of ["options", "checkboxOptions", "dropdownOptions"]) {
    const r = validateTracks(withFields({ fieldType: "multi-select-list", [key]: ["a", "b"] }), { assumeClarity: true });
    assert.deepEqual(r.warnings.filter((w) => /more than one/i.test(w)), [], key);
  }
});

test("empty option arrays are not 'populated' — no warning for the leftover []", () => {
  // Clearing a list in the editor leaves [], which must not read as a second list.
  const r = validateTracks(withFields({ fieldType: "multi-select-list", options: [], checkboxOptions: ["a"] }), { assumeClarity: true });
  assert.deepEqual(r.warnings.filter((w) => /more than one/i.test(w)), []);
});

test("the option warning names every populated array, not just two", () => {
  const r = validateTracks(withFields({
    fieldType: "select", options: ["a"], checkboxOptions: ["b"], dropdownOptions: ["c"],
  }), { assumeClarity: true });
  const hit = r.warnings.find((w) => /more than one/i.test(w));
  assert.ok(hit, "expected a warning");
  for (const k of ["options", "checkboxOptions", "dropdownOptions"]) assert.match(hit, new RegExp(k));
});

// The precise rule — "this fieldType reads checkboxOptions, so your `options` is
// dead" — needs to know each fieldType's accessor. That is an ignite-next fact
// (SubStepRenderer.tsx), and hard-coding it here would recreate the duplicated
// truth the capability manifest exists to remove. So it activates only when the
// manifest supplies it (ignite-next#985), and stays silent otherwise.
test("with a manifest accessor map, the wrong array is named specifically", () => {
  const caps = {
    fieldTypes: {
      declared: ["multi-select-list"], rendered: ["multi-select-list"], aiContext: [],
      optionSource: { "multi-select-list": "checkboxOptions" },
    },
    runtimeCapabilities: {}, substepFields: [], responseModel: [],
  };
  const r = validateTracks(withFields({ fieldType: "multi-select-list", options: ["Psychology"] }), { capabilities: caps, assumeClarity: true });
  const hit = r.warnings.find((w) => /never read|does not read|reads/i.test(w));
  assert.ok(hit, `expected an accessor warning, got ${JSON.stringify(r.warnings)}`);
  assert.match(hit, /checkboxOptions/);
});

test("with a manifest accessor map, the CORRECT array produces no warning", () => {
  const caps = {
    fieldTypes: {
      declared: ["multi-select-list"], rendered: ["multi-select-list"], aiContext: [],
      optionSource: { "multi-select-list": "checkboxOptions" },
    },
    runtimeCapabilities: {}, substepFields: [], responseModel: [],
  };
  const r = validateTracks(withFields({ fieldType: "multi-select-list", checkboxOptions: ["Psychology"] }), { capabilities: caps, assumeClarity: true });
  assert.deepEqual(r.warnings.filter((w) => /option/i.test(w)), []);
});

test("without an accessor map the specific rule stays silent — no guessing", () => {
  const r = validateTracks(withFields({ fieldType: "multi-select-list", options: ["Psychology"] }), { assumeClarity: true });
  assert.deepEqual(r.warnings.filter((w) => /never read|does not read/i.test(w)), []);
});

// ---------------------------------------------------------------------------
// The CLI must actually pass the manifest (macroscope, track-studio#60 PR).
//
// The CLI called validateTracks WITHOUT capabilities, so every manifest-driven
// check was unreachable from the documented entry point — including the #51
// protection against a fieldType that is declared but has no render path. The
// manifest was sitting in data/ unread the whole time.
// ---------------------------------------------------------------------------

test("the vendored capability manifest loads and carries a rendered field-type list", async () => {
  const { caps, note } = await loadVendoredCapabilities(import.meta.url);
  assert.equal(note, null, `expected a clean load, got: ${note}`);
  assert.ok(Array.isArray(caps.fieldTypes.rendered) && caps.fieldTypes.rendered.length > 0);
});

test("WITH the manifest an unknown fieldType is an ERROR, not a warning", () => {
  // This is the observable difference between caps being passed and not. Before the CLI fix
  // it produced only a warning, so a genuinely unsupported field type did not fail the gate.
  const tracks = withFields({ fieldType: "holographic-input-that-cannot-exist" });
  const caps = { fieldTypes: { declared: ["text"], rendered: ["text"], aiContext: [] }, runtimeCapabilities: {}, substepFields: [], responseModel: [] };
  const withCaps = validateTracks(tracks, { capabilities: caps, assumeClarity: true });
  assert.equal(withCaps.errors.filter((e) => /unknown fieldType/.test(e)).length, 1);

  const without = validateTracks(tracks, { assumeClarity: true });
  assert.deepEqual(without.errors.filter((e) => /unknown fieldType/.test(e)), []);
  assert.equal(without.warnings.filter((w) => /unknown fieldType/.test(w)).length, 1);
});

test("a missing manifest degrades with a note rather than throwing", async () => {
  // A validator that refuses to run because a capability file is absent is one people route around.
  const { caps, note } = await loadVendoredCapabilities("file:///nonexistent/deeply/fake.mjs");
  assert.equal(caps, null);
  assert.match(note ?? "", /not read|no fieldTypes/i);
});

test("a malformed manifest degrades instead of crashing the CLI", async () => {
  // `rendered: {}` is truthy, so a truthiness guard let it through and
  // `rendered.includes(ft)` then threw TypeError — crashing the validator instead of
  // degrading, which is the opposite of what the loader promises. Same class as the
  // element-validation gap in track-studio's lib/capabilities.ts.
  const { mkdtempSync, mkdirSync, writeFileSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { pathToFileURL } = await import("node:url");

  const shapes = [
    { fieldTypes: { rendered: {}, declared: [] } },
    { fieldTypes: { rendered: ["text"], declared: "text" } },
    { fieldTypes: { rendered: [42], declared: ["text"] } },
    { fieldTypes: {} },
    { nope: true },
    "not an object",
  ];

  for (const shape of shapes) {
    const root = mkdtempSync(join(tmpdir(), "caps-"));
    mkdirSync(join(root, "scripts"));
    mkdirSync(join(root, "data"));
    writeFileSync(join(root, "data", "track-capabilities.json"), JSON.stringify(shape));
    const url = pathToFileURL(join(root, "scripts", "validate.mjs")).href;

    const { caps, note } = await loadVendoredCapabilities(url);
    assert.equal(caps, null, `${JSON.stringify(shape)} should not be accepted`);
    assert.ok(note, "a rejected manifest must announce itself");

    // And the reduced path must still run without throwing.
    assert.doesNotThrow(() =>
      validateTracks(withFields({ fieldType: "text" }), { capabilities: caps ?? undefined, assumeClarity: true }),
    );
  }
});

test("a well-formed manifest is still accepted", async () => {
  const { mkdtempSync, mkdirSync, writeFileSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { pathToFileURL } = await import("node:url");
  const root = mkdtempSync(join(tmpdir(), "caps-ok-"));
  mkdirSync(join(root, "scripts")); mkdirSync(join(root, "data"));
  writeFileSync(join(root, "data", "track-capabilities.json"),
    JSON.stringify({ fieldTypes: { rendered: ["text"], declared: ["text"], aiContext: [] } }));
  const { caps, note } = await loadVendoredCapabilities(pathToFileURL(join(root, "scripts", "v.mjs")).href);
  assert.equal(note, null);
  assert.deepEqual(caps.fieldTypes.rendered, ["text"]);
});
