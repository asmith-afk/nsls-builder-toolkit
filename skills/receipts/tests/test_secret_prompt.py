#!/usr/bin/env python3.12
"""The hidden-credential prompt: what it refuses, and what it must not refuse.

`base.prompt_for_secret` is the one place a long-lived credential is typed.
It has two obligations that pull in opposite directions, and both have been
got wrong here before:

  * FAIL CLOSED. `getpass.getpass` is not unconditionally hidden. With no
    echo-free terminal it warns with GetPassWarning and then reads from
    sys.stdin WITH ECHO — printing the credential to the screen and into any
    transcript. Nothing may be read or stored in that state.
  * DO NOT OVER-REFUSE. The first attempt at fixing the above tested
    `sys.stdin.isatty()`, which is not the same question. `unix_getpass`
    opens /dev/tty itself, so `run.py --set-neon-key </dev/null` from a real
    terminal has a perfectly hidden prompt. Refusing it helped nobody and
    pushed people towards the workaround below.

And a third, which is why the refusal message itself is tested: the message
must not tell someone to run `export SECRET=value`. That is a shell command
with the credential inline, so it lands in ~/.zsh_history and any shell audit
log — a more durable leak than the echoed prompt it was offered to avoid.

Hermetic: no network, no auth, no real terminal. /dev/tty is never opened —
`os.open` is stubbed both ways — so these behave identically in CI and in a
developer's terminal, which is the whole point of stubbing it.
"""

import contextlib
import errno
import getpass
import os
import re
import sys
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sources.base as base
from sources.base import SecretPromptUnavailable, prompt_for_secret

SENTINEL = "secret_SENTINEL_DO_NOT_PRINT_0123456789"
SHIPPED_ROOT = Path(__file__).resolve().parent.parent


@contextlib.contextmanager
def _terminal(*, stdin_is_tty: bool, dev_tty_opens: bool):
    """Stub the two facts `controlling_terminal_available` reads.

    Never touches the real /dev/tty: a test whose result depends on whether
    the developer happened to run it from a terminal proves nothing.
    """
    class _Stdin:
        def isatty(self):
            return stdin_is_tty

    real_open = os.open

    def fake_open(path, *a, **k):
        if path == "/dev/tty":
            if not dev_tty_opens:
                raise OSError(errno.ENXIO, "no such device or address")
            # A real descriptor, so the caller's os.close() is a real close.
            return real_open(os.devnull, os.O_RDWR)
        return real_open(path, *a, **k)

    with patch.object(sys, "stdin", _Stdin()), \
         patch.object(os, "open", fake_open), \
         patch.object(os, "name", "posix"):
        yield


def _prompt(**kw):
    return prompt_for_secret("Paste it (hidden): ", label="Neon API key",
                             env_var="NEON_API_KEY",
                             command="python3.12 run.py --set-neon-key", **kw)


# ---------------------------------------------------------------------------
# Not over-refusing: a redirected stdin is not the same as no terminal
# ---------------------------------------------------------------------------

def test_prompt_proceeds_when_stdin_is_redirected_but_a_terminal_exists():
    # `--set-neon-key </dev/null` from a real terminal. getpass would open
    # /dev/tty and hide the prompt exactly as promised, so refusing here
    # rejects a safe invocation for no gain.
    with _terminal(stdin_is_tty=False, dev_tty_opens=True), \
         patch("getpass.getpass", return_value=SENTINEL):
        assert _prompt() == SENTINEL


def test_the_terminal_check_asks_about_dev_tty_not_about_stdin():
    with _terminal(stdin_is_tty=False, dev_tty_opens=True):
        assert base.controlling_terminal_available() is True
    with _terminal(stdin_is_tty=False, dev_tty_opens=False):
        assert base.controlling_terminal_available() is False
    # An interactive stdin is a terminal on its own — /dev/tty is not
    # consulted, and must not need to be.
    with _terminal(stdin_is_tty=True, dev_tty_opens=False):
        assert base.controlling_terminal_available() is True


def test_a_stdin_that_cannot_answer_isatty_falls_through_to_dev_tty():
    # pytest's captured stdin, a closed descriptor, a detached daemon. The
    # question is still "is there a terminal", not "did stdin raise".
    class _Broken:
        def isatty(self):
            raise ValueError("I/O operation on closed file")

    real_open = os.open

    def fake_open(path, *a, **k):
        if path == "/dev/tty":
            return real_open(os.devnull, os.O_RDWR)
        return real_open(path, *a, **k)

    with patch.object(sys, "stdin", _Broken()), \
         patch.object(os, "open", fake_open), patch.object(os, "name", "posix"):
        assert base.controlling_terminal_available() is True


# ---------------------------------------------------------------------------
# Failing closed: the guarantee the over-correction was protecting
# ---------------------------------------------------------------------------

def test_no_terminal_at_all_refuses_before_getpass_is_ever_reached():
    def forbidden(*a, **k):
        raise AssertionError(
            "getpass must not be reached when there is demonstrably no terminal"
        )

    with _terminal(stdin_is_tty=False, dev_tty_opens=False), \
         patch("getpass.getpass", forbidden):
        with pytest.raises(SecretPromptUnavailable) as caught:
            _prompt()

    msg = str(caught.value)
    assert "terminal" in msg.lower(), msg
    assert "NEON_API_KEY" in msg, "name the non-interactive alternative: " + msg


def test_getpass_warning_still_refuses_and_never_returns_the_value():
    # The real safety net, and the one that must survive dropping the stdin
    # check: getpass warns BEFORE it reads, so converting the warning to an
    # error means the credential is never typed rather than typed and then
    # discarded. Stdin here IS a terminal — this path is reached on its own.
    def echoing(prompt=""):
        warnings.warn("Can not control echo on the terminal.",
                      getpass.GetPassWarning)
        return SENTINEL

    with _terminal(stdin_is_tty=True, dev_tty_opens=False), \
         patch("getpass.getpass", echoing):
        with pytest.raises(SecretPromptUnavailable) as caught:
            _prompt()

    msg = str(caught.value)
    assert SENTINEL not in msg, msg
    assert "echo" in msg.lower(), msg
    # And the refusal must not hand over the leaky workaround (see below).
    assert "export NEON_API_KEY=" not in msg, msg
    assert "read -rs NEON_API_KEY" in msg, msg


def test_a_warning_that_is_not_getpass_does_not_become_a_refusal():
    # simplefilter("error", GetPassWarning) is scoped to that category; an
    # unrelated DeprecationWarning from inside getpass must not be mistaken
    # for "this terminal echoes" and must not lose the value.
    def noisy(prompt=""):
        warnings.warn("unrelated", DeprecationWarning)
        return SENTINEL

    with _terminal(stdin_is_tty=True, dev_tty_opens=False), \
         patch("getpass.getpass", noisy):
        assert _prompt() == SENTINEL


# ---------------------------------------------------------------------------
# The advice itself: never `export SECRET=value`
# ---------------------------------------------------------------------------

def test_the_refusal_suggests_a_history_safe_way_to_set_the_variable():
    with _terminal(stdin_is_tty=False, dev_tty_opens=False):
        with pytest.raises(SecretPromptUnavailable) as caught:
            _prompt()

    msg = str(caught.value)
    assert "printf 'Neon API key: '; read -rs NEON_API_KEY; echo; " \
           "export NEON_API_KEY" in msg, msg
    # `read -p` is bash's prompt flag; in zsh -p reads from a coprocess. This
    # project has been bitten by that before, so pin it out of the suggestion.
    assert "read -p" not in msg, msg
    assert "export NEON_API_KEY=" not in msg, msg


def test_a_label_with_an_apostrophe_cannot_break_out_of_the_quoted_prompt():
    hint = base.env_var_hint("NEON_API_KEY", "Bob's key")
    assert "'Bob'\\''s key: '" in hint, hint


# ---------------------------------------------------------------------------
# No shipped string may suggest putting a credential on a command line
#
# Scanned, not asserted per-message, so a new message somewhere else cannot
# quietly reintroduce it. Only shipped files: SKILL.md and scripts/. Setting a
# NON-secret inline (NEON_ORG_ID, ANTHROPIC_ORG_UUID) is fine and stays
# readable — this looks for credentials specifically.
# ---------------------------------------------------------------------------

def _shipped_files() -> list[Path]:
    files = sorted(SHIPPED_ROOT.glob("*.md"))
    files += sorted((SHIPPED_ROOT / "scripts").rglob("*.py"))
    return [p for p in files if "__pycache__" not in p.parts]


# `export NAME=` where NAME names a credential, in literal or f-string-
# placeholder form (`export {env_var}=…` renders to exactly the same advice).
_SECRET_NAME = re.compile(r"(KEY|SESSION|TOKEN|SECRET|PASSWORD|COOKIE|CREDENTIAL)")
_EXPORT = re.compile(r"export\s+\{?([A-Za-z_][A-Za-z0-9_]*)\}?\s*=")

# Variables that hold a secret, spelled the way the code spells them —
# including the parameter names the message templates interpolate.
_SECRET_VARS = {"NEON_API_KEY", "CLAUDE_SESSION_KEY", "env_var",
                "KEY_ENV", "SESSION_ENV"}


def test_no_shipped_string_tells_anyone_to_export_a_credential_inline():
    offenders = []
    for path in _shipped_files():
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for match in _EXPORT.finditer(line):
                name = match.group(1)
                if name in _SECRET_VARS or _SECRET_NAME.search(name):
                    offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, (
        "a credential is being suggested inline on a command line, which puts "
        "it in shell history — use base.env_var_hint's form instead:\n"
        + "\n".join(offenders)
    )


def test_the_scan_would_actually_catch_the_thing_it_is_looking_for():
    # A vacuous scan passes forever. Prove the regex fires on the exact form
    # that was removed, and stays quiet on the non-secret ones that must
    # remain readable.
    for bad in ("  export NEON_API_KEY=…", "  export {env_var}=…",
                "export CLAUDE_SESSION_KEY=abc123"):
        match = _EXPORT.search(bad)
        assert match, bad
        name = match.group(1)
        assert name in _SECRET_VARS or _SECRET_NAME.search(name), bad

    for ok in ("  export NEON_ORG_ID=org-your-organization-id",
               "  export ANTHROPIC_ORG_UUID=<your-claude.ai-org-uuid>"):
        match = _EXPORT.search(ok)
        assert match, ok
        name = match.group(1)
        assert name not in _SECRET_VARS and not _SECRET_NAME.search(name), ok


def test_the_scan_looks_at_files_that_actually_exist():
    names = {p.name for p in _shipped_files()}
    assert "SKILL.md" in names, names
    assert "base.py" in names, names
    assert "neon.py" in names, names
    assert "anthropic.py" in names, names
