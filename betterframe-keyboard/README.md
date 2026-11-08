# BetterFrame Keyboard

<img width="2617" height="1530" alt="image" src="keyboard.png" />
An improved customizable keyboard for the Steam Frame. It replaces Steam Frame’s keyboard entirely, adding many requested features and accessibility options.

## Features

- Minimal, Standard and Full (full sized keyboard) layouts
- Swipe typing
- Voice typing
- 41 languages with native layouts
- QWERTY, QWERTZ, AZERTY, Dvorak, Colemak, Colemak-DH
- Japanese: romaji, kana and flick input, with kanji conversion
- Chinese: Zhuyin, Cangjie, Quick and Pinyin
- Korean: Hangul
- Japanese and Chinese show up live in Steam's search and chat as you type
- Emoji page with Steam emoticons, emoji search, Recent and Favorites
- Word suggestions
- Game controller typing:
  - Steam Controller (new and 2015) and PS5 controller: type with the trackpads, press the pad or pull a trigger to type (Light, Medium or Firm press)
  - Xbox, Switch Pro, 8BitDo and others: move between keys with the sticks and D-pad
  - Steam's menus, mouse and desktop leave the controller alone while you type
- Types straight into Steam's own text boxes (Store, Library, chat) and into games streamed from your PC
  (streamed PCs get English letters, numbers, symbols, Backspace, Enter and Tab: that's all Steam passes on)
- Fn key with media keys, and double-tap Ctrl, Alt or Fn to lock it on
- 10 color themes
- Adjustable transparency backdrop
- Fade when not aiming: unless both controllers point at it, the keyboard turns see-through and lets the lasers through to what's behind it (a small button on its bottom edge turns this on and off)
- Curvature toggle
- Undo, Cut, Copy, Paste, Select all
- Key preview, key sounds and button labels
- Resize, tilt and readjust with ease
- Easy enable/disable toggle, reset and uninstall

## Install

On the Frame, in Desktop Mode, download `betterframe-keyboard-1.0.0.zip` from this page's
[Releases](../../releases/latest) into Downloads, open Konsole and run:

```
cd ~ && python3 -m zipfile -e ~/Downloads/betterframe-keyboard-1.0.0.zip . && bash ~/betterframe-keyboard/install.sh
```

The first install takes about a minute, and voice typing finishes setting up by itself within 5 minutes. It asks for your
Frame password once, so the keyboard is allowed to type into apps. After that it starts by itself, and repairs itself after
SteamOS updates.

<img width="1920" height="1080" alt="image" src="advanced.png" />
BFrame Keyboard’s full layout.

## Settings

Everything is at the top of Steam's **Settings > Keyboard**:

- Turn the keyboard on or off (off brings SteamVR's own keyboard back)
- Reset its size, position and tilt
- Uninstall it
- Pick a color theme and set how see-through the backdrop is
- Put the top bar above or below the keys, or turn it off
- Bottom row: .?123, Fn, Ctrl, or Ctrl, Fn like a laptop
- Button labels on the top bar
- Always on top
- Fade when not aiming, and how visible it is while faded
- Holding a key: repeat it, or type its capital
- Language, key layout, key preview and word suggestions
- Game controllers: type with the trackpads, the trackpads split in half, Steam's keyboard, or off
- Trackpad press: Light, Medium or Firm
- Controller face buttons
- Streamed games: type through Steam, or as key presses
- Key sound: Original, Light or Off

To add an emoji to Favorites, hold it for half a second.

## Game controllers

With the keyboard open:

- Trackpads: each one moves its own highlight; press the pad or pull that side's trigger to type
- Sticks and D-pad: step from key to key
- A types, X Backspace, Y Space, Menu Enter, B closes the keyboard
- Hold X, or hold a press on Backspace, Delete or an arrow key, to keep it going
- Left stick click or left bumper: Shift (twice quickly for Caps Lock)
- Steam + X (or View + Menu) opens and closes the keyboard from anywhere

## Uninstall

Steam's **Settings > Keyboard > Uninstall** (click it twice), or in a terminal:

```
bash ~/betterframe-keyboard/uninstall.sh
```

Then restart SteamVR to get its own keyboard back. To delete the files too:
`rm -rf ~/betterframe-keyboard ~/.config/betterframe-keyboard`

## Updating

Download the new zip, delete the old one from Downloads, and run the same install command again. Your settings
are kept.

<img width="2732" height="1532" alt="image" src="minimal.png" />
BFrame Keyboard’s minimal layout.

## License

MIT for the keyboard's own code. Word lists, dictionaries, fonts and the OpenVR library come under their own
licenses: see [NOTICES.md](NOTICES.md).
