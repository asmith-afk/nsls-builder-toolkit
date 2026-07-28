import { test } from "node:test";
import assert from "node:assert/strict";
import { validateTracks, parseArgs } from "./validate-track-json.mjs";

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
