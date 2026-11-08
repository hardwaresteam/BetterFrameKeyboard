#!/usr/bin/env bash
# BetterFrame Keyboard: take it out again. SteamVR's own keyboard comes back.
# This folder is left in place; the last line printed says how to delete it.
cd "$(dirname "$0")"
CONF="$HOME/.config/betterframe-keyboard"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
PY=python3
[ -x venv/bin/python ] && PY=venv/bin/python
echo "== Removing BetterFrame Keyboard"
"$PY" steambridge.py off >/dev/null 2>&1 || true            # its settings out of Steam's Keyboard page
[ -x venv/bin/python ] && venv/bin/python a11yfocus.py off >/dev/null 2>&1 || true   # desktop accessibility back off, only if BetterFrame turned it on
rm -f "$CONF/steam-pages-on" "$CONF/keyboard-only"
for u in betterframe-overlay betterframe-keyboard; do
  systemctl --user disable --now "$u" 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/$u.service"
done
systemctl --user daemon-reload 2>/dev/null || true
"$PY" dashpin.py disable >/dev/null 2>&1 || true   # SteamVR's menu setting back (only if BetterFrame changed it)
if [ -e "$CONF/cef-by-betterframe" ]; then   # Steam's interface switch: off again, only if the install turned it on
  STEAMDIR="$(readlink -f "$HOME/.steam/steam" 2>/dev/null || true)"
  [ -d "$STEAMDIR" ] || STEAMDIR="$HOME/.local/share/Steam"
  rm -f "$STEAMDIR/.cef-enable-remote-debugging" "$CONF/cef-by-betterframe"
fi
if [ -e /etc/udev/rules.d/60-betterframe-uinput.rules ] || [ -e /etc/udev/rules.d/61-betterframe-steam-input.rules ] || [ -e /etc/modules-load.d/betterframe-uinput.conf ]; then
  if [ -t 0 ]; then
    echo "-- Removing the typing permission (enter your password if asked)"
    sudo rm -f /etc/udev/rules.d/60-betterframe-uinput.rules /etc/udev/rules.d/61-betterframe-steam-input.rules /etc/modules-load.d/betterframe-uinput.conf || true
  else
    sudo -n rm -f /etc/udev/rules.d/60-betterframe-uinput.rules /etc/udev/rules.d/61-betterframe-steam-input.rules /etc/modules-load.d/betterframe-uinput.conf 2>/dev/null || \
      echo "-- The typing permission is left in place (it needs your password): run  bash ~/betterframe-keyboard/uninstall.sh  in a terminal to remove it too"
  fi
fi
echo
echo "Removed. Restart SteamVR (or the Frame) to get SteamVR's own keyboard back."
echo "To delete the files too:  rm -rf ~/betterframe-keyboard ~/.config/betterframe-keyboard"
