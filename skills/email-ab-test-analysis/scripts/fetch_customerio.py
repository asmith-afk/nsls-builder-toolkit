#!/usr/bin/env python3
"""Pull a Customer.io campaign's arms into the payloads the engines read.

    python fetch_customerio.py --campaign <id> --out <prefix> --key-file <path>
    python fetch_customerio.py --campaign <id> --out <prefix> --region eu

Region matters: the EU datacenter is a different host, and calling the US host
for an EU workspace returns a 301 rather than an error you would notice. Set it
once in esp.json and stop thinking about it:

    {"esp": "customerio", "region": "us", "workspace": "YOUR_WORKSPACE_ID"}

Resend-to-non-opener legs are dropped by default, matched on a name pattern
(--exclude changes it, --include-rs2no keeps them). They send to a population
that has already declined once, so their denominator is not comparable to the
initial send.

Send windows are rebuilt from per-send records by default, not from the metric
period arrays. The arrays are a summary: anything older than a quarter comes
back in monthly buckets, and a monthly bucket cannot show that one arm stopped
on the 8th while the other ran to the 30th. Everything after that stop is
post-declaration volume on a single arm, and folding it into the comparison is
how a dead heat is reported as a decisive win. `--windows periods` accepts the
coarse read; the output then says on every line that the window is unverified.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from espconfig import Config, read_key, write_payloads, utf8_stdout

HOSTS = {
    "us": "https://api.customer.io/v1",
    "eu": "https://api-eu.customer.io/v1",
}

# Per-send records. The App API has no `/deliveries` — that path exists only on
# the internal API the MCP connector uses, and returns 404 here. `/messages` is
# the public equivalent and carries more: each record's `metrics` is a map of
# metric name to the unix timestamp it happened at, so any count over any window
# is a matter of counting records, down to the second.
MESSAGES_PATH = "/messages"

# `limit` is capped server-side: asking for 5000 returns 1000. Asking for more
# than the cap is not an error, so a caller that trusts its own page size reads
# a truncated page as a complete one.
PAGE_CAP = 1000

# Refuse rather than spend an hour paging a newsletter-sized arm by accident.
# Narrow the window instead — the flight being read is what matters, not the
# arm's whole life.
MAX_MESSAGES = 250_000

# Counted per record by presence of a timestamp. `sent` is excluded on purpose:
# it is the denominator's own event, tracked separately as the send day.
MESSAGE_FIELDS = ("delivered", "opened", "clicked", "human_opened",
                  "human_clicked", "prefetch_opened", "machine_clicked",
                  "converted", "unsubscribed", "spammed", "bounced")
# Resend-to-non-opener legs are excluded by default because their denominator
# is not comparable to an initial send. There is no standard name for them:
# `RS2NO` is one workspace's shorthand, and the spelled-out form is another's.
# Whatever the local convention is, set it — and note that the fetcher always
# reports what this pattern matched, including when it matched nothing, so a
# convention it does not know about is visible rather than silently pooled in.
DEFAULT_EXCLUDE = r"RS2NO|resend.{0,3}to.{0,3}non.{0,3}opener"

# Fields that define WHO entered a campaign. Two sends can only be compared if
# these match, so they travel with the numbers rather than living in someone's
# memory. Key names vary between API versions and campaign types, so every
# candidate is tried and whatever is found is recorded — including nothing,
# which is a valid and important answer.
COHORT_KEYS = ("trigger", "triggers", "trigger_segment_ids", "segment",
               "segment_id", "filter", "event_name")

# Recorded for the operator to read, never compared. A campaign's type or
# sending frequency can differ without the audience differing, and comparing
# them would raise a cohort question where there is none.
CONTEXT_KEYS = ("type", "active_behavior", "frequency", "created",
                "first_started")


def cohort_of(camp, cid, base=None, key=None):
    """Describe the campaign's entry conditions, or say that it could not.

    `resolved` is False when the response carried none of the entry-condition
    fields — in which case the operator has to answer the question, because
    guessing it is exactly the error this exists to prevent.

    A segment id is only a pointer, so the segments themselves are resolved when
    credentials allow. A *dynamic* segment carries `conditions` — the actual
    membership rule, which two campaigns can be compared on directly. A *manual*
    segment has no rule to read: somebody put people in it by hand, and no
    amount of API reading will recover what they intended. That distinction is
    the whole difference between the tool deciding and the tool asking.
    """
    def pick(keys):
        return {k: camp[k] for k in keys
                if camp.get(k) not in (None, "", [], {})}

    found = pick(COHORT_KEYS)
    segments = []
    for sid in (camp.get("trigger_segment_ids") or []):
        if not (base and key):
            break
        try:
            s = get(base, f"/segments/{sid}", key).get("segment", {}) or {}
        except SystemExit:
            continue
        segments.append({"id": sid, "name": s.get("name"),
                         "type": s.get("type"),
                         "rule": s.get("conditions")})
    return {"campaign_id": str(cid), "campaign_name": camp.get("name"),
            "fields": found, "context": pick(CONTEXT_KEYS),
            "segments": segments,
            # Customer.io calls these "manual" segments; the engine speaks in
            # ESP-neutral terms, so they travel as static lists.
            "static_lists": [s["id"] for s in segments
                             if s.get("type") == "manual"],
            # Every referenced segment has to have been read. A campaign that
            # names three segments and resolved none of them knows no more
            # about its population than one that named none — and `resolved`
            # is what the gate reads to decide it may proceed without asking.
            "resolved": bool(found) and
                        len(segments) == len(camp.get("trigger_segment_ids") or [])}


def get(base, path, key, params=None, soft=False):
    """`soft` reports a failure to the caller instead of ending the run.

    Used for the per-send records, which are an upgrade rather than a
    requirement: a workspace that cannot read them still gets a coarse read,
    provided the output says which one it got.
    """
    url = f"{base}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    # urllib copies a Request's ordinary headers onto the request it makes after
    # a redirect. The check below runs on the response, which is too late: an
    # open redirect would already have been handed the App API key. An
    # unredirected header is sent to this host and no other, so a cross-host
    # redirect fails to authenticate instead of leaking the credential.
    req.add_unredirected_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            # urllib follows redirects silently; a changed host means the
            # region is wrong and the caller should be told, not guessed at.
            if urllib.parse.urlparse(r.geturl()).netloc != \
                    urllib.parse.urlparse(url).netloc:
                print(f"  note: redirected to {r.geturl()} — check --region "
                      f"(the credential was not sent to that host)",
                      file=sys.stderr)
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        if soft:
            raise MessagesUnavailable(f"HTTP {e.code} on {path} — {body[:120]}")
        if e.code in (301, 302, 308):
            raise SystemExit(
                f"HTTP {e.code} on {path} — this is almost always the wrong "
                f"region. Try --region eu (or us).")
        raise SystemExit(f"HTTP {e.code} on {path}\n{body}")


class MessagesUnavailable(Exception):
    """The per-send records cannot be read on these credentials.

    Distinct from a paging failure. Unavailable means fall back to the coarse
    period arrays and label the result; a paging failure means the numbers are
    wrong and must not be scored.
    """


def day_of(ts):
    """UTC calendar day of a unix timestamp. Windows are reported in UTC."""
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def send_ts(msg):
    """When this message was sent, by the record's own timestamps."""
    ts = (msg.get("metrics") or {}).get("sent")
    return ts if isinstance(ts, int) else msg.get("created")


def fetch_arm_messages(fetch_page, action_id, start_ts=None, end_ts=None,
                       page_size=PAGE_CAP, max_messages=MAX_MESSAGES):
    """Every message an action sent, paged to completion.

    Records come back NEWEST FIRST, so a page that hits the cap is truncated at
    the OLD end — reading page one as the series undercounts the start of the
    flight, which is exactly where a challenger arm's life begins. Paging to
    exhaustion is not an optimisation here, it is the difference between an
    8-day flight and a month-long one.

    Two failure modes are checked rather than trusted. A cursor that does not
    advance re-serves page one forever, and the loop below would happily append
    the same thousand records until the cap: that is caught and the window is
    walked by timestamp instead. Silent truncation is refused outright —
    `max_messages` raises, because a fetch that stops early returns numbers that
    look complete.
    """
    base = {"type": "email", "action_id": str(action_id), "limit": page_size}
    if start_ts is not None:
        base["start_ts"] = int(start_ts)
    if end_ts is not None:
        base["end_ts"] = int(end_ts)

    out, seen, cursor, pages = [], set(), None, 0
    while True:
        params = dict(base)
        if cursor:
            params["start"] = cursor
        body = fetch_page(params)
        msgs = body.get("messages") or []
        if not msgs:
            break
        ids = {m.get("id") for m in msgs}
        if ids and ids <= seen:
            # The cursor stalled. Walking the window backwards by timestamp
            # reaches the same records without it.
            return _walk_by_timestamp(fetch_page, base, max_messages)
        for m in msgs:
            if m.get("id") not in seen:
                seen.add(m.get("id"))
                out.append(m)
        pages += 1
        if len(out) > max_messages:
            raise SystemExit(
                f"action {action_id}: over {max_messages:,} messages and still "
                f"paging. Narrow the window with --since/--until — reading a "
                f"whole arm's life to score one flight is rarely what is "
                f"wanted, and stopping early here would hand back numbers that "
                f"look complete.")
        nxt = body.get("next")
        if not nxt or nxt == cursor:
            if nxt == cursor and len(msgs) == page_size:
                return _walk_by_timestamp(fetch_page, base, max_messages)
            break
        cursor = nxt
    return out


def _walk_by_timestamp(fetch_page, base, max_messages):
    """Cursor-free paging: step the window back past the oldest record seen.

    Only reached when the cursor stalls. It has one blind spot of its own, and
    it is loud rather than silent: a batch send can put more than a page of
    messages into a single second, and no window narrower than a second exists
    to split those with. That stalls too, and raises.
    """
    limit = base.get("limit", PAGE_CAP)
    out, seen, edge = [], set(), base.get("end_ts")
    while True:
        params = dict(base)
        if edge is not None:
            params["end_ts"] = int(edge)
        msgs = fetch_page(params).get("messages") or []
        if not msgs:
            break
        fresh = [m for m in msgs if m.get("id") not in seen]
        for m in fresh:
            seen.add(m.get("id"))
            out.append(m)
        if len(out) > max_messages:
            raise SystemExit(
                f"over {max_messages:,} messages while walking the window back. "
                f"Narrow it with --since/--until.")
        # A page below the cap is the oldest end of the flight. A page AT the
        # cap is a truncation, and the loop has to be able to step past it —
        # "no new records" there means stuck, not finished, and the difference
        # between those two is the whole reason this gate exists.
        if len(msgs) < limit:
            break
        stamps = [send_ts(m) for m in msgs if isinstance(send_ts(m), int)]
        oldest = min(stamps) if stamps else None
        if oldest is None or not fresh or (edge is not None and oldest >= edge):
            raise SystemExit(
                f"cannot page past "
                f"{day_of(oldest) if oldest else 'the current window'}: a full "
                f"page of messages shares one timestamp and the cursor is not "
                f"advancing, so there is no window left to split. The counts "
                f"would be short by an unknown amount — do not score this. "
                f"Re-run with --windows periods for a labelled coarse read.")
        edge = oldest
    return out


def daily_counts(messages, fields=MESSAGE_FIELDS):
    """Per-send records folded into a per-day series, keyed by SEND day.

    Engagement is attributed to the day the message went out, not the day
    someone clicked. That is what makes the numerator belong to the denominator
    beside it: a click three days later still belongs to the send that earned
    it, and moving it to its own day would score it against a different day's
    volume.
    """
    per_day = {f: {} for f in fields}
    sends, first, last = {}, None, None
    for m in messages:
        ts = send_ts(m)
        if not isinstance(ts, int):
            continue
        d = day_of(ts)
        sends[d] = sends.get(d, 0) + 1
        first = ts if first is None or ts < first else first
        last = ts if last is None or ts > last else last
        metrics = m.get("metrics") or {}
        for f in fields:
            if metrics.get(f) is not None:
                per_day[f][d] = per_day[f].get(d, 0) + 1
    return {"per_day": per_day, "sends_per_day": sends, "sent": len(messages),
            "first_send": first, "last_send": last,
            "totals": {f: sum(per_day[f].values()) for f in fields}}


def reconcile(derived, lifetime, fields=("delivered", "clicked", "opened"),
              tolerance=0.01):
    """Do the counted records add up to what the metrics endpoint reports?

    This is the gate that catches a truncated pull, and it is the only thing
    standing between a half-read flight and a confident verdict — a page cap
    that swallows the first two weeks of an arm does not look like an error, it
    looks like a shorter test.

    A shortfall is a hard failure: records are missing. An excess is reported
    but allowed, because the metrics series reaches back a fixed number of
    buckets and an arm older than that has real sends the series no longer
    covers.
    """
    short, over = [], []
    for f in fields:
        want = lifetime.get(f)
        got = derived["totals"].get(f)
        if not isinstance(want, int) or want <= 0 or got is None:
            continue
        allowed = max(2, want * tolerance)
        if want - got > allowed:
            short.append(f"{f}: counted {got:,} of {want:,} reported "
                         f"({(want - got) / want:.1%} missing)")
        elif got - want > allowed:
            over.append(f"{f}: counted {got:,} against {want:,} reported")
    return {"short": short, "over": over, "ok": not short}


def shared_axis(per_arm_days):
    """One date axis for every arm, so index i means the same day for all.

    Two arms aligned only by position are not aligned at all: an arm that
    started a week later would have its first day compared against the other's
    first day, and the overlap scan would find a window that never existed.
    """
    days = set()
    for d in per_arm_days:
        days |= set(d)
    return sorted(days)


def on_axis(counts_by_day, axis):
    return [counts_by_day.get(d, 0) for d in axis]


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config")
    ap.add_argument("--region", choices=sorted(HOSTS))
    ap.add_argument("--key-file")
    ap.add_argument("--metric", default="clicked",
                    help="decision metric (default: raw clicks, machine and "
                         "human alike)")
    # An unsupported value is not an error at the API: it returns every
    # field null and every total zero, which reads exactly like a campaign
    # that never sent. Reject the typo here, where it is still visible.
    ap.add_argument("--period", default="months",
                    choices=("months", "weeks", "days"))
    ap.add_argument("--steps", type=int, default=12)
    ap.add_argument("--exclude", help="regex of arm names to drop "
                                      f"(default {DEFAULT_EXCLUDE!r})")
    ap.add_argument("--include-rs2no", action="store_true")
    ap.add_argument("--windows", choices=("auto", "messages", "periods"),
                    default="auto",
                    help="how send windows are established: auto (per-send "
                         "records, falling back to period arrays and saying "
                         "so), messages (require them), periods (coarse only)")
    ap.add_argument("--since", type=int, metavar="UNIX_TS",
                    help="only read messages sent at or after this timestamp")
    ap.add_argument("--until", type=int, metavar="UNIX_TS",
                    help="only read messages sent at or before this timestamp")
    args = ap.parse_args()

    cfg = Config.load(args.config)
    region = cfg.get("region", args.region, env="CIO_REGION", default="us")
    base = HOSTS[region]
    key = read_key(args.key_file or cfg.get("key_file"), "CIO_APP_API_KEY",
                   "Customer.io App API key")

    pattern = None
    if not args.include_rs2no:
        pattern = re.compile(
            args.exclude or cfg.get("exclude", default=DEFAULT_EXCLUDE), re.I)

    cid = args.campaign
    camp = get(base, f"/campaigns/{cid}", key).get("campaign", {})
    cohort = cohort_of(camp, cid, base, key)
    if cohort["resolved"]:
        print(f"  entry conditions read: {', '.join(sorted(cohort['fields']))}",
              file=sys.stderr)
        for s in cohort["segments"]:
            how = ("rule readable" if s.get("rule") else
                   "manual segment — no rule to read, populated by hand"
                   if s.get("type") == "manual" else "no rule exposed")
            print(f"    segment {s['id']} '{s.get('name')}' [{s.get('type')}]"
                  f" — {how}", file=sys.stderr)
    else:
        print(f"  note: campaign {cid} exposed no entry-condition fields "
              f"(saw: {', '.join(sorted(camp)) or 'nothing'}). Comparing this "
              f"against another campaign will ask you about the cohort.",
              file=sys.stderr)
    actions = get(base, f"/campaigns/{cid}/actions", key).get("actions", [])
    emails = [a for a in actions if a.get("type") == "email"]
    if pattern:
        kept = [a for a in emails if not pattern.search(a.get("name") or "")]
        dropped = [a.get("name") for a in emails if a not in kept]
        if dropped:
            print(f"excluded {len(dropped)} leg(s): {', '.join(dropped)}",
                  file=sys.stderr)
        else:
            # Silence here would read as "there were no resend legs" when it may
            # mean "this workspace names them something else".
            print(f"excluded nothing (pattern {pattern.pattern!r}). If this "
                  f"campaign has resend-to-non-opener legs under another name, "
                  f"pass --exclude with it — pooling them with an initial send "
                  f"compares different denominators.", file=sys.stderr)
        emails = kept
    if not emails:
        raise SystemExit(f"campaign {cid} has no email actions")

    # Per-send records, when they can be read. This is the difference between a
    # window that is asserted and one that is measured — see `--windows`.
    want_messages = args.windows in ("auto", "messages")
    grains, unavailable = {}, None
    if want_messages:
        def page(params):
            return get(base, MESSAGES_PATH, key, params, soft=True)

        try:
            for a in emails:
                msgs = fetch_arm_messages(
                    page, a["id"], start_ts=args.since, end_ts=args.until)
                grains[str(a["id"])] = daily_counts(msgs)
                g = grains[str(a["id"])]
                if g["first_send"]:
                    print(f"  action {a['id']}: {g['sent']:,} message(s), "
                          f"{day_of(g['first_send'])} → "
                          f"{day_of(g['last_send'])}", file=sys.stderr)
                else:
                    print(f"  action {a['id']}: no message records in window",
                          file=sys.stderr)
        except MessagesUnavailable as e:
            unavailable, grains = str(e), {}
            if args.windows == "messages":
                raise SystemExit(
                    f"per-send records requested but unreadable: {e}\n"
                    f"  Re-run with --windows periods to accept a coarse read, "
                    f"which will be labelled as one.")
            print(f"  note: per-send records unavailable ({e}). Falling back to "
                  f"period arrays — the send window will not be verified.",
                  file=sys.stderr)

    stats_arms, copy_arms = [], []
    for a in emails:
        aid = a["id"]
        detail = get(base, f"/campaigns/{cid}/actions/{aid}", key).get("action", {})
        m = get(base, f"/campaigns/{cid}/actions/{aid}/metrics", key,
                {"period": args.period, "steps": args.steps}).get("metric", {})

        # The public App API returns only `series`; the internal API also
        # carries `total_*`. Sum the series so both shapes work.
        series = m.get("series", m)

        # series/m are bound as defaults, not closed over. Both helpers are only
        # called inside this iteration today, so late binding is harmless — but
        # moving one call outside the loop would silently read the last arm's
        # metrics into every arm, and nothing would fail.
        def arr(name, series=series):
            v = series.get(name)
            return v if isinstance(v, list) else []

        def total(name, m=m):
            t = m.get(f"total_{name}")
            return t if isinstance(t, int) else sum(arr(name))

        if not total("sent"):
            print(f"  note: action {aid} '{a.get('name')}' has 0 sends",
                  file=sys.stderr)

        stats_arms.append({
            "id": str(aid), "name": a.get("name"),
            "subject": detail.get("subject"),
            "cohort": cohort,
            "delivered": total("delivered"),
            # Raw counts score the test; the human/machine split is a diagnostic.
            "opened": total("opened"),
            "clicked": total("clicked"),
            "human_opened": total("human_opened"),
            "human_clicked": total("human_clicked"),
            "prefetch_opened": total("prefetch_opened"),
            "converted": total("converted"),
            "unsubscribed": total("unsubscribed"),
            "spammed": total("spammed"),
            "bounced": total("bounced"),
            "periods": {k: arr(k) for k in
                        ("delivered", "opened", "clicked", "human_opened",
                         "human_clicked", "converted")},
        })
        copy_arms.append({
            "id": str(aid), "name": a.get("name"),
            "subject": detail.get("subject"),
            "preheader": detail.get("preheader") or detail.get("preheader_text"),
            "body_html": detail.get("body"),
        })

    narrowed = args.since is not None or args.until is not None
    if grains and any(g["first_send"] for g in grains.values()):
        # The reconciliation gate. A pull that quietly stopped early produces a
        # shorter flight, a smaller denominator and a cleaner-looking result —
        # nothing about it reads as an error, which is why it is checked here
        # rather than trusted. Skipped only when the operator narrowed the
        # window on purpose, where a shortfall against lifetime totals is the
        # expected answer rather than a fault.
        failures = []
        for arm in stats_arms:
            g = grains.get(arm["id"])
            if not g or not narrowed:
                rec = reconcile(g, arm) if g else {"short": [], "over": [],
                                                   "ok": True}
                for note in rec["over"]:
                    print(f"  note: {arm['id']} {note} — the metric series "
                          f"reaches back a fixed number of buckets, so an arm "
                          f"older than that has sends it no longer covers.",
                          file=sys.stderr)
                if not rec["ok"]:
                    failures.append(f"  {arm['id']} '{arm['name']}': " +
                                    "; ".join(rec["short"]))
        if failures:
            raise SystemExit(
                "per-send records do not reconcile with the reported totals:\n"
                + "\n".join(failures) +
                "\n  Records are missing, which means the paging is wrong — and "
                "a short pull does not look wrong, it looks like a shorter "
                "test. Refusing to score it. Re-run with --windows periods for "
                "a labelled coarse read, or narrow the window with "
                "--since/--until so the totals are meant to differ.")

        axis = shared_axis([g["sends_per_day"] for g in grains.values()])
        for arm in stats_arms:
            g = grains.get(arm["id"])
            if not g or g["first_send"] is None:
                # No sends to measure. day_of(None) is time.gmtime(None), which
                # is now — so this arm would carry today as both its first and
                # last send, marked verified, and appear to overlap every arm
                # that really did send. Say it is unverified and let the engine
                # fall back to the coarse read for the whole set.
                arm["period_resolution"] = "month"
                arm["window"] = {
                    "verified": False, "source": "per-send records",
                    "messages": 0,
                    "why": "no message records for this arm" +
                           (" in the requested window" if narrowed else "")}
                print(f"  note: no sends recorded for arm {arm['id']} "
                      f"'{arm['name']}'"
                      + (" in the requested window" if narrowed else "") +
                      " — its send window is unverified, so the read is coarse "
                      "for every arm.", file=sys.stderr)
                continue
            arm["periods"] = {k: on_axis(g["per_day"].get(k, {}), axis)
                              for k in ("delivered", "opened", "clicked",
                                        "human_opened", "human_clicked",
                                        "converted")}
            arm["periods"]["sent"] = on_axis(g["sends_per_day"], axis)
            arm["period_dates"] = axis
            arm["period_resolution"] = "day"
            arm["window"] = {
                "first_send": g["first_send"], "last_send": g["last_send"],
                "first_send_date": day_of(g["first_send"]),
                "last_send_date": day_of(g["last_send"]),
                "days": len(g["sends_per_day"]),
                "messages": g["sent"],
                "source": "per-send records", "verified": True,
                "scope": "requested window" if narrowed else "arm lifetime",
            }
            if narrowed:
                # Totals must describe the same window as the series beside
                # them. Lifetime totals against a windowed series is the
                # mismatch this whole path exists to remove.
                arm["sent"] = g["sent"]
                for f in MESSAGE_FIELDS:
                    if f in arm:
                        arm[f] = g["totals"].get(f, 0)
    else:
        if narrowed:
            raise SystemExit(
                "--since/--until asked for a bounded window, and no message "
                "records came back for it" +
                (f" ({unavailable})" if unavailable else "") +
                ".\n  The only numbers left are lifetime totals and lifetime "
                "period arrays, which describe a different span than the one "
                "requested — scoring them would answer a question nobody "
                "asked, and nothing in the output would say so. Refusing.\n"
                "  Drop --since/--until for a labelled coarse read of the "
                "arm's whole life, or widen the window.")
        why = unavailable or ("no message records were returned for any arm"
                              if want_messages else
                              "--windows periods was requested")
        for arm in stats_arms:
            arm["period_resolution"] = "month"
            arm["window"] = {"verified": False, "source": "period arrays",
                             "why": why}
        print(f"  send windows NOT verified at send resolution ({why}). The "
              f"engine will label the read coarse.", file=sys.stderr)

    write_payloads(args.out, f"{camp.get('name')} (campaign {cid})",
                   args.metric, stats_arms, copy_arms)


if __name__ == "__main__":
    main()
