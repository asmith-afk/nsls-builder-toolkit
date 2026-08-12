#!/bin/bash
# Session ping — track activity, check for PR credits, deliver announcements.
# Runs on SessionStart via hooks.json. Must be fast and fail silently.

# Find builder email
EMAIL=""
ENV_FILE="$HOME/.claude/local-plugins/nsls-personal-toolkit/.env"
if [ -f "$ENV_FILE" ]; then
  EMAIL=$(grep "^BUILDER_EMAIL=" "$ENV_FILE" | cut -d= -f2)
fi
if [ -z "$EMAIL" ]; then
  EMAIL=$(git config user.email 2>/dev/null)
fi
[ -z "$EMAIL" ] && exit 0

# Find GitHub username
GITHUB=""
if [ -f "$ENV_FILE" ]; then
  GITHUB=$(grep "^GITHUB_USERNAME=" "$ENV_FILE" | cut -d= -f2)
fi

# Detect installed toolkits
TOOLKIT="personal"
if [ -d "$HOME/.claude/local-plugins/nsls-builder-toolkit" ] || [ -d "$HOME/nsls-skills/nsls-builder-toolkit" ]; then
  TOOLKIT="both"
fi

# Ping the proxy and pipe directly to python
curl -s --max-time 8 -X POST ${NSLS_TRACKER_URL:-https://web-production-6281e.up.railway.app}/session-ping \
  -H 'Content-Type: application/json' \
  -d "{\"builder_email\": \"$EMAIL\", \"toolkit\": \"$TOOLKIT\", \"github_username\": \"$GITHUB\"}" 2>/dev/null \
| EMAIL="$EMAIL" python3 -c "
import json, sys, subprocess, os

email = os.environ.get('EMAIL', '')
try:
    data = json.load(sys.stdin)
except:
    sys.exit(0)

output = []

for pr in data.get('new_pr_credits', []):
    output.append(f\"Your PR #{pr.get('pr','?')} to {pr.get('repo','?')} was merged.\")
if data.get('new_pr_credits'):
    output.append('Shipped something new with that PR (a skill, tool, or service others will use — not just a fix)? Run /register-automation so it counts on the org tracker.')

adv = data.get('stage_advanced')
if adv:
    output.append(f\"You advanced to {adv.get('to','?')} on the builder path.\")

for ann in data.get('announcements', []):
    output.append(f\"{ann.get('title','')}: {ann.get('body','')}\")
    ann_id = ann.get('id', '')
    if ann_id and email:
        try:
            subprocess.run([
                'curl', '-s', '--max-time', '5', '-X', 'POST',
                '${NSLS_TRACKER_URL:-https://web-production-6281e.up.railway.app}/dismiss-announcement',
                '-H', 'Content-Type: application/json',
                '-d', json.dumps({'announcement_id': ann_id, 'builder_email': email})
            ], capture_output=True, timeout=8)
        except:
            pass

if output:
    print('\n'.join(output))
" 2>/dev/null
