# Final Polish of the Installation System — master consolidation

Working file for the 2026-08-03 polish round. Owner: Davo (davowood@nsls.org).
Coordinator session: `objective-chaum-2bdc69` worktree. **Nothing here pushes,
PRs, or ships without Davo's explicit per-action approval.**

## Inputs

| Source | File | Status |
|---|---|---|
| Mac round 2 (2026-07-28 fresh-account run + Davo's review notes) | `~/Downloads/onboarding-handoff.md` | ✅ received — work queue |
| PC round 2 (2026-08-03 dry run, Davo as new builder, Windows 11) | `~/Downloads/nsls-onboarding-handoff-2026-08-03.md` | ✅ received — work queue. Findings: I-1..I-8 (guide), M-1..M-8 (master prompts, M-1 critical), T-1..T-12 (repos, T-10 critical). (An identical copy of round 1's PC file was supplied first in error — caught via checksum, discarded.) |
| PC round 1 (reference only) | `.../BK and Training Buff/PC-RUN1-DELIVERABLES.md` | Merged & live (builder-kit #109, personal-toolkit #36, tracker #7 + Railway redeploy). Used for regression checks only. |
| Backlog buffs (this chat, from the 2026-08-02 tracker session) | items 1–3 below | Fold into PR A regardless of test feedback |
| Round-2 orchestrator brief | `.../BK and Training Buff/HANDOFF-ROUND2-ORCHESTRATOR.md` | Mechanics adopted (master-prompt in-place update, guide = draft/suggestions only) |

## Delivery shape (Davo, 2026-08-03)

1. **PR A — builder kit** (`thensls/nsls-builder-toolkit`, this repo). One PR. Kevin merges (Davo has no write access; fork → upstream PR).
2. **PR B — personal toolkit** (`thensls/nsls-personal-toolkit`). One PR. Davo can self-merge.
3. **Master prompts** — edit **in place** on the two hosted Google Docs (same file IDs, bump version footer): Mac `1QCNbSv_OjCBTzeEFN5leLHbI3d3OHCCxBmVW9c-RKT4`, Windows `1X1ylhOPkGonx-Y1kMHgQR0bwRwwxON9jozSI9QBsPI8`. Explicitly authorized by Davo 2026-08-03.
4. **Installation guide** — suggestions only, nothing applied. Live guide doc (`1o3V2n2oyrdDI4SSp0YDdEOx7mqRzvhhh_zc7nfT8NdM`) stays untouched.
5. Codex review of both repo diffs before push. Pushes/PRs only on Davo's per-action word.

## PR A — builder kit worklist

| # | Item | Files | Status |
|---|---|---|---|
| A-1 | **Buff 3: session-ping transport** — curl-first POST w/ urllib fallback (python.org builds ship no CA certs → every urllib ping fails silently; cost Davo ~6 wks of session points). Same for dismiss-announcement. Failure counter on `.last-ping-failed` + one-time visible warning at 3 consecutive failures. | `hooks/session-start.py` | to do |
| A-2 | **Buff 2: /register-automation nudge** on merged-PR pings — judge-then-nudge directive (registerable = new skill/tool/service; pure bugfix = skip; unsure = include). Windows: PR-credit + stage lines currently go to a log file only — route them through the `.pending-announcements` handoff so PC builders actually see them, nudge included. Checklist item in skill-creation. | `hooks/session-start.py`, `hooks/session-ping.sh`, `hooks/session-ping.ps1`, `skills/skill-creation/SKILL.md` | to do |
| A-3 | **Buff 1: GitHub username at setup** — new Step 1.7: ask "which GitHub account do you open PRs as?" (never guess from email — wrong for every known builder), validate account exists (gh api / unauthenticated GET), sanity-check thensls PRs (zero = fine for new builders, suspicious for veterans), write `GITHUB_USERNAME` with the same .env merge pattern as BUILDER_EMAIL. Update roadmap + frontmatter. | `skills/setup/SKILL.md` | to do |
| A-4 | **C1: install.sh dies on Mac Desktop** — `CLAUDE_BIN="$(command -v claude 2>/dev/null)"` at line 274 is a bare assignment under `set -e`; kills the script before the desktop-app probe below it runs. Fix: `|| true`. | `install.sh` | to do |
| A-5 | **C2: gws installer-script URL 404s** — upstream ships only tarballs now (v0.22.5 assets confirmed: `google-workspace-cli-{aarch64,x86_64}-apple-darwin.tar.gz` + `.sha256`). Replace the `google-workspace-cli-installer.sh` one-liner with arch-detected tarball download + SHA-256 verify in all three places. | `install.sh:487`, `skills/gws/SKILL.md:41`, `skills/gdoc-edit/references/setup.md:21` | to do |
| A-6 | **C3: borderless tables** — `add_table()` never calls the `set_cell_borders()` defined 12 lines above it; comment falsely claims the table style "gives borders on import"; SKILL.md:121/:212 prescribe the broken fix. Also fix the template's hardcoded `/Users/k/` save path. | `skills/gdoc-build/templates/build_doc.py`, `skills/gdoc-build/SKILL.md` | to do |
| A-7 | **C4: gdoc-edit insert styling** — `_insert_block` styles only the title range; body inherits insertion-point style (HEADING_1 giants). Set body to NORMAL_TEXT explicitly; add `--level` flag (insert-top/after currently hardcode H2/H3); document that `replaceAllText` reports ok on zero matches + extend verification guidance beyond text-presence. | `skills/gdoc-edit/scripts/gdoc.py`, `skills/gdoc-edit/SKILL.md` | to do |
| A-8 | **C5: gdoc-edit intake** — bare invocation must ask which doc + what change; never invent an edit; offer this session's built doc as likely target. | `skills/gdoc-edit/SKILL.md` | to do |
| A-9 | **C6: fragile deps guard** — `[ -d /tmp/pptx_deps/docx ]` passes on a gutted install (macOS /tmp cleanup deletes files, keeps dirs). Guard on a real import; move target to durable `~/.local/lib/nsls-pydeps` (keep /tmp/pptx_deps on sys.path as legacy fallback). 12 occurrences across gdoc-build, scorecard-builder, academic-outcomes. | `skills/gdoc-build/{SKILL.md,templates/build_doc.py}`, `skills/scorecard-builder/{SKILL.md,references/build_doc_template.py}`, `skills/academic-outcomes/{SKILL.md,scripts/render_academic_outcomes.py,references/outcomes-json-schema.md}` | to do |
| A-10 | **C7: consent-URL wording** — setup Step 5: "A browser opens for Google consent" → prints a consent URL + local listener; surface the URL to the builder as a clickable link (belt-and-braces with master-prompt B2). | `skills/setup/SKILL.md:331` | to do |
| A-11 | **Harvest: gdoc-build Drive-connector fallback** — Davo's uncommitted live-install work: "If gws auth is unavailable" section (Drive MCP `create_file` with `text/html` → native Doc), literal-quote SyntaxError gotcha row, gws-401 gotcha row. Diff saved to scratchpad (`harvest-live-install-gdoc-build.diff`); includes local branch `pp-gdoc-build-quote-gotcha` (926a5db). | `skills/gdoc-build/SKILL.md` | to do |
| A-12 | Planning doc (this file). | `docs/planning/` | done (900f46d) |
| A-13 | **T-1: gdoc.py crashes on em dashes** — subprocess decodes gws output with the locale codec (cp1252 on Windows); pass `encoding='utf-8'` + audit other locale-dependent decodes. | `skills/gdoc-edit/scripts/gdoc.py` | to do |
| A-14 | **T-2: documented Windows `--json '{...}'` can't work in PS 5.1** — inner quotes stripped / arg splits. Rewrite with a working PS 5.1 pattern; sweep scorecard-builder + academic-outcomes for the same documented pattern; verify on PS 5.1 (Davo's PC) before ship. | `skills/gdoc-build/SKILL.md` + siblings | to do |
| A-15 | **T-3: install.ps1 Node install fails 1602 non-interactively** — report as blocking action item (not `[warn]`), remedy = elevated-shell click path, detect elevation up front. | `install.ps1` | to do |
| A-16 | **T-4 + M-3 source half: open the consent URL yourself** — never predict a browser launch; open via `open`/`start` AND always print the link. Extends C7. | `skills/setup/SKILL.md`, `skills/gdoc-edit/references/setup.md` | to do |
| A-17 | **T-6: question last, nothing trailing** — reorder setup Step 1 (disclosure first, confirmation question as final line). | `skills/setup/SKILL.md` | to do |
| A-18 | **T-7: Settings click path** — first-connector walkthrough teaches WHERE Settings is (literal click path; verify against current desktop build on the PC). | `skills/setup/SKILL.md` | to do |
| A-19 | **T-8: full identity pass** — extend Step 1.7: also ask/offer to set `git config --global user.email`/`user.name` (commit attribution ≠ tracker credit — M-4's distinction), consolidated, each skippable but asked. | `skills/setup/SKILL.md` | to do |
| A-20 | **T-9: house rule** — "question on the last line, nothing trailing" added to skill-creation; sweep /setup, /personal-setup, /gdoc-build, /gdoc-edit, /signal-setup. | `skills/skill-creation/SKILL.md` + sweep | to do |
| A-21 | **M-8 kit side: Asana joins the Step 2 connector bundle** (recommended: it's the only absent connector whose lack silently kills a headline feature). Davo can veto — flagged as product call. | `skills/setup/SKILL.md` | to do |
| — | T-5 (hardcoded /Users/k path): **already fixed** in a1d0a52 (expanduser default works on Windows unmodified). | — | done |

### Verified already fixed on main (regression check 2026-08-03 — no action)

PC-RUN1 2.1 (gh guard, install.ps1:359) · 2.2 (superpowers marketplace, .ps1:401 + .sh:351) · 2.3 (desktop CLI glob, .ps1:270 + .sh:283 — but see C1 for the .sh crash *before* the probe) · 2.4 (Python/Node/gws/VC++ provisioning, .ps1) · 2.5/2.7 (setup connector-restart discipline + breadcrumbs) · 2.8 (exit 0, .ps1:553) · 4.2 (`.install-identity` both installers + setup 1.5) · 4.3 (skill-event.sh sed extraction, no python3) · 5.1–5.6 + 5.8 (gws/gdoc docs: Windows branch, client-secret link per #99, @nsls.org note, contradiction reworded, Windows annotations, VC++ manual step) · 5.7 for `/interrogate` (OBSIDIAN_VAULT_PATH + loud skip message).

## PR B — personal toolkit worklist (verify each against current main before building)

| # | Item | Source |
|---|---|---|
| B-1 | P1: open-day step-3 handoff message leads with the command-center line, panel warning stays gated behind the symptom (~line 1057). | Mac R2 |
| B-2 | P2: `companion/cli.py` `status` kills a healthy server inside the startup grace window — retry/poll before reaping (~246–248). | Mac R2 |
| B-3 | P3: open-day step 1 launches companion with bare `&` — reword to the harness's run-in-background facility. | Mac R2 |
| B-4 | P4 (verify first): write today's note before opening the browser, or confirm self-refresh; drop the "refresh once" instruction. | Mac R2 |
| B-5 | 3.5: `?closing=1` ignored outside Command Center mode — honor `closing` in all `day.html` branches; force command mode when set; re-read note from disk. **Check against merged #36/#34/#37 first.** | PC R1 (may already be fixed) |
| B-6 | 3.6: Bonus-item Enter refocus + suggestion-row Bonus checkbox. **Check current code first.** | PC R1 (may already be fixed) |
| B-7 | 3.7: wait-done heartbeat — server flips spinner to "Claude isn't listening — say 'done' in the chat" when no listener seen. **Check current code first.** | PC R1 (may already be fixed) |
| B-8 | Buff 2 (cross-repo): same /register-automation nudge at the end of the announce-update flow. | backlog |
| B-9 | Buff 1 (cross-repo): full personal-setup writes GITHUB_USERNAME unvalidated (~line 242) — mirror the validation from builder-kit setup Step 1.7. | backlog |
| B-10 | 5.7 for `/log`: Obsidian detection via `$OBSIDIAN_VAULT_PATH`, loud message when absent. **Check — #36 claims "log vault message" fixed.** | PC R1 (likely fixed) |
| B-11 | **T-11 FIRST (before T-10): gate close-day 7a/7b** — complete-tasks and add-comment currently run unconfirmed; only additive 7c has preview→confirm. Gate both at 7c's rigor (clickable companion choice preferred, per-item decline), mirror in open-day's create_task, audit open-week/close-week/quarter-set. Fixing T-10 without this turns a dead integration into one that silently mutates task boards. | PC R2 ⚠️ |
| B-12 | **T-10: every Asana call targets a non-existent tool name** — `mcp__claude_ai_Asana__*`/`mcp__claude_ai_asana__*` hardcoded across 6 skills / 16 call sites; real connector tools are UUID-namespaced per install. Replace with intent-based references ("the Asana connector's get_my_tasks tool"), sweep ALL connectors for hardcoded `mcp__` names, add a smoke test that fails on unresolvable names. | PC R2 ⚠️ CRITICAL |
| B-13 | **T-12: verify /personal-setup GID auto-discovery** — its `get_me` call is T-10-broken; confirm fresh runs populate ASANA_*_GID, add post-setup non-empty assertion (or explicit Asana-declined path). | PC R2 (verify first) |
| B-14 | **M-8 degradation half: open-day/close-day say plainly when Asana isn't connected** ("no Asana connected — no task list today; connect via Settings › Connectors") instead of silent emptiness. | PC R2 |

## Master prompts — B1–B6 (Mac R2) + M-1..M-8 (PC R2), both docs, in place, v3 → v4

**M-1 ⚠️ CRITICAL, first:** scope the "I type every skill command myself" rule — carve out product UI (a designed affordance like Command Center Done → `/close-day` must never be refused; name that case), expire the rule when onboarding ends, narrow the phrasing to first-time teaching moments. Audit every other absolutely-phrased rule for the same leak (Step 7 browser rule is a named candidate). Merges with B3 (natural phrases count as typing).

Then: B1 narration discipline + "verbose" toggle (note: doesn't suppress requested script reviews — M-2 governs those) · **M-2 + I-2** tracking disclosure tells the truth about BOTH hooks (session-start sync: email + GitHub username + platform + auto-update-on-launch; skill-event: email + skill name) and facts always travel with the credit framing · **B2 + M-3** browser-open rule, unconditional, all three touchpoints (gws auth, connector Authorize, companion): never predict a launch, open the URL yourself (`open`/`start`), always print the clickable link, fresh link on retry · **M-4** scope the git-identity reassurance (fine for tracker credit, broken for commit attribution) + offer to set it (pairs with T-8) · **M-5** stop promising Node on Windows; on failure say it plainly + elevated path + what stays locked · **M-6** say HOW to run a surfaced command (the app's Run button on shell blocks) · **M-7** resolved by verification: /setup is idempotent by design (Edge Cases section) — instruction becomes "type /setup again after the restart; it detects what's done and continues" · **M-8** Asana added to the Step 5 connector list (pending Davo's veto) · B4 new Finish (ends, no more-skills offer) · B5 command-center line · B6 edit demo asks, never invents.

Platform idiom per doc (`open` vs `start <url>`, tray-exit, VC++ UAC step, Python-stub warning stay Windows-only). Mechanics: read each doc first, integrate with its voice, dedupe if partially present; update in place (file IDs stable — docx replace via `gws drive files update`, or gdoc-edit); bump BOTH footers v3 → v4 with a changelog line; line-by-line parity check. Verify B4's tracker-credit wording against what the hooks actually send.

## Installation guide — suggestions only, surfaced in chat (change-set file retracted 2026-08-04)

The earlier `installation-guide-change-set.md` was anchored to the superseded local draft (INSTALLATION-GUIDE-DRAFT.md v2) — retracted. The real guide is the published artifact "NSLS Builder Toolkit — Installation Guide" (claude.ai artifact `484d34f5`, regenerated from its Google-Doc source via instructional-design; Davo links it as start.nsls.org/installation…). Checked live 2026-08-04: master-prompt links intact (both doc IDs), "Ten skills worth trying next" already present (old G-9 was moot). Remaining suggestions are small — troubleshooting buffs (Node/admin-shell in the dashboard entry, two-hook wording parity with v4, VC++ "one thing" softened), +Asana in the connector list, a one-line Steps-3–7 numbering reconcile, time-estimate honesty, Projects-folder how-to, footer still says "Draft v2". Surfaced in chat 2026-08-04; applied only on Davo's word, in the Google-Doc source, then regenerate.

## Parked / deferred / watch

- **Proxy (tracker) items** — parked per Davo: poller 30-PR window (backlog #4, do NOT re-credit #43/#86), 4.4 install-event dedupe. Action only if a proxy PR happens anyway; Kevin deploys.
- **C8** — setup Step 5 GCP question: gate/move to /deployment-guide, but the 2026-04-13 spec records it as deliberate — confirm with its author first. Not in PR A.
- **Instructional-design skill** — PR #125 open, not merged. Register via /register-automation **when it ships** (gdoc visual companion + gdoc-edit were registered 2026-08-02).
- ~~PC round 2 deliverable — missing~~ — supplied 2026-08-03 (`nsls-onboarding-handoff-2026-08-03.md`) and fully folded in.
- **gdoc-edit comment extension** (INBOX spec, Jul 31) — status unclear; not in scope unless Davo says so.
- Noticed in passing: session-start hook worst case (git pull 10s + replay 35s + live ping 35s) sits at the 90s budget edge — fine today, revisit if timeouts reappear.

## Status — 2026-08-04, pushes approved

Everything above is **built, locally committed, and Codex-reviewed (one round
per repo; review-driven fixes folded in)**. Builder kit: 14 commits on
`claude/objective-chaum-2bdc69`, pushed to the fork + PR opened for Kevin
2026-08-04 on Davo's approval. Personal toolkit: 7 commits on `pp-final-polish`
(~/worktrees/pt-final-polish), companion suite 304 green, pushed + PR opened
(Davo self-merges). Master prompts v4 live on both docs (in place, verified).
Guide v3 proposal (troubleshooting buffs + small fixes) built via
instructional-design, awaiting Davo's approval to replace the live artifact.

**T-2 revision (2026-08-04):** Davo's first PS 5.1 spot-check caught the
escape-only `--json` recipe splitting at spaces inside values — WinPS 5.1's
binder counts the escaped quotes, treats the whitespace as already quoted, and
skips wrapping. Recipe rewritten to env-var + `--%` stop-parsing in all three
doc files (gws SKILL, gdoc-build SKILL + upload-recipes); validated by
simulating the 5.1 binder + CommandLineToArgvW. This commit is HELD off the PR
until Davo's on-box re-test passes.

**Known limitations accepted this round:** gdoc.py's pre-existing
regex-replace index mapping still counts code points (new insert ranges are
UTF-16-correct); install.sh picks gnu Linux artifacts (musl/Alpine now fails
honestly instead of silently — asset selection not built); B-6 bonus-refocus
deferred (needs interactive repro). **Human verification still owed:** T-2
re-test (revised `--%` recipe) + Settings click path on a real PS 5.1 box; the
Mac handoff's 16-point dual-platform simulation once pushes land.

## Verification before "done"

Mac handoff's 16-point dual-platform simulation checklist runs after edits land (both master prompts + repos). Companion test suite (~301 at last count) stays green for PR B. `bash -n` / `py_compile` / pwsh parse for every touched script.
