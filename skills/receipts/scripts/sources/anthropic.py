#!/usr/bin/env python3.12
"""Anthropic (claude.ai) billing source.

Anthropic emails receipts for the subscription charges but NOTHING for
usage-credit auto-recharges — those are 15 of the 22 gaps. The listing call
needs a claude.ai session; the PDF URLs it returns are Stripe secret-token URLs
that resolve with no authentication at all (verified 2026-08-01).

ANTHROPIC_ORG_UUID must be set in the environment — this module ships in an
org-wide toolkit and must never default to one specific organisation's ID.

WHY THERE IS NO BROWSER HERE
----------------------------
This source used to drive Playwright. It failed twice in the field:

* Bundled Chromium got fingerprinted by Cloudflare and served an endless
  "verify you are human" loop that never resolved.
* Real installed Chrome (`channel="chrome"`) fails on macOS with "Opening in
  existing browser session" — launching the installed Chrome while the user's
  own Chrome is running hands the request off to the existing instance instead
  of starting one with our profile, so it would have required quitting Chrome
  before every login. Orphaned browser processes also left stale `Singleton*`
  locks in the profile directory that broke subsequent runs.

A session cookie alone is sufficient: an authenticated GET to
`/api/stripe/{org}/invoices?limit=3&page=` returns HTTP 200 with real invoice
data; the same URL with no cookie returns 403 (verified live 2026-08-01). The
browser only ever existed to *obtain* that cookie — which is precisely the
thing Cloudflare guards. So the cookie is captured once by hand and sent with
stdlib urllib. No Playwright, no Chromium, no browser profile, no new pip
dependency.

THE SESSION IS A CREDENTIAL
---------------------------
Anyone holding it can act as the user on claude.ai. Therefore, in this module:

* It is read from CLAUDE_SESSION_KEY, else from a 0600 file in the user's
  home (never the repo tree, so it cannot be committed).
* A file readable by group or others is REFUSED, not used.
* Its value is never printed, logged, echoed, or interpolated into any error
  message, report line, ledger entry, or exception text. Messages refer to
  "the stored session"; `_scrub()` is a defensive second line for text that
  came from somewhere else (an OS error, a urllib exception) before it is
  handed to a user.
"""

import datetime as dt
import getpass
import hashlib
import json
import os
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

try:
    from .base import Receipt, SourceUnavailable
except ImportError:
    # Running this file directly (`python3.12 sources/anthropic.py
    # --set-session`) gives it no parent package, so the relative import above
    # fails with "attempted relative import with no known parent package" —
    # before this module's own `if __name__ == "__main__":` block at the
    # bottom ever runs. That command used to be exactly what the
    # SourceUnavailable message below and SKILL.md told a user to run for a
    # dead claude.ai session, so the fix for the failure was itself
    # unreachable. `run.py --set-session` is the documented entry point now
    # (it already resolves imports correctly), but this direct-script form may
    # still be in someone's notes or muscle memory — make it work too: put
    # this file's parent directory (the `scripts/` dir) on sys.path so
    # `sources` is importable as a real top-level package, then import the
    # same module absolutely. `python3.12 -m sources.anthropic --set-session`
    # already runs with a package context, so this branch never triggers there.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sources.base import Receipt, SourceUnavailable

LISTING = "https://claude.ai/api/stripe/{org}/invoices?limit={limit}&page={page}"
PAGE_GUARD = 20  # pages (100 invoices/page = 2,000 invoices) — see fetch()

# Where the session comes from. The environment wins, so a CI job or a
# password-manager shim can supply it without a file existing at all.
SESSION_ENV = "CLAUDE_SESSION_KEY"
# Deliberately stored unexpanded and expanded at use time: tests point this at
# a temp path, and it must land in the user's home — never inside the repo,
# where it could be committed.
SESSION_FILE = "~/.claude-receipts-session"
SESSION_MODE = 0o600
# Any group or other permission bit at all. Read is the dangerous one, but a
# credential file nobody else should touch has no business being group-
# writable or executable either.
_UNSAFE_MODE_BITS = stat.S_IRWXG | stat.S_IRWXO

# claude.ai's edge refuses (or challenges) a default `Python-urllib/3.12`
# User-Agent. This is a plain, current desktop-Chrome UA string: it is not an
# attempt to defeat bot detection — the request carries the user's own real
# session — it just keeps a normal authenticated read from being rejected on
# the header alone.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")

# Cloudflare challenge pages (the "Just a moment…" interstitial and its
# variants) reliably contain one of these markers in the body, or set one of
# these response headers on the mitigated request. Neither is guaranteed to
# be exhaustive — Cloudflare changes challenge markup over time — but this
# covers the documented, currently-observed forms.
_CF_BODY_MARKERS = ("cf-chl", "just a moment", "attention required! | cloudflare",
                    "challenge-platform")
_CF_HEADER_MARKERS = ("cf-mitigated", "cf-chl-bypass")

# A 200 that has quietly landed here is a dead session, not an empty account.
_LOGGED_OUT_PATHS = ("/login", "/logout", "/sign-in", "/signin")

# Third instance of the same bug class in this module's history (see the
# ImportError note on the relative import above, and the run.py-from-anywhere
# fix that followed it): a recovery command told a user to run something that
# only worked from one directory. This one hardcoded a repo-relative path —
# "skills/receipts/scripts/run.py" — and every missing/expired-session
# message below tells the user to run exactly this string. That works only
# when the shell's cwd happens to be the repo root, which is not where
# /receipts runs from in the common case.
#
# Fix: resolve run.py's absolute path at runtime from this file's own
# location rather than assuming anything about cwd. This module lives at
# <skill>/scripts/sources/anthropic.py; run.py lives at
# <skill>/scripts/run.py — one directory up from this file's parent. The
# result is author- and machine-independent: it is derived fresh on whatever
# machine and checkout this happens to run on, never hardcoded.
_RUN_PY = Path(__file__).resolve().parent.parent / "run.py"
SET_SESSION_CMD = f"python3.12 {_RUN_PY} --set-session"

COOKIE_INSTRUCTIONS = f"""\
Storing a claude.ai session for the Anthropic billing source.

Where to get the value:
  1. Open https://claude.ai in Chrome, signed in to the right account.
  2. Open DevTools (Option-Command-I on macOS, F12 elsewhere).
  3. Go to the Application tab -> Storage -> Cookies -> https://claude.ai
  4. Find the row named `sessionKey` and copy its Value column (the whole
     string — it is long).
  5. Paste it at the prompt below.

The paste is hidden: it is not echoed to the terminal and never enters your
shell history. It is stored at {SESSION_FILE} with mode 0600 (only you can
read it) and validated against claude.ai before it is written.
"""


def _session_path() -> Path:
    """The stored-session file, expanded at call time.

    Expanding at import time would freeze whatever HOME happened to be set to
    then; this also lets the tests redirect SESSION_FILE into a temp
    directory, so no test can read or clobber a real credential.
    """
    return Path(os.path.expanduser(SESSION_FILE))


def _scrub(text: str, secret: str | None) -> str:
    """Defensive redaction. Nothing in this module deliberately interpolates
    the session into a message — but text that arrives from elsewhere (an
    OSError, a urllib exception, a header dump) can carry anything, and it is
    about to be shown to a user or written to a log. Assume any string being
    interpolated may reach a log and take the secret out of it first.
    """
    out = str(text)
    if secret:
        out = out.replace(secret, "<redacted session>")
    return out


def _stored_session() -> str:
    """The claude.ai session key, from the environment or the stored file.

    Raises SourceUnavailable — never returns a partial or unsafe value, and
    never puts the value itself in the failure message.
    """
    from_env = (os.environ.get(SESSION_ENV) or "").strip()
    if from_env:
        return from_env

    path = _session_path()
    if not path.exists():
        raise SourceUnavailable(
            f"No claude.ai session is stored, so the Anthropic billing source "
            f"cannot authenticate. Store one with: {SET_SESSION_CMD} "
            f"(or set {SESSION_ENV} in the environment)."
        )

    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise SourceUnavailable(
            f"Could not read the stored claude.ai session at {path}: "
            f"{type(exc).__name__}: {exc}"
        ) from None

    if mode & _UNSAFE_MODE_BITS:
        raise SourceUnavailable(
            f"Refusing to use the stored claude.ai session at {path}: its mode "
            f"is {mode:04o}, which lets other accounts on this machine read it. "
            f"That file is a live credential — anyone holding it can act as you "
            f"on claude.ai. Fix it with `chmod 600 {path}`, or re-store the "
            f"session with: {SET_SESSION_CMD}"
        )

    try:
        value = path.read_text().strip()
    except OSError as exc:
        raise SourceUnavailable(
            f"Could not read the stored claude.ai session at {path}: "
            f"{type(exc).__name__}: {exc}"
        ) from None

    if not value:
        raise SourceUnavailable(
            f"The stored claude.ai session at {path} is empty. Store a real one "
            f"with: {SET_SESSION_CMD}"
        )
    return value


def _open(req, timeout: int = 60):
    """The single seam where this module touches the network.

    Isolated in one two-line function so the tests can replace it and still
    exercise the real Request construction — the headers, the URL, the cookie
    — rather than a mock of the code under test.
    """
    return urllib.request.urlopen(req, timeout=timeout)


class _HttpResponse:
    """A uniform view of whatever came back — a urllib response or the
    HTTPError raised in its place — shaped so `_is_cloudflare_challenge` can
    read it unchanged (`.status`, `.headers`, `.text()`).
    """

    def __init__(self, status, headers, body: bytes, url: str = ""):
        self.status = status
        try:
            self.headers = dict(headers.items()) if headers is not None else {}
        except Exception:
            self.headers = {}
        self._body = body or b""
        self.url = url

    def text(self) -> str:
        return self._body.decode("utf-8", "replace")


def _is_cloudflare_challenge(resp) -> bool:
    """True when `resp` looks like a Cloudflare bot-detection challenge
    rather than a genuine response from claude.ai — a 403 whose body is the
    Cloudflare interstitial page, or a response carrying one of Cloudflare's
    own mitigation headers. Distinguishing this from a real 401 (expired
    session) or a real 403 (not an org admin) matters: telling someone stuck
    behind a challenge to "re-authenticate" is useless if the request never
    reached claude.ai, and telling an org-admin user their session merely
    expired hides the one fact they can actually act on.

    Still relevant with no browser in the picture: a plain HTTP request can be
    challenged too, and a fresh cookie is a genuine fix for that case.
    """
    if resp is None:
        return False
    headers = getattr(resp, "headers", None) or {}
    header_blob = " ".join(f"{k}:{v}" for k, v in headers.items()).lower()
    if any(marker in header_blob for marker in _CF_HEADER_MARKERS):
        return True
    if resp.status == 403:
        try:
            body = (resp.text() or "").lower()
        except Exception:
            body = ""
        if any(marker in body for marker in _CF_BODY_MARKERS):
            return True
    return False


def _looks_logged_out(url: str) -> bool:
    """A dead cookie gets answered with a redirect to the sign-in/logout page
    and a 200. Parsing that HTML as JSON and reporting "no invoices" would
    turn an expired session into a clean, empty audit — the exact failure this
    codebase keeps having to design against."""
    return any(marker in (url or "").lower() for marker in _LOGGED_OUT_PATHS)


def _fetch_listing(org: str, session: str, page: str = "", limit: int = 100) -> dict:
    """One authenticated GET against the invoice listing.

    Every failure below is a DIFFERENT thing the user has to do, so each one
    gets its own message and they are never collapsed:

      * Cloudflare challenge  -> the request never reached claude.ai; a fresh
                                 cookie is worth trying.
      * 401 / logged-out 200  -> the stored session expired; re-store it.
      * 403 (not challenged)  -> the account is not an org admin; no amount of
                                 re-authenticating will change that.
      * anything else         -> claude.ai returned something unexpected; say
                                 what, and do not pretend to know the cause.
    """
    url = LISTING.format(org=org, limit=limit, page=page)
    req = urllib.request.Request(url, headers={
        # The credential travels in a header, never in the URL — URLs end up
        # in logs, proxies, and error text.
        "Cookie": f"sessionKey={session}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })

    try:
        with _open(req) as raw:
            resp = _HttpResponse(getattr(raw, "status", 200), getattr(raw, "headers", None),
                                 raw.read(), raw.geturl() if hasattr(raw, "geturl") else url)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        resp = _HttpResponse(exc.code, getattr(exc, "headers", None), body,
                             getattr(exc, "url", url) or url)
    except urllib.error.URLError as exc:
        raise SourceUnavailable(_scrub(
            f"Could not reach claude.ai to list billing invoices: {exc.reason}. "
            f"This is a network problem, not an authentication one — the stored "
            f"session was not rejected, the request never completed.", session,
        )) from None
    except Exception as exc:
        raise SourceUnavailable(_scrub(
            f"Could not reach claude.ai to list billing invoices: "
            f"{type(exc).__name__}: {exc}", session,
        )) from None

    # Checked first: Cloudflare mitigations most often ride on a 403, and
    # reading that as "not an org admin" would send an actual org admin off to
    # request permissions they already have.
    if _is_cloudflare_challenge(resp):
        raise SourceUnavailable(
            f"Cloudflare challenged the request to claude.ai for organization "
            f"{org} instead of letting it through, so the invoice listing was "
            f"never reached. This is neither a stale session nor a permissions "
            f"problem — the request did not get to claude.ai at all. A freshly "
            f"copied cookie usually clears it: re-run "
            f"{SET_SESSION_CMD} and paste a new sessionKey value."
        )

    if resp.status == 401 or (resp.status == 200 and _looks_logged_out(resp.url)):
        raise SourceUnavailable(
            f"The stored claude.ai session has expired — claude.ai no longer "
            f"accepts it for organization {org}. Sessions expire periodically; "
            f"this is normal and expected. Store a fresh one with: "
            f"{SET_SESSION_CMD}"
        )

    if resp.status == 403:
        raise SourceUnavailable(
            f"claude.ai refused the billing invoice listing for organization "
            f"{org} (HTTP 403). The session itself was accepted — this account "
            f"is not an org admin there, and only an org admin can read billing "
            f"invoices, so signing in again will not change it. Ask an org "
            f"owner for admin access, or unset ANTHROPIC_ORG_UUID to run "
            f"without this source."
        )

    if resp.status != 200:
        raise SourceUnavailable(
            f"claude.ai returned HTTP {resp.status} for the billing invoice "
            f"listing of organization {org}. That is not an authentication or "
            f"permissions failure — it is an unexpected response, most likely "
            f"temporary. Re-run; if it persists, check status.anthropic.com."
        )

    try:
        return json.loads(resp.text() or "{}")
    except json.JSONDecodeError:
        raise SourceUnavailable(
            f"claude.ai returned a 200 that is not JSON for the billing invoice "
            f"listing of organization {org} — usually an HTML page served in "
            f"place of the API response. If it persists after storing a fresh "
            f"session ({SET_SESSION_CMD}), the endpoint has changed shape."
        ) from None


class AnthropicSource:
    MERCHANTS = ("anthropic", "anthropicpbc")
    # Set during fetch() to a human-readable reason whenever this source
    # returned LESS than it was asked for but did not fail outright: the page
    # guard fired with more pages pending, the cursor went missing, or an
    # invoice PDF could not be downloaded. None otherwise. run.py reads it via
    # getattr and prints "SOURCE ANTHROPIC: TRUNCATED (...)" — the same channel
    # GmailSource already uses. Without it, a partial search returns quietly
    # and every unmatched transaction reads as a genuine gap.
    truncated: str | None = None

    def parse_invoices(self, payload: dict) -> list[dict]:
        rows = []
        for inv in payload.get("invoices", []):
            if inv.get("status") != "paid" or not inv.get("invoice_pdf_url"):
                continue
            date = dt.datetime.fromtimestamp(inv["created_ts"], dt.UTC).date().isoformat()
            # invoice_pdf_url is unique per invoice (…/live_A/pdf vs …/live_B/pdf).
            # Fold a stable, deterministic slice of it into provenance so that
            # same-date, same-amount invoices — e.g. four $214.56 Anthropic
            # charges within six minutes — don't collide. Must be stable across
            # runs (never random/time-based): the per-upload idempotency key
            # derives from provenance, and a changing key would defeat Ramp's
            # duplicate collapsing.
            token = hashlib.sha1(inv["invoice_pdf_url"].encode()).hexdigest()[:8]
            rows.append({
                "amount_cents": int(inv["total"]),
                "date": date,
                "pdf_url": inv["invoice_pdf_url"],
                "provenance": f"anthropic:invoice {date} {inv['total']} {token}",
            })
        return rows

    def _listing(self, page: str = "") -> dict:
        org = os.environ.get("ANTHROPIC_ORG_UUID")
        if not org:
            raise SourceUnavailable(
                "ANTHROPIC_ORG_UUID is not set. Set it to your claude.ai "
                "organization UUID (Settings > Organization) before running "
                "the Anthropic source."
            )
        return _fetch_listing(org, _stored_session(), page)

    @staticmethod
    def _download(url: str) -> bytes:
        # No auth, deliberately: these are Stripe secret-token URLs that
        # resolve for anyone holding the link. The claude.ai session must
        # never be sent to a third-party host, so this stays a bare urlopen
        # with no headers of ours attached.
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        if not data.startswith(b"%PDF"):
            raise SourceUnavailable(f"Expected PDF from {url[:60]}…, got {data[:16]!r}")
        return data

    def fetch(self, since: str, until: str) -> list[Receipt]:
        self.truncated = None
        notes: list[str] = []

        rows: list[dict] = []
        page, payload = "", {}
        for _ in range(PAGE_GUARD):
            payload = self._listing(page)
            rows.extend(self.parse_invoices(payload))
            if not payload.get("has_more"):
                break
            next_page = payload.get("next_page") or ""
            # has_more with no usable cursor used to leave `page` at "" and
            # re-request the identical first page until the guard ran out —
            # up to 20 identical requests returning the same rows, making no
            # progress and saying nothing. Stop, and say so.
            if not next_page or next_page == page:
                notes.append(
                    f"the invoice listing reported more pages but returned no usable "
                    f"next_page cursor after {len(rows)} invoices — results are incomplete"
                )
                break
            page = next_page
        else:
            # Guard exhausted with more pages still pending. Keep what we have,
            # but this is a partial search, not a complete one.
            if payload.get("has_more"):
                notes.append(
                    f"hit the {PAGE_GUARD}-page cap, {len(rows)} invoices fetched, "
                    f"results incomplete — narrow the date range and re-run"
                )

        # Per-invoice download. One expired URL, non-PDF response, or network
        # blip used to abort the whole list comprehension and discard every
        # valid invoice already gathered — one stale row took the entire
        # Anthropic source down. Keep the good ones; report the losses.
        out: list[Receipt] = []
        failures: list[str] = []
        for r in rows:
            if not (since <= r["date"] <= until):
                continue
            try:
                pdf = self._download(r["pdf_url"])
            except Exception as exc:
                failures.append(
                    f"{r['date']} ${r['amount_cents'] / 100:,.2f} ({type(exc).__name__})"
                )
                continue
            out.append(Receipt(
                merchant="anthropic",
                amount_cents=r["amount_cents"],
                date=r["date"],
                pdf_bytes=pdf,
                provenance=r["provenance"],
            ))

        if failures:
            shown = ", ".join(failures[:5])
            more = f" (+{len(failures) - 5} more)" if len(failures) > 5 else ""
            notes.append(
                f"{len(failures)} invoice PDF(s) failed to download and were skipped: "
                f"{shown}{more}"
            )

        self.truncated = "; ".join(notes) or None
        return out


SOURCE = AnthropicSource()


def _write_session(value: str, path: Path) -> None:
    """Write the credential atomically at mode 0600.

    Same shape as the ledger's write: a temp file in the *destination
    directory* (os.replace is only atomic within one filesystem), permissions
    set on the file descriptor before a single byte of the secret is written,
    then an atomic rename. A half-written credential file would fail
    confusingly on the next run; a briefly world-readable one would be a leak.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".claude-receipts-session.")
    try:
        os.fchmod(fd, SESSION_MODE)
        with os.fdopen(fd, "w") as fh:
            fh.write(value + "\n")
        os.chmod(tmp, SESSION_MODE)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _set_session() -> int:
    """Prompt for a claude.ai sessionKey, validate it live, and store it 0600.

    Replaces the old `--login`, which opened a browser. Returns a process exit
    code. Nothing here ever prints the value it was given.

    RECEIPTS_LOGIN_TEST_NOOP short-circuits before the prompt or any network
    call. Tests that need to prove the dispatch path — import succeeds,
    argument parsing reaches this call — set it to prove that without
    prompting for a credential, which would not be hermetic. (The env var
    keeps its old name: it is referenced by the existing invocation tests and
    means the same thing — "dispatch reached the auth entry point".)
    """
    if os.environ.get("RECEIPTS_LOGIN_TEST_NOOP"):
        print("RECEIPTS_LOGIN_TEST_NOOP set — dispatch reached _set_session(), "
              "skipping the credential prompt")
        return 0

    org = os.environ.get("ANTHROPIC_ORG_UUID")
    if not org:
        # Refuse before prompting. The whole point of this command is that it
        # never stores an unverified credential, and validation is a call to
        # /api/stripe/{org}/invoices — with no org UUID there is nothing to
        # validate against. Asking for a secret we cannot check would store a
        # value the user only discovers is wrong on some later run.
        print("ERROR: ANTHROPIC_ORG_UUID is not set, so a pasted session cannot be "
              "validated — and this command never stores an unverified credential. "
              "Set it to your claude.ai organization UUID (Settings > Organization) "
              "and re-run:\n"
              "  export ANTHROPIC_ORG_UUID=<your-claude.ai-org-uuid>", file=sys.stderr)
        return 2

    path = _session_path()
    print(COOKIE_INSTRUCTIONS)

    # getpass, never input(): the value is not echoed to the terminal, does
    # not survive in a scrollback buffer, and never lands in shell history.
    value = (getpass.getpass("Paste the sessionKey value (hidden): ") or "").strip()
    if not value:
        print("ERROR: nothing was entered — no session was stored, and any "
              "previously stored session is untouched.", file=sys.stderr)
        return 2

    print("Validating against claude.ai…")
    try:
        payload = _fetch_listing(org, value, limit=1)
    except SourceUnavailable as exc:
        # `exc` is built by _fetch_listing, which never interpolates the
        # session — _scrub is the belt-and-braces pass for anything that
        # reached it from a lower layer.
        print(f"ERROR: that session was not accepted, so nothing was stored.\n"
              f"{_scrub(exc, value)}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: could not validate that session, so nothing was stored: "
              f"{_scrub(f'{type(exc).__name__}: {exc}', value)}", file=sys.stderr)
        return 2

    try:
        _write_session(value, path)
    except OSError as exc:
        print(f"ERROR: the session was valid but could not be written to {path}: "
              f"{_scrub(f'{type(exc).__name__}: {exc}', value)}", file=sys.stderr)
        return 2

    count = len(payload.get("invoices") or [])
    print(f"Stored a validated claude.ai session at {path} (mode 0600, readable only "
          f"by you).\nclaude.ai accepted it: the billing listing for organization "
          f"{org} responded with {count} invoice(s).\n"
          f"Do not share or commit this file. Sessions expire periodically — when "
          f"this one does, /receipts will say so and you re-run {SET_SESSION_CMD}")
    return 0


# `--login` used to open a browser and is still in shipped docs, in error
# strings, and in muscle memory. Keep the name working, pointed at the same
# function, and explain the change rather than failing on an unknown flag.
_login = _set_session


if __name__ == "__main__":
    if "--login" in sys.argv:
        print("NOTE: --login is now --set-session. There is no browser step any "
              "more — the Anthropic source authenticates with a stored session "
              "cookie. Running --set-session for you.", file=sys.stderr)
        raise SystemExit(_set_session())
    if "--set-session" in sys.argv:
        raise SystemExit(_set_session())
    # Run with nothing recognisable: say what this file can do rather than
    # exiting 0 in silence, which reads as "it worked".
    print(f"This module is a receipt source, not a command. The one thing it "
          f"can do on its own is store a claude.ai session:\n"
          f"  {SET_SESSION_CMD}", file=sys.stderr)
    raise SystemExit(2)
