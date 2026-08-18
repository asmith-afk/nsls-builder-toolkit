#!/usr/bin/env python3
"""Shared config + payload plumbing for the ESP fetchers.

The statistics and diff engines are ESP-agnostic by construction: they read
plain JSON and never learn where it came from. Everything provider-specific
lives in a fetcher, and every fetcher writes the same two files:

    <prefix>.stats.json   arms with counts + per-period arrays  -> abstats.py
    <prefix>.copy.json    arms with subject/preheader/body      -> abdiff.py

Adding an ESP means writing one fetcher. It means changing nothing else.

Config resolution, first hit wins:
    1. explicit CLI flag
    2. --config <file>, or ./esp.json next to the working directory
    3. environment variable
    4. built-in default

A deployment that only ever talks to one workspace should put that workspace
and region in an esp.json and stop passing flags. A consultant working across
clients should pass --config per client and keep nothing baked in.
"""

import json
import os
import re
import sys

DEFAULT_CONFIG_NAME = "esp.json"


def utf8_stdout():
    """Make stdout carry the bytes the emails actually contain.

    Opening every file as UTF-8 is only half the job. On Windows the console
    streams default to cp1252, so printing a diff of an email that contains an
    emoji bullet, a curly quote or an em dash raises UnicodeEncodeError and
    kills the run at the point where the report was about to be useful.
    Marketing email is full of exactly those characters, so this is a certainty
    rather than an edge case. Reconfigure rather than replace the stream, and
    fall back to backslash-escaping instead of dying if a console truly cannot
    represent a character.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass  # not a real stream (piped, wrapped, or already replaced)


class Config:
    def __init__(self, data=None, path=None):
        self.data = data or {}
        self.path = path

    @classmethod
    def load(cls, explicit_path=None):
        path = explicit_path or os.environ.get("ESP_CONFIG")
        if not path and os.path.exists(DEFAULT_CONFIG_NAME):
            path = DEFAULT_CONFIG_NAME
        if not path:
            return cls()
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh), path)

    def get(self, key, cli_value=None, env=None, default=None):
        if cli_value is not None:
            return cli_value
        if key in self.data and self.data[key] is not None:
            return self.data[key]
        if env and os.environ.get(env):
            return os.environ[env]
        return default


def read_key(key_file=None, env_var=None, label="API key"):
    """Pull a credential from a file or the environment. Never from config.

    esp.json is meant to be shared and committed — that is the whole point of
    it — so a key put there travels with it. Keys come from a file outside the
    repo or from an environment variable instead. This function only reads;
    nothing in this skill ever writes a credential anywhere.
    """
    if key_file:
        with open(key_file, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        m = re.search(r"(?:App\s*API|API\s*key|token)\s*:?\s*([A-Za-z0-9._\-]{16,})",
                      text, re.I)
        if m:
            return m.group(1)
        # A file containing nothing but the key is also fine.
        stripped = text.strip()
        if re.fullmatch(r"[A-Za-z0-9._\-]{16,}", stripped):
            return stripped
        raise SystemExit(
            f"no {label} found in {key_file}. Two shapes are read: a file "
            f"containing only the key, or a line like 'API key: <value>' "
            f"('App API' and 'token' are also recognised). Otherwise set the "
            f"environment variable instead.")
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    raise SystemExit(f"set {env_var} or pass --key-file for the {label}")


def write_payloads(prefix, test_name, primary_metric, stats_arms, copy_arms,
                   mode=None):
    stats = {"test": test_name, "primary_metric": primary_metric,
             "arms": stats_arms}
    if mode:
        stats["mode"] = mode
    with open(f"{prefix}.stats.json", "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2)
    with open(f"{prefix}.copy.json", "w", encoding="utf-8") as fh:
        json.dump({"arms": copy_arms}, fh, indent=2)
    print(f"{test_name}: {len(stats_arms)} arm(s) -> "
          f"{prefix}.stats.json, {prefix}.copy.json")
    for a in stats_arms:
        print(f"  {a['id']}  {a['name']}  delivered={a.get('delivered', 0)}")


def blank_arm(arm_id, name, subject=None):
    return {
        "id": str(arm_id), "name": name, "subject": subject,
        "delivered": 0, "opened": 0, "clicked": 0,
        "human_opened": 0, "human_clicked": 0,
        "converted": 0, "unsubscribed": 0, "spammed": 0, "bounced": 0,
        "periods": {},
    }
