#!/bin/bash
# Runs the daily job search through Claude Code (your subscription; no API key). Called by launchd.
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
log="logs/daily-$(date +%F).log"
{
  echo "=== $(date)"
  # Permissions are passed here (not only in .claude/settings.json) so an unattended run never waits for approval.
  claude -p "/daily" --permission-mode acceptEdits \
    --allowedTools "Bash(npm run fetch:*)" "Bash(npm run record:*)" "Read" "Edit(./.state/**)" "WebSearch" \
    --disallowedTools "WebFetch(domain:linkedin.com)" "WebFetch(domain:www.linkedin.com)"
} >> "$log" 2>&1
