#!/bin/sh
# Runs the TypeScript entry points with a Node that can run .ts directly (22.18+): the one on PATH if it's new
# enough, otherwise any other installed Node that is. Unattended runs can't rely on PATH order.
ok() { "$1" -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 22 || (a === 22 && b >= 18) ? 0 : 1)' 2>/dev/null; }
for n in "$(command -v node)" "$HOME"/.nvm/versions/node/v*/bin/node /opt/homebrew/bin/node /usr/local/bin/node; do
  if [ -x "$n" ] && ok "$n"; then exec "$n" "$@"; fi
done
echo "job-agent needs Node 22.18 or newer; found $(node --version 2>/dev/null || echo none) on PATH." >&2
exit 1
