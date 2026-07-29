import { test } from "node:test";
import assert from "node:assert/strict";
import { setStage, findTrackBySlug, STAGES } from "./set-stage.mjs";

const page = (records, offset) => ({ ok: true, json: async () => ({ records, offset }) });
const rec = (id, slug, stage) => ({ id, fields: { slug, stage } });

test("findTrackBySlug paginates until it finds the slug (client-side match)", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    return calls.length === 1
      ? page([rec("rec1", "welcome", "live")], "off2")
      : page([rec("rec2", "career-clarity", "live")], undefined);
  };
  const hit = await findTrackBySlug({ apiKey: "k", baseId: "appX", slug: "career-clarity", fetchImpl });
  assert.equal(hit.id, "rec2");
  assert.equal(calls.length, 2);
  assert.match(calls[1], /offset=off2/);
});

test("setStage PATCHes the record with typecast and returns the transition", async () => {
  let patch;
  const fetchImpl = async (url, opts = {}) => {
    if (opts.method === "PATCH") {
      patch = { url: String(url), body: JSON.parse(opts.body) };
      return { ok: true, json: async () => ({ id: "recB" }) };
    }
    return page([rec("recB", "snt", "backlog")], undefined);
  };
  const out = await setStage({ apiKey: "k", baseId: "appX", slug: "snt", stage: "in-development", fetchImpl });
  assert.deepEqual(out, { recordId: "recB", from: "backlog", to: "in-development", fields: { stage: "in-development" } });
  assert.match(patch.url, /\/v0\/appX\/Tracks\/recB$/);
  assert.deepEqual(patch.body, { fields: { stage: "in-development" }, typecast: true });
});

test("setStage REFUSES live and points at track-publish", async () => {
  // Going live is a verified step now (track-studio's go_live: deployed content must
  // hash-match an approved version, and the capability manifest must show ignite-next can
  // render it). This script writes Airtable DIRECTLY, so leaving `live` here would have kept
  // the bypass open no matter what the MCP tool refuses — the gate would be
  // advisory-by-bypass. Replaces the old "live also sets is_live and current_version" test.
  let patched = false;
  const fetchImpl = async (url, opts = {}) => {
    if (opts.method === "PATCH") { patched = true; return { ok: true, json: async () => ({}) }; }
    return page([rec("recC", "snt", "in-development")], undefined);
  };
  await assert.rejects(
    () => setStage({ apiKey: "k", baseId: "appX", slug: "snt", stage: "live", liveVersion: "abc123def456", fetchImpl }),
    /track-publish|go_live/
  );
  assert.equal(patched, false, "a refused transition must not write anything");
});

test("setStage rejects unknown stages and missing slugs; PATCH failures throw", async () => {
  await assert.rejects(
    () => setStage({ apiKey: "k", baseId: "appX", slug: "x", stage: "shipped", fetchImpl: async () => page([], undefined) }),
    /stage must be one of/
  );
  // `live` stays in STAGES: a caller who tries it gets the explanatory refusal rather than an
  // unhelpful "not a valid stage".
  assert.deepEqual(STAGES, ["backlog", "in-development", "live", "optimization"]);
  await assert.rejects(
    () => setStage({ apiKey: "k", baseId: "appX", slug: "ghost", stage: "in-development", fetchImpl: async () => page([], undefined) }),
    /No Tracks row with slug "ghost"/
  );
  const fetchImpl = async (url, opts = {}) =>
    opts.method === "PATCH"
      ? { ok: false, status: 422, text: async () => "INVALID_MULTIPLE_CHOICE_OPTIONS" }
      : page([rec("recD", "snt", "backlog")], undefined);
  await assert.rejects(
    () => setStage({ apiKey: "k", baseId: "appX", slug: "snt", stage: "optimization", fetchImpl }),
    /Airtable 422: INVALID_MULTIPLE_CHOICE_OPTIONS/
  );
});
