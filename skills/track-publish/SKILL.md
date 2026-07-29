---
name: track-publish
description: >-
  Use when a builder wants to take an authored track live, hand a track off to
  engineering, or find out what shipping a track version would actually require.
  Triggers: "publish my track", "take this track live", "what does this track need
  from ignite-next", "hand this off to Red", "ship this version", "go live". Runs the
  go-live gate: integrity checks, the ignite-next readiness diff filed as issues, and
  the verified go-live step. For Society (ignite-next) tracks ONLY.
---

# Track Publish

The go-live gate. Turns "publish" from an unguarded field write into a verified step, and
turns the engineering handoff from prose someone writes once into issues that are tracked.

**This skill never deploys anything.** Studio does not ship content — ignite-next does, when
Red merges and deploys. Passing the gate is not shipping.

## Why it is two moments, not one

Content reaches members when ignite-next deploys. Studio's `stage = live` is a *record* that
this happened, not a cause of it. So publishing is two moments with Red's work in between:

```
  1. HANDOFF                    Red                     2. GO-LIVE
  what must be built    ──►  builds it   ──deploy──►  verify deployed == approved,
  filed as issues            (ignite-next)             then record it live
```

The load-bearing rule: **capability gaps are the payload at moment 1 and the blocker at
moment 2.** A track needing a component ignite-next does not have is exactly what a handoff
is *for*, so nothing about ignite-next's capabilities blocks the handoff. Those same gaps
block going live, because that is when members see them.

## Moment 1 — the handoff

### Step 1: Check

Call the Studio MCP tool (`society-studio` server):

```
publish_check(slug: "<slug>", version_record_id: "<rec…>")   # id optional: defaults to the newest approved, unpublished version
```

Read-only, safe to repeat. Returns `{ report, issue }` — the issue is the exact text that would
be filed, so the author can approve it **before anything is written**. Show, in this order:

1. **Blocking findings**, if any — each with its fix.
2. **The build estimate** — the cost summary and tier, then every advisory item.
3. **Anything not evaluated** (`notes`) — a check that did not run is not a check that passed.
4. **The issue title and body, in full** — then ask for explicit confirmation.

**Get that confirmation here, at step 1 — not after `publish_handoff`.** `publish_handoff`
writes: it sets the version's status to `publish-requested`. Asking afterwards would mean a
declined confirmation leaves a version marked as requested with no issue filed.

**If it is blocked, stop and explain.** Do not offer to work around a blocking finding.
Each maps to one action:

| Code | What it means |
|---|---|
| `no-content` | The version has no attached `track.json`. Re-save it. |
| `not-approved` | Nobody approved it, so it is still editable and its hash can change. Approve it on the track page. |
| `validation-errors` | The canonical validator found real errors. Fix the content. |
| `validation-unavailable` | The validator could not run. Unknown is not valid — find out why. |
| `synthetic-gate` | No score run with every check MET on **this exact content hash**. Run the focus group against this exact build (`track-prototype`). |

### Step 2: Record intent (only after the author has confirmed)

```
publish_handoff(slug: "<slug>", version_record_id: "<rec…>")
```

Re-runs the gate itself — it does not trust that `publish_check` was called — then sets the
version's status to `publish-requested` and returns `{ report, issue }`. It does **not** file
anything.

Use the `issue` it returns, not the one from step 1: the gate re-ran, so this is the current
text. If it now refuses, something changed between the two calls — show the findings rather
than re-using the earlier body.

If the `gh` filing in step 3 fails after this call, say plainly that the version is already
marked `publish-requested` while no issue exists yet, and that re-running the handoff is how to
retry (the marker makes it idempotent).

### Step 3: File it (once)

The body carries a hidden marker, `<!-- track-publish:<slug>:<content_hash> -->`, so
re-running the handoff on unchanged content updates the existing issue instead of opening a
second one. A gate that filed fresh every attempt would just convert a silent problem into a
noisy one.

**Write the body to a file and use `--body-file`. Never interpolate it into a quoted shell
argument.** The body contains authored track text, so an apostrophe is close to certain — and a
single quote inside `--body '…'` terminates the argument, after which the rest is read as shell
syntax. Titles too: they carry the cost summary.

```bash
BODY=$(mktemp)   # write the returned body to this file verbatim, then:

gh issue list --repo thensls/ignite-next --state open --search '<marker>' --json number,state,body
```

- **A match** → `gh issue comment <number> --repo thensls/ignite-next --body-file "$BODY"`
- **No match** → `gh issue create --repo thensls/ignite-next --title "$TITLE" --body-file "$BODY" --label track-publish`

(`--search` is safe single-quoted: the marker is `track-publish:<slug>:<hash>` — no quotes.)

A **closed** marked issue is not reused — a close means Red finished that round, so asking
again deserves a new issue. Link the closed one for context.

If `gh` is not authenticated, print the body in full so nothing is lost, and tell the author
to run `gh auth login`.

### Step 4: Stop

Red builds and deploys. **Never open or merge an ignite-next PR** — Red reviews and merges
those.

## Moment 2 — go-live

Only after Red has deployed.

```
go_live(slug: "<slug>", version_record_id: "<rec…>")
```

It verifies, then records — and it is the **only** path to live. `set_stage` refuses
`stage=live`, and so does `track-prototype/scripts/set-stage.mjs`.

There is no `live_version` argument. The hash is derived from the version that was verified,
so `current_version` and `current_version_id` are written from one source and cannot disagree.

What it refuses on, beyond the integrity checks above:

| Code | What it means |
|---|---|
| `deployed-mismatch` | What is deployed is not what was approved. Usually the deploy has not finished; sometimes the content changed after handoff. Both hashes are shown. |
| `deployed-unknown` | It could not read what is deployed. It will say why — commonly a missing `GITHUB_TOKEN` in Studio. |
| `manifest-not-fresh` | The capability manifest is stale or unverifiable, so ignite-next support cannot be proven. Regenerate (`pnpm gen:capabilities` in ignite-next) and re-vendor (`node scripts/sync-capabilities.mjs` in track-studio). |
| `capability-gap` | A field type, DB column, or runtime capability the content needs is not in ignite-next yet. These are the handoff items — they must be **deployed**, not merely closed. |

Studio reads deployed content and manifest freshness from **GitHub**, not from a local
checkout: it has none on Railway, and a stale checkout is not evidence. A manifest built from
a `staging` that was 423 commits behind was once published, quoted in a PR and an issue, and
used to "correct" a bug report that had been right all along. Only CI caught it.

## Red flags

| Thought | Reality |
|---|---|
| "The gate passed, so it's live" | The gate is not a deploy. Only ignite-next shipping makes it live. |
| "I'll file the issue and go live now" | Moment 2 is after Red deploys. It will refuse on `deployed-mismatch` anyway. |
| "The issue is closed, so we're clear" | Closing is not deploying. `go_live` checks the manifest, never issue state. |
| "`capability-gap` is blocking me — I'll drop the field type" | Maybe right, maybe you are removing the point of the track. It is the author's call, not a workaround to apply quietly. |
| "`publish_check` was clean a minute ago" | `publish_handoff` and `go_live` re-run it themselves. If they now refuse, something changed. |
| "I'll just set the stage field in Airtable" | That is the bypass this gate exists to close. If you genuinely need it, say so out loud to a human first. |

## Where this sits

`track-brief` → `track-design` → `track-prototype` → **`track-publish`** → `track-optimize`
