#!/usr/bin/env bash
# Runs each time before the keyboard starts. Puts back anything a SteamOS update took away.
# It only ever changes things inside this folder (and starts a background reinstall of voice typing if needed).
cd "$(dirname "$0")"
CONF="$HOME/.config/betterframe-keyboard"
LOGF="$CONF/repair.log"
mkdir -p "$CONF"
say() { echo "[repair] $*"; echo "$(date '+%F %T') $*" >> "$LOGF"; }
# setup is working on this folder right now: no repairing of its parts meanwhile (both at once corrupted them). The
# keyboard itself still starts if it can
BUSY=""
if [ -e "$CONF/installing" ] && [ $(( $(date +%s) - $(stat -c %Y "$CONF/installing" 2>/dev/null || echo 0) )) -lt 1800 ]; then
  BUSY=1
fi

# 1. The keyboard's Python parts (a SteamOS update can replace Python, which breaks them)
if ! venv/bin/python -c "import PIL, importlib.util as u; assert u.find_spec('openvr')" 2>/dev/null; then
  if [ -n "$BUSY" ]; then
    say "setup is still running: the keyboard starts once it's done"
    sleep 15
    exit 1
  fi
  last=$(cat "$CONF/repair-last" 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ $((now - last)) -lt 120 ]; then   # don't rebuild over and over while there's no internet yet
    sleep 20
    exit 1
  fi
  echo "$now" > "$CONF/repair-last"
  say "keyboard parts missing or broken (probably a SteamOS update): rebuilding them"
  rm -rf venv
  if ! { python3 -m venv venv && venv/bin/pip install --quiet openvr pillow; }; then
    say "rebuild didn't finish (no internet yet?), will try again"
    exit 1
  fi
  say "keyboard parts rebuilt"
fi

# 1b. The part that notices text boxes being selected (bundled with BetterFrame, so no internet needed)
if [ -x venv/bin/python ] && ! venv/bin/python -c "import jeepney" 2>/dev/null; then
  venv/bin/pip install --quiet --no-index vendor/jeepney-0.9.0-py3-none-any.whl 2>/dev/null && say "text box part put back"
fi

# 2. Valve's ARM64 OpenVR library (pip installs one for other computers)
SITE="$(venv/bin/python -c 'import os, importlib.util; print(os.path.dirname(importlib.util.find_spec("openvr").origin))' 2>/dev/null)"
if [ -n "$SITE" ] && ! cmp -s vendor/linuxarm64/libopenvr_api.so "$SITE/libopenvr_api_64.so"; then
  cp vendor/linuxarm64/libopenvr_api.so "$SITE/libopenvr_api_64.so" && say "put the ARM64 OpenVR library back"
fi

# 3. Voice typing parts: reinstalled in the background (takes a few minutes, the keyboard works meanwhile)
if [ -z "$BUSY" ] && ! venv/bin/python -c "import faster_whisper" 2>/dev/null; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
  if ! systemctl --user is-active --quiet betterframe-repair-voice 2>/dev/null; then
    say "voice typing parts missing: reinstalling them in the background"
    systemd-run --user --quiet --unit=betterframe-repair-voice --collect -p Nice=19 -p IOSchedulingClass=idle bash "$(pwd)/setup.sh" >/dev/null 2>&1 || true
  fi
fi

# 4. Permission to type (needs your password, so only reported)
if [ ! -w /dev/uinput ]; then
  say "typing permission is missing: run  bash ~/betterframe-keyboard/install.sh"
fi
exit 0
