#!/usr/bin/env python3
"""
guardrail-gate.py — PreToolUse hook implementing the four NSLS hard gates.

Skills can't block. They're description-matched, so a builder who never types a
trigger phrase never meets one. This hook is deterministic: it sees every Bash,
Write and Edit call regardless of what the builder said.

The four gates (see CLAUDE.md § Builder Guardrails):
  1. NSLS work in a personal repo        — git remote isn't an NSLS org
  2. Tier 3 ship with no tracker record  — deploying member-facing, unowned
  3. Production write at scale           — bulk writes, no reviewer, no rollback
  4. Off-platform at Tier 2+             — non-Anthropic SDK on a shared build

DESIGN RULES, in priority order:

*   **Fail open, always.** Every failure path allows the action. A guardrail
    that bricks someone's session costs more trust than the risk it averts.
    Unparseable input, no network, no git, missing config — allow.
*   **False positives are the failure mode.** A gate that fires when it
    shouldn't teaches builders to route around the toolkit, and then it
    protects nobody. Every pattern here is deliberately narrow. When in doubt,
    stay silent.
*   **Never a flat no.** Each block states the policy AND the way through,
    including the authorization route. See _shared/references/guardrail-voice.md.
*   **Escape hatch.** NSLS_GUARDRAILS_DISABLED=1 turns everything off. A gate
    with no off-switch is a gate that gets uninstalled.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

TRACKER_URL = os.environ.get(
    "NSLS_TRACKER_URL", "https://web-production-6281e.up.railway.app"
)
NSLS_ORGS = ("thensls",)

# The hook's total budget is 10s (hooks.json). Every subprocess and socket here
# has to fit inside it *cumulatively*, because a gate can chain several: repo
# lookup, then a tracker lookup, then the event POST on the way out. Blowing the
# budget means the harness kills the hook mid-decision and the block is lost —
# the gate silently fails to fire. These numbers are picked so the worst path
# (gate 2: repo_root + tracker_get + emit) lands near 6s, leaving headroom on a
# slow network. Raise them and redo that arithmetic.
GIT_TIMEOUT = 2
NET_TIMEOUT = 3
EMIT_TIMEOUT = 1.5


# Appended to every block. Some gates will misfire in situations we could not
# simulate, and a builder who hits a wrong block with no way to say so loses
# trust in the whole toolkit. This is the only channel through which a false
# positive becomes visible: it emits guardrail_disputed, which surfaces in
# Signal's guardrail report where Davo will actually see it.
FEEDBACK = (
    "\n\n---\n"
    # Two clauses here are load-bearing and were lost in the first length trim.
    # "why you think it misfired" is the reason the dispute event is worth
    # emitting at all -- without it the report says a gate fired and nothing
    # about whether it should have. "not a complaint form" is what makes a
    # builder willing to use it; people who think they're filing a complaint
    # against the tooling mostly just don't.
    "If this block looks wrong, say so — I'll log what you were doing and why "
    "you think it misfired, straight to Davo. Genuinely useful, not a "
    "complaint form: getting these wrong is worse than not having them."
)


def builder_email():
    """Same precedence as session-start.py and skill-event.sh."""
    try:
        cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
        env_file = cfg / "local-plugins" / "nsls-personal-toolkit" / ".env"
        if env_file.is_file():
            for line in env_file.read_text(errors="ignore").splitlines():
                if line.startswith("BUILDER_EMAIL="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return git("config", "user.email")


# Reporting comes from the shared emitter so the payload contract with
# POST /guardrail-event lives in exactly one file (guardrail_emit.py). It used
# to be inlined here, which is how the gate ended up the only thing in the
# toolkit that emitted anything at all, and how the docstring describing the
# payload drifted out of date.
#
# Imported defensively: fail open is the first design rule above, and a hook
# that cannot import its reporting module must still make the decision. A gate
# that fires without recording is worth far more than one that does not fire.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from guardrail_emit import emit_detached as _emit
except Exception:  # pragma: no cover - reporting is optional, deciding is not
    def _emit(*a, **k):
        return ""


def emit(event_type: str, description: str, automation: str = ""):
    """Fire-and-forget guardrail event. Never raises, never affects the decision.

    Deduplication is off here. Every hard block is a distinct event worth a row
    even when the same gate stops the same build twice in a day -- a builder
    hitting a wall repeatedly is the signal, and collapsing it would hide the
    gate most in need of a second look.

    Detached, because the endpoint takes ~1.5s and this hook has 10s for the
    whole decision. The previous version waited inline on a 1.5s timeout, which
    means the block events we believed were being recorded were landing about
    half the time. EMIT_TIMEOUT in guardrail_emit.py has the measurements.
    """
    log = os.environ.get("NSLS_GUARDRAIL_EVENT_LOG")
    if log:
        # Test seam. Never set in normal use: the tests need to count events
        # per decision (a double-fire writes TWO guardrail_blocked rows, which
        # would corrupt the very metric the gates are measured by) and that
        # cannot be asserted against a detached network POST.
        try:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": event_type,
                                     "description": description,
                                     "automation": automation}) + "\n")
        except Exception:
            pass
        return
    try:
        _emit(event_type, description, automation=automation, dedupe=False)
    except Exception:
        pass  # reporting is never worth failing or delaying a decision over


def allow():
    """Exit silently, permitting the tool call. Every error path lands here."""
    sys.exit(0)


def block(reason: str, gate: str = "", automation: str = ""):
    emit("guardrail_blocked", f"{gate}: {reason.splitlines()[0]}", automation)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason + FEEDBACK,
                }
            }
        )
    )
    sys.exit(0)


# ---------------------------------------------------------------- helpers


_GIT_CACHE = {}


def git(*args, cwd=None):
    """Memoised per process. Three gates ask for the repo root independently;
    without the cache that's three subprocesses against the same 10s budget."""
    key = (args, cwd)
    if key in _GIT_CACHE:
        return _GIT_CACHE[key]
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            cwd=cwd,
        )
        val = out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        val = ""
    _GIT_CACHE[key] = val
    return val


def repo_root(start=None):
    return git("rev-parse", "--show-toplevel", cwd=start) or ""


def origin_url(cwd=None):
    return git("remote", "get-url", "origin", cwd=cwd)


def is_nsls_remote(url: str) -> bool:
    """True only for a confidently-NSLS remote.

    Unknown hosts return True (allow) on purpose — this decides whether to
    BLOCK, so ambiguity must resolve to silence.
    """
    if not url:
        return True
    low = url.lower()
    if "github.com" not in low:
        return True  # not GitHub; not our call to make
    m = re.search(r"github\.com[:/]+([^/]+)/", low)
    if not m:
        return True
    return m.group(1) in NSLS_ORGS


def looks_like_nsls_work(root: str) -> bool:
    """Narrow test for 'this repo is NSLS work'.

    Requires positive evidence — an NSLS system named in tracked config or
    docs. A personal scratch repo with no NSLS fingerprints is none of our
    business, and treating it as ours is exactly the false positive that
    makes builders resent the toolkit.
    """
    if not root:
        return False
    # "nsls" alone is decisive. The SaaS names are not — plenty of people use
    # Airtable or PostHog for their own projects, and blocking someone's
    # weekend build is exactly the false positive that gets the toolkit
    # uninstalled. So they only count as evidence in pairs. (Tightened after
    # Codex review 2026-08-15 flagged the fingerprints as too broad.)
    decisive = ("nsls",)
    corroborating = (
        "hubspot",
        "customer.io",
        "customerio",
        "airtable",
        "feather",
        "posthog",
    )
    try:
        seen = set()
        for name in ("README.md", "CLAUDE.md", "DESIGN.md", "package.json",
                     "pyproject.toml", ".env.example", "requirements.txt"):
            p = Path(root) / name
            if not p.is_file():
                continue
            try:
                text = p.read_text(errors="ignore").lower()[:20000]
            except Exception:
                continue
            if any(n in text for n in decisive):
                return True
            seen.update(n for n in corroborating if n in text)
        # customer.io/customerio are the same system; don't let them pair up.
        if "customer.io" in seen and "customerio" in seen:
            seen.discard("customerio")
        return len(seen) >= 2
    except Exception:
        pass
    return False


MAX_BODY = 1 << 20  # 1 MiB — a tracker reply is a few KB; anything else is wrong


def tracker_records(path: str):
    """Fetch automation records.

    Returns a LIST on a well-formed reply, or None for "I don't know".

    The distinction is load-bearing. Callers block on an empty list (the tracker
    positively said there's no such automation) and stay silent on None. So any
    reply we can't confidently parse — HTTP error, unreadable body, a 200
    carrying an error object, an unexpected shape — must be None. Codex review
    2026-08-15 caught the original returning [] for a malformed 200, which turned
    a tracker hiccup into a denied deploy: a fail-open violation.
    """
    try:
        import urllib.request

        req = urllib.request.Request(f"{TRACKER_URL}{path}")
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
            raw = r.read(MAX_BODY)
        data = json.loads(raw.decode(errors="replace"))
    except Exception:
        return None

    if isinstance(data, list):
        recs = data
    elif isinstance(data, dict):
        if "automations" not in data:
            return None  # unrecognised shape — do not infer "none found"
        recs = data.get("automations")
    else:
        return None

    if not isinstance(recs, list):
        return None
    # A list with a non-dict inside is a half-garbled reply. Filtering the
    # garbage out silently turned "temporary error" strings into an empty
    # result — which callers read as "positively no record" and BLOCKED on.
    # Fail-open rule: anything not confidently parsed is "I don't know".
    for r in recs:
        if not isinstance(r, dict):
            return None
    return recs


# ── Command segmentation ────────────────────────────────────────────────────
# Four Macroscope findings on PR #157 shared one root cause: the gates matched
# RAW COMMAND TEXT. So `echo 'git push origin main'` read as a push, a harmless
# `git push --help` in one segment vouched for a real push after the semicolon,
# `--dry-run` anywhere disabled the bulk-write gate for the whole line, and
# `cd elsewhere && railway up` was judged against the shell's cwd instead of
# the directory actually being deployed. The fix is one idea applied
# everywhere: split the command into the segments that actually execute, and
# judge each segment by its own tokens — where a quoted string is ONE token,
# so text inside quotes can never look like a command.

_SEG_BREAKS = frozenset({";", "&&", "||", "|", "&", "\n"})


def command_segments(cmd: str):
    """Token lists for each independently-executed segment, quotes resolved.

    Returns None when the command cannot be tokenized (unbalanced quotes,
    heredocs). Callers must then fall back to their old whole-string
    behaviour — degraded precision, never a crash.
    """
    # Newlines separate commands exactly like semicolons, but shlex eats them
    # as whitespace — so a two-line command folded into ONE segment, and an
    # `echo --dry-run` on line one excused the real write on line two.
    # Tokenize per line; a quoted string that spans lines fails that line's
    # parse, and one failed line fails the whole command into the callers'
    # conservative whole-string fallback.
    segments = []
    heredoc_end = None  # inside a heredoc: skip body lines until the delimiter
    for line in cmd.splitlines():
        if heredoc_end is not None:
            if line.strip() == heredoc_end:
                heredoc_end = None
            continue  # heredoc BODY is data — tokenizing it as commands made
            # a heredoc that merely CONTAINED "git push origin main" block
        # The delimiter is a WORD, and bash words include -, ., + and more.
        # `\w+` truncated `END-1` to `END`, so the terminator line never
        # matched, heredoc mode never exited, and every command after it was
        # skipped — silently disabling all four gates for the rest of the
        # command. A gate that can be switched off by a hyphen is not a gate.
        m_here = re.search(r"""<<-?\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z0-9_.+-]+))""", line)
        if m_here:
            heredoc_end = m_here.group(1) or m_here.group(2) or m_here.group(3)
            line = line[:m_here.start()]  # the command part before << still counts
        if not line.strip():
            continue
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=";|&")
            lex.whitespace_split = True
            tokens = list(lex)
        except ValueError:
            return None
        current = []
        for tok in tokens:
            if tok and all(c in ";|&" for c in tok):
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(tok)
        if current:
            segments.append(current)
    return segments


_WRAPPERS = frozenset({"env", "command", "exec", "nohup", "nice", "time"})
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def strip_wrappers(seg):
    """Drop leading VAR=… assignments and transparent wrappers.

    `RAILWAY_TOKEN=$T railway up` and `command git push origin main` are the
    same actions with the executable not at seg[0]; anchoring there let both
    walk past the gates. `env -i` style flags after `env` are dropped too.
    Fail-open by construction: stripping can only EXPOSE an executable to the
    gates, never hide one.
    """
    i = 0
    while i < len(seg) and _ASSIGN_RE.match(seg[i]):
        i += 1
    while i < len(seg) and seg[i] in _WRAPPERS:
        i += 1
        while i < len(seg) and seg[i].startswith("-"):
            i += 1
        while i < len(seg) and _ASSIGN_RE.match(seg[i]):
            i += 1
    return seg[i:]


def walk_segments(cmd: str):
    """Yield (effective_cwd, tokens) per segment, tracking `cd` between them.

    effective_cwd is None until a cd is seen (meaning: the hook's own cwd).
    Relative cd targets resolve against the previous effective cwd. `git -C
    <dir> …` is handled by the caller, since it scopes one invocation only.
    """
    segs = command_segments(cmd)
    if segs is None:
        return None
    out, cwd = [], None
    for seg in segs:
        seg = strip_wrappers(seg)  # `MODE=prod cd dir` is still a cd
        if seg and seg[0] == "cd":
            if len(seg) == 1:
                cwd = str(Path.home())
            else:
                target = os.path.expanduser(seg[1])
                base = cwd or os.getcwd()
                resolved = target if os.path.isabs(target) else os.path.normpath(
                    os.path.join(base, target))
                # A cd to a directory that doesn't exist FAILS in the shell —
                # the next command runs in the OLD directory (`;`) or not at
                # all (`&&`). Tracking the bogus target instead made
                # repo_root("") come back empty and waved the push through.
                if os.path.isdir(resolved):
                    cwd = resolved
            continue
        out.append((cwd, seg))
    return out


def _git_invocation(seg):
    """(is_git, effective_dir_flag, args_after_global_flags) for one segment."""
    seg = strip_wrappers(seg)
    if not seg or seg[0] != "git":
        return False, None, []
    i, gitdir = 1, None
    while i < len(seg):
        tok = seg[i]
        if tok == "-C" and i + 1 < len(seg):
            gitdir = seg[i + 1]
            i += 2
        elif tok.startswith("--work-tree="):
            gitdir = tok.split("=", 1)[1]
            i += 1
        elif tok == "--work-tree" and i + 1 < len(seg):
            gitdir = seg[i + 1]
            i += 2
        elif tok.startswith("--git-dir="):
            # the repo is the .git dir's parent — pushing via --git-dir was a
            # clean walk past a gate that only knew -C
            gitdir = gitdir or os.path.dirname(tok.split("=", 1)[1].rstrip("/")) or "."
            i += 1
        elif tok == "--git-dir" and i + 1 < len(seg):
            gitdir = gitdir or os.path.dirname(seg[i + 1].rstrip("/")) or "."
            i += 2
        elif tok.startswith("-"):
            i += 1
        else:
            break
    return True, os.path.expanduser(gitdir) if gitdir else None, seg[i:]


# ---------------------------------------------------------------- gate 1

# Loose on purpose: `git -C <dir> push` and `git -c k=v push` put options
# between the words, and the old tight form returned before the tokenizer ever
# saw them. Precision lives in _git_invocation; this only has to not miss.
PUSH_RE = re.compile(r"\bgit\b[^|;&\n]*\bpush\b")
# A push that publishes nothing isn't the moment we care about. Matched only
# within the push invocation itself (not across ; | &&) so an unrelated later
# command can't wave the gate through. Codex review 2026-08-15.
PUSH_HARMLESS_RE = re.compile(r"\bgit\s+push\b[^|;&]*?(--dry-run|--help|\s-n\b)")


def gate_personal_repo(tool: str, ti: dict):
    """NSLS work in a personal repo. Fires on push, not on every edit —
    an edit is reversible, a push publishes the code to the wrong owner."""
    cwd = None
    push_remote = ""
    if tool == "Bash":
        cmd = ti.get("command") or ""
        if not PUSH_RE.search(cmd):
            return  # cheap pre-filter before any tokenizing
        walked = walk_segments(cmd)
        if walked is None:
            # Untokenizable (heredoc, unbalanced quote): old whole-string
            # behaviour rather than no gate at all.
            if PUSH_HARMLESS_RE.search(cmd):
                return
        else:
            push_cwd, found = None, False
            for seg_cwd, seg in walked:
                is_git, gitdir, args = _git_invocation(seg)
                if not is_git or "push" not in args:
                    continue  # `echo 'git push …'` is one quoted token, not git
                if any(a in ("--dry-run", "--help", "-n") for a in args):
                    continue  # harmless — but only for THIS segment
                # A relative -C/--work-tree resolves against the shell's
                # tracked cd, not the hook's own directory — `cd /x && git -C
                # service push` targets /x/service.
                if gitdir and not os.path.isabs(gitdir):
                    gitdir = os.path.normpath(
                        os.path.join(seg_cwd or os.getcwd(), gitdir))
                found, push_cwd = True, (gitdir or seg_cwd)
                # `git push <remote> …` names its destination; a second remote
                # pointing at a personal account slipped past a check that only
                # ever read origin.
                after = args[args.index("push") + 1:]
                push_remote = next((a for a in after if not a.startswith("-")), "")
                break
            if not found:
                return
            cwd = push_cwd
    elif tool in ("Write", "Edit"):
        return  # editing locally is fine; the push is the moment that matters
    else:
        return

    root = repo_root(cwd)
    if not root:
        return
    url = origin_url(root)
    if push_remote and push_remote != "origin" and not push_remote.startswith(
            ("http://", "https://", "git@")):
        named = git("remote", "get-url", push_remote, cwd=root)
        if named:
            url = named
    elif push_remote.startswith(("http://", "https://", "git@")):
        url = push_remote  # pushing straight to a URL names the destination itself
    if is_nsls_remote(url):
        return
    if not looks_like_nsls_work(root):
        return

    owner = "your personal account"
    m = re.search(r"github\.com[:/]+([^/]+)/([^/\s.]+)", url or "")
    if m:
        owner = f"{m.group(1)}/{m.group(2)}"

    block(
        f"Critical flag — this looks like an NSLS tool in a personal repo "
        f"({owner}). If you're away or you move on, no one else can open it.\n\n"
        f"Moving it to the NSLS org takes about a minute, keeps your full "
        f"history, and you stay the owner. Or Kevin can authorize it staying "
        f"put — I'll draft that note now if you'd rather.\n\n"
        f"Which one?",
        gate="personal_repo",
        automation=Path(root).name,
    )


# ---------------------------------------------------------------- gate 2

DEPLOY_RE = re.compile(
    r"\b(railway\s+up|railway\s+redeploy"
    r"|netlify\s+deploy"
    r"|vercel\s+(deploy\s+)?--prod"
    r"|fly\s+deploy"
    r"|gcloud\s+(run\s+deploy|functions\s+deploy)"
    r"|serverless\s+deploy"
    r"|eb\s+deploy)\b"
)
# The first token a deploy segment must start with. Anchoring here is what
# separates a command from a mention of one.
DEPLOY_BINARIES = frozenset(
    {"railway", "netlify", "vercel", "fly", "gcloud", "serverless", "eb"}
)

# Reading the docs, rehearsing, or shipping to a preview target isn't shipping
# to members. Codex review 2026-08-15 flagged `railway up --help` blocking.
DEPLOY_HARMLESS_RE = re.compile(
    r"--help|-h\b|--dry-run|--alias|--preview|\bnetlify\s+deploy(?!.*--prod)",
    re.I,
)


def gate_unregistered_ship(tool: str, ti: dict):
    """Tier 3 ship with no tracker record.

    Only blocks when the tracker positively reports no record. Network failure,
    an unparseable response, or an unnamed repo all fall through to allow.
    """
    if tool != "Bash":
        return
    cmd = ti.get("command") or ""
    if not DEPLOY_RE.search(cmd):
        return

    deploy_cwd = None
    walked = walk_segments(cmd)
    if walked is None:
        # Untokenizable: old whole-string behaviour.
        if DEPLOY_HARMLESS_RE.search(cmd):
            return
    else:
        found = False
        for seg_cwd, seg in walked:
            # Anchor on the segment's own binary so `echo 'railway up'` — one
            # quoted token under echo — can never read as a deploy, and a
            # `railway --help` segment can't vouch for the real deploy after
            # the semicolon.
            seg = strip_wrappers(seg)
            if not seg or seg[0] not in DEPLOY_BINARIES:
                continue
            seg_str = " ".join(seg)
            if not DEPLOY_RE.search(seg_str) or DEPLOY_HARMLESS_RE.search(seg_str):
                continue
            found, deploy_cwd = True, seg_cwd
            break
        if not found:
            return

    # Judge the repo the deploy actually runs in. `cd /path/to/service &&
    # railway up` deploys THAT service; the shell's own cwd is irrelevant and
    # judging it let an unregistered service ship from anywhere.
    root = repo_root(deploy_cwd)
    if not root:
        return
    name = Path(root).name
    if not name:
        return

    # Only NSLS work is our business. Without this, every personal side project
    # deployed from a laptop gets blocked for not being in the NSLS tracker —
    # which is both wrong and the fastest way to lose builders. Codex review
    # 2026-08-15.
    if not looks_like_nsls_work(root):
        return

    # Encoded, or a repo named `member-sync&v2` becomes two query fields, the
    # lookup finds nothing, and a REGISTERED service gets blocked as unknown.
    from urllib.parse import quote

    records = tracker_records(f"/automations?name={quote(name, safe='')}")
    if records is None:
        return  # unreachable or unparseable => unknown => allow

    match = None
    for r in records:
        if (r.get("name") or "").lower() == name.lower():
            match = r
            break

    if match:
        scope = (match.get("scope") or "").lower()
        reviewer = match.get("reviewer")
        if "company" in scope and not reviewer:
            block(
                f"Critical flag — '{name}' is registered as Company-wide but has "
                f"no reviewer assigned, and this deploys it.\n\n"
                f"Anything member-facing needs a second set of eyes before it "
                f"ships. Kevin covers member-facing and usually turns these round "
                f"inside a day. Want me to assign him and request review now? "
                f"If it's genuinely urgent he can authorize the deploy instead — "
                f"I'll draft that note.",
                gate="tier3_no_reviewer",
                automation=name,
            )
        return  # registered and reviewed, or lower tier — carry on

    block(
        f"Critical flag — this deploys '{name}', and there's no record of it in "
        f"the Automation Tracker. If it misfires at 2am nobody can tell what it "
        f"is or who owns it.\n\n"
        f"Two minutes and it's sorted: I can register it and get a reviewer "
        f"assigned, then we deploy properly. Want me to do that now?\n\n"
        f"If this is genuinely urgent, Kevin can authorize shipping first — say "
        f"the word and I'll draft the note.",
        gate="tier3_unregistered",
        automation=name,
    )


# ---------------------------------------------------------------- gate 3

BULK_WRITE_RE = re.compile(
    r"(api\.hubapi\.com|track\.customer\.io|api\.customer\.io|api\.airtable\.com)",
    re.I,
)
# -X, --request, and curl's data flags (which imply POST with no verb flag at
# all) — the tight -X-only form let `--request DELETE` and `-d @rows.json`
# bulk writes straight past the prefilter.
WRITE_VERB_RE = re.compile(
    r"(-X\s*|--request[\s=])(POST|PUT|PATCH|DELETE)\b"
    r"|(^|\s)(-d|--data(-\w+)?|--json)([\s=]|$)",
    re.I,
)
# The marker has to appear inside the URL, not anywhere in a compound command.
# That's what makes "import" safe to keep: `.../customers/import` is a real bulk
# endpoint, while `... && python import_data.py` sits outside any URL and no
# longer matches. Codex review 2026-08-15 flagged the unscoped version.
BATCH_RE = re.compile(r"(https?://)?\S*\b(batch|bulk|backfill|import|/records)\b", re.I)
DRYRUN_RE = re.compile(r"--dry[-_]?run|\bDRY_RUN=(1|true)\b", re.I)

# Airtable base IDs are "app" + 14 chars and appear directly in the URL path.
AIRTABLE_RE = re.compile(r"api\.airtable\.com", re.I)
AIRTABLE_BASE_RE = re.compile(r"\bapp[A-Za-z0-9]{14}\b")

# Bases the builder has told us are sandboxes. One ID per line, # for comments.
#
# Airtable has no separate sandbox host -- a test base and the real one are both
# api.airtable.com and differ only by base ID -- so the gate cannot tell them
# apart on its own. Before this list, rehearsing a bulk write against a copy got
# blocked, which punished exactly the careful behaviour we want people to have.
#
# An allowlist of DECLARED test bases rather than a list of known production
# ones: we don't have a reliable inventory of NSLS's production bases, and
# inverting it would silently un-protect every base nobody had got round to
# listing. This way the default stays "block", and a builder who hits it once
# says "that's my sandbox" and is never bothered about that base again.
# Overridable so the scenario suite can point at a throwaway file. The suite is
# hermetic by design (it already stubs the tracker over loopback); a test that
# rewrote the builder's real allowlist would be changing what the gate lets
# through on their machine.
TEST_BASES_FILE = Path(
    os.environ.get("NSLS_AIRTABLE_TEST_BASES_FILE")
    or (Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
        / ".nsls-airtable-test-bases")
)


def declared_test_bases():
    try:
        lines = TEST_BASES_FILE.read_text().splitlines()
    except Exception:
        return set()  # no file, unreadable => nothing declared => block as before
    return {
        ln.strip() for ln in lines
        if ln.strip() and not ln.strip().startswith("#")
    }


def only_hits_test_bases(cmd: str) -> bool:
    """True only when this command is Airtable-only AND every base in it is declared.

    Conservative on every axis. If the command also touches HubSpot or
    Customer.io, a declared Airtable base is irrelevant. If no base ID is
    visible -- the common case of `$AIRTABLE_BASE_ID` from the environment --
    we cannot know which base it is, so it does not qualify.
    """
    if not AIRTABLE_RE.search(cmd):
        return False
    if re.search(r"(api\.hubapi\.com|track\.customer\.io|api\.customer\.io)", cmd, re.I):
        return False
    # Only base IDs appearing in an Airtable REQUEST URL count. Scanning the
    # whole command let a declared sandbox ID sitting anywhere else -- a comment,
    # an unrelated argument, or the JSON payload -- vouch for a write whose real
    # target was a production base held in a shell variable. That turned the
    # "this is my sandbox" declaration into a way to switch the gate off.
    found = {
        base
        for url in re.findall(r"https?://\S+", cmd)
        if AIRTABLE_RE.search(url)
        for base in AIRTABLE_BASE_RE.findall(url)
    }
    if not found:
        return False
    return found <= declared_test_bases()


def _segment_is_bulk_write(seg) -> bool:
    """Does THIS segment perform an un-rehearsed bulk production write?

    Judged entirely on the segment's own tokens: the target hosts and batch
    markers must appear in tokens that ARE URLs (so a URL quoted inside an
    echo string or a JSON payload never counts — and a sandbox URL inside the
    payload can't vouch for the request either), the mutating verb must be a
    real curl-style flag token, and a dry-run flag only excuses the segment it
    is actually part of. `echo --dry-run; curl -X POST …` was disabling the
    gate for the whole command line.
    """
    # curl accepts scheme-less URLs and sends the same request, so a token
    # counts as a request URL if it carries a scheme OR is host-shaped for one
    # of the gated systems. Quoted payloads stay excluded: a JSON token starts
    # with '{', not a hostname.
    url_toks = [
        t for t in seg
        if t.lower().startswith(("http://", "https://"))
        or re.match(r"^(api\.airtable\.com|api\.hubapi\.com|track\.customer\.io"
                    r"|api\.customer\.io)/", t, re.I)
    ]
    if not url_toks:
        return False
    urls = " ".join(url_toks)
    if not (BULK_WRITE_RE.search(urls) and BATCH_RE.search(urls)):
        return False

    verb = False
    for i, t in enumerate(seg):
        if re.fullmatch(r"-X(POST|PUT|PATCH|DELETE)", t, re.I):
            verb = True
        elif t in ("-X", "--request") and i + 1 < len(seg) and re.fullmatch(
                r"POST|PUT|PATCH|DELETE", seg[i + 1], re.I):
            verb = True
        elif re.fullmatch(r"-d|--data(-\w+)?|--json", t):
            verb = True  # curl sends POST for data flags with no verb at all
    if not verb:
        return False

    # Everything after curl's `--` marker is a URL, not an option — so a
    # `--dry-run` sitting there does not make the POST a rehearsal, it just
    # names a path. Only tokens BEFORE the marker can excuse the write.
    option_tokens = seg[:seg.index("--")] if "--" in seg else seg
    if any(DRYRUN_RE.fullmatch(t) or DRYRUN_RE.search(t) and t.startswith("--")
           or re.fullmatch(r"DRY_RUN=(1|true)", t, re.I) for t in option_tokens):
        return False

    # Sandbox rehearsal: every base named in this segment's request URLs is a
    # declared test base, and none of the URLs reach HubSpot / Customer.io.
    if re.search(r"(api\.hubapi\.com|track\.customer\.io|api\.customer\.io)",
                 urls, re.I):
        return True
    if AIRTABLE_RE.search(urls):
        found = set(AIRTABLE_BASE_RE.findall(urls))
        if found and found <= declared_test_bases():
            return False
    return True


def gate_bulk_production_write(tool: str, ti: dict):
    """Production write at scale.

    Deliberately narrow: a system-of-record host AND a mutating verb AND a
    batch/bulk marker AND no dry-run flag. A single-record POST is normal work
    and must not trip this.
    """
    if tool != "Bash":
        return
    cmd = ti.get("command") or ""
    if not (
        BULK_WRITE_RE.search(cmd)
        and WRITE_VERB_RE.search(cmd)
        and BATCH_RE.search(cmd)
    ):
        return  # cheap pre-filter; precise judgement is per-segment below

    walked = walk_segments(cmd)
    if walked is None:
        # Untokenizable: the old whole-string checks.
        if DRYRUN_RE.search(cmd):
            return
        if only_hits_test_bases(cmd):
            return
    else:
        if not any(_segment_is_bulk_write(seg) for _, seg in walked):
            return

    block(
        "Critical flag — this writes to a production system of record in bulk, "
        "with no dry run and no rollback path I can see. I'm not worried about "
        "the code; I'm worried about the version of this that runs twice.\n\n"
        "A dry-run pass first shows what it would touch — want me to set that "
        "up? Kevin can also authorize it as-is, and I'll draft that note.\n\n"
        "If this is a test base, tell me and I'll remember it — you won't be "
        "stopped on it again.",
        gate="bulk_production_write",
    )


# ---------------------------------------------------------------- gate 4

OFF_PLATFORM_RE = re.compile(
    r"(from\s+openai\s+import|import\s+openai\b|require\(['\"]openai['\"]\)"
    r"|import\s+(\{[^}]{0,120}\}\s+from\s+)?['\"]openai['\"]"
    r"|from\s+['\"]openai['\"]|api\.openai\.com"
    r"|generativelanguage\.googleapis\.com|from\s+mistralai|import\s+cohere\b)",
    re.I,
)


def gate_off_platform(tool: str, ti: dict):
    """Off-platform at Tier 2+.

    Needs the build's scope, which lives in the tracker. Unknown scope => allow;
    we do not block a personal experiment for using another vendor.
    """
    if tool not in ("Write", "Edit"):
        return
    # Documentation quoting `from openai import OpenAI` is prose, not a
    # platform choice — a README example was getting the same block as real
    # code. Judge only files that execute.
    path = str(ti.get("file_path") or "").lower()
    name = Path(path).name
    if (path.endswith((".md", ".mdx", ".markdown", ".rst", ".txt", ".adoc"))
            or "/docs/" in path
            or name.startswith(("readme", "changelog", "license", "contributing"))):
        return
    body = ti.get("content") or ti.get("new_string") or ""
    # Drop comment lines before matching: "# migrate from openai import later"
    # is a note, not an SDK. String literals stay matchable on purpose —
    # imports inside strings are usually codegen writing real code.
    body = "\n".join(
        l for l in body.splitlines()
        if not l.lstrip().startswith(("#", "//", "--", "*", "/*"))
    )
    if not OFF_PLATFORM_RE.search(body):
        return

    root = repo_root()
    if not root:
        return
    name = Path(root).name
    records = tracker_records(f"/automations?name={name}")
    if records is None:
        return

    scope = ""
    for r in records:
        if (r.get("name") or "").lower() == name.lower():
            scope = (r.get("scope") or "").lower()
            break

    # Positive confirmation of Tier 2+ only. Previously any unrecognised scope
    # string ("", "n/a", "tbd") fell through to a block; Codex review
    # 2026-08-15 caught it. Unknown scope is not evidence of anything.
    if not ("department" in scope or "company" in scope):
        return

    block(
        f"Pausing on this one — '{name}' is registered as {scope}, and this adds "
        f"a non-Anthropic AI platform to it.\n\n"
        f"NSLS's default is Anthropic; it isn't dogma, it's that security review, "
        f"spend tracking and support all point one direction, and splitting them "
        f"for something a whole team depends on costs more than it looks. Going "
        f"off-platform at this scope needs a short written why, which Kevin "
        f"then authorizes — the same authorization route as any other flag.\n\n"
        f"If there's a real reason it's the right call here — and sometimes there "
        f"is — tell me and I'll draft the memo with you now. It's a paragraph, "
        f"not a process.",
        gate="off_platform",
        automation=name,
    )


# ---------------------------------------------------------------- main

GATES = (
    gate_personal_repo,
    gate_unregistered_ship,
    gate_bulk_production_write,
    gate_off_platform,
)


_INFLIGHT_DIR = Path(
    os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")
) / ".nsls-gate-inflight"
# Comfortably above the hook's own 10s timeout, so a slow winner is never
# overtaken; comfortably below any interval at which a builder could produce a
# genuinely new call carrying the same id (Claude Code does not reuse them).
_INFLIGHT_TTL = 90
_TOOL_USE_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")


def _sweep_inflight():
    """Drop markers nothing will ever look at again. Bounded and best-effort."""
    try:
        cutoff = time.time() - (_INFLIGHT_TTL * 4)
        for i, entry in enumerate(_INFLIGHT_DIR.iterdir()):
            if i > 200:
                return
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
            except OSError:
                continue
    except Exception:
        pass


def already_deciding(tool_use_id) -> bool:
    """True when another copy of this hook already owns this exact tool call.

    A machine can carry two live registrations of this gate at once: the
    plugin's hooks.json entry and a settings.json entry the installer wrote
    before the migration stopped stripping it. The docs are explicit that a
    plugin's copy of a handler "stays separate" from a settings.json copy —
    both run, in parallel. Two decisions would be survivable; two
    `guardrail_blocked` rows per block would not, because emit() deliberately
    does not deduplicate and those rows are the only measure the gates have.

    The marker is deliberately NOT removed when the decision finishes. Removing
    it reopens the race it exists to close: the winner can finish before the
    loser has even started, and the loser would then claim a free marker and
    decide again. It ages out instead.

    Every failure path here returns False — deciding twice is a bad day;
    skipping a decision because a marker could not be written is a hole.
    """
    tid = tool_use_id if isinstance(tool_use_id, str) else ""
    if not _TOOL_USE_ID_RE.match(tid):
        return False  # no usable id — decide, rather than skip a decision
    marker = _INFLIGHT_DIR / tid
    try:
        _INFLIGHT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(_INFLIGHT_DIR, 0o700)
        except OSError:
            pass
        for _ in range(2):
            try:
                os.close(os.open(str(marker),
                                 os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
                _sweep_inflight()
                return False  # we own this call
            except FileExistsError:
                try:
                    if time.time() - marker.stat().st_mtime <= _INFLIGHT_TTL:
                        return True  # a live sibling owns it
                    marker.unlink()  # abandoned; try once more to claim it
                except OSError:
                    return True
    except Exception:
        return False
    return False


def normalize_call(tool: str, ti: dict):
    """Show the gates the shapes they were written against.

    The matcher admits five tool names; the gates read three. MultiEdit carries
    its text in edits[].new_string and NotebookEdit in new_source, so without
    this both are a silent bypass of gate 4 — the tool call is inspected, finds
    no `content` or `new_string`, and is waved through.
    """
    if tool == "MultiEdit":
        parts = []
        edits = ti.get("edits")
        if isinstance(edits, list):
            for e in edits:
                if isinstance(e, dict) and isinstance(e.get("new_string"), str):
                    parts.append(e["new_string"])
        return "Edit", {"file_path": ti.get("file_path"),
                        "new_string": "\n".join(parts)}
    if tool == "NotebookEdit":
        source = ti.get("new_source")
        return "Edit", {"file_path": ti.get("notebook_path") or ti.get("file_path"),
                        "new_string": source if isinstance(source, str) else ""}
    return tool, ti


def main():
    if os.environ.get("NSLS_GUARDRAILS_DISABLED") == "1":
        allow()

    try:
        payload = json.load(sys.stdin)
    except Exception:
        allow()

    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        allow()

    if already_deciding(payload.get("tool_use_id")):
        allow()

    tool, ti = normalize_call(tool, ti)

    for gate in GATES:
        try:
            gate(tool, ti)
        except SystemExit:
            raise
        except Exception:
            continue  # one broken gate never takes down the rest

    allow()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        allow()
