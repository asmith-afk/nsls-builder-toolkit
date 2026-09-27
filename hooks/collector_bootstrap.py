#!/usr/bin/env python3
"""Install the NSLS Claude usage collector on a builder's machine, quietly.

Called at the end of session start (session-start.py main(); Windows has its
own copy in collector_bootstrap.ps1). When the collector is not installed, it
launches the same one-line installer as the self-serve link, fully detached,
and returns at once. It prints nothing: the collector's enrollment sends the
builder a Signal DM, and that DM is the notice.

Checks, cheapest first; any failure means "skip silently":

  1. NSLS_COLLECTOR_OPTOUT=1 (or true/yes)  -> never install, write nothing.
  2. Platform: macOS and Windows only. Linux has no supported scheduler.
  3. Installed = the collector's config.json exists in its home
     (~/Library/Application Support/nsls-collector on a Mac,
     %LOCALAPPDATA%\\nsls-collector on Windows), or its evidence file is fresh
     (collector_evidence.fresh()).
  4. Throttle, via <CLAUDE_CONFIG_DIR or ~/.claude>/.nsls-collector/bootstrap.json
     = {attempted_at, attempts}: at most one attempt per 24 hours, and none
     after 5 (logged once). The marker is written BEFORE the launch, under a
     short O_EXCL lock, so two sessions starting together launch once.

The installer's output goes to <collector home>/bootstrap.log when that
folder exists, else to the marker folder. NSLS_COLLECTOR_BASE_URL overrides
https://signal.nsls.org for tests; it must be a bare http(s) origin.
"""

import json
import os
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_BASE_URL = "https://signal.nsls.org"
THROTTLE = timedelta(hours=24)
MAX_ATTEMPTS = 5
LOCK_STALE_SECONDS = 600
MAX_MARKER_BYTES = 4096

_ORIGIN = re.compile(r"https?://[A-Za-z0-9.-]+(?::[0-9]{1,5})?")
_ISO = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")


def opted_out(env):
    return str(env.get("NSLS_COLLECTOR_OPTOUT", "")).strip().lower() in ("1", "true", "yes")


def collector_home(platform, env):
    if platform == "darwin":
        home = env.get("HOME")
        if not home:
            return None
        return Path(home) / "Library" / "Application Support" / "nsls-collector"
    if platform == "win32":
        local = env.get("LOCALAPPDATA")
        return Path(local) / "nsls-collector" if local else None
    return None


def base_url(env):
    """The installer origin, or None when the override is not a bare origin."""
    raw = env.get("NSLS_COLLECTOR_BASE_URL") or DEFAULT_BASE_URL
    raw = raw.strip()
    if raw.endswith("/"):
        raw = raw[:-1]
    return raw if _ORIGIN.fullmatch(raw) else None


def install_command(platform, base):
    """The self-serve one-liner, verbatim, as an argv list."""
    if platform == "win32":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                f"iwr -UseBasicParsing {base}/api/collector/dist/install.ps1 | iex"]
    return ["/bin/bash", "-c", f"curl -fsSL {base}/api/collector/dist/install.sh | bash"]


def installed(platform, env, config_dir):
    home = collector_home(platform, env)
    if home is not None and (home / "config.json").is_file():
        return True
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import collector_evidence

        return bool(collector_evidence.fresh(config_dir=config_dir))
    except Exception:
        return False


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_regular(path, flags, mode=0o600):
    """fd for `path` only if it is a regular file, else None. O_NONBLOCK means a
    FIFO planted at the path can never block the hook: a read open returns at
    once and a write open with no reader fails; the fstat then rejects it."""
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, mode)
    except OSError:
        return None
    try:
        if stat.S_ISREG(os.fstat(fd).st_mode):
            return fd
    except OSError:
        pass
    os.close(fd)
    return None


def _open_log(path):
    """Append handle on the log (a regular file), or on devnull."""
    fd = _open_regular(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    if fd is None:
        return open(os.devnull, "a", encoding="utf-8")
    return os.fdopen(fd, "a", encoding="utf-8")


def _read_marker(path):
    """(attempts, attempted_at or None, gave_up). Untrusted: junk reads as empty."""
    try:
        fd = _open_regular(path, os.O_RDONLY)
        if fd is None:
            return 0, None, False
        with os.fdopen(fd, "rb") as f:
            raw = f.read(MAX_MARKER_BYTES + 1)
        if len(raw) > MAX_MARKER_BYTES:
            return 0, None, False
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return 0, None, False
        attempts = data.get("attempts")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
            attempts = 0
        at = None
        m = _ISO.fullmatch(str(data.get("attempted_at", "")))
        if m:
            at = datetime(*(int(g) for g in m.groups()), tzinfo=timezone.utc)
        return attempts, at, data.get("gave_up") is True
    except Exception:
        return 0, None, False


def _write_marker(path, data):
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _take_over_stale(lock, stale_ino):
    """Remove the lock judged stale, but only if it is still that same file.

    Rename is atomic, so exactly one session wins the stale file. If what we
    renamed is not the inode we judged stale, another session has already
    replaced it with a live lock: put it back and stand down.
    """
    quarantine = lock.with_name(f"{lock.name}.stale.{os.getpid()}.{time.time_ns()}")
    try:
        os.rename(lock, quarantine)
    except OSError:
        return True  # someone else took it first; retry the O_EXCL create
    try:
        if os.stat(quarantine).st_ino != stale_ino:
            try:
                os.rename(quarantine, lock)
            except OSError:
                pass
            return False
        os.unlink(quarantine)
    except OSError:
        pass
    return True


def _acquire_lock(lock):
    """True if we now hold the lock. A lock older than 10 minutes (or dated in
    the future) is abandoned and taken over once."""
    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            return True
        except FileExistsError:
            try:
                st = os.stat(lock)
            except OSError:
                continue
            age = time.time() - st.st_mtime
            if age > LOCK_STALE_SECONDS or age < -60:
                if not _take_over_stale(lock, st.st_ino):
                    return False
                continue
            return False
    return False


def _log_path(platform, env, marker_dir):
    home = collector_home(platform, env)
    if home is not None and home.is_dir():
        return home / "bootstrap.log"
    return marker_dir / "bootstrap.log"


def _append_log(path, line):
    try:
        with _open_log(path) as f:
            f.write(line + "\n")
    except Exception:
        pass


def maybe_bootstrap(config_dir, platform, env, now, popen):
    """One bootstrap decision. Returns a status word; raises only on bugs."""
    if opted_out(env):
        return "optout"
    if collector_home(platform, env) is None:
        return "unsupported"
    if installed(platform, env, config_dir):
        return "installed"
    base = base_url(env)
    if base is None:
        return "error"

    marker_dir = Path(config_dir) / ".nsls-collector"
    try:
        marker_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return "error"
    marker = marker_dir / "bootstrap.json"
    lock = marker_dir / "bootstrap.lock"
    if not _acquire_lock(lock):
        return "busy"
    try:
        attempts, last, gave_up = _read_marker(marker)
        log = _log_path(platform, env, marker_dir)
        if attempts >= MAX_ATTEMPTS:
            if not gave_up:
                _append_log(log, f"[{_iso(now)}] collector bootstrap: {attempts} attempts "
                                 "without an install; giving up. Run the installer by hand "
                                 "from signal.nsls.org/me/machines.")
                _write_marker(marker, {"attempted_at": _iso(last or now),
                                       "attempts": attempts, "gave_up": True})
            return "capped"
        if last is not None and timedelta(0) <= now - last < THROTTLE:
            return "throttled"
        # Record the attempt BEFORE launching: a second session starting now
        # sees it and stands down, and a machine that can never launch still
        # stops at MAX_ATTEMPTS.
        _write_marker(marker, {"attempted_at": _iso(now), "attempts": attempts + 1})
    finally:
        try:
            lock.unlink()
        except OSError:
            pass

    _append_log(log, f"[{_iso(now)}] collector bootstrap: attempt {attempts + 1} "
                     f"from {base}")
    kwargs = {"stdin": subprocess.DEVNULL, "close_fds": True}
    if platform == "win32":
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True
    out = _open_log(log)
    try:
        kwargs["stdout"] = out
        kwargs["stderr"] = out
        popen(install_command(platform, base), **kwargs)
    except Exception:
        return "error"
    finally:
        out.close()  # the child holds its own copy of the descriptor
    return "launched"


def run(config_dir=None, platform=None, env=None, now=None, popen=None):
    """Session-start entry point: never raises, never prints."""
    try:
        env = os.environ if env is None else env
        if config_dir is None:
            config_dir = env.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")
        return maybe_bootstrap(
            config_dir=config_dir,
            platform=platform or sys.platform,
            env=env,
            now=now or datetime.now(timezone.utc),
            popen=popen or subprocess.Popen,
        )
    except Exception:
        return "error"


if __name__ == "__main__":
    print(run())
