# Third-party parts

The keyboard's own code is under the MIT License (see LICENSE). These parts come with it under their own licenses:

| Part | Where | License |
|---|---|---|
| Word lists for swipe typing, made from wordfreq (Robyn Speer and contributors) | `words/` | CC BY-SA 4.0 (see `words/NOTICE.txt`) |
| Japanese, Chinese and Korean conversion dictionaries (Mozc and others) | `ime/` | see `ime/NOTICE.txt` |
| Noto Sans Arabic, Hebrew, Devanagari and Thai fonts | `fonts/` | SIL Open Font License 1.1 (`fonts/OFL.txt`) |
| Emoji list and search words, Unicode emoji-test.txt and CLDR | `emoji_data.py` | Unicode License v3 (`EMOJI-NOTICE.txt`) |
| OpenVR runtime library for ARM64 (Valve) | `vendor/linuxarm64/` | BSD 3-Clause (`vendor/linuxarm64/OPENVR-LICENSE`) |
| three.js | `vendor/` | MIT |
| jeepney (D-Bus for Python, Thomas Kluyver), for noticing text boxes being selected | `vendor/` | MIT (inside the .whl) |

Downloaded during setup (not included here): faster-whisper and its Whisper model (MIT), sherpa-onnx and its
streaming English model (Apache 2.0), Piper and the "lessac" voice (MIT / see the voice's model card), openvr for
Python (BSD 3-Clause), Pillow (MIT-CMU).
