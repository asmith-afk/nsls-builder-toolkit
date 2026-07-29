// Advance a track's lifecycle stage on the Studio board (Airtable "Track Previews"
// base, Tracks table). This is how the pipeline keeps studio.nsls.org truthful:
// each skill writes its own transition instead of leaving stage as an unowned
// manual Airtable edit —
//   track-design (authoring starts)          → in-development
//   track-optimize (optimization flagged)    → optimization
//
// `live` is REFUSED here. Going live is a verified step: use the track-publish skill
// (Studio MCP `go_live`), which proves the deployed content hash-matches an approved,
// immutable version and that ignite-next can actually render it, then writes
// current_version AND current_version_id from that one version so they cannot disagree.
// This script writes Airtable directly, so it was the real bypass — the gate is only the
// only path if this refuses too.
//
// Reads AIRTABLE_API_KEY + AIRTABLE_BASE_ID from env (base appzDWu6GowvnACtv).
// PATCHes with typecast:true so a select option that doesn't exist yet is created
// (scoped tokens can't add options via the metadata API — see airtable gotchas).

export const STAGES = ["backlog", "in-development", "live", "optimization"];

// Find the Tracks record id for a slug. Paginates and matches client-side
// (never a field-ID filterByFormula — the silent-empty gotcha).
export async function findTrackBySlug({ apiKey, baseId, slug, fetchImpl = fetch }) {
  let offset;
  do {
    const url = new URL(`https://api.airtable.com/v0/${baseId}/Tracks`);
    url.searchParams.set("pageSize", "100");
    if (offset) url.searchParams.set("offset", offset);
    const res = await fetchImpl(url, { headers: { Authorization: `Bearer ${apiKey}` } });
    if (!res.ok) throw new Error(`Airtable ${res.status}: ${await res.text()}`);
    const data = await res.json();
    const hit = (data.records || []).find((r) => r.fields && r.fields.slug === slug);
    if (hit) return hit;
    offset = data.offset;
  } while (offset);
  return null;
}

// PATCH the stage (and, when going live, the shipped version marker). Throws on
// non-2xx — a stage transition that silently fails leaves the board lying.
export async function setStage({ apiKey, baseId, slug, stage, fetchImpl = fetch }) {
  if (!STAGES.includes(stage)) {
    throw new Error(`stage must be one of ${STAGES.join(" / ")} (got "${stage}")`);
  }
  // Refused BEFORE any read: this script writes Airtable directly, so it was the real bypass
  // around the go-live gate — refusing `live` in the Studio MCP tool alone would have left the
  // gate advisory-by-bypass.
  if (stage === "live") {
    throw new Error(
      "set-stage cannot take a track live. Going live is verified now: use the track-publish " +
        "skill (Studio MCP `go_live`), which proves the deployed content hash-matches an " +
        "approved version and that ignite-next can render it, then writes both pin fields itself."
    );
  }
  const rec = await findTrackBySlug({ apiKey, baseId, slug, fetchImpl });
  if (!rec) throw new Error(`No Tracks row with slug "${slug}" — create it first (track-brief writes the backlog row).`);
  const fields = { stage };
  const res = await fetchImpl(`https://api.airtable.com/v0/${baseId}/Tracks/${rec.id}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: JSON.stringify({ fields, typecast: true }),
  });
  if (!res.ok) throw new Error(`Airtable ${res.status}: ${await res.text()}`);
  const prev = rec.fields.stage || "(unset)";
  return { recordId: rec.id, from: prev, to: stage, fields };
}

// CLI: node set-stage.mjs <slug> <stage>
// `--live-version` is gone with the `live` transition: go_live derives the hash from the
// version it verified, so there is nothing left for a caller to pass (or to get wrong).
if (import.meta.url === `file://${process.argv[1]}`) {
  const [slug, stage] = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const apiKey = process.env.AIRTABLE_API_KEY;
  const baseId = process.env.AIRTABLE_BASE_ID;
  if (!slug || !stage || !apiKey || !baseId) {
    console.error("Usage: AIRTABLE_API_KEY=… AIRTABLE_BASE_ID=… node set-stage.mjs <slug> <stage>");
    console.error(`stages: ${STAGES.filter((s) => s !== "live").join(" / ")} (live: use the track-publish skill)`);
    process.exit(2);
  }
  const out = await setStage({ apiKey, baseId, slug, stage });
  console.log(`stage: ${slug} ${out.from} → ${out.to}` + (out.fields.current_version ? ` (current_version=${out.fields.current_version}, is_live=true)` : ""));
}
