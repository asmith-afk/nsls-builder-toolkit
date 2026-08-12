#!/usr/bin/env python3
"""gws_doctor — one command that makes the NSLS toolkit's gws profile healthy.

Replaces the multi-step shell procedures that used to live in skill docs (agents
transcribe multi-step shell unreliably; they run one script fine). It:

  1. finds gws and checks the version floor (older gws ignores the profile env var)
  2. ensures the toolkit profile dir exists and holds the CANONICAL client file
     (validated by client_id — never by existence or filename), acquiring it from
     the default dir or ~/Downloads when possible, neutralizing project_id at
     placement — set to "" not removed; gws's strict parser REJECTS the file if
     the field is absent (defuses googleworkspace/cli#729), backing up any foreign file or
     symlink found inside OUR profile, and NEVER touching or writing through to
     any file outside the profile directory
  3. verifies gws actually resolves its config to the canonical client inside the
     profile (post-condition — catches an ignored env var, an old gws, a typo'd
     path, and lookalike directories)
  4. checks credentials + scopes (exact scope matching — a limited scope like
     drive.file does NOT count as drive), and (unless --no-login) runs the
     one-time browser consent with the UNION of already-granted + requested
     services, so one skill's login can never clobber another's
  5. re-verifies and prints a final DOCTOR: HEALTHY / ACTION_REQUIRED / ERROR line

Usage (agents: run with a generous timeout — the login step waits for a human):
    python3 gws_doctor.py                          # ensure docs,drive (gdoc baseline)
    python3 gws_doctor.py --services docs,drive,sheets
    python3 gws_doctor.py --no-login               # report + provision only, never
                                                   # opens a browser (CI/status checks)

Exit codes: 0 healthy · 2 login required (only with --no-login) · 3 client file
needed (human must download — the script prints exactly how) · 4 environment
problem (gws missing/too old/env var ignored/profile unsafe) · 1 unexpected error.

Windows note: run with a REAL Python (e.g.
%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe) — the Microsoft Store
stub prints "Python was not found" and exits 0. If no working Python exists,
follow the manual fallback in skills/gdoc-edit/references/setup.md instead.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser

# Keep in sync with skills/gdoc-edit/scripts/gdoc.py (duplicated deliberately —
# the scripts ship in different skills and must not import across skill dirs).
PROFILE = os.path.expanduser(
    os.path.join("~", ".config", "gws-profiles", "nsls-gdocs-skill")
)
# Full-ID equality, not prefix: every OAuth client in the same GCP project
# shares the numeric prefix — a prefix match would bless a sibling client.
CANONICAL_ID = "598752584124-4t7bdffqchrt8b6nlv1uuhpkl1b24vtc.apps.googleusercontent.com"
DRIVE_FILE_ID = "1fOu-0M35vgGO6mzbd0BInEt_sgkmgCn7"
DRIVE_URL = f"https://drive.google.com/file/d/{DRIVE_FILE_ID}/view"
MIN_GWS = (0, 22, 5)  # oldest version the profile env var is verified to work on
DEFAULT_DIR_CLIENT = os.path.expanduser(os.path.join("~", ".config", "gws", "client_secret.json"))

# Exact scope URLs per service (matched exactly — substring matching wrongly
# accepts limited scopes like drive.file/gmail.readonly as the full service,
# and misses gmail's broad https://mail.google.com/ form). A service counts as
# granted ONLY when one of its listed scopes is present verbatim; unknown or
# partial scopes are conservatively treated as not granted (worst case: the
# consent screen is shown once more).
G = "https://www.googleapis.com/auth/"
SERVICE_SCOPES = {
    "docs": {G + "documents"},
    "drive": {G + "drive"},
    "sheets": {G + "spreadsheets"},
    "slides": {G + "presentations"},
    "gmail": {"https://mail.google.com/", G + "gmail.modify"},
    "calendar": {G + "calendar"},
    "tasks": {G + "tasks"},
    "people": {G + "contacts"},
    "chat": {G + "chat.messages", G + "chat.spaces"},
    "forms": {G + "forms.body"},
    "keep": {G + "keep"},
}


def log(msg):
    print(f"doctor: {msg}")


def finish(state, detail, code):
    print(f"DOCTOR: {state} — {detail}")
    sys.exit(code)


def gws_env():
    return dict(os.environ, GOOGLE_WORKSPACE_CLI_CONFIG_DIR=PROFILE)


def run_gws(args, interactive=False):
    """Run gws inside the profile. interactive=True streams output through and
    auto-opens the consent URL: without a TTY (agent shells) gws only PRINTS
    the URL and waits silently — the human would stare at nothing."""
    cmd = ["gws"] + args
    if interactive:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, env=gws_env())
        opened = False
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if not opened:
                m = re.search(r"https://accounts\.google\.com/\S+", line)
                if m:
                    try:
                        opened = bool(webbrowser.open(m.group(0)))
                    except Exception:
                        opened = True  # URL already printed above — human can click it
        p.wait()
        return p
    return subprocess.run(cmd, capture_output=True, text=True, env=gws_env())


def parse_tolerant_json(out):
    """gws sometimes prefixes JSON with a keyring/log line."""
    try:
        return json.loads(out)
    except Exception:
        lines = (out or "").splitlines()
        for i, ln in enumerate(lines):
            if ln.lstrip().startswith(("{", "[")):
                try:
                    return json.loads("\n".join(lines[i:]))
                except Exception:
                    return None
    return None


def read_json_dict(path):
    """Load a JSON object from path. Returns a dict or None — never raises on
    missing/malformed/mis-typed content (the doctor's job includes damaged state)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def installed_of(path):
    """The 'installed' object of a client file, or None if absent/malformed."""
    data = read_json_dict(path)
    if data is None:
        return None
    installed = data.get("installed")
    return installed if isinstance(installed, dict) else None


def client_id_of(path):
    installed = installed_of(path) or {}
    cid = installed.get("client_id")
    return cid if isinstance(cid, str) else ""


def is_canonical(path):
    # isfile() first: a FIFO with no writer would block open() forever
    return os.path.isfile(path) and client_id_of(path) == CANONICAL_ID


def inside_profile(path):
    """True iff the fully-resolved path is inside the fully-resolved profile dir
    (commonpath — a prefix test wrongly accepts lookalikes such as
    .../nsls-gdocs-skill-other)."""
    try:
        rp, rd = os.path.realpath(PROFILE), os.path.realpath(path)
        return os.path.commonpath([rp, rd]) == rp
    except ValueError:  # different drives on Windows
        return False


def ensure_profile_dir():
    os.makedirs(PROFILE, exist_ok=True)
    if os.path.islink(PROFILE) or not os.path.isdir(PROFILE):
        finish(
            "ERROR",
            f"profile path {PROFILE} is a symlink or not a directory — refusing to "
            "operate (writes could land outside the profile). Remove the symlink and re-run.",
            4,
        )


def sidestep_existing(dest):
    """Move aside a dest we must not write through: any symlink (its target may
    be OUTSIDE the profile — never truncate through it), or a foreign regular
    file. Renaming moves only the link/file inside our profile; targets are
    untouched. No-op when dest is our own regular canonical file."""
    if not os.path.lexists(dest):
        return
    bak = f"{dest}.replaced-{int(time.time())}-{os.getpid()}.bak"
    if os.path.islink(dest):
        os.rename(dest, bak)
        log(f"dest was a symlink — moved the link aside to {bak} (target untouched)")
    elif not is_canonical(dest):
        os.rename(dest, bak)
        log(f"a foreign/unreadable client was inside OUR profile — backed up to {bak}")


def place_client(src, dest):
    """Validated, atomic placement: canonical source only, project_id neutralized,
    staged in a temp file inside the profile, then os.replace()'d over dest.
    Reads src fully into memory first, so self-placement (src == dest) is safe."""
    # Judge containment on the PARENT directory, not the resolved final
    # component: a hostile symlink AT dest must pass this guard so
    # sidestep_existing() below can move the link aside (the self-heal path);
    # os.replace() then swaps in a regular file without following the link.
    if not inside_profile(os.path.dirname(dest)):
        finish("ERROR", f"internal error: refusing to write outside the profile ({dest})", 1)
    data = read_json_dict(src)
    installed = data.get("installed") if data else None
    if not isinstance(installed, dict) or installed.get("client_id") != CANONICAL_ID:
        finish("ERROR", f"refusing to place a FOREIGN or malformed client from {src}", 1)
    # NEVER pop project_id: gws (>=0.22.5, strict parser) refuses the whole file
    # if the field is missing. Empty string parses AND gives #729's
    # x-goog-user-project header no project to name.
    installed["project_id"] = ""
    payload = json.dumps(data, ensure_ascii=False)

    fd, tmp = tempfile.mkstemp(prefix=".client_secret.", suffix=".tmp", dir=PROFILE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        sidestep_existing(dest)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    if os.name != "nt":
        os.chmod(dest, 0o600)

    check = installed_of(dest) or {}
    if check.get("client_id") != CANONICAL_ID or check.get("project_id") != "":
        finish("ERROR", "placed client failed verification — redo from a fresh download", 1)
    log(f"placed canonical client (project_id neutralized) -> {dest}")


def ensure_client():
    dest = os.path.join(PROFILE, "client_secret.json")
    if not os.path.islink(dest) and is_canonical(dest):
        installed = installed_of(dest) or {}
        # raw download (real project_id) or legacy strip (field removed — gws
        # refuses to parse that): neutralize in place (atomic, src==dest is safe)
        if installed.get("project_id") != "":
            place_client(dest, dest)
        return
    # acquire: pre-profile default dir first (zero download), then Downloads
    if is_canonical(DEFAULT_DIR_CLIENT):
        log("found canonical client in the pre-profile default dir — copying (original untouched)")
        place_client(DEFAULT_DIR_CLIENT, dest)
        return
    downloads = sorted(
        glob.glob(os.path.expanduser(os.path.join("~", "Downloads", "*client_secret*.json"))),
        key=os.path.getmtime,
        reverse=True,
    )
    for cand in downloads:
        if is_canonical(cand):
            log(f"found canonical client in Downloads: {cand}")
            place_client(cand, dest)
            return
        log(f"ignoring non-canonical file in Downloads: {cand}")
    finish(
        "ACTION_REQUIRED",
        "no canonical client file found. Download it (signed in as your @nsls.org "
        f"account): {DRIVE_URL}  — then re-run this script. Access denied? Staff: ask in "
        "#builders. Contractors: ask to be added to gcp-builders@nsls.org.",
        3,
    )


def gws_version_ok():
    exe = shutil.which("gws")
    if not exe:
        finish(
            "ERROR",
            "gws is not installed / not on PATH — run the toolkit installer, or see "
            "skills/gdoc-edit/references/setup.md step 1",
            4,
        )
    r = subprocess.run(["gws", "--version"], capture_output=True, text=True)
    if r.returncode != 0:
        finish("ERROR", f"`gws --version` failed (exit {r.returncode}): {(r.stderr or r.stdout or '').strip()[:200]}", 4)
    m = re.search(r"gws\s+(\d+)\.(\d+)\.(\d+)", r.stdout + r.stderr)
    if not m:
        log("could not parse gws version — continuing; the post-condition below will catch an incompatible gws")
        return
    ver = tuple(int(x) for x in m.groups())
    if ver < MIN_GWS:
        finish(
            "ERROR",
            f"gws {'.'.join(map(str, ver))} is older than {'.'.join(map(str, MIN_GWS))} and may "
            "ignore the profile env var — upgrade gws (another tool may have installed the old one)",
            4,
        )
    log(f"gws {'.'.join(map(str, ver))} OK")


def auth_status():
    r = run_gws(["auth", "status"])
    status = parse_tolerant_json(r.stdout)
    if not isinstance(status, dict):
        if r.returncode != 0:
            finish("ERROR", f"`gws auth status` failed (exit {r.returncode}): {(r.stderr or r.stdout or '').strip()[:200]}", 4)
        status = {}
    return status


def check_postcondition(status):
    """gws must resolve its client config to a regular file inside the profile
    that is ALSO the canonical client — location alone isn't health."""
    cfg = status.get("client_config")
    if not isinstance(cfg, str) or not cfg:
        finish("ERROR", "gws auth status reported no client_config — unexpected gws output", 4)
    cfg_err = status.get("client_config_error")
    if cfg_err:
        finish("ERROR", f"gws rejected the client file it resolved: {cfg_err} — run me again to repair", 4)
    rcfg = os.path.realpath(cfg)
    if not inside_profile(cfg) or not os.path.isfile(rcfg):
        finish(
            "ERROR",
            f"gws did NOT resolve its config inside the profile (client_config={cfg!r}). "
            "This gws likely ignores GOOGLE_WORKSPACE_CLI_CONFIG_DIR — upgrade gws.",
            4,
        )
    if not is_canonical(rcfg):
        finish("ERROR", f"gws resolved a NON-canonical client at {cfg!r} — run me again to repair", 4)


def granted_services(status):
    scopes = {s for s in (status.get("scopes") or []) if isinstance(s, str)}
    return {name for name, accept in SERVICE_SCOPES.items() if accept & scopes}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--services", default="docs,drive",
                    help="services this skill needs (comma-separated, default: docs,drive)")
    ap.add_argument("--no-login", action="store_true",
                    help="never open a browser; report ACTION_REQUIRED instead")
    args = ap.parse_args()

    requested = {s.strip() for s in args.services.split(",") if s.strip()}
    unknown = requested - set(SERVICE_SCOPES)
    if unknown:
        finish("ERROR", f"unknown service(s): {', '.join(sorted(unknown))}", 1)
    requested |= {"docs", "drive"}  # gdoc baseline — a narrower login would clobber the shared profile

    gws_version_ok()
    ensure_profile_dir()
    ensure_client()

    status = auth_status()
    check_postcondition(status)

    have = granted_services(status)
    authed = bool(status.get("has_refresh_token")) or bool(status.get("encrypted_credentials_exists"))
    missing = requested - have if authed else requested

    if authed and not missing:
        log(f"credentials present; scopes cover: {', '.join(sorted(requested))}")
        finish("HEALTHY", "profile client canonical, credentials valid, scopes sufficient", 0)

    union = sorted(have | requested)
    if args.no_login:
        finish(
            "ACTION_REQUIRED",
            f"login needed (services: {','.join(union)}). Re-run without --no-login "
            "when a human is present to complete the browser consent.",
            2,
        )

    print()
    log("about to open the one-time Google consent in your browser.")
    log("sign in as your REAL @nsls.org account — aliases and personal accounts are refused.")
    log("this waits for you; it can take a few minutes. (Agents: run me with a long timeout.)")
    print()
    r = run_gws(["auth", "login", "--services", ",".join(union)], interactive=True)
    if r.returncode != 0:
        finish("ERROR", f"gws auth login exited {r.returncode} — consent not completed", 1)

    status = auth_status()
    check_postcondition(status)
    have = granted_services(status)
    authed = bool(status.get("has_refresh_token")) or bool(status.get("encrypted_credentials_exists"))
    if authed and not (requested - have):
        finish("HEALTHY", f"login complete; scopes cover: {', '.join(sorted(requested))}", 0)
    finish("ERROR",
           "login ran but the profile still isn't healthy "
           f"(authed={authed}, missing={sorted(requested - have)}). "
           "If credentials fail to decrypt, another tool may have reset the gws keyring — re-run me.",
           1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        finish("ERROR", "interrupted", 1)
    except Exception as e:  # controlled last-resort: diagnose, don't traceback
        finish("ERROR", f"unexpected failure: {type(e).__name__}: {e}", 1)
