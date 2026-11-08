# BetterFrame Keyboard

https://github.com/user-attachments/assets/29c61a42-6596-427a-9c05-5c9858bbe455

An improved customizable keyboard for the Steam Frame. It replaces Steam Frame’s keyboard entirely, adding many requested features and accessibility options.

## Features

- Select All, Copy, Paste, Cut, Undo
- Minimal, Standard and Full keyboard layouts
- Swipe typing
- Voice typing
- 41 languages with native layouts
- QWERTY, QWERTZ, AZERTY, Dvorak, Colemak, Colemak-DH
- Japanese: romaji, kana and flick input, with kanji conversion
- Chinese: Zhuyin, Cangjie, Quick and Pinyin
- Korean: Hangul
- Steam Controller support
- Emoji page with Steam emoticons, Recent and Favorites
- Word suggestions
- 10 color themes
- Adjustable transparency backdrop
- Curvature toggle
- Key preview toggle
- Swappable order for Ctrl & Fn placement 
- 3 key sound options: Default, Light, Off
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

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/041d7e1c-8c0f-4be6-8e8f-21b0cb7413e3" />
BFrame Keyboard’s standard keyboard layout.

## Settings

Everything is at the top of Steam's **Settings > Keyboard**:

- Turn the keyboard on or off (off brings SteamVR's own keyboard back)
- Reset its size, position and tilt
- Uninstall it
- Pick a color theme
- Set how see-through the backdrop is
- Put the top bar above or below the keys, or turn it off
- Bottom row: .?123, Fn, Ctrl, or Ctrl, Fn
- Button labels on the top bar
- Always on top
- Languages
- Key layout
- Word suggestions
- Key preview
- Holding a key: repeat it, or type its capital
- Game controllers: type with the trackpads, the trackpads split in half, Steam's keyboard, or off
- Trackpad press: Light, Medium or Firm
- Controller face buttons (A types, X Backspace, Y Space, Menu Enter, B closes, left bumper Shift)
- Streamed games: type through Steam, or as key presses
- Key sound: Original, Light or Off
- Vibrate on each key

To add an emoji to Favorites, hold it for half a second.

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

<img width="1355" height="397" alt="image" src="https://github.com/user-attachments/assets/332ee2c3-228f-4582-9b55-99584e30cbe6" />
BFrame Keyboard’s full keyboard layout.

## License

MIT for the keyboard's own code. Word lists, dictionaries, fonts and the OpenVR library come under their own
licenses: see [NOTICES.md](NOTICES.md).
