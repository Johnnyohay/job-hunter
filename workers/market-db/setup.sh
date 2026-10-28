#!/bin/bash
# One-time setup: first full data pull, then a once-a-day refresh at 07:10 via launchd.
# Run in Terminal:  bash workers/market-db/setup.sh   (add --schedule-only to just (re)install the 07:10 refresh)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then echo "python3 not found. Install Python 3, then run this again."; exit 1; fi
mkdir -p "$DIR/logs"
LABEL="com.jobmarket.dailyrefresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string><string>-u</string><string>$DIR/jobmarket.py</string><string>update</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>10</integer></dict>
  <key>StandardOutPath</key><string>$DIR/logs/daily.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/daily.err.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Daily refresh installed (07:10 every day). To remove it: launchctl unload \"$PLIST\" && rm \"$PLIST\""
[ "${1:-}" = "--schedule-only" ] && exit 0
echo "Starting the first full pull now. The first run downloads about 1 GB and can take 20 to 60 minutes."
"$PY" -u "$DIR/jobmarket.py" update 2>&1 | tee "$DIR/logs/first_run.log"
