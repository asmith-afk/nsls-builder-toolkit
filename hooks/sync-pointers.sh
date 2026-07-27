#!/bin/bash
# Sync pointer skills from the plugin to ~/.claude/skills/
# Creates pointers for new plugin skills, updates existing pointers,
# skips user's custom (non-pointer) skills.

PLUGIN_DIR="$HOME/.claude/local-plugins/nsls-builder-toolkit"
SKILLS_DIR="$HOME/.claude/skills"
MARKER="local-plugins/nsls-builder-toolkit"

[ -d "$PLUGIN_DIR/skills" ] || exit 0
mkdir -p "$SKILLS_DIR"

created=0
for skill_dir in "$PLUGIN_DIR/skills"/*/; do
  skill=$(basename "$skill_dir")
  dest="$SKILLS_DIR/$skill"
  src="$skill_dir/SKILL.md"
  [ -f "$src" ] || continue

  # Skip if user has a custom (non-pointer) skill
  if [ -d "$dest" ] && [ -f "$dest/SKILL.md" ]; then
    grep -q "$MARKER" "$dest/SKILL.md" 2>/dev/null || continue
  fi

  # Extract name from frontmatter
  name=$(grep "^name:" "$src" | head -1 | sed 's/name: *//')
  [ -z "$name" ] && continue

  # Extract description
  desc=$(python3 -c "
import re, sys
with open('$src', encoding='utf-8') as f: content = f.read()
fm = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
if not fm: sys.exit(0)
m = re.search(r'description:\s*>-?\s*\n((?:[ \t]+.+\n?)*)', fm.group(1))
if m: d = ' '.join(m.group(1).split())
else:
    m = re.search(r'description:[ \t]*(.+)', fm.group(1), re.MULTILINE)
    d = m.group(1).strip() if m else ''
    # A bare block indicator is not a description; and strip YAML quotes off a
    # single-line scalar, decoding double-quoted escapes in ONE left-to-right
    # pass (chained replaces would re-decode their own output). chr(34)/chr(39)
    # /chr(92) are a double-quote, single-quote and backslash: this Python is
    # embedded in a double-quoted shell string, where a literal double-quote
    # would end it early.
    if d in ('>', '>-', '>+', chr(124), chr(124) + '-', chr(124) + '+'):
        d = ''
    else:
        q = d[:1]
        if len(d) > 1 and d[-1:] == q and q in (chr(34), chr(39)):
            inner = d[1:-1]
            if q == chr(34):
                # Includes YAML's four named Unicode escapes (N _ L P);
                # the whitespace collapse folds all four to spaces.
                simple = {'0': chr(0), 'a': chr(7), 'b': chr(8), 't': chr(9),
                          'n': chr(10), 'v': chr(11), 'f': chr(12), 'r': chr(13),
                          'e': chr(27), 'N': chr(133), '_': chr(160),
                          'L': chr(8232), 'P': chr(8233)}
                esc = re.compile(chr(92) * 2 + 'x([0-9a-fA-F]{2})|' + chr(92) * 2
                                 + 'u([0-9a-fA-F]{4})|' + chr(92) * 2
                                 + 'U([0-9a-fA-F]{8})|' + chr(92) * 2 + '(.)')
                def rep(mm):
                    for g in (1, 2, 3):
                        if mm.group(g): return chr(int(mm.group(g), 16))
                    return simple.get(mm.group(4), mm.group(4))
                inner = esc.sub(rep, inner)
            else:
                inner = inner.replace(chr(39) * 2, chr(39))
            d = inner
    # Map decoded control chars (NUL, BEL, ESC) to spaces -- they would make the
    # generated pointer unparseable -- then collapse whitespace, because the
    # caller embeds this as one indented line under description: >-.
    d = re.sub('[' + chr(92) + 'x00-' + chr(92) + 'x08' + chr(92) + 'x0b' + chr(92) + 'x0c' + chr(92) + 'x0e-' + chr(92) + 'x1f' + chr(92) + 'x7f-' + chr(92) + 'x9f]', ' ', d)
    d = ' '.join(d.split())
if d: print(d)
" 2>/dev/null)
  [ -z "$desc" ] && desc="NSLS Builder Toolkit skill: $skill"

  mkdir -p "$dest"
  cat > "$dest/SKILL.md" << POINTER
---
name: $name
description: >-
  $desc
---

Read and follow the full skill at \`~/.claude/local-plugins/nsls-builder-toolkit/skills/$skill/SKILL.md\`.
POINTER
  created=$((created + 1))
done

# Output count if any were created/updated (silent otherwise)
[ $created -gt 0 ] && echo "$created skill pointers synced" >&2
