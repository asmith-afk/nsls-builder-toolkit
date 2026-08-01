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


def test_playwright_install_command_works_on_homebrew_python():
    # `python3.12 -m pip install playwright` fails on Homebrew Python with
    # PEP 668 "externally-managed-environment". Documenting the command that
    # cannot work sends every reader into the same dead end.
    assert "python3.12 -m pip install --user --break-system-packages playwright" in TEXT, (
        "the documented Playwright install must carry the PEP 668 escape flags"
    )
    assert not re.search(r"pip install playwright\b", TEXT), (
        "the bare `pip install playwright` form fails on Homebrew Python and "
        "must not be documented"
    )


def test_playwright_install_names_the_pep668_error_a_reader_will_see():
    assert "externally-managed-environment" in TEXT, (
        "name the exact error text so someone who hits it recognises it"
    )
    assert "PEP 668" in TEXT


def test_playwright_browser_install_step_is_still_documented():
    assert "python3.12 -m playwright install chromium" in TEXT


def test_login_is_documented_as_the_run_py_invocation():
    # `sources/anthropic.py --login` used to be the documented login command,
    # and it crashed with an ImportError (relative import, no package
    # context) before argument dispatch ever ran — the fix for a dead
    # claude.ai session was unreachable through the instructions telling a
    # user how to fix it. `run.py` is the single documented entry point for
    # everything else this tool does; login must be documented the same way.
    assert f"{RUN_CMD} --login" in TEXT, (
        "SKILL.md must document `run.py --login` as the way to authenticate "
        "the Anthropic source"
    )
    assert "sources/anthropic.py --login" not in TEXT, (
        "the direct-script login form must not be documented as the fix — "
        "even though it also works now, run.py --login is the one form "
        "users should be told to run: " + TEXT
    )


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
