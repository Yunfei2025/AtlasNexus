#!/bin/sh
# One-shot publish: commit + push input/ (squashing old history via
# input/snapshot.sh) and bin-v4.0 (code).
# Usage: ./push_all.sh [-m "message"]   (message applies to bin-v4.0)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
MSG="update"
[ "$1" = "-m" ] && MSG="$2"

echo "== input/ (data snapshot) =="
sh "$HERE/../input/snapshot.sh"

echo "== bin-v4.0 (code) =="
cd "$HERE"
git add -A
git diff --cached --quiet || git commit -q -m "$MSG"
git push -q origin "$(git rev-parse --abbrev-ref HEAD)"
git status -sb | head -1
echo "done"
