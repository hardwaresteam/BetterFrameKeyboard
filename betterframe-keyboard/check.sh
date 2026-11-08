#!/usr/bin/env bash
# BetterFrame after a SteamOS update: checks every part it depends on and saves the results to
# ~/Downloads/bf-check.txt. It only looks: nothing is changed, installed or restarted.
# Run in Desktop Mode with SteamVR running (headset on).
cd "$(dirname "$0")"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
OUT="$HOME/Downloads/bf-check.txt"
CONF="$HOME/.config/betterframe-keyboard"
mkdir -p "$HOME/Downloads"
ok() { echo "  OK    $*"; }
bad() { echo "  FAIL  $*"; }
{
echo "== BetterFrame $(cat VERSION 2>/dev/null)   $(date)"
echo "== SteamOS: $(grep -h -E '^(VERSION_ID|BUILD_ID)=' /etc/os-release 2>/dev/null | tr '\n' ' ')  kernel $(uname -r)"
echo "== Python: $(python3 --version 2>&1)   keyboard's own: $(venv/bin/python --version 2>&1)"

echo "== parts"
venv/bin/python -c "import openvr, PIL" 2>/dev/null && ok "keyboard parts (openvr, pillow)" || bad "keyboard parts: missing or broken"
venv/bin/python -c "import faster_whisper, sherpa_onnx" 2>/dev/null && ok "voice typing parts" || bad "voice typing parts: missing or broken"
[ -s models/sherpa-onnx-streaming-zipformer-en-2023-06-26/tokens.txt ] && ok "live voice model" || bad "live voice model missing"
[ -w /dev/uinput ] && ok "typing access (/dev/uinput)" || bad "typing access: /dev/uinput isn't writable"

echo "== running"
for u in betterframe-overlay betterframe-keyboard; do
  s=$(systemctl --user is-active "$u" 2>/dev/null)
  [ "$s" = active ] && ok "$u" || bad "$u is $s"
done
pgrep -f "betterframe-keyboard/overlay.py|overlay.py" >/dev/null && ok "keyboard program running" || bad "keyboard program not running"
pgrep -x vrcompositor >/dev/null || pgrep -f vrcompositor >/dev/null && ok "SteamVR running" || bad "SteamVR not running (start it and run this again)"

echo "== Steam's settings pages and typing into Steam"
STEAMDIR="$(readlink -f "$HOME/.steam/steam" 2>/dev/null)"; [ -d "$STEAMDIR" ] || STEAMDIR="$HOME/.local/share/Steam"
[ -e "$STEAMDIR/.cef-enable-remote-debugging" ] && ok "Steam lets the keyboard in (CEF switch on)" || bad "Steam's CEF switch is off (the update may have reset it)"
if curl -s -m 3 http://127.0.0.1:8080/json >/tmp/bf-pages.json 2>/dev/null && [ -s /tmp/bf-pages.json ]; then
  ok "Steam's pages reachable ($(grep -c '"type": "page"' /tmp/bf-pages.json) pages)"
  grep -o '"title": "[^"]*"' /tmp/bf-pages.json | sort | uniq -c | sed 's/^/        /' | head -20
else
  bad "Steam's pages not reachable on 127.0.0.1:8080"
fi
rm -f /tmp/bf-pages.json

if [ -f pointer/install.sh ]; then
  echo "== pointer add-on"
  bash pointer/install.sh status 2>&1 | sed 's/^/        /' | head -8
fi

echo "== what the keyboard said since SteamVR started (problems first)"
journalctl --user -u betterframe-overlay -b --no-pager 2>/dev/null | grep -iE "traceback|error|exception|can't|couldn't|failed|refus" | tail -25
echo "   --"
journalctl --user -u betterframe-overlay -b --no-pager 2>/dev/null | grep -iE "connected to steamvr|waiting for steamvr|reconnect|keyboard asked|typing into|settings pages|steam pages|trackpads|controller|text box" | tail -40
echo "== repair log (last lines)"
tail -8 "$CONF/repair.log" 2>/dev/null
echo "== done"
} 2>&1 | tee "$OUT"
echo
echo "Saved: $OUT"
