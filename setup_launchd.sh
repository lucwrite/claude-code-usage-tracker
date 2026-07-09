#!/bin/bash
# Installs a launchd job that runs `cli.py sync` daily at 8pm, plus once
# immediately. macOS only (launchd is Apple's scheduler). Safe to re-run --
# it overwrites its own previous install.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$(command -v python3)"
LABEL="com.$(whoami).claude-usage-tracker.sync"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [ -z "$PYTHON_BIN" ]; then
  echo "python3 not found on PATH -- install it first." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${PROJECT_DIR}/cli.py</string>
        <string>sync</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>

    <!-- launchd jobs don't inherit your shell's PATH -- without this,
         npx (needed to run ccusage) silently fails to resolve. -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <!-- Daily at 8pm, plus once immediately on load/login -- launchd does
         not retroactively run a missed StartCalendarInterval if the
         machine was asleep at 8pm, so RunAtLoad is the backstop. -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>20</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/sync.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/sync.error.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed and loaded: $PLIST_PATH"
echo "It just ran once (check sync.log). Runs daily at 8pm from now on."
echo ""
echo "To check it's alive:  launchctl list | grep claude-usage-tracker"
echo "To remove it:         launchctl unload $PLIST_PATH && rm $PLIST_PATH"
