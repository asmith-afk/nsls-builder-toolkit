#!/usr/bin/env python3
"""When the toolkit is allowed to say a personal-toolkit FORK has fallen behind.

Plain stdlib, no pytest, no network: NSLS and the fork are both local bare
repos, and git runs with an isolated global config so a builder's own settings
(signing, hooks, default remote name) cannot change the fixture. Run with
`python3 hooks/tests/test_fork_drift.py`.

The silence these exist to end (verified 2026-09-09): an active builder's
personal toolkit was her own GitHub fork. Her checkout tracked the fork, the
fork never received anything NSLS shipped, so every session pulled cleanly,
every check reported healthy, and she sat 196 commits behind for months.
The personal toolkit's own hook now carries the same check — but that hook
lives inside the fork, so no fork can receive it; this hook self-updates
from NSLS on every machine and is the only channel that reaches a fork.
"""

import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

# --- isolate git from the machine's own configuration ------------------------
ISO = Path(tempfile.mkdtemp(prefix="fork-drift-iso-"))
(ISO / "nohooks").mkdir()
(ISO / "gitconfig").write_text(
    "[user]\n\tname = T\n\temail = t@t.test\n"
    "[commit]\n\tgpgsign = false\n"
    "[init]\n\tdefaultBranch = main\n"
    "[clone]\n\tdefaultRemoteName = origin\n"
    f"[core]\n\thooksPath = {ISO / 'nohooks'}\n"
    "[protocol \"file\"]\n\tallow = always\n",
    encoding="utf-8",
)
os.environ["GIT_CONFIG_GLOBAL"] = str(ISO / "gitconfig")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["GIT_TERMINAL_PROMPT"] = "0"

HOOK = Path(__file__).resolve().parents[1] / "session-start.py"
spec = importlib.util.spec_from_file_location("session_start_hook", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

failures = []
checks_run = 0


def check(label, cond):
    global checks_run
    checks_run += 1
    print(f"{'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        failures.append(label)


def git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def commit(repo, name, text):
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", f"add {name}")


def seed_repo(path):
    path.mkdir()
    git(path, "init", "--quiet")
    git(path, "checkout", "--quiet", "-b", "main")
    return path


def make_world(tmp, nsls_ahead=5, customized=True):
    """NSLS (bare) → fork (bare, frozen at NSLS's first commit) → the builder's
    checkout, cloned from the fork, with one customization of her own. NSLS then
    moves `nsls_ahead` commits on. This is Chelsea's machine in miniature."""
    tmp = Path(tmp)
    work = seed_repo(tmp / "seed")
    commit(work, "skill.md", "v1\n")
    nsls = tmp / "nsls.git"
    git(work, "clone", "--quiet", "--bare", str(work), str(nsls))
    fork = tmp / "fork.git"
    git(work, "clone", "--quiet", "--bare", str(nsls), str(fork))
    for i in range(nsls_ahead):
        commit(work, f"skill{i}.md", f"v{i}\n")
    git(work, "tag", "nsls-release-tag")  # a tag the fork does not have
    git(work, "push", "--quiet", str(nsls), "main", "nsls-release-tag")

    config_dir = tmp / ".claude"
    plugin_dir = config_dir / "local-plugins" / "nsls-personal-toolkit"
    plugin_dir.parent.mkdir(parents=True)
    git(tmp, "clone", "--quiet", str(fork), str(plugin_dir))
    if customized:
        commit(plugin_dir, "mine.md", "her own customization\n")
    else:
        git(plugin_dir, "config", "user.email", "t@example.com")
        git(plugin_dir, "config", "user.name", "t")

    hook.CONFIG_DIR = config_dir
    hook.PERSONAL_UPSTREAM_STAMP = config_dir / ".nsls-personal-upstream-check"
    hook.PERSONAL_UPSTREAM_LOCK = config_dir / ".nsls-personal-upstream-check.flock"
    hook.PERSONAL_UPSTREAM_LEGACY_LOCK = config_dir / ".nsls-personal-upstream-check.lock"
    hook.PERSONAL_UPSTREAM_URL = str(nsls)
    return plugin_dir, nsls, fork


def run(deadline=None):
    buf = io.StringIO()
    with redirect_stdout(buf):
        hook.report_personal_fork_drift(deadline=deadline)
    return buf.getvalue()


def rearm():
    hook.PERSONAL_UPSTREAM_STAMP.unlink(missing_ok=True)
    hook.PERSONAL_UPSTREAM_LOCK.unlink(missing_ok=True)
    hook.PERSONAL_UPSTREAM_LEGACY_LOCK.unlink(missing_ok=True)


def lock_is_free():
    """True when nobody holds the OS lock: we can take it (and let it go again).
    The lock FILE existing means nothing — it is never deleted by design."""
    fd = hook._claim_lock(hook.PERSONAL_UPSTREAM_LOCK)
    if fd is None:
        return False
    hook._release_lock(fd)
    return True


# ---------------------------------------------------------------- URL forms
yes = [
    "https://github.com/thensls/nsls-personal-toolkit.git",
    "https://github.com/thensls/nsls-personal-toolkit",
    "https://github.com/thensls/nsls-personal-toolkit/",
    "git@github.com:thensls/nsls-personal-toolkit.git",
    "github.com:thensls/nsls-personal-toolkit.git",
    "ssh://git@github.com/thensls/nsls-personal-toolkit.git",
    "ssh://git@github.com:22/thensls/nsls-personal-toolkit.git",
    "https://user:tok@github.com/thensls/nsls-personal-toolkit.git",
    "https://www.github.com/thensls/nsls-personal-toolkit",
    "HTTPS://GitHub.com/THENSLS/NSLS-Personal-Toolkit.GIT",
]
no = [
    "https://github.com/grandmamischief/nsls-personal-toolkit.git",
    "https://github.com/cbyers-nsls/nsls-personal-toolkit.git",
    "https://gitlab.com/mirror/thensls/nsls-personal-toolkit.git",
    "https://github.com/thensls/nsls-personal-toolkit-experiments.git",
    "https://github.com/thensls/nsls-builder-toolkit.git",
    "https://github.com.evil.example/thensls/nsls-personal-toolkit.git",
    "file://github.com/thensls/nsls-personal-toolkit.git",
    "evil://github.com/thensls/nsls-personal-toolkit.git",
    "C:\\Users\\x\\thensls\\nsls-personal-toolkit",
    "/Users/x/thensls/nsls-personal-toolkit",
    "file:///Users/x/thensls/nsls-personal-toolkit",
    "", None,
]
check("every canonical spelling is recognised",
      all(hook._is_canonical_origin(u) is True for u in yes))
check("no fork, mirror, look-alike, local path or odd scheme passes as canonical",
      all(hook._is_canonical_origin(u) is False for u in no))
check("a path with control characters is rendered harmless and bounded",
      hook._safe_text("a\nb\x1bc/d") == "a?b?c/d" and len(hook._safe_text("x" * 500)) == 200)

# ------------------------------------------------------- the fork, behind
with tempfile.TemporaryDirectory() as tmp:
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5)
    out = run()
    check("a fork 5 behind NSLS is announced with the exact count",
          "OWN FORK" in out and "is 5 commit(s) behind NSLS" in out)
    check("the notice names our private ref, never a bare 'upstream'",
          "merge refs/nsls/upstream-main" in out and "upstream/main" not in out.replace("refs/nsls/upstream-main", ""))
    check("the notice names the checkout path and the skill file to follow",
          str(plugin_dir) in out and "skills/update-personal-productivity/SKILL.md" in out)
    check("exactly one line, all of it ours — nothing of git's output leaks",
          out.count("\n") == 1 and out.startswith("[NSLS Personal Toolkit] ")
          and "fatal" not in out and "From " not in out)
    check("NSLS landed in our private ref, at NSLS's actual main",
          git(plugin_dir, "rev-parse", "refs/nsls/upstream-main") == git(nsls, "rev-parse", "main"))
    check("no remote was created — her remote list is exactly as it was",
          git(plugin_dir, "remote") == "origin")
    check("NSLS's tags were not written into her checkout (--no-tags)",
          "nsls-release-tag" not in git(plugin_dir, "tag", "-l"))
    check("her own commit is untouched and the tree is clean (we only fetched)",
          (plugin_dir / "mine.md").exists() and git(plugin_dir, "status", "--porcelain") == "")
    check("the stamp was written", hook.PERSONAL_UPSTREAM_STAMP.exists())
    check("the lock was released (the file stays; the OS lock is gone)", lock_is_free())
    check("the old protocol's file holds our EMPTY shadow claim (an old hook arriving now would yield)",
          hook.PERSONAL_UPSTREAM_LEGACY_LOCK.exists() and hook.PERSONAL_UPSTREAM_LEGACY_LOCK.stat().st_size == 0)

    check("an immediate second run is throttled into silence", run() == "")

    future = time.time() + 5 * 3600
    os.utime(hook.PERSONAL_UPSTREAM_STAMP, (future, future))
    check("a future-dated stamp does not silence the check", "OWN FORK" in run())

    stale = time.time() - 13 * 3600
    os.utime(hook.PERSONAL_UPSTREAM_STAMP, (stale, stale))
    check("a 13h-old stamp re-arms the check", "OWN FORK" in run())

    # A deadline already spent: silent, and neither stamp nor lock is touched.
    rearm()
    check("no time left in the hook budget: silent", run(deadline=time.monotonic() - 1) == "")
    check("...and the slot was NOT claimed, so the next session gets a real check",
          not hook.PERSONAL_UPSTREAM_STAMP.exists() and not hook.PERSONAL_UPSTREAM_LOCK.exists()
          and not hook.PERSONAL_UPSTREAM_LEGACY_LOCK.exists())

    # Another hook holds the lock right now: this one stays quiet and leaves it.
    rearm()
    held = hook._claim_lock(hook.PERSONAL_UPSTREAM_LOCK)
    check("a lock held by a concurrent hook: silent", held is not None and run() == "")
    check("...the stamp is not written (the holder will write it)", not hook.PERSONAL_UPSTREAM_STAMP.exists())
    check("...and the holder still holds it", not lock_is_free())
    hook._release_lock(held)
    check("...and once the holder lets go, the next hook gets through", "OWN FORK" in run())

    # A lock FILE left on disk by a hook that died — however old, or dated in the
    # future — is not a lock. The OS lock is the claim, and it died with the
    # process that took it; there is nothing on disk to reclaim, and no grave.
    for label, when in (("300s old", time.time() - 300), ("dated 3h ahead", time.time() + 3 * 3600)):
        rearm()
        hook.PERSONAL_UPSTREAM_LOCK.write_text("")
        os.utime(hook.PERSONAL_UPSTREAM_LOCK, (when, when))
        check(f"a lock file {label} from a hook that died does not block the check", "OWN FORK" in run())
        check("...and nothing was left behind to reclaim (no graves, lock free)",
              not list(hook.PERSONAL_UPSTREAM_LOCK.parent.glob("*.stale-*")) and lock_is_free())

    # One machine may briefly run an OLD copy of this check beside this one. The
    # old copy claims by creating ITS OWN lock file exclusively with a token
    # inside, stale after 120 s. That file is read, never touched: a fresh token
    # is an old hook mid-check — yield; a stale one is a dead old hook — proceed.
    legacy = hook.PERSONAL_UPSTREAM_LEGACY_LOCK
    rearm()
    legacy.write_text("4242-1700000000-deadbeef")
    recent = time.time() - 10
    os.utime(legacy, (recent, recent))
    check("an old-style lock with a fresh token (an old hook mid-check): silent", run() == "")
    check("...the stamp is not written (the old hook will write it)", not hook.PERSONAL_UPSTREAM_STAMP.exists())
    check("...and the old file is left exactly as it was", legacy.read_text() == "4242-1700000000-deadbeef")
    old = time.time() - 300
    os.utime(legacy, (old, old))
    check("an old-style lock with a stale token (a dead old hook): the check proceeds", "OWN FORK" in run())
    check("...and the dead token is replaced by our EMPTY shadow, fresh — an old hook looking now sees a live lock",
          legacy.exists() and legacy.stat().st_size == 0 and 0 <= time.time() - legacy.stat().st_mtime < 30)
    check("...while our own lock lives in a different file, now free again",
          hook.PERSONAL_UPSTREAM_LOCK.exists() and lock_is_free())

    # Our own empty shadow from a previous run is not an old hook: only a fresh
    # NON-EMPTY token makes this protocol yield.
    rearm()
    legacy.write_text("")
    check("a fresh but EMPTY old-file (our own last shadow) does not block the check", "OWN FORK" in run())
    check("...and the shadow is there, empty, when the check ends", legacy.exists() and legacy.stat().st_size == 0)

    # Her own `upstream` pointing at something unrelated: left alone, not counted.
    other = seed_repo(Path(tmp) / "other")
    for i in range(40):
        commit(other, f"o{i}.md", "x\n")
    git(plugin_dir, "remote", "add", "upstream", str(other))
    rearm()
    out = run()
    check("a foreign 'upstream' remote is neither fetched nor counted",
          "is 5 commit(s) behind NSLS" in out)
    check("...and is left exactly as she had it",
          git(plugin_dir, "remote", "get-url", "upstream") == str(other))

    # Even a remote named nsls-upstream aimed elsewhere is neither used nor touched.
    git(plugin_dir, "remote", "add", "nsls-upstream", str(other))
    rearm()
    out = run()
    check("a remote that happens to be called nsls-upstream is ignored, not fetched",
          "is 5 commit(s) behind NSLS" in out
          and git(plugin_dir, "remote", "get-url", "nsls-upstream") == str(other))
    git(plugin_dir, "remote", "remove", "nsls-upstream")
    git(plugin_dir, "remote", "remove", "upstream")

    # Mirror URL as origin (Macroscope's case): NOT canonical, so still checked.
    real_origin = git(plugin_dir, "remote", "get-url", "origin")
    git(plugin_dir, "remote", "set-url", "origin",
        "https://gitlab.example/mirror/thensls/nsls-personal-toolkit.git")
    rearm()
    check("an origin that merely CONTAINS the canonical path is still checked",
          "OWN FORK" in run())

    # Canonical origin: not a fork, so this check says nothing and touches nothing.
    git(plugin_dir, "remote", "set-url", "origin",
        "https://github.com/thensls/nsls-personal-toolkit.git")
    rearm()
    check("a canonical checkout is silent here (the freeze checks own it)", run() == "")
    check("...and no stamp is written for it", not hook.PERSONAL_UPSTREAM_STAMP.exists())

    # Canonical origin, but the branch actually PULLS from a fork: a fork in
    # every way that matters, and classified as one.
    git(plugin_dir, "remote", "add", "fork", str(fork))
    git(plugin_dir, "fetch", "--quiet", "fork")
    git(plugin_dir, "branch", "--quiet", "--set-upstream-to=fork/main")
    rearm()
    check("canonical origin but a branch that pulls from a fork is judged by what it pulls from",
          "is 5 commit(s) behind NSLS" in run())
    git(plugin_dir, "branch", "--quiet", "--set-upstream-to=origin/main")
    git(plugin_dir, "remote", "remove", "fork")
    git(plugin_dir, "remote", "set-url", "origin", real_origin)

    # A fork whose remote is not called origin at all is still a fork.
    git(plugin_dir, "remote", "rename", "origin", "nsls")
    rearm()
    check("a fork whose remote was renamed away from 'origin' is still detected",
          "is 5 commit(s) behind NSLS" in run())
    git(plugin_dir, "remote", "rename", "nsls", "origin")

    # A remote whose NAME contains a slash: read from config, not split on "/".
    git(plugin_dir, "remote", "rename", "origin", "personal/fork")
    rearm()
    check("a fork whose remote is named with a slash (personal/fork) is still detected",
          "is 5 commit(s) behind NSLS" in run())
    git(plugin_dir, "remote", "rename", "personal/fork", "origin")

    # Detached HEAD (a deliberate pin): no branch config, so origin decides.
    head = git(plugin_dir, "rev-parse", "HEAD")
    git(plugin_dir, "checkout", "--quiet", "--detach", head)
    rearm()
    check("a detached HEAD on a fork falls back to origin and is still detected",
          "is 5 commit(s) behind NSLS" in run())
    git(plugin_dir, "checkout", "--quiet", "main")

    # A branch that pulls from a LOCAL branch (remote "."): followed one hop to
    # the remote that branch tracks, not mistaken for origin and not skipped.
    git(plugin_dir, "checkout", "--quiet", "-b", "work", "--track", "main")
    check("branch tracking a local branch (remote '.') is followed to the fork it really pulls from",
          git(plugin_dir, "config", "--get", "branch.work.remote") == "." and "is 5 commit(s) behind NSLS" in (rearm() or run()))
    git(plugin_dir, "checkout", "--quiet", "main")
    git(plugin_dir, "branch", "--quiet", "-D", "work")

    # A chain of local-tracking branches longer than two hops still resolves.
    git(plugin_dir, "checkout", "--quiet", "-b", "l1", "--track", "main")
    git(plugin_dir, "checkout", "--quiet", "-b", "l2", "--track", "l1")
    git(plugin_dir, "checkout", "--quiet", "-b", "l3", "--track", "l2")
    rearm()
    check("a three-hop chain of local-tracking branches is followed to the fork",
          "is 5 commit(s) behind NSLS" in run())
    git(plugin_dir, "checkout", "--quiet", "main")
    for b in ("l3", "l2", "l1"):
        git(plugin_dir, "branch", "--quiet", "-D", b)

    # The lock is the OS's, not a token's: a second claim fails while the first
    # is held, succeeds once it is released, and the file is never deleted.
    rearm()
    first = hook._claim_lock(hook.PERSONAL_UPSTREAM_LOCK)
    second = hook._claim_lock(hook.PERSONAL_UPSTREAM_LOCK)
    check("claiming the lock returns a handle, and a second claim while it is held does not",
          first is not None and second is None)
    hook._release_lock(first)
    third = hook._claim_lock(hook.PERSONAL_UPSTREAM_LOCK)
    check("...and once released, the next claim succeeds", third is not None)
    hook._release_lock(third)
    check("...and the lock file itself is never deleted", hook.PERSONAL_UPSTREAM_LOCK.exists())

    # Six real processes race for the lock at the same instant: exactly one
    # holds it, the other five are refused, and none can take it from the
    # holder. The winner keeps the lock until every racer has reported, so a
    # slow runner cannot turn the race into six sequential holders.
    racers = 6
    arena = Path(tmp) / "arena"
    arena.mkdir()
    racer = f"""
import importlib.util, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("h", {str(HOOK)!r})
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
arena = Path({str(arena)!r})
me = sys.argv[1]
(arena / ("ready-" + me)).touch()
while not (arena / "go").exists():
    time.sleep(0.005)
h.PERSONAL_UPSTREAM_LEGACY_LOCK = Path({str(hook.PERSONAL_UPSTREAM_LEGACY_LOCK)!r})
fd = h._claim_lock(Path({str(hook.PERSONAL_UPSTREAM_LOCK)!r}))
(arena / ("result-" + me)).write_text("refused" if fd is None else "held")
if fd is not None:
    while not (arena / "release").exists():
        time.sleep(0.005)
    h._release_lock(fd)
"""
    procs = [subprocess.Popen([sys.executable, "-c", racer, str(i)]) for i in range(racers)]

    def all_present(pattern, seconds):
        until = time.time() + seconds
        while len(list(arena.glob(pattern))) < racers and time.time() < until:
            time.sleep(0.01)
        return len(list(arena.glob(pattern))) == racers

    all_ready = all_present("ready-*", 30)
    (arena / "go").touch()
    all_tried = all_present("result-*", 30)
    (arena / "release").touch()
    for p in procs:
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    outcomes = [f.read_text() for f in arena.glob("result-*")]
    check("six processes race for the lock: all six try while the winner holds; one holds, five are refused",
          all_ready and all_tried and outcomes.count("held") == 1 and outcomes.count("refused") == racers - 1)

    # Fork caught up: silent.
    git(plugin_dir, "merge", "--quiet", "--no-edit", "refs/nsls/upstream-main")
    rearm()
    check("a fork that has been caught up is silent", run() == "")

    # An UNRELATED repository at the personal-toolkit path: not a fork, no shared
    # history with NSLS — say nothing rather than tell Claude to merge NSLS into it.
    import shutil
    shutil.rmtree(plugin_dir)
    stranger = seed_repo(plugin_dir)
    commit(stranger, "README.md", "something else entirely\n")
    git(stranger, "remote", "add", "origin", "https://github.com/someone/other-project.git")
    rearm()
    check("an unrelated repository at the path is not called a fork and gets no merge instruction",
          run() == "")

    # No checkout at all: silent, no crash.
    hook.CONFIG_DIR = Path(tmp) / "nowhere"
    check("no personal toolkit installed: silent", run() == "")

# ------------------------------------------ clean forks catch themselves up
# A fork with nothing of its own is fast-forwarded onto NSLS and told so once;
# anything of theirs in the way keeps the offer. Each case is its own world.
def head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

def upstream(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "refs/nsls/upstream-main"],
                          capture_output=True, text=True).stdout.strip()

with tempfile.TemporaryDirectory() as tmp:
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    out = run()
    check("a clean fork on main is caught up: HEAD is now NSLS's main",
          head(plugin_dir) == upstream(plugin_dir))
    check("...and it is told so once, with the caught-up line instead of the offer",
          "just been caught up with NSLS automatically" in out and "5 commit(s) behind" in out
          and "want me to catch it up" not in out)
    check("...and the working tree is clean afterwards", git(plugin_dir, "status", "--porcelain") == "")
    rearm()
    check("...and the next check has nothing to say", run() == "")

with tempfile.TemporaryDirectory() as tmp:
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=True)
    before = head(plugin_dir)
    out = run()
    check("a fork with a commit of its own is NOT moved", head(plugin_dir) == before)
    check("...and gets the offer instead", "want me to catch it up" in out)

with tempfile.TemporaryDirectory() as tmp:
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    (plugin_dir / "skill.md").write_text("an edit she has not saved\n")
    before = head(plugin_dir)
    out = run()
    check("a fork with an unsaved edit is NOT moved, and the edit survives",
          head(plugin_dir) == before and (plugin_dir / "skill.md").read_text() == "an edit she has not saved\n")
    check("...and gets the offer instead", "want me to catch it up" in out)

with tempfile.TemporaryDirectory() as tmp:
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    (plugin_dir / "scratch.md").write_text("a new file she has not added\n")
    before = head(plugin_dir)
    out = run()
    check("a fork with an untracked file is NOT moved", head(plugin_dir) == before)
    check("...and gets the offer instead", "want me to catch it up" in out)

with tempfile.TemporaryDirectory() as tmp:
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    git(plugin_dir, "checkout", "--quiet", "-b", "pinned")
    before = head(plugin_dir)
    out = run()
    check("a fork on a branch other than main is NOT moved", head(plugin_dir) == before)
    check("...and gets the offer instead", "want me to catch it up" in out)

with tempfile.TemporaryDirectory() as tmp:
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    git(plugin_dir, "checkout", "--quiet", "--detach")
    before = head(plugin_dir)
    out = run()
    check("a detached checkout is NOT moved", head(plugin_dir) == before)
    check("...and gets the offer instead", "want me to catch it up" in out)

with tempfile.TemporaryDirectory() as tmp:
    # The one way a fast-forward loses work: NSLS starts tracking a path the
    # builder keeps as an IGNORED local file. Plain git overwrites it silently.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=0, customized=False)
    work = Path(tmp) / "seed"
    (plugin_dir / ".git" / "info").mkdir(exist_ok=True)
    (plugin_dir / ".git" / "info" / "exclude").write_text("local-notes.md\n")
    (plugin_dir / "local-notes.md").write_text("HER PRIVATE NOTES\n")
    commit(work, "local-notes.md", "nsls's version\n")
    git(work, "push", "--quiet", str(nsls), "main")
    before = head(plugin_dir)
    out = run()
    check("an ignored file NSLS starts tracking is NOT overwritten",
          (plugin_dir / "local-notes.md").read_text() == "HER PRIVATE NOTES\n")
    check("...the checkout is left where it was", head(plugin_dir) == before)
    check("...and it gets the offer instead of a false 'caught up'",
          "want me to catch it up" in out and "caught up with NSLS automatically" not in out)

with tempfile.TemporaryDirectory() as tmp:
    # A write we might have to abandon is never begun: with the deadline already
    # inside the margin, the merge must not even be started.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    before = head(plugin_dir)
    real_merge, merge_calls = hook._ff_merge, []
    hook._ff_merge = lambda *a, **k: merge_calls.append(a) or real_merge(*a, **k)
    out = run(deadline=time.monotonic() + hook.PERSONAL_FF_MIN_LEFT_S - 2)
    hook._ff_merge = real_merge
    check("with too little time left, the merge is never started", merge_calls == [])
    check("...the checkout is left where it was, and gets the offer",
          head(plugin_dir) == before and "want me to catch it up" in out)

with tempfile.TemporaryDirectory() as tmp:
    # A merge that succeeds as the caller's deadline runs out must still be
    # reported: the state check does not go through the expired deadline.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    real_merge = hook._ff_merge
    deadline = time.monotonic() + hook.PERSONAL_FF_MIN_LEFT_S + 3
    def slow_merge(*a, **k):
        time.sleep(max(0, deadline - time.monotonic()) + 1)   # finish after the deadline
        return real_merge(*a, **k)
    hook._ff_merge = slow_merge
    out = run(deadline=deadline)
    hook._ff_merge = real_merge
    check("a merge that finishes after the deadline is still reported as caught up",
          head(plugin_dir) == upstream(plugin_dir) and "caught up with NSLS automatically" in out)

with tempfile.TemporaryDirectory() as tmp:
    # branch.main.mergeOptions=--squash turns a plain fast-forward into "stage
    # NSLS's tree, leave the branch where it is". The merge must neutralise it.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    git(plugin_dir, "config", "branch.main.mergeOptions", "--squash")
    out = run()
    check("with mergeOptions=--squash configured, it is still a clean fast-forward",
          head(plugin_dir) == upstream(plugin_dir) and git(plugin_dir, "status", "--porcelain") == "")
    check("...and reports caught up, not the offer over a staged tree", "caught up with NSLS automatically" in out)

with tempfile.TemporaryDirectory() as tmp:
    # Mid-bisect a checkout can be clean and on main; moving main changes the bisect.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    git(plugin_dir, "bisect", "start")
    before = head(plugin_dir)
    out = run()
    check("a checkout mid-bisect is NOT moved", head(plugin_dir) == before)
    check("...and gets the offer instead", "want me to catch it up" in out)

with tempfile.TemporaryDirectory() as tmp:
    # A post-merge hook runs after the branch has moved, and can hang.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    marker = Path(tmp) / "hook-ran"
    # Installed through the repo's LOCAL core.hooksPath. This suite's isolated
    # global config points core.hooksPath at an empty folder, so a hook in
    # .git/hooks would never run here whatever the hook does; local config beats
    # that, and only the command-line override in _ff_merge beats local. It is
    # also the shape a builder with their own hooks directory would have.
    hooks_dir = Path(tmp) / "builder-hooks"
    hooks_dir.mkdir()
    hook_file = hooks_dir / "post-merge"
    hook_file.write_text(f"#!/bin/sh\ntouch '{marker}'\nsleep 30\n")
    hook_file.chmod(0o755)
    git(plugin_dir, "config", "core.hooksPath", str(hooks_dir))
    t0 = time.monotonic()
    out = run()
    took = time.monotonic() - t0
    check("a hanging post-merge hook is never run", not marker.exists())
    check(f"...so the catch-up completes promptly ({took:.1f}s) and is reported",
          took < 15 and head(plugin_dir) == upstream(plugin_dir) and "caught up with NSLS automatically" in out)

with tempfile.TemporaryDirectory() as tmp:
    # status.showUntrackedFiles=no hides an untracked file from plain porcelain.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    git(plugin_dir, "config", "status.showUntrackedFiles", "no")
    (plugin_dir / "scratch.md").write_text("a new file she has not added\n")
    before = head(plugin_dir)
    out = run()
    check("an untracked file is seen even with status.showUntrackedFiles=no, and nothing moves",
          head(plugin_dir) == before and "want me to catch it up" in out)

with tempfile.TemporaryDirectory() as tmp:
    # A merge still running after the wait is left alone and reported honestly.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    real_merge = hook._ff_merge
    hook._ff_merge = lambda *a, **k: None
    out = run()
    hook._ff_merge = real_merge
    check("a merge still running is reported as needing a look, not as the offer",
          "did not finish cleanly" in out and "want me to catch it up" not in out)

with tempfile.TemporaryDirectory() as tmp:
    # Any state other than exactly-before or exactly-after is reported, never masked.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    real_merge = hook._ff_merge
    def half_merge(*a, **k):
        (plugin_dir / "skill.md").write_text("half-written by a merge that died\n")
        return 128
    hook._ff_merge = half_merge
    out = run()
    hook._ff_merge = real_merge
    check("a half-updated checkout is reported as needing a look, not offered or called caught up",
          "did not finish cleanly" in out and "want me to catch it up" not in out
          and "caught up with NSLS automatically" not in out)

with tempfile.TemporaryDirectory() as tmp:
    # git reads GIT_DIR and friends ahead of -C. A session launched from inside a
    # git hook inherits them, and they must not aim the catch-up at that repository.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    decoy = seed_repo(Path(tmp) / "decoy")
    commit(decoy, "project.md", "someone else's project\n")
    decoy_head = head(decoy)
    saved = {k: os.environ.get(k) for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    os.environ.update(GIT_DIR=str(decoy / ".git"), GIT_WORK_TREE=str(decoy),
                      GIT_INDEX_FILE=str(decoy / ".git" / "index"))
    try:
        out = run()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check("with GIT_DIR aimed at another repository, the toolkit is still the one caught up",
          head(plugin_dir) == upstream(plugin_dir) and "caught up with NSLS automatically" in out)
    check("...and that other repository is untouched: same HEAD, no NSLS ref fetched into it",
          head(decoy) == decoy_head
          and subprocess.run(["git", "-C", str(decoy), "rev-parse", "--verify", "--quiet",
                              "refs/nsls/upstream-main"], capture_output=True).returncode != 0)

with tempfile.TemporaryDirectory() as tmp:
    # The wait never runs past the caller's deadline: that deadline is the 15s pull
    # envelope the 90s hook budget is built on.
    plugin_dir, nsls, fork = make_world(tmp, nsls_ahead=5, customized=False)
    real_merge, waits = hook._ff_merge, []
    hook._ff_merge = lambda d, wait: waits.append(wait) or real_merge(d, wait)
    out = run(deadline=time.monotonic() + hook.PERSONAL_FF_MIN_LEFT_S + 6)
    hook._ff_merge = real_merge
    check("the merge's wait ends by the caller's deadline, not a fixed 20s after starting",
          len(waits) == 1 and waits[0] <= hook.PERSONAL_FF_MIN_LEFT_S + 6)
    check("...and a quick merge inside it is still reported as caught up",
          head(plugin_dir) == upstream(plugin_dir) and "caught up with NSLS automatically" in out)

print()
if failures:
    print(f"{len(failures)} FAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print(f"all {checks_run} checks passed")
