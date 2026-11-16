#!/usr/bin/env bash
# Starts the BetterFrame Keyboard helper on http://localhost:8643
cd "$(dirname "$0")"
PY=python3
[ -x venv/bin/python ] && PY=venv/bin/python
# Emergency off switch
if [ -e "$HOME/.config/betterframe-keyboard/disabled" ]; then
  echo "BetterFrame Keyboard is turned off (remove ~/.config/betterframe-keyboard/disabled to turn it on)"
  exec sleep infinity
fi
# Just after boot, let Steam and SteamVR start first
UP=$(cut -d. -f1 /proc/uptime 2>/dev/null || echo 999)
if [ "$UP" -lt 180 ]; then
  export BF_PRELOAD_AFTER=$((180 - UP))
fi
# Low priority and only a couple of cores
export BF_THREADS="${BF_THREADS:-2}"
export OMP_NUM_THREADS="$BF_THREADS" OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
exec nice -n 15 "$PY" server.py --preload "$@"
