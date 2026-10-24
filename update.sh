#!/bin/bash
set -e
cd "$(dirname "$0")"

cfg() { grep -E "^$1=" config.env 2>/dev/null | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//; s/^[[:space:]]*//; s/[[:space:]]*$//'; }

REPO="${UPSTREAM_REPO:-$(cfg UPSTREAM_REPO)}"
BRANCH="${1:-${UPSTREAM_BRANCH:-$(cfg UPSTREAM_BRANCH)}}"
BRANCH="${BRANCH:-main}"

[ -n "$REPO" ] || { echo "❌ UPSTREAM_REPO set nahi hai (config.env me daalo)."; exit 1; }

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
