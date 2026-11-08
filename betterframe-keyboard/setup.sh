#!/usr/bin/env bash
# BetterFrame Keyboard setup.
# Installs voice typing (faster-whisper, sherpa-onnx) and speech (Piper) into THIS folder only.
# Nothing is installed system-wide, so SteamOS updates won't remove it.
# The three model downloads run at the same time as the Python parts install, so the wait is mostly one download.
#   bash setup.sh             everything (voice typing too)
#   bash setup.sh --keyboard  just the keyboard's own parts (under a minute): install.sh does this, then the rest
#                             in the background (bash setup.sh --restart), so the keyboard works straight away
set -euo pipefail
MODE="${1:-}"
cd "$(dirname "$0")"

MODEL="${BF_STT_MODEL:-base.en}"
VOICE="${BF_VOICE:-en_US-lessac-medium}"
VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
LIVE=sherpa-onnx-streaming-zipformer-en-2023-06-26
LIVE_URL="https://huggingface.co/csukuangfj/$LIVE/resolve/main"
LIVE_TAG="epoch-99-avg-1-chunk-16-left-128.int8.onnx"
WHISPER_URL="https://huggingface.co/Systran/faster-whisper-$MODEL/resolve/main"
START=$(date +%s)
took() { local s=$(( $(date +%s) - START )); printf '%dm %02ds' $((s / 60)) $((s % 60)); }

echo "== BetterFrame Keyboard setup"
command -v python3 >/dev/null || { echo "python3 wasn't found on this system."; exit 1; }
command -v curl >/dev/null || { echo "curl wasn't found on this system."; exit 1; }
CONF="$HOME/.config/betterframe-keyboard"
mkdir -p "$CONF"
# one setup at a time (a second one waits): two working on the same folder at once broke pip
exec 9>"$CONF/setup.lock"
flock 9
touch "$CONF/installing"
PIDS=()
trap 'rm -f "$CONF/installing"; for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done' EXIT

make_venv() {
  if [ -x venv/bin/python ] && ! venv/bin/python -m pip --version >/dev/null 2>&1; then
    echo "   The Python environment was damaged: making it again"
    rm -rf venv
  fi
  if [ ! -x venv/bin/python ]; then
    if ! python3 -m venv venv; then
      echo "Couldn't make a Python environment. Python on this system is missing venv support; try a distrobox setup instead."
      exit 1
    fi
  fi
}
if [ "$MODE" = "--keyboard" ]; then
  make_venv
  venv/bin/python -m pip install --quiet openvr pillow
  echo "   Keyboard parts ready ($(took))"
  exit 0
fi

echo "   Voice typing: about 440 MB to download, usually 2 to 5 minutes."

# ---- 1. the downloads, in the background (each file lands under its own name only once it's complete)
get() {  # get URL FILE: download, retrying a few times; a half-finished file is never left under the real name
  [ -s "$2" ] && return 0
  curl -fsSL --retry 4 --retry-delay 2 --connect-timeout 20 -o "$2.part" "$1" && mv "$2.part" "$2"
}
mkdir -p models voices "models/faster-whisper-$MODEL"
(
  d="models/$LIVE"; mkdir -p "$d"
  ok=1
  for f in encoder decoder joiner; do get "$LIVE_URL/$f-$LIVE_TAG" "$d/$f-$LIVE_TAG" || ok=0; done
  get "$LIVE_URL/tokens.txt" "$d/tokens.txt" || ok=0
  if [ "$ok" = 0 ]; then   # (that site unreachable: the full package from GitHub instead, bigger but the same model)
    rm -f "$d"/*.part
    get "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$LIVE.tar.bz2" "models/$LIVE.tar.bz2" &&
      python3 -c "import tarfile; tarfile.open('models/$LIVE.tar.bz2').extractall('models')" &&
      rm -f "models/$LIVE.tar.bz2" &&
      find "$d" -name "*.onnx" ! -name "*.int8.onnx" -delete && rm -rf "$d/test_wavs"
  fi
) > models/.live.log 2>&1 &
PIDS+=($!); LIVE_PID=$!
( get "$VOICE_URL/$VOICE.onnx?download=true" "voices/$VOICE.onnx" &&
  get "$VOICE_URL/$VOICE.onnx.json?download=true" "voices/$VOICE.onnx.json" ) > voices/.get.log 2>&1 &
PIDS+=($!); VOICE_PID=$!
( for f in config.json tokenizer.json vocabulary.txt model.bin; do
    get "$WHISPER_URL/$f" "models/faster-whisper-$MODEL/$f" || exit 1
  done ) > "models/.whisper.log" 2>&1 &
PIDS+=($!); WHISPER_PID=$!

# ---- 2. the private Python environment
echo "-- [1/3] Python environment"
make_venv
venv/bin/python -m pip install --quiet --upgrade pip || true

# ---- 3. every Python part in one go (shared pieces are fetched once)
echo "-- [2/3] Voice typing and the keyboard's parts ($(took))"
# the audio library: the older versions on Python up to 3.13 (as always); from Python 3.14 (SteamOS 0.5.7) only the
# newer ones have ready-made builds (building it on the Frame fails). Ready-made builds only, never built here
AV="av<15"
if [ "$(venv/bin/python -c 'import sys; print(sys.version_info >= (3, 14))')" = True ]; then AV="av>=18"; fi
if ! venv/bin/python -m pip install --quiet --prefer-binary --only-binary av faster-whisper "$AV" sherpa-onnx openvr pillow piper-tts; then
  # (Piper is the one that sometimes has no build for a system: everything else without it)
  venv/bin/python -m pip install --quiet --prefer-binary --only-binary av faster-whisper "$AV" sherpa-onnx openvr pillow
fi

# ---- 4. the downloads finish
echo "-- [3/3] Finishing the downloads ($(took))"
wait "$LIVE_PID" || true
wait "$VOICE_PID" || true
wait "$WHISPER_PID" || true
PIDS=()
if [ ! -s "models/$LIVE/tokens.txt" ]; then
  echo "   Real-time voice typing's model didn't download (check the internet, then run the install again)."
fi
if [ ! -s "models/faster-whisper-$MODEL/model.bin" ]; then
  # (the direct download failed: let the voice typing library fetch it its own way)
  rm -rf "models/faster-whisper-$MODEL"
  HF_HUB_VERBOSITY=error HF_HUB_DISABLE_PROGRESS_BARS=1 venv/bin/python - <<PY || echo "   Voice typing's model didn't download (check the internet, then run the install again)."
from faster_whisper import WhisperModel
WhisperModel("$MODEL", device="cpu", compute_type="int8")
PY
fi
rm -f models/.live.log voices/.get.log models/.whisper.log
echo "   Setup done in $(took)"
if [ "$MODE" = "--restart" ]; then   # (set up in the background after an install: voice typing picks it up now)
  systemctl --user try-restart betterframe-keyboard 2>/dev/null || true
fi
