#!/bin/bash
# Installs (or with --remove, removes) a launchd job that runs the daily search every morning.
# Usage: npm run schedule [-- 8]      (hour, 24h clock; default 8)
#        npm run schedule -- --remove
set -euo pipefail
cd "$(dirname "$0")/.."
label="com.jobagent.daily"
plist="$HOME/Library/LaunchAgents/$label.plist"

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
if [[ "${1:-}" == "--remove" ]]; then
  rm -f "$plist"
  echo "Removed the daily schedule."
  exit 0
fi

hour="${1:-8}"
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
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$hour</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardErrorPath</key><string>$PWD/logs/launchd.err</string>
</dict>
</plist>
PLIST
mkdir -p logs
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "Scheduled: every day at $hour:00 (runs at next wake if the Mac is asleep). Logs: logs/"
