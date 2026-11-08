#!/usr/bin/env bash
# BetterFrame Keyboard: install or update. Safe to run again any time.
# Remove it again with:  bash ~/betterframe-keyboard/uninstall.sh   (or Steam Settings > Keyboard > Uninstall)
set -euo pipefail
cd "$(dirname "$0")"
CONF="$HOME/.config/betterframe-keyboard"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
echo "== BetterFrame Keyboard $(cat VERSION 2>/dev/null)"
mkdir -p "$CONF"
touch "$CONF/keyboard-only"
chmod +x ./*.sh
# the keyboard paused while its parts are set up (they start again at the end)
rm -f "$CONF/installing"   # (setup.sh marks itself while it works; nothing else may block the keyboard starting)
rm -f "$HOME"/.local/share/betterframe/vrapps/betterframe.stick*.vrmanifest   # (an earlier test's leftovers)
# voice typing still setting up from an earlier install: let it finish first (two at once broke the parts)
if systemctl --user is-active --quiet betterframe-repair-voice 2>/dev/null; then
  echo "-- Voice typing is still setting up from before: waiting for it to finish"
  flock "$CONF/setup.lock" true
fi
systemctl --user stop betterframe-overlay betterframe-keyboard 2>/dev/null || true

if ! venv/bin/python -c "import openvr, PIL" 2>/dev/null; then
  echo "-- First-time setup: the keyboard's parts"
  bash setup.sh --keyboard
else
  echo "-- Parts already installed"
fi
# the part that notices a text box being selected on the desktop (bundled: no download)
venv/bin/python -c "import jeepney" 2>/dev/null || venv/bin/pip install --quiet --no-index vendor/jeepney-0.9.0-py3-none-any.whl 2>/dev/null || true
bash install-overlay.sh
bash install-service.sh
# voice typing: set up in the background (a few minutes), so the keyboard works straight away
VOICE_LATER=""
if ! venv/bin/python -c "import faster_whisper, sherpa_onnx" 2>/dev/null || \
   [ ! -s models/sherpa-onnx-streaming-zipformer-en-2023-06-26/tokens.txt ]; then
  if systemd-run --user --quiet --unit=betterframe-repair-voice --collect -p Nice=19 -p IOSchedulingClass=idle bash "$(pwd)/setup.sh" --restart >/dev/null 2>&1; then
    VOICE_LATER=1
  else
    echo "-- Voice typing"
    bash setup.sh
  fi
fi

# Steam's interface has to let the keyboard in (on 127.0.0.1 only) for its settings in Steam's Keyboard page and
# for typing into games streamed from your PC. Same switch as Developer > CEF Remote Debugging.
STEAMDIR="$(readlink -f "$HOME/.steam/steam" 2>/dev/null || true)"
[ -d "$STEAMDIR" ] || STEAMDIR="$HOME/.local/share/Steam"
STEAM_RESTART=""
if [ -d "$STEAMDIR" ] && [ ! -e "$STEAMDIR/.cef-enable-remote-debugging" ]; then
  touch "$STEAMDIR/.cef-enable-remote-debugging" "$CONF/cef-by-betterframe"
  STEAM_RESTART=1
fi
touch "$CONF/steam-pages-on"
rm -f "$CONF/dash-pin-on"
# SteamVR's menu has to let the keyboard in too (127.0.0.1 only), so its keyboard button can say "Hide Keyboard"
# while the keyboard is open. Put back on uninstall, only if this turned it on
if [ -x /opt/steamvr/bin/linuxarm64/vrcmd ] && [ ! -e "$CONF/dash-debug-on" ]; then
  if venv/bin/python dashpin.py enable 2>/dev/null | grep -q "^now:"; then STEAM_RESTART=1; fi
fi

echo
echo "Done ($(cat VERSION 2>/dev/null)). It starts by itself, and repairs itself after SteamOS updates."
if [ -n "$VOICE_LATER" ]; then
  echo "Voice typing is finishing its setup in the background and will be ready in 2 to 5 minutes. Everything else works now."
fi
echo "Its settings are in Steam's Settings > Keyboard."
if [ -n "$STEAM_RESTART" ]; then
  echo "Restart the Frame once to finish setting up (the keyboard's settings in Steam, and its Show/Hide label)."
fi
