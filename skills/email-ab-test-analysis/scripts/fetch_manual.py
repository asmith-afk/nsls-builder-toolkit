#!/usr/bin/env python3
"""Build the payloads from a CSV or a UI export — no API credentials needed.

    python3 fetch_manual.py --csv arms.csv --out t1 --esp hubspot
    python3 fetch_manual.py --csv export.csv --out t1 --map "clicks=Unique Clicks"

WHY THIS EXISTS
---------------
Creating a HubSpot private app is a permission most people who run email are not
granted; getting it means a request to whoever administers the portal.
Requiring a token would have made this skill unusable for the majority of the
people it is for. Anyone who can open the email performance screen can read
these numbers off it, so that is the floor: if you can see the test, you can
analyse it.

The statistics and diff engines never knew where their input came from. This is
just an honest front door for the case where the door is a screen.

FILE SHAPE
----------
One row per arm. The separator is detected, so a comma CSV, a tab-separated
paste out of a UI table, or a semicolon or pipe export all work — pasting the
rows into a .txt is enough. Headers are matched case-insensitively against the
aliases below, so most ESP exports work unedited. Anything unmatched is reported
rather than silently dropped — a column read as zero is how a test gets called
backwards.

    name,subject,delivered,opens,clicks,unsubscribed,bounced
    Control,Your plan renews soon,10000,2500,300,25,90
    Variant B,Your plan renews soon,10000,2480,265,31,88

Override a mapping with --map "field=Header Name" (repeatable).

COPY DIFF
---------
Numbers alone give you the verdict, not the reason. For the copy diff, save each
arm's HTML as <name>.html in one folder and pass --body-dir. Without it you
still get subjects compared; body and CTA are reported as unknown rather than
as unchanged, because "we did not look" and "nothing changed" are different
findings and must never render the same.
"""

import argparse
import csv
import os
import re
import sys

from espconfig import write_payloads, utf8_stdout

ALIASES = {
    "id": ["id", "email id", "emailid", "action id"],
    "name": ["name", "arm", "variant", "email name", "email", "campaign"],
    "subject": ["subject", "subject line"],
    "delivered": ["delivered", "delivered count", "sent", "total sent",
                  "emails delivered"],
    # Raw counts first — every open and click, machine or human. The human-only
    # columns are kept as a diagnostic where an ESP reports them separately.
    "opened": ["opens", "open", "opened", "unique opens", "unique open",
               "total opens"],
    "clicked": ["clicks", "click", "clicked", "unique clicks", "unique click",
                "total clicks"],
    "human_opened": ["human opens", "human_opened", "human open"],
    "human_clicked": ["human clicks", "human_clicked", "human click"],
    "converted": ["converted", "conversions", "conversion"],
    "unsubscribed": ["unsubscribed", "unsubs", "unsubscribes", "opt outs"],
    "spammed": ["spammed", "spam reports", "spamreport", "complaints"],
    "bounced": ["bounced", "bounces", "bounce"],
}
NUMERIC = [k for k in ALIASES if k not in ("id", "name", "subject")]


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def sniff_delimiter(sample):
    """Pick the separator from the header line.

    People paste tables out of an ESP screen, and what lands on the clipboard is
    usually tab-separated. Assuming a comma made the whole file parse as one
    column, which surfaced as every field 'not found' rather than as an error.
    """
    header = sample.splitlines()[0] if sample else ""
    counts = {d: header.count(d) for d in ("\t", ",", ";", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def build_map(headers, overrides):
    lookup = {norm(h): h for h in headers}
    mapping, used = {}, set()
    for field, names in ALIASES.items():
        if field in overrides:
            mapping[field] = overrides[field]
            used.add(overrides[field])
            continue
        for cand in names:
            h = lookup.get(norm(cand))
            if h and h not in used:
                mapping[field] = h
                used.add(h)
                break
    return mapping, [h for h in headers if h not in used]


def text_to_blocks(raw):
    """Wrap pasted plain text so the diff can see line-level changes.

    The diff splits on block tags. Text pasted out of an email client has no
    tags, so without this the whole body collapses into one unit and every
    edit reports as one enormous changed blob. One line becomes one block —
    which is how someone reading the email thinks about it anyway.

    A line in ALL CAPS or wrapped in [brackets] is almost always the button;
    marking it as an anchor lets the CTA be scored as its own element.
    """
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.fullmatch(r"\[(.+)\]", line)
        looks_like_cta = bool(m) or (
            line.isupper() and 2 <= len(line.split()) <= 6)
        if looks_like_cta:
            out.append(f'<a href="#cta">{m.group(1) if m else line}</a>')
        else:
            out.append(f"<p>{line}</p>")
    return "".join(out)


def to_int(v):
    if v is None:
        return 0
    s = str(v).strip().replace(",", "").replace("%", "")
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--test", help="name of the test, for the report header")
    ap.add_argument("--esp", help="hubspot: opens are not reported by source")
    ap.add_argument("--metric", help="decision metric; defaults to raw clicks "
                                     "when the CSV carries a clicks column")
    ap.add_argument("--cohort", help="who entered this test, in your own words: "
                                     "name the group and the rule that put them "
                                     "in it. Compared verbatim across tests, so "
                                     "an identical string means the same cohort.")
    ap.add_argument("--body-dir", help="folder of <name>.html files for the diff")
    ap.add_argument("--map", action="append", default=[],
                    metavar="field=Header", help="override a column mapping")
    args = ap.parse_args()

    overrides = {}
    for spec in args.map:
        if "=" not in spec:
            ap.error(f"--map needs field=Header, got {spec!r}")
        f, h = spec.split("=", 1)
        if f not in ALIASES:
            ap.error(f"unknown field {f!r}; known: {', '.join(sorted(ALIASES))}")
        overrides[f] = h

    with open(args.csv, newline="", encoding="utf-8-sig") as fh:
        text = fh.read()
    delim = sniff_delimiter(text)
    if delim != ",":
        print(f"   separator detected: {delim!r}")
    rows = list(csv.DictReader(text.splitlines(True), delimiter=delim))
    if not rows:
        raise SystemExit(f"{args.csv} has no data rows")
    if len(rows) < 2:
        raise SystemExit(f"{args.csv} has one arm; a test needs at least two")

    mapping, unused = build_map(rows[0].keys(), overrides)

    print("column mapping:")
    for field in ["name", "subject"] + NUMERIC:
        src = mapping.get(field)
        print(f"   {field:<15} <- {src if src else '(not found -> 0)'}")
    if unused:
        print(f"   ignored columns: {', '.join(unused)}")
    missing = ["delivered"] if "delivered" not in mapping else []
    if "clicked" not in mapping and "human_clicked" not in mapping:
        missing.append("clicked")
    if missing:
        raise SystemExit(
            f"\ncannot proceed without {', '.join(missing)}. Name the column "
            f"with --map, e.g. --map \"delivered=Emails Delivered\".")
    if "opened" not in mapping and "human_opened" not in mapping:
        print("   note: no opens column — click-to-open will be skipped")

    metric = args.metric or ("clicked" if "clicked" in mapping
                             else "human_clicked")
    if metric == "human_clicked":
        print("   note: only a human-clicks column was found. Raw clicks are "
              "the better default — machine activity acts on both arms alike.")

    unsplit_opens = (args.esp or "").lower() == "hubspot"
    stats_arms, copy_arms = [], []
    for i, row in enumerate(rows):
        name = row.get(mapping.get("name", ""), "") or f"Arm {i + 1}"
        arm_id = row.get(mapping.get("id", ""), "") or str(i + 1)
        subject = row.get(mapping.get("subject", ""), "") or None
        arm = {"id": str(arm_id), "name": name.strip(), "subject": subject,
               "cohort": {
                   "campaign_id": args.out,
                   "campaign_name": args.test or args.csv,
                   "fields": {"declared": args.cohort} if args.cohort else {},
                   "resolved": bool(args.cohort)},
               "periods": {}}
        for field in NUMERIC:
            arm[field] = to_int(row.get(mapping[field])) if field in mapping else 0
        if unsplit_opens:
            arm["opens_not_split_by_source"] = True
        stats_arms.append(arm)

        body = None
        if args.body_dir:
            stem = name.strip()
            for cand in (f"{stem}.html", f"{arm_id}.html",
                         f"{stem}.txt", f"{arm_id}.txt"):
                p = os.path.join(args.body_dir, cand)
                if os.path.exists(p):
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        raw = fh.read()
                    body = raw if cand.endswith(".html") else text_to_blocks(raw)
                    break
            if body is None:
                print(f"   note: no body file for {stem!r} in {args.body_dir} "
                      f"(looked for .html and .txt)", file=sys.stderr)
        copy_arms.append({"id": str(arm_id), "name": name.strip(),
                          "subject": subject, "preheader": None,
                          "body_html": body})

    if not args.body_dir:
        print("\nNo --body-dir given: the diff will compare subjects only. "
              "Body and CTA differences are UNKNOWN, not absent — do not report "
              "them as unchanged.", file=sys.stderr)
    if unsplit_opens:
        print("HubSpot: opens are not reported by source, so the human/prefetch "
              "split is unavailable as a placement diagnostic. The open rate "
              "still reads.", file=sys.stderr)
    print("No period data from a manual import, so the overlap check cannot "
          "run. Confirm the send windows yourself — and confirm both arms went "
          "to the same cohort under the same rules, which decides whether they "
          "are comparable at all.", file=sys.stderr)

    write_payloads(args.out, args.test or f"Manual import from {args.csv}",
                   metric, stats_arms, copy_arms)


if __name__ == "__main__":
    main()
