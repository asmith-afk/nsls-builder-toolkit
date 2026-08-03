#!/usr/bin/env python3.12
"""Contract every receipt source implements."""

import getpass
import hashlib
import importlib
import os
import pkgutil
import re
import stat
import sys
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import warnings
from dataclasses import dataclass
from pathlib import Path


class SourceUnavailable(Exception):
    """Source could not run — auth, network, config. Never a match failure."""


class SecretPromptUnavailable(Exception):
    """There was no way to read a secret without it being echoed, so none was
    read. Never raised after a value has been obtained — the whole point is
    that nothing was typed."""


# ---------------------------------------------------------------------------
# Stored credentials
#
# Two sources now hold a long-lived secret on disk (a claude.ai session, a
# Neon API key) and both have exactly the same obligations: refuse a file
# other accounts can read, write atomically at 0600, and never let the value
# reach a message. Those three things live here so the two sources cannot
# drift apart on them — the messages stay per-source, because "the stored
# claude.ai session expired" and "re-issue this as an organization API key"
# are different instructions and must not be homogenised.
# ---------------------------------------------------------------------------

SECRET_MODE = 0o600
# Any group or other permission bit at all. Read is the dangerous one, but a
# credential file nobody else should touch has no business being group-
# writable or executable either.
UNSAFE_MODE_BITS = stat.S_IRWXG | stat.S_IRWXO


def scrub_secret(text, secret: str | None) -> str:
    """Defensive redaction. No source deliberately interpolates a credential
    into a message — but text that arrives from elsewhere (an OSError, a
    urllib exception, a server's own error body) can carry anything, and it
    is about to be shown to a user or written to a log. Assume any string
    being interpolated may reach a log and take the secret out of it first.
    """
    out = str(text)
    if secret:
        out = out.replace(secret, "<redacted credential>")
    return out


def env_var_hint(env_var: str, label: str) -> str:
    """A history-safe way to put a credential in the environment.

    NOT `export NAME=value`. That is a shell command with the secret inline,
    so the credential is written verbatim into ~/.zsh_history (or
    ~/.bash_history), into any shell audit log, and into the process table
    while it runs — defeating the exact guarantee `prompt_for_secret` exists
    to provide. Telling someone to do that as the "safe alternative" to an
    echoed prompt trades one leak for a more durable one.

    The form below never puts the value on a command line: `read` takes it
    from the terminal, `-s` keeps it off the screen, `-r` stops a backslash
    being eaten, and `export` then exports the ALREADY-SET name. Correct on
    both shells builders here use — zsh's `read -s` and bash's `read -s` both
    mean "do not echo", and neither `-r` nor a bare `export NAME` differs.
    Deliberately not `read -p`: that is bash's prompt flag, and in zsh `-p`
    reads from a coprocess instead, so the prompt would silently vanish and
    the read would fail. `printf` writes the prompt in both.
    """
    # Single-quote the prompt the POSIX way, so a label containing an
    # apostrophe cannot end the quoted string and turn the rest of the line
    # into something else. Neither current label has one; a future one might.
    quoted = label.replace("'", "'\\''")
    return f"  printf '{quoted}: '; read -rs {env_var}; echo; export {env_var}"


def controlling_terminal_available() -> bool:
    """True when there is a terminal a hidden prompt can be read from.

    Deliberately NOT `sys.stdin.isatty()`. `getpass.unix_getpass` opens
    /dev/tty itself and prompts there; it only falls back to an ECHOING read
    of sys.stdin — after a GetPassWarning — when that open fails. So a
    redirected stdin is not by itself unsafe: `run.py --set-neon-key
    </dev/null` from a real terminal still gets a properly hidden prompt.
    Checking stdin conflated "stdin is redirected" with "no echo-free
    terminal exists" and refused invocations that were never at risk.

    Fails closed in the direction that matters: this only ever returns True
    when a terminal was actually proven to exist (stdin is one, or /dev/tty
    opened). Anything else is False and nothing is read. It is not the real
    safety net either — the GetPassWarning conversion below is, and it stands
    alone — this exists to give a clearer message in the common case and to
    guarantee `getpass` is not even reached when there is demonstrably no
    terminal.
    """
    try:
        if sys.stdin.isatty():
            return True
    except (AttributeError, OSError, ValueError):
        # A closed, detached, or stubbed stdin. Says nothing about /dev/tty.
        pass

    if os.name != "posix":
        # There is no /dev/tty to test. Windows' getpass reads through msvcrt
        # without echo and never emits GetPassWarning, so refusing here would
        # reject every Windows run. Let it prompt.
        return True

    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return False
    os.close(fd)
    return True


def prompt_for_secret(prompt: str, *, label: str, env_var: str, command: str) -> str:
    """Read a credential from the terminal — or refuse to read one at all.

    `getpass.getpass` is not unconditionally hidden. When it cannot find an
    echo-free terminal (no controlling TTY, a CI runner, an agent shell, a
    `docker exec` without -t) it warns with GetPassWarning, prints "Warning:
    Password input may be echoed.", and then reads the value from sys.stdin
    WITH ECHO. The credential is printed to the screen, kept in scrollback,
    and captured in whatever log or transcript is recording that session —
    which is precisely the guarantee both callers make in their instructions
    ("the paste is hidden").

    So this fails closed, on both halves of that failure:

      * no controlling terminal at all -> refuse before prompting
      * getpass says it cannot hide it -> refuse, and never return the value

    The GetPassWarning is raised BEFORE the read (CPython's fallback_getpass
    warns first, then reads), so turning it into an error means the secret is
    never typed rather than typed and then discarded. That conversion is the
    guarantee; the terminal check in front of it is a clearer message, not a
    second line of defence, and it is deliberately narrow — see
    `controlling_terminal_available` for why testing stdin was wrong.

    Refusing is not a dead end: the environment variable is checked ahead of
    the stored file by every source here, so a non-interactive context has a
    first-class way to supply the value. The message says so — and says it in
    a form that does not put the credential into shell history.
    """
    fix = (f"Set it in the environment instead — {env_var} is checked before "
           f"the stored file, so a non-interactive run can supply it without "
           f"a prompt. Type the value rather than passing it as an argument, "
           f"so it never lands in your shell history (zsh and bash both):\n"
           f"{env_var_hint(env_var, label)}\n"
           f"Or run `{command}` again from a terminal.")

    if not controlling_terminal_available():
        raise SecretPromptUnavailable(
            f"Refusing to prompt for the {label}: this process has no "
            f"controlling terminal, so what you typed would be echoed to the "
            f"screen and captured in any log or transcript of this run. "
            f"Nothing was read and nothing was stored; any previously stored "
            f"value is untouched.\n{fix}"
        )

    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            value = getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise SecretPromptUnavailable(
                f"Refusing to read the {label}: this terminal cannot turn off "
                f"echo, so the value would be printed as you typed it and "
                f"captured in any log or transcript of this run. Nothing was "
                f"stored; any previously stored value is untouched.\n{fix}"
            ) from None

    return (value or "").strip()


def secret_file_mode(path: Path) -> int:
    """The file's permission bits. Raises OSError like stat() does."""
    return stat.S_IMODE(path.stat().st_mode)


def secret_file_is_unsafe(mode: int) -> bool:
    return bool(mode & UNSAFE_MODE_BITS)


def write_secret_file(value: str, path: Path, prefix: str) -> None:
    """Write a credential atomically at mode 0600.

    Same shape as the ledger's write: a temp file in the *destination
    directory* (os.replace is only atomic within one filesystem), permissions
    set on the file descriptor before a single byte of the secret is written,
    then an atomic rename. A half-written credential file would fail
    confusingly on the next run; a briefly world-readable one would be a leak.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=prefix)
    try:
        os.fchmod(fd, SECRET_MODE)
        with os.fdopen(fd, "w") as fh:
            fh.write(value + "\n")
        os.chmod(tmp, SECRET_MODE)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Redirect policy — where a credential goes when a server says "go elsewhere"
#
# urllib does NOT strip credential headers when it follows a redirect to a
# different origin (CPython #77842). `HTTPRedirectHandler.redirect_request`
# rebuilds the request from `req.headers` minus only the two CONTENT_HEADERS,
# so an `Authorization:` or `Cookie:` header we set by hand is re-sent verbatim
# to whatever host the `Location:` header names. (Cookies managed by a
# `CookieJar` escape this because the jar uses `add_unredirected_header`; ours
# are set explicitly, so they do not.) One redirect — a DNS takeover, a
# misconfiguration, a vendor's own change — and a builder's long-lived
# credential is handed to a third party.
#
# Two sources here send a credential header, and they need DIFFERENT answers,
# so this module holds the shared machinery and each source picks its policy:
#
#   * sources/neon.py      refuses redirects outright (`_RefuseRedirect`).
#     That endpoint has never redirected, so there is no working behaviour to
#     preserve and a redirect means something changed — stop and say so.
#   * sources/anthropic.py must FOLLOW a same-origin redirect: claude.ai
#     answers a dead session with a 302 to /login, and reading that final URL
#     is how an expired session is detected at all. So it follows, and strips
#     the credential headers on any cross-origin hop
#     (`StripCredentialsOnCrossOriginRedirect`).
#
# Both live on the same fact — `same_origin` is the single definition of
# "somewhere else" — so neither source can drift into a laxer rule alone.
# ---------------------------------------------------------------------------

# Lower-cased. Any header on this list carries authority and must not cross an
# origin boundary. `Cookie2` is long obsolete but costs nothing to cover, and
# `Proxy-Authorization` is a credential by any other name.
CREDENTIAL_HEADERS = frozenset({
    "authorization", "cookie", "cookie2", "proxy-authorization",
})

_DEFAULT_PORTS = {"http": 80, "https": 443, "ftp": 21}


def same_origin(a: str, b: str) -> bool:
    """True when two URLs share a scheme, host, and port.

    Deliberately an EXACT host comparison, not a suffix one: a redirect from
    `claude.ai` to `evil.claude.ai.example` is a different host, and so is a
    redirect to a genuinely-owned sibling like `api.claude.ai`. Volunteering a
    session to a different subdomain is a decision someone should make on
    purpose, not something a `Location:` header gets to make for them.

    Fails closed. Anything unparseable, schemeless, hostless, or carrying a
    malformed port is reported as NOT the same origin, because the only thing
    that answer gates is whether a credential is re-sent.
    """
    pa = urllib.parse.urlsplit(a or "")
    pb = urllib.parse.urlsplit(b or "")

    scheme = pa.scheme.lower()
    if not scheme or scheme != pb.scheme.lower():
        return False

    try:
        host_a, host_b = pa.hostname, pb.hostname
        port_a = pa.port or _DEFAULT_PORTS.get(scheme)
        port_b = pb.port or _DEFAULT_PORTS.get(pb.scheme.lower())
    except ValueError:
        # urlsplit defers port parsing to attribute access; a garbage port
        # ("https://claude.ai:notaport/") raises here.
        return False

    if not host_a or host_a.lower() != (host_b or "").lower():
        return False
    return port_a == port_b


def strip_credential_headers(req) -> list[str]:
    """Remove every credential-bearing header from a urllib Request, in place.

    Returns the names removed, so a caller can say what it did. Both header
    dicts are swept: `Request.headers` is what a redirect carries forward, and
    `unredirected_hdrs` is swept too so this cannot become subtly incomplete
    if a caller ever sets a credential there.
    """
    removed = []
    for store in (req.headers, req.unredirected_hdrs):
        for name in list(store):
            if name.lower() in CREDENTIAL_HEADERS:
                del store[name]
                removed.append(name)
    return removed


class StripCredentialsOnCrossOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never carry a credential to another origin.

    Same-origin hops are passed through untouched, so behaviour that depends
    on following a redirect (claude.ai's 302 to /login on a dead session) is
    exactly what it was. On a cross-origin hop the request is still followed —
    an unauthenticated GET to a stranger is harmless, and refusing would break
    that expiry detection — but every credential header is removed first.

    `redirect_request` is the right seam: urllib routes 301/302/303/307/308
    through it, it runs BEFORE any new request is built, and it is the exact
    method whose stock implementation copies the headers forward. The scrub
    happens on the object urllib is about to send, so there is no path where
    the header survives.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            # urllib's own answer for "this redirect should not be followed".
            return None
        if not same_origin(req.full_url, new.full_url):
            strip_credential_headers(new)
        return new


@dataclass(frozen=True)
class Receipt:
    merchant: str        # normalized
    amount_cents: int
    date: str            # ISO yyyy-mm-dd
    pdf_bytes: bytes
    provenance: str      # e.g. "anthropic:invoice 2026-07-19 108500"


def normalize_merchant(name: str) -> str:
    """Fold a merchant name to a comparable key.

    Two failures the naive `[^a-z0-9]` strip produced, both silent:

    * Accented Latin lost its letters instead of folding them. Ramp's
      "München" became "mnchen" while a receipt's "Munchen" became "munchen",
      so a real receipt for a real charge came back UNFOUND. NFKD decomposes
      the letter into base + combining mark; dropping only the marks keeps
      the base letter.
    * Merchants written entirely in a non-Latin script collapsed to "" — and
      so compared EQUAL to every other such merchant, and to a blank name.
      That is the dangerous direction: equal keys make one vendor's receipt an
      automatic upload against another vendor's charge. When nothing survives
      the fold, fall back to a per-name key that only ever equals itself.

    The result is always [a-z0-9]*, so normalize_merchant is idempotent —
    match.py re-normalizes already-normalized Receipt.merchant values.
    """
    decomposed = unicodedata.normalize("NFKD", name or "")
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]", "", folded.lower())
    if slug:
        return slug

    # Nothing survived. A name that is genuinely blank stays blank — there is
    # no merchant to distinguish. A name with real content gets a stable,
    # process-independent sentinel built only from [a-z0-9], so re-normalizing
    # it is a no-op and no two different names can ever collide into "".
    stripped = " ".join((name or "").split())
    if not stripped:
        return ""
    return "x" + hashlib.sha1(stripped.casefold().encode("utf-8")).hexdigest()[:16]


def load_sources(errors: list | None = None) -> list:
    """Every sources/*.py module exposing a SOURCE singleton.

    One source failing at import — a missing dependency, a syntax error, a
    module-level side effect that raises — must not end discovery for the
    others. Failures are appended to `errors` as "NAME: reason" so the caller
    can announce them the same way it announces a source that was skipped at
    fetch time. Swallowing them silently would leave a run that found fewer
    receipts than it should looking exactly like a clean one.
    """
    import sources

    found = []
    for mod in pkgutil.iter_modules(sources.__path__):
        if mod.name == "base":
            continue
        try:
            module = importlib.import_module(f"sources.{mod.name}")
        except Exception as exc:
            if errors is not None:
                errors.append(f"{mod.name.upper()}: import failed — {type(exc).__name__}: {exc}")
            continue
        if hasattr(module, "SOURCE"):
            found.append(module.SOURCE)
    return found
