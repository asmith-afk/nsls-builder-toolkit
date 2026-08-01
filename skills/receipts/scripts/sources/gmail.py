#!/usr/bin/env python3.12
"""Gmail receipt source — reads receipt mail via the `gws` CLI.

MERCHANTS is empty, meaning "candidate for any merchant". Gmail is tried after
merchant-specific portal sources. Covers Neon Tech, Supabase, Zoom, Asana,
Groq, OpenAI, Hex, Kie, Mysecond — the non-Anthropic gaps.

Three `gws` calls per receipt PDF (verified live 2026-08-01):
  1. gmail users messages list        -> {id, threadId} only
  2. gmail users messages get         -> headers, snippet, internalDate, MIME tree
  3. gmail users messages attachments get -> base64url PDF bytes

Four deviations from a naive subject/snippet transcription, all measured
against real mail rather than assumed:

* Amount extraction reads the decoded text/plain body, not just the Subject
  and (truncated ~200-char) snippet. Verified against the canonical Anthropic
  reference message (id 19f94f2f9efe8c87): its subject is
  "Your receipt from Anthropic, PBC #2422-8527-1659" and its snippet is the
  same string padded with hair-spaces — neither contains a dollar figure.
  The amount ($99.91) only appears in the decoded text/plain part. Without
  this, the source would extract zero amounts, including from its own
  reference example.
* Merchant resolution prefers the sender's email domain (second-level label)
  over the display name, plus a small alias map for the cases that still
  don't line up with Ramp's `merchant_name`. Measured live 2026-08-01:
    - "Anthropic, PBC" <invoice+statements@mail.anthropic.com> -> domain
      label "anthropic" already equals Ramp's "Anthropic" -> "anthropic".
    - "Zoom Communications, Inc." <billing@zoom.us> -> domain label "zoom"
      already equals Ramp's "Zoom" -> "zoom".
    - "Asana" <billing@email1.asana.com> -> domain label "asana" already
      equals Ramp's "Asana" -> "asana".
    - Neon's sender domain is "neon.tech" -> domain label "neon", but Ramp's
      merchant_name is "Neon Tech" -> normalize_merchant gives "neontech".
      "neon" != "neontech" — genuinely does not line up on any generic rule,
      hence the explicit alias entry below.
  A mismatch is always safe: the receipt just doesn't bind and the
  transaction stays UNFOUND (see match.py). This never produces a wrong
  binding, so the alias map is intentionally small — add entries only when
  a real, measured gap shows up, not preemptively.
* `list` follows `nextPageToken` to the end instead of reading only the
  first 100 results. Measured live 2026-08-01: the query below matched 516
  messages over a 2-month window (subject:receipt/invoice/payment are
  common words in ordinary NSLS mail, not just vendor receipts), and a real,
  live vendor receipt matching an outstanding transaction only appeared on
  page 4. Stopping at page 1 — the brief's original call, and a completely
  reasonable-looking one — would silently have dropped it. The pagination
  loop is still capped (PAGE_GUARD, currently 50 pages / 5,000 messages) as
  a sane upper bound; if that cap is ever hit with more results still
  pending, `fetch()` prints a visible warning (see `_gws`/`fetch` below) —
  a silent truncation here would be exactly the "degradation that reads as
  a clean result" failure mode this codebase treats as its recurring bug.
* `parse_amount` prefers a total-labelled dollar figure (near "Total",
  "Amount charged", "Amount paid", "Grand Total") over the first bare `$`
  match. A receipt body routinely contains several dollar figures — a
  subtotal, a tax line, a discount — and blindly taking the first one risks
  picking the wrong amount, which (combined with a coincidental merchant
  match) could produce a real amount-extraction miss even where an email
  does exist. Falls back to the first bare match when no labelled figure is
  present, so existing behavior for simple one-figure bodies is unchanged.
"""

import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys

from .base import Receipt, SourceUnavailable, normalize_merchant

AMOUNT = re.compile(r"\$\s?([0-9][0-9,]*\.[0-9]{2})")
# A dollar figure explicitly labelled as the actual charged/total amount,
# e.g. "Total $99.91", "Amount paid: $99.91". \b before the label prevents
# matching "Subtotal" (no word boundary exists between "Sub" and "Total").
LABELED_AMOUNT = re.compile(
    r"\b(?:Total(?:\s+(?:amount|due))?|Amount\s+(?:charged|paid)|Grand\s+Total)\b"
    r"\s*:?\s*\$\s?([0-9][0-9,]*\.[0-9]{2})",
    re.IGNORECASE,
)
GWS = shutil.which("gws") or os.path.expanduser("~/bin/gws")
PAGE_GUARD = 50  # pages (100 messages/page = 5,000 messages) — see fetch()

# Normalized candidate (sender domain label, or display name, whichever is
# tried and comes up short) -> Ramp's normalized merchant_name. Populate only
# from measured mismatches — see module docstring.
ALIASES: dict[str, str] = {
    "neon": "neontech",  # sender domain neon.tech; Ramp calls it "Neon Tech"
    "anthropicpbc": "anthropic",  # belt-and-suspenders if domain lookup ever fails
}


def _gws(args: list[str], params: dict) -> dict:
    if not os.path.exists(GWS):
        raise SourceUnavailable(
            "`gws` CLI not found — see the gws skill (run `gws auth login`)"
        )
    proc = subprocess.run(
        [GWS, *args, "--params", json.dumps(params), "--format", "json"],
        capture_output=True, text=True, timeout=120,
    )
    # gws prints a keyring banner before JSON and reports auth failure as a
    # JSON error object with exit code 0. Both must be handled: a non-zero
    # exit check alone would silently pass an auth failure through as
    # "no receipts found."
    start = proc.stdout.find("{")
    if start < 0:
        raise SourceUnavailable(f"gws returned no JSON: {proc.stderr[:200]}")
    payload = json.loads(proc.stdout[start:])
    if "error" in payload:
        raise SourceUnavailable(
            f"gws: {payload['error'].get('message', '')[:160]} — run `gws auth login`"
        )
    return payload


def _domain_label(from_header: str) -> str:
    """Second-level domain label from the address in a From header, e.g.
    'billing@zoom.us' -> 'zoom', '"X" <invoice@mail.anthropic.com>' -> 'anthropic'.
    A cheap heuristic (last two dot-labels, take the first) — not a full
    public-suffix lookup — good enough for the vendor domains actually seen
    in this inbox. A wrong label is harmless: it just fails to bind.
    """
    m = re.search(r"@([\w.-]+)", from_header or "")
    if not m:
        return ""
    labels = m.group(1).split(".")
    return labels[-2] if len(labels) >= 2 else labels[0]


def _merchant_from_header(from_header: str) -> str:
    display = normalize_merchant(re.sub(r"<.*?>", "", from_header or ""))
    domain = normalize_merchant(_domain_label(from_header))
    for candidate in (domain, display):
        if candidate in ALIASES:
            return ALIASES[candidate]
    return domain or display


def _decode_b64url(data: str) -> bytes:
    # Gmail uses the URL-safe alphabet; standard b64decode fails on it.
    return base64.urlsafe_b64decode(data + "==")


class GmailSource:
    MERCHANTS: tuple[str, ...] = ()
    # Set during fetch() to a human-readable reason when the pagination cap
    # is hit with more results still pending; None otherwise. run.py checks
    # this (via getattr, so sources that never set it are unaffected) and
    # surfaces it through the report's existing "SOURCE ... " channel — the
    # stderr warning below is necessary but not sufficient, since it never
    # reaches the markdown report a user actually reads.
    truncated: str | None = None

    def parse_amount(self, text: str) -> int | None:
        text = text or ""
        # Prefer the LAST labelled total — receipts commonly list a subtotal
        # and/or tax line before the final "Total"/"Amount paid", and the
        # final one is the one that was actually charged. Fall back to the
        # first bare $ match when no label is present at all.
        labeled = list(LABELED_AMOUNT.finditer(text))
        m = labeled[-1] if labeled else AMOUNT.search(text)
        return round(float(m.group(1).replace(",", "")) * 100) if m else None

    def build_query(self, since: str, until: str) -> str:
        # Gmail's `before:` is EXCLUSIVE while `after:` is inclusive. Passing
        # `until` through unchanged drops every receipt sent ON the end date —
        # and since `until` defaults to today, today's transactions could never
        # match today's receipts. Ask for the day after so the window the caller
        # asked for is the window Gmail searches.
        until_exclusive = (dt.date.fromisoformat(until) + dt.timedelta(days=1)).isoformat()
        return (f"after:{since.replace('-', '/')} before:{until_exclusive.replace('-', '/')} "
                f"(subject:receipt OR subject:invoice OR subject:payment)")

    @staticmethod
    def _pdf_parts(part: dict) -> list[dict]:
        """Flatten the MIME tree to PDF parts, Receipt-* preferred over Invoice-*."""
        found = []
        if (part.get("mimeType") == "application/pdf"
                and (part.get("body") or {}).get("attachmentId")):
            found.append(part)
        for sub in part.get("parts") or []:
            found += GmailSource._pdf_parts(sub)
        return sorted(found, key=lambda p: not (p.get("filename") or "").startswith("Receipt-"))

    @staticmethod
    def _plain_text(part: dict) -> list[str]:
        """Flatten the MIME tree to decoded text/plain bodies (inline, no
        attachmentId — those come back directly on `get`, no extra call).
        """
        found = []
        body = part.get("body") or {}
        if part.get("mimeType") == "text/plain" and body.get("data"):
            found.append(_decode_b64url(body["data"]).decode("utf-8", "replace"))
        for sub in part.get("parts") or []:
            found += GmailSource._plain_text(sub)
        return found

    def fetch(self, since: str, until: str) -> list[Receipt]:
        # `list` paginates via nextPageToken and must be followed to the end.
        # Measured live 2026-08-01: a real query matched 516 messages over a
        # 2-month window (subject:receipt/invoice/payment are common words
        # across ordinary NSLS mail, not just vendor receipts) — a single
        # 100-result page misses real receipts entirely; a real vendor
        # receipt matching an outstanding transaction only turned up on page
        # 4. Guarded at PAGE_GUARD pages as a sane upper bound. If the guard
        # is hit while more pages remain, that's a silent truncation unless
        # we say so — print a visible warning rather than letting results
        # quietly vanish.
        self.truncated = None
        stubs: list[dict] = []
        page_token = None
        for _ in range(PAGE_GUARD):
            params = {"userId": "me", "q": self.build_query(since, until), "maxResults": 100}
            if page_token:
                params["pageToken"] = page_token
            listing = _gws(["gmail", "users", "messages", "list"], params)
            stubs.extend(listing.get("messages", []))
            page_token = listing.get("nextPageToken")
            if not page_token:
                break
        else:
            if page_token:
                self.truncated = (
                    f"hit the {PAGE_GUARD}-page cap, {len(stubs)} messages fetched, "
                    f"results incomplete"
                )
                print(
                    f"WARNING: gmail source hit the {PAGE_GUARD}-page pagination cap "
                    f"({len(stubs)} messages fetched) with more results still available "
                    f"(nextPageToken present) — receipts beyond page {PAGE_GUARD} were "
                    f"NOT scanned. Results are incomplete.",
                    file=sys.stderr,
                )

        out = []
        for stub in stubs:
            msg = _gws(
                ["gmail", "users", "messages", "get"],
                {"userId": "me", "id": stub["id"], "format": "full"},
            )
            hdrs = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}

            # Amount candidates: Subject + snippet (cheap, sometimes enough)
            # plus the full decoded text/plain body (necessary in practice —
            # see module docstring for the measured Anthropic counter-example).
            haystack = " ".join([
                hdrs.get("Subject", ""),
                msg.get("snippet", ""),
                *self._plain_text(msg["payload"]),
            ])
            cents = self.parse_amount(haystack)

            parts = self._pdf_parts(msg["payload"])
            if cents is None or not parts:
                continue

            att = _gws(
                ["gmail", "users", "messages", "attachments", "get"],
                {"userId": "me", "messageId": stub["id"], "id": parts[0]["body"]["attachmentId"]},
            )
            pdf = _decode_b64url(att["data"])
            if not pdf.startswith(b"%PDF"):
                continue

            import datetime as _dt
            date = _dt.datetime.fromtimestamp(
                int(msg["internalDate"]) / 1000, _dt.UTC
            ).date().isoformat()

            out.append(Receipt(
                merchant=_merchant_from_header(hdrs.get("From", "")),
                amount_cents=cents,
                date=date,
                pdf_bytes=pdf,
                provenance=f"gmail:msg {stub['id']}",
            ))
        return out


SOURCE = GmailSource()
