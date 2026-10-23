#!/bin/bash
# Runs the daily job search through Claude Code (your subscription; no API key). Called by launchd.
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
log="logs/daily-$(date +%F).log"
{
  echo "=== $(date)"
  claude -p "/daily" --permission-mode acceptEdits
} >> "$log" 2>&1
