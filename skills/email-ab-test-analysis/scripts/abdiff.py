#!/usr/bin/env python3
"""Element-level copy diff between the arms of an email test.

The point is not to produce a pretty diff. The point is to COUNT how many
things changed at once, because that number decides whether a causal claim is
allowed at all. One change -> you may attribute. More than one -> you learned
that a bundle beat a bundle, and saying why is storytelling.

Usage:
    python abdiff.py arms.json
    python abdiff.py arms.json --json

Input shape:

    {"arms": [
       {"id": "101", "name": "...", "subject": "...", "preheader": "...",
        "body_html": "<html>...</html>"},
       ...
    ]}
"""

import argparse
import difflib
import html as htmllib
import json
import re
import sys

from espconfig import utf8_stdout

TAG_RE = re.compile(r"<[^>]*>")
STYLE_RE = re.compile(r"<(style|script)[\s\S]*?</\1>", re.I)
COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']*)["\']', re.I)
WS_RE = re.compile(r"\s+")

# Anchors and buttons styled as anchors carry the CTA. Liquid tags and the
# unsubscribe link are chrome, not copy.
ANCHOR_RE = re.compile(r"<a\b[^>]*>([\s\S]*?)</a>", re.I)
BLOCK_SPLIT_RE = re.compile(
    r"</?(?:p|div|li|ul|ol|tr|td|th|h[1-6]|br|table|section|header|footer|blockquote)"
    r"\b[^>]*>", re.I)
PUNCT_ONLY_RE = re.compile(r"[\W_]+", re.U)
CHROME = ("unsubscribe", "manage preferences", "{%", "facebook", "instagram",
          "linkedin", "twitter", "tiktok", "youtube", "reddit", "blog")


def visible_text(body):
    if not body:
        return ""
    t = COMMENT_RE.sub(" ", body)
    t = STYLE_RE.sub(" ", t)
    t = TAG_RE.sub(" ", t)
    t = htmllib.unescape(t)
    # Zero-width space, em space, hair space: invisible, common in marketing
    # HTML, and they make identical copy diff as different. Written as
    # escapes deliberately — as literals they are invisible in source and a
    # reformat or a copy-paste drops them with nothing to catch it.
    for invisible in ("\u200b", "\u2003", "\u200a"):
        t = t.replace(invisible, " ")
    return WS_RE.sub(" ", t).strip()


def links(body):
    if not body:
        return []
    out = []
    for h in HREF_RE.findall(body):
        h = h.strip()
        if not h or h.startswith("#"):
            continue
        out.append(h)
    return sorted(set(out))


def ctas(body):
    """Anchor text that is not site chrome — i.e. the actual calls to action."""
    if not body:
        return []
    found = []
    for inner in ANCHOR_RE.findall(body):
        txt = visible_text(inner)
        if not txt or len(txt) > 80:
            continue
        low = txt.lower()
        if any(c in low for c in CHROME):
            continue
        found.append(txt)
    seen, out = set(), []
    for c in found:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def prose_blocks(body):
    """Body copy as a list of block-level units, anchors removed.

    Splitting on sentences looks reasonable and is wrong for email: bullets
    rarely carry terminal punctuation, so a whole <ul> collapses into one
    "sentence" and the diff reports a single edited blob that spans several
    independent lines. Splitting on block tags keeps every bullet, paragraph
    and cell as its own unit, which is the granularity a copywriter edits at.

    Anchor text is dropped here because CTA and links are scored as their own
    elements; leaving them in would double-count them.
    """
    if not body:
        return []
    t = COMMENT_RE.sub(" ", body)
    t = STYLE_RE.sub(" ", t)
    t = ANCHOR_RE.sub(" ", t)
    out = []
    for chunk in BLOCK_SPLIT_RE.split(t):
        txt = visible_text(chunk)
        if len(txt) > 1 and not PUNCT_ONLY_RE.fullmatch(txt):
            out.append(txt)
    return out


def body_changes(sa, sb):
    """Block-level adds/drops/edits between two bodies."""
    sm = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
    added, removed, changed = [], [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "delete":
            removed += sa[i1:i2]
        elif tag == "insert":
            added += sb[j1:j2]
        elif tag == "replace":
            for old, new in zip(sa[i1:i2], sb[j1:j2]):
                changed.append((old, new))
            extra_old, extra_new = sa[i1 + len(sb[j1:j2]):i2], sb[j1 + len(sa[i1:i2]):j2]
            removed += extra_old
            added += extra_new
    return {"added": added, "removed": removed, "changed": changed}


# Only these are read. Anything else in an arm is either ignorable metadata or
# a hand-built payload using the wrong key — and the wrong key is dangerous,
# because unread copy would be reported as "nothing differs".
KNOWN_KEYS = {"id", "name", "subject", "preheader", "from_name",
              "body_html"}
IGNORABLE = {"esp", "source", "note", "notes", "url", "template_id",
             "action_id", "campaign", "campaign_id", "send_time"}
LIKELY_TYPO = {"body": "body_html", "body_text": "body_html",
               "html": "body_html", "content": "body_html",
               "cta": "body_html (the CTA is read from the anchors in the body)",
               "cta_text": "body_html (the CTA is read from the body's anchors)",
               "preheader_text": "preheader", "subject_line": "subject"}


def check_shape(arms):
    """Refuse a payload whose copy would be silently skipped.

    Reporting "0 elements changed" because the body arrived under a key nobody
    reads is the exact failure this tool exists to prevent.
    """
    problems = []
    for i, arm in enumerate(arms):
        label = arm.get("name") or arm.get("id") or f"arm {i + 1}"
        for k in arm:
            if k in KNOWN_KEYS or k in IGNORABLE:
                continue
            hint = LIKELY_TYPO.get(k)
            problems.append(f"  {label}: unrecognised key {k!r}" +
                            (f" — did you mean {hint}?" if hint else ""))
        if not arm.get("body_html"):
            problems.append(f"  {label}: no body_html, so body, CTA and links "
                            f"are UNKNOWN — not unchanged")
    if problems:
        header = ("abdiff reads only: " + ", ".join(sorted(KNOWN_KEYS)) +
                  ".\nWhat it cannot see, it cannot diff:\n")
        print(header + "\n".join(problems) + "\n", file=sys.stderr)
        if any("unrecognised key" in p for p in problems):
            raise SystemExit(
                "refusing to diff: fix the keys above, or the result would "
                "read as 'nothing differs' when copy actually changed.")


# What can only be read out of the body markup. When a body is unavailable
# these are UNKNOWN, and unknown is not unchanged: comparing an absent body to
# an absent body yields "nothing differs", and an absent body to a present one
# yields "arm B deleted all the copy". Both are fabrications.
BODY_ELEMENTS = ("body", "cta", "links")


def compare(arm_a, arm_b):
    body_a, body_b = arm_a.get("body_html"), arm_b.get("body_html")
    unreadable = [arm.get("name") or arm.get("id") or label
                  for arm, body, label in ((arm_a, body_a, "arm A"),
                                           (arm_b, body_b, "arm B"))
                  if not body]

    elements = {}

    sa, sb = (arm_a.get("subject") or "").strip(), (arm_b.get("subject") or "").strip()
    if sa != sb:
        elements["subject"] = {"a": sa, "b": sb}

    pa, pb = (arm_a.get("preheader") or "").strip(), (arm_b.get("preheader") or "").strip()
    if pa != pb:
        elements["preheader"] = {"a": pa, "b": pb}

    # The sender name is read before the subject is, and it moves opens. Read as
    # metadata it silently licensed "the subject did it" for a test that also
    # changed who the mail appeared to come from.
    fa, fb = (arm_a.get("from_name") or "").strip(), (arm_b.get("from_name") or "").strip()
    if fa != fb:
        elements["from_name"] = {"a": fa, "b": fb}

    if not unreadable:
        ta, tb = prose_blocks(body_a), prose_blocks(body_b)
        la, lb = links(body_a), links(body_b)
        ca, cb = ctas(body_a), ctas(body_b)

        if ca != cb:
            elements["cta"] = {"a": ca, "b": cb}

        if la != lb:
            elements["links"] = {"only_in_a": [x for x in la if x not in lb],
                                 "only_in_b": [x for x in lb if x not in la]}

        bc = body_changes(ta, tb)
        if bc["added"] or bc["removed"] or bc["changed"]:
            elements["body"] = bc

    return {
        "a": arm_a.get("name"), "b": arm_b.get("name"),
        "elements_changed": sorted(elements.keys()),
        "n_changed": len(elements),
        "detail": elements,
        "unknown_elements": list(BODY_ELEMENTS) if unreadable else [],
        "body_unreadable_for": unreadable,
        # One element out of a set that was only partly readable is not one
        # element. Attribution needs the whole set compared.
        "attribution_allowed": len(elements) == 1 and not unreadable,
    }


def render(cmp_result):
    out = []
    out.append(f"{cmp_result['a']}")
    out.append(f"   vs {cmp_result['b']}")
    n = cmp_result["n_changed"]
    unreadable = cmp_result.get("body_unreadable_for") or []
    unknown = cmp_result.get("unknown_elements") or []
    out.append(f"   Independent elements changed: {n} "
               f"({', '.join(cmp_result['elements_changed']) or 'none'})"
               + (f", of the elements that could be read" if unknown else ""))
    if unknown:
        out.append(f"   UNKNOWN, not unchanged: {', '.join(unknown)} — no body "
                   f"markup for {', '.join(unreadable)}. Nothing below rules "
                   f"out a change to any of them.")
    out.append("")

    d = cmp_result["detail"]
    if "from_name" in d:
        out.append(f"  FROM NAME")
        out.append(f"    A: {d['from_name']['a'] or '(none)'}")
        out.append(f"    B: {d['from_name']['b'] or '(none)'}")
    if "subject" in d:
        out.append(f"  SUBJECT")
        out.append(f"    A: {d['subject']['a']}")
        out.append(f"    B: {d['subject']['b']}")
    if "preheader" in d:
        out.append(f"  PREHEADER")
        out.append(f"    A: {d['preheader']['a'] or '(none)'}")
        out.append(f"    B: {d['preheader']['b'] or '(none)'}")
    if "cta" in d:
        out.append(f"  CTA")
        out.append(f"    A: {' | '.join(d['cta']['a']) or '(none)'}")
        out.append(f"    B: {' | '.join(d['cta']['b']) or '(none)'}")
    if "links" in d:
        out.append(f"  LINKS")
        for x in d["links"]["only_in_a"]:
            out.append(f"    only in A: {x}")
        for x in d["links"]["only_in_b"]:
            out.append(f"    only in B: {x}")
    if "body" in d:
        out.append(f"  BODY")
        for x in d["body"]["removed"]:
            out.append(f"    - dropped: {x}")
        for x in d["body"]["added"]:
            out.append(f"    + added:   {x}")
        for old, new in d["body"]["changed"]:
            out.append(f"    ~ A: {old}")
            out.append(f"      B: {new}")
    out.append("")

    if cmp_result["attribution_allowed"]:
        out.append("  IS THE DIFFERENCE IN PERFORMANCE ATTRIBUTABLE TO ONE "
                   "ELEMENT?  YES — exactly one element differs, so a "
                   "significant result on the matching metric names its cause.")
    elif unknown:
        out.append(f"  IS THE DIFFERENCE IN PERFORMANCE ATTRIBUTABLE TO ONE "
                   f"ELEMENT?  CANNOT SAY — {n} readable element(s) differ, but "
                   f"{', '.join(unknown)} were never compared. Attribution is "
                   f"withheld: supply the body markup for "
                   f"{', '.join(unreadable)} (fetch_manual --body-dir) to get "
                   f"an answer instead of a guess.")
    elif n == 0:
        out.append("  IS THE DIFFERENCE IN PERFORMANCE ATTRIBUTABLE TO ONE "
                   "ELEMENT?  NOT APPLICABLE — nothing differs in the copy. If "
                   "the outcomes differ, the cause is outside the message: "
                   "audience, timing, deliverability, or send volume.")
    else:
        out.append(f"  IS THE DIFFERENCE IN PERFORMANCE ATTRIBUTABLE TO ONE "
                   f"ELEMENT?  NO — {n} elements changed together. This test can "
                   "show which bundle won, not why. Report the differences in "
                   "full, say which one most likely drove the result and why (or "
                   "that none stands out), name the one cleanest to isolate, and "
                   "isolate it next time.")
    return "\n".join(out)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("payload")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with open(args.payload, encoding="utf-8") as fh:
        data = json.load(fh)
    arms = data["arms"]
    check_shape(arms)

    results = []
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            results.append(compare(arms[i], arms[j]))

    if args.json:
        json.dump(results, sys.stdout, indent=2)
    else:
        for r in results:
            print(render(r))
            print("-" * 72)


if __name__ == "__main__":
    main()
