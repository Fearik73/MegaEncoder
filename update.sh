#!/bin/bash
set -e
cd "$(dirname "$0")"

REPO="https://github.com/Fearik73/MegaEncoder.git"
BRANCH="${1:-main}"

[ -d .git ] || git init -q
if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$REPO"
else
    git remote add origin "$REPO"
fi

OLD="$(git rev-parse HEAD 2>/dev/null || true)"
git fetch origin "$BRANCH"
git reset --hard FETCH_HEAD
if [ -z "$OLD" ] || ! git diff --quiet "$OLD" HEAD -- requirements.txt; then
    pip3 install -q -r requirements.txt
fi
echo "✅ Updated to $(git rev-parse --short HEAD). Restart the bot now."
