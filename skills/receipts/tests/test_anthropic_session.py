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
import getpass
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sources.anthropic as anth
import sources.base as base
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
def _tty():
    """Stand in for an interactive terminal that can hide what is typed.

    The prompt refuses to run without one — see the no-terminal tests below —
    so every test that gets as far as the prompt has to say it has a terminal.
    Patching the whole object rather than one attribute: under pytest's
    capture, sys.stdin is a stub that may not accept attribute assignment.

    `base.controlling_terminal_available` is stubbed too, not just stdin: it
    is the thing the prompt actually asks, and stubbing it is what keeps
    these hermetic. Left to itself it would open the REAL /dev/tty, so the
    suite would behave one way in CI and another way in a developer's
    terminal — see tests/test_secret_prompt.py for that check done properly.
    """
    class _Stdin:
        def isatty(self):
            return True

    with patch.object(sys, "stdin", _Stdin()), \
         patch.object(base, "controlling_terminal_available", lambda: True):
        yield


@contextlib.contextmanager
def _no_terminal():
    """A process with no controlling terminal at all: a CI runner, an agent
    shell, `docker exec` without -t. Note this is NOT "stdin is redirected" —
    getpass opens /dev/tty itself, so `--set-session </dev/null` from a real
    terminal is safe and must still be allowed through."""
    class _Stdin:
        def isatty(self):
            return False

    with patch.object(sys, "stdin", _Stdin()), \
         patch.object(base, "controlling_terminal_available", lambda: False):
        yield


@contextlib.contextmanager
def _no_echo():
    """getpass must be what reads the value — never input(), which echoes to
    the terminal and (in a shell one-liner) lands in history."""
    def forbidden(*a, **k):
        raise AssertionError("the session must be read with getpass, never input()")

    with patch("builtins.input", forbidden), _tty():
        yield


def test_set_session_refuses_to_read_a_session_with_no_interactive_terminal():
    # getpass.getpass falls back to an ECHOING read from sys.stdin when no
    # echo-free TTY is available — printing the credential to the terminal and
    # into any transcript or job log. The same weakness as --set-neon-key, and
    # it fails closed the same way.
    def prompted(*a, **k):
        raise AssertionError(
            "getpass must not even be reached without an echo-free terminal"
        )

    out, err = io.StringIO(), io.StringIO()
    with _sandbox() as path:
        with patch.object(anth, "_open", _serve(200)), _no_terminal(), \
             patch("getpass.getpass", prompted), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = anth._set_session()

        combined = out.getvalue() + err.getvalue()
        assert code != 0, combined
        assert not path.exists(), "nothing may be stored when nothing was read"
        assert anth.SESSION_ENV in combined, (
            "point at the non-interactive alternative: " + combined
        )
        assert "echo" in combined.lower() or "terminal" in combined.lower(), combined


def test_set_session_refuses_when_getpass_says_it_would_echo():
    def echoing(prompt=""):
        import warnings as _w
        _w.warn("Can not control echo on the terminal.", getpass.GetPassWarning)
        return SENTINEL

    out, err = io.StringIO(), io.StringIO()
    with _sandbox() as path:
        with patch.object(anth, "_open", _serve(200)), _no_echo(), \
             patch("getpass.getpass", echoing), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = anth._set_session()

        combined = out.getvalue() + err.getvalue()
        assert code != 0, combined
        assert not path.exists(), (
            "a session read with echo on must not be stored as if it were safe"
        )
        assert SENTINEL not in combined, combined
        assert anth.SESSION_ENV in combined, combined


def test_a_getpass_that_would_echo_leaves_a_previously_stored_session_untouched():
    # Same guarantee as the Neon twin: the GetPassWarning conversion stands on
    # its own, with stdin a terminal so the precheck is not what stops it, and
    # a session already on disk survives byte for byte.
    previous = "sk-ant-sid01-PREVIOUSLY-STORED-DO-NOT-REPLACE"

    def echoing(prompt=""):
        import warnings as _w
        _w.warn("Can not control echo on the terminal.", getpass.GetPassWarning)
        return SENTINEL

    out, err = io.StringIO(), io.StringIO()
    with _sandbox(stored=previous) as path:
        before = path.read_bytes()
        with patch.object(anth, "_open", _serve(200)), _no_echo(), \
             patch("getpass.getpass", echoing), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = anth._set_session()

        combined = out.getvalue() + err.getvalue()
        assert code != 0, combined
        assert path.read_bytes() == before, (
            "the stored session was modified by a prompt that refused to read one"
        )
        assert SENTINEL not in combined, combined
        assert previous not in combined, combined


def test_the_refusal_to_prompt_never_leaks_a_previously_stored_session():
    previous = "sk-ant-sid01-PREVIOUSLY-STORED-DO-NOT-PRINT"
    out, err = io.StringIO(), io.StringIO()
    with _sandbox(stored=previous) as path:
        with _no_terminal(), contextlib.redirect_stdout(out), \
             contextlib.redirect_stderr(err):
            code = anth._set_session()

        combined = out.getvalue() + err.getvalue()
        assert code != 0, combined
        assert previous not in combined, combined
        assert path.read_text().strip() == previous


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


# ---------------------------------------------------------------------------
# A redirect must never carry the session to another origin
#
# urllib does not strip the Cookie header when it follows a redirect to a
# different origin (CPython #77842) — `redirect_request` rebuilds the request
# from the original headers minus only Content-Length/Content-Type. One
# redirect off claude.ai and the builder's live session is handed to whatever
# host the Location header names.
#
# The answer here is NOT to refuse redirects (that is sources/neon.py's, whose
# endpoint has never redirected). This source depends on following one:
# claude.ai answers a dead session with a 302 to /login, and reading that final
# URL is how an expired session is detected at all. So: follow, but strip the
# credential on a cross-origin hop. These tests hold both halves — the leak is
# closed AND expiry detection is untouched — by driving a real urllib handler
# chain with the socket layer replaced, not by asserting on a mock.
# ---------------------------------------------------------------------------

class _FakeResp:
    """Enough of an http.client response for urllib's own handler chain."""

    def __init__(self, code, body=b"", headers=None, url=""):
        self.code = self.status = code
        self.msg = self.reason = "OK" if code == 200 else "Found"
        self.headers = _headers(headers)
        self._body = body
        self.url = url

    def info(self):
        return self.headers

    def read(self, *a):
        return self._body

    def geturl(self):
        return self.url

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _redirecting_opener(target, body=None):
    """A real urllib opener wired to this module's redirect policy, with the
    socket layer replaced. The FIRST request is answered with a 302 to
    `target`; every later one (i.e. the followed redirect) answers 200.

    Every request the transport was asked to send is recorded, so a leak shows
    up as a real outbound request carrying the cookie — not as a call arg on a
    mock of the code under test.
    """
    seen = []
    payload = json.dumps(PAYLOAD).encode() if body is None else body

    class _FakeTransport(urllib.request.BaseHandler):
        handler_order = 100  # ahead of the real HTTPSHandler

        def https_open(self, req):
            seen.append(req)
            if len(seen) == 1:
                return _FakeResp(302, b"", {"Location": target}, req.full_url)
            return _FakeResp(200, payload, {}, req.full_url)

        # A redirect may downgrade the scheme. Without this the real
        # HTTPHandler would take that hop and these tests would hit the
        # network — they must never leave the process.
        http_open = https_open

    opener = urllib.request.build_opener(
        base.StripCredentialsOnCrossOriginRedirect, _FakeTransport())
    return opener, seen


def _follow_redirect_to(target, body=None):
    """Run one real `_listing()` through the redirect policy. Returns the
    requests the transport saw and whatever came back (a payload or the
    SourceUnavailable text)."""
    opener, seen = _redirecting_opener(target, body)
    with _sandbox(stored=SENTINEL):
        with patch.object(anth, "_opener", lambda: opener):
            try:
                outcome = SOURCE._listing()
            except SourceUnavailable as exc:
                outcome = str(exc)
    return seen, outcome


def _all_header_values(req) -> str:
    return " ".join(
        f"{k}: {v}"
        for store in (req.headers, req.unredirected_hdrs)
        for k, v in store.items()
    )


def test_a_cross_origin_redirect_is_followed_without_the_session_cookie():
    foreign = "https://receipts-decoy.example.invalid/api/stripe/x/invoices"
    seen, outcome = _follow_redirect_to(foreign)

    assert len(seen) == 2, (
        "the redirect must still be followed — expiry detection depends on it: "
        + str([r.full_url for r in seen])
    )
    first, second = seen
    assert first.host == "claude.ai", first.full_url
    assert first.get_header("Cookie") == f"sessionKey={SENTINEL}", (
        "the original request to claude.ai must still carry the session"
    )
    assert second.full_url == foreign, second.full_url
    assert second.get_header("Cookie") is None, (
        "the session was forwarded to a foreign host: " + second.full_url
    )


def test_the_session_never_reaches_a_foreign_requests_headers_at_all():
    # The sentinel is the whole point: not "no header named Cookie", but the
    # credential value itself appearing nowhere in what crossed the wire.
    for foreign in ("https://receipts-decoy.example.invalid/x",
                    "http://claude.ai/x",           # scheme downgrade
                    "https://claude.ai:8443/x"):    # port change
        seen, outcome = _follow_redirect_to(foreign)
        assert len(seen) == 2, (foreign, [r.full_url for r in seen])
        blob = _all_header_values(seen[1])
        assert SENTINEL not in blob, f"{foreign} received the session: {blob}"
        assert "sessionKey=" not in blob, f"{foreign} received a cookie: {blob}"
        assert SENTINEL not in str(outcome), outcome


def test_a_different_subdomain_is_treated_as_cross_origin():
    # `evil.claude.ai.example` is a stranger wearing a familiar prefix, and
    # `api.claude.ai` is a sibling the session was never volunteered to. A
    # suffix match would hand the credential to the first; "close enough"
    # would hand it to the second. Host equality is exact.
    for foreign in ("https://evil.claude.ai.example/api/stripe/x/invoices",
                    "https://api.claude.ai/api/stripe/x/invoices",
                    "https://claude.ai.attacker.test/x"):
        seen, _ = _follow_redirect_to(foreign)
        assert len(seen) == 2, (foreign, [r.full_url for r in seen])
        assert seen[1].get_header("Cookie") is None, (
            f"a subdomain change is cross-origin; {foreign} got the session"
        )
        assert SENTINEL not in _all_header_values(seen[1]), foreign


def test_a_same_origin_redirect_to_login_keeps_the_cookie_and_still_detects_expiry():
    # THE regression this must not cause. claude.ai answers a dead session
    # with a 302 to /login on its own origin; following it with the cookie
    # intact is how `_looks_logged_out` sees the final URL. Strip the cookie
    # here, or refuse the redirect, and an expired session either reads as a
    # different failure or — worse — as a clean, empty audit.
    seen, outcome = _follow_redirect_to(
        "https://claude.ai/login?returnTo=%2Fsettings%2Fbilling",
        body=b"<html>sign in</html>",
    )

    assert len(seen) == 2, (
        "the same-origin redirect must be followed: "
        + str([r.full_url for r in seen])
    )
    assert seen[1].get_header("Cookie") == f"sessionKey={SENTINEL}", (
        "a same-origin hop must keep the session — stripping it changes the "
        "behaviour expiry detection is built on: " + str(seen[1].headers)
    )
    assert isinstance(outcome, str), (
        "a redirect to /login must be reported as an expired session, not "
        f"parsed as invoice data: {outcome!r}"
    )
    assert "expired" in outcome.lower(), outcome
    assert "--set-session" in outcome, outcome
    assert SENTINEL not in outcome, outcome


def test_a_same_origin_redirect_that_is_not_a_login_page_still_returns_data():
    # The other half of "same-origin is untouched": a benign in-origin hop
    # completes normally and the payload comes back.
    seen, outcome = _follow_redirect_to(
        "https://claude.ai/api/stripe/v2/x/invoices?limit=100&page=")
    assert len(seen) == 2, [r.full_url for r in seen]
    assert seen[1].get_header("Cookie") == f"sessionKey={SENTINEL}"
    assert isinstance(outcome, dict) and outcome["invoices"][0]["total"] == 21456, outcome


def test_the_stock_urllib_handler_really_does_forward_the_cookie():
    # Keeps the tests above from being vacuous. If urllib had ever started
    # stripping credentials on a cross-origin redirect, every assertion in
    # this section would pass for free and prove nothing. It does not: the
    # same fake transport, driven through the STOCK handler, hands the
    # sentinel session to a foreign host. That is CPython #77842, executable.
    seen = []

    class _FakeTransport(urllib.request.BaseHandler):
        handler_order = 100

        def https_open(self, req):
            seen.append(req)
            if len(seen) == 1:
                return _FakeResp(
                    302, b"", {"Location": "https://receipts-decoy.example.invalid/x"},
                    req.full_url)
            return _FakeResp(200, b"{}", {}, req.full_url)

    stock = urllib.request.build_opener(_FakeTransport())
    req = urllib.request.Request("https://claude.ai/api/stripe/x/invoices",
                                 headers={"Cookie": f"sessionKey={SENTINEL}"})
    with stock.open(req, timeout=5):
        pass

    assert len(seen) == 2, [r.full_url for r in seen]
    assert seen[1].host == "receipts-decoy.example.invalid", seen[1].full_url
    assert SENTINEL in _all_header_values(seen[1]), (
        "urllib no longer forwards credentials across origins — if that is "
        "genuinely true now, this whole section needs rethinking rather than "
        "quietly passing"
    )


def test_the_listing_opener_carries_the_stripping_redirect_handler():
    handlers = anth._opener().handlers
    redirectors = [h for h in handlers
                   if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert redirectors, "urllib installs a redirect handler; ours must replace it"
    assert all(isinstance(h, base.StripCredentialsOnCrossOriginRedirect)
               for h in redirectors), (
        "the stock redirect handler is still installed and will forward the "
        f"Cookie header across origins: {redirectors}"
    )


def test_open_goes_through_that_opener_and_not_bare_urlopen():
    marker = object()
    calls = []

    class _Opener:
        def open(self, req, timeout=None):
            calls.append((req, timeout))
            return marker

    def forbidden(*a, **k):
        raise AssertionError(
            "urllib.request.urlopen uses the default opener, whose redirect "
            "handler forwards the Cookie header to another origin"
        )

    req = urllib.request.Request("https://claude.ai/x",
                                 headers={"Cookie": "sessionKey=x"})
    with patch.object(anth, "_opener", lambda: _Opener()), \
         patch("urllib.request.urlopen", forbidden):
        assert anth._open(req, timeout=7) is marker
    assert calls and calls[0][1] == 7, calls


# --- the shared origin rule itself ----------------------------------------

def test_same_origin_compares_scheme_host_and_port_exactly():
    same = [
        ("https://claude.ai/api/x", "https://claude.ai/login"),
        ("https://claude.ai/api/x", "https://CLAUDE.AI/login"),
        ("https://claude.ai/api/x", "https://claude.ai:443/login"),
        ("http://h.test:80/a", "http://h.test/b"),
    ]
    for a, b in same:
        assert base.same_origin(a, b), (a, b)

    different = [
        ("https://claude.ai/x", "https://api.claude.ai/x"),
        ("https://claude.ai/x", "https://evil.claude.ai.example/x"),
        ("https://claude.ai/x", "https://claude.ai.attacker.test/x"),
        ("https://claude.ai/x", "http://claude.ai/x"),
        ("https://claude.ai/x", "https://claude.ai:8443/x"),
        ("https://claude.ai/x", "https://claude.a/x"),
    ]
    for a, b in different:
        assert not base.same_origin(a, b), (a, b)


def test_same_origin_fails_closed_on_anything_it_cannot_parse():
    # The only thing this answer gates is whether a credential is re-sent, so
    # "I could not tell" must mean "not the same origin".
    for a, b in [
        ("https://claude.ai/x", "https://claude.ai:notaport/x"),
        ("https://claude.ai/x", "/login"),
        ("https://claude.ai/x", ""),
        ("", ""),
        ("https://claude.ai/x", None),
        (None, None),
    ]:
        assert not base.same_origin(a, b), (a, b)


def test_strip_credential_headers_sweeps_every_authority_bearing_header():
    req = urllib.request.Request("https://x.test/", headers={
        "Cookie": "sessionKey=abc",
        "Authorization": "Bearer abc",
        "Proxy-Authorization": "Basic abc",
        "Accept": "application/json",
    })
    req.add_unredirected_header("Cookie2", "$Version=1")
    removed = base.strip_credential_headers(req)

    assert sorted(n.lower() for n in removed) == [
        "authorization", "cookie", "cookie2", "proxy-authorization"], removed
    assert "abc" not in _all_header_values(req), _all_header_values(req)
    assert req.get_header("Accept") == "application/json", (
        "only credential headers may be removed"
    )


if __name__ == "__main__":
    print("Running anthropic session-cookie tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll anthropic session-cookie tests passed.")
