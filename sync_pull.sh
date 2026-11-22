#!/usr/bin/env bash
# Pull bin-v4.0/ and ../input/ from their remotes. The remote always wins:
# local files are overwritten, so conflicts cannot occur.
#
# Before overwriting, any uncommitted local work (including untracked files) is saved to a git stash,
# so nothing is lost for good:   git stash list   /   git stash show -p stash@{0}
# Unpushed local commits are dropped from the branch but stay in `git reflog`.
#
# Usage:  ./sync_pull.sh                  # both repos
#         INPUT_DIR=/path/to/input ./sync_pull.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_DIR="$SCRIPT_DIR"
INPUT_DIR="${INPUT_DIR:-$SCRIPT_DIR/../input}"

sync_repo() {
    local dir="$1" name
    name="$(basename "$(cd "$dir" && pwd)")"
    if [ ! -d "$dir/.git" ]; then
        echo "[$name] not a git repo: $dir" >&2
        return 1
    fi
    cd "$dir"
    local branch
    branch="$(git rev-parse --abbrev-ref HEAD)"
    echo "[$name] fetching origin ($branch)..."
    git fetch origin

    if [ -n "$(git status --porcelain)" ]; then
        local msg="sync_pull backup $(date '+%Y-%m-%d %H:%M:%S')"
        git stash push --include-untracked -m "$msg" >/dev/null
        echo "[$name] local changes saved to stash: \"$msg\""
    fi

    git reset --hard "origin/$branch"
    echo "[$name] now at $(git rev-parse --short HEAD): $(git log -1 --format=%s)"
}

sync_repo "$CODE_DIR"
sync_repo "$INPUT_DIR"
echo "Done."
