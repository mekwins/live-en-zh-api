#!/usr/bin/env bash
# Installs a launchd agent that keeps the API server running in the background
# and restarts it automatically (on crash or reboot/login).
set -euo pipefail
cd "$(dirname "$0")"

PLIST_LABEL="com.kris.live-en-zh-api"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
WORKDIR="$(pwd)"
PYTHON_BIN="$WORKDIR/.venv/bin/python3"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${WORKDIR}/server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${WORKDIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${WORKDIR}/server.log</string>
    <key>StandardErrorPath</key>
    <string>${WORKDIR}/server.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed and started launchd agent: ${PLIST_LABEL}"
echo "Logs: ${WORKDIR}/server.log"
echo ""
echo "Manage with:"
echo "  launchctl unload ${PLIST_PATH}   # stop"
echo "  launchctl load ${PLIST_PATH}     # start"
echo "  tail -f ${WORKDIR}/server.log    # watch logs"
