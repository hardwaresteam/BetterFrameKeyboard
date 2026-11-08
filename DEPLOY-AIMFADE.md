# Fade when not aiming: deploy and test

## What it does

- Both controllers point at the keyboard: it's solid and you can type, as before.
- Point one controller away: after 0.2 s the keyboard fades to 25% (you can change this), and stops taking the
  lasers. They pass through to whatever is behind it.
- Point both back at it: it's solid and typeable again straight away.
- A small button on the keyboard's bottom edge, between the turn handle and the move bar, turns the feature on and
  off. It always takes the laser, even while the keyboard is faded. Blue means on, struck through means off.
- Steam **Settings > Keyboard** has two new rows: **Fade when not aiming** (on by default) and
  **How visible when faded** (5 to 100%).

It never fades in these cases:

- the first 0.75 s after the keyboard opens
- while you move, resize or tilt the keyboard
- while you hold a key, swipe or flick
- for 8 s after you type with a game controller's trackpads
- while you type by looking

## Install on the Frame

Copy `betterframe-keyboard-1.0.1-aimfade.zip` into `~/Downloads` on the Frame. Delete any older BetterFrame zip
there first. Then, in Desktop Mode, run this in Konsole:

```
cd ~ && python3 -m zipfile -e ~/Downloads/betterframe-keyboard-1.0.1-aimfade.zip . && bash ~/betterframe-keyboard/install.sh
```

The installer updates in place and keeps your settings. It ends with `Done (1.0.1-aimfade)`.

## Check it on the headset

1. Open the keyboard and point both lasers at it. It should be solid, and keys should type.
2. Point one controller at the Steam menu behind the keyboard. The keyboard should fade, and that laser should
   now work on the menu.
3. Point both back at it. It should be solid again.
4. Click the small button on the bottom edge. A message should say "Fade when not aiming: off", and the keyboard
   should stay solid.

To watch it work:

```
journalctl --user -u betterframe-overlay -f | grep -iE "see-through|solid|fade"
```

## Tuning (in `betterframe-keyboard/aimfade.py`)

| Setting | Default | What it changes |
|---|---|---|
| `LEAVE_S` | 0.2 | How long a laser has to be off the keyboard before it fades |
| `FADE_S` | 0.18 | How long the fade takes |
| `OPEN_GRACE_S` | 0.75 | How long it stays solid after opening |
| `LOOSE_PX` | 60 | How far past the edge (in keyboard pixels) a laser still counts as on it |
| `DEFAULT_AIM` | | The laser's angle on a controller until it has been learned |

After you change one, restart the keyboard:

```
systemctl --user restart betterframe-overlay
```

## If the fade misfires

While the keyboard is faded, it works out where each controller points from that controller's angle. It learns
each controller's laser angle from SteamVR as you type, and remembers it as `aim_dirs` in
`~/.config/betterframe-keyboard/overlay.json`.

On a fresh install it starts from a guess. If the first few seconds feel off, type a little with both hands so it
learns the real angle.

## Undo

To turn the feature off, use the switch in Settings or the button on the keyboard. To go back to stock, reinstall
the 1.0.0 zip.
