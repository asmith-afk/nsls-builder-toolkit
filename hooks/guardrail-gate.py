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
import subprocess
import sys
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


def emit(event_type: str, description: str, automation: str = ""):
    """Fire-and-forget guardrail event. Never raises, never affects the decision.

    Payload contract with POST /guardrail-event on the tracker proxy:

        {"builder_email": str, "event_type": str, "description": str,
         "automation_name": str, "repo_url": str}

    written to the Events table as Event Type / Description / Builder /
    Automation. `Event Type` is free text, so no Airtable schema change is
    needed; the proxy enforces a `guardrail_` prefix.

    `repo_url` exists because `automation_name` is a directory name
    ("mex-tools") while Airtable's Name is human-entered ("MEx Tools"), so
    name matching alone leaves most events with no build attached — and an
    event trail that can't say which build tripped the gate is most of the
    value gone. The Automations table already has a GitHub Repo URL field,
    which is an exact key rather than a guess.
    """
    try:
        import urllib.request

        email = builder_email()
        if not email:
            return
        body = json.dumps(
            {
                "builder_email": email,
                "event_type": event_type,
                "description": description[:500],
                "automation_name": automation,
                "repo_url": origin_url() or "",
            }
        ).encode()
        req = urllib.request.Request(
            f"{TRACKER_URL}/guardrail-event",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=EMIT_TIMEOUT).read()
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
    return [r for r in recs if isinstance(r, dict)]


# ---------------------------------------------------------------- gate 1

PUSH_RE = re.compile(r"\bgit\s+push\b")
# A push that publishes nothing isn't the moment we care about. Matched only
# within the push invocation itself (not across ; | &&) so an unrelated later
# command can't wave the gate through. Codex review 2026-08-15.
PUSH_HARMLESS_RE = re.compile(r"\bgit\s+push\b[^|;&]*?(--dry-run|--help|\s-n\b)")


def gate_personal_repo(tool: str, ti: dict):
    """NSLS work in a personal repo. Fires on push, not on every edit —
    an edit is reversible, a push publishes the code to the wrong owner."""
    cwd = None
    if tool == "Bash":
        cmd = ti.get("command") or ""
        if not PUSH_RE.search(cmd):
            return
        if PUSH_HARMLESS_RE.search(cmd):
            return
    elif tool in ("Write", "Edit"):
        return  # editing locally is fine; the push is the moment that matters
    else:
        return

    root = repo_root(cwd)
    if not root:
        return
    url = origin_url(root)
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
    if not DEPLOY_RE.search(cmd) or DEPLOY_HARMLESS_RE.search(cmd):
        return

    root = repo_root()
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

    records = tracker_records(f"/automations?name={name}")
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
WRITE_VERB_RE = re.compile(r"-X\s*(POST|PUT|PATCH|DELETE)\b", re.I)
# The marker has to appear inside the URL, not anywhere in a compound command.
# That's what makes "import" safe to keep: `.../customers/import` is a real bulk
# endpoint, while `... && python import_data.py` sits outside any URL and no
# longer matches. Codex review 2026-08-15 flagged the unscoped version.
BATCH_RE = re.compile(r"https?://\S*\b(batch|bulk|backfill|import|/records)\b", re.I)
DRYRUN_RE = re.compile(r"--dry[-_]?run|\bDRY_RUN=(1|true)\b", re.I)


def gate_bulk_production_write(tool: str, ti: dict):
    """Production write at scale.

    Deliberately narrow: a system-of-record host AND a mutating verb AND a
    batch/bulk marker AND no dry-run flag. A single-record POST is normal work
    and must not trip this.
    """
    if tool != "Bash":
        return
    cmd = ti.get("command") or ""
    if DRYRUN_RE.search(cmd):
        return
    if not (
        BULK_WRITE_RE.search(cmd)
        and WRITE_VERB_RE.search(cmd)
        and BATCH_RE.search(cmd)
    ):
        return

    block(
        "Critical flag — this writes to a production system of record in bulk, "
        "with no dry run and no rollback path I can see. I'm not worried about "
        "the code; I'm worried about the version of this that runs twice.\n\n"
        "A dry-run pass first shows what it would touch — want me to set that "
        "up? Kevin can also authorize it as-is, and I'll draft that note.",
        gate="bulk_production_write",
    )


# ---------------------------------------------------------------- gate 4

OFF_PLATFORM_RE = re.compile(
    r"(from\s+openai\s+import|import\s+openai\b|require\(['\"]openai['\"]\)"
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
    body = ti.get("content") or ti.get("new_string") or ""
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
        f"off-platform at this scope needs a short written why plus Kevin's OK.\n\n"
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
