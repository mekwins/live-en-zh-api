#!/usr/bin/env bash
# Run this ON THE MACBOOK (client side) — sets up a venv with everything
# client_stopgap.py needs, so you can just run it afterwards.
set -euo pipefail
cd "$(dirname "$0")"

echo "== live-en-zh-api CLIENT setup (run on your MacBook) =="

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" &>/dev/null; then
    ver=$("$candidate" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "$major" -eq 3 ] && [ "$minor" -ge 9 ]; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "No suitable Python 3 found. Install with: brew install python@3.12"
  exit 1
fi

echo "-- Using $PYTHON ($($PYTHON --version)) --"
"$PYTHON" -m venv .venv-client
source .venv-client/bin/activate

echo "-- Installing client dependencies (sounddevice, numpy, requests, soundfile) --"
pip install --upgrade pip --quiet
pip install sounddevice numpy requests soundfile --quiet

echo ""
echo "== Client setup complete =="
echo ""
echo "Check Tailscale is connected on this MacBook:"
echo "  tailscale status"
echo ""
echo "List your microphones:"
echo "  source .venv-client/bin/activate && python client_stopgap.py --list-devices"
echo ""
echo "Start live translation (default server: http://100.118.167.42:8731):"
echo "  source .venv-client/bin/activate && python client_stopgap.py"
echo ""
echo "(macOS will prompt for microphone permission on first run — approve it.)"
