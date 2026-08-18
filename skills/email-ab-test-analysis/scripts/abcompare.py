#!/usr/bin/env python3
"""Build a cross-test payload by picking one arm out of each of several fetches.

    python abcompare.py --out cross testA:101 testB:202
    python abcompare.py --out cross testA:101 testB:202 --labels "Q1 control,Q2 control"

Each argument is <prefix>:<arm-id>, where <prefix> is what you passed to a
fetcher's --out. Writes <out>.stats.json (marked cross_test, so abstats.py
suppresses the split-imbalance check and reports the read as observational)
and <out>.copy.json.

Comparing the winners of two separate tests is the most common real question —
"why did this quarter's email do worse than last quarter's" — and the most
common place a false causal claim gets made. The point of marking the payload
is that the verdict language downgrades automatically rather than depending on
whoever writes the summary remembering to hedge.
"""

import argparse
import json
import sys

from espconfig import utf8_stdout


def load(prefix):
    try:
        with open(f"{prefix}.stats.json", encoding="utf-8") as fh:
            stats = json.load(fh)
        with open(f"{prefix}.copy.json", encoding="utf-8") as fh:
            copy = json.load(fh)
    except FileNotFoundError as e:
        raise SystemExit(f"{e.filename} not found — run a fetcher with "
                         f"--out {prefix} first")
    return stats, copy


def pick(arms, arm_id, prefix, kind):
    for a in arms:
        if str(a.get("id")) == str(arm_id):
            return dict(a)
    ids = ", ".join(str(a.get("id")) for a in arms)
    raise SystemExit(f"arm {arm_id} not in {prefix}.{kind}.json (has: {ids})")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+", metavar="PREFIX:ARM_ID")
    ap.add_argument("--out", required=True)
    ap.add_argument("--metric")
    ap.add_argument("--labels", help="comma-separated display names, in order")
    args = ap.parse_args()

    if len(args.specs) < 2:
        ap.error("need at least two PREFIX:ARM_ID arguments")

    labels = [s.strip() for s in args.labels.split(",")] if args.labels else []
    metric, stats_arms, copy_arms, sources = args.metric, [], [], []

    for i, spec in enumerate(args.specs):
        if ":" not in spec:
            ap.error(f"{spec!r} must look like PREFIX:ARM_ID")
        prefix, arm_id = spec.rsplit(":", 1)
        stats, copy = load(prefix)
        source_metric = stats.get("primary_metric", "clicked")
        if args.metric is None:
            if metric is None:
                metric = source_metric
            elif metric != source_metric:
                ap.error(
                    f"{prefix} was scored on {source_metric!r} but an earlier "
                    f"source was scored on {metric!r}. Composing them would "
                    f"label the output with one metric and score arms that "
                    f"carry the other as zero — a false comparison that never "
                    f"looks like a failure. "
                    f"Re-fetch on one metric, or pass --metric to name the one "
                    f"every arm carries.")
        sa = pick(stats["arms"], arm_id, prefix, "stats")
        ca = pick(copy["arms"], arm_id, prefix, "copy")
        if i < len(labels) and labels[i]:
            sa["name"] = ca["name"] = labels[i]
        else:
            sa["name"] = f"{sa.get('name')} — {stats.get('test', prefix)}"
        stats_arms.append(sa)
        copy_arms.append(ca)
        sources.append(stats.get("test", prefix))

    name = "CROSS-TEST: " + " vs ".join(sources)
    with open(f"{args.out}.stats.json", "w", encoding="utf-8") as fh:
        json.dump({"test": name, "primary_metric": metric,
                   "mode": "cross_test", "arms": stats_arms}, fh, indent=2)
    with open(f"{args.out}.copy.json", "w", encoding="utf-8") as fh:
        json.dump({"arms": copy_arms}, fh, indent=2)

    print(f"{name}\n  -> {args.out}.stats.json, {args.out}.copy.json")
    for a in stats_arms:
        print(f"  {a['id']}  {a['name']}")
    print("\nThese arms were never randomised against each other. abstats.py "
          "will report the result as observed, not caused.", file=sys.stderr)


if __name__ == "__main__":
    main()
