#!/usr/bin/env bash
# AtlasNexus — Mac Launcher
# Double-click this file in Finder, or run it from Terminal.
# Starts the Dash server + Cloudflare tunnel in one window.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  AtlasNexus Daily Console"
echo "============================================================"
echo ""

# ── 1. Conda environment ─────────────────────────────────────────
echo "[1/3] Activating conda environment 'prod'..."

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
    echo "ERROR: Could not find conda. Install Anaconda or Miniconda first."
    read -rp "Press enter to exit..."; exit 1
fi

eval "$("$CONDA_BIN" shell.bash hook)" 2>/dev/null
if ! conda activate prod 2>/dev/null; then
    echo "ERROR: Could not activate conda env 'prod'."
    echo "       Run: conda create -n prod python=3.13"
    read -rp "Press enter to exit..."; exit 1
fi
echo "      OK"
echo ""

# ── 2. Dash server (background) ──────────────────────────────────
echo "[2/3] Starting Dash server on port 8080..."
export FI_SHOW_LOG_WINDOW=0
python main.py daily-web &
SERVER_PID=$!
echo "      PID $SERVER_PID — waiting for server to be ready..."
sleep 4

if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "ERROR: Server process exited early. Check the output above."
    read -rp "Press enter to exit..."; exit 1
fi
echo "      OK"
echo ""

# ── 3. Cloudflare tunnel (foreground) ────────────────────────────
echo "[3/3] Starting Cloudflare tunnel (atlasnexus → anmac.mayunfei.org)..."
echo ""
echo "  Local:   http://127.0.0.1:8080"
echo "  Public:  https://anmac.mayunfei.org"
echo ""
echo "Share https://anmac.mayunfei.org with your friends."
echo "Press Ctrl+C to stop everything."
echo "============================================================"
echo ""

cleanup() {
    echo ""
    echo "Shutting down..."
    kill "$SERVER_PID" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

cloudflared tunnel --config ~/.cloudflared/config.yml run atlasnexus

# cloudflared exited on its own — stop the server too
kill "$SERVER_PID" 2>/dev/null || true
echo ""
echo "Tunnel stopped. Press enter to close."
read -r
