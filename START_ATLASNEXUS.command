#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

bash "$SCRIPT_DIR/START_ATLASNEXUS.sh"
EXIT_CODE=$?

if [[ $EXIT_CODE -ne 0 ]]; then
  echo
  echo "============================================================"
  echo "Launcher exited with error code: $EXIT_CODE"
  echo "Press Enter to close this window..."
  echo "============================================================"
  read -r
fi

exit $EXIT_CODE
