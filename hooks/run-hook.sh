#!/usr/bin/env bash
# run-hook.sh — the single cross-platform entry point for the toolkit's Python
# hooks.
#
# WHY THIS EXISTS. hooks.json has no OS conditional, so a plugin hook that runs
# Python has to name one interpreter for every machine. The two alternatives
# both fail somewhere:
#   * a bare `python3` entry errors on stock Windows, where `python3` is a
#     Microsoft Store alias that exits without running anything (that error is
#     why the gate was pulled out of hooks.json on 2026-09-06, which is what
#     left every migrated Mac with no gate at all);
#   * registering the hook twice (`python3` and `py -3`) means the absent twin
#     prints a "<hook> hook error" notice on EVERY matching tool call, on every
#     machine — unsuppressable, because swallowing it needs a shell.
# One shell-form entry per hook, with "shell": "bash" named explicitly in
# hooks.json, resolves the interpreter here instead. install.ps1 hard-requires
# Git for Windows, so Git Bash is present wherever this has to run.
#
# CONTRACT: exit 2 passes through (the only code that blocks a tool call);
# everything else exits 0 with whatever the script printed. A hook that cannot
# run is silence, never a notice — fail open is the gate's first design rule.
set -u

sub="${1:-}"
root="${CLAUDE_PLUGIN_ROOT:-}"
if [ -z "$root" ]; then
  root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd)" || exit 0
fi

case "$sub" in
  gate)          script="$root/hooks/guardrail-gate.py" ;;
  session-start) script="$root/hooks/session-start.py" ;;
  *)             exit 0 ;;
esac
[ -f "$script" ] || exit 0

# Resolving the interpreter costs a probe subprocess, and this runs before every
# Bash/Write/Edit call, so the answer is cached per machine. The cache holds a
# format tag and an ABSOLUTE path: validating it is then a file test, a changed
# format invalidates every old entry at once, and a Python that was upgraded or
# removed fails the test and costs exactly one re-probe.
cache_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
cache="$cache_dir/.nsls-hook-python"
CACHE_FORMAT=v2
py=""
flag=""
if [ -r "$cache" ]; then
  IFS='|' read -r c_fmt c_py c_flag < "$cache" 2>/dev/null || true
  if [ "${c_fmt:-}" = "$CACHE_FORMAT" ] && [ -n "${c_py:-}" ] && [ -x "${c_py}" ]; then
    py="$c_py"
    flag="${c_flag:-}"
  fi
fi

# A zero exit status is NOT proof of a Python. install.ps1 documents exactly what
# this guards against: the stock Windows `python` / `python3` App Execution
# Aliases can exit 0 having run nothing at all. A probe that accepted exit 0
# would cache one of those, and from then on every hook would "succeed" having
# executed nothing -- silently, no notice, no beacon, no gate. That is this
# entire outage reproduced one layer down. So the probe demands a sentinel on
# stdout, which only a real Python 3 can produce.
probe() {
  _out=""
  if [ -n "${2:-}" ]; then
    _out=$("$1" "$2" -c 'import sys; sys.stdout.write("NSLS-PY-%d" % sys.version_info[0])' 2>/dev/null)
  else
    _out=$("$1" -c 'import sys; sys.stdout.write("NSLS-PY-%d" % sys.version_info[0])' 2>/dev/null)
  fi
  [ "$_out" = "NSLS-PY-3" ]
}

# Every match on PATH, in order, not just the first. A broken stub earlier in
# PATH must not be able to hide a working interpreter behind it -- on Windows
# the Store aliases sit in exactly that position. Newline-separated, and read
# without word splitting, because a real Windows Python path contains spaces.
pick_python() {
  local spec cand cand_flag resolved candidates
  while IFS= read -r spec; do
    [ -n "$spec" ] || continue
    cand="${spec%%|*}"
    cand_flag="${spec#*|}"
    case "$cand" in
      /*|[A-Za-z]:[\\/]*) candidates="$cand" ;;
      *) candidates="$(type -aP "$cand" 2>/dev/null)" ;;
    esac
    [ -n "$candidates" ] || continue
    while IFS= read -r resolved; do
      [ -n "$resolved" ] || continue
      [ -x "$resolved" ] || continue
      if probe "$resolved" "$cand_flag"; then
        printf '%s|%s\n' "$resolved" "$cand_flag"
        return 0
      fi
    done <<CANDIDATES
$candidates
CANDIDATES
  done <<ORDER
$order
ORDER
  return 1
}

if [ -z "$py" ]; then
  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*|Windows*)
      # `py` first: the real launcher, never an alias. Then the explicit 3.12
      # path install.ps1 provisions, ahead of the bare names, so a machine
      # carrying the aliases still resolves to a real interpreter.
      order="py|-3
${LOCALAPPDATA:-$HOME}/Programs/Python/Python312/python.exe|
python|
python3|"
      ;;
    *) order="python3|
python|
py|-3" ;;
  esac
  if picked="$(pick_python)"; then
    py="${picked%|*}"
    flag="${picked##*|}"
    ( umask 077; printf '%s|%s|%s\n' "$CACHE_FORMAT" "$py" "$flag" > "$cache" ) 2>/dev/null || true
  fi
fi

# No Python at all: silence. The gate fails open by absence, exactly as its
# design rules say, and the builder sees nothing.
[ -n "$py" ] || exit 0

if [ -n "$flag" ]; then
  "$py" "$flag" "$script"
else
  "$py" "$script"
fi
status=$?
[ "$status" = "2" ] && exit 2
exit 0
