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
GIT_TIMEOUT = 3
NET_TIMEOUT = 3


# Appended to every block. Some gates will misfire in situations we could not
# simulate, and a builder who hits a wrong block with no way to say so loses
# trust in the whole toolkit. This is the only channel through which a false
# positive becomes visible: it emits guardrail_disputed, which surfaces in
# Signal's guardrail report where Davo will actually see it.
FEEDBACK = (
    "\n\n---\n"
    "If this block looks wrong, say so — I'll log it as a disputed guardrail "
    "with what you were doing and why you think it misfired, and it goes "
    "straight to Davo. Getting these wrong is worse than not having them, so "
    "the report is genuinely useful, not a complaint form."
)


def allow():
    """Exit silently, permitting the tool call. Every error path lands here."""
    sys.exit(0)


def block(reason: str):
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


def git(*args, cwd=None):
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            cwd=cwd,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


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
    needles = (
        "nsls",
        "hubspot",
        "customer.io",
        "customerio",
        "airtable",
        "feather",
        "posthog",
    )
    try:
        for name in ("README.md", "CLAUDE.md", "DESIGN.md", "package.json",
                     "pyproject.toml", ".env.example", "requirements.txt"):
            p = Path(root) / name
            if not p.is_file():
                continue
            try:
                text = p.read_text(errors="ignore").lower()[:20000]
            except Exception:
                continue
            if any(n in text for n in needles):
                return True
    except Exception:
        pass
    return False


def tracker_get(path: str):
    try:
        import urllib.request

        req = urllib.request.Request(f"{TRACKER_URL}{path}")
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None  # network down => unknown => allow


# ---------------------------------------------------------------- gate 1

PUSH_RE = re.compile(r"\bgit\s+push\b")


def gate_personal_repo(tool: str, ti: dict):
    """NSLS work in a personal repo. Fires on push, not on every edit —
    an edit is reversible, a push publishes the code to the wrong owner."""
    cwd = None
    if tool == "Bash":
        cmd = ti.get("command") or ""
        if not PUSH_RE.search(cmd):
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
        f"Critical flag — this looks like an NSLS tool sitting in a personal "
        f"repo ({owner}). If you're away or you move on, no one else can open it.\n\n"
        f"Moving it into the NSLS org takes about a minute, keeps your entire "
        f"commit history, and you stay the owner: repo Settings → Danger Zone → "
        f"Transfer ownership → thensls. Two things worth doing in the same "
        f"sitting — scan the git history for credentials first (private repos "
        f"get no secret scanning), and add your reviewers explicitly afterwards "
        f"(org default permission is none).\n\n"
        f"NSLS policy blocks the push until then. It's not a flat no — Kevin can "
        f"authorize it staying where it is, and I can draft that note now if "
        f"you'd rather. Say the word and I'll do either."
    )


# ---------------------------------------------------------------- gate 2

DEPLOY_RE = re.compile(
    r"\b(railway\s+up|railway\s+redeploy"
    r"|netlify\s+deploy(?!.*--dry-run)"
    r"|vercel\s+(deploy\s+)?--prod"
    r"|fly\s+deploy"
    r"|gcloud\s+(run\s+deploy|functions\s+deploy)"
    r"|serverless\s+deploy"
    r"|eb\s+deploy)\b"
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

    root = repo_root()
    if not root:
        return
    name = Path(root).name
    if not name:
        return

    found = tracker_get(f"/automations?name={name}")
    if found is None:
        return  # tracker unreachable => unknown => allow

    records = found if isinstance(found, list) else found.get("automations") or []
    match = None
    for r in records:
        if isinstance(r, dict) and (r.get("name") or "").lower() == name.lower():
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
                f"I'll draft that note."
            )
        return  # registered and reviewed, or lower tier — carry on

    block(
        f"Critical flag — this deploys '{name}', and there's no record of it in "
        f"the Automation Tracker. If it misfires at 2am nobody can tell what it "
        f"is or who owns it.\n\n"
        f"Two minutes and it's sorted: I can register it and get a reviewer "
        f"assigned, then we deploy properly. Want me to do that now?\n\n"
        f"If this is genuinely urgent, Kevin can authorize shipping first — say "
        f"the word and I'll draft the note."
    )


# ---------------------------------------------------------------- gate 3

BULK_WRITE_RE = re.compile(
    r"(api\.hubapi\.com|track\.customer\.io|api\.customer\.io|api\.airtable\.com)",
    re.I,
)
WRITE_VERB_RE = re.compile(r"-X\s*(POST|PUT|PATCH|DELETE)\b", re.I)
BATCH_RE = re.compile(r"\b(batch|bulk|/records\b|import|backfill)\b", re.I)
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
        "Critical flag — this looks like a bulk write to a system of record in "
        "production, and I can't see a dry run or a rollback path.\n\n"
        "I'm not worried about the code; I'm worried about the version of this "
        "that runs twice. Before it goes: a tracker record, a reviewer, and a "
        "dry-run pass so we can see what it would touch. Want me to set those up?\n\n"
        "If it's already been reviewed and you're re-running it deliberately, "
        "re-run with --dry-run first, or ask Kevin to authorize and I'll draft "
        "the note."
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
    found = tracker_get(f"/automations?name={name}")
    if found is None:
        return

    records = found if isinstance(found, list) else found.get("automations") or []
    scope = ""
    for r in records:
        if isinstance(r, dict) and (r.get("name") or "").lower() == name.lower():
            scope = (r.get("scope") or "").lower()
            break

    if not scope or "personal" in scope:
        return  # Tier 1, or unknown — not our call

    block(
        f"Pausing on this one — '{name}' is registered as {scope}, and this adds "
        f"a non-Anthropic AI platform to it.\n\n"
        f"NSLS's default is Anthropic; it isn't dogma, it's that security review, "
        f"spend tracking and support all point one direction, and splitting them "
        f"for something a whole team depends on costs more than it looks. Going "
        f"off-platform at this scope needs a short written why plus Kevin's OK.\n\n"
        f"If there's a real reason it's the right call here — and sometimes there "
        f"is — tell me and I'll draft the memo with you now. It's a paragraph, "
        f"not a process."
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
