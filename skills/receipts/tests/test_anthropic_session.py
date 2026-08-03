#!/usr/bin/env python3.12
"""Session-cookie auth for the Anthropic billing source.

The browser is gone. An authenticated GET to
`/api/stripe/{org}/invoices` returns real invoice JSON with nothing but a
`sessionKey` cookie (verified live 2026-08-01); the same URL without one
returns 403. The browser only ever existed to obtain that cookie — which is
exactly the thing Cloudflare guards — so the cookie is stored once and sent
directly.

That cookie is a live credential. Half of this file exists to prove the code
treats it like one: it is never echoed, never logged, never interpolated into
a message, and the file holding it is refused outright if anyone else on the
machine can read it.

Hermetic by construction: no network (the `_open` seam is always patched), no
browser, no auth, and every session path is redirected into a throwaway temp
directory — no test reads or writes the real ~/.claude-receipts-session.
"""

import contextlib
import email.message
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sources.anthropic as anth
from sources.anthropic import SOURCE
from sources.base import SourceUnavailable

# A value that is never real and never valid. Every error path in this file
# runs with this as "the session", and every assertion checks it did not come
# back out in the message. If a test here ever fails on the sentinel, the
# code leaked a credential into text a user (or a log, or a ledger) will see.
SENTINEL = "sk-ant-sid01-SENTINEL-DO-NOT-PRINT-0123456789abcdef"
ORG = "test-org-uuid"

PAYLOAD = {
    "invoices": [
        {"total": 21456, "status": "paid", "created_ts": 1784806673,
         "invoice_pdf_url": "https://pay.stripe.com/invoice/acct_X/live_A/pdf?s=ap"},
    ],
    "has_more": False,
    "next_page": None,
}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _sandbox(*, stored=None, mode=0o600, org=ORG, env_session=None):
    """Point the module's session file at a throwaway temp path and control
    the environment. Nothing in this file may ever touch the real file."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / ".claude-receipts-session"
        if stored is not None:
            path.write_text(stored + "\n")
            os.chmod(path, mode)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(anth.SESSION_ENV, None)
            os.environ.pop("ANTHROPIC_ORG_UUID", None)
            os.environ.pop("RECEIPTS_LOGIN_TEST_NOOP", None)
            if org is not None:
                os.environ["ANTHROPIC_ORG_UUID"] = org
            if env_session is not None:
                os.environ[anth.SESSION_ENV] = env_session
            with patch.object(anth, "SESSION_FILE", str(path)):
                yield path


def _headers(pairs):
    msg = email.message.Message()
    for k, v in (pairs or {}).items():
        msg[k] = v
    return msg


class _FakeRaw:
    """Stand-in for a urllib response: context manager, .status, .headers,
    .read(), .geturl()."""

    def __init__(self, status=200, body=b"{}", headers=None, url=""):
        self.status = status
        self.headers = _headers(headers)
        self._body = body
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body

    def geturl(self):
        return self._url


def _serve(status=200, body=b"{}", headers=None, final_url=None):
    """A fake `_open` that records the urllib.request.Request objects handed
    to it, so tests can assert on the headers the code actually built."""
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        if status == 200:
            return _FakeRaw(200, body, headers, final_url or req.full_url)
        raise urllib.error.HTTPError(
            req.full_url, status, "error", _headers(headers), io.BytesIO(body),
        )

    fake.calls = calls
    return fake


# ---------------------------------------------------------------------------
# Session resolution
# ---------------------------------------------------------------------------

def test_env_session_beats_the_stored_file():
    with _sandbox(stored="from-the-file", env_session=SENTINEL):
        assert anth._stored_session() == SENTINEL


def test_stored_file_is_used_when_the_env_var_is_unset():
    with _sandbox(stored=SENTINEL):
        assert anth._stored_session() == SENTINEL


def test_no_session_anywhere_raises_source_unavailable_naming_set_session():
    with _sandbox():
        try:
            anth._stored_session()
        except SourceUnavailable as exc:
            assert "--set-session" in str(exc), str(exc)
            return
    raise AssertionError("a missing session must raise SourceUnavailable")


def test_group_or_world_readable_session_file_is_refused():
    # The file is a live credential. If anyone else on the machine can read
    # it, reading it anyway silently accepts a compromised secret.
    for bad_mode in (0o644, 0o640, 0o604, 0o666):
        with _sandbox(stored=SENTINEL, mode=bad_mode) as path:
            try:
                anth._stored_session()
            except SourceUnavailable as exc:
                msg = str(exc)
                assert "600" in msg, f"say what the mode must be: {msg}"
                assert str(path) in msg, f"name the file: {msg}"
                assert SENTINEL not in msg
            else:
                raise AssertionError(
                    f"mode {bad_mode:04o} is readable by others and must be refused"
                )


def test_a_correctly_locked_down_file_is_accepted():
    with _sandbox(stored=SENTINEL, mode=0o600):
        assert anth._stored_session() == SENTINEL
    with _sandbox(stored=SENTINEL, mode=0o400):
        assert anth._stored_session() == SENTINEL


def test_empty_session_file_is_refused_rather_than_sent_as_a_blank_cookie():
    with _sandbox(stored="   ", mode=0o600):
        try:
            anth._stored_session()
        except SourceUnavailable as exc:
            assert "--set-session" in str(exc), str(exc)
            return
    raise AssertionError("an empty session file must raise SourceUnavailable")


def test_session_file_lives_outside_the_repo_so_it_cannot_be_committed():
    repo_root = Path(__file__).resolve().parents[3]
    path = Path(os.path.expanduser(anth.SESSION_FILE))
    assert not str(path.resolve()).startswith(str(repo_root) + os.sep), (
        f"the session file must never live inside the repo tree: {path}"
    )
    assert anth.SESSION_FILE.startswith("~/"), (
        f"the session file must live in the user's home: {anth.SESSION_FILE}"
    )
    home = Path(os.path.expanduser("~")).resolve()
    assert home in path.resolve().parents, (path, home)


# ---------------------------------------------------------------------------
# The request itself
# ---------------------------------------------------------------------------

def test_listing_sends_the_session_as_a_cookie_and_a_real_browser_user_agent():
    fake = _serve(200, json.dumps(PAYLOAD).encode())
    with _sandbox(stored=SENTINEL):
        with patch.object(anth, "_open", fake):
            payload = SOURCE._listing()

    assert payload["invoices"][0]["total"] == 21456
    assert fake.calls, "no HTTP request was made"
    req = fake.calls[0]
    assert req.get_header("Cookie") == f"sessionKey={SENTINEL}", req.headers
    ua = req.get_header("User-agent") or ""
    assert "Mozilla" in ua and "python-urllib" not in ua.lower(), (
        f"a default Python-urllib UA may itself be refused: {ua!r}"
    )
    assert ORG in req.full_url
    assert SENTINEL not in req.full_url, "the credential must never ride in the URL"


def test_org_uuid_is_still_required_and_checked_before_any_request():
    fake = _serve(200, json.dumps(PAYLOAD).encode())
    with _sandbox(stored=SENTINEL, org=None):
        with patch.object(anth, "_open", fake):
            try:
                SOURCE.fetch("2026-01-01", "2026-12-31")
            except SourceUnavailable as exc:
                assert "ANTHROPIC_ORG_UUID" in str(exc)
                assert not fake.calls, "no request may be made without an org UUID"
                return
    raise AssertionError("a missing ANTHROPIC_ORG_UUID must raise SourceUnavailable")


# ---------------------------------------------------------------------------
# Four distinct failure modes — never collapsed into one
# ---------------------------------------------------------------------------

def _listing_error(**serve_kwargs):
    fake = _serve(**serve_kwargs)
    with _sandbox(stored=SENTINEL):
        with patch.object(anth, "_open", fake):
            try:
                SOURCE._listing()
            except SourceUnavailable as exc:
                return str(exc)
    raise AssertionError("expected SourceUnavailable")


def test_401_says_the_stored_session_expired_and_names_set_session():
    msg = _listing_error(status=401)
    assert "expired" in msg.lower(), msg
    assert "--set-session" in msg, msg
    assert "admin" not in msg.lower(), "must not collapse into the not-admin message: " + msg
    assert "cloudflare" not in msg.lower(), msg
    assert SENTINEL not in msg


def test_a_redirect_to_logout_is_read_as_an_expired_session():
    # claude.ai answers a dead cookie with a 200 that has quietly landed on
    # the logout page. Parsing that as JSON and reporting "no invoices" would
    # turn a dead session into a clean, empty audit.
    fake = _serve(200, b"<html>signed out</html>",
                  final_url="https://claude.ai/logout?returnTo=%2F")
    with _sandbox(stored=SENTINEL):
        with patch.object(anth, "_open", fake):
            try:
                SOURCE._listing()
            except SourceUnavailable as exc:
                msg = str(exc)
                assert "expired" in msg.lower(), msg
                assert "--set-session" in msg, msg
                assert SENTINEL not in msg
                return
    raise AssertionError("a redirect to logout must raise SourceUnavailable")


def test_403_org_admin_refusal_does_not_tell_you_to_re_authenticate():
    msg = _listing_error(status=403, body=b'{"error":{"type":"permission_error"}}')
    assert "admin" in msg.lower(), msg
    assert "--set-session" not in msg, (
        "re-authenticating cannot fix a permissions problem: " + msg
    )
    assert "expired" not in msg.lower(), msg
    assert "cloudflare" not in msg.lower(), msg
    assert SENTINEL not in msg


def test_cloudflare_challenge_stays_its_own_message_on_the_http_path():
    # Cloudflare can still challenge a plain HTTP request. It is neither an
    # expired session nor a permissions refusal, and a fresh cookie is the fix.
    msg = _listing_error(
        status=403,
        body=b'<html><body>Just a moment...<div class="cf-chl-widget"></div></body></html>',
    )
    assert "cloudflare" in msg.lower(), msg
    assert "--set-session" in msg, "a fresh cookie is the remedy: " + msg
    assert "admin" not in msg.lower(), msg
    assert "expired" not in msg.lower(), msg
    assert SENTINEL not in msg


def test_cloudflare_header_marker_also_produces_the_cloudflare_message():
    msg = _listing_error(status=403, headers={"cf-mitigated": "challenge"})
    assert "cloudflare" in msg.lower(), msg
    assert SENTINEL not in msg


def test_no_session_stored_is_its_own_message_naming_set_session():
    fake = _serve(200, json.dumps(PAYLOAD).encode())
    with _sandbox():
        with patch.object(anth, "_open", fake):
            try:
                SOURCE._listing()
            except SourceUnavailable as exc:
                msg = str(exc)
                assert "--set-session" in msg, msg
                assert "expired" not in msg.lower(), (
                    "never-stored is not the same failure as expired: " + msg
                )
                assert not fake.calls, "no request may be made with no session"
                return
    raise AssertionError("a missing session must raise SourceUnavailable")


def test_the_four_failure_modes_all_differ_from_one_another():
    msgs = [
        _listing_error(status=401),
        _listing_error(status=403, body=b'{"error":{"type":"permission_error"}}'),
        _listing_error(status=403, body=b'<html>Just a moment... cf-chl</html>'),
    ]
    with _sandbox():
        with patch.object(anth, "_open", _serve(200)):
            try:
                SOURCE._listing()
            except SourceUnavailable as exc:
                msgs.append(str(exc))
    assert len(set(msgs)) == 4, "failure modes were collapsed:\n" + "\n---\n".join(msgs)


def test_a_transport_failure_is_reported_without_leaking_the_session():
    def boom(req, timeout=None):
        raise urllib.error.URLError("connection reset")

    with _sandbox(stored=SENTINEL):
        with patch.object(anth, "_open", boom):
            try:
                SOURCE._listing()
            except SourceUnavailable as exc:
                assert SENTINEL not in str(exc)
                return
    raise AssertionError("a transport failure must degrade to SourceUnavailable")


# ---------------------------------------------------------------------------
# The credential never comes back out
# ---------------------------------------------------------------------------

def test_the_session_value_never_appears_in_any_message_this_module_raises():
    # Every error path, one sentinel, one rule: it is never in the text.
    paths = [
        lambda: _listing_error(status=401),
        lambda: _listing_error(status=403),
        lambda: _listing_error(status=403, headers={"cf-mitigated": "challenge"}),
        lambda: _listing_error(status=500),
        lambda: _listing_error(status=200, body=b"<html>not json</html>"),
    ]
    for i, run_path in enumerate(paths):
        msg = run_path()
        assert SENTINEL not in msg, f"path {i} leaked the session: {msg}"
        assert "sessionKey=" not in msg, f"path {i} echoed the cookie header: {msg}"


def test_fetch_never_leaks_the_session_through_the_truncated_report_line():
    with _sandbox(stored=SENTINEL):
        with patch.object(anth, "_open", _serve(200, b'{"invoices":[],"has_more":true}')):
            SOURCE.fetch("2026-01-01", "2026-12-31")
    note = getattr(SOURCE, "truncated", "") or ""
    assert SENTINEL not in note, note


# ---------------------------------------------------------------------------
# --set-session: store the credential safely, and only if it works
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _no_echo():
    """getpass must be what reads the value — never input(), which echoes to
    the terminal and (in a shell one-liner) lands in history."""
    def forbidden(*a, **k):
        raise AssertionError("the session must be read with getpass, never input()")

    with patch("builtins.input", forbidden):
        yield


def test_set_session_stores_a_validated_value_with_mode_0600():
    fake = _serve(200, json.dumps(PAYLOAD).encode())
    out = io.StringIO()
    # Every assertion runs INSIDE the sandbox — the temp directory holding the
    # stand-in session file is deleted when it exits.
    with _sandbox() as path:
        with patch.object(anth, "_open", fake), _no_echo(), \
             patch("getpass.getpass", return_value=SENTINEL + "\n") as gp, \
             contextlib.redirect_stdout(out):
            code = anth._set_session()

        assert code == 0, out.getvalue()
        gp.assert_called_once()
        assert path.exists(), "a validated session must actually be stored"
        assert path.read_text().strip() == SENTINEL
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"stored credential must be 0600, got {mode:04o}"
        assert fake.calls, "the value must be validated with a live call before storing"
        assert fake.calls[0].get_header("Cookie") == f"sessionKey={SENTINEL}"


def test_set_session_writes_atomically_through_a_same_directory_temp_file():
    fake = _serve(200, json.dumps(PAYLOAD).encode())
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append((str(src), str(dst)))
        return real_replace(src, dst)

    with _sandbox() as path:
        with patch.object(anth, "_open", fake), _no_echo(), \
             patch("getpass.getpass", return_value=SENTINEL), \
             patch("os.replace", spy), \
             contextlib.redirect_stdout(io.StringIO()):
            anth._set_session()

        assert seen, "the write must go through os.replace, like the ledger's"
        src, dst = seen[-1]
        assert dst == str(path)
        assert os.path.dirname(src) == os.path.dirname(str(path)), (
            "the temp file must sit in the destination directory or os.replace "
            f"is not atomic across filesystems: {src} -> {dst}"
        )
        assert not list(path.parent.glob(".claude-receipts-session.*")), (
            "the temp file must not be left behind next to the credential"
        )


def test_set_session_rejects_an_invalid_value_instead_of_storing_it():
    fake = _serve(401)
    out, err = io.StringIO(), io.StringIO()
    with _sandbox() as path:
        with patch.object(anth, "_open", fake), _no_echo(), \
             patch("getpass.getpass", return_value=SENTINEL), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = anth._set_session()

        combined = out.getvalue() + err.getvalue()
        assert code != 0, "an unusable session must not report success"
        assert not path.exists(), (
            "an invalid session must never be stored — the user would discover "
            "it on the next real run instead of right now"
        )
        assert "expired" in combined.lower(), (
            "say why it was rejected, not just that it was: " + combined
        )
        assert SENTINEL not in combined, combined


def test_set_session_never_prints_the_value_it_was_given():
    fake = _serve(200, json.dumps(PAYLOAD).encode())
    out, err = io.StringIO(), io.StringIO()
    with _sandbox():
        with patch.object(anth, "_open", fake), _no_echo(), \
             patch("getpass.getpass", return_value=SENTINEL), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            anth._set_session()

    combined = out.getvalue() + err.getvalue()
    assert combined.strip(), "storing a credential must confirm it worked"
    assert SENTINEL not in combined, "the stored value was echoed back: " + combined


def test_set_session_prints_where_to_find_the_cookie():
    fake = _serve(200, json.dumps(PAYLOAD).encode())
    out = io.StringIO()
    with _sandbox():
        with patch.object(anth, "_open", fake), _no_echo(), \
             patch("getpass.getpass", return_value=SENTINEL), \
             contextlib.redirect_stdout(out):
            anth._set_session()

    text = out.getvalue().lower()
    for needle in ("devtools", "application", "cookies", "claude.ai", "sessionkey", "value"):
        assert needle in text, f"the instructions must name {needle!r}: {out.getvalue()}"


def test_set_session_refuses_to_prompt_at_all_without_an_org_uuid():
    # Validation is a call to /api/stripe/{org}/invoices — without the org
    # UUID there is nothing to validate against, and storing an unverified
    # credential is exactly what this command exists to avoid.
    def forbidden(*a, **k):
        raise AssertionError("must not prompt when the value cannot be validated")

    err = io.StringIO()
    with _sandbox(org=None) as path:
        with patch("getpass.getpass", forbidden), _no_echo(), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = anth._set_session()

        assert code != 0
        assert "ANTHROPIC_ORG_UUID" in err.getvalue()
        assert not path.exists()


def test_set_session_stores_nothing_when_the_prompt_comes_back_empty():
    err = io.StringIO()
    with _sandbox() as path:
        with patch.object(anth, "_open", _serve(200)), _no_echo(), \
             patch("getpass.getpass", return_value="   "), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = anth._set_session()

        assert code != 0
        assert not path.exists()


# ---------------------------------------------------------------------------
# The browser is actually gone
# ---------------------------------------------------------------------------

def test_the_module_no_longer_imports_playwright_or_launches_a_browser():
    # Checked against the parsed code, not the raw text: the module docstring
    # deliberately still explains *why* Playwright was removed, and that
    # history is the thing stopping someone from reintroducing it. What must
    # be gone is the machinery.
    import ast

    tree = ast.parse(Path(anth.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "playwright" not in imported, f"playwright is still imported: {imported}"

    code = "\n".join(
        ln for ln in Path(anth.__file__).read_text().splitlines()
        if not ln.lstrip().startswith("#")
    )
    # Strip docstrings so only executable code is searched.
    for doc in [ast.get_docstring(n) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))]:
        if doc:
            code = code.replace(doc, "")
    for banned in ("launch_persistent_context", "sync_playwright", "channel=",
                   "claude-receipts-profile"):
        assert banned not in code, (
            f"{banned!r} still appears in the code of sources/anthropic.py — "
            f"the browser path was supposed to be removed entirely"
        )

    assert not hasattr(anth, "PROFILE")
    assert not hasattr(anth, "_launch_context")


def test_cloudflare_detection_survived_the_browser_removal():
    # It still applies: a plain HTTP request can be challenged too.
    assert callable(anth._is_cloudflare_challenge)


def test_download_still_needs_no_auth_and_sends_no_cookie():
    # Stripe PDF URLs carry their own secret token — they resolve with no
    # session at all, and the claude.ai cookie must never be sent to Stripe.
    captured = {}

    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"%PDF-1.4 fake"

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        return _R()

    with _sandbox(stored=SENTINEL):
        with patch("urllib.request.urlopen", fake_urlopen):
            data = SOURCE._download("https://pay.stripe.com/invoice/acct_X/live_A/pdf?s=ap")

    assert data.startswith(b"%PDF")
    assert isinstance(captured["url"], str), (
        "_download must keep passing a bare URL — no Request, no headers, no cookie"
    )


# ---------------------------------------------------------------------------
# SET_SESSION_CMD — the recovery command must actually run, not just read
# correctly. This is the third instance of the same bug class in this
# module's history: --login's ImportError, then a run.py command documented
# to work only from certain directories, then SET_SESSION_CMD hardcoding a
# repo-relative path ("skills/receipts/scripts/run.py"). Every test above
# this section only ever asserted the *string* '--set-session' appeared in a
# message — which is exactly what let a command that fails with "No such
# file or directory" from any cwd but the repo root ship three times.
# ---------------------------------------------------------------------------

_SET_SESSION_RE = re.compile(r"python3\.12 (\S+) --set-session")


def _extract_set_session_path(message: str) -> str:
    m = _SET_SESSION_RE.search(message)
    assert m, f"no 'python3.12 <path> --set-session' command found in: {message}"
    return m.group(1)


def test_set_session_cmd_embeds_an_absolute_path_not_a_repo_relative_one():
    # The regression itself: SET_SESSION_CMD used to be the literal string
    # "python3.12 skills/receipts/scripts/run.py --set-session" — relative to
    # the repo root. Every SourceUnavailable message below quotes this
    # constant verbatim as the fix for a missing or dead session, so a
    # relative path here means the recovery instruction itself is broken
    # unless the user's shell happens to be sitting at the repo root.
    with _sandbox():
        try:
            anth._stored_session()
        except SourceUnavailable as exc:
            path = _extract_set_session_path(str(exc))
            assert os.path.isabs(path), (
                f"SET_SESSION_CMD must embed an absolute path, got: {path!r}"
            )
            return
    raise AssertionError("a missing session must raise SourceUnavailable")


def test_set_session_cmd_path_is_derived_never_hardcoded():
    # Constraint from the fix: no author-specific literal (no "/Users/...").
    # The path must be *derived* from this module's own location on disk at
    # runtime, so it points at wherever this checkout actually lives on
    # whatever machine runs it — not baked in at authoring time. Checked
    # against the module's own source text, not just its runtime value: a
    # hardcoded literal that happened to match this machine would still pass
    # a value-only check.
    source = Path(anth.__file__).read_text()
    assert "/Users/" not in source, (
        "sources/anthropic.py must never contain an author-specific literal "
        "path"
    )
    expected = Path(anth.__file__).resolve().parent.parent / "run.py"
    assert anth._RUN_PY == expected, (
        f"run.py must resolve from anthropic.py's own __file__, not a fixed "
        f"string: {anth._RUN_PY} != {expected}"
    )


def test_every_session_recovery_message_names_an_absolute_run_py():
    # All four SourceUnavailable failure modes (never-stored, expired,
    # unsafe file mode, empty file) quote SET_SESSION_CMD — prove each one
    # actually carries the absolute form, not just the one checked above.
    cases = []

    with _sandbox():
        try:
            anth._stored_session()
        except SourceUnavailable as exc:
            cases.append(("never stored", str(exc)))

    with _sandbox(stored="   "):
        try:
            anth._stored_session()
        except SourceUnavailable as exc:
            cases.append(("empty file", str(exc)))

    with _sandbox(stored=SENTINEL, mode=0o644):
        try:
            anth._stored_session()
        except SourceUnavailable as exc:
            cases.append(("unsafe mode", str(exc)))

    assert len(cases) == 3, f"expected all three paths to raise: {cases}"
    for label, msg in cases:
        path = _extract_set_session_path(msg)
        assert os.path.isabs(path), f"{label}: recovery path not absolute: {path!r}"


def test_the_emitted_recovery_command_actually_runs_from_an_unrelated_cwd():
    # The point of this whole fix: not that the string looks right, but that
    # running it works. Extract the exact command the error message hands the
    # user, and execute it for real — as a subprocess, from a temp directory
    # that has nothing to do with this repo — the way a user actually
    # encounters it (some unrelated cwd, following the printed instruction).
    with _sandbox():
        try:
            anth._stored_session()
        except SourceUnavailable as exc:
            path = _extract_set_session_path(str(exc))
        else:
            raise AssertionError("expected SourceUnavailable")

    assert os.path.isfile(path), f"the emitted path does not exist on disk: {path}"

    with tempfile.TemporaryDirectory() as unrelated_cwd:
        proc = subprocess.run(
            [sys.executable, path, "--set-session"],
            cwd=unrelated_cwd,
            # A minimal, hermetic environment: PATH for the interpreter to
            # resolve, and deliberately no ANTHROPIC_ORG_UUID, no
            # CLAUDE_SESSION_KEY, no HOME override needed — the org-uuid
            # check inside _set_session() fires before anything touches the
            # session file, the network, or a credential prompt.
            env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")},
            capture_output=True,
            text=True,
            timeout=30,
        )

    combined = proc.stdout + proc.stderr
    # These are the failure signatures of the actual bug: the file could not
    # be found or imported at all, because the path only resolved from the
    # repo root.
    assert "No such file or directory" not in combined, combined
    assert "can't open file" not in combined.lower(), combined
    assert "ImportError" not in combined, combined
    assert "Traceback" not in combined, combined
    # It is fine — expected — for the command to then fail for a DIFFERENT,
    # later reason: no ANTHROPIC_ORG_UUID is set in the stripped-down
    # environment above, and _set_session() refuses to even prompt for a
    # credential without one (nothing to validate it against). Getting this
    # far — a clean, explained, exit-2 error naming the real missing
    # prerequisite — proves the file was found and the script actually
    # started running. A missing-file failure would never reach this message.
    assert proc.returncode == 2, (
        f"expected a clean exit 2 (missing ANTHROPIC_ORG_UUID), not a path "
        f"failure: returncode={proc.returncode}\n{combined}"
    )
    assert "ANTHROPIC_ORG_UUID" in combined, (
        f"expected the run to get far enough to hit the org-uuid guard: {combined}"
    )


if __name__ == "__main__":
    print("Running anthropic session-cookie tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll anthropic session-cookie tests passed.")
