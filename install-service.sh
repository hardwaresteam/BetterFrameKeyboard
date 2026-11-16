#!/usr/bin/env bash
# Keeps the helper running in the background and starts it after reboots
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# Always talk to this user's own service manager
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/betterframe-keyboard.service" <<EOF
[Unit]
Description=BetterFrame Keyboard helper

[Service]
ExecStart=/usr/bin/env bash "$DIR/start.sh"
Restart=on-failure

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable betterframe-keyboard
systemctl --user restart betterframe-keyboard   # (a running copy is replaced with the new one)
