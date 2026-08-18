#!/usr/bin/env python3
"""SKILL.md is the only thing the model reads when this skill fires.

The scripts can be perfect and the read still comes out wrong, because the
judgement lives in the prose: which metric decides, what refuses attribution,
when a verdict is withheld. These tests pin the claims that would silently
diverge from the code as either side is edited, plus the spec constraints the
toolkit's skill-creation cascade requires.

Hermetic: reads two files, runs nothing.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / "SKILL.md").read_text(encoding="utf-8")
FRONTMATTER = TEXT.split("---")[1] if TEXT.startswith("---") else ""

# Two SKILL.md variants ship on purpose: the toolkit build written to the
# skill-creation rubric, and the prose build. Everything else in this file
# applies to both, so the rubric check is the only thing keyed to the variant.
RUBRIC_BUILD = "## Quick Start" in TEXT

# Prose assertions must run against this, not TEXT. In the source a phrase is
# routinely broken by a line wrap or split by markdown emphasis, so a literal
# search over TEXT fails on wording that is actually present and correct.
FLAT = re.sub(r"\s+", " ", re.sub(r"[*_`]+", "", TEXT))

# The same flattening, minus the underscore. Stripping `_` is right for prose
# and silently fatal for identifiers: it turns `human_clicked` in the document
# into `humanclicked`, so a search for the field name matches nothing and an
# assertion that loops over the matches passes by never running. Identifier
# assertions use this and are guarded by the vacuity test below.
FLAT_IDS = re.sub(r"\s+", " ", re.sub(r"[*`]+", "", TEXT))


# --- spec compliance (Phase 3 of the cascade) -------------------------------

def test_frontmatter_has_a_valid_name():
    name = re.search(r"^name:\s*(.+)$", FRONTMATTER, re.M).group(1).strip()
    assert re.fullmatch(r"[a-z0-9-]{1,64}", name), name


def test_the_description_captures_when_to_invoke_not_how_to_use():
    """Claude shortcuts a workflow it can read in the description."""
    desc = re.search(r"description: >-\n(.*?)(?=\n[a-z-]+:|\Z)",
                     FRONTMATTER, re.S).group(1)
    desc = " ".join(l.strip() for l in desc.splitlines()).strip()
    assert 0 < len(desc) <= 1024, len(desc)
    # Must START with the trigger, not merely contain one. A description that
    # opens by summarising the workflow gives the reader somewhere to stop: the
    # summary gets followed and the skill goes unread. One build shipped for a
    # week opening "Read an email A/B test end to end: pull... join... decide",
    # and this assertion passed it because "use when" appeared in sentence four.
    assert desc.lower().startswith("use when"), desc[:80]
    assert not re.search(r"\bstep 1\b|\bfirst,? run\b", desc, re.I)


def test_the_file_stays_under_the_line_budget():
    assert len(TEXT.splitlines()) < 500


def test_headings_are_markdown_not_xml():
    body = re.sub(r"```.*?```", "", TEXT, flags=re.S)
    assert not re.findall(r"^\s*<[a-z_]+>\s*$", body, re.M)


def test_no_second_person_drift():
    body = re.sub(r"```.*?```", "", TEXT, flags=re.S)
    hits = [l for l in body.splitlines() if re.search(r"\b(you|your)\b", l, re.I)]
    assert not hits, hits[:3]


@pytest.mark.skipif(not RUBRIC_BUILD, reason="prose build, not the rubric build")
def test_the_rubric_sections_are_all_present():
    for heading in ("## Safety", "## Purpose", "## Quick Start",
                    "## Diagnostic loop", "## Output guidelines",
                    "## Rationalization table", "## Red Flags",
                    "## Where this sits"):
        assert heading in TEXT, f"missing {heading}"


# --- the doc must not contradict the engine ---------------------------------

def test_every_script_it_names_exists():
    for rel in set(re.findall(r"scripts/([a-z_]+\.py)", TEXT)):
        assert (ROOT / "scripts" / rel).exists(), rel


def test_every_shipped_script_is_listed_in_the_files_section():
    shipped = {p.name for p in (ROOT / "scripts").glob("*.py")}
    listed = set(re.findall(r"scripts/([a-z_]+\.py)", TEXT))
    assert shipped <= listed, f"undocumented: {shipped - listed}"


def test_the_identifier_search_is_not_vacuous():
    """The guard on the guard.

    `FLAT` strips underscores, so the field-name assertion below spent its whole
    life iterating over an empty match list and passing. A loop-shaped assertion
    that can silently have nothing to loop over is not an assertion, so pin the
    thing that made it empty.
    """
    assert "human_clicked" not in FLAT, \
        "FLAT is for prose; it eats underscores"
    assert "human_clicked" in FLAT_IDS, \
        "FLAT_IDS must preserve field names, or every check using it is vacuous"


def test_it_states_that_raw_engagement_is_what_gets_scored():
    """The engine defaults to `clicked`; the prose must not prescribe human.

    Three contexts are legitimate: the documented fallback when no raw count was
    supplied, the human/machine split read as a diagnostic, and the rescore the
    engine calls for when a raw-click win is not corroborated by human clicks —
    which is a machine artefact on changed links, not a result. Anything else is
    the prose drifting into prescribing the human-only metric.
    """
    assert re.search(r"raw clicks", FLAT, re.I)
    hits = list(re.finditer(r"human_clicked", FLAT_IDS))
    assert hits, "the fallback metric is never named"
    for m in hits:
        near = FLAT_IDS[max(0, m.start() - 300):m.end() + 300]
        assert re.search(r"fall back|only when|absent|diagnostic|machine",
                         near, re.I), (
            "human_clicked may appear as the documented fallback, as a "
            "diagnostic, or as the rescore for a machine-click artefact — "
            "never as the metric to score on by default")


def test_it_documents_the_cohort_gate_as_withholding_a_verdict():
    assert "cohort" in TEXT.lower()
    assert "--cohort-same" in TEXT and "--cohort-differs" in TEXT
    assert re.search(r"withhold", TEXT, re.I)


def test_it_documents_the_pre_shift_rescore_and_not_merely_a_warning():
    """The engine narrows the window on a lopsided split; prose that only says
    "warns" understates what runs and is how the two drifted apart before."""
    assert re.search(r"rescor", TEXT, re.I), "the rescore has to be named"
    assert re.search(r"pre-shift|before the shift", TEXT, re.I)
    assert re.search(r"no per-period|without per-period|cannot locate", TEXT, re.I), (
        "the case where the rescore CANNOT run must be stated, or the doc "
        "promises a check that did not happen")


def test_it_does_not_claim_a_series_can_prove_arms_were_never_randomised():
    """The engine deliberately stopped asserting this; the prose must not keep
    asserting it. An uneven first period can mean a designed uneven split, or a
    series too coarse to hold the balanced stretch. Only the branch config and
    the send timestamps settle it, and this claim being wrong inverts a real
    result into a discarded one."""
    # A phrase blacklist cannot work here: the corrected wording contains the
    # claim inside its own denial. Check proximity instead — wherever an uneven
    # first period is discussed, the disclaimer must sit with it.
    for m in re.finditer(r"uneven in the first period|lopsided from the first",
                         FLAT, re.I):
        near = FLAT[max(0, m.start() - 200):m.end() + 500]
        assert re.search(r"not conclude|too coarse", near, re.I), (
            "an uneven first period is not evidence the arms were never "
            "randomised; the passage must say so where it says it")


def test_it_instructs_rebuilding_the_window_rather_than_observing_that_it_helps():
    """The doc already said "a period array is a summary, not the record" while
    the code went on scoring the arrays, and two wrong verdicts shipped anyway.
    An observation the reader is free to agree with does not change what gets
    run; these are the four claims that have to survive as instructions."""
    assert re.search(r"rebuild the window from per-send records", FLAT, re.I), (
        "the rebuild has to be named as the step, not implied")
    assert re.search(r"required[^.]{0,24}not an improvement", FLAT, re.I), (
        "stated as optional, it will be skipped exactly when it matters")
    assert re.search(r"shared bucket is not an overlap", FLAT, re.I), (
        "the phantom-overlap failure: a shared calendar bucket read as "
        "concurrency must be refused in the prose, not only in the engine")
    assert re.search(r"newest.first", FLAT, re.I) and \
        re.search(r"reconcile against the reported totals", FLAT, re.I), (
        "both silent-truncation traps have to be stated: the page order that "
        "loses the start of a flight, and the gate that catches it")


def test_it_never_promises_a_write_to_the_esp():
    assert "read-only" in TEXT.lower()
    assert "POST /actions/{id}/winner" in TEXT, (
        "the one dangerous endpoint has to be named to be refused")


def test_the_reference_file_it_points_at_exists():
    for rel in set(re.findall(r"reference/([a-z0-9-]+\.md)", TEXT)):
        assert (ROOT / "reference" / rel).exists(), rel


def skill_files():
    """Every shipped file. Not just SKILL.md — that scope was the bug.

    A neutrality check that reads only the prose passed clean while the test
    fixtures asserted on shipped-looking CTA copy for a week.
    """
    skip = {"__pycache__", ".pytest_cache", ".git"}
    me = Path(__file__).resolve()
    return [p for p in ROOT.rglob("*")
            if p.is_file() and p.suffix in {".md", ".py", ".json"}
            and not skip & set(p.parts)
            # This file holds the pattern table, so it necessarily contains
            # every string it forbids. A linter cannot lint its own rules.
            and p.resolve() != me]


def test_it_carries_no_client_identifiers():
    """This ships in a public repo and is meant to be forked.

    Don't extend this by matching against real copy — a banned-phrases list
    puts the real subject lines in the repo permanently.

    Stripping the identifying details out of a real result isn't enough
    either. The scenario is the fingerprint, and an example modeled on a read
    this skill already produced points the next run at re-finding it.
    """
    for path in skill_files():
        text = path.read_text(encoding="utf-8")
        for pattern in (r"\b\d{6}\b", r"campaign \d+", r"action \d{3,}"):
            assert not re.search(pattern, text), f"{path.name}: {pattern}"


def test_illustrative_numbers_are_round():
    """An unrounded count reads as a real send volume whether or not it was one,
    and a model that copies it writes another number that reads real. A
    placeholder ends in zeros so nobody can mistake it for a measurement.
    """
    for path in skill_files():
        for n in re.findall(r"\b\d{1,3},\d{3}\b", path.read_text(encoding="utf-8")):
            assert n.endswith("00"), f"{path.name}: {n} does not read as a placeholder"


def test_the_quick_start_can_actually_be_run_from_where_it_says_to_run_it():
    """The block `cd`s to a working directory outside the repo, and the scripts
    live beside this file. Invoked by a bare relative path they are all
    file-not-found — the first command a reader types, failing."""
    block = re.search(r"```bash\n(.*?)```", TEXT, re.S).group(1)
    assert re.search(r"^\s*cd ", block, re.M), "the cd is what makes this matter"
    for line in block.splitlines():
        if "scripts/" in line and "#" not in line.split("scripts/")[0]:
            assert "$SKILL_DIR" in line or "SKILL_DIR" in line, (
                f"script invoked by a path relative to the working directory: "
                f"{line.strip()}")
