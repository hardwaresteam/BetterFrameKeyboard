#!/usr/bin/env bash
# Installs the system-wide BetterFrame Keyboard (a SteamVR overlay) and keeps it running.
# Run setup.sh first. Undo with: systemctl --user disable --now betterframe-overlay
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
# Always talk to this user's own service manager (Konsole can point somewhere else, e.g. after a reset)
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

[ -x venv/bin/python ] || { echo "Run setup.sh first."; exit 1; }

echo "-- Installing the keyboard"
venv/bin/pip install --quiet openvr pillow
SITE="$(venv/bin/python -c 'import os, importlib.util; print(os.path.dirname(importlib.util.find_spec("openvr").origin))')"
# Valve's ARM64 OpenVR library (from the official OpenVR SDK) in place of the x86 one the package ships
cp vendor/linuxarm64/libopenvr_api.so "$SITE/libopenvr_api_64.so"

echo "-- Checking permission to type into apps"
if [ -w /dev/uinput ]; then
  echo "   already allowed"
else
  echo "   BetterFrame needs permission to act as a keyboard. Enter your password if asked."
  sudo bash -c '
    modprobe uinput 2>/dev/null || true
    echo uinput > /etc/modules-load.d/betterframe-uinput.conf
    echo "KERNEL==\"uinput\", SUBSYSTEM==\"misc\", TAG+=\"uaccess\", OPTIONS+=\"static_node=uinput\"" > /etc/udev/rules.d/60-betterframe-uinput.rules
    udevadm control --reload-rules
    udevadm trigger --name-match=uinput 2>/dev/null || true
  '
  sudo setfacl -m "u:$(id -un):rw" /dev/uinput 2>/dev/null || sudo chmod 660 /dev/uinput
  [ -w /dev/uinput ] && echo "   allowed" || echo "   still not allowed: typing won't work until /dev/uinput is writable."
fi

echo "-- Checking permission to keep controller presses on the keyboard"
# While a controller types on the keyboard, Steam also turns its presses into mouse moves and keys for the desktop.
# The keyboard holds Steam's made-up mouse and keyboard while you type with a controller (never a real device), so
# those presses only type. This lets your own account open just those made-up Steam devices.
RULE=/etc/udev/rules.d/61-betterframe-steam-input.rules
if [ -f "$RULE" ]; then
  echo "   already allowed"
else
  echo "   Enter your password if asked."
  sudo tee "$RULE" >/dev/null <<'RULES'
SUBSYSTEM=="input", KERNEL=="event*", DEVPATH=="/devices/virtual/*", ATTRS{id/vendor}=="28de", TAG+="uaccess"
SUBSYSTEM=="input", KERNEL=="event*", DEVPATH=="/devices/virtual/*", ATTRS{name}=="*Steam*", TAG+="uaccess"
RULES
  sudo udevadm control --reload-rules 2>/dev/null || true
  sudo udevadm trigger --subsystem-match=input 2>/dev/null || true
  [ -f "$RULE" ] && echo "   allowed" || echo "   not allowed: controller presses may also move things behind the keyboard"
fi

echo "-- Starting it in the background (also in Game Mode)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/betterframe-overlay.service" <<EOF
[Unit]
Description=BetterFrame Keyboard overlay
After=betterframe-keyboard.service
StartLimitIntervalSec=0

[Service]
WorkingDirectory=$DIR
ExecStartPre=/usr/bin/env bash $DIR/repair.sh
ExecStart=$DIR/venv/bin/python $DIR/overlay.py
TimeoutStartSec=900
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable betterframe-overlay
systemctl --user restart betterframe-overlay   # (a running copy is replaced with the new one)
