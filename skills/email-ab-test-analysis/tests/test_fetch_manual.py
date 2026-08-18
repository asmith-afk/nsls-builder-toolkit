#!/usr/bin/env python3
"""Tests for the credential-free front door — reads and writes temp files only.

This is the path for someone who can see the performance screen and nothing
else, which is most people who run email. Its failure mode is quiet: a column
that does not match an alias becomes a zero, and a zero denominator or a zero
numerator produces a clean, confident, wrong report. Everything below pins the
input handling that stands in front of that.

Hermetic: uses pytest's tmp_path, no network.
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from fetch_manual import build_map, sniff_delimiter, text_to_blocks, to_int


# --- reading the file someone actually has ----------------------------------

def test_a_tab_separated_paste_is_read_as_columns():
    """Copying a table out of an ESP screen yields tabs, not commas."""
    assert sniff_delimiter("Name\tDelivered\tClicks\nA\t10\t1\n") == "\t"


def test_comma_semicolon_and_pipe_are_all_recognised():
    assert sniff_delimiter("a,b,c\n1,2,3") == ","
    assert sniff_delimiter("a;b;c\n1;2;3") == ";"
    assert sniff_delimiter("a|b|c\n1|2|3") == "|"


def test_a_single_column_file_falls_back_to_comma():
    assert sniff_delimiter("Name\nA\n") == ","


# --- mapping columns --------------------------------------------------------

def test_ui_export_headers_map_without_editing():
    m, unused = build_map(["Email Name", "Subject Line", "Emails Delivered",
                           "Opens", "Clicks"], {})
    assert m["name"] == "Email Name" and m["delivered"] == "Emails Delivered"
    assert m["opened"] == "Opens" and m["clicked"] == "Clicks"
    assert unused == []


def test_raw_counts_win_over_human_only_columns():
    m, _ = build_map(["Delivered", "Opens", "Human Opens", "Clicks",
                      "Human Clicks"], {})
    assert m["opened"] == "Opens" and m["human_opened"] == "Human Opens"
    assert m["clicked"] == "Clicks" and m["human_clicked"] == "Human Clicks"


def test_unmatched_columns_are_reported_rather_than_silently_dropped():
    _, unused = build_map(["Delivered", "Clicks", "Some Vendor Column"], {})
    assert unused == ["Some Vendor Column"]


def test_an_override_wins_over_the_aliases():
    m, _ = build_map(["Delivered", "Clicks"], {"clicked": "Delivered"})
    assert m["clicked"] == "Delivered"


def test_thousands_separators_and_junk_do_not_become_zero():
    assert to_int("10,000") == 10000
    assert to_int("2.5%") == 2
    assert to_int("") == 0 and to_int(None) == 0
    assert to_int("not a number") == 0


# --- pasted plain-text bodies -----------------------------------------------

def test_a_pasted_body_becomes_one_block_per_line():
    html = text_to_blocks("First line.\nSecond line.\n")
    assert html.count("<p>") == 2, (
        "without this the whole body is one blob and every edit reports as "
        "one enormous change")


def test_a_bracketed_or_shouting_line_is_treated_as_the_button():
    assert '<a href="#cta">CTA TEXT</a>' in text_to_blocks("[CTA TEXT]")
    assert '<a href="#cta">BUTTON LABEL</a>' in text_to_blocks("BUTTON LABEL")


# --- end to end -------------------------------------------------------------

def run(tmp, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / "fetch_manual.py"),
                           *args], capture_output=True, text=True, cwd=tmp)


def test_a_tab_pasted_table_produces_a_scorable_payload(tmp_path):
    src = tmp_path / "pasted.txt"
    src.write_text("Email Name\tSubject Line\tDelivered\tOpens\tClicks\n"
                   "Control\tSame\t10,000\t3,000\t500\n"
                   "Test\tSame\t10,500\t2,500\t600\n", encoding="utf-8")
    r = run(tmp_path, "--csv", str(src), "--out", "t")
    assert r.returncode == 0, r.stderr
    stats = json.loads((tmp_path / "t.stats.json").read_text(encoding="utf-8"))
    assert stats["primary_metric"] == "clicked"
    assert [a["delivered"] for a in stats["arms"]] == [10000, 10500]
    assert [a["clicked"] for a in stats["arms"]] == [500, 600]


def test_a_missing_clicks_column_stops_the_run_instead_of_scoring_zeroes(tmp_path):
    src = tmp_path / "arms.csv"
    src.write_text("Name,Delivered\nA,1000\nB,1000\n", encoding="utf-8")
    r = run(tmp_path, "--csv", str(src), "--out", "t")
    assert r.returncode != 0
    assert "cannot proceed without" in (r.stdout + r.stderr)


def test_one_row_is_not_a_test(tmp_path):
    src = tmp_path / "arms.csv"
    src.write_text("Name,Delivered,Clicks\nA,1000,20\n", encoding="utf-8")
    r = run(tmp_path, "--csv", str(src), "--out", "t")
    assert r.returncode != 0
    assert "at least two" in (r.stdout + r.stderr)


def test_without_bodies_the_diff_says_unknown_rather_than_unchanged(tmp_path):
    src = tmp_path / "arms.csv"
    src.write_text("Name,Delivered,Clicks\nA,1000,20\nB,1000,25\n",
                   encoding="utf-8")
    r = run(tmp_path, "--csv", str(src), "--out", "t")
    assert "UNKNOWN, not absent" in r.stderr


def test_the_operator_can_state_the_cohort_on_the_credential_free_path(tmp_path):
    """There is no API to interrogate here, so the human supplies it."""
    src = tmp_path / "arms.csv"
    src.write_text("Name,Delivered,Clicks\nA,1000,20\nB,1000,25\n",
                   encoding="utf-8")
    r = run(tmp_path, "--csv", str(src), "--out", "t",
            "--cohort", "cohort description")
    assert r.returncode == 0, r.stderr
    stats = json.loads((tmp_path / "t.stats.json").read_text(encoding="utf-8"))
    assert all(a["cohort"]["fields"]["declared"] == "cohort description"
               for a in stats["arms"])
    assert all(a["cohort"]["resolved"] for a in stats["arms"])
