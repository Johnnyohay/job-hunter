#!/bin/bash
# Installs (or with --remove, removes) a launchd job that runs the daily search every morning.
# Usage: npm run schedule [-- 12 15]  (hours, 24h clock; default 8). Later hours are retries: a run that
#        already recorded today's results exits immediately.
#        npm run schedule -- --remove
set -euo pipefail
cd "$(dirname "$0")/.."
label="com.jobhunter.applicant"
plist="$HOME/Library/LaunchAgents/$label.plist"

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/com.jobagent.daily" 2>/dev/null || true   # the label before the rename
rm -f "$HOME/Library/LaunchAgents/com.jobagent.daily.plist"
if [[ "${1:-}" == "--remove" ]]; then
  rm -f "$plist"
  echo "Removed the daily schedule."
  exit 0
fi

hours=("${@:-8}")
times=""; for h in "${hours[@]}"; do times+="<dict><key>Hour</key><integer>$h</integer><key>Minute</key><integer>0</integer></dict>"; done
# launchd starts with a bare PATH: give it the node and claude this shell uses.
path="$(dirname "$(command -v node)"):$(dirname "$(command -v claude)"):/usr/bin:/bin:/usr/sbin:/sbin"
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$PWD/scripts/run-daily.sh</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$path</string></dict>
  <key>StartCalendarInterval</key><array>$times</array>
  <key>StandardErrorPath</key><string>$PWD/logs/launchd.err</string>
</dict>
</plist>
PLIST
mkdir -p logs
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "Scheduled: every day at ${hours[*]/%/:00} (first one runs; later ones retry only if it failed; missed times run at next wake). Logs: logs/"
