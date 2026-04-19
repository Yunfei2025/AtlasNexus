#!/usr/bin/env bash
set -euo pipefail

# AtlasNexus Daily Console Launcher (macOS)
# Runs the app with conda environment: dev

echo "============================================================"
echo "AtlasNexus Daily Console Launcher (macOS)"
echo "============================================================"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[1/3] Locating conda..."

CONDA_BIN=""
if command -v conda >/dev/null 2>&1; then
  CONDA_BIN="$(command -v conda)"
elif [[ -x "$HOME/opt/anaconda3/bin/conda" ]]; then
  CONDA_BIN="$HOME/opt/anaconda3/bin/conda"
elif [[ -x "$HOME/anaconda3/bin/conda" ]]; then
  CONDA_BIN="$HOME/anaconda3/bin/conda"
elif [[ -x "$HOME/miniconda3/bin/conda" ]]; then
  CONDA_BIN="$HOME/miniconda3/bin/conda"
fi

if [[ -z "$CONDA_BIN" ]]; then
  echo "ERROR: Could not find conda. Please install or initialize Anaconda/Miniconda."
  exit 1
fi

echo "[2/3] Using conda: $CONDA_BIN"

if ! "$CONDA_BIN" env list | awk '{print $1}' | grep -qx "dev"; then
  echo "ERROR: Conda environment 'dev' does not exist."
  echo "Create it with: conda create -n dev python=3.13.5"
  exit 1
fi

echo "Python in dev environment:"
"$CONDA_BIN" run -n dev python --version

echo
echo "[3/3] Starting AtlasNexus Daily Console..."
echo "Server will start at: ttp://127.0.0.1:8080"
echo "Press Ctrl+C to stop the server"
echo "============================================================"
echo

exec "$CONDA_BIN" run -n dev python main.py daily-web
