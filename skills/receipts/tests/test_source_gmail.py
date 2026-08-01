#!/usr/bin/env python3.12
"""Tests for the Gmail source.

parse_amount / build_query / merchant resolution are pure and tested directly.
fetch() is verified hermetically by mocking the `gws` subprocess — no network,
no gws binary, no auth required to run this file.
"""

import base64
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sources.gmail import SOURCE, PAGE_GUARD, _domain_label, _merchant_from_header
from sources.base import SourceUnavailable


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def test_parse_amount_handles_thousands():
    assert SOURCE.parse_amount("Total $1,085.00 paid") == 108500


def test_parse_amount_plain():
    assert SOURCE.parse_amount("Amount charged: $99.91") == 9991


def test_parse_amount_absent():
    assert SOURCE.parse_amount("used 75% of its credits") is None


def test_parse_amount_prefers_total_over_subtotal_tax_and_discount():
    # Realistic receipt shape: several dollar figures, only one of which is
    # the actual charged amount. Blindly taking the first "$" match would
    # grab the subtotal ($50.00) instead of what was actually charged.
    text = "Subtotal $50.00 Tax $4.13 Discount -$5.00 Total $49.13"
    assert SOURCE.parse_amount(text) == 4913


def test_parse_amount_prefers_amount_paid_over_subtotal_and_tax_lines():
    # Reproduces the real Anthropic receipt body structure (verified live,
    # message 19f94f2f9efe8c87): a per-unit price, a subtotal, a
    # "Total excluding tax" line, and a tax line all precede the actual
    # "Total" / "Amount paid" figure that was charged.
    text = ("Qty 1 $95.02 Subtotal $95.02 Total excluding tax $95.02 "
            "Tax - Colorado (5.15%) $4.89 Total $99.91 Amount paid $99.91")
    assert SOURCE.parse_amount(text) == 9991


def test_parse_amount_does_not_match_subtotal_as_total():
    # "Subtotal" must never satisfy the "Total" label match — there is no
    # word boundary between "Sub" and "Total", so \b protects against it.
    # Falls back to the first bare "$" match when nothing is labelled.
    text = "Subtotal $50.00"
    assert SOURCE.parse_amount(text) == 5000


def test_build_query_scopes_by_date():
    q = SOURCE.build_query("2026-07-01", "2026-07-31")
    assert "after:2026/07/01" in q and "before:2026/07/31" in q


def test_empty_merchants_means_any():
    assert SOURCE.MERCHANTS == ()


# ---------------------------------------------------------------------------
# Merchant resolution — measured against real Gmail senders (2026-08-01)
# ---------------------------------------------------------------------------

def test_domain_label_extracts_second_level_domain():
    assert _domain_label('"Zoom Communications, Inc." <billing@zoom.us>') == "zoom"
    assert _domain_label('"Anthropic, PBC" <invoice+statements@mail.anthropic.com>') == "anthropic"
    assert _domain_label('"Asana" <billing@email1.asana.com>') == "asana"
    assert _domain_label("changelog@neon.tech") == "neon"


def test_merchant_from_header_matches_ramp_merchant_name_directly_for_most_vendors():
    # These line up on the domain label alone — no alias needed. Verified
    # against Ramp's real merchant_name field: "Anthropic", "Zoom", "Asana".
    assert _merchant_from_header('"Anthropic, PBC" <invoice+statements@mail.anthropic.com>') == "anthropic"
    assert _merchant_from_header('"Zoom Communications, Inc." <billing@zoom.us>') == "zoom"
    assert _merchant_from_header('"Asana" <billing@email1.asana.com>') == "asana"


def test_merchant_from_header_resolves_neon_tech_via_alias():
    # Sender domain is neon.tech -> domain label "neon". Ramp's merchant_name
    # is "Neon Tech" -> normalize_merchant gives "neontech". "neon" !=
    # "neontech" on any generic rule, so this is the one measured case that
    # needs an explicit alias entry.
    assert _merchant_from_header("Neon <changelog@neon.tech>") == "neontech"


def test_merchant_from_header_falls_back_to_display_name_when_no_alias():
    # An unmapped vendor with no domain still resolves to *something*
    # normalized, even if it won't happen to bind — that's safe (UNFOUND),
    # never a wrong match.
    assert _merchant_from_header('"Totally Unknown Co" <hello@nowhere-in-particular.example>') == \
        "nowhereinparticular"


# ---------------------------------------------------------------------------
# fetch() — hermetic: gws subprocess fully mocked
# ---------------------------------------------------------------------------

def _b64url_nopad(raw: bytes) -> str:
    """Mirror real Gmail behavior: base64url data with no padding."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _proc(payload: dict, banner: bool = True):
    class _P:
        pass
    p = _P()
    text = json.dumps(payload)
    p.stdout = ("Using keyring backend: keyring\n" + text) if banner else text
    p.stderr = ""
    p.returncode = 0
    return p


LIST_PAYLOAD = {"messages": [{"id": "msg1", "threadId": "t1"}]}

GET_PAYLOAD_TWO_PDFS = {
    "payload": {
        "headers": [
            {"name": "Subject", "value": "Your receipt from Anthropic, PBC #2422-8527-1659"},
            {"name": "From", "value": '"Anthropic, PBC" <invoice+statements@mail.anthropic.com>'},
        ],
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {
                        "data": _b64url_nopad(b"Receipt from Anthropic, PBC $99.91 Paid July 24, 2026")
                    }},
                    {"mimeType": "text/html", "body": {"data": _b64url_nopad(b"<p>html</p>")}},
                ],
            },
            {"mimeType": "application/pdf", "filename": "Invoice-DSCOITDB-0021.pdf",
             "body": {"attachmentId": "ATT_INVOICE", "size": 32965}},
            {"mimeType": "application/pdf", "filename": "Receipt-2422-8527-1659.pdf",
             "body": {"attachmentId": "ATT_RECEIPT", "size": 34104}},
        ],
    },
    "snippet": "Your receipt from Anthropic, PBC #2422-8527-1659      ",
    "internalDate": "1784943600000",  # 2026-07-24 (approx, UTC)
}

PDF_BYTES = b"%PDF-1.4\nfake pdf content for testing\n"


def _attachment_payload(raw: bytes = PDF_BYTES):
    return {"attachmentId": "whatever", "size": len(raw), "data": _b64url_nopad(raw)}


def _dispatch(responses):
    """side_effect for subprocess.run: route by the gws subcommand."""
    def run(cmd, capture_output=True, text=True, timeout=120):
        # cmd = [GWS, "gmail", "users", "messages", ("list"|"get"|"attachments"), ..., "--params", json, "--format", "json"]
        sub = tuple(cmd[1:5])
        if sub[:4] == ("gmail", "users", "messages", "list"):
            return _proc(responses["list"])
        if sub[:4] == ("gmail", "users", "messages", "get"):
            return _proc(responses["get"])
        if sub[:4] == ("gmail", "users", "messages", "attachments"):
            return _proc(responses["attachments"])
        raise AssertionError(f"unexpected gws subcommand: {cmd}")
    return run


def test_fetch_raises_source_unavailable_when_gws_missing():
    with patch("sources.gmail.os.path.exists", return_value=False):
        try:
            SOURCE.fetch("2026-01-01", "2026-12-31")
        except SourceUnavailable as exc:
            assert "gws" in str(exc).lower()
            return
    raise AssertionError("fetch() must raise SourceUnavailable when gws is missing")


def test_fetch_raises_source_unavailable_on_auth_error_with_exit_code_zero():
    # gws reports auth failure as a JSON {"error": {...}} object with exit
    # code 0 — a bare `returncode != 0` check would silently swallow this.
    error_payload = {"error": {"message": "invalid_grant: token expired"}}
    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=_dispatch({"list": error_payload,
                                                                        "get": {}, "attachments": {}})):
        try:
            SOURCE.fetch("2026-01-01", "2026-12-31")
        except SourceUnavailable as exc:
            assert "gws auth login" in str(exc)
            return
    raise AssertionError("fetch() must raise SourceUnavailable on a JSON error payload, even with exit code 0")


def test_fetch_strips_keyring_banner_before_parsing_json():
    responses = {"list": {"messages": []}, "get": {}, "attachments": {}}
    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=_dispatch(responses)):
        receipts = SOURCE.fetch("2026-01-01", "2026-12-31")
    assert receipts == []


def test_fetch_prefers_receipt_prefixed_pdf_and_decodes_urlsafe_base64():
    responses = {
        "list": LIST_PAYLOAD,
        "get": GET_PAYLOAD_TWO_PDFS,
        "attachments": _attachment_payload(PDF_BYTES),
    }
    captured_attachment_id = {}

    def run(cmd, capture_output=True, text=True, timeout=120):
        sub = tuple(cmd[1:5])
        if sub[:4] == ("gmail", "users", "messages", "list"):
            return _proc(responses["list"])
        if sub[:4] == ("gmail", "users", "messages", "get"):
            return _proc(responses["get"])
        if sub[:4] == ("gmail", "users", "messages", "attachments"):
            params_idx = cmd.index("--params") + 1
            params = json.loads(cmd[params_idx])
            captured_attachment_id["id"] = params["id"]
            return _proc(responses["attachments"])
        raise AssertionError(f"unexpected gws subcommand: {cmd}")

    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=run):
        receipts = SOURCE.fetch("2026-01-01", "2026-12-31")

    assert captured_attachment_id["id"] == "ATT_RECEIPT", (
        "must fetch the Receipt-* attachment, not Invoice-*"
    )
    assert len(receipts) == 1
    r = receipts[0]
    assert r.pdf_bytes == PDF_BYTES
    assert r.pdf_bytes.startswith(b"%PDF")


def test_fetch_extracts_amount_from_decoded_body_when_subject_and_snippet_lack_it():
    # Reproduces the real Anthropic reference message (id 19f94f2f9efe8c87):
    # neither Subject nor snippet contain a dollar figure — only the decoded
    # text/plain body does.
    responses = {
        "list": LIST_PAYLOAD,
        "get": GET_PAYLOAD_TWO_PDFS,
        "attachments": _attachment_payload(PDF_BYTES),
    }
    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=_dispatch(responses)):
        receipts = SOURCE.fetch("2026-01-01", "2026-12-31")

    assert len(receipts) == 1
    assert receipts[0].amount_cents == 9991
    assert "$" not in GET_PAYLOAD_TWO_PDFS["snippet"]
    assert "$" not in dict(
        (h["name"], h["value"]) for h in GET_PAYLOAD_TWO_PDFS["payload"]["headers"]
    )["Subject"]


def test_fetch_resolves_merchant_from_sender_domain():
    responses = {
        "list": LIST_PAYLOAD,
        "get": GET_PAYLOAD_TWO_PDFS,
        "attachments": _attachment_payload(PDF_BYTES),
    }
    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=_dispatch(responses)):
        receipts = SOURCE.fetch("2026-01-01", "2026-12-31")
    assert receipts[0].merchant == "anthropic"


def test_fetch_skips_message_with_no_pdf_attachment():
    get_no_pdf = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Amount charged: $10.00"},
                {"name": "From", "value": "billing@example.com"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64url_nopad(b"nothing attached here")},
        },
        "snippet": "no attachment",
        "internalDate": "1784943600000",
    }
    responses = {"list": LIST_PAYLOAD, "get": get_no_pdf, "attachments": {}}
    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=_dispatch(responses)):
        receipts = SOURCE.fetch("2026-01-01", "2026-12-31")
    assert receipts == []


def test_fetch_skips_message_with_unparseable_amount():
    get_no_amount = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "used 75% of its credits"},
                {"name": "From", "value": "billing@example.com"},
            ],
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "application/pdf", "filename": "Receipt-x.pdf",
                 "body": {"attachmentId": "A1", "size": 10}},
            ],
        },
        "snippet": "no dollar figure anywhere in this message",
        "internalDate": "1784943600000",
    }
    responses = {"list": LIST_PAYLOAD, "get": get_no_amount, "attachments": _attachment_payload()}
    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=_dispatch(responses)):
        receipts = SOURCE.fetch("2026-01-01", "2026-12-31")
    assert receipts == []


def test_fetch_follows_next_page_token_to_the_end():
    # Measured live 2026-08-01: a real query matched 516 messages over a
    # 2-month window, and a real Asana receipt only appeared on page 4 of a
    # 100-per-page listing. Reading only page 1 silently drops receipts.
    page1 = {"messages": [{"id": "p1a", "threadId": "t"}], "nextPageToken": "TOK2"}
    page2 = {"messages": [{"id": "p2a", "threadId": "t"}]}  # no nextPageToken -> stop

    list_calls = []

    def run(cmd, capture_output=True, text=True, timeout=120):
        sub = tuple(cmd[1:5])
        if sub[:4] == ("gmail", "users", "messages", "list"):
            params_idx = cmd.index("--params") + 1
            params = json.loads(cmd[params_idx])
            list_calls.append(params)
            return _proc(page2 if params.get("pageToken") == "TOK2" else page1)
        if sub[:4] == ("gmail", "users", "messages", "get"):
            return _proc(GET_PAYLOAD_TWO_PDFS)
        if sub[:4] == ("gmail", "users", "messages", "attachments"):
            return _proc(_attachment_payload(PDF_BYTES))
        raise AssertionError(f"unexpected gws subcommand: {cmd}")

    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=run):
        receipts = SOURCE.fetch("2026-01-01", "2026-12-31")

    assert len(list_calls) == 2, "must follow nextPageToken to a second page"
    assert list_calls[1]["pageToken"] == "TOK2"
    assert len(receipts) == 2, "receipts from both pages must be returned"


def test_fetch_warns_when_pagination_cap_is_hit_with_more_pages_pending():
    # If nextPageToken is still set after PAGE_GUARD pages, results beyond
    # that point are silently dropped unless we say so. This must be a
    # visible signal (printed warning), not just a code comment — a
    # degradation that reads as a clean result is the exact recurring bug
    # this codebase is built to avoid.
    call_count = {"n": 0}

    def run(cmd, capture_output=True, text=True, timeout=120):
        sub = tuple(cmd[1:5])
        if sub[:4] == ("gmail", "users", "messages", "list"):
            call_count["n"] += 1
            # Every page still has a nextPageToken — never exhausts on its own.
            return _proc({"messages": [{"id": f"m{call_count['n']}", "threadId": "t"}],
                           "nextPageToken": f"TOK{call_count['n']}"})
        if sub[:4] == ("gmail", "users", "messages", "get"):
            return _proc({"payload": {"headers": [], "mimeType": "text/plain",
                                       "body": {"data": ""}},
                          "snippet": "no dollar figure", "internalDate": "1784943600000"})
        raise AssertionError(f"unexpected gws subcommand: {cmd}")

    import io
    captured_stderr = io.StringIO()
    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=run), \
         patch("sources.gmail.sys.stderr", captured_stderr):
        SOURCE.fetch("2026-01-01", "2026-12-31")

    assert call_count["n"] == PAGE_GUARD, (
        f"must stop at the {PAGE_GUARD}-page guard, not loop forever"
    )
    warning = captured_stderr.getvalue()
    assert "WARNING" in warning
    assert str(PAGE_GUARD) in warning
    assert "incomplete" in warning.lower() or "not scanned" in warning.lower()
    # The stderr warning alone isn't enough — run.py's report only reaches a
    # user via skipped_sources, which it populates by checking this public
    # attribute (getattr(src, "truncated", None)). Without it being set,
    # truncation would be invisible outside raw terminal output.
    assert SOURCE.truncated, "must set a public `truncated` reason so run.py can report it"
    assert str(PAGE_GUARD) in SOURCE.truncated


def test_fetch_does_not_warn_when_pagination_ends_within_the_cap():
    # The warning must be specific to truly hitting the cap — a normal run
    # that finishes in a couple of pages must stay silent.
    responses = {
        "list": LIST_PAYLOAD,  # single page, no nextPageToken
        "get": GET_PAYLOAD_TWO_PDFS,
        "attachments": _attachment_payload(PDF_BYTES),
    }
    import io
    captured_stderr = io.StringIO()
    with patch("sources.gmail.os.path.exists", return_value=True), \
         patch("sources.gmail.subprocess.run", side_effect=_dispatch(responses)), \
         patch("sources.gmail.sys.stderr", captured_stderr):
        SOURCE.fetch("2026-01-01", "2026-12-31")
    assert captured_stderr.getvalue() == ""
    assert SOURCE.truncated is None, "a normal run must not leave a stale truncated reason"


def test_fetch_provenance_is_stable_and_keyed_on_message_id():
    responses = {
        "list": LIST_PAYLOAD,
        "get": GET_PAYLOAD_TWO_PDFS,
        "attachments": _attachment_payload(PDF_BYTES),
    }
    runs = []
    for _ in range(2):
        with patch("sources.gmail.os.path.exists", return_value=True), \
             patch("sources.gmail.subprocess.run", side_effect=_dispatch(responses)):
            runs.append(SOURCE.fetch("2026-01-01", "2026-12-31"))
    assert runs[0][0].provenance == runs[1][0].provenance == "gmail:msg msg1"


if __name__ == "__main__":
    print("Running gmail source tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll gmail source tests passed.")
