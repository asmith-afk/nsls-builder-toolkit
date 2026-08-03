#!/usr/bin/env python3.12
"""Neon Tech billing source.

Neon sends NO invoice email. The mailbox was searched unrestricted on
2026-08-01: Neon sends product updates and usage recaps only, never a
receipt or an invoice. The billing portal is therefore the only source, and
Neon is the largest unautomated vendor in the queue — 3 outstanding charges
totalling $1,293.73, billed monthly and growing ($317.61 -> $425.36 ->
$550.76), roughly a $6.6k/yr run rate.

THE ENDPOINT (verified live 2026-08-01)
---------------------------------------
    GET https://console.neon.tech/api/v2/organizations/{org_id}/billing/invoices
    Authorization: Bearer $NEON_API_KEY

HTTP 200 with a plain API key — no cookies, no browser, no Cloudflare in the
way. There is no session to expire here, which is the one respect in which
this source is simpler than the Anthropic one.

`/api/v2/billing/invoices?org_id=…` is the RETIRED form and answers HTTP 400
`{"message":"method is deprecated"}`. If that ever comes back, it is a
wrong-endpoint signal — a bug in this file — not a credential problem, and
`_fetch_invoices` says exactly that rather than sending someone off to
re-issue an API key that was fine.

THREE SHAPE FACTS THAT DIFFER FROM ANTHROPIC'S SOURCE
-----------------------------------------------------
* `total` is a decimal STRING ("550.76"), not integer cents. It goes through
  Decimal, never float: `int(float("1.15") * 100)` is 114, not 115, and this
  value is uploaded against a real financial record and matched on exact
  cents. See `_to_cents`.
* The charge date is `paid_at`, falling back to `issued_at` when absent —
  the card charge follows payment, which is what Ramp's transaction date
  reflects. (Both were same-day in every observed invoice, so this only
  matters at a midnight boundary — which is exactly where a one-day error
  would push a receipt out of the match window.)
* `currency` is carried per invoice and is honoured: only USD invoices become
  receipts. Matching compares merchant, integer cents and date and never sees
  currency, so a paid non-USD invoice with the same number on it would attach
  to an unrelated USD Ramp charge — a wrong document on a financial record.
  Exclusions are counted into `truncated`, never dropped quietly. (Carrying
  currency through Receipt and match.py is the larger correct fix; this is
  the narrow one.)
* `pdf_url` needs no authentication: it is an assets.withorb.com link
  carrying its own token (Neon bills through Orb, not Stripe). Verified by
  opening it with no Neon cookie present. The API key must never be sent
  there — `_download` is a bare urlopen with no headers of ours attached.

The response is NOT paginated: all 16 invoices came back in one call, with no
cursor and no `has_more`. So there is no pagination loop here — inventing one
would be guessing at an API that doesn't work that way. But a silently
partial list is this codebase's recurring bug, so `fetch` watches for any
sign the shape changed (a cursor-ish field, a suspiciously round row count)
and sets `truncated` rather than returning a short list quietly.

THE API KEY IS A CREDENTIAL
---------------------------
It is long-lived — longer than a claude.ai session, which makes leaking it
strictly worse. Therefore, in this module:

* It is read from NEON_API_KEY, else from a 0600 file in the user's home
  (never the repo tree, so it cannot be committed).
* A file readable by group or others is REFUSED, not used.
* Its value is never printed, logged, echoed, or interpolated into any error
  message, report line, ledger entry, or exception text. `_scrub` is a
  defensive second line for text that came from somewhere else (an OS error,
  a urllib exception, a server error body that echoed the token back).
* The authenticated request does not follow REDIRECTS. urllib re-sends the
  Authorization header to the redirect target, including across origins
  (CPython #77842), so one redirect off console.neon.tech would hand this key
  to another host. See `_RefuseRedirect`.
* The `--set-neon-key` prompt refuses to read anything at all when the
  terminal cannot hide it — getpass falls back to an ECHOING read when it
  finds no echo-free TTY, which would print the key into the session's
  scrollback and into any log capturing it. See `base.prompt_for_secret`.

This skill ships org-wide: every builder runs it with their own key against
their own Neon organization, so each of those is a promise made to someone
who never read this file.

NEON_ORG_ID must be set in the environment — this module ships in an
org-wide toolkit and must never default to one organisation's billing data.
"""

import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

try:
    from .base import (Receipt, SecretPromptUnavailable, SourceUnavailable,
                       prompt_for_secret, scrub_secret,
                       secret_file_is_unsafe, secret_file_mode, write_secret_file)
except ImportError:
    # Running this file directly (`python3.12 sources/neon.py --set-neon-key`)
    # gives it no parent package, so the relative import above fails before
    # this module's own `if __name__ == "__main__":` block ever runs — and
    # that command is exactly what the SourceUnavailable messages below tell
    # a user to run. Same fix as sources/anthropic.py: put the `scripts/`
    # directory on sys.path so `sources` is importable as a real top-level
    # package, then import the same module absolutely.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sources.base import (Receipt, SecretPromptUnavailable,
                              SourceUnavailable, prompt_for_secret,
                              scrub_secret, secret_file_is_unsafe,
                              secret_file_mode, write_secret_file)

LISTING = "https://console.neon.tech/api/v2/organizations/{org}/billing/invoices"

# Where the key comes from. The environment wins, so a CI job or a
# password-manager shim can supply it without a file existing at all.
KEY_ENV = "NEON_API_KEY"
# Deliberately stored unexpanded and expanded at use time: tests point this at
# a temp path, and it must land in the user's home — never inside the repo,
# where it could be committed.
KEY_FILE = "~/.claude-receipts-neon-key"
ORG_ENV = "NEON_ORG_ID"

# Row counts that look like a page size rather than a real total. Neon
# returns everything in one call today; if that ever changes, landing exactly
# on one of these is the cheapest available signal that we are looking at
# page one of several.
_SUSPICIOUS_COUNTS = (50, 100, 200, 250, 500, 1000)
# Fields that would indicate more results exist. None of these appear in the
# response today — they are watched for, not relied on.
_MORE_RESULTS_FIELDS = ("has_more", "has_next", "next_page", "next_cursor",
                        "cursor", "next", "pagination")

# Resolved at runtime from this file's own location rather than hardcoded, so
# the recovery command works on whatever machine and checkout this happens to
# run on, from whatever directory the user is standing in. (Same bug class
# that bit sources/anthropic.py three times — a documented fix that only
# resolved from the repo root.)
_RUN_PY = Path(__file__).resolve().parent.parent / "run.py"
SET_KEY_CMD = f"python3.12 {_RUN_PY} --set-neon-key"

ORG_HINT = (
    f"{ORG_ENV} is not set, so the Neon billing source does not know which "
    f"organization to read. Find it in the Neon Console URL — it is the "
    f"`org-…` segment (console.neon.tech/app/projects?org_id=org-…). Then:\n"
    f"  export {ORG_ENV}=org-your-organization-id"
)

KEY_INSTRUCTIONS = f"""\
Storing a Neon API key for the Neon billing source.

Where to create it:
  1. Open the Neon Console (https://console.neon.tech) and sign in.
  2. Go to Organization settings -> API keys.
  3. Create an ORGANIZATION API key (a personal key cannot read the
     organization's billing invoices).
  4. Copy the key — Neon shows it once — and paste it at the prompt below.

The paste is hidden: it is not echoed to the terminal and never enters your
shell history. It is stored at {KEY_FILE} with mode 0600 (only you can read
it) and validated against Neon before it is written.
"""


def _key_path() -> Path:
    """The stored-key file, expanded at call time.

    Expanding at import time would freeze whatever HOME happened to be set to
    then; this also lets the tests redirect KEY_FILE into a temp directory, so
    no test can read or clobber a real credential.
    """
    return Path(os.path.expanduser(KEY_FILE))


def _scrub(text, secret: str | None) -> str:
    """Defensive redaction — see base.scrub_secret."""
    return scrub_secret(text, secret)


def _stored_key() -> str:
    """The Neon API key, from the environment or the stored file.

    Raises SourceUnavailable — never returns a partial or unsafe value, and
    never puts the value itself in the failure message.
    """
    from_env = (os.environ.get(KEY_ENV) or "").strip()
    if from_env:
        return from_env

    path = _key_path()
    if not path.exists():
        raise SourceUnavailable(
            f"No Neon API key is stored, so the Neon billing source cannot "
            f"authenticate. Store one with: {SET_KEY_CMD} "
            f"(or set {KEY_ENV} in the environment)."
        )

    try:
        mode = secret_file_mode(path)
    except OSError as exc:
        raise SourceUnavailable(
            f"Could not read the stored Neon API key at {path}: "
            f"{type(exc).__name__}: {exc}"
        ) from None

    if secret_file_is_unsafe(mode):
        raise SourceUnavailable(
            f"Refusing to use the stored Neon API key at {path}: its mode is "
            f"{mode:04o}, which lets other accounts on this machine read it. "
            f"That file is a live credential — anyone holding it can read your "
            f"organization's Neon billing data. Fix it with `chmod 600 {path}`, "
            f"or re-store the key with: {SET_KEY_CMD}"
        )

    try:
        value = path.read_text().strip()
    except OSError as exc:
        raise SourceUnavailable(
            f"Could not read the stored Neon API key at {path}: "
            f"{type(exc).__name__}: {exc}"
        ) from None

    if not value:
        raise SourceUnavailable(
            f"The stored Neon API key at {path} is empty. Store a real one "
            f"with: {SET_KEY_CMD}"
        )
    return value


def _stored_org() -> str:
    org = (os.environ.get(ORG_ENV) or "").strip()
    if not org:
        raise SourceUnavailable(ORG_HINT)
    return org


class RedirectRefused(Exception):
    """A redirect was answered on the authenticated request and not followed.

    Carries the target so the caller can name it: a real vendor change should
    be diagnosable in one line, not a mystery.
    """

    def __init__(self, code: int, target: str):
        self.code = code
        self.target = target
        super().__init__(f"HTTP {code} redirect to {target}")


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects on the authenticated request. Ever.

    urllib does NOT strip the Authorization header when it follows a redirect
    to a different scheme/host (CPython #77842) — it rebuilds the request with
    the original headers and sends them to the new origin. So one redirect off
    console.neon.tech, from any cause (a DNS takeover, a misconfiguration, a
    vendor's own change), hands the builder's long-lived Neon API key to
    whatever host the Location header names. This module's docstring promises
    that key never reaches a third party; this class is what makes that true
    rather than merely intended.

    Refusing outright, rather than stripping the header on cross-origin hops:
    this endpoint has never redirected, so there is no working behaviour to
    preserve, and "which redirects are safe enough to follow" is exactly the
    judgement call that loses a credential. A redirect here means something
    changed, and the right response to that is to stop and say so.

    sources/anthropic.py answers the same hazard differently — it strips the
    Cookie header and follows — because claude.ai's 302 to /login is how an
    expired session is detected there, so refusing would break a working
    behaviour. Both policies and the shared origin rule are documented
    together under "Redirect policy" in sources/base.py.

    Overriding `redirect_request` covers 301/302/303/307/308 in one place —
    urllib routes all of them through http_error_302 — and it runs BEFORE any
    new request is built, so nothing is ever sent to the target.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedirectRefused(code, newurl)


def _opener() -> urllib.request.OpenerDirector:
    """The opener used for the AUTHENTICATED request — no redirect following.

    Built per call rather than cached: it is a handful of small objects, and a
    module-level singleton is one more piece of state to reason about in a
    module whose whole job is not leaking a credential.
    """
    return urllib.request.build_opener(_RefuseRedirect)


def _open(req, timeout: int = 60):
    """The single seam where this module touches the network.

    Isolated in one small function so the tests can replace it and still
    exercise the real Request construction — the URL, the headers, the bearer
    token — rather than a mock of the code under test.

    Not `urllib.request.urlopen`: that uses the default opener, which follows
    redirects and forwards the Authorization header when it does. See
    _RefuseRedirect.
    """
    return _opener().open(req, timeout=timeout)


class _HttpResponse:
    """A uniform view of whatever came back — a urllib response or the
    HTTPError raised in its place."""

    def __init__(self, status, body: bytes, url: str = ""):
        self.status = status
        self._body = body or b""
        self.url = url

    def text(self) -> str:
        return self._body.decode("utf-8", "replace")


def _fetch_invoices(org: str, key: str) -> dict:
    """One authenticated GET against the org-scoped invoice listing.

    Every failure below is a DIFFERENT thing to do about it, so each one gets
    its own message and they are never collapsed:

      * 401 / 403   -> the key is invalid or is not an ORGANIZATION key. No
                       amount of setting NEON_ORG_ID fixes that.
      * 400 with
        "method is
        deprecated" -> we called the retired endpoint form. That is a bug in
                       THIS FILE. Saying "your credentials failed" would send
                       someone to re-issue a key that was never the problem.
      * transport   -> the request never completed; nothing was rejected.
      * anything
        else        -> say what came back, and do not pretend to know why.
    """
    url = LISTING.format(org=org)
    req = urllib.request.Request(url, headers={
        # The credential travels in a header, never in the URL — URLs end up
        # in logs, proxies, and error text.
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    })

    try:
        with _open(req) as raw:
            resp = _HttpResponse(getattr(raw, "status", 200), raw.read(),
                                 raw.geturl() if hasattr(raw, "geturl") else url)
    except RedirectRefused as exc:
        # Deliberately first: this is the one failure here that is a
        # credential-safety stop rather than a transport or auth problem, and
        # the generic handlers below would report it as "network failure",
        # which is both wrong and unactionable.
        raise SourceUnavailable(_scrub(
            f"console.neon.tech answered HTTP {exc.code} and tried to redirect "
            f"the authenticated billing request to {exc.target}. The request "
            f"was NOT followed and the API key was not sent there: urllib "
            f"forwards the Authorization header across a redirect, so "
            f"following one would hand a long-lived Neon credential to "
            f"whatever host that is. This endpoint has never redirected. If "
            f"Neon has genuinely moved it, sources/neon.py needs updating to "
            f"the new URL — your API key and {ORG_ENV} are not at fault.",
            key,
        )) from None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        resp = _HttpResponse(exc.code, body, getattr(exc, "url", url) or url)
    except urllib.error.URLError as exc:
        raise SourceUnavailable(_scrub(
            f"Could not reach console.neon.tech to list billing invoices: "
            f"{exc.reason}. This is a network problem, not an authentication "
            f"one — the stored API key was not rejected, the request never "
            f"completed.", key,
        )) from None
    except Exception as exc:
        raise SourceUnavailable(_scrub(
            f"Could not reach console.neon.tech to list billing invoices "
            f"(network or transport failure): {type(exc).__name__}: {exc}", key,
        )) from None

    body_text = resp.text()

    # Checked before the generic 400 branch: this specific 400 is the one
    # failure here that is OUR bug, and reading it as a bad request would
    # leave the real cause unnamed.
    if resp.status == 400 and "deprecated" in body_text.lower():
        raise SourceUnavailable(_scrub(
            f"Neon answered HTTP 400 'method is deprecated' for the billing "
            f"invoice listing. That is a wrong-endpoint signal, not a "
            f"credential problem: the retired form is "
            f"/api/v2/billing/invoices?org_id=…, and the current one is the "
            f"org-scoped path /api/v2/organizations/<org>/billing/invoices. "
            f"Your API key and {ORG_ENV} are not at fault — this is a bug in "
            f"sources/neon.py and needs a code change, not a new credential.",
            key,
        ))

    if resp.status in (401, 403):
        raise SourceUnavailable(_scrub(
            f"Neon refused the billing invoice listing for organization {org} "
            f"(HTTP {resp.status}). The stored API key is either invalid or "
            f"lacks billing access to that organization. Re-issue it as an "
            f"ORGANIZATION API key (Neon Console -> Organization settings -> "
            f"API keys) — a personal key cannot read organization billing — "
            f"and store the new one with: {SET_KEY_CMD}", key,
        ))

    if resp.status != 200:
        raise SourceUnavailable(_scrub(
            f"Neon returned HTTP {resp.status} for the billing invoice listing "
            f"of organization {org}. That is neither an authentication failure "
            f"nor a wrong endpoint — it is an unexpected response, most likely "
            f"temporary. Re-run; if it persists, check neonstatus.com.", key,
        ))

    try:
        payload = json.loads(body_text or "{}")
    except json.JSONDecodeError:
        raise SourceUnavailable(_scrub(
            f"Neon returned a 200 that is not JSON for the billing invoice "
            f"listing of organization {org} — usually an HTML page served in "
            f"place of the API response. If it persists, the endpoint has "
            f"changed shape.", key,
        )) from None

    # Valid JSON is not the same thing as the shape every caller assumes.
    # `[]`, `null` and `"…"` all parse, and every caller then does
    # payload.get(...) and gets an AttributeError instead of this module's one
    # controlled failure type — which run.py reports as a crash rather than a
    # skipped source. The declared return type is dict; enforce it here, at
    # the boundary, so no caller has to.
    if not isinstance(payload, dict):
        raise SourceUnavailable(_scrub(
            f"Neon returned a 200 whose JSON is a {type(payload).__name__}, not "
            f"an object, for the billing invoice listing of organization {org}. "
            f"The response has changed shape — this source expects "
            f'{{"invoices": [...]}}. Nothing was read from it.', key,
        ))
    return payload


def _to_cents(total) -> int:
    """A decimal-string amount ("550.76") as exact integer cents (55076).

    Decimal, never float. `float("1.15") * 100` is 114.99999999999999, so
    int() of it is 114 — a cent low, on a value that is uploaded against a
    real financial record and matched on exact cents. Raises InvalidOperation
    (or ValueError/TypeError) on anything that is not a number; the caller
    drops the row and the drop is counted, never swallowed.
    """
    text = str(total).strip().replace(",", "").replace("$", "")
    if not text:
        raise InvalidOperation("empty total")
    cents = (Decimal(text) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


BILLING_CURRENCY = "USD"


def _is_billing_currency(inv: dict) -> bool:
    """Is this invoice denominated in the currency Ramp charges in?

    Matching compares merchant, integer cents and date — never currency (that
    would mean carrying it through Receipt and match.py). So a paid €550.76
    invoice and a $550.76 Ramp charge are indistinguishable to the matcher,
    and the wrong document gets attached to a real financial record. Cheapest
    correct guard: only USD invoices become receipts at all.

    A missing or blank `currency` is refused too. Every invoice observed live
    carried it, so its absence is a shape change — and "it was probably
    dollars" is a guess about a financial record. fetch() counts every refusal
    into `truncated`, so this is loud, not silent.
    """
    return str(inv.get("currency") or "").strip().upper() == BILLING_CURRENCY


def _invoice_rows(payload: dict) -> list:
    """The `invoices` array, or [] if it is missing or the wrong type.

    fetch() checks the same thing and announces it; this keeps parse_invoices
    pure and crash-free on any shape.
    """
    rows = payload.get("invoices")
    return rows if isinstance(rows, list) else []


def _to_date(stamp: str) -> str:
    """An ISO8601 UTC timestamp ("2026-08-01T14:22:23Z") as an ISO date."""
    text = str(stamp).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = dt.datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).date().isoformat()


class NeonSource:
    MERCHANTS = ("neontech",)
    # Set during fetch() to a human-readable reason whenever this source
    # returned LESS than it was asked for but did not fail outright: the
    # response looked paginated, a paid invoice would not parse, or an invoice
    # PDF could not be downloaded. None otherwise. run.py reads it via getattr
    # and prints "SOURCE NEON: TRUNCATED (...)". Without it, a partial search
    # returns quietly and every unmatched transaction reads as a genuine gap.
    truncated: str | None = None

    def parse_invoices(self, payload: dict) -> list[dict]:
        """Pure. Payload shape in, receipt-shaped dicts out.

        Drops anything that is not a completed card charge with a fetchable
        document: unpaid invoices (no charge exists yet), invoices with no
        pdf_url (nothing to attach), and rows whose total or dates will not
        parse. fetch() compares this list against the paid rows in the payload
        and announces the difference — a paid invoice disappearing silently is
        exactly the failure mode this codebase keeps having to design against.
        """
        rows: list[dict] = []
        for inv in _invoice_rows(payload):
            if not isinstance(inv, dict):
                continue
            if inv.get("status") != "paid":
                continue
            # Before anything else about the money: an invoice in another
            # currency cannot be compared to a USD charge, and the matcher
            # never sees currency. fetch() counts these and announces them.
            if not _is_billing_currency(inv):
                continue
            pdf_url = inv.get("pdf_url")
            if not pdf_url:
                continue

            # paid_at first: the card charge follows payment, and Ramp's
            # transaction date reflects the charge.
            stamp = inv.get("paid_at") or inv.get("issued_at")
            if not stamp:
                continue
            try:
                date = _to_date(stamp)
                amount_cents = _to_cents(inv.get("total"))
            except (InvalidOperation, ValueError, TypeError):
                continue

            # invoice_number is unique and stable per invoice
            # ("NLPHVL-00016"), so it is the natural provenance key — no
            # hashing of a PDF URL needed, unlike Anthropic. Provenance must
            # be stable across runs (the per-upload idempotency key derives
            # from it, and a changing key would defeat Ramp's duplicate
            # collapsing) and unique per invoice (match.py dedupes on it). If
            # a row ever arrives without one, fall back to the equally stable
            # invoice_id, then to a hash of pdf_url — anything but a shared
            # blank, which would make two different invoices compare equal and
            # silently drop one.
            #
            # The last fallback is a property of the INVOICE, never its
            # position in the list. A row index is stable only until something
            # earlier is inserted or reordered, and then the same invoice gets
            # a new provenance, a new idempotency key, and is uploaded again
            # instead of collapsing as a duplicate. pdf_url is unique per
            # invoice and carries its own token — same reasoning, and the same
            # sha1-prefix construction, as sources/anthropic.py.
            key = (str(inv.get("invoice_number") or "").strip()
                   or str(inv.get("invoice_id") or "").strip()
                   or "pdf-" + hashlib.sha1(str(pdf_url).encode()).hexdigest()[:8])
            rows.append({
                "amount_cents": amount_cents,
                "date": date,
                "pdf_url": pdf_url,
                "provenance": f"neon:invoice {key}",
            })
        return rows

    def _invoices(self) -> dict:
        # Order matters: the org id is checked before the key is read, so a
        # user with neither gets the cheaper, more specific instruction first,
        # and no request is ever built without both.
        org = _stored_org()
        return _fetch_invoices(org, _stored_key())

    @staticmethod
    def _download(url: str) -> bytes:
        # No auth, deliberately: assets.withorb.com PDF links carry their own
        # token and resolve for anyone holding the link (verified 2026-08-01).
        # The Neon API key must never be sent to a third-party host, so this
        # stays a bare urlopen with no headers of ours attached.
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        if not data.startswith(b"%PDF"):
            raise SourceUnavailable(f"Expected PDF from {url[:60]}…, got {data[:16]!r}")
        return data

    def fetch(self, since: str, until: str) -> list[Receipt]:
        self.truncated = None
        notes: list[str] = []

        payload = self._invoices()
        rows = self.parse_invoices(payload)

        # `invoices` missing, or present and not a list. Every item is then
        # skipped, `lost` stays zero, no pagination hint fires, and the source
        # returns [] with truncated unset — a degraded run that reads as a
        # clean one, and real Neon charges reported as genuinely receipt-less.
        # That is this codebase's recurring failure mode, so it is named here
        # rather than inferred from an empty result.
        listing = payload.get("invoices")
        if isinstance(listing, list):
            raw = listing
        else:
            raw = []
            notes.append(
                f"the invoice listing had no usable `invoices` array — the "
                f"response carried {type(listing).__name__} where a list was "
                f"expected, so NOTHING was searched and no absence below can "
                f"be trusted; the endpoint has changed shape and "
                f"sources/neon.py needs updating"
            )

        # A paid invoice that did not survive parsing is a receipt we should
        # have had and don't. Draft/unpaid rows are correctly dropped and are
        # not counted here.
        paid = [i for i in raw if isinstance(i, dict) and i.get("status") == "paid"]

        # Excluded on purpose, and for a different reason than "unreadable" —
        # so counted and reported separately. Rolling these into the count
        # below would send someone looking for a parsing bug that isn't there.
        foreign = [i for i in paid if not _is_billing_currency(i)]
        if foreign:
            seen = sorted({str(i.get("currency") or "none stated").strip()
                           for i in foreign})
            notes.append(
                f"{len(foreign)} paid invoice(s) are not in {BILLING_CURRENCY} "
                f"({', '.join(seen)}) and were excluded — matching compares "
                f"amounts as plain cents, so a non-{BILLING_CURRENCY} invoice "
                f"could be attached to an unrelated {BILLING_CURRENCY} charge. "
                f"Attach those manually in Ramp"
            )

        lost = len(paid) - len(foreign) - len(rows)
        if lost > 0:
            notes.append(
                f"{lost} paid invoice(s) could not be read from the listing "
                f"(missing pdf_url, or an unparseable total or date) and were "
                f"skipped — results are incomplete"
            )

        # The response is not paginated today and this module deliberately
        # does not invent a cursor loop. But if the shape ever changes, a
        # quietly partial list must not read as a complete one.
        hints = [f for f in _MORE_RESULTS_FIELDS if payload.get(f)]
        if hints:
            notes.append(
                f"the invoice listing carried {', '.join(sorted(hints))}, which "
                f"suggests more results than the {len(raw)} returned — this "
                f"endpoint was not paginated when this source was written, so "
                f"results may be incomplete and sources/neon.py needs updating"
            )
        elif len(raw) in _SUSPICIOUS_COUNTS:
            notes.append(
                f"the invoice listing returned exactly {len(raw)} invoices, which "
                f"looks like a page size rather than a total — results may be "
                f"incomplete; narrow the date range and check for a cursor field"
            )

        out: list[Receipt] = []
        failures: list[str] = []
        for r in rows:
            if not (since <= r["date"] <= until):
                continue
            try:
                pdf = self._download(r["pdf_url"])
            except Exception as exc:
                # One expired URL or network blip must not discard every valid
                # invoice already gathered. Keep the good ones; report the loss.
                failures.append(
                    f"{r['date']} ${r['amount_cents'] / 100:,.2f} ({type(exc).__name__})"
                )
                continue
            out.append(Receipt(
                merchant="neontech",
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


SOURCE = NeonSource()


def _write_key(value: str, path: Path) -> None:
    """Write the credential atomically at mode 0600 — see
    base.write_secret_file."""
    write_secret_file(value, path, prefix=".claude-receipts-neon-key.")


def _set_neon_key() -> int:
    """Prompt for a Neon API key, validate it live, and store it 0600.

    Returns a process exit code. Nothing here ever prints the value it was
    given.

    RECEIPTS_LOGIN_TEST_NOOP short-circuits before the prompt or any network
    call — the same marker sources/anthropic.py uses, meaning "dispatch
    reached the auth entry point". Tests that need to prove the dispatch path
    set it, because prompting for a credential would not be hermetic.
    """
    if os.environ.get("RECEIPTS_LOGIN_TEST_NOOP"):
        print("RECEIPTS_LOGIN_TEST_NOOP set — dispatch reached _set_neon_key(), "
              "skipping the credential prompt")
        return 0

    org = (os.environ.get(ORG_ENV) or "").strip()
    if not org:
        # Refuse before prompting. This command never stores an unverified
        # credential, and validation is a call to the org-scoped endpoint —
        # with no org id there is nothing to validate against, and asking for
        # a secret we cannot check would store a value the user only discovers
        # is wrong on some later run.
        print(f"ERROR: a pasted key cannot be validated, and this command never "
              f"stores an unverified credential.\n{ORG_HINT}", file=sys.stderr)
        return 2

    path = _key_path()
    print(KEY_INSTRUCTIONS)

    # getpass, never input(): the value is not echoed to the terminal, does
    # not survive in a scrollback buffer, and never lands in shell history.
    # And getpass only if it can actually hide the value — see
    # base.prompt_for_secret, which refuses rather than accepting an echoed
    # paste in a session with no echo-free terminal.
    try:
        value = prompt_for_secret("Paste the Neon API key (hidden): ",
                                  label="Neon API key", env_var=KEY_ENV,
                                  command=SET_KEY_CMD)
    except SecretPromptUnavailable as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not value:
        print("ERROR: nothing was entered — no key was stored, and any "
              "previously stored key is untouched.", file=sys.stderr)
        return 2

    print("Validating against console.neon.tech…")
    try:
        payload = _fetch_invoices(org, value)
    except SourceUnavailable as exc:
        # `exc` is built by _fetch_invoices, which never interpolates the key
        # — _scrub is the belt-and-braces pass for anything that reached it
        # from a lower layer (including a server error body echoing it back).
        print(f"ERROR: that API key was not accepted, so nothing was stored.\n"
              f"{_scrub(exc, value)}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: could not validate that API key, so nothing was stored: "
              f"{_scrub(f'{type(exc).__name__}: {exc}', value)}", file=sys.stderr)
        return 2

    # Everything that can still reject this key happens BEFORE the write. The
    # ordering is the point: _write_key replaces whatever is already stored,
    # so any read of the response that could fail has to fail first, or a
    # validation that never finished leaves a working credential overwritten
    # by an unverified one. (_fetch_invoices guarantees a mapping, which is
    # what makes this line safe — this is the second lock on the same door.)
    invoices = payload.get("invoices")
    count = len(invoices) if isinstance(invoices, list) else 0

    try:
        _write_key(value, path)
    except OSError as exc:
        print(f"ERROR: the API key was valid but could not be written to {path}: "
              f"{_scrub(f'{type(exc).__name__}: {exc}', value)}", file=sys.stderr)
        return 2

    print(f"Stored a validated Neon API key at {path} (mode 0600, readable only "
          f"by you).\nNeon accepted it: the billing listing for organization "
          f"{org} responded with {count} invoice(s).\n"
          f"Do not share or commit this file. If the key is ever revoked or "
          f"rotated, /receipts will say so and you re-run {SET_KEY_CMD}")
    return 0


if __name__ == "__main__":
    if "--set-neon-key" in sys.argv:
        raise SystemExit(_set_neon_key())
    # Run with nothing recognisable: say what this file can do rather than
    # exiting 0 in silence, which reads as "it worked".
    print(f"This module is a receipt source, not a command. The one thing it "
          f"can do on its own is store a Neon API key:\n"
          f"  {SET_KEY_CMD}", file=sys.stderr)
    raise SystemExit(2)
