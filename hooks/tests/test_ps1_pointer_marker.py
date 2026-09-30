#!/usr/bin/env python3
"""The Windows scripts refresh their own skill pointers, and only their own.

Plain stdlib: `python3 hooks/tests/test_ps1_pointer_marker.py`.

session-start.ps1 and install.ps1 overwrite ~/.claude/skills/<name>/SKILL.md
only when that file is their own pointer, so they never clobber a skill the
builder wrote. Three ways that check has been wrong:

1. session-start.ps1 looked for 'local-plugins\\nsls-' (a backslash) while the
   pointers it writes use forward slashes, so it never matched and no pointer
   was ever refreshed.
2. The obvious fix, 'local-plugins/nsls-', matches any builder skill that merely
   mentions a toolkit path. Personal-toolkit stubs do, to log credit.
3. Even this skill's exact path is not enough on its own: a builder's own skill
   that credits or links the toolkit skill contains it too (Macroscope, #202).
   install.ps1's looser 'local-plugins[\\/]nsls-builder-toolkit' had the same
   problem.

So ownership is structural: the file must BE a pointer, front matter then one
"Read and follow" line naming this skill's own path. There is no PowerShell
where these tests usually run, so the predicate is rebuilt here from the
script's own pattern literal and exercised against real-shaped files; the
static checks pin both scripts to it. The Windows CI job parses the scripts.
"""
import re
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
PS1 = HOOKS / "session-start.ps1"
INSTALL = HOOKS.parent / "install.ps1"
src = PS1.read_text(encoding="utf-8")
inst = INSTALL.read_text(encoding="utf-8")
failures = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name} {'' if cond else detail}")
    if not cond:
        failures.append(name)


def func_body(text):
    m = re.search(r"function Test-OwnPointer \{.*?\n\}\n", text, re.S)
    return m.group(0) if m else None


print("both scripts are pinned to the exact-pointer predicate")
own = re.search(r'\$ownPath\s*=\s*"([^"]*)"', src)
check("the ownership path is built from this plugin and this skill", bool(own)
      and own.group(1) == "local-plugins/$pluginName/skills/$($skillFolder.Name)/SKILL.md",
      f"({own.group(1) if own else None!r})")
fn = func_body(src)
check("session-start.ps1 defines Test-OwnPointer", bool(fn))
check("install.ps1 carries the identical Test-OwnPointer", fn is not None and func_body(inst) == fn)
check("session-start.ps1 gates the overwrite on it",
      "if (-not (Test-OwnPointer -Text $existing -OwnPath $ownPath)) { continue }" in src)
check("install.ps1 gates the overwrite on it",
      "if (-not (Test-OwnPointer -Text $existing -OwnPath $ownPath)) { continue }" in inst)
check("install.ps1 names this skill's own toolkit path",
      '$ownPath = "local-plugins/nsls-builder-toolkit/skills/$($skillFolder.Name)/SKILL.md"' in inst)
check("no substring ownership check is left",
      ".Contains($ownPath)" not in src and "-notmatch 'local-plugins" not in inst
      and "$Marker" not in src)
check("an empty file cannot throw on the check",
      src.count("$existing = [string](Get-Content $destMd -Raw -Encoding UTF8)") == 1
      and inst.count("$existing = [string](Get-Content $destMd -Raw -Encoding UTF8)") == 1)
check("the pointer session-start.ps1 writes names that same path",
      '$pointerPath = "~/.claude/$ownPath"' in src)
check("the pointer install.ps1 writes names that same path", '$ptr = "~/.claude/$ownPath"' in inst)
for name, text in (("session-start.ps1", src), ("install.ps1", inst)):
    check(f"{name} is ASCII-only", all(ord(c) < 128 for c in text))

# The pattern, from the script's own literals. .NET's \z is Python's \Z.
pieces = re.findall(r"'((?:[^']|'')*)'", re.search(r"\$pattern = (.*?)\n\s*return", fn or "", re.S).group(1)) if fn else []


def owned(existing, plugin, skill):
    path = own.group(1).replace("$pluginName", plugin).replace("$($skillFolder.Name)", skill)
    t = (existing or "").replace("\\", "/").replace("\r\n", "\n").lstrip("\ufeff")
    pattern = (pieces[0] + re.escape(path) + pieces[1]).replace(r"\z", r"\Z")
    return re.search(pattern, t) is not None


def pointer(path, desc="Google Workspace", nl="\n"):
    return nl.join(["---", "name: gws", "description: >-", f"  {desc}", "---", "",
                    f"Read and follow the full skill at `{path}`.", ""])


print("\nwhat it will and will not overwrite")
check("the pattern was read from the script", len(pieces) == 2, f"({pieces!r})")
if own and len(pieces) == 2:
    tk = "nsls-builder-toolkit"
    home = "~/.claude/local-plugins/nsls-builder-toolkit/skills/gws/SKILL.md"
    check("its own pointer is refreshed", owned(pointer(home), tk, "gws"))
    check("install.ps1's pointer (different description) is refreshed",
          owned(pointer(home, "NSLS Builder Toolkit skill: gws"), tk, "gws"))
    win = "C:\\Users\\x\\.claude\\local-plugins\\nsls-builder-toolkit\\skills\\gws\\SKILL.md"
    check("a CRLF pointer naming a Windows path is refreshed",
          owned("\ufeff" + pointer(win, nl="\r\n"), tk, "gws"))

    credit = ("---\nname: gws\ndescription: my own Workspace helper\n---\n\n"
              "Based on ~/.claude/local-plugins/nsls-builder-toolkit/skills/gws/SKILL.md,\n"
              "but always use my shared drive first.\n")
    check("a builder skill that credits this exact toolkit skill is left alone",
          not owned(credit, tk, "gws"))
    extended = pointer(home) + "\nAlso: always cc my manager.\n"
    check("a pointer the builder extended with notes is left alone", not owned(extended, tk, "gws"))
    stub = ("---\nname: gws\n---\nWhen done, run\n"
            "bash ~/.claude/local-plugins/nsls-builder-toolkit/hooks/skill-event.sh\n")
    check("a builder skill that mentions a toolkit path is left alone", not owned(stub, tk, "gws"))
    other = pointer("~/.claude/local-plugins/nsls-builder-toolkit/skills/slack/SKILL.md")
    check("a pointer to a DIFFERENT toolkit skill is left alone", not owned(other, tk, "gws"))
    lookalike = pointer("~/.claude/local-plugins/nsls-builder-toolkit/skills/gws/SKILL.md.bak")
    check("a path that only starts with this skill's path is left alone",
          not owned(lookalike, tk, "gws"))
    check("an empty file is left alone", not owned("", tk, "gws"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
