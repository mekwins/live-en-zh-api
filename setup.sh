#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "== live-en-zh-api setup =="

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" &>/dev/null; then
    ver=$("$candidate" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ] && [ "$minor" -le 13 ]; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "No suitable Python found (need 3.10-3.13). Install with: brew install python@3.12"
  exit 1
fi

echo "-- Using $PYTHON ($($PYTHON --version)) --"
"$PYTHON" -m venv .venv
source .venv/bin/activate

echo "-- Installing dependencies --"
pip install --upgrade pip --quiet
pip install -r requirements.txt

echo "-- Downloading English -> Chinese translation model (Argos Translate, one-time) --"
python3 - <<'PY'
import argostranslate.package as pkg
import argostranslate.translate as tr

pkg.update_package_index()
avail = pkg.get_available_packages()
p = next((x for x in avail if x.from_code == "en" and x.to_code == "zh"), None)
if p is None:
    raise SystemExit("Could not find en->zh Argos Translate package.")

installed = tr.get_installed_languages()
already = any(l.code == "en" for l in installed) and any(l.code == "zh" for l in installed)
if already:
    print("en->zh model already installed.")
else:
    path = p.download()
    pkg.install_from_path(path)
    print("en->zh model installed.")
PY

echo ""
echo "== Setup complete =="
echo ""
echo "Start the server with:"
echo "  source .venv/bin/activate"
echo "  python server.py"
echo ""
echo "Or persistently via launchd (survives reboots/logouts):"
echo "  ./install_launchd.sh"
echo ""
echo "First request will download the Parakeet model (~600MB) from HuggingFace Hub."
