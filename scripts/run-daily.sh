#!/bin/bash
# Runs the daily job search through Claude Code (your subscription; no API key). Called by launchd.
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
log="logs/daily-$(date +%F).log"
# The schedule fires more than once a day as a safety net; skip once today's run has been recorded.
if [[ -f .state/results.recorded.json ]] && grep -q "\"date\": \"$(date +%F)\"" .state/run.json 2>/dev/null; then
  echo "=== $(date) today's run is already recorded; nothing to do" >> "$log"
  exit 0
fi
{
  echo "=== $(date)"
  # Permissions are passed here (not only in .claude/settings.json) so an unattended run never waits for approval.
  # launchd may start this in a brief wake from sleep; keep the Mac awake until the run ends.
  caffeinate -i -w $$ &
  # Wait up to 10 minutes for the network after waking.
  for _ in $(seq 60); do curl -sfo /dev/null -m 10 https://script.google.com && break; sleep 10; done
  claude -p "/daily" --permission-mode acceptEdits \
    --allowedTools "Bash(npm run fetch:*)" "Bash(npm run record:*)" "Read" "Edit(./.state/**)" "WebSearch" \
    --disallowedTools "WebFetch(domain:linkedin.com)" "WebFetch(domain:www.linkedin.com)"
} >> "$log" 2>&1
