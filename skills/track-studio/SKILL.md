---
name: track-studio
description: >-
  Use when a builder wants to work on a Society (ignite-next) learning track and
  needs the right tool for where the track is in its lifecycle — adding a new
  idea, building a prototype, refining for production, or optimizing a live
  track. The front door that shows what's in the Studio and hands off to the
  right skill. Triggers: "track studio", "work on a track", "open track studio",
  "I want to work on a track", "new track idea", "which track should I work on",
  "build/refine/optimize a track".
---

# track-studio

## Purpose

The single front door to the track pipeline. A builder shouldn't have to know
which of half a dozen skills to run — they should say what they want to do, see
what's already in the Studio, pick a track, and be handed the right tool with
that track's context already loaded. This skill is a **router**: it asks the
lifecycle question, reads the live Studio, and hands off. The real work stays in
the sub-skills. (The dashboard at `studio.nsls.org` is the *view* of the same
tracks; this skill is the *doer*.)

## The lifecycle map

| Builder wants to… | Hand off to | Moves the track |
|---|---|---|
| **Add an idea** | `track-brief` | → Backlog |
| **Build a prototype** | `track-design` (calls `value-moment`, then `academic-outcomes` + `prompt-pack`) | Backlog → In Development |
| **Refine for production** | `track-prototype` (walk → focus-group → score → gate) | stays In Development |
| **Take a track live / hand off to engineering** | `track-publish` (integrity gate → ignite-next issues → verified go-live) | In Development → Live |
| **Optimize a live track** | `track-optimize` *(not built yet — see below)* | Live → Optimization → Live |

> **`track-optimize` is forthcoming.** Until it ships, route an optimize request
> to an interim path: pull the live track's PostHog per-step continuation to find
> the weak step (see `/posthog`), and run `track-prototype`'s focus-group panel on
> the current content to diagnose it. Say plainly that the dedicated skill is
> coming.

## Flow

1. **Ask the lifecycle question:** *"What would you like to do — add an idea,
   build a prototype, refine for production, or optimize something live?"*
2. **Show what's in the Studio** (skip only when adding a brand-new idea). Run
   the bundled listing script — it lives in **this skill's own `scripts/`
   directory**, so run it from there (or give its full path):
   ```bash
   **Prefer the Studio MCP tools when available** (`society-studio` server, ships
   with this toolkit): `list_tracks` / `get_track` need no Airtable PAT and see
   exactly what the board sees. The script below is the fallback when the MCP
   server isn't configured (no `STUDIO_MCP_TOKEN`).

   cd "<this skill's directory>" && AIRTABLE_API_KEY=… node scripts/list_studio_tracks.mjs
   ```
   Lists every track grouped by stage (Backlog / In Development / Live /
   Optimization), with owner. Ask which one they want to work on. (Token: a PAT
   with read on base `appzDWu6GowvnACtv`; if unavailable, run `/connect` or
   `/airtable`.)
3. **Sanity-check the stage vs. the intent** (see Guardrails), then
4. **Hand off** to the matching skill, carrying whatever context the chosen track
   has: `slug`, `title`, `stage`, the location of its **`track.json`** (required
   by `track-design` / `track-prototype` / `academic-outcomes` / `prompt-pack`,
   which all read it), and any of `brief_doc_url` / `outcomes_doc_url` that exist
   (early-stage tracks legitimately have blank fields — carry what's there, don't
   wait for all of them). Tell the builder which skill you're invoking and why.

**The router is re-entrant.** Each hand-off routes to the work that moves the
track toward its next stage; the `Tracks.stage` field itself is updated in
Airtable as that work lands (e.g. `track-brief` writes `stage=backlog`; flipping
to `in-development` happens when the prototype is authored) — the router doesn't
write it. A builder whose goal is "production" from a Backlog idea passes through
`track-design` and then comes *back* here to run `track-prototype` — two hops,
not one. Say so, so their expectation is right.

## Guardrails — match intent to the track's real state

**The track's `stage` (from the listing) is the signal** — you don't need to
inspect files. The pipeline sets `stage` as a track advances (Backlog = an idea,
no `track.json` yet; In Development = a prototype exists; Live = shipped). Route
on that:

- **"Refine for production" on a Backlog track** → it's still an idea, no
  prototype exists yet. Route to `track-design` (build a prototype) first; note
  production is then a second hop through `track-prototype`.
- **"Build a prototype" on a Live track** → confirm they mean a new version /
  optimization; if so, use the optimize path (the interim workflow below, until
  `track-optimize` ships).
- **"Optimize" a track that isn't Live** → nothing to optimize yet; route to the
  step its current stage actually calls for.
- **"Add an idea" that duplicates an existing track** (same slug/title in the
  listing) → surface the existing one before creating a duplicate.

When the intent and the stage don't line up, say so and route to the step that
actually fits — don't force the mismatched hand-off.

## What this skill does NOT do

- It does not author, score, or optimize — it routes. Each sub-skill owns its work.
- It does not write to Airtable — it reads the Studio to route (stage changes are
  made by the sub-skills / in Airtable).
- It is not the dashboard — for the visual portfolio view, that's
  `studio.nsls.org`.

## Reference index
- `scripts/list_studio_tracks.mjs` — list Studio tracks by stage (reads the base the dashboard uses).
- Hand-off targets: `track-brief`, `track-design`, `value-moment`, `academic-outcomes`, `prompt-pack`, `track-prototype`, `track-publish`, `track-optimize`.
