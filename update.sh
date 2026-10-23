#!/bin/bash
set -e
cd "$(dirname "$0")"
BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
OLD="$(git rev-parse HEAD 2>/dev/null || true)"
git fetch origin "$BRANCH"
git reset --hard FETCH_HEAD
if [ -z "$OLD" ] || ! git diff --quiet "$OLD" HEAD -- requirements.txt; then
    pip3 install -q -r requirements.txt
fi
echo "✅ Updated to $(git rev-parse --short HEAD). Restart the bot now."
