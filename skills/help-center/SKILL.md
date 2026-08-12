---
name: help-center
description: Operate the NSLS self-help portal — run the HubSpot KB sync, reorder or relabel Popular Help, adjust the member and prospective guide sections, add or remove IA leaves and crosslinks, add search synonyms, retire an article, or report portal health. Use when someone says "resync the KB", "sync the help center", "add X to popular help", "reorder popular articles", "add a synonym", "remove that article from help", "retire an article", "what changed in the last sync", or "is the help center healthy". For the nsls-marketing repo only.
---

# Operating the NSLS Help Center

The portal's article bodies are a **mirror of the HubSpot KB**. This skill changes
*curation* — what is surfaced, in what order, under what label — and triggers the sync.
It never edits article bodies.

Status page: `/help/manage` shows the last sync counts, the live Popular Help order, the
synced-but-unmapped list, and a "Run sync now" button. Read it first when someone asks
"what's the state of the help center?"

## First: confirm you are in the right repo

This skill only works in the **nsls-marketing** repo (the Astro/Netlify marketing site that
owns the help portal). It is published in the builders toolkit so every builder has it, not
because it is repo-agnostic.

Before anything else:

    git -C . remote -v | grep -q "marketing-pages" && test -f src/data/help-ia.json && echo OK

If that does not print `OK`, stop and say so: "This skill operates the help portal in the
nsls-marketing repo. Open that repo (`~/nsls-marketing`) and run it there." Do not attempt
any of the operations below against another repo, and never create the data files elsewhere.


## Hard rules

0. **The HubSpot KB is the source of truth for article content.** If an article is added,
   updated, or removed there, the sync reflects it here. Where a hand-authored warm leaf and
   a synced KB article cover the same topic, **the KB article wins** and the leaf should be
   repointed at it (Julia, 2026-08-05). Never resolve the other way round.
1. **Never edit `src/content/help/*.json`.** Those are synced bodies. Every fix goes in
   `src/data/help-*.json`, `src/content/help-warm/*.md`, or `src/lib/help-render.ts`.
2. **Run `npm run help:validate` before proposing any change.** A failing validator blocks
   the PR. It catches curation that points at an article a sync renamed or dropped.
3. **Always open a PR into `staging`.** Never commit curation straight to a shared branch.
4. **Zero em dashes** in any label you write.
5. **Draft member-facing copy, never finalize it.** Julia approves every member-facing string.
6. **No Jira tickets without Julia's approval.** Assign any MP card to her at creation.

## Operations

### Resync the KB from HubSpot

The sync is already automated: `.github/workflows/help-sync.yml` runs weekly (Mondays
08:00 UTC) and on demand. It syncs, validates, builds, tests, opens a PR into `staging`,
and alerts Slack on failure. It keeps last-good content when a single article fetch fails.

To run it now:

    gh workflow run help-sync.yml --repo thensls/marketing-pages --ref staging

**`--ref` must name a branch that actually contains the workflow file.** Until the help
portal branch merges into `staging`, pass the portal branch instead
(`--ref feat/help-content-pipeline`), or the dispatch fails with "workflow does not exist".

Then check the outcome:

    gh run list --workflow help-sync.yml --repo thensls/marketing-pages --limit 1

When it finishes, read `src/content/help/_sync-report.json` on the PR branch and report the
`added` / `changed` / `unchanged` / `archived` / `failed` counts, plus `duplicateGroups`.

Two of those need action:

- **`failed`** — those articles kept their previous body, so the portal is safe but stale for
  those slugs.
- **`duplicateGroups`** — slugs whose KB bodies are byte-identical, i.e. the same article
  published at more than one KB URL. Both copies compete in search. Only the KB owners can fix
  it, in HubSpot; report it and say who needs to act.

Two duplicate classes are already handled and need no work from you: two distinct KB URLs
flattening to one slug throws a fail-loud `slug collision` error during selection, and exact
duplicate sitemap entries are deduped. `duplicateGroups` is exact-hash only, so it never
reports a false positive and it will not catch a near-duplicate that differs by a word.

**Removal is handled too:** a slug that leaves the sitemap is flipped to `status: "archived"`,
which drops it from routing and from the search index while keeping the file for history. It
is not deleted.

### Reorder, add, drop, or relabel a Popular Help tile

File: `src/data/help-top-tasks.json`. An array; **array order is render order**.

Each entry is `{ "id": "<leaf id>", "label": "<card copy>" }` with an optional
`"targetLeafId"` that re-points only the destination while keeping the entry's icon
(used today so the "Track my stole or cords" tile shows the regalia icon but links to
general order tracking).

`id` and `targetLeafId` must both be real leaf ids in `src/data/help-ia.json`.
`getTopTaskLeaves()` silently drops an entry whose `id` does not resolve, so **a typo
removes the tile rather than failing the build.** Always confirm the tile still renders
after an edit — `/help/manage` lists the resolved order, which is the fastest check.

### Adjust a guide section

Files: `src/data/help-prospective-tasks.json` today, plus
`src/data/help-member-tasks.json` once the MemberGuide ships (spec:
`docs/spec/2026-08-04-memberguide-design.md`).

Same shape: `{ comment, groups: [{ heading, blurb, tasks }] }`, where each task is
`{ "kind": "kb" | "leaf" | "url", "ref": "...", "label": "..." }`.

- `kind: "kb"` — `ref` is a synced article slug, rendering `/help/<slug>`
- `kind: "leaf"` — `ref` is an IA leaf id, resolved through `getLeafUrl()`
- `kind: "url"` — `ref` IS the absolute external URL

`validate-help-ia.mjs` fails the build on a `kb` ref with no live article, a `leaf` ref
with no such leaf, or a `url` ref that is not absolute http(s).

### Add, move, or remove an IA leaf

File: `src/data/help-ia.json`. Categories sort by `order`; leaves render in array order.
A leaf is `{ id, label, source: { type: "kb" | "warm" | "action", ref }, crosslinks?: [] }`.

Removing a leaf is how you take something out of browse. Check first whether any
`crosslinks` array elsewhere points at its id — the validator will fail the build if one
does, which is the guard working, not a problem to route around. Repoint or remove those
crosslinks in the same change.

### Add search synonyms

File: `src/data/help-synonyms.json`, a map of term → array of leaf ids. This is the
operation driven directly by data: pull the top zero-result queries from PostHog dashboard
1938788 ("Top failed searches") and add the phrasings members actually used. Adding a
synonym is the cheapest fix in the portal and needs no new article.

Every synonym target must be a real leaf id; a unit test enforces it.

### Retire an article

**You cannot delete an article from this repo.** Bodies come from HubSpot. Do both halves
and say so plainly:

1. **This repo:** remove every reference, not just the leaf. Grep the slug **and** the leaf
   id across `src/data/` — there are four kinds of pointer and missing one leaves a live
   link to a retired article:
   - the IA leaf in `help-ia.json` whose `source.ref` is the slug;
   - any `crosslinks` entry on other leaves pointing at that leaf id;
   - any **guide task** in `help-prospective-tasks.json` / `help-member-tasks.json` with
     `kind: "kb"` and `ref: "<slug>"` — these address the article directly and survive the
     leaf's deletion untouched;
   - any **Popular Help tile** in `help-top-tasks.json` naming the removed leaf id — that
     one fails silently, since `getTopTaskLeaves()` just drops what it can't resolve.
2. **HubSpot:** the article itself must be retired in the KB. The next sync then flips it
   to `status: "archived"`, at which point it drops out of search and browse.

Do not offer a "delete" that only removes the leaf. Until it is retired in HubSpot the
article stays reachable by direct URL and by search, and a hidden-but-live article is worse
than a visible one.

**Order matters, and the validator is a backstop, not the check.** `validate-help-ia.mjs`
fails the build on a `kb` ref with no live article — so a guide task you forgot surfaces as
a red build, but only *after* the HubSpot retirement and the next sync, which means the
breakage lands on whoever pushes next rather than on this change. Clear the repo-side refs
in the same PR that starts the retirement.

### Report portal health

    npm run help:validate
    scripts/verify-task.sh $(git rev-parse HEAD)

Report: validator OK or the exact orphaned keys; the four gate results; the last sync
counts from `_sync-report.json`; and the unmapped-slug warnings (articles that are synced
and search-reachable but not in browse).

## Every change ends the same way

1. `npm run help:validate`
2. `scripts/verify-task.sh $(git rev-parse HEAD)` — expect `ALL PASS`
3. Open a PR into `staging`, naming the file changed and what a reviewer should look at
4. Report what changed, and flag any member-facing copy as needing Julia's approval

Two e2e flakes are known and are not defects: the `/_demo` mobile snapshot (390 vs 427px)
and `help-helpful`, which fails on a different line each full run and passes in isolation.
Re-run `help-helpful` alone before believing it.
