#!/usr/bin/env python3
"""
session-start.py — Cross-platform SessionStart hook for the NSLS Builder Toolkit.

Runs on every Claude Code session start. Does three things:
1. git pull the toolkit to get latest updates
2. Sync skill pointers from the plugin to ~/.claude/skills/
3. Ping the automation tracker for points, PR credits, and announcements

Must be fast and fail silently. Works on Mac, Linux, and Windows.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
# Respect CLAUDE_CONFIG_DIR (Claude Code passes it through to hook processes),
# falling back to ~/.claude. Keeps a --test install fully isolated: the test
# copy of this hook operates on the test config dir, never the real one.
CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (HOME / ".claude"))
PLUGIN_DIR = CONFIG_DIR / "local-plugins" / "nsls-builder-toolkit"
SKILLS_DIR = CONFIG_DIR / "skills"
ENV_FILE = CONFIG_DIR / "local-plugins" / "nsls-personal-toolkit" / ".env"
PROXY_URL = os.environ.get("NSLS_TRACKER_URL", "https://web-production-6281e.up.railway.app")

# When a session-ping can't be delivered (timeout / network / proxy down), we
# stash the payload here and replay it at the start of the next session so a
# queued announcement or credit isn't lost. Deleted once delivery succeeds.
PING_FAIL_MARKER = PLUGIN_DIR / ".last-ping-failed"
# was 8, then 20 — live measurement (2026-07-03): /session-ping takes ~8s WARM
# (server-side Airtable writes + announcement scan) and 15-27s on Railway cold
# start, so 20 was still marginal. The SessionStart hook budget must stay
# comfortably above this (install.sh sets 60).
PING_TIMEOUT = 35

# Plugins to sync, in precedence order — earlier entries win on name collision.
SYNC_PLUGINS = [
    "nsls-builder-toolkit",
    "nsls-personal-toolkit",
]
MARKERS = tuple(f"local-plugins/{p}" for p in SYNC_PLUGINS)


# A bare block-scalar indicator is not a description. If `description: >-` (or
# `|`) has no indented body, the value is empty — the indicator itself must
# never become the description text.
BLOCK_INDICATORS = (">", ">-", ">+", "|", "|-", "|+")

# One left-to-right pass over a double-quoted scalar's escapes. Single-pass
# matters: chained .replace() calls would decode the output of an earlier
# replacement (\\" would collapse to " and lose its backslash).
_DQ_ESCAPE = re.compile(r"\\x([0-9a-fA-F]{2})|\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})|\\(.)")
_DQ_SIMPLE = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "n": "\n",
              "v": "\v", "f": "\f", "r": "\r", "e": "\x1b",
              # The four named Unicode escapes YAML defines beyond the C set:
              # next-line, non-breaking space, line separator, paragraph
              # separator. Decoded faithfully; the collapse below folds all four
              # to spaces (\x85 via _CONTROL, the rest because str.split treats
              # them as whitespace), which is what a YAML value folded onto a
              # single line should become.
              "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029"}

# Decoded control characters (NUL, BEL, ESC…) would make the generated pointer's
# frontmatter unparseable, so they're mapped to spaces and folded away by the
# whitespace collapse. \t \n \r are deliberately absent — they're whitespace and
# the collapse already handles them.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _dq_unescape(match):
    for group in (1, 2, 3):
        if match.group(group):
            return chr(int(match.group(group), 16))
    ch = match.group(4)
    # Anything else (\" \\ \/ \space) stands for itself.
    return _DQ_SIMPLE.get(ch, ch)


def unquote_scalar(value):
    """Turn a single-line YAML scalar into the string a YAML parser would give.

    The folded-block branch never sees quotes, but a description written as
    `description: "Brain dump…"` reaches the single-line fallback with its
    delimiters attached, and they end up verbatim in the generated pointer.
    We can't just call a YAML parser here — pyyaml isn't guaranteed on a fresh
    machine, which is why this extraction is hand-rolled in the first place.

    Whitespace is collapsed at the end because the caller embeds the result as
    a single indented line under `description: >-`. A decoded `\\n` left as a
    real newline would break the generated frontmatter, so folding it to a
    space is both safe and what the folded-block branch already does.
    """
    v = value.strip()
    if v in BLOCK_INDICATORS:
        return ""
    quote = v[:1]
    if len(v) >= 2 and v[-1:] == quote and quote in ('"', "'"):
        inner = v[1:-1]
        if quote == '"':
            inner = _DQ_ESCAPE.sub(_dq_unescape, inner)
        else:
            # Single-quoted YAML has exactly one escape: '' is a literal quote.
            inner = inner.replace("''", "'")
        v = inner
    return " ".join(_CONTROL.sub(" ", v).split())


def git_pull():
    """Pull latest changes for every toolkit in SYNC_PLUGINS.

    Parity fix with the Windows hook: session-start.ps1 has always looped
    @($BuilderDir, $PersonalDir) and pulled both, but this function pulled only
    the builder dir — so on macOS/Linux the personal toolkit was cloned once and
    then frozen at install-time state forever. Fixes shipped upstream (like the
    visual-companion self-heal) never reached those machines. SYNC_PLUGINS
    already names both toolkits for pointer sync; pull the same list.

    Bare `pull --ff-only` — no explicit remote/refspec — follows each
    checkout's configured upstream, the same convention personal-setup's own
    update path uses. Hardcoding `origin main` here would silently fast-forward
    a supported fork checkout (NSLS_PERSONAL_REPO / NSLS_PERSONAL_BRANCH) or a
    deliberately pinned detached HEAD onto a branch it never tracked; with no
    upstream configured, a bare pull just exits nonzero and the checkout is
    left alone. --ff-only matches the .ps1: the `pull origin main` this
    replaces could stop on merge conflicts (leaving a conflicted tree) or, on
    modern git with no reconcile config, refuse divergence outright — neither
    visible here, since the exit status is ignored and output captured, while
    the toolkit quietly never updated again. ff-only refuses cleanly instead
    of half-merging.

    Prompts are disabled (GIT_TERMINAL_PROMPT=0, stdin closed) so a remote
    that wants credentials fails in milliseconds instead of hanging out the
    timeout, and the loop shares one 15s deadline so the worst case — every
    pull wedged — still leaves the 35s replay + 35s live ping inside the 90s
    hook budget install.sh configures.
    """
    deadline = time.monotonic() + 15
    for plugin in SYNC_PLUGINS:
        plugin_dir = CONFIG_DIR / "local-plugins" / plugin
        if not (plugin_dir / ".git").exists():
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            subprocess.run(
                ["git", "-C", str(plugin_dir), "pull", "--ff-only", "--quiet"],
                capture_output=True, timeout=min(10, remaining),
                stdin=subprocess.DEVNULL,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except Exception:
            pass


def org_plugin_installed():
    """True once the toolkit is installed as a real Claude Code plugin."""
    try:
        # utf-8-sig: tolerate a UTF-8 BOM (PowerShell-written files carry one).
        registry = json.loads(
            (CONFIG_DIR / "plugins" / "installed_plugins.json").read_text(
                encoding="utf-8-sig"
            )
        )
        return any(
            key.startswith("nsls-builder-toolkit@")
            for key in registry.get("plugins", {})
        )
    except Exception:
        return False


def org_plugin_active():
    """Installed AND not explicitly disabled.

    The distinction matters: a user who disables the plugin must fall back to
    the pointer-stub path (the disabled plugin can't deliver skills), so
    anything that hands responsibility over to the plugin gates on active,
    never on merely installed.
    """
    if not org_plugin_installed():
        return False
    try:
        settings = json.loads(
            (CONFIG_DIR / "settings.json").read_text(encoding="utf-8-sig")
        )
        for key, enabled in settings.get("enabledPlugins", {}).items():
            if key.startswith("nsls-builder-toolkit@") and enabled is False:
                return False
    except Exception:
        pass
    return True


def run_plugin_migration():
    """Run the shim→plugin migration from the just-pulled clone.

    Executed from the clone (not this file's own copy) so migration fixes
    take effect one session after landing on main. On plugin-only machines
    the clone is absent and this is a no-op. Fail-open: a broken migration
    must never break the session — shims keep working and we retry next
    session.

    Bounded: the migration's CLI calls are individually timed out but their
    sum was not, and stage A's worst case (30 + 60 + 60) is nearly double the
    whole 90s SessionStart budget install.sh configures. Overrunning kills the
    hook, which also drops sync_pointers and the session ping — so a slow
    migration would quietly cost the builder pointer updates and credit.

    Budget arithmetic for the 90s hook: git_pull takes up to 15s and the live
    session_ping up to 35s (PING_TIMEOUT), so ~40s is genuinely spare;
    ensure_plugin_fresh claims 20s of it. 25s here leaves headroom for
    sync_pointers and keeps the common path well inside budget. A first
    migration may need more than one session to finish, which is exactly how
    the stages are built — both are idempotent and resume next session.
    """
    script = PLUGIN_DIR / "hooks" / "migrate_to_plugin.py"
    if not script.exists():
        return
    try:
        code = compile(script.read_text(encoding="utf-8"), str(script), "exec")
        exec(code, {
            "__name__": "nsls_migrate",
            "__file__": str(script),
            # Consumed by migrate_to_plugin.py as its cumulative ceiling.
            "_NSLS_MIGRATION_DEADLINE": time.monotonic() + 25,
        })
    except Exception:
        pass


def ensure_plugin_fresh():
    """At most once a day, ask the CLI to sync the installed plugin.

    Plugin installs run from a version-pinned cache that only refreshes via
    `claude plugin update` after a plugin.json version bump — without this,
    a machine that loses the settings-shim git-pull path would silently
    freeze on an old version.
    """
    if not org_plugin_active():
        return
    marker = CONFIG_DIR / ".nsls-plugin-update-check"
    try:
        if marker.exists() and (
            datetime.now(timezone.utc).timestamp() - marker.stat().st_mtime < 86400
        ):
            return
        import shutil as _shutil
        claude = _shutil.which("claude")
        if not claude:
            return
        marker.touch()
        # 20s, not the hook's whole 90s budget — a hung update must leave room
        # for sync_pointers and the session pings behind it. On timeout the
        # marker is already touched, so the next attempt is tomorrow; releases
        # just arrive a day later on that machine.
        subprocess.run(
            [claude, "plugin", "update", "nsls-builder-toolkit@nsls-toolkit"],
            capture_output=True, timeout=20,
        )
    except Exception:
        pass


def sync_pointers():
    """Sync skill pointers from installed plugins to ~/.claude/skills/.

    Iterates plugins in SYNC_PLUGINS precedence order. On name collision,
    earlier plugins win (org skills override personal). Skips skills that
    look user-customized (no managed marker present in the existing pointer).
    """
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    written = set()
    created = 0

    for plugin_name in SYNC_PLUGINS:
        # Once the org toolkit is an ACTIVE plugin, its skills load through
        # the plugin system — stop regenerating its pointer stubs so the
        # stage-B migration cleanup sticks. Gates on active, not installed:
        # a disabled plugin can't deliver skills, so those users keep the
        # stub path. Personal-toolkit pointers keep syncing regardless.
        if plugin_name == "nsls-builder-toolkit" and org_plugin_active():
            continue
        plugin_dir = CONFIG_DIR / "local-plugins" / plugin_name
        skills_src = plugin_dir / "skills"
        if not skills_src.is_dir():
            continue

        for skill_dir in sorted(skills_src.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill = skill_dir.name

            # Skill name is interpolated into a bash literal in the generated
            # pointer (see report_cmd below). Reject names with characters
            # that would break the JSON or shell quoting.
            if any(c in skill for c in "'\"\\$`\n\r"):
                print(f"sync: skipping skill with unsafe name: {skill!r}", file=sys.stderr)
                continue

            # Org-wins precedence: skip if a higher-precedence plugin
            # already wrote this skill in the current run.
            if skill in written:
                continue

            src = skill_dir / "SKILL.md"
            if not src.exists():
                continue

            dest = SKILLS_DIR / skill
            dest_skill = dest / "SKILL.md"

            # Skip if the existing file looks user-customized — i.e., no
            # managed marker for any of our plugins is present.
            if dest.is_dir() and dest_skill.exists():
                try:
                    existing = dest_skill.read_text(encoding="utf-8")
                    if not any(m in existing for m in MARKERS):
                        continue
                except Exception:
                    continue

            try:
                content = src.read_text(encoding="utf-8")
            except Exception:
                continue

            name_match = re.search(r"^name:\s*(.+)", content, re.MULTILINE)
            if not name_match:
                continue
            name = name_match.group(1).strip()

            desc = f"{plugin_name} skill: {skill}"
            fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if fm_match:
                fm = fm_match.group(1)
                # `*` not `+`: an empty folded block still belongs to the folded
                # branch. With `+` it fell through to the fallback, which then
                # captured the literal `>-` as the description.
                ml_match = re.search(r"description:\s*>-?\s*\n((?:[ \t]+.+\n?)*)", fm)
                if ml_match:
                    extracted = " ".join(l.strip() for l in ml_match.group(1).strip().split("\n"))
                else:
                    sl_match = re.search(r"description:[ \t]*(.+)", fm, re.MULTILINE)
                    extracted = unquote_scalar(sl_match.group(1)) if sl_match else ""
                # Only override the default when we actually recovered text —
                # a blank or `""` description must not produce a blank pointer.
                if extracted.strip():
                    desc = extracted

            dest.mkdir(parents=True, exist_ok=True)
            hook_path = CONFIG_DIR / "local-plugins" / "nsls-builder-toolkit" / "hooks" / "skill-event.sh"
            skill_path = CONFIG_DIR / "local-plugins" / plugin_name / "skills" / skill / "SKILL.md"
            report_cmd = (
                f"echo '{{\"tool_input\":{{\"skill\":\"{skill}\"}}}}' | "
                f"bash {hook_path}"
            )
            dest_skill.write_text(
                f"---\nname: {name}\ndescription: >-\n  {desc}\n---\n\n"
                f"Before reading the skill, run this Bash command exactly once in the "
                f"background (do not wait, do not announce, do not retry on failure) "
                f"to record skill usage:\n\n"
                f"```bash\n{report_cmd}\n```\n\n"
                f"Then read and follow the full skill at "
                f"`{skill_path}`.\n",
                encoding="utf-8",
            )
            written.add(skill)
            created += 1

    if created > 0:
        print(f"{created} skill pointers synced", file=sys.stderr)


def read_env(key):
    """Read a value from the personal toolkit .env file."""
    if not ENV_FILE.exists():
        return ""
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _http_post_json(url, body, timeout):
    """POST JSON to url and return the parsed JSON response. Raises on failure.

    curl first, urllib as the fallback — not the other way around: python.org
    framework builds ship WITHOUT CA certificates, so every urllib HTTPS call
    on such a Mac fails cert verification and the ping dies silently (this
    cost a builder ~6 weeks of session points, June–Aug 2026, while
    skill-event.sh — which shells out to curl — kept working). curl uses the
    OS trust store, so it works on a stock install.
    """
    payload = json.dumps(body)
    if shutil.which("curl"):
        # curl PRESENT is not curl WORKING. A broken proxy/TLS config, or a curl
        # that can't reach this host while Python can, made every POST fail
        # permanently — the old code raised here, so the urllib fallback below
        # was only ever reached when curl was missing entirely. Treat a curl
        # failure as "try the other transport", and only fail if both lose.
        started = time.monotonic()
        try:
            result = subprocess.run(
                ["curl", "-s", "--fail", "--max-time", str(timeout), "-X", "POST",
                 url, "-H", "Content-Type: application/json",
                 "--data-binary", payload],
                # encoding is explicit: text=True alone decodes with the platform
                # locale, so on Windows with a legacy code page (cp1252) a
                # non-ASCII announcement raises UnicodeDecodeError out of this
                # call. A ping that actually succeeded then counts as failed,
                # the failure marker gets written, and the announcement is lost.
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout + 10,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
            # 28 == curl's own operation-timeout. The host is slow or
            # unreachable, so urllib would burn the same wait again for the same
            # answer — and this runs inside a SessionStart hook whose whole
            # budget (90s, install.sh) covers a replayed ping AND a live one.
            # Retrying only NON-timeout failures is what keeps a second
            # transport from doubling the worst case.
            if result.returncode == 28:
                raise RuntimeError("curl exited 28 (timeout)")
        except subprocess.TimeoutExpired:
            raise RuntimeError("curl timed out")
        except (OSError, ValueError):
            pass  # curl unusable or returned unparseable JSON — try urllib
        # Only the remaining slice of this call's budget, for the same reason.
        timeout = max(5, timeout - (time.monotonic() - started))
    req = urllib.request.Request(
        url,
        data=payload.encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _post_session_ping(body, timeout=PING_TIMEOUT):
    """POST a session-ping body dict. Returns parsed response, or raises."""
    return _http_post_json(f"{PROXY_URL}/session-ping", body, timeout)


def replay_failed_ping():
    """Replay a previously failed session-ping before the current one.

    Runs at session start, ahead of the live ping. If delivery succeeds (or
    the marker is malformed), the marker is cleared; if it fails again, the
    marker is left in place for the next session to retry. We deliberately do
    not re-surface the replayed response — the live ping right after fetches
    fresh announcements, so processing the stale body here would double up.

    Returns the successfully replayed payload (dict) or None. The caller uses
    it to skip the live ping when the payloads are identical — the endpoint is
    slow (~8s warm), so a redundant back-to-back POST both wastes time and
    risks a pointless timeout that would re-write the marker.
    """
    if not PING_FAIL_MARKER.exists():
        return None
    try:
        saved = json.loads(PING_FAIL_MARKER.read_text(encoding="utf-8"))
        body = saved.get("payload")
        if body:
            _post_session_ping(body)
        PING_FAIL_MARKER.unlink()
        return body
    except Exception:
        return None  # still unreachable — keep the marker for the next attempt


def session_ping(replayed=None):
    """Ping the automation tracker for points, PR credits, and announcements.

    replayed: payload dict just delivered by replay_failed_ping(), or None.
    If it matches today's payload, the session is already recorded — skip the
    redundant POST (the payload carries no timestamp; the server stamps
    arrival time, so a successful replay IS today's ping).
    """
    email = read_env("BUILDER_EMAIL")
    if not email:
        try:
            result = subprocess.run(
                ["git", "config", "user.email"],
                capture_output=True, text=True, timeout=5
            )
            email = result.stdout.strip()
        except Exception:
            pass
    if not email:
        return

    github = read_env("GITHUB_USERNAME")

    toolkit = "personal"
    if PLUGIN_DIR.exists() or org_plugin_installed():
        toolkit = "both"

    platform_map = {"darwin": "mac", "win32": "windows", "linux": "linux"}
    platform = platform_map.get(sys.platform, sys.platform)

    body = {
        "builder_email": email,
        "toolkit": toolkit,
        "github_username": github,
        "platform": platform,
    }

    if replayed == body:
        return  # this exact payload was just delivered by the replay

    try:
        data = _post_session_ping(body)
    except Exception:
        # Delivery failed (timeout / network / proxy down). Stash the payload
        # so the next session start replays it. Best-effort — never raise.
        failures = 1
        try:
            prior = json.loads(PING_FAIL_MARKER.read_text(encoding="utf-8"))
            failures = int(prior.get("failures", 1)) + 1
        except Exception:
            pass
        try:
            PING_FAIL_MARKER.parent.mkdir(parents=True, exist_ok=True)
            PING_FAIL_MARKER.write_text(
                json.dumps({
                    "payload": body,
                    "attempted_at": datetime.now(timezone.utc).isoformat(),
                    "failures": failures,
                }),
                encoding="utf-8",
            )
        except Exception:
            pass
        # One visible heads-up per failure streak (the marker resets on any
        # success). Silent-forever is how a CA-cert breakage went unnoticed
        # for six weeks — the builder must eventually hear about it.
        if failures == 3:
            print(
                "[NSLS Builder Toolkit — surface the following to the user "
                "at the start of your first reply, then proceed with their "
                "request:]\n\n"
                "Heads up: the NSLS automation tracker hasn't been reachable "
                "for your last 3 sessions, so daily session points aren't "
                "being recorded. If your network is otherwise fine, mention "
                "this in #builders so it gets looked at."
            )
        return

    # Delivered — clear any stale failure marker from a prior session.
    try:
        PING_FAIL_MARKER.unlink()
    except OSError:
        pass

    output = []

    # PR credits
    for pr in data.get("new_pr_credits", []):
        repo = pr.get("repo", "?")
        pr_num = pr.get("pr", "?")
        output.append(f"Your PR #{pr_num} to {repo} was merged.")

    # Stage advancement
    adv = data.get("stage_advanced")
    if adv:
        output.append(f"You advanced to {adv.get('to', '?')} on the builder path.")

    # Announcements
    for ann in data.get("announcements", []):
        title = ann.get("title", "")
        body = ann.get("body", "")
        output.append(f"{title}: {body}")
        # Dismiss (same curl-first transport as the ping — the urllib CA-cert
        # failure mode applies here too, and a failed dismiss re-delivers the
        # announcement every session).
        ann_id = ann.get("id", "")
        if ann_id:
            try:
                _http_post_json(
                    f"{PROXY_URL}/dismiss-announcement",
                    {"announcement_id": ann_id, "builder_email": email},
                    5,
                )
            except Exception:
                pass

    if output:
        # Wrap with a directive prefix so the announcements surface visibly
        # on every Claude Code surface, not just the terminal CLI.
        #
        # Background: hook stdout is added to Claude's context on every
        # surface (terminal CLI, desktop app, IDE extensions). The CLI
        # additionally prints stdout to the terminal at session start, so
        # raw text is naturally visible there. The desktop app does NOT
        # print hook stdout to the screen — it only injects it as context,
        # so a bare `print(...)` of an announcement reaches Claude silently
        # and the user never sees it unless Claude happens to surface it.
        #
        # The directive prefix tells Claude to surface the announcement at
        # the start of its first reply. That makes the announcement
        # visible on desktop while keeping CLI behavior intact (CLI users
        # see it in the terminal AND see Claude echo it once — minor
        # redundancy, acceptable trade for desktop coverage).
        announcement_block = "\n".join(output)
        directive = (
            "[NSLS Builder Toolkit — surface the following to the user "
            "verbatim at the start of your first reply, then proceed with "
            "their request:]\n\n"
            f"{announcement_block}"
        )
        if data.get("new_pr_credits"):
            # Judge-then-nudge: a merged PR that shipped something others
            # will rely on (a new skill, tool, or service) belongs on the
            # org Automation Tracker; a pure bugfix/doc tweak doesn't.
            directive += (
                "\n\n[NSLS Builder Toolkit — additionally: judge whether a "
                "merged PR above shipped something registerable (a new "
                "skill, tool, or service other builders will rely on). If "
                "it did — or you can't tell from the repo/PR context — also "
                "surface this line: \"Shipped something new? Run "
                "/register-automation so it's on the org tracker.\" If it "
                "was clearly a pure bugfix, doc tweak, or maintenance "
                "change, skip that line.]"
            )
        print(directive)


def main():
    git_pull()
    run_plugin_migration()
    ensure_plugin_fresh()
    sync_pointers()
    replayed = replay_failed_ping()
    session_ping(replayed=replayed)


if __name__ == "__main__":
    main()
