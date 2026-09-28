#!/usr/bin/env python3
"""The Windows hook refreshes its own skill pointers, and only its own.

Plain stdlib: `python3 hooks/tests/test_ps1_pointer_marker.py`.

session-start.ps1 overwrites ~/.claude/skills/<name>/SKILL.md only when that file
is its own pointer, so it never clobbers a skill the builder wrote. Two ways that
check has been wrong:

1. It looked for 'local-plugins\\nsls-' (a backslash) while the pointers it writes
   use forward slashes, so it never matched and no pointer was ever refreshed.
2. The obvious fix, 'local-plugins/nsls-', would match any builder skill that
   merely mentions a toolkit path. Personal-toolkit stubs do, to log credit, so
   they would have been overwritten.

The check is now exact: the file must name THIS skill's own path. There is no
PowerShell where these tests usually run, so the predicate is re-created here
from the script's own templates and exercised against real-shaped files; the
static checks pin the script to that predicate. The Windows CI job parses the
script itself.
"""
import re
import sys
from pathlib import Path

PS1 = Path(__file__).resolve().parents[1] / "session-start.ps1"
src = PS1.read_text(encoding="utf-8")
failures = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name} {'' if cond else detail}")
    if not cond:
        failures.append(name)


print("the script is pinned to the exact-ownership predicate")
own = re.search(r'\$ownPath\s*=\s*"([^"]*)"', src)
check("the ownership path is built from this plugin and this skill", bool(own)
      and own.group(1) == "local-plugins/$pluginName/skills/$($skillFolder.Name)/SKILL.md",
      f"({own.group(1) if own else None!r})")
check("an existing file is normalised, then must contain that exact path",
      "if (-not ($existing -replace '\\\\', '/').Contains($ownPath)) { continue }" in src)
check("an empty file cannot throw on the check",
      "$existing = [string](Get-Content $destMd -Raw -Encoding UTF8)" in src)
check("the pointer it writes names that same path",
      '$pointerPath = "~/.claude/$ownPath"' in src)
check("the loose $Marker is gone entirely", "$Marker" not in src)
check("session-start.ps1 is ASCII-only", all(ord(c) < 128 for c in src))


def owned(existing, plugin, skill):
    """The script's predicate, from its own template."""
    path = own.group(1).replace("$pluginName", plugin).replace("$($skillFolder.Name)", skill)
    return path in (existing or "").replace("\\", "/")


print("\nwhat it will and will not overwrite")
if own:
    written = ("---\nname: gws\ndescription: >-\n  Google Workspace\n---\n\n"
               "Read and follow the full skill at "
               "`~/.claude/local-plugins/nsls-builder-toolkit/skills/gws/SKILL.md`.\n")
    check("its own pointer is refreshed", owned(written, "nsls-builder-toolkit", "gws"))

    legacy = ("Read and follow the full skill at "
              "C:\\Users\\x\\.claude\\local-plugins\\nsls-builder-toolkit\\skills\\gws\\SKILL.md\n")
    check("a pointer written with a Windows path is still recognised",
          owned(legacy, "nsls-builder-toolkit", "gws"))

    stub = ("---\nname: my-thing\n---\nWhen done, run\n"
            "bash ~/.claude/local-plugins/nsls-builder-toolkit/hooks/skill-event.sh\n")
    check("a builder skill that mentions a toolkit path is left alone",
          not owned(stub, "nsls-builder-toolkit", "my-thing"))

    other = ("See also ~/.claude/local-plugins/nsls-builder-toolkit/skills/slack/SKILL.md\n")
    check("a file pointing at a DIFFERENT toolkit skill is left alone",
          not owned(other, "nsls-builder-toolkit", "gws"))

    check("an empty file is left alone", not owned("", "nsls-builder-toolkit", "gws"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
