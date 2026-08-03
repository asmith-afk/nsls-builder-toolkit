#!/usr/bin/env python3.12
"""SKILL.md is the only thing the model reads when `/receipts` fires.

A SKILL.md is prompt content, not an executable command definition. If it
merely *describes* the workflow, invoking the skill loads prose and nothing
runs — the dry run the docs promise never happens, and the model is left to
paraphrase the documentation as if it were a result. That is this codebase's
recurring failure mode wearing a documentation costume: a run that did nothing
reading as a run that found nothing.

These tests pin the two facts that make the difference:
  1. the file explicitly names the script the model must invoke, and
  2. the setup commands it hands a user actually work on the Python this
     toolkit targets (Homebrew python3.12, which is PEP 668 managed).

Hermetic: reads one file, runs no commands.
"""

import re
from pathlib import Path

SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"
TEXT = SKILL_PATH.read_text()
FRONTMATTER = TEXT.split("---")[1] if TEXT.startswith("---") else ""

RUN_CMD = "python3.12 skills/receipts/scripts/run.py"


def test_skill_md_names_the_script_the_model_must_run():
    assert RUN_CMD in TEXT, (
        "SKILL.md never tells the model to run run.py — invoking /receipts "
        "would load descriptive notes and execute nothing"
    )


def test_skill_md_gives_the_dry_run_and_the_send_invocation():
    assert f"{RUN_CMD} --send" in TEXT, "the --send invocation must be spelled out verbatim"
    # The bare form (dry run) must appear on its own, not only as a prefix of
    # the --send line.
    bare = [ln.strip() for ln in TEXT.splitlines() if ln.strip() == RUN_CMD]
    assert bare, "the bare dry-run invocation must appear as its own command line"


def test_skill_md_maps_since_and_until_to_the_flags():
    exec_section = _section("Execution")
    assert "--since" in exec_section and "--until" in exec_section, (
        "the execution procedure must say how a user's date request becomes "
        "--since/--until: " + exec_section
    )


def test_skill_md_forbids_paraphrasing_the_docs_instead_of_running():
    exec_section = _section("Execution")
    assert "paraphrase" in exec_section.lower(), (
        "the execution procedure must say the model relays the script's real "
        "report rather than paraphrasing this document"
    )


def test_skill_md_has_an_execution_section():
    assert re.search(r"^##+\s+Execution\b", TEXT, re.MULTILINE), (
        "SKILL.md needs an explicit Execution section"
    )


def test_frontmatter_never_disables_model_invocation():
    # disable-model-invocation makes the skill invisible in new sessions.
    assert "disable-model-invocation" not in FRONTMATTER
    assert "disable-model-invocation" not in TEXT


def test_frontmatter_still_declares_name_and_description():
    assert re.search(r"^name:\s*receipts\s*$", FRONTMATTER, re.MULTILINE)
    assert re.search(r"^description:\s*\S", FRONTMATTER, re.MULTILINE)


def test_no_install_step_is_documented_for_this_skill():
    # The Anthropic source is stdlib HTTP now. Leaving a Playwright install in
    # the prerequisites would send every new reader through a browser setup
    # this skill no longer uses — and, worse, imply the browser path still
    # exists to fall back on when a session fails.
    # Checked against the commands the doc actually hands a reader — the
    # fenced blocks — not the prose, which is allowed (and encouraged) to say
    # "there is no pip install step".
    commands = "\n".join(re.findall(r"```(?:bash)?\n(.*?)```", TEXT, re.DOTALL)).lower()
    for dead in ("pip install", "playwright", "chromium"):
        assert dead not in commands, (
            f"{dead!r} is still handed to the reader as a setup command, but "
            f"the browser path was removed:\n{commands}"
        )


def test_set_session_is_documented_as_the_run_py_invocation():
    # `sources/anthropic.py --login` used to be the documented auth command,
    # and it crashed with an ImportError (relative import, no package
    # context) before argument dispatch ever ran — the fix for a dead
    # claude.ai session was unreachable through the instructions telling a
    # user how to fix it. `run.py` is the single documented entry point for
    # everything else this tool does; authentication must be the same way.
    assert f"{RUN_CMD} --set-session" in TEXT, (
        "SKILL.md must document `run.py --set-session` as the way to "
        "authenticate the Anthropic source"
    )
    assert "sources/anthropic.py --login" not in TEXT, (
        "the direct-script form must not be documented as the fix — even "
        "though it also works, run.py is the one form users should be told "
        "to run"
    )


def test_skill_md_says_where_to_get_the_cookie():
    # "Store a session cookie" is not actionable on its own. The exact click
    # path is the whole difference between a 30-second setup and a support
    # question.
    text = TEXT.lower()
    for needle in ("devtools", "application", "cookies", "sessionkey", "value"):
        assert needle in text, f"the cookie instructions must name {needle!r}"


def test_skill_md_treats_the_session_as_a_credential():
    text = TEXT.lower()
    assert "0600" in text or "`0600`" in text, (
        "say the file is 0600 so a reader knows what 'refused' means later"
    )
    assert "~/.claude-receipts-session" in TEXT, "name the file"
    assert "commit" in text, "say it must not be committed"
    assert "expire" in text, (
        "say the session expires periodically — otherwise the first expiry "
        "reads as the skill breaking"
    )


def test_skill_md_documents_the_neon_source_and_its_setup():
    # A source nobody knows exists is a source nobody configures — and an
    # unconfigured source is indistinguishable, in the report, from a vendor
    # with no source at all.
    text = TEXT.lower()
    assert "neon" in text, "the Neon billing source must be documented"
    assert f"{RUN_CMD} --set-neon-key" in TEXT, (
        "SKILL.md must document `run.py --set-neon-key` as the way to "
        "authenticate the Neon source"
    )
    assert "NEON_ORG_ID" in TEXT, "name the org-id variable the source needs"
    assert "~/.claude-receipts-neon-key" in TEXT, "name the credential file"
    assert "NEON_API_KEY" in TEXT, "name the environment-variable alternative"


def test_skill_md_no_longer_claims_neon_has_no_automated_source():
    # The coverage note used to group Neon Tech with the vendors that have
    # neither an email nor a portal API. Half of that is still true (no
    # email); the other half is now false, and a doc that says a working
    # source doesn't exist is worse than no doc.
    coverage = _section("Coverage — the known ceiling, not a defect")
    assert coverage, "the coverage section must still exist"
    # Bullets wrap across source lines, so flatten each one before reading it
    # — and stop at the blank line that ends the list, or the prose after it
    # gets read as part of the final bullet.
    bullets = [" ".join(b.split("\n\n")[0].split()).lower()
               for b in re.split(r"^\s*[-*]\s+", coverage, flags=re.MULTILINE)[1:]]
    assert bullets, coverage
    for b in bullets:
        if "neon" in b:
            assert "no portal api" not in b, (
                "Neon has a portal API now — this bullet says it doesn't: " + b
            )
            assert not ("supabase" in b and "zoom" in b), (
                "Neon must no longer be grouped with the vendors that have no "
                "source at all: " + b
            )
    # And the genuinely uncovered vendors must still be named honestly.
    uncovered = [b for b in bullets if "supabase" in b and "zoom" in b]
    assert uncovered, "Supabase and Zoom must still be named as uncovered: " + coverage


def test_skill_md_states_the_credential_handling_guarantees_plainly():
    # This ships org-wide and every builder runs it with their own live
    # claude.ai session and Neon key. "Where does my credential go" is a
    # question they are entitled to a plain answer to, in the one file the
    # skill actually shows them — and it is a claim they can check, so it has
    # to keep matching what sources/ does.
    section = _section("What happens to your credentials").lower()
    assert section, "SKILL.md must state where credentials live and where they go"

    assert "0600" in section, "say the file mode"
    assert "$home" in section or "home directory" in section, "say where it lives"
    assert "commit" in section, "say it cannot be committed"

    assert "redirect" in section, (
        "the redirect guarantee is the one a reader cannot infer: " + section
    )
    assert "third-party" in section or "third party" in section, section
    for claim in ("report", "log", "ledger"):
        assert claim in section, f"say it never reaches the {claim}: {section}"


def _section(title: str) -> str:
    """Text of the `## <title>` section, up to the next same-or-higher heading."""
    m = re.search(rf"^##+\s+{re.escape(title)}\b(.*?)(?=^##\s|\Z)", TEXT,
                  re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


if __name__ == "__main__":
    print("Running SKILL.md doc tests")
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(); print(f"  ok {n}")
    print("\nAll SKILL.md doc tests passed.")
