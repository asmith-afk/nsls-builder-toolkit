#!/usr/bin/env bash
# skill-event.sh — PreToolUse hook for the `Skill` tool.
#
# Reads the Claude Code hook JSON from stdin, extracts the skill name from
# tool_input.skill, looks up BUILDER_EMAIL, and POSTs the event to the
# automation tracker. The POST is synchronous but bounded (--max-time), so it
# can never block tool execution for more than a couple of seconds.
set -uo pipefail

# Mute by default — the completion notification clutters chat.
# Set SKILL_EVENT_VERBOSE=1 to see output (useful for debugging).
# Skills can pass this via: `open day -v` → skill sets the env var
# before invoking the hook.
[ "${SKILL_EVENT_VERBOSE:-}" != "1" ] && exec >/dev/null 2>&1

# Beacon: evidence that the PLUGIN copy of this hook fires on this machine.
# Stage B retires all three shims together off one shared marker, so retiring
# them needs proof per hook, not per plugin — and this is the credit-logging
# hook, the one whose silent loss costs builders the record of their work.
# Only a copy running from the plugin cache may write it: the shim must not be
# able to certify its own retirement.
case "${BASH_SOURCE[0]:-$0}" in
  */plugins/cache/*)
    _nsls_root=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd) || _nsls_root=""
    if [ -n "$_nsls_root" ]; then
      _nsls_beacons="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.nsls-plugin-beacons"
      # Escape before interpolating. A root path containing a quote, a
      # backslash or a control character produced a file that is not JSON, so
      # plugin_beacon.fired() could never parse it — and this hook could then
      # never present the evidence that retires its own shim, on exactly the
      # platform whose paths are full of backslashes.
      _nsls_esc=$(printf '%s' "$_nsls_root" | tr -d '\000-\037' | sed 's/\\/\\\\/g; s/"/\\"/g')
      _nsls_ver=$(printf '%s' "${_nsls_root##*/}" | tr -d '\000-\037' | sed 's/\\/\\\\/g; s/"/\\"/g')
      mkdir -p "$_nsls_beacons" 2>/dev/null &&
        printf '{"hook":"skill-event","root":"%s","version":"%s","last":%s}\n' \
          "$_nsls_esc" "$_nsls_ver" "$(date +%s)" \
          > "$_nsls_beacons/skill-event.json" 2>/dev/null
    fi
    ;;
esac

INPUT=$(cat)

# Collector early-exit. While the NSLS usage collector's evidence file is fresh,
# the collector already reports this machine's skill use, so posting here too is
# redundant. Same contract and same grammar as hooks/collector_evidence.py (the
# test runs this copy against every one of its cases):
#   - a regular file (never a FIFO or device, so the read cannot block) of at
#     most 4096 bytes with no NUL bytes, read once and bounded;
#   - the whole document is one flat JSON object of EXACTLY the keys
#     machine_id, at and version, each once, any order, each value a plain
#     printable-ASCII string with no escapes. Nesting, duplicates, extra or
#     missing keys and trailing commas all fail closed;
#   - machine_id non-empty; at a real UTC calendar time
#     YYYY-MM-DDTHH:MM:SS[.fff](Z|+00:00), at most 7 days old and at most 1
#     day ahead.
# Pure bash + date -u, no python3, so a python3-less Mac keeps working.
# Anything unexpected -> not fresh -> post as always. Placed after the stdin
# read so the hook never leaves input unread.
# Assigns one member into the caller's mid/at/ver; fails on an unknown key or
# a key seen before (bash's dynamic scoping writes the caller's locals).
_ce_field() {
  case "$seen" in *" $1 "*) return 1 ;; esac
  case "$1" in
    machine_id) mid=$2 ;;
    at) at=$2 ;;
    version) ver=$2 ;;
    *) return 1 ;;
  esac
  seen="$seen$1 "
}
collector_evidence_fresh() {
  local LC_ALL=C
  local f="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.nsls-collector/reported.json"
  [ -f "$f" ] && [ ! -p "$f" ] || return 1
  # ONE bounded read (a file swapped in after the -f check still yields at
  # most 4097 bytes). NUL -> \001 so bash cannot silently drop it; the grammar
  # below rejects control bytes. The trailing x keeps $(...) from eating
  # newlines, so the length check is exact.
  local raw
  raw=$(head -c 4097 "$f" 2>/dev/null | tr '\000' '\001'; printf x) || return 1
  raw=${raw%x}
  [ "${#raw}" -le 4096 ] || return 1
  local ws=$'[ \t\r\n]*'
  local str='"([] !#-[^-~]*)"'
  local member="${ws}${str}${ws}:${ws}${str}${ws}"
  local doc_re="^${ws}\\{${member},${member},${member}\\}${ws}\$"
  [[ $raw =~ $doc_re ]] || return 1
  local mid="" at="" ver="" seen=" "
  _ce_field "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" &&
    _ce_field "${BASH_REMATCH[3]}" "${BASH_REMATCH[4]}" &&
    _ce_field "${BASH_REMATCH[5]}" "${BASH_REMATCH[6]}" || return 1
  [ -n "$mid" ] || return 1
  local iso_re='^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?(Z|\+00:00)$'
  [[ $at =~ $iso_re ]] || return 1
  local y=$((10#${BASH_REMATCH[1]})) m=$((10#${BASH_REMATCH[2]})) d=$((10#${BASH_REMATCH[3]}))
  local hh=$((10#${BASH_REMATCH[4]})) mm=$((10#${BASH_REMATCH[5]})) ss=$((10#${BASH_REMATCH[6]}))
  [ "$m" -ge 1 ] && [ "$m" -le 12 ] && [ "$d" -ge 1 ] || return 1
  [ "$hh" -le 23 ] && [ "$mm" -le 59 ] && [ "$ss" -le 59 ] || return 1
  local dim
  case "$m" in
    4|6|9|11) dim=30 ;;
    2) if [ $((y % 4)) -eq 0 ] && { [ $((y % 100)) -ne 0 ] || [ $((y % 400)) -eq 0 ]; }; then dim=29; else dim=28; fi ;;
    *) dim=31 ;;
  esac
  [ "$d" -le "$dim" ] || return 1
  # Days since 1970-01-01 (Howard Hinnant's days_from_civil), all integer math.
  local yy=$y mp
  [ "$m" -le 2 ] && yy=$((yy - 1))
  local era=$((yy / 400)) yoe
  yoe=$((yy - era * 400))
  if [ "$m" -gt 2 ]; then mp=$((m - 3)); else mp=$((m + 9)); fi
  local doy=$(((153 * mp + 2) / 5 + d - 1))
  local doe=$((yoe * 365 + yoe / 4 - yoe / 100 + doy))
  local at_epoch=$(((era * 146097 + doe - 719468) * 86400 + hh * 3600 + mm * 60 + ss))
  local now
  now=$(date -u +%s 2>/dev/null) || return 1
  local age=$((now - at_epoch))
  [ "$age" -le 604800 ] && [ "$age" -ge -86400 ]
}
collector_evidence_fresh && exit 0

# Extract tool_input.skill WITHOUT python3 — a python3-less Mac otherwise loses
# skill credit silently (the Windows .ps1 uses ConvertFrom-Json and is fine).
# The PreToolUse(Skill) payload has exactly one "skill" key (tool_input.skill);
# a decoy like "skill_name" or "skillx" can't match because the pattern requires
# "skill" immediately closed by a quote and followed by a colon. Handles compact
# and pretty-printed JSON and skill names with hyphens/colons (e.g.
# compound-engineering:ce-commit). Same semantics as the old json.load: absent
# or unparseable -> empty -> exit 0.
SKILL_NAME=$(printf '%s' "$INPUT" | sed -n 's/.*"skill"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)

[ -z "$SKILL_NAME" ] && exit 0

# Plugin-installed toolkits namespace their skills (nsls-builder-toolkit:gws).
# Strip OUR prefixes only, so tracker credit rows stay continuous with the
# years of bare-name history. Third-party prefixes (compound-engineering:…)
# are real distinct names and pass through untouched.
SKILL_NAME=${SKILL_NAME#nsls-builder-toolkit:}
SKILL_NAME=${SKILL_NAME#nsls-personal-toolkit:}

# Find builder email (same precedence as session-start.py). Respect
# CLAUDE_CONFIG_DIR so a --test install reads its own (absent) .env instead of
# the real user's — keeping test skill events off the real builder's row.
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
EMAIL=""
ENV_FILE="$CONFIG_DIR/local-plugins/nsls-personal-toolkit/.env"
if [ -f "$ENV_FILE" ]; then
  EMAIL=$(grep "^BUILDER_EMAIL=" "$ENV_FILE" | cut -d= -f2 | tr -d '"')
fi
if [ -z "$EMAIL" ]; then
  EMAIL=$(git config user.email 2>/dev/null || true)
fi
[ -z "$EMAIL" ] && exit 0

# JSON-escape skill name (paranoia — skill names are plain ASCII today but
# strip anything that could break the JSON body).
SAFE_SKILL=$(printf '%s' "$SKILL_NAME" | tr -d '"\\')
SAFE_EMAIL=$(printf '%s' "$EMAIL" | tr -d '"\\')

# Deliver synchronously. We deliberately do NOT background/disown the curl:
# a disowned curl gets reaped on process-group teardown before the ~1.8s
# round-trip finishes, which silently dropped events (worse on desktop, where
# teardown is faster). The PreToolUse hook has a 5s timeout and this call is
# ~1.8s, so --max-time 3 leaves headroom while keeping delivery deterministic.
# Output is already muted by the `exec` above unless SKILL_EVENT_VERBOSE=1, in
# which case the response body prints for debugging. `|| true` keeps a failed
# POST from ever failing the hook.
curl -s --max-time 3 -X POST \
  ${NSLS_TRACKER_URL:-https://web-production-6281e.up.railway.app}/skill-event \
  -H 'Content-Type: application/json' \
  -d "{\"builder_email\":\"$SAFE_EMAIL\",\"skill_name\":\"$SAFE_SKILL\"}" \
  || true

exit 0
