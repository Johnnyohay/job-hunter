#!/bin/bash
# Deploys the Apps Script bridge with clasp (instead of pasting it by hand) and saves its URL to .env.
# Needs: `npx @google/clasp login` once, and the Apps Script API turned on at
# https://script.google.com/home/usersettings. Re-running updates the same deployment (same URL).
set -euo pipefail
cd "$(dirname "$0")/.."
clasp() { npx -y @google/clasp@3.4.1 "$@"; }

npm run -s bridge > /dev/null          # token in .env, filled script in .cache/Code.gs
dir=.cache/apps-script
mkdir -p "$dir"
cp .cache/Code.gs "$dir/Code.gs"
cp apps-script/appsscript.json "$dir/appsscript.json"

cd "$dir"
[[ -f .clasp.json ]] || clasp create-script --type standalone --title "Job Agent bridge" --rootDir .
clasp push --force
if [[ -f deployment-id ]]; then
  clasp create-deployment -i "$(cat deployment-id)" -d "job agent bridge"
else
  out="$(clasp create-deployment -d "job agent bridge")"
  echo "$out"
  grep -oE 'AKfy[A-Za-z0-9_-]+' <<<"$out" | head -1 > deployment-id
fi
cd - > /dev/null
url="https://script.google.com/macros/s/$(cat "$dir/deployment-id")/exec"
echo "Web app URL: $url"
echo "Open it once in your browser and allow access, then run: npm run bridge -- $url"
