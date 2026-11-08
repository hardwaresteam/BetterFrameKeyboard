#!/usr/bin/env python3
"""BetterFrame Keyboard overlay: a system-wide VR keyboard for the Steam Frame.

It is a SteamVR overlay, so it floats over everything: Desktop Mode, games, the Steam menu.
You point at it with the normal SteamVR laser. Keys are typed into whatever text box has focus
through a virtual keyboard device (/dev/uinput), exactly as if a real keyboard were plugged in.

Voice typing uses the BetterFrame helper (server.py) that is already running on the headset.

Run:  venv/bin/python overlay.py          (install-overlay.sh sets it up as a background service)
      venv/bin/python overlay.py --preview DIR   draws the layouts to PNG files, no VR needed
"""
import ctypes
import fcntl
import json
import math
import os
import re
import struct
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FLOOR_MIN = 0.12   # metres: the keyboard is never lower than this (SteamVR's floor is height 0)
CONF_DIR = os.path.expanduser("~/.config/betterframe-keyboard")
CONF_PATH = os.path.join(CONF_DIR, "overlay.json")
HELPER = "http://127.0.0.1:8643"
LOG = lambda *a: print("[overlay]", *a, flush=True)

DEFAULTS = {
    "layout": "minimal",            # minimal (big keys) or full
    "sounds": True,
    "volume": 0.5,                  # 0 to 1
    "start_visible": False,         # appear only when you ask for it
    "replace_system_keyboard": True,  # SteamVR's keyboard button opens and closes this one instead
    "dictation_punctuation": False,   # False: no periods or commas from voice typing
    "font": "",                     # path to a .ttf/.otf; empty = best system font
    "pitch_minimal": [0.084, 0.064],  # key pitch in metres (width, height) at size 1
    "pitch_full": [0.072, 0.062],
    "pitch_advanced": [0.066, 0.058],  # full-size keyboard: keys nearly as big as Full's, so they're easy to hit
    "size_version": 5,
    "curved": True,                 # bends around you like a curved monitor, so wide keyboards are easy to reach
    "curve_radius": 0.95,           # metres (about how far the keyboard is from your eyes, so every key faces you)
    "scale": 0.6,                   # set by the resize corner (starts about as wide as SteamVR's own keyboard)
    # where it opens, like SteamVR's own keyboard: in front, about chest height, leaning back like a laptop
    "distance": 0.72,               # metres in front of your eyes (level distance)
    "drop": 0.68,                   # metres below your eyes (sits under the Steam bar, not on it)
    "side": 0.0,                    # degrees left/right of straight ahead (set when you move it)
    "tilt": 15,                     # extra lean-back in degrees when it sits below your eyes
    "place_version": 5,
    "two_hands": "native",          # native: SteamVR draws a laser per controller; "own": draw our own; "off"
    "hand_button": False,           # small open/close button on the left controller
    "panel": True,                  # slightly see-through back behind the keys
    "panel_opacity": 1.0,           # 0 = invisible, 1 = solid
    "lang": "en-US",                # keyboard language (the globe button)
    "swipe": False,                 # swipe typing (the curvy-line button)
    "fmt": "default",               # key layout: default (the language's own), qwerty, qwertz, azerty, dvorak, colemak, colemak-dh
    "bubble": True,                 # little bubble above the key you point at, showing its letter (Key preview)
    "words": False,                 # word bar above the keys: the word you're swiping as you go, and word suggestions
    "wing_side": "right",           # Advanced layout: which side the numpad / editing-keys wing sits on
    "wing_v": 2,
    "wing_angle": 24,               # ...and how far it's turned toward you, in degrees
    "paste_keys": "shift+insert",   # how letters a US keyboard doesn't have are pasted in: "shift+insert" (works in terminals too) or "ctrl+v"
    "edit_keys": "universal",       # Copy/Cut/Paste buttons: "universal" (Ctrl+Insert / Shift+Delete / Shift+Insert, works in Konsole and apps) or "ctrl"
    "keys_version": 2,
}


def load_conf():
    c = dict(DEFAULTS)
    saved = {}
    try:
        with open(CONF_PATH) as f:
            saved = json.load(f)
        c.update(saved)
    except Exception:
        pass
    if saved and saved.get("wing_v", 1) < 2:  # the wing now sits on the right, like a real keyboard
        c["wing_side"], c["wing_v"] = "right", 2
    if saved and saved.get("place_version", 1) < 5:  # older builds saved the keyboard's middle, not its letters
        for k in ("distance", "drop", "tilt", "place_version", "side") + (("two_hands",) if saved.get("place_version", 1) < 3 else ()):
            c[k] = DEFAULTS[k]
    if saved and saved.get("size_version", 1) == 2:  # one build shrank the keyboard by mistake: back to the normal size
        for k in ("pitch_minimal", "pitch_full", "pitch_advanced", "size_version", "scale"):
            c[k] = DEFAULTS[k]
    if saved and saved.get("size_version", 1) < 5:  # Full's and Advanced's keys were a bit small to hit comfortably
        c["pitch_full"], c["pitch_advanced"], c["size_version"] = DEFAULTS["pitch_full"], DEFAULTS["pitch_advanced"], 5
    if saved and saved.get("keys_version", 1) < 2:  # Ctrl+V pasted "^V" into terminals; Shift+Insert works everywhere
        c["paste_keys"], c["edit_keys"], c["keys_version"] = "shift+insert", "universal", 2
    return c


def save_conf(c):
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(CONF_PATH, "w") as f:
            json.dump(c, f, indent=2)
    except Exception as e:
        LOG("couldn't save settings:", e)


# --------------------------------------------------------------------------- virtual keyboard (uinput)
EV_SYN, EV_KEY, SYN_REPORT = 0, 1, 0
UI_SET_EVBIT, UI_SET_KEYBIT, UI_DEV_CREATE, UI_DEV_DESTROY = 0x40045564, 0x40045565, 0x5501, 0x5502
KEY = dict(ESC=1, MINUS=12, EQUAL=13, BACKSPACE=14, TAB=15, LEFTBRACE=26, RIGHTBRACE=27, ENTER=28, LEFTCTRL=29,
           SEMICOLON=39, APOSTROPHE=40, GRAVE=41, LEFTSHIFT=42, BACKSLASH=43, COMMA=51, DOT=52, SLASH=53,
           LEFTALT=56, SPACE=57, F1=59, F2=60, F3=61, F4=62, F5=63, F6=64, F7=65, F8=66, F9=67, F10=68, F11=87, F12=88,
           LEFT=105, RIGHT=106, UP=103, DOWN=108, INSERT=110, DELETE=111, LEFTMETA=125,
           HOME=102, END=107, PAGEUP=104, PAGEDOWN=109, MUTE=113, VOLUMEDOWN=114, VOLUMEUP=115,
           NEXTSONG=163, PLAYPAUSE=164, PREVIOUSSONG=165, SYSRQ=99, SCROLLLOCK=70, PAUSE=119)
# Fn layer (Full layout): what keys do while Fn is on
FN = {"f1": ("Mute", "MUTE"), "f2": ("Vol −", "VOLUMEDOWN"), "f3": ("Vol +", "VOLUMEUP"), "f4": ("Prev", "PREVIOUSSONG"),
      "f5": ("Play", "PLAYPAUSE"), "f6": ("Next", "NEXTSONG"), "f12": ("Print", "SYSRQ"), "del": ("Insert", "INSERT"),
      "left": ("Home", "HOME"), "right": ("End", "END"), "up": ("PgUp", "PAGEUP"), "down": ("PgDn", "PAGEDOWN")}
for i, c in enumerate("1234567890"):
    KEY[c] = 2 + i
for row, start in (("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44)):
    for i, c in enumerate(row):
        KEY[c] = start + i
KEY_NAME = {v: k for k, v in KEY.items()}   # (key code -> its name: for keys sent to a streamed game)
BASE = {"-": 12, "=": 13, "[": 26, "]": 27, ";": 39, "'": 40, "`": 41, "\\": 43, ",": 51, ".": 52, "/": 53, " ": 57, "\t": 15, "\n": 28}
SHIFTED = {"!": 2, "@": 3, "#": 4, "$": 5, "%": 6, "^": 7, "&": 8, "*": 9, "(": 10, ")": 11, "_": 12, "+": 13,
           "{": 26, "}": 27, ":": 39, '"': 40, "~": 41, "|": 43, "<": 51, ">": 52, "?": 53}


class VKeyboard:
    """A virtual keyboard device. Needs write access to /dev/uinput (install-overlay.sh sets that up)."""

    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_SYN)
        for code in range(1, 249):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        dev = struct.pack("80sHHHHi", b"BetterFrame Keyboard", 0x03, 0x1209, 0xBF01, 1, 0) + bytes(64 * 4 * 4)
        os.write(self.fd, dev)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.4)

    def _ev(self, typ, code, value):
        os.write(self.fd, struct.pack("llHHi", 0, 0, typ, code, value))

    def _sync(self):
        self._ev(EV_SYN, SYN_REPORT, 0)

    @staticmethod
    def _pack(typ, code, value):
        return struct.pack("llHHi", 0, 0, typ, code, value)

    def tap(self, code, mods=()):
        """Press and let go, sent to the system in ONE write: the press and the let-go can never be split up.
        (Sent separately, the keyboard being held up for a moment in between, or the let-go failing, left the key
        down, and the system's own key repeat then typed it over and over: "seeeeeeee")"""
        ev = b"".join(self._pack(EV_KEY, m, 1) for m in mods)
        ev += self._pack(EV_KEY, code, 1) + self._pack(EV_SYN, SYN_REPORT, 0)
        ev += self._pack(EV_KEY, code, 0) + b"".join(self._pack(EV_KEY, m, 0) for m in reversed(mods))
        ev += self._pack(EV_SYN, SYN_REPORT, 0)
        for attempt in range(3):
            try:
                n = os.write(self.fd, ev)
                if n != len(ev):
                    self.let_go(code, mods)   # (only part of it went: never leave a key down, never press it twice)
                break
            except BlockingIOError:   # the system is busy for a moment: nothing went, so try again
                time.sleep(0.01)
            except OSError:
                self.let_go(code, mods)
                break
        else:
            self.let_go(code, mods)
        time.sleep(0.004)

    def release_mods(self):
        """Shift, Ctrl, Alt and the Windows key up, both sides (harmless when they're up already: nothing changes)."""
        codes = [KEY[n] for n in ("LEFTSHIFT", "LEFTCTRL", "LEFTALT", "LEFTMETA") if n in KEY] + [54, 97, 100, 126]
        up = b"".join(self._pack(EV_KEY, c, 0) for c in codes) + self._pack(EV_SYN, SYN_REPORT, 0)
        for _ in range(10):
            try:
                os.write(self.fd, up)
                return
            except BlockingIOError:
                time.sleep(0.02)

    def let_go(self, code, mods=()):
        """Make sure a key (and its Shift/Ctrl) is up, whatever happened (it's harmless if it already is)."""
        up = self._pack(EV_KEY, code, 0) + b"".join(self._pack(EV_KEY, m, 0) for m in mods) + self._pack(EV_SYN, SYN_REPORT, 0)
        for _ in range(5):
            try:
                os.write(self.fd, up)
                return
            except OSError:
                time.sleep(0.02)

    @staticmethod
    def can_type(ch):
        low = ch.lower()
        return ch in BASE or ch in SHIFTED or (low in KEY and len(low) == 1)

    def type_text(self, s):
        missed = 0
        for ch in s:
            low = ch.lower()
            if ch in BASE:
                self.tap(BASE[ch])
            elif ch in SHIFTED:
                self.tap(SHIFTED[ch], (KEY["LEFTSHIFT"],))
            elif low in KEY and len(low) == 1:
                self.tap(KEY[low], (KEY["LEFTSHIFT"],) if ch != low else ())
            else:
                missed += 1
        return missed

    def combo(self, *names):
        codes = [KEY[n] for n in names]
        self.tap(codes[-1], tuple(codes[:-1]))

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            os.close(self.fd)
        except Exception:
            pass


# --------------------------------------------------------------------------- sounds
def make_click(kind="key", volume=0.5):
    """The "Light" key sound: a soft tap that eases in and fades quickly; space and Enter a touch lower."""
    import random
    rate = 48000
    dur = 0.032 if kind == "key" else 0.042
    low, mid = (300, 1500) if kind == "key" else (220, 1150)
    rnd = random.Random(3)
    out = bytearray()
    prev = prev2 = 0.0
    for i in range(int(rate * dur)):
        t = i / rate
        body = math.sin(2 * math.pi * low * t) * math.exp(-t * 140) * 0.35
        tap = math.sin(2 * math.pi * mid * t + 0.3) * math.exp(-t * 330) * 0.6
        n = rnd.random() * 2 - 1
        prev = prev * 0.75 + n * 0.25
        prev2 = prev2 * 0.75 + prev * 0.25
        tick = prev2 * math.exp(-t * 900) * 0.35
        attack = min(1.0, t / 0.003) ** 2
        fade = min(1.0, (dur - t) / 0.006)
        v = (body + tap + tick) * attack * fade * 0.45 * volume
        out += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
    return bytes(out)


def make_click_deep(kind="key", volume=0.5):
    """The "Original" key sound (the default): a rounded 'thock' like a mechanical key; space and Enter a little deeper."""
    import random
    rate = 48000
    dur = 0.045 if kind == "key" else 0.06
    low, mid = (175, 820) if kind == "key" else (120, 560)
    rnd = random.Random(3)
    out = bytearray()
    prev = 0.0
    for i in range(int(rate * dur)):
        t = i / rate
        thump = math.sin(2 * math.pi * low * t) * math.exp(-t * 70)
        knock = math.sin(2 * math.pi * mid * t + 0.4) * math.exp(-t * 260) * 0.55
        n = rnd.random() * 2 - 1
        prev = prev * 0.6 + n * 0.4            # soften the noise
        tick = prev * math.exp(-t * 1400) * 0.5
        attack = min(1.0, t / 0.002) ** 2           # (eases in: no hard edge at the start)
        fade = min(1.0, (dur - t) / 0.008)          # (and fades out: it used to stop dead, a tiny extra tick at the end)
        v = (thump * 0.7 + knock + tick) * attack * fade * (0.32 if kind == "key" else 0.24) * volume   # (space/Enter as loud as a key)
        out += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
    return bytes(out)


class Sounds:
    """While the keyboard is open, one audio stream stays open and a click is written the moment a key is
    pressed. While it's hidden the stream is closed, so it costs nothing."""

    def __init__(self, volume):
        self.set_volume(volume)
        self.proc = None
        self.lock = threading.Lock()

    def open_async(self):
        threading.Thread(target=self.open, daemon=True).start()

    def close(self):
        with self.lock:
            p, self.proc = self.proc, None
        if p:
            try:
                p.stdin.close()
                p.terminate()
            except Exception:
                pass

    def open(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
        proc = None
        for cmd in (["pw-cat", "--playback", "--raw", "--format", "s16", "--rate", "48000", "--channels", "1", "--latency", "128", "-"],
                    ["pacat", "--raw", "--format=s16le", "--rate=48000", "--channels=1", "--latency-msec=5"],
                    ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "48000", "-c", "1", "-B", "10000"]):
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
                time.sleep(0.2)
                if proc.poll() is None:
                    break
                proc = None
            except FileNotFoundError:
                continue
        if proc:
            try:  # never wait on the audio system: a write that can't go through right away is dropped
                os.set_blocking(proc.stdin.fileno(), False)
            except Exception:
                pass
        with self.lock:
            self.proc = proc

    def set_volume(self, v, style="light"):
        """The key sound (Original or Light, Settings > Keyboard) at this volume (0 to 1). Each click starts with 12 ms
        of silence: the sound output wakes up for each click and that first moment can come out muffled or cut, which
        took the crisp start off the click (Light, mostly), so it now falls on silence instead."""
        f = make_click_deep if style == "deep" else make_click
        pre = b"\0\0" * int(48000 * 0.012)
        self.clicks = {"key": pre + f("key", v), "big": pre + f("big", v)}
        self.style, self.volume = style, v

    def queued(self, p):
        """Bytes of sound still waiting to be played."""
        try:
            import array
            import termios
            n = array.array("i", [0])
            fcntl.ioctl(p.stdin.fileno(), termios.FIONREAD, n)
            return n[0]
        except Exception:
            return 0

    def play(self, kind="key"):
        """Never blocks. If the last click is still waiting to play (e.g. holding Backspace repeats faster
        than a click lasts), this one is skipped instead of piling up and freezing the keyboard."""
        p = self.proc
        if not p:
            return
        click = self.clicks[kind]
        if self.queued(p) > len(click) // 3:
            return
        try:
            n = p.stdin.write(click)
            if n is not None and n < len(click) and n % 2:  # keep 16-bit samples aligned after a partial write
                p.stdin.write(b"\0")
        except (BlockingIOError, InterruptedError):
            pass
        except Exception:
            self.proc = None


# --------------------------------------------------------------------------- letters a US keyboard doesn't have
class QueuedKeyboard:
    """Sends key presses from a background worker, strictly in order. Pasting a special letter needs the
    clipboard tools, which can take a moment; with this the keyboard itself never waits for them."""

    def __init__(self, vk):
        import queue
        self.vk = vk
        self.q = queue.Queue()
        self._can_type = vk.can_type
        self.stream = None  # a streamed game asked for the keyboard: text goes to it through Steam (see StreamText)
        threading.Thread(target=self._work, daemon=True).start()

    def can_type(self, ch):
        return True if self.stream else self._can_type(ch)

    def _work(self):
        import queue
        dirty = False
        while True:
            try:
                fn, args = self.q.get(timeout=0.4)
            except queue.Empty:
                if dirty:   # typing stopped a moment ago: make sure no Shift / Ctrl / Alt is left down by accident
                    dirty = False
                    try:
                        self.vk.release_mods()
                    except Exception:
                        pass
                    st = self.stream
                    if st is not None and hasattr(st, "let_go"):
                        st.let_go()
                continue
            dirty = True
            try:
                fn(*args)
            except Exception as ex:
                LOG("typing error:", ex)

    def tap(self, code, mods=()):
        st = self.stream
        if st and not mods and code in st.KEYS:
            self.q.put((st.send, (st.KEYS[code],)))
            return
        if st is not None and hasattr(st, "key"):
            # a streamed game: arrows, Delete, Home, Esc and keys with Ctrl/Alt go to the game as key presses
            name = KEY_NAME.get(code)
            mod_names = [KEY_NAME.get(m) for m in mods]
            if name and None not in mod_names:
                self.q.put((st.key, (name if len(name) > 1 else name.lower(), mod_names)))
                return
        self.q.put((self.vk.tap, (code, mods)))

    def combo(self, *names):
        st = self.stream
        if st is not None and hasattr(st, "combo"):
            self.q.put((st.combo, names))
            return
        self.q.put((self.vk.combo, names))

    def type_text(self, s):
        if self.stream:
            self.q.put((self.stream.send, (s,)))
            return 0
        self.q.put((self.vk.type_text, (s,)))
        return 0

    def call(self, fn, *args):
        self.q.put((fn, args))

    def close(self):
        self.vk.close()


class StreamText:
    """Typing into a game streamed from a PC (Steam Link / Remote Play in VR). Key presses made on the headset
    don't reach the PC, so the text goes the way Steam's own keyboard sends it: through Steam, which passes it
    to the game. Games read it as plain text (English letters, digits and symbols)."""
    KEYS = {}

    def __init__(self, url):
        self.url = url
        StreamText.KEYS = {KEY["BACKSPACE"]: "\b", KEY["ENTER"]: "\n", KEY["TAB"]: "\t", KEY["SPACE"]: " "}

    @staticmethod
    def find():
        """The Steam page that can send text to a streamed game, or None."""
        try:
            import dashpin
            url = dashpin.steam_page()
            if url and dashpin.run_js(url, "typeof (window.SteamClient && SteamClient.OpenVR && SteamClient.OpenVR.Keyboard "
                                           "&& SteamClient.OpenVR.Keyboard.SendText)") == "function":
                return url
        except Exception as ex:
            LOG("streamed game typing: Steam isn't reachable:", ex)
        return None

    # Steam's text sending only takes the first character of what it's given: ".com" came out as ".", ":)" as ":",
    # and an emoji (several characters underneath) as nothing. So: one character each time, in order
    JS = "(%s.forEach(c => SteamClient.OpenVR.Keyboard.SendText(c)), 'ok')"

    on_drop = None   # (the keyboard's "can't type that here" message)
    on_fail = None   # (its "that key can't be sent" message)
    ascii_only = False   # (a streamed PC: only plain English characters get there)

    # Keys that aren't text (arrows, Delete, Home, Esc...) and shortcuts (Ctrl+C...): pressed the way Steam's own
    # controller keyboard presses them, through Steam Input, which passes key presses on to the streamed PC. The codes
    # are the standard USB keyboard codes, which Steam's keyboard uses
    HID = dict({chr(ord("a") + i): 4 + i for i in range(26)}, **{str(i): 29 + i for i in range(1, 10)})
    HID.update({"0": 39, "ENTER": 40, "ESC": 41, "BACKSPACE": 42, "TAB": 43, "SPACE": 44, "INSERT": 73, "HOME": 74,
                "PAGEUP": 75, "DELETE": 76, "END": 77, "PAGEDOWN": 78, "RIGHT": 79, "LEFT": 80, "DOWN": 81, "UP": 82,
                "LEFTCTRL": 224, "LEFTSHIFT": 225, "LEFTALT": 226, "LEFTMETA": 227, "RIGHTCTRL": 228,
                "RIGHTSHIFT": 229, "RIGHTALT": 230, "RIGHTMETA": 231,
                # (punctuation, so Ctrl + , or Ctrl + / go too; Print Screen, Scroll Lock, Pause; mute and volume)
                "MINUS": 45, "EQUAL": 46, "LEFTBRACE": 47, "RIGHTBRACE": 48, "BACKSLASH": 49, "SEMICOLON": 51,
                "APOSTROPHE": 52, "GRAVE": 53, "COMMA": 54, "DOT": 55, "SLASH": 56, "SYSRQ": 70, "SCROLLLOCK": 71,
                "PAUSE": 72, "MUTE": 127, "VOLUMEUP": 128, "VOLUMEDOWN": 129},
               **{"F%d" % i: 57 + i for i in range(1, 13)})
    # Pressed and let go in one go, and the letting go is done by Steam's page itself a moment later. (Pressing and
    # letting go were two separate calls: when the second didn't get through, after the headset had been off for a
    # while, Shift stayed held down in Steam, so everything came out in capitals, even after streaming, until a restart)
    PRESS = """((down, up) => { const I = window.SteamClient && SteamClient.Input;
      if (!I || typeof I.ControllerKeyboardSetKeyState !== 'function') return 'none';
      for (const k of down) I.ControllerKeyboardSetKeyState(k, true);
      setTimeout(() => { for (const k of up) try { I.ControllerKeyboardSetKeyState(k, false); } catch (e) {} }, 30);
      return 'ok'; })(%s, %s)"""
    # Shift, Ctrl, Alt and the Windows key (both sides) let go: harmless if they're up already
    LET_GO = """(codes => { const I = window.SteamClient && SteamClient.Input;
      if (!I || typeof I.ControllerKeyboardSetKeyState !== 'function') return 'none';
      for (const k of codes) try { I.ControllerKeyboardSetKeyState(k, false); } catch (e) {}
      return 'ok'; })(%s)"""
    pressed = False
    WHOLE = """(t => { const I = window.SteamClient && SteamClient.Input;
      if (!I || typeof I.ControllerKeyboardSendText !== 'function') return 'none';
      I.ControllerKeyboardSendText(t); return 'ok'; })(%s)"""
    HOW = """(word => { const out = [];
      for (const k of Object.keys(window)) { if (!k.startsWith('webpackChunk')) continue; let req = null;
        try { window[k].push([[Symbol('bf')], {}, r => { req = r; }]); } catch (e) {}
        if (!req) continue;
        for (const id of Object.keys(req.m)) { let s = ''; try { s = req.m[id].toString(); } catch (e) { continue; }
          let i = s.indexOf(word);
          while (i >= 0 && out.length < 4) { out.push(s.slice(Math.max(0, i - 160), i + 160)); i = s.indexOf(word, i + 1); } } }
      return JSON.stringify(out); })(%s)"""
    told_how = False

    def how_steam_does_it(self):
        """Once: how Steam's own keyboard presses keys (in the log, to check the key codes if a key goes wrong)."""
        if StreamText.told_how:
            return
        StreamText.told_how = True
        try:
            import dashpin
            for w in ("ControllerKeyboardSetKeyState(", "ControllerKeyboardSendText("):
                LOG("streamed game: how Steam uses", w, str(dashpin.run_js(self.url, self.HOW % json.dumps(w)))[:700])
        except Exception as ex:
            LOG("streamed game: couldn't look at Steam's keyboard:", ex)

    def press_keys(self, names):
        """Press these keys together (modifiers first) and let go in reverse order, on the streamed PC."""
        import dashpin
        codes = [self.HID.get(n if len(n) > 1 else n.lower()) for n in names]
        if None in codes:
            # (the media keys: a keyboard has no code for them that a PC takes this way)
            LOG("streamed game: no way to send", "+".join(names))
            if self.on_fail:
                self.on_fail()
            return False
        self.how_steam_does_it()
        self.pressed = True
        try:
            res = dashpin.run_js(self.url, self.PRESS % (json.dumps(codes), json.dumps(list(reversed(codes)))))
        except Exception as ex:
            res = "error: %s" % ex
        if res != "ok":
            LOG("streamed game: key press failed:", str(res)[:200])
            if self.on_fail:
                self.on_fail()
        return res == "ok"

    def let_go(self, force=False):
        """Make sure no Shift / Ctrl / Alt / Windows key is left held down in Steam (after typing stops, and when
        streaming starts and ends)."""
        if not (self.pressed or force):
            return
        self.pressed = False
        try:
            import dashpin
            dashpin.run_js(self.url, self.LET_GO % json.dumps(list(range(224, 232))))
        except Exception as ex:
            LOG("streamed game: couldn't let go of Shift/Ctrl/Alt:", ex)
            self.pressed = True   # (tried again next time typing stops)

    # Measured on the Frame (tools/streamtest.py, twice): of everything Steam has, only its VR keyboard's plain text
    # reaches a streamed PC: letters, digits, symbols, Backspace, Tab and Enter. Steam Input's key presses and text
    # and key presses made on the Frame never arrive, and terminal-style sequences (how Steam's own VR keyboard sends
    # arrows) are swallowed; the ones with Shift / Ctrl in them even left a key stuck repeating on the PC. So nothing
    # else is ever sent: those keys say they can't be sent to a streamed PC instead
    def combo(self, *names):
        """Undo, Cut, Copy, Paste, Select all: no way to send them to a streamed PC."""
        LOG("streamed game: shortcut can't be sent:", "+".join(names))
        if self.on_fail:
            self.on_fail()
        return False

    def key(self, name, mods=()):
        if not mods and name in ("BACKSPACE", "TAB", "ENTER", "SPACE"):
            import dashpin
            t = {"BACKSPACE": "\b", "TAB": "\t", "ENTER": "\n", "SPACE": " "}[name]
            return dashpin.run_js(self.url, "(SteamClient.OpenVR.Keyboard.SendText(%s), 'ok')" % json.dumps(t)) == "ok"
        LOG("streamed game: no way to send", "+".join(list(mods) + [name]))
        if self.on_fail:
            self.on_fail()
        return False

    def send(self, text):
        import dashpin
        # Measured on the Frame (tools/streamtest.py): a streamed PC only gets plain English characters this way.
        # Accents, other alphabets, symbols like ★ and every emoji, sent any way Steam has, arrive as nothing. So
        # those are kept back and the keyboard says so, instead of seeming to type and nothing appearing
        if self.ascii_only:
            kept = "".join(c for c in text if ord(c) < 128)
            if kept != text:
                LOG("streamed PC: only plain English characters reach it, left out:", len(text) - len(kept))
                if self.on_drop:
                    self.on_drop()
            text = kept
        parts, cur, emo = [], "", None
        for c in text:
            e = is_emoji(c)
            if cur and e != emo:
                parts.append((emo, cur))
                cur = ""
            cur, emo = cur + c, e
        if cur:
            parts.append((emo, cur))
        for e, piece in parts:
            if e:
                # (measured on the Frame: no way Steam has gets an emoji to a streamed PC, whole or in pieces)
                LOG("streamed game: emoji can't be sent")
                if self.on_drop:
                    self.on_drop()
            else:
                res = dashpin.run_js(self.url, self.JS % json.dumps(list(piece)))
                if res != "ok":
                    LOG("streamed game typing failed:", str(res)[:200])


class SteamUIText:
    """Typing into Steam's own text boxes (friend chat, search...): straight into the box that has focus on Steam's
    page, at its cursor, like a keyboard plugged into that page. So clicking between letters puts the cursor there,
    emoji go in whole (handed over one piece at a time through Steam, they came out as numbers), and arrows,
    Backspace, Undo, Cut, Copy, Paste and Select all work there too."""
    KEYS = {}
    FIND = ("(() => { const a = document.activeElement; "
            "const box = !!(a && (a.isContentEditable || /^(INPUT|TEXTAREA)$/.test(a.tagName))); "
            "return box ? (document.hasFocus() ? 2 : 1) : 0; })()")
    INSERT = """(t => { const a = document.activeElement; if (!a) return 'no box';
      if (!a.__bfSeen) {   // the first letter into this box: let the page do what it does when you click into it (the
        a.__bfSeen = true;  // Store's search clears its "enter search term or tags" text then: it's real text, not a hint)
        a.dispatchEvent(new FocusEvent('focus')); a.dispatchEvent(new FocusEvent('focusin', {bubbles: true}));
        if (a.value && a.value === a.defaultValue && (a.id === 'term' || a.name === 'term') && !/[?&]term=/.test(location.search)) {
          a.value = ''; a.dispatchEvent(new Event('input', {bubbles: true})); }
      }
      const p = a.__bfPre; a.__bfPre = null;   // (what was shown live while typing Japanese/Chinese: replaced by this)
      if (p && a.setRangeText && a.value !== undefined && a.value.substr(p.s, p.n) === p.t) {
        a.setRangeText(t, p.s, p.s + p.n, 'end'); a.dispatchEvent(new Event('input', {bubbles: true})); return 'ok'; }
      if (p && p.n && a.value === undefined) for (let i = 0; i < p.n; i++) document.execCommand('delete');
      if (!document.execCommand('insertText', false, t) && a.setRangeText) {
        a.setRangeText(t, a.selectionStart, a.selectionEnd, 'end'); a.dispatchEvent(new Event('input', {bubbles: true})); }
      return 'ok'; })(%s)"""
    # Japanese / Chinese still being typed: shown in the box as you go (like a phone or PC does), then swapped for the
    # way you pick to write it. t is everything typed so far ('' takes it out again)
    PRE = """(t => { const a = document.activeElement; if (!a) return 'no box';
      if (!a.__bfSeen) {
        a.__bfSeen = true;
        a.dispatchEvent(new FocusEvent('focus')); a.dispatchEvent(new FocusEvent('focusin', {bubbles: true}));
        if (a.value && a.value === a.defaultValue && (a.id === 'term' || a.name === 'term') && !/[?&]term=/.test(location.search)) {
          a.value = ''; a.dispatchEvent(new Event('input', {bubbles: true})); }
      }
      const p = a.__bfPre;
      if (a.setRangeText && a.value !== undefined) {
        let s = a.selectionStart, e = a.selectionEnd;
        if (p && a.value.substr(p.s, p.n) === p.t) { s = p.s; e = p.s + p.n; }
        a.setRangeText(t, s, e, 'end'); a.dispatchEvent(new Event('input', {bubbles: true}));
        a.__bfPre = t ? {s: s, n: t.length, t: t} : null;
      } else {
        if (p && p.n) for (let i = 0; i < p.n; i++) document.execCommand('delete');
        if (t) document.execCommand('insertText', false, t);
        a.__bfPre = t ? {n: t.length, t: t} : null;
      }
      return 'ok'; })(%s)"""
    KEY = """(k => { const a = document.activeElement; if (!a) return 'no box';
      const ed = {Backspace: 'delete', Delete: 'forwardDelete', undo: 'undo', redo: 'redo', cut: 'cut', copy: 'copy',
                  paste: 'paste', selall: 'selectAll'}[k];
      if (ed) { document.execCommand(ed); return 'ok'; }
      if (['Left', 'Right', 'Home', 'End'].includes(k)) {
        if (a.setSelectionRange && a.value !== undefined) {
          let p = a.selectionStart;
          p = k === 'Left' ? Math.max(0, p - 1) : k === 'Right' ? Math.min(a.value.length, p + 1) : k === 'Home' ? 0 : a.value.length;
          a.setSelectionRange(p, p);
        } else window.getSelection().modify('move', (k === 'Left' || k === 'Home') ? 'backward' : 'forward',
                                             (k === 'Home' || k === 'End') ? 'lineboundary' : 'character');
        return 'ok'; }
      const key = {Up: 'ArrowUp', Down: 'ArrowDown'}[k] || k;
      const code = {Enter: 13, Tab: 9, Escape: 27, ArrowUp: 38, ArrowDown: 40}[key] || 0;
      let handled = false;
      for (const t of ['keydown', 'keypress', 'keyup'])
        if (!a.dispatchEvent(new KeyboardEvent(t, {key, code: key, keyCode: code, which: code, bubbles: true, cancelable: true})))
          handled = true;
      if (key === 'Enter' && !handled && a.form && a.tagName === 'INPUT') a.form.requestSubmit();
      return 'ok'; })(%s)"""

    def __init__(self, url):
        self.url = url
        SteamUIText.KEYS = {KEY[n]: "\x00" + v for n, v in (
            ("BACKSPACE", "Backspace"), ("DELETE", "Delete"), ("ENTER", "Enter"), ("TAB", "Tab"), ("ESC", "Escape"),
            ("LEFT", "Left"), ("RIGHT", "Right"), ("UP", "Up"), ("DOWN", "Down"), ("HOME", "Home"), ("END", "End"))}
        SteamUIText.KEYS[KEY["SPACE"]] = " "      # (the space bar is a key press, not text: it types a space here)

    @staticmethod
    def find():
        """The Steam page whose text box has focus right now, or None."""
        try:
            import steambridge
            import dashpin
            best, score = None, 0
            for u in steambridge._targets():
                try:
                    v = dashpin.run_js(u, SteamUIText.FIND)
                except Exception:
                    continue
                if isinstance(v, int) and v > score:   # (the page that has focus first; else any with a text box active)
                    best, score = u, v
            return best
        except Exception as ex:
            LOG("Steam text box typing: Steam isn't reachable:", ex)
        return None

    def send(self, text):
        import dashpin
        if text.startswith("\x00"):
            res = dashpin.run_js(self.url, self.KEY % json.dumps(text[1:]))
        else:
            res = dashpin.run_js(self.url, self.INSERT % json.dumps(text))
        if res != "ok":
            LOG("Steam text box typing:", str(res)[:200])

    def preedit(self, text):
        import dashpin
        res = dashpin.run_js(self.url, self.PRE % json.dumps(text))
        if res != "ok":
            LOG("Steam text box typing (live):", str(res)[:200])

    def combo(self, *names):
        """Undo, Cut, Copy, Paste, Select all (Ctrl + Z/X/C/V/A, and their Shift/Ctrl + Insert/Delete forms)."""
        n = set(names)
        what = ({"z": "undo", "x": "cut", "c": "copy", "v": "paste", "a": "selall"}.get(names[-1]) if "LEFTCTRL" in n else None) or \
            {("LEFTCTRL", "INSERT"): "copy", ("LEFTSHIFT", "DELETE"): "cut", ("LEFTSHIFT", "INSERT"): "paste"}.get(tuple(names))
        if what:
            self.send("\x00" + what)
        return bool(what)


def is_emoji(ch):
    """An emoji, or a piece of one (skin tones, the joiners that glue family emoji together, keycap marks...).
    Steam's text channel can't carry these: it splits them up, and apps turn the pieces into numbers ("1111")."""
    o = ord(ch)
    return o > 0xFFFF or o in (0x200D, 0xFE0F, 0x20E3) or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF \
        or 0x2190 <= o <= 0x21FF or 0x2300 <= o <= 0x23FF or 0x3030 == o or 0x303D == o or 0x3297 <= o <= 0x3299


class UnicodeTyper:
    """Types any character (é, ñ, ß, Greek, kana, ...) by putting it on the clipboard and pasting it.
    Tries KDE's clipboard (Desktop Mode), then wl-copy, xclip and xsel. Your own clipboard is put back
    a moment later."""

    def __init__(self, vk, conf):
        self.vk, self.conf = vk, conf
        self.method = None
        self.tried = 0
        self.gen = 0
        self.saved = None
        self.env = dict(os.environ)
        uid = os.getuid()
        self.env.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % uid)
        self.env.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/%d/bus" % uid)
        if "WAYLAND_DISPLAY" not in self.env:  # started as a service: find the desktop's display ourselves
            run = self.env["XDG_RUNTIME_DIR"]
            for name in ("wayland-0", "wayland-1", "gamescope-0"):
                if os.path.exists(os.path.join(run, name)):
                    self.env["WAYLAND_DISPLAY"] = name
                    break
        self.env.setdefault("DISPLAY", ":0")

    def _run(self, cmd, data=None, timeout=1.0, out=True):
        try:
            if out:
                r = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout, env=self.env)
                return r.returncode == 0, r.stdout
            # copying: the tool may keep running to hold the clipboard, so don't wait on its output
            r = subprocess.run(cmd, input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, env=self.env)
            return r.returncode == 0, b""
        except Exception:
            return False, b""

    def use_session_env(self, notes):
        """The desktop you see in VR is its own KDE session, with its own message bus and display: borrow those
        from KDE's running programs, so the clipboard we reach is the one you paste from."""
        want = ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR")
        uid = os.getuid()
        for name in ("plasmashell", "kwin_wayland", "krunner", "konsole", "dolphin"):
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                try:
                    if os.stat("/proc/" + pid).st_uid != uid:
                        continue
                    with open("/proc/%s/comm" % pid) as f:
                        if f.read().strip() != name:
                            continue
                    with open("/proc/%s/environ" % pid, "rb") as f:
                        env = dict(x.split(b"=", 1) for x in f.read().split(b"\0") if b"=" in x)
                except OSError:
                    continue
                got = {k: env[k.encode()].decode("utf-8", "replace") for k in want if k.encode() in env}
                if got.get("DBUS_SESSION_BUS_ADDRESS"):
                    self.env.update(got)
                    notes.append("using %s's session" % name)
                    return True
        notes.append("no KDE session found")
        return False

    def _klipper(self, *args):
        return self._run(["dbus-send", "--session", "--print-reply=literal", "--dest=org.kde.klipper", "/klipper"] + list(args))

    def detect(self, every=True):
        """Find every way to reach a clipboard here: KDE's clipboard, then wl-copy and xclip/xsel on each display
        that exists (Desktop Mode and Game Mode use different ones). Desktop Mode uses the first that works; Game
        Mode puts the letter on all of them, since the app you type into may read any one. Each try is logged."""
        import shutil
        self.tried = time.time()
        self.method, self.targets, self.every = None, [], every
        notes = []
        self.use_session_env(notes)
        if shutil.which("dbus-send"):
            if self._klipper("org.kde.klipper.klipper.getClipboardContents")[0]:
                self.targets.append(("klipper", dict(self.env)))
                if not every:   # (Desktop Mode: KDE's clipboard is the one, as always; nothing else is tried)
                    self.method, self.env = "klipper", dict(self.env)
                    LOG("typing other letters through: KDE clipboard (" + "; ".join(notes) + ")")
                    return self.method
            else:
                notes.append("KDE clipboard: no answer")
        else:
            notes.append("dbus-send: missing")
        run = self.env.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
        waylands = [n for n in ("wayland-0", "wayland-1", "gamescope-0") if os.path.exists(os.path.join(run, n))]
        xs = [":%s" % f[1:] for f in sorted(os.listdir("/tmp/.X11-unix"))] if os.path.isdir("/tmp/.X11-unix") else [":0"]
        tries = [("wl-copy", "WAYLAND_DISPLAY", d) for d in waylands] + \
                [(m, "DISPLAY", d) for m in ("xclip", "xsel") for d in xs]
        base = dict(self.env)
        xdone = set()
        for m, var, disp in tries:
            if m == "xsel" and disp in xdone:
                continue  # (that display is already reached through xclip)
            if not shutil.which(m):
                notes.append("%s: not installed" % m)
                continue
            env = dict(base)
            env[var] = disp
            probe = "bf-%d" % int(time.time() * 1000)
            old = self._get_one(m, env)  # (whatever you had copied there goes straight back after the check)
            if self._set_one(m, env, probe) and (self._get_one(m, env) or "").strip() == probe:
                if old:
                    self._set_one(m, env, old)
                self.targets.append((m, env))
                if m == "xclip":
                    xdone.add(disp)
                if not every:
                    break
            else:
                notes.append("%s on %s: didn't work" % (m, disp))
        if self.targets:
            self.method = self.targets[0][0]
            self.env = self.targets[0][1]
            LOG("typing other letters through: " + ", ".join(
                m if m == "klipper" else "%s on %s" % (m, e.get("DISPLAY") if m != "wl-copy" else e.get("WAYLAND_DISPLAY"))
                for m, e in self.targets) + (" (" + "; ".join(dict.fromkeys(notes)) + ")" if notes else ""))
            return self.method
        LOG("typing other letters: no way to reach the clipboard here (" + "; ".join(dict.fromkeys(notes)) + ")")
        return None

    def _get_one(self, m, env):
        if m == "klipper":
            self.env, keep = env, self.env
            ok, out = self._klipper("org.kde.klipper.klipper.getClipboardContents")
            self.env = keep
            return out.decode("utf-8", "replace").strip("\n").lstrip() if ok else None
        cmd = {"wl-copy": ["wl-paste", "-n"], "xclip": ["xclip", "-o", "-selection", "clipboard"], "xsel": ["xsel", "-ob"]}.get(m)
        keep, self.env = self.env, env
        ok, out = self._run(cmd) if cmd else (False, b"")
        self.env = keep
        return out.decode("utf-8", "replace") if ok else None

    def _set_one(self, m, env, text):
        keep, self.env = self.env, env
        try:
            if m == "klipper":
                return self._klipper("org.kde.klipper.klipper.setClipboardContents", "string:" + text)[0]
            cmd = {"wl-copy": ["wl-copy"], "xclip": ["xclip", "-selection", "clipboard"], "xsel": ["xsel", "-ib"]}.get(m)
            return self._run(cmd, text.encode("utf-8"), out=False)[0] if cmd else False
        finally:
            self.env = keep

    def _where(self, everywhere):
        t = getattr(self, "targets", [])
        return t if everywhere else t[:1]

    def get(self, everywhere=False):
        """What's on the clipboard(s) now: one value per clipboard used (so each gets its own back afterwards)."""
        return [(m, e, self._get_one(m, e)) for m, e in self._where(everywhere)]

    def set(self, text, everywhere=False):
        return any([self._set_one(m, e, text) for m, e in self._where(everywhere)])

    def type(self, text, everywhere=False):
        if everywhere and self.method and not getattr(self, "every", True):
            self.method = None          # (switched to Game Mode: find every clipboard there now)
        if not self.method and (not self.tried or time.time() - self.tried > 5 or everywhere != getattr(self, "every", everywhere)):
            self.detect(every=everywhere)
        if not self.method:
            return False
        if self.saved is None:
            self.saved = self.get(everywhere)
        if not self.set(text, everywhere):
            self.method = None
            return False
        # paste only once the clipboard really holds it: pasting a moment too early typed whatever was copied before
        # (Japanese came out as random earlier text)
        want = text.strip()
        for _ in range(8):
            time.sleep(0.03 if everywhere else 0.02)
            m, e = self._where(everywhere)[0]
            if (self._get_one(m, e) or "").strip() == want:
                break
        else:
            LOG("typing other letters: the clipboard didn't take it in time, so nothing was pasted")
            return False
        if self.conf.get("paste_keys") == "shift+insert":
            self.vk.combo("LEFTSHIFT", "INSERT")
        else:
            self.vk.combo("LEFTCTRL", "v")
        self.gen += 1
        gen = self.gen

        def restore():  # put your own clipboard(s) back once typing pauses (not too soon: apps read it a moment later)
            time.sleep(2.0)
            if gen == self.gen and self.saved is not None:
                saved, self.saved = self.saved, None
                for m, e, old in saved:
                    if old is not None:
                        self._set_one(m, e, old)
        threading.Thread(target=restore, daemon=True).start()
        return True


# --------------------------------------------------------------------------- dictation (uses the helper)
def plain_text(t):
    """Voice typing without punctuation: no periods, commas or question marks; normal casing."""
    t = re.sub(r"[.,!?;:\"“”…]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t and not re.match(r"^I(\b|')", t):
        t = t[0].lower() + t[1:]
    return t


class PadReader:
    """The new Steam Controller, read straight from it (only reading: nothing is sent to it, and Steam carries on
    using it as normal). state: each pad (touching, x, y, clicked) with x and y 0-1 left to right, top to bottom;
    buttons (bits, as below); triggers 0-1; sticks -1..1 (up is +y)."""
    IDS = {0x1302, 0x1303, 0x1304}          # the new Steam Controller over USB and Bluetooth, and its puck
    OLD_IDS = {0x1102, 0x1142}               # the 2015 Steam Controller, wired and through its wireless dongle
    SONY_IDS = {0x0CE6, 0x0DF2}              # PS5 controller (DualSense) and DualSense Edge
    KINDS = {"new": "Steam Controller", "old": "Steam Controller (2015)", "ps5": "PS5 controller", "pad": "controller"}
    # any other controller (Xbox, Switch Pro, 8BitDo...): read through the system's own driver for it. No trackpad,
    # so the sticks and D-pad move between keys and the buttons type (same buttons as the Steam Controller)
    EV_KEYS = {0x130: "A", 0x131: "B", 0x133: "Y", 0x134: "X", 0x136: "LB", 0x137: "RB", 0x13a: "VIEW",
               0x13b: "MENU", 0x13c: "STEAM", 0x13d: "L3", 0x220: "DUP", 0x221: "DDOWN", 0x222: "DLEFT",
               0x223: "DRIGHT", 0x138: "LT", 0x139: "RT"}
    SKIP_NAMES = ("steam", "virtual", "valve", "touchpad", "motion", "sensor", "frame")
    # report layout (as in SDL's driver for it): 1 seq, 2-5 buttons, 6-9 triggers, 10-17 sticks, then each pad's
    # x, y and pressure (16 bit). Report 0x47 has a 2-byte timestamp just before the pads
    PAD_AT = {0x42: 18, 0x45: 18, 0x47: 20}
    A, B, X, Y, VIEW, RB, DDOWN, DRIGHT, DLEFT, DUP, MENU, STEAM, LB = (0x1, 0x2, 0x4, 0x8, 0x40, 0x200, 0x400, 0x800,
                                                                        0x1000, 0x2000, 0x4000, 0x10000, 0x80000)
    L3 = 0x8000   # left stick pressed in
    LT, RT = 1 << 40, 1 << 41   # (triggers that are only buttons, like a Switch Pro controller's: as fully pulled)
    L_TOUCH, L_CLICK, R_TOUCH, R_CLICK = 0x02000000, 0x04000000, 0x00200000, 0x00400000
    IDLE = {"L": (False, 0.5, 0.5, False), "R": (False, 0.5, 0.5, False), "buttons": 0, "trig": (0.0, 0.0),
            "sticks": ((0.0, 0.0), (0.0, 0.0))}

    def __init__(self):
        self.state = dict(self.IDLE)
        self.running = False
        self.thread = None
        self.seen = 0.0
        self.held = {"L": False, "R": False}

    @classmethod
    def kind_of(cls, vid, pid):
        if vid == 0x28DE and pid in cls.IDS:
            return "new"
        if vid == 0x28DE and pid in cls.OLD_IDS:
            return "old"
        if vid == 0x054C and pid in cls.SONY_IDS:
            return "ps5"
        return None

    @classmethod
    def gamepads(cls):
        """[(device file, name)] for the other controllers the system knows as game controllers."""
        out = []
        base = "/sys/class/input"
        for n in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if not n.startswith("event"):
                continue
            try:
                d = os.path.join(base, n, "device")
                with open(os.path.join(d, "name")) as f:
                    name = f.read().strip()
                vid = int(open(os.path.join(d, "id", "vendor")).read(), 16)
                pid = int(open(os.path.join(d, "id", "product")).read(), 16)
                if cls.kind_of(vid, pid) or vid == 0x28DE or any(w in name.lower() for w in cls.SKIP_NAMES):
                    continue   # (read directly instead, or Steam's own stand-in for a controller)
                with open(os.path.join(base, n, "dev")) as f:
                    major, minor = f.read().strip().split(":")
                with open("/run/udev/data/c%s:%s" % (major, minor)) as f:
                    if "E:ID_INPUT_JOYSTICK=1" not in f.read():
                        continue
                out.append(("/dev/input/" + n, name))
            except (OSError, ValueError):
                continue
        return out

    @classmethod
    def nodes(cls):
        """[(device file, kind)] for every controller we can read."""
        out = [(node, "pad") for node, _ in cls.gamepads()]
        base = "/sys/class/hidraw"
        for n in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            try:
                with open(os.path.join(base, n, "device", "uevent")) as f:
                    u = dict(l.split("=", 1) for l in f.read().splitlines() if "=" in l)
                parts = u.get("HID_ID", "0:0:0").split(":")
                kind = cls.kind_of(int(parts[1], 16), int(parts[2], 16))
                if kind:
                    out.append(("/dev/" + n, kind))
            except (OSError, ValueError, IndexError):
                continue
        return out

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True, name="steam-controller")
        self.thread.start()

    def stop(self):
        self.running = False
        self.state = dict(self.IDLE)

    def parse(self, data, kind="new"):
        if kind == "old":
            return self.parse_old(data)
        if kind == "ps5":
            return self.parse_ps5(data)
        return self.parse_new(data)

    def parse_ps5(self, data):
        """PS5 controller: report 0x01 over USB (64 bytes), 0x31 over Bluetooth (one byte further in), as in SDL's
        driver. One touchpad that follows two fingers: each finger gets its own highlight; pressing the touchpad
        down types the key under the finger that touched last."""
        if len(data) >= 64 and data[0] == 0x01:
            p = data[1:]
        elif len(data) >= 66 and data[0] == 0x31:
            p = data[2:]
        else:
            return None
        b0, b1, b2 = p[7], p[8], p[9]
        hat = b0 & 0x0F
        btn = 0
        for bit, on in ((self.X, b0 & 0x10), (self.A, b0 & 0x20), (self.B, b0 & 0x40), (self.Y, b0 & 0x80),
                        (self.LB, b1 & 0x01), (self.RB, b1 & 0x02), (self.VIEW, b1 & 0x10), (self.MENU, b1 & 0x20),
                        (self.L3, b1 & 0x40), (self.STEAM, b2 & 0x01),
                        (self.DUP, hat in (7, 0, 1)), (self.DRIGHT, hat in (1, 2, 3)),
                        (self.DDOWN, hat in (3, 4, 5)), (self.DLEFT, hat in (5, 6, 7))):
            if on:
                btn |= bit
        fingers = []
        for c, d in ((p[32], p[33:36]), (p[36], p[37:40])):
            down = not (c & 0x80)
            x = d[0] | ((d[1] & 0x0F) << 8)
            y = (d[1] >> 4) | (d[2] << 4)
            fingers.append((down, c & 0x7F, min(1.0, x / 1919), min(1.0, y / 1069)))
        last = self.__dict__.setdefault("ps_last", {})
        for i, (down, tid, _, _) in enumerate(fingers):   # (which finger touched most recently: it gets the click)
            if down and last.get(i) != tid:
                last[i] = tid
                self.ps_newest = i
            elif not down:
                last.pop(i, None)
        click = bool(b2 & 0x02)
        newest = getattr(self, "ps_newest", 0)
        if not fingers[newest][0]:
            newest = 0 if fingers[0][0] else 1
        sides = {}
        for i, side in ((0, "L"), (1, "R")):
            down, _, x, y = fingers[i]
            sides[side] = (down, x, y, click and down and i == newest)
        return dict(sides, buttons=btn, trig=(p[4] / 255, p[5] / 255), margin=0.03, one_pad=True,
                    sticks=(((p[0] - 128) / 127, (128 - p[1]) / 127), ((p[2] - 128) / 127, (128 - p[3]) / 127)))

    def parse_old(self, data):
        """The 2015 Steam Controller (wired or through its dongle), as in SDL's driver: a 64-byte state packet. Its
        left pad and its stick take turns in the same numbers, told apart by a flag."""
        import struct
        if len(data) < 28 or data[0] != 0x01 or data[1] != 0x00 or data[2] != 0x01 or data[3] < 24:
            return None
        raw = struct.unpack_from("<Q", data, 8)[0]
        buttons = raw & ~0xFFFF000000
        lx, ly, rx, ry = struct.unpack_from("<hhhh", data, 16)
        LEFT_DOWN, RIGHT_DOWN, BOTH = 0x80000, 0x100000, 0x800000
        prev = self.__dict__.setdefault("old_prev", {"pad": (0, 0), "stick": (0, 0)})
        if buttons & LEFT_DOWN:
            pad, prev["pad"] = (lx, ly), (lx, ly)
            stick = prev["stick"] if raw & BOTH else (0, 0)
        else:
            stick, prev["stick"] = (lx, ly), (lx, ly)
            pad = prev["pad"] if raw & BOTH else (0, 0)
        left_touch = bool(buttons & LEFT_DOWN or raw & BOTH)

        def turn(x, y, deg):   # (the pads sit at an angle on the controller: straightened, as SDL does)
            a = math.radians(deg)
            return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)
        plx, ply = turn(*pad, -15)
        prx, pry = turn(rx, ry, 15)
        btn = 0
        for bit, on in ((self.A, buttons & 0x80), (self.B, buttons & 0x20), (self.X, buttons & 0x40),
                        (self.Y, buttons & 0x10), (self.LB, buttons & 0x8), (self.RB, buttons & 0x4),
                        (self.VIEW, buttons & 0x1000), (self.MENU, buttons & 0x4000), (self.STEAM, buttons & 0x2000),
                        (self.L3, buttons & 0x400000)):
            if on:
                btn |= bit
        return {"L": (left_touch, plx / 65536 + 0.5, 0.5 - ply / 65536, bool(buttons & 0x20000) and left_touch),
                "R": (bool(buttons & RIGHT_DOWN), prx / 65536 + 0.5, 0.5 - pry / 65536, bool(buttons & 0x40000)),
                "buttons": btn, "trig": (data[11] / 255, data[12] / 255),
                "sticks": ((stick[0] / 32767, stick[1] / 32767), (0.0, 0.0))}

    PRESS_FILE = os.path.expanduser("~/.config/betterframe-keyboard/pad-press.json")

    def pressed(self, side, p_, click, touch):
        """Is this pad pressed down? p_ its pressure, click its own click, touch a thumb on it."""
        cal = self.__dict__.get("cal")
        if cal is None:
            cal = self.cal = {"click": None, "rest": {"L": None, "R": None}, "saved": 0.0}
            try:
                with open(self.PRESS_FILE) as f:
                    v = float(json.load(f).get("click", 0))
                cal["click"] = v if v > 0 else None
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        was = self.held[side]
        prev_click = self.__dict__.setdefault("click_was", {"L": False, "R": False})
        if click and not prev_click[side] and p_ > 0:
            # the pad's own click came: remember how hard that was (both pads share one scale)
            c = cal["click"]
            cal["click"] = float(p_) if c is None else c * 0.7 + p_ * 0.3
            if c is None or abs(cal["click"] - c) > c * 0.1:
                LOG("trackpad: its own click comes at %d (light press types from %d)"
                    % (cal["click"], self.press_level(side)))
            if time.time() - cal["saved"] > 30:
                cal["saved"] = time.time()
                try:
                    os.makedirs(os.path.dirname(self.PRESS_FILE), exist_ok=True)
                    with open(self.PRESS_FILE, "w") as f:
                        json.dump({"click": round(cal["click"])}, f)
                except OSError:
                    pass
        prev_click[side] = click
        rest = cal["rest"][side]
        if touch and not was and not click:
            # a thumb resting or sliding on the pad (not pressing): its usual pressure, eased toward slowly, and
            # quickly down when it's lighter
            rest = p_ if rest is None else (rest + (p_ - rest) * (0.3 if p_ < rest else 0.003))
            cal["rest"][side] = rest
        level = self.press_level(side)
        if level is None:
            return click
        if was:   # let go a little way back up (a quick tap, tap, tap types each time)
            off = (cal["rest"][side] or 0) + (level - (cal["rest"][side] or 0)) * 0.5
            return click or p_ > off
        return click or p_ > level

    def press_level(self, side):
        """The pressure a press types at, for this pad (None: not known yet, only its own click types)."""
        cal = self.__dict__.get("cal") or {}
        c = cal.get("click")
        frac = getattr(self, "press_frac", 0.3)
        if not c:
            # (not learnt yet: these numbers, until the pad's first own click shows its scale)
            return getattr(self, "press_at", 2000)
        rest = min(cal["rest"].get(side) or 0, c * 0.5)
        return max(rest + (c - rest) * frac, rest + c * 0.08)

    def parse_new(self, data):
        import struct
        at = self.PAD_AT.get(data[0]) if data else None
        if at is None or len(data) < at + 12:
            return None
        buttons = struct.unpack_from("<I", data, 2)[0]
        tl, tr, lsx, lsy, rsx, rsy = struct.unpack_from("<hhhhhh", data, 6)
        lx, ly, lp, rx, ry, rp = struct.unpack_from("<hhHhhH", data, at)
        # a pad press: how hard it's pressed (Settings > Keyboard > Trackpad press), or the pad's own click,
        # whichever comes first. The pressure numbers differ from pad to pad, so each pad's own scale is learnt: the
        # pressure its own click comes at, and the pressure of a thumb just resting on it. A press is a set part of
        # the way from resting to that click (fixed numbers made Light as firm as a full click on some pads)
        for side, p_, bit in (("L", lp, self.L_CLICK), ("R", rp, self.R_CLICK)):
            self.held[side] = self.pressed(side, p_, bool(buttons & bit), bool(buttons & (self.L_TOUCH if side == "L" else self.R_TOUCH)))
        return {"L": (bool(buttons & self.L_TOUCH) or lp > 400, lx / 65536 + 0.5, 0.5 - ly / 65536, self.held["L"]),
                "R": (bool(buttons & self.R_TOUCH) or rp > 400, rx / 65536 + 0.5, 0.5 - ry / 65536, self.held["R"]),
                "buttons": buttons, "trig": (max(0, tl) / 32767, max(0, tr) / 32767),
                "sticks": ((lsx / 32767, lsy / 32767), (rsx / 32767, rsy / 32767))}

    def ev_open(self, fd):
        """A controller read through the system's driver: the range of each stick and trigger, from the driver."""
        import fcntl
        import struct
        info = {}
        for code in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x10, 0x11):   # X Y Z RX RY RZ HAT0X HAT0Y
            try:
                buf = bytearray(24)
                fcntl.ioctl(fd, (2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + code), buf)
                _, lo, hi, _, _, _ = struct.unpack("<6i", bytes(buf))
                if hi > lo:
                    info[code] = (lo, hi)
            except OSError:
                continue
        return {"abs": info, "val": {}, "keys": set()}

    def parse_ev(self, data, ev):
        """Input events (24 bytes each) -> the controller's state, once each batch of them is complete."""
        import struct
        out = None
        for i in range(0, len(data) - 23, 24):
            _, _, typ, code, val = struct.unpack_from("<qqHHi", data, i)
            if typ == 1 and code in self.EV_KEYS:
                (ev["keys"].add if val else ev["keys"].discard)(code)
            elif typ == 3:
                ev["val"][code] = val
            elif typ == 0:
                out = self.ev_state(ev)
        return out

    def ev_state(self, ev):
        def axis(code, centred=True):
            lo, hi = ev["abs"].get(code, (-32768, 32767))
            v = ev["val"].get(code, (lo + hi) / 2 if centred else lo)
            f = (v - lo) / ((hi - lo) or 1)
            return f * 2 - 1 if centred else f
        btn = 0
        for code in ev["keys"]:
            btn |= getattr(self, self.EV_KEYS[code])
        hx, hy = ev["val"].get(0x10, 0), ev["val"].get(0x11, 0)   # (a D-pad reported as a hat)
        btn |= (self.DLEFT if hx < 0 else self.DRIGHT if hx > 0 else 0) | (self.DUP if hy < 0 else self.DDOWN if hy > 0 else 0)
        tl = 1.0 if btn & self.LT else axis(0x02, False) if 0x02 in ev["abs"] else 0.0
        tr = 1.0 if btn & self.RT else axis(0x05, False) if 0x05 in ev["abs"] else 0.0
        return {"L": (False, 0.5, 0.5, False), "R": (False, 0.5, 0.5, False), "buttons": btn & ~(self.LT | self.RT),
                "trig": (tl, tr),
                "sticks": ((axis(0x00), -axis(0x01)), (axis(0x03), -axis(0x04)))}

    def _run(self):
        import select
        fds, said, looked = {}, False, 0
        try:
            while self.running:
                if time.time() - looked > (3 if not fds else 5):   # (a controller turned on later: found within moments)
                    looked = time.time()
                    have = {v[0] for v in fds.values()}
                    added = []
                    for node, kind in self.nodes():
                        if node in have:
                            continue
                        try:
                            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
                        except OSError as ex:
                            if not said:
                                LOG("controller: can't read it:", ex)
                                said = True
                            continue
                        fds[fd] = (node, kind, self.ev_open(fd) if kind == "pad" else None)
                        added.append(self.KINDS[kind])
                    if added:
                        LOG("controller: reading", ", ".join(sorted(set(added))))
                if not fds:
                    time.sleep(0.5)
                    continue
                r, _, _ = select.select(list(fds), [], [], 0.5)
                for fd in r:
                    try:
                        data = os.read(fd, 24 * 64 if fds[fd][1] == "pad" else 128)
                    except OSError:
                        os.close(fd)
                        fds.pop(fd, None)   # (turned off or out of range: found again when it's back)
                        continue
                    node, kind, ev = fds[fd]
                    st = self.parse_ev(data, ev) if kind == "pad" else self.parse(data, kind)
                    if st:
                        self.state, self.seen = st, time.time()
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass


class Dictation:
    """Mic -> live words (real-time recognizer) -> on each pause, the sentence is typed into the app."""

    SR = 16000

    def __init__(self, on_live, on_final, on_error):
        self.on_live, self.on_final, self.on_error = on_live, on_final, on_error
        self.proc = None
        self.running = False
        self.recent = ""
        self.lang = "en"  # the keyboard's language: other languages are written down by the multilingual model

    def start(self):
        if self.running:
            return
        self.running = True  # opening the microphone can take a moment: never on the keyboard's own time
        threading.Thread(target=self._open, daemon=True).start()

    def _open(self):
        for cmd in (["pw-record", "--raw", "--format", "s16", "--rate", "16000", "--channels", "1", "-"],
                    ["parecord", "--raw", "--format=s16le", "--rate=16000", "--channels=1"],
                    ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-r", "16000", "-c", "1"]):
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                time.sleep(0.15)
                if self.proc.poll() is None:
                    LOG("microphone through", cmd[0])
                    break
                self.proc = None
            except FileNotFoundError:
                continue
        if not self.proc:
            self.running = False
            self.on_error("Couldn't open the microphone")
            return
        if not self.running:  # stopped while it was opening
            self.stop()
            return
        self._loop()

    def stop(self):
        self.running = False
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None

    @staticmethod
    def _post(path, data, ctype):
        req = urllib.request.Request(HELPER + path, data=data, headers={"Content-Type": ctype})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")

    def _wav(self, pcm):
        n = len(pcm)
        hdr = b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, self.SR, self.SR * 2, 2, 16) + b"data" + struct.pack("<I", n)
        return hdr + pcm

    def _loop(self):
        import array
        chunk_bytes = int(self.SR * 0.05) * 2
        seg, pre, speaking, silence, floor, seg_id, live = bytearray(), [], False, 0.0, 0.006, 0, ""
        sid = "ov%d" % int(time.time())
        while self.running and self.proc:
            data = self.proc.stdout.read(chunk_bytes)
            if not data:
                break
            a = array.array("h", data)
            rms = math.sqrt(sum(x * x for x in a) / max(1, len(a))) / 32768.0
            loud = rms > max(0.012, floor * 2.6)
            if not speaking and not loud:
                floor = floor * 0.95 + rms * 0.05
            pending = b""
            if loud and not speaking:
                speaking, silence = True, 0.0
                seg = bytearray(b"".join(pre))
                pending = bytes(seg)
            if speaking:
                seg += data
                pending += data
                try:
                    if self.lang != "en":  # the live preview only knows English
                        raise ValueError
                    j = self._post("/api/stream?sid=%s-%d" % (sid, seg_id), pending, "application/octet-stream")
                    t = (j.get("text") or "").lower()
                    if t != live:
                        live = t
                        self.on_live(live)
                except Exception:
                    pass
                silence = 0.0 if loud else silence + 0.05
                if silence > 0.45 or len(seg) > self.SR * 2 * 12:
                    audio, live_text = bytes(seg), live
                    seg, speaking, live, seg_id = bytearray(), False, "", seg_id + 1
                    threading.Thread(target=self._finish, args=(audio, live_text), daemon=True).start()
            else:
                pre.append(data)
                if len(pre) > 7:
                    pre.pop(0)
        self.running = False

    def _finish(self, audio, live_text):
        if len(audio) < self.SR * 2 * 0.3 and not live_text:
            self.on_live("")
            return
        text = ""
        try:
            from urllib.parse import quote
            j = self._post("/api/stt?mode=final&lang=%s&context=%s" % (self.lang, quote(self.recent[-150:])), self._wav(audio), "audio/wav")
            text = (j.get("text") or "").strip()
        except Exception as e:
            LOG("clean-up failed, using live words:", e)
        if not text and live_text:
            text = live_text
        self.on_live("")
        if text:
            self.recent += " " + text
            self.on_final(text)


# --------------------------------------------------------------------------- layouts
STEAM_TAB = 99   # the emoji page's Steam tab (its emoticons)
FAV_TAB = 98     # the emoji page's Favorites tab (hold any emoji to add it)
EMOJI_PAGES = [1]   # how many pages the emoji tab you're on has (as last drawn)
SEMO_DIR = os.path.expanduser("~/.cache/betterframe-keyboard/emoticons")
SEMO_URL = "https://community.fastly.steamstatic.com/economy/emoticonlarge/%s"


def semo_path(name):
    return os.path.join(SEMO_DIR, "".join(c for c in name if c.isalnum() or c in "_-") + ".png")


SEMO_JS = """(() => {
  const s = window.g_FriendsUIApp && g_FriendsUIApp.ChatStore && g_FriendsUIApp.ChatStore.EmoticonStore;
  if (!s) return JSON.stringify({ok: false});
  const L = Array.from(s.m_rgEmoticons || []);   // (Steam's lists can be special list objects: a plain copy)
  // which field is the name: Steam doesn't say, so the text field that differs from one emoticon to the next
  let key = null, most = -1;
  if (L.length && typeof L[0] === 'object') for (const k of Object.keys(L[0])) {
    if (typeof L[0][k] !== 'string') continue;
    const c = new Set(L.map(e => e && e[k])).size;
    if (c > most || (c === most && /name/i.test(k))) { most = c; key = k; }
  }
  const nm = e => typeof e === 'string' ? e : (e && key ? String(e[key] || '') : (e && (e.name || e.m_strName)) || '');
  const when = e => (e && typeof e === 'object') ? +(e.last_used || e.time_last_used || e.time_received || 0) : 0;
  const l = L.map(e => ({n: nm(e), r: when(e)}));
  const own = s.m_setEmoticonOwned;
  if (own && own.forEach) own.forEach(v => { const n = typeof v === 'string' ? v : nm(v); if (n) l.push({n, r: 0}); });
  let sample = '';
  try { sample = JSON.stringify(L[0]).slice(0, 200); } catch (e) { sample = String(L[0]).slice(0, 200); }
  let osample = '';
  try { if (own && own.forEach) { let f = null; own.forEach(v => { if (f === null) f = v; }); osample = JSON.stringify(f).slice(0, 120); } } catch (e) {}
  return JSON.stringify({ok: true, l, keys: L.length && typeof L[0] === 'object' ? Object.keys(L[0]) : [], key, n: L.length,
                         owned: own ? (own.size || own.length || 0) : -1, sample, osample});
})()"""


# Steam only downloads your emoticons when its chat's emoticon picker first opens: until then the list is empty.
# Ask it to load them (its own loading function, found by name, since Steam doesn't say which), and report what it has
SEMO_LOAD_JS = """(() => {
  const s = window.g_FriendsUIApp && g_FriendsUIApp.ChatStore && g_FriendsUIApp.ChatStore.EmoticonStore;
  if (!s) return JSON.stringify({ok: false});
  const fns = [];
  for (let p = Object.getPrototypeOf(s); p && p !== Object.prototype; p = Object.getPrototypeOf(p))
    for (const k of Object.getOwnPropertyNames(p)) if (typeof s[k] === 'function' && k !== 'constructor') fns.push(k);
  const called = [];
  for (const k of fns) {
    if (/^(Request|Ensure|Load|Fetch|Update|Refresh|Get)?.*Emoticon.*(List|s)$/i.test(k) && /request|ensure|load|fetch|refresh|update/i.test(k)) {
      try { const r = s[k](); called.push(k + (r && r.then ? ' (promise)' : '')); } catch (e) { called.push(k + ' failed: ' + e); }
    }
  }
  return JSON.stringify({ok: true, called, fns: fns.slice(0, 60), requested: !!s.m_bEmoticonListRequested});
})()"""


def K(label, w=1.0, **o):
    o.update(label=label, w=w)
    return o


def letters(s):
    return [K(c, 1, ch=c) for c in s]


def syms(pairs, w=1.0):
    return [K(a, w, sym=(a, b)) for a, b in pairs]


def chars(lst, w):
    return [K(c, w, ins=c) for c in lst]


import languages as LANG
import ime as IME


def fit(row, U):
    """Make a row exactly U key-widths wide: stretch Space / Enter / Back / Shift, or shrink every key a little."""
    w = sum(k["w"] for k in row)
    if w < U - 1e-6:
        flex = (next((k for k in row if k.get("act") == "space"), None)
                or next((k for k in reversed(row) if k.get("act") in ("enter", "shift", "back", "del")), None)
                or next((k for k in row if k.get("act") in ("tab", "caps")), None))
        if flex:  # rows of plain letters just stay centred, keys keep their size
            flex["w"] += U - w
    elif w > U + 1e-6:
        for k in row:
            k["w"] *= U / w
    return row


def lkeys(row):
    """Keys for a letter row: letters, or (key, with Shift) pairs for punctuation among the letters (Dvorak)."""
    return [K(c[0], 1, sym=c) if isinstance(c, tuple) else K(c, 1, ch=c) for c in row]


def _kana_rows():
    rows = [[K(c, 1, ch=c) for c in r] for r in LANG.KANA_ROWS]
    rows[0].append(K("", 1, mod=True, act="back", icon="backspace"))
    rows[1].append(K("゛゜", 1, mod=True, act="dakuten", center=True))
    rows[2].append(K("小", 1, mod=True, act="small", center=True))
    rows[3].append(K("Enter", 1, go=True, act="enter"))
    rows[4].append(K("カナ", 1, mod=True, act="shift", center=True))
    rows.append([K(".?123", 2, mod=True, act="p123"), K("Tab", 1.2, mod=True, act="tab"), K("", 7.8, act="space")])
    return rows


def _flick_rows():
    """Japanese flick keypad, like a phone: big kana keys in the middle; tap for あ, or press and flick
    left / up / right / down for い う え お. A guide shows the choices while you hold."""
    side, mid = 2.0, 7.0 / 3
    rows = []
    for r in LANG.FLICK:
        rows.append([K("゛゜小", mid, mod=True, act="flickmod", center=True) if f is None else
                     K(f[0] if f[0] != "、" else "、。?!", mid, flick=f, center=True) for f in r])
    left = [K("カナ", side, mod=True, act="shift", center=True), K("", side, mod=True, act="left", icon="left"),
            K(".?123", side, mod=True, act="p123"), K("", side, mod=True, act="emoji", icon="emoji")]
    right = [K("", side, mod=True, act="back", icon="backspace"), K("", side, mod=True, act="right", icon="right"),
             K("", side, act="space"), K("Enter", side, go=True, act="enter")]
    return [[l] + r + [rt] for l, r, rt in zip(left, rows, right)]


def _letter_rows(layout, lang, fmt="default"):
    if lang.get("flick"):
        return _flick_rows()
    if lang.get("kana"):
        return _kana_rows()
    r1, r2, r3 = LANG.letter_rows(lang, fmt)
    alt = [K("", 1, mod=True, act="alt", altkey=True)] if lang["layers"] else []
    extra = [K(a, 1, sym=(a, b)) for a, b in lang["extra"]]
    num = syms(lang["numrow"]) if lang.get("numrow") else None
    if layout == "minimal":
        # like a phone: comma and full stop sit beside Space, so every language has them; the Shift row's
        # free spots get ? ' - (most used first), whatever the language's own letters leave room for
        used = {c[0] if isinstance(c, tuple) else c for r in (r1, r2, r3) for c in r} | {a for a, b in (lang.get("numrow") or ())}
        row2 = lkeys(r1) + (syms([("'", '"')]) if len(r1) < 11 and "'" not in used else [])
        if len(row2) > len(r1):
            used.add("'")
        tail4 = alt + extra
        room = max(11, len(row2), len(r2) + (1.5 + 0.5 if len(r2) <= 9 else 1.3))
        order = [("?", "!"), ("'", '"'), ("-", "_")]
        if lang["code"][:2] in ("fr", "it", "uk"):  # l'apostrophe is used constantly in French and Italian
            order = [("'", '"'), ("?", "!"), ("-", "_")]
        for k in syms(order):
            if 1 + len(r3) + len(tail4) + 1 <= room + 1e-6 and k["sym"][0] not in used:
                tail4.append(k)
                used.add(k["sym"][0])
        if BOTTOM_ROW[0] == "laptop":   # (Settings > Keyboard > Bottom row) Ctrl in the corner and Fn, then .?123: Minimal
            # has no symbol keys of its own, so .?123 stays
            bottom = [K("Ctrl", 1.1, mod=True, act="ctrl"), K("Fn", 1.0, mod=True, act="fn"), K(".?123", 1.4, mod=True, act="p123")]
            sp, tab = 4.5, 1.0
        else:
            bottom = [K(".?123", 1.6, mod=True, act="p123")]   # (the emoji button is up in the top bar)
            sp, tab = 6.2, 1.2
        bottom += [k for k in syms([(",", ";")]) if "," not in used] + [K("", sp, act="space")]
        bottom += [k for k in syms([(".", ":")]) if "." not in used] + [K("Tab", tab, mod=True, act="tab")]
        if num and lang.get("ime") == "zhuyin":  # Zhuyin: ㄦ (after 0 on the real keyboard) has to be here too
            num = num + syms([p for p in lang.get("after0") or () if p[0] in IME.FINALS])
        if lang.get("mini"):  # letters a real keyboard has after 0 or top-left (Thai ข ช, Arabic ذ, Hindi ृ)
            num = (num or chars(list("1234567890"), 1)) + syms(lang["mini"])
        return [
            (num or chars(list("1234567890"), 1)) + [K("", 1, mod=True, act="back", icon="backspace")],
            row2,
            ([K("", 0.5, spacer=True)] if len(r2) <= 9 else []) + lkeys(r2) + [K("Enter", 1.5 if len(r2) <= 9 else 1.3, go=True, act="enter")],
            [K("Shift", 1, mod=True, act="shift")] + lkeys(r3) + tail4,
            bottom,
        ]
    if is_iso(lang):
        return _top_rows(num, euro=lang.get("code") != "en-GB", lang=lang) + _iso_rows(lang, r1, r2, r3, alt, extra) + [_bottom_full()]
    row3 = [K("Tab", 1.5, mod=True, act="tab")] + lkeys(r1)
    own = lang.get("punct") == []  # a script with its own punctuation among the letters: only the \\ key after them
    for k in ([] if own else syms([("[", "{"), ("]", "}")])) + [K("\\", 1.5, sym=("\\", "|"))]:
        if sum(x["w"] for x in row3) + k["w"] <= 15.01:
            row3.append(k)
    row3[0]["w"] += max(0.0, 15 - sum(x["w"] for x in row3))
    row4 = [K("Caps", 1.75, mod=True, act="caps")] + lkeys(r2)
    for k in syms([(";", ":"), ("'", '"')]):
        if k["sym"] in r1 or k["sym"] in r3:
            continue  # already among the letters (Dvorak)
        if sum(x["w"] for x in row4) + k["w"] + 1.75 <= 15.01:
            row4.append(k)
    row4.append(K("Enter", max(1.75, 15 - sum(x["w"] for x in row4)), go=True, act="enter"))
    row5 = [K("Shift", 2.25, mod=True, act="shift")] + lkeys(r3) + alt + extra + \
        [k for k in syms([] if own else [(",", "<"), (".", ">"), ("/", "?")]) if k["sym"] not in r3]
    row5.append(K("Shift", max(1.25, 15 - sum(x["w"] for x in row5)), mod=True, act="shift"))
    if row5[-1]["w"] > row5[0]["w"]:  # the left Shift is used more, so it gets the bigger key
        row5[0]["w"], row5[-1]["w"] = row5[-1]["w"], row5[0]["w"]
    return _top_rows(num, lang=lang) + [row3, row4, row5, _bottom_full()]


def _top_rows(num, euro=False, lang=None):
    # each language's own keys after 0 and top-left (German ß ´ and ^, Nordic + ´ and §, ...); otherwise
    # European keyboards get ' and ? after 0 (and - _ moves down to the Shift row)
    lang = lang or {}
    after0 = lang.get("after0") or ([("'", "?"), ("=", "+")] if euro else [("-", "_"), ("=", "+")])
    topleft = lang.get("topleft") or ("`", "~")
    return [
        [K("Esc", 1, mod=True, act="esc")] + [K("F%d" % n, 1, mod=True, act="f%d" % n, center=True) for n in range(1, 13)] + [K("Delete", 2, mod=True, act="del")],
        syms([topleft]) + (num or syms([("1", "!"), ("2", "@"), ("3", "#"), ("4", "$"), ("5", "%"), ("6", "^"), ("7", "&"), ("8", "*"), ("9", "("), ("0", ")")]))
        + syms(after0) + [K("", 2, mod=True, act="back", icon="backspace")],
    ]


BOTTOM_ROW = ["default"]   # Standard's bottom-left keys (Settings > Keyboard > Bottom row): set for each drawing


def _bottom_full():
    if BOTTOM_ROW[0] == "laptop":   # like a laptop: Ctrl in the corner, then Fn, Start, Alt (no .?123: the number row is there)
        return [K("Ctrl", 1.4, mod=True, act="ctrl"), K("Fn", 1.1, mod=True, act="fn"),
                K("Start", 1.2, mod=True, act="start"), K("Alt", 1.0, mod=True, act="alt-mod"),
                K("", 4.9, act="space"),
                K("", 1.1, mod=True, act="left", icon="left"), K("", 1.1, mod=True, act="up", icon="up"),
                K("", 1.1, mod=True, act="down", icon="down"), K("", 1.1, mod=True, act="right", icon="right")]
    return [K(".?123", 1.4, mod=True, act="p123"), K("Fn", 1.0, mod=True, act="fn"),
            K("Ctrl", 1.1, mod=True, act="ctrl"), K("Start", 1.2, mod=True, act="start"), K("Alt", 1.0, mod=True, act="alt-mod"),
            K("", 4.9, act="space"),
            K("", 1.1, mod=True, act="left", icon="left"), K("", 1.1, mod=True, act="up", icon="up"),
            K("", 1.1, mod=True, act="down", icon="down"), K("", 1.1, mod=True, act="right", icon="right")]


# Keyboards sold in the US (and Japan, and Polish "programmer" boards) are ANSI: a wide Enter and a long left Shift.
# Almost everywhere else they're ISO: a tall Enter, a short left Shift, and one more key next to it
# (that's where < > lives in Europe, \ | in the UK, and the extra letter í in Hungary).
ANSI = {"en-US", "pl-PL", "nl-NL", "lv-LV", "ja-JP", "ja-JP-r", "ko-KR", "zh-TW", "zh-HK", "zh-HK-q", "zh-CN",
        "ru-RU", "uk-UA", "vi-VN", "id-ID", "ms-MY", "ar", "he-IL", "hi-IN", "th-TH"}  # (Dutch and Latvian typists use US-style boards)
ISO_KEYS = {  # language -> (key next to the left Shift, key just left of Enter)
    "en-GB": (("\\", "|"), ("#", "~")),
    "de-DE": (("<", ">"), ("#", "'")),
    "fr-FR": (("<", ">"), ("*", "µ")),
    "fr-CA": (None, ("<", ">")),  # Canadian French: ù sits beside the left Shift
    "sv-SE": (("<", ">"), ("'", "*")), "fi-FI": (("<", ">"), ("'", "*")), "da-DK": (("<", ">"), ("'", "*")),
    "nb-NO": (("<", ">"), ("'", "*")), "et-EE": (("<", ">"), ("'", "*")),
    "cs-CZ": (("\\", "|"), ("'", '"')), "sk-SK": (("\\", "|"), ("'", '"')),
    "pt-PT": (("<", ">"), ("~", "^")),
    "hu-HU": (None, ("\\", "|")),  # Hungarian: í sits beside the left Shift
    "ga-IE": (("\\", "|"), ("#", "~")), "mt-MT": (("\\", "|"), ("ż", "Ż")),
    "bg-BG": (("ѝ", "Ѝ"), ("„", "“")), "bg-PH": (("ѝ", "Ѝ"), ("ю", "Ю")),
    "es-419": (("<", ">"), ("}", "]")),
    "pt-BR": (("\\", "|"), ("]", "}")), "tr-TR": (("<", ">"), (",", ";")),
}


TOP_FILL = {  # what follows the letters on the top row of a real keyboard in each language
    "de-DE": [("+", "*")], "it-IT": [("+", "*")], "es-ES": [("`", "^"), ("+", "*")], "pt-PT": [("+", "*"), ("´", "`")],
    "fr-FR": [("^", "¨"), ("$", "£")], "fr-CA": [("^", "¨")],
    "sv-SE": [("¨", "^")], "fi-FI": [("¨", "^")], "da-DK": [("¨", "^")], "nb-NO": [("¨", "^")],
    "cs-CZ": [(")", "(")], "sk-SK": [(")", "(")],
    "es-419": [("´", "¨"), ("+", "*")], "ca-ES": [("`", "^"), ("+", "*")], "eu-ES": [("`", "^"), ("+", "*")],
    "gl-ES": [("`", "^"), ("+", "*")], "ga-IE": [("[", "{"), ("]", "}")],
    "pt-BR": [("´", "`"), ("[", "{")],
}


def is_iso(lang):
    return lang.get("code") not in ANSI and not lang.get("kana")


def _iso_rows(lang, r1, r2, r3, alt, extra):
    """Tab, Caps and Shift rows the ISO way: a tall Enter spanning the Tab and Caps rows, a short left Shift."""
    used = {c[0] if isinstance(c, tuple) else c for r in (r1, r2, r3) for c in r}
    used |= {a for a, b in (lang.get("numrow") or ())} | {a for a, b in (lang.get("after0") or ())}
    used |= {(lang.get("topleft") or ("`",))[0]}
    iso, hashk = ISO_KEYS.get(lang.get("code"), (("<", ">"), ("\\", "|")))
    W, ENTER = 15.0, 1.25
    row3 = lkeys(r1)
    for k in syms(TOP_FILL.get(lang.get("code"), [("[", "{"), ("]", "}")])):  # the keys after p, per language
        if k["sym"][0] not in used and len(row3) < 12:
            row3.append(k)
            used.add(k["sym"][0])
    row4 = lkeys(r2)
    for k in syms([hashk, (";", ":"), ("'", '"')] if len(r2) > 9 else [(";", ":"), ("'", '"'), hashk]):
        if k["sym"][0] not in used and len(row4) < 12:
            row4.append(k)
            used.add(k["sym"][0])
    # Tab and Caps take up whatever is left, so the tall Enter lines up exactly on both rows
    row3 = [K("Tab", max(1.0, W - ENTER - len(row3)), mod=True, act="tab")] + row3 + [K("Enter", ENTER, go=True, act="enter", tall=True)]
    row4 = [K("Caps", max(1.0, W - ENTER - len(row4)), mod=True, act="caps")] + row4 + [K("", ENTER, spacer=True)]
    # the extra key beside the left Shift: a language with an extra letter there (Hungarian í) already has it
    lead = [] if not iso or iso[0] in used else syms([iso])
    row5 = [K("Shift", 1.25, mod=True, act="shift")] + lead + lkeys(r3) + alt + extra
    punct = lang.get("punct") or ([(",", "<"), (".", ">"), ("/", "?")] if lang.get("code") == "en-GB" else
                                  [(",", ";"), (".", ":"), ("-", "_"), ("/", "?")])
    for k in syms(punct):
        if k["sym"][0] not in used and k["sym"][0] not in {x.get("sym", ("",))[0] for x in row5} \
                and sum(x["w"] for x in row5) + 1 + 1.25 <= W + 1e-6:
            row5.append(k)
    row5.append(K("Shift", max(1.25, W - sum(x["w"] for x in row5)), mod=True, act="shift"))
    return [row3, row4, row5]


def _advanced_rows(lang, fmt="default"):
    """A full-size (101-key) keyboard in one piece, like a real one: the main block, a gap, the editing keys
    and arrows, a gap, then the numpad. Tall keys (numpad + and Enter) span two rows."""
    if lang.get("flick"):
        return _flick_rows()
    if lang.get("kana"):
        return _kana_rows()
    rows = _letter_rows("full", lang, fmt)
    fkeys = [K("Esc", 1, mod=True, act="esc"), K("", 1, spacer=True)]
    for g in range(3):
        fkeys += [K("F%d" % n, 1, mod=True, act="f%d" % n, center=True) for n in range(g * 4 + 1, g * 4 + 5)]
        if g < 2:
            fkeys.append(K("", 0.5, spacer=True))
    bottom = [K("Ctrl", 1.5, mod=True, act="ctrl"), K("Start", 1.25, mod=True, act="start"), K("Alt", 1.25, mod=True, act="alt-mod"),
              K("", 6.5, act="space"), K("Alt", 1.25, mod=True, act="alt-mod"), K("Fn", 1.0, mod=True, act="fn"),
              K("Ctrl", 1.5, mod=True, act="ctrl")]
    main = [fkeys] + rows[1:5] + [bottom]
    U = max(15, max(sum(k["w"] for k in r) for r in main))
    main = [fit(r, U) for r in main]
    gap = lambda: K("", 0.5, spacer=True)
    sp = lambda w=1: K("", w, spacer=True)
    nav = lambda label, act: K(label, 1, mod=True, act=act, center=True)
    np = lambda d, navk, lab, w=1: K(d, w, ins=d, np=navk, nplabel=lab)
    side = [
        [nav("PrtSc", "prtsc"), nav("ScrLk", "scrlk"), nav("Pause", "pause"), gap(), sp(4)],
        [nav("Ins", "ins"), nav("Home", "home"), nav("PgUp", "pgup"), gap(),
         K("Num", 1, mod=True, act="numlock", center=True), K("/", 1, ins="/"), K("*", 1, ins="*"), K("-", 1, ins="-")],
        [nav("Del", "del"), nav("End", "end"), nav("PgDn", "pgdn"), gap(),
         np("7", "HOME", "Home"), np("8", "UP", "↑"), np("9", "PAGEUP", "PgUp"), K("+", 1, ins="+", tall=True)],
        [sp(3), gap(), np("4", "LEFT", "←"), np("5", None, ""), np("6", "RIGHT", "→"), sp()],
        [sp(), K("", 1, mod=True, act="up", icon="up"), sp(), gap(),
         np("1", "END", "End"), np("2", "DOWN", "↓"), np("3", "PAGEDOWN", "PgDn"), K("Enter", 1, go=True, act="enter", center=True, tall=True)],
        [K("", 1, mod=True, act="left", icon="left"), K("", 1, mod=True, act="down", icon="down"), K("", 1, mod=True, act="right", icon="right"),
         gap(), np("0", "INSERT", "Ins", 2), np(".", "DELETE", "Del"), sp()],
    ]
    return [m + [gap()] + sd for m, sd in zip(main, side)]


def wing_items(side="right"):
    """The side wing: editing keys and arrows on the inner edge (next to the main keys), numpad on the outer
    edge - on the right that's exactly a full-size keyboard's order. Returned as (key, column, row, width,
    height) in key units; rows line up with the main block."""
    np = lambda d, nav, lab: K(d, 1, ins=d, np=nav, nplabel=lab)
    out = [
        (K("PrtSc", 1, mod=True, act="prtsc", center=True), 4.5, 0, 1, 1), (K("ScrLk", 1, mod=True, act="scrlk", center=True), 5.5, 0, 1, 1),
        (K("Pause", 1, mod=True, act="pause", center=True), 6.5, 0, 1, 1),
        (K("Num", 1, mod=True, act="numlock", center=True), 0, 1, 1, 1), (K("/", 1, ins="/"), 1, 1, 1, 1),
        (K("*", 1, ins="*"), 2, 1, 1, 1), (K("-", 1, ins="-"), 3, 1, 1, 1),
        (K("Ins", 1, mod=True, act="ins", center=True), 4.5, 1, 1, 1), (K("Home", 1, mod=True, act="home", center=True), 5.5, 1, 1, 1),
        (K("PgUp", 1, mod=True, act="pgup", center=True), 6.5, 1, 1, 1),
        (np("7", "HOME", "Home"), 0, 2, 1, 1), (np("8", "UP", "↑"), 1, 2, 1, 1), (np("9", "PAGEUP", "PgUp"), 2, 2, 1, 1),
        (K("+", 1, ins="+"), 3, 2, 1, 2),
        (K("Del", 1, mod=True, act="del", center=True), 4.5, 2, 1, 1), (K("End", 1, mod=True, act="end", center=True), 5.5, 2, 1, 1),
        (K("PgDn", 1, mod=True, act="pgdn", center=True), 6.5, 2, 1, 1),
        (np("4", "LEFT", "←"), 0, 3, 1, 1), (np("5", None, ""), 1, 3, 1, 1), (np("6", "RIGHT", "→"), 2, 3, 1, 1),
        (np("1", "END", "End"), 0, 4, 1, 1), (np("2", "DOWN", "↓"), 1, 4, 1, 1), (np("3", "PAGEDOWN", "PgDn"), 2, 4, 1, 1),
        (K("Enter", 1, go=True, act="enter", center=True), 3, 4, 1, 2),
        (K("", 1, mod=True, act="up", icon="up"), 5.5, 4, 1, 1),
        (np("0", "INSERT", "Ins"), 0, 5, 2, 1), (np(".", "DELETE", "Del"), 2, 5, 1, 1),
        (K("", 1, mod=True, act="left", icon="left"), 4.5, 5, 1, 1), (K("", 1, mod=True, act="down", icon="down"), 5.5, 5, 1, 1),
        (K("", 1, mod=True, act="right", icon="right"), 6.5, 5, 1, 1),
    ]
    if side == "right":  # editing keys first (columns 0-2), then the numpad (3.5-7.5)
        out = [(k, (c - 4.5) if c >= 4.5 else (c + 3.5), r, w, h) for k, c, r, w, h in out]
    return out


WING_UNITS = 7.5


def units_for(layout, lang_code="en-US", fmt="default"):
    """How many key-widths wide this layout is (a language with extra letters makes it a bit wider, keys stay the same size)."""
    lang = LANG.get(lang_code)
    base = 11 if (layout == "minimal" or lang.get("kana")) else 15
    rows = _advanced_rows(lang, fmt) if layout == "advanced" else _letter_rows(layout, lang, fmt)
    return max(base, max(sum(k["w"] for k in r) for r in rows))


def emoji_rows(layout, U, st):
    """The emoji page: tabs along the top, a grid of emoji, and ABC / page arrows / space / Backspace below."""
    import emoji_data as E
    cat = st.get("ecat", 1)
    cols = 10 if layout == "minimal" else 14
    w = U / cols
    semo = st.get("semo") or ()          # Steam's emoticons you own (names), once Steam has told us
    steam_tab = STEAM_TAB
    favs = tuple(st.get("efav") or ())    # your favorites (what each one types), newest first
    favset = {App.emo_key(x) for x in favs}   # (compared however each was written down)
    ntabs = len(E.CATS) + 1 + (1 if semo else 0)
    tabs = [K(icon, U / ntabs, bar=True, act="ecat:%d" % i, on=i == cat, emoji=True, tip=name)
            for i, (icon, name, _) in enumerate(E.CATS)]
    tabs.insert(1, K("⭐", U / ntabs, bar=True, act="ecat:%d" % FAV_TAB, on=cat == FAV_TAB, emoji=True, tip="Favorites"))
    if semo:   # Steam's own emoticons: the first tab
        face = "steamhappy" if "steamhappy" in semo else semo[0]
        tabs.insert(0, K("", U / ntabs, bar=True, act="ecat:%d" % steam_tab, on=cat == steam_tab, semo=face, tip="Steam"))
    elif cat == steam_tab:
        cat = 1
    tone = st.get("etone", -1)
    allm = list(semo) if cat == steam_tab else list(favs) if cat == FAV_TAB else E.items(cat, st.get("erecent", ()), tone)
    nrows = 3 if layout == "minimal" else 4  # fill the same height as the letters
    per = cols * nrows
    pages = max(1, -(-len(allm) // per))
    pg = min(st.get("epage", 0), pages - 1)
    EMOJI_PAGES[0] = pages
    shown = allm[pg * per:(pg + 1) * per]
    grid = []
    for r_ in range(nrows):
        part = shown[r_ * cols:(r_ + 1) * cols]
        if cat == steam_tab:   # Steam's emoticons: types :name:, which Steam's chat shows as the picture
            row = [K(e, w, ins=":%s:" % e, semo=e, emoji=True, tip=e, fav=App.emo_key(":%s:" % e) in favset) for e in part]
        elif cat in (FAV_TAB, 0):   # Favorites and Recent (a Steam emoticon among them is kept as :name:)
            row = [K(e[1:-1], w, ins=e, semo=e[1:-1], emoji=True, tip=e[1:-1], fav=App.emo_key(e) in favset)
                   if len(e) > 2 and e[0] == ":" and e[-1] == ":" else K(e, w, ins=e, emoji=True, fav=App.emo_key(e) in favset)
                   for e in part]
        else:
            row = [K(e, w, ins=e, emoji=True, fav=App.emo_key(e) in favset) for e in part]
        if not row and r_ == 0 and cat == 0:
            row = [K("Emoji you use show up here", U, bar=True, act="noop", fitlabel=True)]
        if not row and r_ == 0 and cat == FAV_TAB:
            row = [K("Hold any emoji to add it to your Favorites", U, bar=True, act="noop", fitlabel=True)]
        row += [K("", w, spacer=True) for _ in range(cols - len(row))] if row and not row[0].get("bar") else []
        grid.append(row or [K("", U, spacer=True)])
    s = U / 11
    hand = E.with_tone("✋", tone)
    bottom = [K("ABC", 1.5 * s, mod=True, act="abc"),
              K("", 1.0 * s, mod=True, act="epage:-1" if pg > 0 else "noop", icon="left", off=pg == 0),
              K("%d / %d" % (pg + 1, pages), 1.0 * s, mod=True, act="noop", center=True),   # (always: blank looked broken)
              K("", 1.0 * s, mod=True, act="epage:1" if pg < pages - 1 else "noop", icon="right", off=pg >= pages - 1),
              K(hand, 1.0 * s, mod=True, act="etone", emoji=True, tip="Skin tone"),
              K("", 4.0 * s, act="space"), K("", 1.5 * s, mod=True, act="back", icon="backspace")]
    return [fit(tabs, U)] + [fit(r_, U) for r_ in grid] + [fit(bottom, U)]


LANG_COLS, LANG_ROWS = 6, 4   # the language picker: 24 languages a page


def rows_for(layout, page, lang_code="en-US", fmt="default", st=None):
    lang = LANG.get(lang_code)
    U = units_for(layout, lang_code, fmt)
    if page == "emoji":   # (the flick keypad is short, like Minimal: its emoji page uses Minimal's smaller grid to fit)
        return emoji_rows("minimal" if lang.get("flick") else layout, U, st or {})
    if page == "fmt":  # the key layout picker
        opts = []
        for f in LANG.FORMAT_ORDER:
            if f == "default":
                name, sample = "Default (%s)" % LANG.native_format(lang), "".join(
                    c if isinstance(c, str) else c[0] for c in LANG.letter_rows(lang, "default")[0][:6]).upper()
            else:
                name, rows3 = LANG.FORMATS[f]
                sample = "".join(c if isinstance(c, str) else c[0] for c in rows3[0][:6]).upper()
            opts.append(K(name, U / 4, bar=True, act="fmt:" + f, on=f == fmt, fitlabel=True, sample=" ".join(sample)))
        return [fit(r, U) for r in (opts[:4], opts[4:])]
    if page == "lang":  # the language picker: each language once, in its own name, big enough to read
        st = st or {}
        groups = LANG.groups()
        cur = lang["code"].split("-")[0]
        g = next((x for x in groups if x[0] == st.get("lgroup")), None)
        if g is not None:  # a language with more than one keyboard: which one
            vs = g[2]
            row = [K(LANG.variant_label(l), U / max(3, len(vs)), bar=True, act="lang:" + l["code"], on=l["code"] == lang["code"],
                     pick="") for l in vs]
            return [fit(row, U), fit([K("‹  " + g[1], U / 3, bar=True, act="lback", pick="")], U)]
        per = LANG_COLS * LANG_ROWS
        pages = max(1, -(-len(groups) // per))
        pg = max(0, min(pages - 1, st.get("lpage", 0)))
        part = groups[pg * per:(pg + 1) * per]
        rows = []
        for i in range(0, len(part), LANG_COLS):
            rows.append([K(name + ("  ›" if len(ls) > 1 else ""), U / LANG_COLS, bar=True,
                           act=("lgroup:" + key) if len(ls) > 1 else "lang:" + ls[0]["code"], on=key == cur, pick="")
                         for key, name, ls in part[i:i + LANG_COLS]])
        while len(rows) < LANG_ROWS:
            rows.append([K("", U / LANG_COLS, spacer=True)])
        if pages > 1:
            rows.append([K("", U / 8, bar=True, act="lpage:-1", icon="left"), K("%d / %d" % (pg + 1, pages), U / 6, bar=True, act="noop"),
                         K("", U / 8, bar=True, act="lpage:+1", icon="right")])
        return [fit(r, U) for r in rows]
    if page == "abc":
        return [fit(r, U) for r in (_advanced_rows(lang, fmt) if layout == "advanced" else _letter_rows(layout, lang, fmt))]
    if lang.get("kana"):
        layout = "minimal"
    f, cw = (11 / 15, 1.1) if layout == "minimal" else (1.0, 1.5)
    s = 15 / 11 * f
    bottom = [K("ABC", 1.6 * s, mod=True, act="abc"), K("Tab", 1.2 * s, mod=True, act="tab"),
              K("", 5.6 * s, act="space"), K("Enter", 2.6 * s, go=True, act="enter")]
    top = [] if layout == "minimal" else [_letter_rows("full", lang, fmt)[0]]
    cur = lang["currency"]
    if page == "123":
        rows = top + [
            chars(list("1234567890"), cw),
            chars(["#", "@", cur, "&", "*", "(", ")", "-", "_", "/"], cw),
            chars(list("!?.,'\":;=+"), cw),
            [K("#+=", 1.65 * s, mod=True, act="psym")] + chars(list("%^~`|\\<"), cw) + [K("", 1.65 * s, mod=True, act="back", icon="backspace")],
            bottom,
        ]
    else:
        money = "$" if cur != "$" else "€"
        rows = top + [
            chars(list("[]{}<>^~`|"), cw),
            chars(["\\", "/", "=", "+", "-", "_", "*", "&", "%", money], cw),
            chars(list("@#!?;:'\",."), cw),
            [K("123", 1.65 * s, mod=True, act="p123")] + chars(["(", ")", ":)", ";)", "...", "->", ".com"], cw) + [K("", 1.65 * s, mod=True, act="back", icon="backspace")],
            bottom,
        ]
    return [fit(r, U) for r in rows]


def bar_items(st):
    return [
        K("", 0.95, bar=True, act="undo", icon="undo", tip="Undo"),
        K("", 0.95, bar=True, act="cut", icon="cut", tip="Cut"), K("", 0.95, bar=True, act="copy", icon="copy", tip="Copy"),
        K("", 0.95, bar=True, act="paste", icon="paste", tip="Paste"), K("", 0.95, bar=True, act="selall", icon="selall", tip="Select all"),
        K("", 0.5, spacer=True),
        # the three layouts as small keyboard pictures (named when you point at them)
        K("", 0.95, bar=True, act="lay-minimal", icon="lay-minimal", wide=True, on=st["layout"] == "minimal", tip="Minimal"),
        K("", 0.95, bar=True, act="lay-full", icon="lay-full", wide=True, on=st["layout"] == "full", tip="Standard"),
        K("", 0.95, bar=True, act="lay-advanced", icon="lay-advanced", wide=True, on=st["layout"] == "advanced", tip="Full"),   # (full-size, number pad and all)
        K("", 0.5, spacer=True),
        K("", 0.95, bar=True, act="recenter", icon="recenter", tip="Recenter"),
        K("", 0.5, spacer=True),
        K("", 0.95, bar=True, act="mic", icon="mic", rec=st["mic"], wide=True, tip="Stop voice typing" if st["mic"] else "Voice typing"),
        K("", 0.95, bar=True, act="emoji", icon="emoji", on=st["page"] == "emoji", wide=True, tip="Emoticon"),
        K("", 0.95, bar=True, act="swipe", icon="swipe", on=st.get("swipe", False), tip="Swipe typing"),
        K("", 0.95, bar=True, act="curve", icon="curve", off=not st.get("curved", True), tip="Curved keyboard"),
        K("", 0.95, bar=True, act="panel", icon="panel", off=not st.get("panel", True), tip="Backdrop"),
        K("", 0.95, bar=True, act="hide", icon="close", tip="Close keyboard"),
    ]


# --------------------------------------------------------------------------- drawing
PAL = {"key": (42, 55, 69, 255), "mod": (29, 38, 49, 255), "go": (26, 143, 232, 255), "bar": (24, 33, 43, 255),
       "on": (26, 143, 232, 255), "rec": (217, 69, 74, 255), "glow": (143, 203, 255, 255), "text": (255, 255, 255, 255),
       "sub": (142, 153, 166, 255), "strip": (10, 15, 22, 255), "accent": (40, 72, 104, 255), "grab": (154, 166, 180, 230), "slash": (235, 87, 87, 255)}
PAL["panel"] = (46, 47, 50)

# Colour themes (Settings > Keyboard > Colours). Each changes only the colours, never the layout
THEMES = {
    "steam": dict(PAL),
    "midnight": {"key": (24, 24, 27, 255), "mod": (14, 14, 16, 255), "bar": (12, 12, 14, 255), "strip": (0, 0, 0, 255),
                 "accent": (38, 52, 72, 255), "panel": (0, 0, 0), "sub": (128, 132, 140, 255)},
    "slate": {"key": (78, 84, 92, 255), "mod": (56, 61, 68, 255), "bar": (48, 52, 58, 255), "strip": (30, 33, 37, 255),
              "accent": (70, 98, 128, 255), "panel": (66, 69, 74), "sub": (176, 182, 190, 255)},
    "light": {"key": (246, 247, 249, 255), "mod": (214, 219, 226, 255), "bar": (226, 230, 236, 255), "strip": (236, 239, 243, 255),
              "accent": (196, 220, 246, 255), "panel": (200, 205, 212), "text": (24, 28, 34, 255), "sub": (96, 104, 114, 255),
              "grab": (110, 118, 128, 230), "glow": (26, 120, 220, 255)},
    "ocean": {"key": (22, 64, 72, 255), "mod": (14, 44, 52, 255), "bar": (12, 38, 45, 255), "go": (0, 168, 150, 255),
              "on": (0, 168, 150, 255), "accent": (20, 98, 104, 255), "glow": (120, 236, 220, 255), "panel": (10, 40, 46)},
    "violet": {"key": (54, 42, 82, 255), "mod": (38, 29, 60, 255), "bar": (32, 24, 50, 255), "go": (138, 92, 246, 255),
               "on": (138, 92, 246, 255), "accent": (82, 60, 130, 255), "glow": (200, 176, 255, 255), "panel": (36, 28, 54)},
    "forest": {"key": (36, 62, 44, 255), "mod": (25, 44, 31, 255), "bar": (21, 37, 26, 255), "go": (46, 160, 90, 255),
               "on": (46, 160, 90, 255), "accent": (44, 96, 60, 255), "glow": (150, 230, 170, 255), "panel": (26, 40, 30)},
    "sunset": {"key": (72, 46, 36, 255), "mod": (52, 32, 25, 255), "bar": (44, 27, 21, 255), "go": (240, 120, 40, 255),
               "on": (240, 120, 40, 255), "accent": (120, 70, 40, 255), "glow": (255, 196, 140, 255), "panel": (50, 32, 26)},
    "rose": {"key": (74, 40, 58, 255), "mod": (54, 28, 42, 255), "bar": (46, 24, 36, 255), "go": (232, 76, 140, 255),
             "on": (232, 76, 140, 255), "accent": (118, 56, 88, 255), "glow": (255, 170, 210, 255), "panel": (52, 28, 40)},
    "contrast": {"key": (0, 0, 0, 255), "mod": (0, 0, 0, 255), "bar": (0, 0, 0, 255), "strip": (0, 0, 0, 255), "go": (0, 102, 255, 255),
                 "on": (0, 102, 255, 255), "accent": (60, 60, 60, 255), "glow": (255, 214, 0, 255), "panel": (0, 0, 0),
                 "sub": (230, 230, 230, 255), "outline": (255, 255, 255, 255)},
}


def set_theme(name):
    """Switch the colours; True if anything changed."""
    new = dict(THEMES["steam"])
    new.update(THEMES.get(name) or {})
    changed = new != PAL
    PAL.clear()
    PAL.update(new)
    return changed

FONT_CANDIDATES = [
    "/usr/share/fonts/noto/NotoSans-Medium.ttf", "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/TTF/NotoSans-Medium.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Medium.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


_ICON_CACHE = {}


def _stroke(d, pts, w, fill):
    """Line with round ends and joins."""
    d.line(pts, fill=fill, width=int(w), joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=fill)


def _arc(d, cx, cy, r, a0, a1, w, fill, steps=48):
    """Arc (degrees, 0 = right, clockwise like PIL) with round ends."""
    pts = [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
            cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps))) for i in range(steps + 1)]
    _stroke(d, pts, w, fill)


# Japanese typed in English letters (romaji): the kana each key starts, shown small on the key
ROMAJI_HINT = {"a": "あ", "i": "い", "u": "う", "e": "え", "o": "お", "k": "か", "s": "さ", "t": "た", "n": "な", "h": "は",
               "m": "ま", "y": "や", "r": "ら", "w": "わ", "g": "が", "z": "ざ", "d": "だ", "b": "ば", "p": "ぱ", "j": "じ",
               "f": "ふ", "c": "ち", "v": "ゔ", "x": "ぁ", "l": "ぁ", "q": "く"}


def icon_image(kind, size, color, bg, slash=False):
    """Icon drawn on a 512 px grid, then scaled down smoothly (no jaggy edges)."""
    key = (kind, int(size), color, bg, slash)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    from PIL import Image, ImageDraw
    S = 512
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if kind == "mic":
        d.rounded_rectangle((166, 36, 346, 322), radius=90, fill=color)        # capsule
        _arc(d, 256, 222, 132, 0, 180, 34, color)                                # holder
        _stroke(d, [(256, 354), (256, 446)], 34, color)                          # stem
        _stroke(d, [(184, 458), (328, 458)], 34, color)                          # base
    elif kind == "sound":
        d.rounded_rectangle((64, 196, 168, 316), radius=18, fill=color)         # body
        d.polygon([(150, 196), (262, 104), (262, 408), (150, 316)], fill=color)  # cone
        d.ellipse((238, 92, 286, 140), fill=color)
        d.ellipse((238, 372, 286, 420), fill=color)
        d.rectangle((238, 116, 274, 396), fill=color)
        _arc(d, 262, 256, 82, -48, 48, 34, color)                               # waves
        _arc(d, 262, 256, 160, -50, 50, 34, color)
        if slash:  # red line with a clear gap cut around it
            _stroke(d, [(70, 70), (442, 442)], 90, (0, 0, 0, 0))
            _stroke(d, [(70, 70), (442, 442)], 38, PAL["slash"])
    elif kind == "globe":
        cx, cy, r = 256, 256, 196
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=30)
        d.ellipse((cx - 86, cy - r, cx + 86, cy + r), outline=color, width=26)  # meridian
        d.line((cx, cy - r, cx, cy + r), fill=color, width=26)
        for dy in (-92, 0, 92):  # latitude lines, clipped to the globe
            half = (r * r - dy * dy) ** 0.5 - 14
            d.line((cx - half, cy + dy, cx + half, cy + dy), fill=color, width=24)
    elif kind == "swipe":  # swipe typing: a curvy stroke starting from a dot
        pts = []
        for i in range(41):
            t = i / 40
            pts.append((96 + 320 * t, 352 - 200 * t + 78 * math.sin(t * math.pi * 2.2)))
        _stroke(d, pts, 34, color)
        x, y = pts[0]
        d.ellipse((x - 40, y - 40, x + 40, y + 40), fill=color)
    elif kind == "preview":  # key preview: a speech bubble with a letter in it (filled = on, outline = off)
        box = (64, 72, 448, 372)
        tail = [(196, 366), (256, 448), (316, 366)]
        if not slash:
            d.rounded_rectangle(box, radius=72, fill=color)
            d.polygon(tail, fill=color)
            hole = (0, 0, 0, 0)
        else:
            d.rounded_rectangle(box, radius=72, outline=color, width=28)
            d.line([(204, 372), (256, 440), (308, 372)], fill=color, width=28, joint="curve")
            hole = color
        # the letter A
        d.line([(178, 318), (256, 126), (334, 318)], fill=hole, width=40, joint="curve")
        d.line([(208, 252), (304, 252)], fill=hole, width=34)
    elif kind == "gear":  # settings: a cog with eight teeth around a ring
        cx, cy = 256, 256
        for i in range(8):
            a = math.radians(i * 45)
            pts = []
            for da, rr in ((-13, 150), (-9, 210), (9, 210), (13, 150)):
                pts.append((cx + rr * math.cos(a + math.radians(da)), cy + rr * math.sin(a + math.radians(da))))
            d.polygon(pts, fill=color)
        d.ellipse((cx - 160, cy - 160, cx + 160, cy + 160), fill=color)
        d.ellipse((cx - 66, cy - 66, cx + 66, cy + 66), fill=(0, 0, 0, 0))
    elif kind == "search":  # a magnifying glass
        d.ellipse((96, 96, 336, 336), outline=color, width=40)
        _stroke(d, [(310, 310), (420, 420)], 52, color)
    elif kind == "words":  # word suggestions: a W in a small rounded square (filled = on, outline = off)
        box = (76, 76, 436, 436)
        if not slash:
            d.rounded_rectangle(box, radius=70, fill=color)
            ink = (0, 0, 0, 0)
        else:
            d.rounded_rectangle(box, radius=70, outline=color, width=30)
            ink = color
        _stroke(d, [(150, 170), (198, 346), (256, 222), (314, 346), (362, 170)], 38, ink)
    elif kind == "eye":  # eyes on the keyboard: an eye (crossed out when off)
        top = [(56 + 400 * i / 24, 256 - 150 * math.sin(math.pi * i / 24)) for i in range(25)]
        bot = [(56 + 400 * i / 24, 256 + 150 * math.sin(math.pi * i / 24)) for i in range(25)]
        d.line(top, fill=color, width=34, joint="curve")
        d.line(bot, fill=color, width=34, joint="curve")
        d.ellipse((186, 186, 326, 326), fill=color)
        if slash:
            _stroke(d, [(90, 430), (422, 82)], 38, bg)
            _stroke(d, [(96, 424), (416, 88)], 30, color)
    elif kind == "undo":  # a curved arrow going back to the left, like every app's Undo
        pts = [(286 + 140 * math.cos(math.radians(a_)), 300 + 140 * math.sin(math.radians(a_))) for a_ in range(60, -181, -6)]
        pts = pts[:-2]
        _stroke(d, pts[:-1] + [(146, 300)], 38, color)
        d.polygon([(66, 262), (226, 262), (146, 392)], fill=color)      # the arrow head, pointing down at the end
    elif kind == "selall":  # selected text: a rounded outline with a few lines inside
        d.rounded_rectangle((64, 110, 448, 402), radius=44, outline=color, width=32)
        for yy, x1_ in ((196, 372), (256, 390), (316, 296)):
            _stroke(d, [(140, yy), (x1_, yy)], 30, color)
    elif kind == "recenter":  # four corner marks around a small window in the middle: "put it back in the middle"
        for cx_, cy_, sx, sy in ((70, 70, 1, 1), (442, 70, -1, 1), (70, 442, 1, -1), (442, 442, -1, -1)):
            _stroke(d, [(cx_, cy_ + sy * 110), (cx_, cy_), (cx_ + sx * 110, cy_)], 34, color)
    elif kind in ("lay-minimal", "lay-full", "lay-advanced"):
        # the three layouts as small keyboards made of tiny keys: Minimal narrow, Standard wider with the F-key row,
        # Full the widest with a number pad set apart
        wide = {"lay-minimal": 300, "lay-full": 420, "lay-advanced": 492}[kind]
        x0_ = (512 - wide) / 2
        top_, bot_ = 136, 376
        d.rounded_rectangle((x0_, top_, x0_ + wide, bot_), radius=34, outline=color, width=24)
        ix0, iy0, iy1 = x0_ + 34, top_ + 32, bot_ - 32
        main_w = (wide - 68) if kind != "lay-advanced" else (wide - 68) * 0.72
        rows = 4 if kind == "lay-minimal" else 5          # (the last row: the space bar)
        cols = 5 if kind == "lay-minimal" else 7
        gh = (iy1 - iy0) / rows
        gap_ = 9

        def keycap(x0k, y0k, x1k, y1k):
            d.rounded_rectangle((x0k, y0k, x1k, y1k), radius=min(8, (y1k - y0k) / 2), fill=color)
        for r_ in range(rows - 1):
            ky0, ky1 = iy0 + gh * r_ + gap_ / 2, iy0 + gh * (r_ + 1) - gap_ / 2
            if kind != "lay-minimal" and r_ == 0:     # the F-key row: thinner keys
                ky1 = ky0 + (ky1 - ky0) * 0.6
            for c_ in range(cols):
                kx0 = ix0 + main_w * c_ / cols + gap_ / 2
                keycap(kx0, ky0, kx0 + main_w / cols - gap_, ky1)
        sy0 = iy0 + gh * (rows - 1) + gap_ / 2           # space bar, in the middle of the bottom row
        keycap(ix0 + main_w * 0.22, sy0, ix0 + main_w * 0.78, iy0 + gh * rows - gap_ / 2)
        if kind == "lay-advanced":
            px0 = ix0 + main_w + 22
            pw = x0_ + wide - 34 - px0
            for r_ in range(4):
                for c_ in range(2):
                    kx0 = px0 + pw * c_ / 2 + gap_ / 2
                    ky0 = iy0 + (iy1 - iy0) * r_ / 4 + gap_ / 2
                    keycap(kx0, ky0, kx0 + pw / 2 - gap_, ky0 + (iy1 - iy0) / 4 - gap_)
    elif kind == "cut":  # scissors: two rings, two crossing blades
        for x in (138, 374):
            d.ellipse((x - 70, 300, x + 70, 440), outline=color, width=32)
        _stroke(d, [(178, 312), (352, 64)], 34, color)
        _stroke(d, [(334, 312), (160, 64)], 34, color)
    elif kind == "copy":  # two pages, one on top of the other
        d.rounded_rectangle((170, 56, 436, 356), radius=36, outline=color, width=32)
        d.rounded_rectangle((60, 140, 342, 470), radius=40, fill=(0, 0, 0, 0))   # (a gap around the front page)
        d.rounded_rectangle((76, 156, 326, 454), radius=36, outline=color, width=32)
    elif kind == "paste":  # a clipboard
        d.rounded_rectangle((92, 96, 420, 470), radius=40, outline=color, width=32)
        d.rounded_rectangle((176, 50, 336, 140), radius=26, fill=color)
        _stroke(d, [(170, 252), (342, 252)], 30, color)
        _stroke(d, [(170, 344), (300, 344)], 30, color)
    elif kind == "emoji":  # a smiley face: round outline, two eyes, a smile
        d.ellipse((60, 60, 452, 452), outline=color, width=34)
        d.ellipse((168, 170, 214, 236), fill=color)
        d.ellipse((298, 170, 344, 236), fill=color)
        d.arc((150, 190, 362, 372), start=20, end=160, fill=color, width=34)
    elif kind == "curve":  # on: a curved screen (edges bowed, like a curved monitor); off: a flat screen outline
        if not slash:
            n = 24
            # (just the curved screen, no stand: it's the keyboard bending, not a monitor)
            top = [(56 + 400 * i / n, 150 + 52 * (1 - (2 * i / n - 1) ** 2)) for i in range(n + 1)]
            bot = [(56 + 400 * i / n, 368 + 52 * (1 - (2 * i / n - 1) ** 2)) for i in range(n + 1)]
            d.polygon(top + bot[::-1], fill=color)
        else:   # off: the same curved shape, just its outline (so it's never mistaken for the backdrop button)
            n = 24
            top = [(72 + 368 * i / n, 162 + 48 * (1 - (2 * i / n - 1) ** 2)) for i in range(n + 1)]
            bot = [(72 + 368 * i / n, 356 + 48 * (1 - (2 * i / n - 1) ** 2)) for i in range(n + 1)]
            _stroke(d, top + bot[::-1] + [top[0]], 30, color)
    elif kind == "panel":  # background on: a filled rounded rectangle; off: just its outline
        box = (52, 128, 460, 384)
        if not slash:
            d.rounded_rectangle(box, radius=64, fill=color)
        else:
            d.rounded_rectangle(box, radius=64, outline=color, width=32)
    elif kind in ("left", "right", "up", "down"):  # drawn pointing left, then turned
        _stroke(d, [(110, 256), (402, 256)], 44, color)
        _stroke(d, [(236, 130), (110, 256), (236, 382)], 44, color)
        img = img.rotate({"left": 0, "up": -90, "right": 180, "down": 90}[kind], resample=Image.BICUBIC)
    elif kind in ("backspace", "delete"):
        outline = [(48, 256), (168, 112), (466, 112), (466, 400), (168, 400), (48, 256)]
        d.line(outline, fill=color, width=36, joint="curve")
        for x, y in outline[:-1]:
            d.ellipse((x - 18, y - 18, x + 18, y + 18), fill=color)
        _stroke(d, [(262, 196), (382, 316)], 36, color)
        _stroke(d, [(262, 316), (382, 196)], 36, color)
        if kind == "delete":
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
    elif kind == "close":
        _stroke(d, [(136, 136), (376, 376)], 46, color)
        _stroke(d, [(136, 376), (376, 136)], 46, color)
    out = img.resize((int(size), int(size)), Image.LANCZOS)
    _ICON_CACHE[key] = out
    return out


def draw_icon(img, kind, cx, cy, s, color, bg, slash=False):
    ic = icon_image(kind, s, color, bg, slash)
    img.alpha_composite(ic, (int(round(cx - s / 2)), int(round(cy - s / 2))))


class Renderer:
    W = 1600

    def __init__(self, font_path=""):
        from PIL import ImageFont
        self.ImageFont = ImageFont
        self.draw_lock = threading.RLock()
        path = font_path if font_path and os.path.exists(font_path) else next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
        if not path:
            try:
                path = subprocess.run(["fc-match", "-f", "%{file}", "sans:medium"], capture_output=True, text=True, timeout=3).stdout.strip() or None
            except Exception:
                path = None
        self.font_path = path
        LOG("font:", path or "Pillow default")
        self.cache = {}

    EMOJI_FONTS = ["/usr/share/fonts/noto/NotoColorEmoji.ttf", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
                   "/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf", "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
                   "/usr/share/fonts/TTF/NotoColorEmoji.ttf"]

    def emoji_glyph(self, ch):
        """A colour emoji as a picture (drawn once at the font's own size, then reused)."""
        cache = self.cache.setdefault("emoji", {})
        if ch in cache:
            return cache[ch]
        from PIL import Image, ImageDraw
        img = None
        if not hasattr(self, "emoji_font"):
            self.emoji_font = None
            path = next((p for p in self.EMOJI_FONTS if os.path.exists(p)), None)
            if not path:
                try:
                    path = subprocess.run(["fc-match", "-f", "%{file}", "emoji:color"], capture_output=True, text=True, timeout=3).stdout.strip()
                except Exception:
                    path = None
            if path and "moji" in path.lower():
                try:
                    self.emoji_font = self.ImageFont.truetype(path, 109)  # colour emoji fonts come in one size
                except Exception as ex:
                    LOG("emoji font unusable:", ex)
            LOG("emoji font:", path if self.emoji_font else "none (plain symbols instead)")
        if self.emoji_font:
            try:
                im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
                ImageDraw.Draw(im).text((80, 80), ch, font=self.emoji_font, embedded_color=True, anchor="mm")
                box = im.getbbox()
                img = im.crop(box) if box else None
            except Exception:
                img = None
        cache[ch] = img
        return img

    def draw_semo(self, img, d, name, cx, cy, size, maxw):
        """A Steam emoticon from its saved picture; just its name (small) until the picture has been fetched."""
        from PIL import Image
        cache = self.cache.setdefault("semo", {})
        g = cache.get(name)
        if g is None:
            p = semo_path(name)
            if os.path.exists(p):
                try:
                    g = Image.open(p).convert("RGBA")
                    cache[name] = g
                except Exception:
                    g = None
        if g is None:
            d.text((cx, cy), name, font=self.fit_font(d, name, size * 0.32, maxw), fill=PAL["sub"], anchor="mm")
            return
        sc = size / max(g.width, g.height)
        gi = g.resize((max(1, int(g.width * sc)), max(1, int(g.height * sc))), Image.LANCZOS)
        img.alpha_composite(gi, (int(cx - gi.width / 2), int(cy - gi.height / 2)))

    def draw_emoji(self, img, d, ch, cx, cy, size):
        g = self.emoji_glyph(ch)
        if g is None:  # no colour emoji font: show it as text
            d.text((cx, cy), ch, font=self.font(size * 0.8, ch), fill=PAL["text"], anchor="mm")
            return
        from PIL import Image
        sc = size / max(g.width, g.height)
        gi = g.resize((max(1, int(g.width * sc)), max(1, int(g.height * sc))), Image.LANCZOS)
        img.alpha_composite(gi, (int(cx - gi.width / 2), int(cy - gi.height / 2)))

    # scripts the main font usually lacks: drawn with the Noto fonts that come with BetterFrame
    SCRIPT_FONTS = (((0x0590, 0x05FF), "NotoSansHebrew.ttf"), ((0x0600, 0x06FF), "NotoSansArabic.ttf"),
                    ((0xFB50, 0xFEFF), "NotoSansArabic.ttf"), ((0x0900, 0x097F), "NotoSansDevanagari.ttf"),
                    ((0x0E00, 0x0E7F), "NotoSansThai.ttf"))

    def script_font(self, text):
        for ch in text:
            o = ord(ch)
            for (a, b), name in self.SCRIPT_FONTS:
                if a <= o <= b:
                    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", name)
                    return path if os.path.exists(path) else None
        return None

    def font(self, px, text=""):
        px = int(px)
        sp = self.script_font(text) if text else None
        if sp:
            key = (sp, px)
            if key not in self.cache:
                try:
                    f = self.ImageFont.truetype(sp, px)
                    try:
                        f.set_variation_by_name("Medium")
                    except Exception:
                        pass
                    self.cache[key] = f
                except Exception:
                    self.cache[key] = self.font(px)
            return self.cache[key]
        if text and any(ord(c) >= 0x2E80 or 0x1100 <= ord(c) <= 0x11FF for c in text) and self.cjk_path():
            idx = self.cjk_index if self._cjk.endswith(".ttc") else 0
            key = ("cjk", px, idx)
            if key not in self.cache:
                try:
                    self.cache[key] = self.ImageFont.truetype(self._cjk, px, index=idx)
                except Exception:
                    try:
                        self.cache[key] = self.ImageFont.truetype(self._cjk, px)
                    except Exception:
                        self.cache[key] = self.font(px)
            return self.cache[key]
        if px not in self.cache:
            try:
                self.cache[px] = self.ImageFont.truetype(self.font_path, px) if self.font_path else self.ImageFont.load_default(px)
            except Exception:
                self.cache[px] = self.ImageFont.load_default()
        return self.cache[px]

    # Noto Sans CJK holds each region's own character shapes: Japanese, Korean, Simplified, Traditional, Hong Kong
    CJK_INDEX = {"ja": 0, "ko": 1, "zh-CN": 2, "zh-TW": 3, "zh-HK": 4}
    cjk_index = 0

    def set_cjk(self, lang_code):
        c = lang_code or ""
        self.cjk_index = self.CJK_INDEX.get(c[:5], self.CJK_INDEX.get(c[:2], 0))

    def cjk_path(self):
        if not hasattr(self, "_cjk"):
            self._cjk = None
            for p in ("/usr/share/fonts/noto-cjk/NotoSansCJK-Medium.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
                      "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
                if os.path.exists(p):
                    self._cjk = p
                    break
            if not self._cjk:
                try:
                    out = subprocess.run(["fc-match", "-f", "%{file}", ":lang=ja"], capture_output=True, text=True, timeout=3).stdout.strip()
                    self._cjk = out or None
                except Exception:
                    pass
        return self._cjk

    def fit_font(self, d, text, px, max_w):
        """Biggest font up to px that fits text into max_w."""
        f = self.font(px, text)
        while px > 10 and d.textlength(text, font=f) > max_w:
            px -= 2
            f = self.font(px, text)
        return f

    def layout(self, st, conf):
        LANG.set_lang(st.get("lang"))
        BOTTOM_ROW[0] = st.get("bottomrow", "default")
        mini = st["layout"] == "minimal"
        self.W = 2048 if st["layout"] == "advanced" else 1600  # the full-size keyboard is wider, keep it sharp
        lang = st.get("lang", "en-US")
        fmt = st.get("fmt", "default")
        units = units_for(st["layout"], lang, fmt)
        pw, ph = conf["pitch_minimal"] if mini else conf.get("pitch_advanced", [0.066, 0.058]) if st["layout"] == "advanced" else conf["pitch_full"]
        upx = self.W / (units + 0.4)
        uph = upx * ph / pw
        gap = upx * 0.1
        margin = upx * 0.2
        ref_rows = len(rows_for(st["layout"], "abc", lang, fmt))
        rows = rows_for(st["layout"], st["page"], lang, fmt, st)
        bar_h = uph * 0.6
        ime_on = bool(LANG.get(lang).get("ime")) and IME.available(LANG.get(lang).get("ime"))
        if st.get("esearch"):
            ime_on = True        # (searching emoji: the word bar shows what you typed and the emoji found)
        strip_h = uph * 0.62 if (st.get("words") or ime_on) else 0   # (messages and voice typing: a pop-up above instead)
        top = margin + strip_h + (gap if strip_h else 0)
        self.strip_box = (margin, margin + strip_h)
        items = []
        grid_w = max(sum(k["w"] for k in r) for r in rows_for(st["layout"], "abc", lang, fmt)) * upx
        gx0, gx1 = (self.W - grid_w) / 2, (self.W + grid_w) / 2 - gap  # left and right edge of the keys
        self.grid = (gx0, gx1)
        bar = [] if st.get("barpos") == "off" else bar_items(st)   # (Top bar: Off in Settings)
        # every button as wide as its text needs, one text size for the whole bar (shrinks together if tight)
        from PIL import Image, ImageDraw
        probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        px = bar_h * 0.4
        need = []
        for k in bar:
            if k.get("spacer"):
                need.append(bar_h * 0.35)
            elif k.get("icon"):
                need.append(bar_h * (1.9 if k.get("wide") else 1.12) + gap)   # (the mic: wider, easier to hit)
            else:
                need.append(probe.textlength(k["label"], font=self.font(px, k["label"])) + bar_h * 0.62 + gap)
        sf = (gx1 - gx0 + gap) / (sum(need) or 1)
        self.bar_px = px * min(1.0, sf)
        below = st.get("barpos") == "bottom"
        by = (top + ref_rows * uph + gap * 0.6) if below else top
        x = gx0
        for k, n in zip(bar, need):
            w = n * sf
            if not k.get("spacer"):
                items.append((k, (x, by, x + w - gap, by + bar_h)))
            x += w
        if ime_on and not st["mic"]:
            # Japanese / Chinese / Korean: what you've typed, four ways to write it, and "more"
            # (searching emoji: what you've typed, seven emoji, and "more")
            fr = EMOJI_CELLS if st.get("esearch") else IME_CELLS
            x = gx0
            for i, f in enumerate(fr):
                cw = (gx1 - gx0 + gap) * f / sum(fr)
                act = "ime:raw" if i == 0 else "ime:more" if i == len(fr) - 1 else "ime:%d" % (i - 1)
                items.append((K("", cw, bar=True, act=act, ghost=True), (x, margin, x + cw - gap, margin + strip_h)))
                x += cw
        elif st.get("words") and not st["mic"]:
            # the word bar: three spots to tap. The words themselves are drawn on their own small overlay on top,
            # so they can change with every letter without the whole keyboard being redrawn
            cw = (gx1 - gx0 + gap) / 3
            for i in range(3):
                x = gx0 + i * cw
                items.append((K("", cw, bar=True, act="sugg:%d" % i, ghost=True), (x, margin, x + cw - gap, margin + strip_h)))
        y0 = top if (below or not bar) else top + bar_h + gap * 1.6
        offset = (ref_rows - len(rows)) / 2 if st["page"] in ("lang", "fmt") else ref_rows - len(rows)
        for i, r in enumerate(rows):
            y = y0 + (i + offset) * uph
            rw = sum(k["w"] for k in r) * upx
            x = (self.W - rw) / 2
            for k in r:
                w = k["w"] * upx
                if not k.get("spacer"):
                    tall = uph if k.get("tall") else 0  # numpad + and Enter span two rows
                    items.append((k, (x, y, x + w - gap, y + uph + tall - gap)))
                x += w
        self.metrics = {"upx": upx, "uph": uph, "gap": gap, "margin": margin, "y0": y0}
        gy = (by + bar_h + gap * 2.0) if (below and bar) else y0 + ref_rows * uph + gap * 0.6
        # the bar you hold to move it: in the middle, under the whole keyboard (every layout)
        gcx = self.W / 2
        rs = upx * 0.42
        gh = max(8, uph * 0.1)
        gyc = gy - gap * 0.2 + (rs - gh) / 2     # (centred between the keys and the bottom edge, level with the corner handles)
        grab = (gcx - upx * 1.6, gyc, gcx + upx * 1.6, gyc + gh)
        resize = (gx1 - rs, gy - gap * 0.2, gx1, gy - gap * 0.2 + rs)
        # turn handle: bottom left, mirroring the resize corner (turns the keyboard where it stands)
        lx0 = self.W - gx1
        self.metrics["rotate"] = (lx0, gy - gap * 0.2, lx0 + rs, gy - gap * 0.2 + rs)
        H = int(max(grab[3], resize[3]) + margin * 0.6)
        width_m = self.W / upx * pw * conf.get("scale", 1.0)
        return items, grab, resize, (self.W, H), width_m, strip_h

    def draw(self, st, conf):
        with self.draw_lock:   # (one drawing at a time on this drawer: they share its measurements)
            return self._draw(st, conf)

    def _draw(self, st, conf):
        from PIL import Image, ImageDraw
        self.set_cjk(st.get("lang"))
        items, grab, resize, (W, H), width_m, strip_h = self.layout(st, conf)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if st.get("panel", conf.get("panel", True)):  # a slightly see-through back behind the keys
            boxes = [b for _, b in items] + [grab, resize]
            if strip_h:
                boxes.append((self.grid[0], self.strip_box[0], self.grid[1], self.strip_box[1]))
            pad = max(10, (boxes[0][3] - boxes[0][1]) * 0.28)
            px0 = max(1, min(b[0] for b in boxes) - pad)
            py0 = max(1, min(b[1] for b in boxes) - pad)
            px1 = min(W - 2, max(b[2] for b in boxes) + pad)
            py1 = min(H - 2, max(b[3] for b in boxes) + pad * 0.6)
            a = int(255 * max(0.0, min(1.0, conf.get("panel_opacity", 1.0))))
            d.rounded_rectangle((px0, py0, px1, py1), radius=pad * 1.6, fill=PAL["panel"] + (a,), outline=(255, 255, 255, 30), width=2)
        # the language picker: one text size for every name, so the grid looks even
        picks = [(k, b) for k, b in items if "pick" in k]
        if picks:
            hh = min(b[3] - b[1] for _, b in picks)
            ww = min(b[2] - b[0] for _, b in picks)
            subs = any(k["pick"] for k, _ in picks)
            sizes = sorted(self.fit_font(d, k["label"], hh * (0.36 if subs else 0.4), ww - hh * 0.4).size for k, _ in picks)
            self.pick_px = sizes[0]
            self.pick_cap = sizes[len(sizes) // 4]   # what nearly every name fits at
            self.pick_sub = min(self.fit_font(d, k["pick"], hh * 0.2, ww - hh * 0.3).size for k, _ in picks if k["pick"]) \
                if any(k["pick"] for k, _ in picks) else 0
        self.draw_keys(img, d, items, st)
        d.rounded_rectangle(grab, radius=(grab[3] - grab[1]) / 2, fill=PAL["grab"])
        # the corner handles: resize (bottom right) and tilt (bottom left). Drawn four times larger and scaled down, so the
        # strokes are smooth all along with no blobs at their ends
        x0, y0, x1, y1 = resize
        lw = max(4, int((x1 - x0) * 0.16))
        self.draw_handles(img, resize, self.metrics.get("rotate"), lw)
        if strip_h:  # the empty word bar (its words go on top)
            gx0, gx1 = self.grid
            sy0, sy1 = self.strip_box
            d.rounded_rectangle((gx0, sy0, gx1, sy1), radius=(sy1 - sy0) * 0.35, fill=PAL["strip"])
        return img, items, grab, resize, width_m

    def draw_keys(self, img, d, items, st):
        up = st["shift"] != st["caps"]
        lang = LANG.get(st.get("lang"))
        alt = st.get("alt", -1)
        layer = lang["layers"][alt] if 0 <= alt < len(lang["layers"]) else {}
        # (Shift stands in for Caps Lock only on a layout with no Caps key of its own, like Minimal)
        # (decided by the layout itself, never by which keys happen to be in this picture)
        lay_caps = any(k.get("act") == "caps" for r in rows_for(st["layout"], "abc", st.get("lang", "en-US"),
                                                               st.get("fmt", "default"), st) for k in r)
        caps_on_shift = st["caps"] and not lay_caps
        for k, (x0, y0, x1, y1) in items:
            if k.get("ghost"):
                continue
            h = min(y1 - y0, (x1 - x0) * 1.25)  # tall keys (numpad + and Enter) keep normal-size text
            if k.get("tall") and getattr(self, "metrics", None):
                h = min(h, self.metrics["uph"] - self.metrics["gap"])
            lit = (k.get("act") == "shift" and (st["shift"] or caps_on_shift)) or (k.get("act") == "caps" and st["caps"]) \
                or (k.get("act") == "ctrl" and st.get("ctrl")) or (k.get("act") == "alt-mod" and st.get("altm")) \
                or (k.get("act") == "fn" and st.get("fn")) or (k.get("act") == "super" and st.get("meta")) \
                or (k.get("act") == "numlock" and st.get("numlock", True)) \
                or (k.get("altkey") and alt >= 0)
            fn_on = st.get("fn") and k.get("act") in FN
            accented = ("ch" in k and k["ch"] in layer) or fn_on
            fill = PAL["rec"] if k.get("rec") else PAL["on"] if (k.get("bar") and k.get("on")) else PAL["bar"] if k.get("bar") else \
                PAL["go"] if k.get("go") else PAL["on"] if lit else PAL["accent"] if accented else PAL["mod"] if k.get("mod") else PAL["key"]
            d.rounded_rectangle((x0, y0, x1, y1), radius=h * 0.2, fill=fill,
                                outline=PAL.get("outline"), width=max(1, int(h * 0.04)) if PAL.get("outline") else 0)
            if (k.get("act") in st.get("locks", ())) or (k.get("act") == "caps" and st["caps"]) or (k.get("act") == "shift" and caps_on_shift):
                # locked on (a double tap): a short bar along the bottom, like a laptop's Caps Lock light
                pad_, by_ = h * 0.22, y1 - h * 0.13   # (along the whole key, in from its rounded corners)
                d.rounded_rectangle((x0 + pad_, by_ - h * 0.03, x1 - pad_, by_ + h * 0.03), radius=h * 0.03, fill=PAL["text"])
            label, sub = k["label"], ""
            if "ch" in k:
                c = layer.get(k["ch"], k["ch"])
                label = LANG.show(LANG.shifted(c) if up else c)
                if lang.get("romaji"):  # Japanese typed in English letters: show the sound each key starts
                    sub = ROMAJI_HINT.get(k["ch"], "")
                elif lang.get("labels") == "cangjie" and k["ch"] in LANG.CANGJIE:  # Cangjie: the radical, and its letter
                    label, sub = LANG.CANGJIE[k["ch"]], k["ch"].upper()
            elif k.get("altkey"):  # accent key: shows the next set it will switch to
                layers = lang["layers"]
                nxt = alt + 1
                sample = "abc" if nxt >= len(layers) else next(iter(layers[nxt].values()))
                label = sample if sample == "abc" else (LANG.upper(sample) if up else sample)
            elif "sym" in k:
                label, sub = (k["sym"][1], k["sym"][0]) if st["shift"] else k["sym"]
                if st["caps"] and not st["shift"] and label.isalpha():
                    label = LANG.upper(label)
                label, sub = LANG.show(label), LANG.show(sub)
            if "np" in k and not st.get("numlock", True):  # Num Lock off: 7 is Home, 8 is up, ...
                label = k["nplabel"] or k["label"]
            if k.get("act") == "shift" and caps_on_shift and not lang.get("kana"):
                label = "Caps"
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if fn_on:  # Fn is on: show what this key does now
                name = FN[k["act"]][0]
                d.text((cx, cy), name, font=self.fit_font(d, name, h * 0.3, (x1 - x0) * 0.86), fill=PAL["text"], anchor="mm")
            elif k.get("semo"):   # one of Steam's emoticons: its picture
                self.draw_semo(img, d, k["semo"], cx, cy, h * (0.72 if k.get("bar") else 0.8), (x1 - x0) * 0.9)
            elif k.get("emoji"):  # a colour emoji, drawn from the emoji font
                self.draw_emoji(img, d, k["label"], cx, cy, h * (0.7 if k.get("bar") else 0.74))   # (big: they're the point of the page)
            elif k.get("icon") and k.get("off") and k["icon"] in ("left", "right"):  # page arrow with nowhere to go: dimmed
                draw_icon(img, k["icon"], cx, cy, h * 0.5, PAL["sub"], fill)
            elif k.get("icon"):
                draw_icon(img, k["icon"], cx, cy, h * {"mic": 0.72, "sound": 0.64, "panel": 0.74, "globe": 0.64, "preview": 0.68, "words": 0.66, "search": 0.6, "gear": 0.64, "swipe": 0.7, "curve": 0.7, "emoji": 0.72, "cut": 0.6, "copy": 0.6, "paste": 0.6, "undo": 0.6, "selall": 0.72, "recenter": 0.62,
                                                       "lay-minimal": 1.6, "lay-full": 1.6, "lay-advanced": 1.6}.get(k["icon"], 0.5),
                          PAL["text"], fill, slash=k.get("off"))
            elif k.get("altkey"):
                d.text((cx, cy), label, font=self.font(h * (0.3 if label == "abc" else 0.36), label), fill=PAL["text"], anchor="mm")
            elif "pick" in k:  # language picker: the name, and the variant underneath
                # most names share one size; a long one (Bahasa Indonesia) only shrinks itself, not the rest
                f = self.fit_font(d, label, self.pick_cap, (x1 - x0) - h * 0.4)
                if k["pick"]:
                    d.text((cx, cy - h * 0.12), label, font=f, fill=PAL["text"], anchor="mm")
                    d.text((cx, cy + h * 0.25), k["pick"], font=self.font(self.pick_sub, k["pick"]),
                           fill=(205, 222, 240, 255) if k.get("on") else PAL["sub"], anchor="mm")
                else:
                    d.text((cx, cy), label, font=f, fill=PAL["text"], anchor="mm")
            elif k.get("bar") and k.get("sample"):  # layout picker: name, and the first letters underneath
                f = self.fit_font(d, label, h * 0.34, (x1 - x0) - h * 0.35)
                d.text((cx, cy - h * 0.14), label, font=f, fill=PAL["text"], anchor="mm")
                d.text((cx, cy + h * 0.24), k["sample"], font=self.fit_font(d, k["sample"], h * 0.2, (x1 - x0) * 0.8),
                       fill=(205, 222, 240, 255) if k.get("on") else PAL["sub"], anchor="mm")
            elif k.get("bar"):
                if k.get("fitlabel"):  # picker buttons: fit their own text
                    f = self.fit_font(d, label, h * 0.4, (x1 - x0) - h * 0.35)
                else:  # top bar: one size for every button
                    f = self.font(getattr(self, "bar_px", h * 0.4), label)
                d.text((cx, cy), label, font=f, fill=PAL["text"], anchor="mm")
            elif (k.get("mod") or k.get("go")) and not k.get("center"):
                d.text((x0 + h * 0.24, cy), label, font=self.font(h * 0.26, label), fill=PAL["text"], anchor="lm")
            elif k.get("center"):
                d.text((cx, cy), label, font=self.fit_font(d, label, h * 0.32, (x1 - x0) * 0.84), fill=PAL["text"], anchor="mm")
            else:
                if sub:
                    d.text((cx, cy - h * 0.22), sub, font=self.font(h * 0.19, sub), fill=PAL["sub"], anchor="mm")
                f = self.fit_font(d, label, h * (0.3 if sub else 0.35), (x1 - x0) * 0.86)
                d.text((cx, cy + h * (0.12 if sub else 0.03)), label, font=f, fill=PAL["text"], anchor="mm")
            if k.get("fav") and not fn_on:   # one of your favorites: a small star in its corner (on top of the emoji)
                self.draw_star(d, x1 - h * 0.17, y0 + h * 0.17, h * 0.1)

    def draw_handles(self, img, resize, rot, lw):
        """Resize corner and tilt handle, each drawn four times larger on its own small tile and scaled down."""
        from PIL import Image, ImageDraw
        k = 4
        col = PAL["grab"]

        def tile_for(box, paint):
            bx0, by0 = int(box[0]) - lw * 2, int(box[1]) - lw * 2
            bx1, by1 = int(box[2]) + lw * 2, int(box[3]) + lw * 2
            t = Image.new("RGBA", ((bx1 - bx0) * k, (by1 - by0) * k), (0, 0, 0, 0))
            d = ImageDraw.Draw(t)
            L = lambda x, y: ((x - bx0) * k, (y - by0) * k)
            paint(d, L, lw * k)
            img.alpha_composite(t.resize((bx1 - bx0, by1 - by0), Image.LANCZOS), (bx0, by0))

        def line(d, L, w, pts):   # a smooth stroke: a round brush swept along the path (no seams, no blobs)
            P = [L(*p) for p in pts]
            r = w / 2
            for (ax, ay), (bx, by) in zip(P, P[1:]):
                n = max(1, int(math.hypot(bx - ax, by - ay) / (w / 6)))
                for i in range(n + 1):
                    x, y = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
                    d.ellipse((x - r, y - r, x + r, y + r), fill=col)

        x0, y0, x1, y1 = resize
        X, Y = x1 - lw / 2, y1 - lw / 2
        rc = (x1 - x0) * 0.42
        corner = [(X - rc + rc * math.cos(math.radians(a)), Y - rc + rc * math.sin(math.radians(a))) for a in range(0, 91, 3)]
        tile_for(resize, lambda d, L, w: line(d, L, w, [(X, y0 + lw / 2)] + corner + [(x0 + lw / 2, Y)]))
        if rot:
            tx0, ty0, tx1, ty1 = rot
            cx, cy = (tx0 + tx1) / 2, (ty0 + ty1) / 2
            R = (tx1 - tx0) * 0.36
            a0, a1 = -40, 250            # an open circle (gap at the top right) ending in an arrowhead: "turn"

            def paint(d, L, w):
                lw_ = w * 0.8            # (a little thinner than the resize corner, so the arrowhead reads)
                pts = [(cx + R * math.cos(math.radians(a0 + (a1 - a0) * i / 60)),
                        cy + R * math.sin(math.radians(a0 + (a1 - a0) * i / 60))) for i in range(61)]
                line(d, L, lw_, pts)
                ex, ey = cx + R * math.cos(math.radians(a1)), cy + R * math.sin(math.radians(a1))
                tx, ty = -math.sin(math.radians(a1)), math.cos(math.radians(a1))   # (along the circle, the way it turns)
                nx, ny = -ty, tx
                hw, hl = lw * 1.15, lw * 1.5   # half its width, its length (in the keyboard's pixels)
                bx, by = ex - tx * hl * 0.25, ey - ty * hl * 0.25    # (its base sits just over the stroke's end: joined)
                d.polygon([L(bx + tx * hl, by + ty * hl), L(bx + nx * hw, by + ny * hw), L(bx - nx * hw, by - ny * hw)], fill=col)
            tile_for(rot, paint)

    def draw_star(self, d, cx, cy, r):
        """A small five-pointed star (marks your favorite emoji)."""
        pts = []
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.45
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(pts, fill=(255, 204, 77, 255), outline=(40, 30, 10, 200))

    def draw_wing(self, st, conf, H):
        """The side wing (numpad + editing keys + arrows), same key size and row heights as the main block,
        same height picture, so its rows line up exactly with the keyboard's rows."""
        from PIL import Image, ImageDraw
        m = self.metrics
        upx, uph, gap, margin, y0 = m["upx"], m["uph"], m["gap"], m["margin"], m["y0"]
        W = int(WING_UNITS * upx + 2 * margin)
        img = Image.new("RGBA", (W, int(H)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        items = []
        for k, col, row, w, h in wing_items(conf.get("wing_side", "right")):
            x = margin + col * upx
            y = y0 + row * uph
            items.append((k, (x, y, x + w * upx - gap, y + h * uph - gap)))
        if st.get("panel", conf.get("panel", True)):
            pad = max(10, uph * 0.28)
            a = int(255 * max(0.0, min(1.0, conf.get("panel_opacity", 1.0))))
            d.rounded_rectangle((max(1, margin - pad), max(1, y0 - pad), min(W - 2, W - margin + pad - gap), min(H - 2, y0 + 6 * uph - gap + pad)),
                                radius=pad * 1.6, fill=PAL["panel"] + (a,), outline=(255, 255, 255, 30), width=2)
        self.draw_keys(img, d, items, st)
        return img, items

    def popup(self, text, rec=False, live=False, max_w=20.0):
        """The pop-up above the keyboard: a dark rounded pill just big enough for its text (a red dot while voice
        typing listens). Drawn at 96 px tall; max_w is the widest it may be, in heights. Long voice text keeps its
        newest words, starting with "…"."""
        from PIL import Image, ImageDraw
        H = 96
        f = self.font(H * 0.42, text)
        probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        dot = H * 0.5 if rec else 0
        pad = H * 0.42
        t = text
        while len(t) > 2 and probe.textlength(t, font=f) + dot + pad * 2 > max_w * H:
            t = "…" + t.lstrip("…")[2:]
        W = int(probe.textlength(t, font=f) + dot + pad * 2)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((1, 1, W - 2, H - 2), radius=H / 2 - 1, fill=(16, 20, 27, 238), outline=(255, 255, 255, 40), width=2)
        x = pad
        if rec:
            r = H * 0.11
            d.ellipse((x - r * 0.2, H / 2 - r, x + r * 1.8, H / 2 + r), fill=PAL["rec"])
            x += dot
        d.text((x, H / 2), t, font=f, fill=PAL["text"] if (live or not rec) else PAL["sub"], anchor="lm")
        return img

    def tooltip(self, text, h):
        key = ("tip", text, int(h))
        c = self.cache.setdefault("pics", {})
        if key not in c:
            c[key] = self._tooltip(text, h)
        return c[key]

    def _tooltip(self, text, h):
        """Small dark label shown above an icon you point at."""
        from PIL import Image, ImageDraw
        f = self.font(h * 0.5, text)
        probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        w = probe.textlength(text, font=f) + h * 0.9
        img = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((1, 1, w - 2, h - 2), radius=h * 0.45, fill=(12, 16, 22, 240), outline=(255, 255, 255, 50), width=2)
        d.text((w / 2, h / 2), text, font=f, fill=(255, 255, 255, 255), anchor="mm")
        return img

    FLICK_W = 360  # flick guide picture: always this size (3 x 3 cells)

    def flick_guide(self, chars, sel):
        """A cross: the middle kana with the other four around it (left, up, right, down); the pick is lit."""
        from PIL import Image, ImageDraw
        ss, W = 2, self.FLICK_W
        c = W * ss // 3
        img = Image.new("RGBA", (W * ss, W * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        spots = [(1, 1), (0, 1), (1, 0), (2, 1), (1, 2)]
        for i, ch in enumerate(chars[:5]):
            gx, gy = spots[i]
            box = (gx * c + c * 0.05, gy * c + c * 0.05, gx * c + c * 0.95, gy * c + c * 0.95)
            d.rounded_rectangle((box[0] + 6, box[1] + 10, box[2] + 6, box[3] + 10), radius=c * 0.18, fill=(0, 0, 0, 90))
            d.rounded_rectangle(box, radius=c * 0.18, fill=PAL["go"] if i == sel else PAL["key"],
                                outline=(255, 255, 255, 60), width=ss * 2)
            f = self.font(c * 0.55, ch)
            d.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), ch, font=f, fill=PAL["text"], anchor="mm")
        return img.resize((W, W), Image.LANCZOS)

    def bubble(self, text, w, h):
        key = ("bubble", text, int(w), int(h), PAL["key"], PAL["glow"], PAL["text"])
        c = self.cache.setdefault("pics", {})
        if key not in c:
            if len(c) > 600:
                c.clear()
            c[key] = self._bubble(text, w, h)
        return c[key]

    def _bubble(self, text, w, h):
        """The letter you're pointing at, in a small rounded bubble just above the key (like a phone keyboard).
        Drawn three times larger and scaled down, so edges and letters come out smooth."""
        from PIL import Image, ImageDraw
        k = 3
        W, H = int(w) * k, int(h) * k
        tail = H * 0.10
        body = H - tail
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        r = W * 0.24
        pad = W * 0.05
        # soft shadow, then the bubble with a small point toward the key
        d.rounded_rectangle((pad, pad + k * 3, W - pad, body - pad + k * 3), radius=r, fill=(0, 0, 0, 70))
        bg = tuple(min(255, c + 22) for c in PAL["key"][:3]) + (255,)   # (a touch lighter than the keys, so it stands out)
        d.polygon([(W / 2 - tail * 1.1, body - pad - 2), (W / 2 + tail * 1.1, body - pad - 2), (W / 2, H - 2)], fill=PAL["glow"])
        d.rounded_rectangle((pad, pad, W - pad, body - pad), radius=r, fill=bg, outline=PAL["glow"], width=k * 2)
        f = self.fit_font(d, text, body * 0.5, (W - 2 * pad) * 0.72)
        d.text((W / 2, (body - pad + pad) / 2), text, font=f, fill=PAL["text"], anchor="mm")
        return img.resize((int(w), int(h)), Image.LANCZOS)

    def highlight(self, w, h, pressed):
        """Outline image for the key under the laser. Drawn on its own small overlay, so the keyboard isn't redrawn."""
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        lw = max(2, int(h * 0.03))
        d.rounded_rectangle((lw / 2, lw / 2, w - lw / 2 - 1, h - lw / 2 - 1), radius=h * 0.2,
                            fill=(0, 0, 0, 70) if pressed else (255, 255, 255, 34), outline=PAL["glow"], width=lw)
        return img


# --------------------------------------------------------------------------- math helpers
def mat_to_pos_rot(m):
    return (m[0][3], m[1][3], m[2][3]), [[m[i][j] for j in range(3)] for i in range(3)]


# Pictures SteamVR is sent over and over always keep the same size. Each new size makes SteamVR set up a new
# texture, and after enough of those it starts refusing pictures: the keyboard stops updating ("freezes").
BUB_W, BUB_H = 96, 112    # letter bubble
TIP_W = 576               # icon label (text centred on a fixed-width strip)
WORDS_W = 960             # word bar (its own overlay over the strip above the keys)
TRAIL_W = 520             # swipe line (stretched over the whole keyboard; sharp enough not to look blurry)
TRAIL_PIX = 110000        # swipe line: most pixels a picture of it may have (the same as the old full-keyboard one)

def words_picture(want, tw, th, font, cells):
    """The word bar's picture: the word being swiped, or up to three words to pick from."""
    from PIL import Image, ImageDraw
    ss = 2
    img = Image.new("RGBA", (tw * ss, th * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    H = th * ss

    def put(text, cx, cw, color, size):
        f = font(size, text)
        while size > H * 0.25 and d.textlength(text, font=f) > cw * 0.9:
            size *= 0.9
            f = font(size, text)
        while len(text) > 2 and d.textlength(text, font=f) > cw * 0.9:
            text = text[:-2] + "…"
        d.text((cx, H / 2), text, font=f, fill=color, anchor="mm")

    if want[0] == "preview":
        word = want[1]
        if word:
            f = font(H * 0.5, word)
            w = d.textlength(word, font=f) + H * 0.9
            cx = tw * ss / 2
            d.rounded_rectangle((cx - w / 2, H * 0.12, cx + w / 2, H * 0.88), radius=H * 0.38, fill=PAL["accent"])
            put(word, cx, tw * ss * 0.6, PAL["text"], H * 0.5)
    else:
        _, words, sel, mode = want
        for i, (u0, u1) in enumerate(cells):
            x0, x1 = u0 * tw * ss, u1 * tw * ss
            if i and words:
                d.line((x0 - H * 0.05, H * 0.28, x0 - H * 0.05, H * 0.72), fill=PAL["sub"][:3] + (90,), width=max(1, ss))
            if i < len(words):
                if mode == "swipe" and i == sel:
                    d.rounded_rectangle((x0 + H * 0.12, H * 0.12, x1 - H * 0.12, H * 0.88), radius=H * 0.38, fill=PAL["accent"])
                dim = mode == "type" and i == 0
                put(words[i], (x0 + x1) / 2, x1 - x0, PAL["sub"] if dim else PAL["text"], H * 0.48)
    return img.resize((tw, th), Image.LANCZOS)


IME_CELLS = [1.3, 1.2, 1.2, 1.2, 1.2, 0.5]  # word bar for converted languages: typed | 4 choices | more
EMOJI_CELLS = [2.2] + [0.85] * 7 + [0.5]     # word bar while searching emoji: what you typed | 7 emoji | more


def emoji_bar_picture(want, tw, th, renderer, cells):
    """The word bar while searching emoji: ✕ and what you've typed (tap to stop searching), the emoji found, ›."""
    from PIL import Image, ImageDraw
    ss = 2
    img = Image.new("RGBA", (tw * ss, th * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    H = th * ss
    _, query, found, more = want
    xs = [(u0 * tw * ss, u1 * tw * ss) for u0, u1 in cells]
    x0, x1 = xs[0]
    d.text((x0 + H * 0.3, H / 2), "✕", font=renderer.font(H * 0.42), fill=PAL["sub"], anchor="lm")
    text = query + "▏" if query else "Type to search emoji"
    f = renderer.font(H * 0.42, text)
    while len(text) > 2 and d.textlength(text, font=f) > (x1 - x0) - H * 1.1:
        text = "…" + text[2:]
    d.text((x0 + H * 0.85, H / 2), text, font=f, fill=PAL["text"] if query else PAL["sub"], anchor="lm")
    if query and not found:
        d.text(((xs[1][0] + xs[-2][1]) / 2, H / 2), "No emoji found", font=renderer.font(H * 0.36), fill=PAL["sub"],
               anchor="mm")
    for (c0, c1), e in zip(xs[1:-1], found):
        g = renderer.emoji_glyph(e)
        if g is None:
            d.text(((c0 + c1) / 2, H / 2), e, font=renderer.font(H * 0.5, e), fill=PAL["text"], anchor="mm")
            continue
        size = min(H * 0.66, (c1 - c0) * 0.8)
        sc = size / max(g.width, g.height)
        gi = g.resize((max(1, int(g.width * sc)), max(1, int(g.height * sc))), Image.LANCZOS)
        img.alpha_composite(gi, (int((c0 + c1) / 2 - gi.width / 2), int(H / 2 - gi.height / 2)))
    if more:
        x0, x1 = xs[-1]
        d.text(((x0 + x1) / 2, H / 2), "›", font=renderer.font(H * 0.6), fill=PAL["text"], anchor="mm")
    return img.resize((tw, th), Image.LANCZOS)


def ime_picture(want, tw, th, font, cells):
    """The word bar while typing Japanese / Chinese / Korean: what you've typed (tap to send it as it is),
    the ways it can be written (the chosen one lit), and › for more."""
    from PIL import Image, ImageDraw
    ss = 2
    img = Image.new("RGBA", (tw * ss, th * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    H = th * ss
    _, typed, cands, sel, more = want

    def put(text, x0, x1, color, size, left=False):
        cw = x1 - x0
        f = font(size, text)
        while size > H * 0.22 and d.textlength(text, font=f) > cw * 0.9:
            size *= 0.92
            f = font(size, text)
        while len(text) > 2 and d.textlength(text, font=f) > cw * 0.9:
            text = ("…" + text[2:]) if left else (text[:-2] + "…")
        if left:
            d.text((x0 + H * 0.2, H / 2), text, font=f, fill=color, anchor="lm")
        else:
            d.text(((x0 + x1) / 2, H / 2), text, font=f, fill=color, anchor="mm")
    xs = [(u0 * tw * ss, u1 * tw * ss) for u0, u1 in cells]
    if typed:
        x0, x1 = xs[0]
        put(typed, x0, x1, PAL["sub"], H * 0.44, left=True)
        f = font(H * 0.44, typed)
        w = min(x1 - x0 - H * 0.3, d.textlength(typed, font=f))
        d.line((x0 + H * 0.2, H * 0.78, x0 + H * 0.2 + w, H * 0.78), fill=PAL["sub"][:3] + (140,), width=max(1, ss))
    for i, (x0, x1) in enumerate(xs[1:-1]):
        if i and i < len(cands):
            d.line((x0 - H * 0.05, H * 0.28, x0 - H * 0.05, H * 0.72), fill=PAL["sub"][:3] + (90,), width=max(1, ss))
        if i < len(cands):
            if i == sel:
                d.rounded_rectangle((x0 + H * 0.08, H * 0.12, x1 - H * 0.08, H * 0.88), radius=H * 0.36, fill=PAL["accent"])
            put(cands[i], x0, x1, PAL["text"], H * 0.5)
    if more:
        x0, x1 = xs[-1]
        put("›", x0, x1, PAL["text"], H * 0.6)
    return img.resize((tw, th), Image.LANCZOS)


def trail_picture(line, W, H):
    """The swipe line: one clean, sharp stroke that fades smoothly toward its tail, on a fixed-size picture
    covering the whole keyboard. Drawn at twice the size and scaled down, so its edges are crisp and smooth."""
    from PIL import Image, ImageDraw, ImageFilter
    tw, th, ss = TRAIL_W, max(8, round(TRAIL_W * H / W)), 2
    k = tw * ss / W
    core = Image.new("L", (tw * ss, th * ss), 0)
    d = ImageDraw.Draw(core)
    loc = [(x * k, y * k) for x, y in line]
    n = len(loc)
    wd = max(2, int(round(6.0 * k)))
    r = wd / 2
    # each little piece a touch brighter than the one behind it: a smooth fade, no steps
    for j in range(n - 1):
        f = (j + 1) / (n - 1)
        v = int(255 * 0.9 * f ** 1.5)
        if v < 6:
            continue
        (x0, y0), (x1, y1) = loc[j], loc[j + 1]
        d.line((x0, y0, x1, y1), fill=v, width=wd)
        d.ellipse((x1 - r, y1 - r, x1 + r, y1 + r), fill=v)   # round joints
    core = core.reduce(ss)   # average each 2x2: smooth edges, and quick
    glow = core.filter(ImageFilter.BoxBlur(max(1, 1.1 * k))).point(lambda p: int(p * 0.5))
    out = Image.new("RGBA", (tw, th), (90, 160, 255, 0))
    out.putalpha(glow)
    top = Image.new("RGBA", (tw, th), (235, 244, 255, 0))
    top.putalpha(core)
    out.alpha_composite(top)
    return out


def trail_box(line, W, H, kw):
    """The part of the keyboard the swipe line covers (with room for its width and glow), in keyboard pixels, and how
    many picture pixels each keyboard pixel gets: at least the keyboard's own sharpness, more for a short line."""
    pad = 14
    x0 = max(0, int(min(x for x, _ in line) - pad)); x1 = min(W, int(max(x for x, _ in line) + pad) + 1)
    y0 = max(0, int(min(y for _, y in line) - pad)); y1 = min(H, int(max(y for _, y in line) + pad) + 1)
    # (a little extra each way, rounded, so the box doesn't change size every frame while you move)
    q = 24
    x0, y0 = max(0, x0 // q * q), max(0, y0 // q * q)
    x1, y1 = min(W, -(-x1 // q) * q), min(H, -(-y1 // q) * q)
    bw, bh = max(8, x1 - x0), max(8, y1 - y0)
    k = min(2.0, math.sqrt(TRAIL_PIX / float(bw * bh)))
    return x0, y0, bw, bh, k


def trail_picture_box(line, box):
    """The swipe line drawn only over its own box, sharp: three times the size, then scaled down smoothly."""
    from PIL import Image, ImageDraw, ImageFilter
    x0, y0, bw, bh, k = box
    tw, th, ss = max(4, int(round(bw * k))), max(4, int(round(bh * k))), 3
    kk = k * ss
    core = Image.new("L", (tw * ss, th * ss), 0)
    d = ImageDraw.Draw(core)
    loc = [((x - x0) * kk, (y - y0) * kk) for x, y in line]
    n = len(loc)
    wd = max(3, int(round(6.0 * kk)))
    r = wd / 2
    for j in range(n - 1):
        f = (j + 1) / (n - 1)
        v = int(255 * 0.9 * f ** 1.5)
        if v < 6:
            continue
        (ax, ay), (bx, by) = loc[j], loc[j + 1]
        d.line((ax, ay, bx, by), fill=v, width=wd)
        d.ellipse((bx - r, by - r, bx + r, by + r), fill=v)   # round joints
    core = core.resize((tw, th), Image.LANCZOS)   # smooth, sharp edges
    glow = core.filter(ImageFilter.GaussianBlur(max(1.0, 2.2 * k))).point(lambda p: int(p * 0.55))
    out = Image.new("RGBA", (tw, th), (90, 160, 255, 0))
    out.putalpha(glow)
    top = Image.new("RGBA", (tw, th), (235, 244, 255, 0))
    top.putalpha(core)
    out.alpha_composite(top)
    return out


SORT = 0  # the keyboard's layers (keys 10, highlights 11, ...) stay below SteamVR's own laser and its dot
SORT_TOP = 40   # "Always on top": the whole keyboard above windows (still under SteamVR's laser)


def facing(pos, head):
    """Yaw and pitch that make the keyboard face your head, like SteamVR's own windows and keyboard."""
    dx, dy, dz = pos[0] - head[0], pos[1] - head[1], pos[2] - head[2]
    yaw = math.atan2(-dx, -dz)
    pitch = -math.atan2(-dy, math.hypot(dx, dz))
    return yaw, pitch


def rot(yaw, pitch):
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    return [[cy, sy * sp, sy * cp], [0, cp, -sp], [-sy, cy * sp, cy * cp]]  # Ry(yaw) * Rx(pitch)


def make_matrix(openvr, pos, R):
    m = openvr.HmdMatrix34_t()
    for i in range(3):
        for j in range(3):
            m.m[i][j] = R[i][j]
        m.m[i][3] = pos[i]
    return m


def ray_plane(o, d, p0, n):
    den = sum(d[i] * n[i] for i in range(3))
    if abs(den) < 1e-6:
        return None
    t = sum((p0[i] - o[i]) * n[i] for i in range(3)) / den
    return [o[i] + d[i] * t for i in range(3)] if t > 0 else None


# --------------------------------------------------------------------------- the app
class Gaze:
    """Where you look, on the keyboard: the key you look at lights up (blue), and, if those settings are on,
    pressing A / X types it, or looking at it long enough does. The eyes are read by bfgaze.py, a separate
    small program (so the keyboard's own controller input is never touched); it only runs while one of these
    settings is on."""
    PREFS = os.path.join(CONF_DIR, "prefs.json")
    ACTIVE = os.path.join(CONF_DIR, "gaze-active")
    COLOR = (0.55, 0.8, 1.0)

    def __init__(self, app):
        self.app = app
        self.glow = self.type = self.menus = False
        self.dwell = 0.0
        self.proc = self.sock = None
        self.retry_at = 0.0
        self.hands_on = False
        self.hands_proc = None
        self.hands_retry = 0.0
        self.show_hands = False
        self.kb_pinch = False
        self.view_proc = None
        self.view_retry = 0.0
        self.pts = []
        self.key = self.cand = None
        self.cand_t = self.key_t = 0.0
        self.dwelled = None
        self.a_was = False
        self.last_rx = 0.0
        self.active_on = False

    def load(self):
        try:
            with open(self.PREFS) as f:
                p = json.load(f)
        except Exception:
            p = {}
        try:
            import bfmode
            p = bfmode.apply(p)        # "Control the menus with" (Settings > Tracking) decides the rest
        except Exception:
            pass                       # (the keyboard on its own: no eyes or hands)
        self.glow = bool(p.get("gaze_glow", False))
        self.menus = bool(p.get("gaze_ui", False)) or (bool(p.get("hand_on")) and bool(p.get("hand_ui")))
        self.hands_on = bool(p.get("hand_on", False))
        self.mover_on = bool(p.get("mover_on", False))
        self.show_hands = bool(p.get("hand_models", False))
        # look at a key and pinch to type it (the keyboard snaps your look to the key: much easier than aiming)
        self.kb_pinch = bool(p.get("gaze_ui", False)) and p.get("gaze_kb", True) is not False
        st = getattr(self.app, "st", None)
        if st is not None and st.get("eyes") != self.kb_pinch:     # the eye button on the keyboard shows it
            st["eyes"] = self.kb_pinch
            self.app.dirty = True
        # with the look-to-select pointer on, it clicks the keyboard like everything else: no double typing here
        self.type = bool(p.get("gaze_type", False)) and not self.menus
        # typing by holding your look on a key: only in Custom (the modes don't type by looking alone)
        self.dwell = 0.0 if (self.menus or p.get("ctl_mode", "off") != "custom") else max(0.0, float(p.get("gaze_dwell", 0) or 0)) / 1000.0
        self.sync()

    def on(self):
        return self.glow or self.type or self.dwell > 0 or self.menus or self.hands_on

    def sync(self):
        if self.on():
            if self.sock is None:
                import socket
                try:
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    self.sock.bind(("127.0.0.1", 47900))
                    self.sock.setblocking(False)
                except OSError as ex:
                    LOG("gaze: can't listen:", ex)
                    self.sock = None
            alive = self.proc is not None and self.proc.poll() is None
            if not alive and time.time() >= self.retry_at and os.path.exists(os.path.join(HERE, "bfgaze.py")):
                if self.proc is not None:
                    LOG("gaze: the eye reader stopped (code %s); trying again in 30 s" % self.proc.returncode)
                self.retry_at = time.time() + 30
                try:
                    self.proc = subprocess.Popen([sys.executable, os.path.join(HERE, "bfgaze.py")], stdin=subprocess.DEVNULL)
                    LOG("gaze: eye reader started")
                except Exception as ex:
                    LOG("gaze: couldn't start the eye reader:", ex)
                    self.proc = None
        else:
            self.stop_eyes()
        # hand tracking: its own program too (bfhands.py), only while it's switched on
        hands_alive = self.hands_proc is not None and self.hands_proc.poll() is None
        if not hands_alive and self.hands_proc is not None and self.hands_proc.returncode == 0:
            self.hands_proc, self.hands_retry = None, 0.0      # it stopped because it was switched off: fine
        if self.hands_on and not hands_alive and time.time() >= self.hands_retry and os.path.exists(os.path.join(HERE, "bfhands.py")):
            if self.hands_proc is not None:
                LOG("hands: hand tracking stopped (code %s); trying again in 30 s" % self.hands_proc.returncode)
            self.hands_retry = time.time() + 30
            try:
                self.hands_proc = subprocess.Popen([sys.executable, os.path.join(HERE, "bfhands.py")], stdin=subprocess.DEVNULL)
                LOG("hands: hand tracking started")
            except Exception as ex:
                LOG("hands: couldn't start hand tracking:", ex)
                self.hands_proc = None
        elif not self.hands_on and hands_alive:
            self.stop_hands()
        # moving the play space: its own program (bfmover.py), only while it's switched on; it stops by itself (and puts
        # your real play space back) when switched off
        mp = self.__dict__.get("mover_proc")
        mover_alive = mp is not None and mp.poll() is None
        if mp is not None and not mover_alive and mp.returncode == 0:
            self.mover_proc, mp = None, None
        if getattr(self, "mover_on", False) and not mover_alive and time.time() >= getattr(self, "mover_retry", 0.0) \
                and os.path.exists(os.path.join(HERE, "bfmover.py")):
            if mp is not None:
                LOG("play space: the mover stopped (code %s); trying again in 30 s" % mp.returncode)
            self.mover_retry = time.time() + 30
            try:
                self.mover_proc = subprocess.Popen([sys.executable, os.path.join(HERE, "bfmover.py")], stdin=subprocess.DEVNULL)
                LOG("play space: mover started")
            except Exception as ex:
                LOG("play space: couldn't start the mover:", ex)
                self.mover_proc = None
        # hands drawn on your controllers in the menu: its own program too (bfhandsview.py)
        view_alive = self.view_proc is not None and self.view_proc.poll() is None
        if not view_alive and self.view_proc is not None and self.view_proc.returncode == 0:
            self.view_proc, self.view_retry = None, 0.0        # it stopped because it was switched off: fine
        if self.show_hands and not view_alive and time.time() >= self.view_retry and os.path.exists(os.path.join(HERE, "bfhandsview.py")):
            if self.view_proc is not None:
                LOG("hands view: stopped (code %s); trying again in 30 s" % self.view_proc.returncode)
            self.view_retry = time.time() + 30
            try:
                self.view_proc = subprocess.Popen([sys.executable, os.path.join(HERE, "bfhandsview.py")], stdin=subprocess.DEVNULL)
                LOG("hands view: started")
            except Exception as ex:
                LOG("hands view: couldn't start:", ex)
                self.view_proc = None
        want = self.on() and self.app.visible
        if want != self.active_on:
            self.active_on = want
            try:
                if want:
                    open(self.ACTIVE, "w").close()
                elif os.path.exists(self.ACTIVE):
                    os.remove(self.ACTIVE)
            except OSError:
                pass

    def on_kb_flag(self, on):
        """Tell the pointer your look is on the keyboard (the keyboard types it; the laser shouldn't click too)."""
        if on != getattr(self, "kb_flag", False):
            self.kb_flag = on
            path = os.path.join(CONF_DIR, "gaze-on-kb")
            try:
                if on:
                    open(path, "w").close()
                elif os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    def stop_hands(self):
        if self.hands_proc is not None:
            try:
                self.hands_proc.terminate()
                self.hands_proc.wait(timeout=3)
            except Exception:
                try:
                    self.hands_proc.kill()
                except Exception:
                    pass
            self.hands_proc = None

    def stop(self):
        """Everything off (the keyboard is turned off, or SteamVR closed)."""
        self.stop_hands()
        if self.view_proc is not None:
            try:
                self.view_proc.terminate()
                self.view_proc.wait(timeout=3)
            except Exception:
                try:
                    self.view_proc.kill()
                except Exception:
                    pass
            self.view_proc = None
        self.stop_eyes()

    def stop_eyes(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        self.set_key(None)

    def set_key(self, idx):
        if idx != self.key:
            self.key, self.key_t, self.dwelled = idx, time.time(), None
            app = self.app
            lit = self.glow or self.kb_pinch          # (typing by look + pinch: you need to see which key)
            if idx is None or not lit:
                app.hovers.pop("gaze", None)
            else:
                app.hovers["gaze"] = idx
            if lit or idx is None:
                app.place_highlight("gaze")

    def a_pressed(self):
        app, vr = self.app, self.app.vr
        down = False
        for role in (vr.TrackedControllerRole_LeftHand, vr.TrackedControllerRole_RightHand):
            try:
                dev = app.system.getTrackedDeviceIndexForControllerRole(role)
                if dev == vr.k_unTrackedDeviceIndexInvalid:
                    continue
                ok, st = app.system.getControllerState(dev)
                if ok and st.ulButtonPressed & (1 << vr.k_EButton_A):
                    down = True
            except Exception:
                pass
        edge = down and not self.a_was
        self.a_was = down
        return edge

    def tick(self):
        """Called every pass of the keyboard's main loop."""
        app = self.app
        if self.sock is None:
            return
        got = None
        while True:
            try:
                got = self.sock.recv(64)
            except (BlockingIOError, OSError):
                break
        if not app.visible:
            self.pts = []
            self.set_key(None)
            self.on_kb_flag(False)
            return
        now = time.time()
        if got is not None and len(got) == 36:
            t, ox, oy, oz, dx, dy, dz, ok = struct.unpack("<d6fI", got)
            self.last_rx = now
            pinch = bool(ok & 2)
            if pinch and not getattr(self, "pinch_was", False):
                self.pinch_new = True
            self.pinch_was = pinch
            hit = None
            if ok:
                vr = app.vr
                params = vr.VROverlayIntersectionParams_t()
                params.eOrigin = vr.TrackingUniverseStanding
                params.vSource.v[0], params.vSource.v[1], params.vSource.v[2] = ox, oy, oz
                params.vDirection.v[0], params.vDirection.v[1], params.vDirection.v[2] = dx, dy, dz
                try:
                    inside, res = app.ov.computeOverlayIntersection(app.handle, params)
                    if inside:
                        W, H = app.img_size
                        hit = (res.vUVs.v[0] * W, (1 - res.vUVs.v[1]) * H)
                except Exception:
                    hit = None
            if hit is None:
                self.pts = []
            else:
                self.pts = (self.pts + [hit])[-6:]   # the last few looks, so eye jitter doesn't flick between keys
            self.on_kb_flag(hit is not None and self.kb_pinch)
        elif now - self.last_rx > 0.3:
            self.pts = []
        idx = None
        if self.pts:
            xs = sorted(p[0] for p in self.pts)
            ys = sorted(p[1] for p in self.pts)
            h = app.item_at(xs[len(xs) // 2], ys[len(ys) // 2], "main")
            idx = h if isinstance(h, int) and not isinstance(h, bool) else None
        if idx != self.cand:
            self.cand, self.cand_t = idx, now
        if self.cand != self.key and (self.cand is None or now - self.cand_t >= 0.08):
            self.set_key(self.cand)
        k = self.key
        a = self.a_pressed() if self.type else False
        pinched = self.kb_pinch and getattr(self, "pinch_new", False)
        self.pinch_new = False
        if pinched and self.cand is not None and self.cand < len(app.items):
            k = self.cand                       # what you're looking at right now (not a moment ago)
            if k != self.key:
                self.set_key(k)
        if k is None or k >= len(app.items):
            return
        if a or pinched or (self.dwell > 0 and self.dwelled != k and now - self.key_t >= self.dwell):
            self.dwelled = k
            app.hpressed["gaze"] = now + 0.12
            app.place_highlight("gaze")
            app.press(app.items[k][0])


from aimfade import AimFade, bind as _aim_bind   # fade when not aiming (see aimfade.py)
_aim_bind(make_matrix=make_matrix, mat_to_pos_rot=mat_to_pos_rot, save_conf=save_conf, pal=lambda: PAL)


class App(AimFade):
    def __init__(self):
        import openvr
        self.vr = openvr
        self.conf = load_conf()
        self.streamer = os.path.exists(os.path.join(CONF_DIR, "streamer-on"))  # hide what you type from viewers
        self.st = {"layout": self.conf["layout"], "page": "abc", "shift": False, "caps": False, "mic": False,
                   "sounds": self.conf["sounds"], "live": "", "msg": "",
                   "panel": bool(self.conf.get("panel", True)), "lang": self.conf.get("lang", "en-US"), "alt": -1,
                   "hover": True, "bubble": bool(self.conf.get("bubble", True)), "ctrl": False, "altm": False, "fn": False, "meta": False, "numlock": True,
                   "fmt": self.conf.get("fmt", "default"), "swipe": bool(self.conf.get("swipe", False)), "words": bool(self.conf.get("words", False)),
                   "curved": bool(self.conf.get("curved", True))}
        if self.st["lang"] not in LANG.BY_CODE:
            self.st["lang"] = "en-US"
        self.romaji = LANG.Romaji()
        # Japanese / Chinese / Korean: typed text waits in the word bar until it's converted and sent
        self.comp, self.comp_lang = None, None
        self.esq, self.es_page = "", 0         # emoji search: what's typed, which page of results
        self.st["esearch"] = False
        self.st["etone"] = int(self.conf.get("emoji_tone", -1))
        self.st["semo"], self.st["semo_gen"] = (), 0   # Steam's emoticons (filled in the background: here from the start)
        self.ime_sel, self.ime_page, self.ime_busy, self.ime_shown = -1, 0, False, None
        self.msg_until = 0
        self.ctrl, self.alt = False, False
        self.meta = False
        self.last_shift = 0
        self.renderer = Renderer(self.conf.get("font", ""))
        self.sounds = Sounds(self.conf["volume"])
        try:
            real = VKeyboard()
            self.vk = QueuedKeyboard(real)
        except Exception as e:
            real = self.vk = None
            LOG("virtual keyboard unavailable:", e)
        self.dict = Dictation(self.on_live, self.on_final, lambda m: self.flash(m))
        self.unicode = UnicodeTyper(real, self.conf) if real else None
        self.hover, self.pressed, self.pressed_until = None, None, 0
        self.hl_key = None
        self.dirty = True
        self.drag = None
        self.visible = False
        self.pos, self.yaw, self.pitch = [0, 1.2, -0.5], 0.0, -0.45
        self.width_m = 0.9
        self.img_size = (1, 1)
        self.toggle_block_until = 0
        # two-hand typing
        self.hands = None
        self.hovers, self.hpressed, self.hls, self.hl_keys, self.beams, self.beam_w = {}, {}, {}, {}, {}, {}
        self.steam_dev, self.steam_dev_t = None, 0
        self.steam_px, self.steam_on = None, False
        self.calib = dict(self.conf.get("aim_calib") or {})  # per hand: aim direction in the controller's own frame, learned from SteamVR's laser
        self.cursors = {}
        self.repeat = None
        self.held = {}           # laser slot -> item its trigger went down on
        self.ehold = {}          # laser slot -> an emoji being pressed (tap: types it; hold: favorite)
        self.grip = {}           # laser slot -> (controller, buttons, axes) holding it down
        self.slot_seen = {}      # laser slot -> last time SteamVR told us about it
        self.lcal, self.dev_seen, self.dev_moved, self.dev_last_pt, self.stolen_t = {}, {}, {}, {}, 0
        self.duck_t, self.ducked = 0, 0.0
        self.seen_cursors = set()

    # ---- feedback
    def reset_keyboard(self):
        """Size, position and tilt back to how they started (your settings, layouts and favorites stay)."""
        for k in ("distance", "drop", "side", "scale"):
            self.conf[k] = DEFAULTS[k]
        self.conf["roll"] = 0.0
        for k in ("turn", "dash_off"):
            self.conf.pop(k, None)
        save_conf(self.conf)
        self.dirty = True
        if self.visible:
            self.redraw()
            self.recenter()
        LOG("keyboard reset: size, position and tilt back to how they started")

    @staticmethod
    def emo_key(v):
        """The same emoji or Steam emoticon however it was written down (:mikuDIVA: and :mikudiva:, Steam's own
        ːmikuDIVAː colons, stray spaces): so it's in Favorites and Recent only once."""
        v = (v or "").strip().replace("\u02d0", ":")
        return v.lower() if len(v) > 2 and v[0] == ":" and v[-1] == ":" else v

    def dedupe_emoji(self):
        """Favorites and Recent with each emoji once (keeps the first: the newest). Fixes lists saved by older
        versions, which could hold the same emoticon twice."""
        for name in ("emoji_fav", "emoji_recent"):
            seen, out = set(), []
            for x in self.conf.get(name, []):
                key = self.emo_key(x)
                if key and key not in seen:
                    seen.add(key)
                    out.append(x.strip().replace("\u02d0", ":"))   # (Steam's own colons: shown as the picture too)
            if out != self.conf.get(name, []):
                self.conf[name] = out
                save_conf(self.conf)
                LOG("emoji %s: took out doubles (%d left)" % ("favorites" if name == "emoji_fav" else "recent", len(out)))

    def toggle_fav(self, k):
        """Add an emoji (or Steam emoticon) to your Favorites, or take it off if it's there already."""
        v = k.get("ins")
        if not v:
            return
        self.dedupe_emoji()
        key = self.emo_key(v)
        favs = [x for x in self.conf.get("emoji_fav", []) if self.emo_key(x) != key]
        added = len(favs) == len(self.conf.get("emoji_fav", []))
        if added:
            favs = [v] + favs[:59]
        self.conf["emoji_fav"] = favs
        save_conf(self.conf)
        self.st["efav"] = tuple(favs)
        self.dirty = True
        if self.st["sounds"]:
            self.sounds.play("big")
        self.flash("Added to Favorites" if added else "Removed from Favorites", 1.5)
        LOG("emoji favorites: %s %s (%d now)" % ("added" if added else "removed", v, len(favs)))

    def check_voice(self):
        """Right after the mic is pressed, ask voice typing's helper if it's ready (in the background, the keyboard
        never waits on it), and say so if not, so the mic never just silently does nothing."""
        def work():
            try:
                with urllib.request.urlopen(HELPER + "/api/status", timeout=2) as r:
                    j = json.loads(r.read() or b"{}")
            except Exception:
                j = None
            msg = None
            busy = self.voice_setting_up() or subprocess.run(
                ["systemctl", "--user", "is-active", "--quiet", "betterframe-repair-voice"]).returncode == 0
            if j is None:
                msg = "Voice typing is still setting up: ready in a few minutes" if busy else \
                    "Voice typing is starting up: try again in a moment"
            elif not j.get("stt"):
                msg = "Voice typing is still setting up: ready in a few minutes" if busy else \
                    "Voice typing isn't installed: run the install again"
            elif not j.get("loaded"):
                msg = "Voice typing is loading: a few seconds"
            if msg:
                LOG("mic:", msg)
                if j is None or not j.get("stt"):
                    self.dict.stop()
                    self.st["mic"], self.st["live"] = False, ""
                    self.dirty = True
                self.flash(msg, 4.0)
        threading.Thread(target=work, daemon=True, name="voice-check").start()

    def voice_setting_up(self):
        """Voice typing still being set up in the background (right after an install)? Only while that's really
        happening: setup's marker is there and less than 10 minutes old, and voice typing's parts aren't all in place.
        Once they are, this never shows again."""
        try:
            if time.time() - os.path.getmtime(os.path.join(CONF_DIR, "installing")) > 600:
                return False
        except OSError:
            return False
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        return importlib.util.find_spec("faster_whisper") is None or not os.path.isfile(
            os.path.join(here, "models", "sherpa-onnx-streaming-zipformer-en-2023-06-26", "tokens.txt"))

    def flash(self, msg, secs=2.5):
        """A short message in the pop-up above the keyboard."""
        self.pop_msg = msg
        self.msg_until = time.time() + secs

    def on_live(self, text):
        # called from the dictation thread; shown by the main loop at most ~7 times a second
        self.live_pending = text

    def on_final(self, text):
        if not self.conf.get("dictation_punctuation"):
            text = plain_text(text)
        if text:
            self.type_text(text + " ")

    def type_text(self, s):
        """Plain letters and symbols go straight through the virtual keyboard; anything else (é, ñ, Greek,
        kana...) is pasted in, in the right order."""
        if not self.vk:
            self.flash("Typing needs /dev/uinput access. Run install-overlay.sh.")
            return
        stream = getattr(self.vk, "stream", None)
        if isinstance(stream, SteamUIText):
            # one of Steam's own text boxes: everything goes straight in, kana, kanji and é included (pasting can't
            # reach Steam's windows: Japanese typed there came out as nothing, or as whatever was on the clipboard)
            self.vk.type_text(s)
            self.pre_sent = (id(stream), "")   # (this replaced any live Japanese/Chinese text in the box)
            return
        if isinstance(stream, StreamText):
            # a streamed game: all of it through Steam (pasting on the headset can't reach the PC), emoji included
            self.vk.type_text(s)
            return
        run, kind = "", None
        for ch in s + "\0":
            k = "end" if ch == "\0" else ("plain" if self.vk.can_type(ch) else "other")
            if k != kind and run:
                if kind == "plain":
                    self.vk.type_text(run)
                elif hasattr(self.vk, "call"):  # pasted from the typing worker, in order with everything else
                    self.vk.call(self.paste_text, run)
                else:
                    self.paste_text(run)
                run = ""
            run, kind = run + ch if k != "end" else run, k

    def steam_send(self, run):
        """Letters the virtual keyboard has no key for (ą, é, ñ, Cyrillic...), sent the way Steam's own keyboard
        sends text: straight into what you're typing in, in Steam and SteamVR's menus (where pasting doesn't reach)."""
        if getattr(self, "send_url", None) is None:
            if time.time() - getattr(self, "send_tried", 0) < 30:
                return False
            self.send_tried = time.time()
            self.send_url = StreamText.find()
            if not self.send_url:
                LOG("typing other letters: Steam's keyboard text isn't reachable right now")
                return False
        try:
            import dashpin
            res = dashpin.run_js(self.send_url, StreamText.JS % json.dumps(list(run)))   # (one character at a time)
            ok = res == "ok"
        except Exception as ex:
            ok, res = False, ex
        if not ok:
            LOG("typing other letters: Steam's keyboard text failed:", str(res)[:160])
            self.send_url = None
        return ok

    def in_desktop_mode(self):
        """Desktop Mode or Game Mode? Desktop Mode is whenever KDE's desktop (plasmashell) is running: exactly what
        worked before for typing é, emoji and the like in desktop apps. (Going by Game Mode's own program instead
        sent Desktop Mode's emoji the Game Mode way: they came out wrong.) Looked at every 5 s."""
        if time.time() - getattr(self, "mode_t", 0) > 5:
            self.mode_t = time.time()
            desk = False
            uid = os.getuid()
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                try:
                    if os.stat("/proc/" + pid).st_uid != uid:
                        continue
                    with open("/proc/%s/comm" % pid) as f:
                        if f.read().strip() == "plasmashell":
                            desk = True
                            break
                except OSError:
                    continue
            if getattr(self, "desktop", None) is not desk:
                LOG("typing other letters: %s" % ("Desktop Mode" if desk else "Game Mode"))
            self.desktop = desk
        return self.desktop

    def paste_text(self, run):
        # Letters with no key of their own (ą, ę, ñ, emoji...). Desktop Mode: pasted, which desktop apps take.
        # Game Mode: sent the way Steam's own keyboard sends text first; if Steam can't be reached, pasted with the
        # letter put on every clipboard there is (the app you're in may read any one of them), never only one.
        desktop = self.in_desktop_mode()
        if any(is_emoji(c) for c in run):
            # emoji: only ever pasted. Steam's text channel splits them up and apps typed numbers instead ("1111")
            if self.unicode and self.unicode.type(run, everywhere=not desktop):
                return
            if time.time() - getattr(self, "paste_flashed", 0) > 10:
                self.paste_flashed = time.time()
                self.flash("Emoji can't be typed here")
            LOG("emoji: couldn't paste here, so nothing was typed (never sent as numbers)")
            return
        if not desktop and self.steam_send(run):
            if not getattr(self, "send_said", False):
                self.send_said = True
                LOG("typing other letters through: Steam's keyboard text (Game Mode)")
            return
        if self.unicode and self.unicode.type(run, everywhere=not desktop):
            return
        if not desktop and self.steam_send(run):
            if not getattr(self, "send_said", False):
                self.send_said = True
                LOG("typing other letters through: Steam's keyboard text")
            return
        if time.time() - getattr(self, "paste_flashed", 0) > 10:  # say it once, not on every letter (each one redraws)
            self.paste_flashed = time.time()
            self.flash("Can't type “%s” here yet" % run[:6])

    def replace_typed(self, n, text):
        """Erase the last n characters typed and type text instead (Japanese romaji -> kana)."""
        if self.vk:
            for _ in range(n):
                self.vk.tap(KEY["BACKSPACE"])
            self.type_text(text)

    def layer_map(self):
        lang = LANG.get(self.st.get("lang"))
        a = self.st.get("alt", -1)
        return lang["layers"][a] if 0 <= a < len(lang["layers"]) else {}

    def char_for(self, k):
        """What a key types right now (Shift, Caps and the accent key taken into account)."""
        st = self.st
        if "ch" in k:
            c = self.layer_map().get(k["ch"], k["ch"])
            c = LANG.shifted(c) if st["shift"] != st["caps"] else c
            return LANG.TYPES.get(c, c)
        if "sym" in k:
            if st["shift"]:
                return LANG.TYPES.get(k["sym"][1], k["sym"][1])
            a = k["sym"][0]
            return LANG.upper(a) if st["caps"] and a.isalpha() else a
        return k.get("ins")

    # ---- openvr setup
    def start_vr(self):
        vr = self.vr
        self.system = vr.init(vr.VRApplication_Overlay)
        self.ov = vr.VROverlay()
        # two copies of the keyboard: a new picture goes onto the hidden one, which is then shown on top
        # before the old one hides, so pressing Shift (or anything that redraws) never flashes
        self.multi = self.conf.get("two_hands", "native") == "native"
        self.kb_gen = 0
        self.kbs = [self.make_kb_copy("betterframe.keyboard", "BetterFrame Keyboard"),
                    self.make_kb_copy("betterframe.keyboard.b", "BetterFrame Keyboard (buffer)")]
        self.handle = self.kbs[0]
        # the Advanced layout's side wing (numpad, editing keys, arrows): its own overlay next to the keyboard
        self.wing = self.ov.createOverlay("betterframe.keyboard.wing", "BetterFrame Keyboard numpad")
        self.ov.setOverlayInputMethod(self.wing, vr.VROverlayInputMethod_Mouse)
        self.ov.setOverlayFlag(self.wing, vr.VROverlayFlags_MakeOverlaysInteractiveIfVisible, True)
        if self.multi:
            try:
                self.ov.setOverlayFlag(self.wing, vr.VROverlayFlags_MultiCursor, True)
            except Exception:
                pass
        self.set_sort(self.wing, 10)
        self.wing_on, self.wing_key, self.wing_size, self.wing_shown = False, None, (1, 1), False
        self.kb_scale = {}       # mouse scale set on each copy
        self.kb_content = {}     # which picture each copy currently holds
        self.hl_pool, self.hl_shown, self.hl_tint, self.hl_width = {}, {}, {}, {}  # reusable key highlights (shared)
        self.hl_curve = {}
        self.bubbles, self.bubble_tex, self.bubble_shown = {}, {}, {}  # letter bubbles, one per laser
        self.bubble_sent, self.bubble_wait = {}, {}
        self.atlas = {}          # bubble overlay -> the picture of all bubbles/labels it holds  # last new bubble picture per laser, bubble waiting for the laser to settle
        self.swipes = {}         # laser slot -> swipe in progress
        self.flicks = {}         # laser slot -> Japanese flick in progress
        self.gaze = Gaze(self)   # where you look (only when a gaze setting is on)
        self.flick_ov, self.flick_pic = None, None
        self.trail, self.trail_shown = [], 0
        self.last_swipe, self.auto_space = "", False
        # word bar
        self.words_ov, self.words_shown, self.words_tex, self.words_geom, self.words_sent = None, False, None, None, 0.0
        self.word_list, self.word_mode, self.word_sel, self.cur_word, self.words_due = [], "type", -1, "", False
        self.preview_word, self.preview_busy, self.preview_t, self.preview_n = "", False, 0.0, 0
        self.preview_gen, self.swipe_gen, self.comp_index = 0, 0, {}
        self.decode_lock = threading.Lock()
        try:
            import swipe as _sw
            self.decoder = _sw.Decoder()
        except Exception as ex:
            LOG("swipe typing unavailable:", ex)
            self.decoder = None
        self.rcache = {}         # drawn keyboard pictures, by look
        self.up_times, self.up_backoff, self.up_count, self.up_slowest, self.up_logged = [], 0, 0, 0.0, 0
        self.wait_key, self.wait_t, self.slow_paints = None, 0, 0
        self.rlock = threading.Lock()
        self.kb_width = {}       # width set on each copy
        self.pending_hide = None
        self.kill_kb_until, self.last_kill = 0, 0
        self.last_touch = 0      # last time a laser was on our keyboard
        self.last_press = 0      # last time a key was pressed
        self.dash_hide_pending = False
        self.last_checks = 0
        self.live_pending, self.last_live = None, 0
        self.hl = self.ov.createOverlay("betterframe.keyboard.highlight", "BetterFrame Keyboard highlight")
        self.set_sort(self.hl, 11)
        self.aim_init()          # fade when not aiming: its button, and the keyboard solid to start with
        self.tog = None  # small open/close button on the left controller: off unless "hand_button": true
        if self.conf.get("hand_button"):
            self.tog = self.ov.createOverlay("betterframe.keyboard.toggle", "BetterFrame Keyboard button")
            self.ov.setOverlayInputMethod(self.tog, vr.VROverlayInputMethod_Mouse)
            self.ov.setOverlayFlag(self.tog, vr.VROverlayFlags_MakeOverlaysInteractiveIfVisible, True)
            self.ov.setOverlayWidthInMeters(self.tog, 0.05)
            self.ov.setOverlayMouseScale(self.tog, vr.HmdVector2_t(128, 128))
            self.upload_toggle()
            self.attach_toggle()
            self.ov.showOverlay(self.tog)
        if self.conf.get("two_hands") == "own":
            try:
                from hands import Hands
                self.hands = Hands(vr, self.system, self.conf, LOG)
            except Exception as e:
                LOG("two-hand typing unavailable:", e)
        LOG("two-hand typing:", "SteamVR lasers (multi-cursor)" if self.multi else self.conf.get("two_hands"))
        self.redraw()
        if self.conf.get("start_visible"):
            self.set_visible(True)
        LOG("running (hidden until you open it)" if not self.visible else "running")

    def set_sort(self, h, layer):
        """Put one of the keyboard's pieces in its drawing layer (remembered, so "Always on top" can move them all)."""
        self.__dict__.setdefault("sorts", {})[h] = layer
        try:
            self.ov.setOverlaySortOrder(h, (SORT_TOP if getattr(self, "on_top", False) else SORT) + layer)
        except Exception:
            pass

    def resort(self):
        for h, layer in list(getattr(self, "sorts", {}).items()):
            self.set_sort(h, layer)

    def make_kb_copy(self, key, name):
        vr = self.vr
        h = self.ov.createOverlay(key, name)
        self.ov.setOverlayInputMethod(h, vr.VROverlayInputMethod_Mouse)
        self.ov.setOverlayFlag(h, vr.VROverlayFlags_MakeOverlaysInteractiveIfVisible, True)
        try:   # the stick's up/down while a laser is on it (as windows scroll): pushes and pulls it while you move it
            self.ov.setOverlayFlag(h, getattr(vr, "VROverlayFlags_SendVRSmoothScrollEvents", 1 << 17), True)
        except Exception as ex:
            LOG("stick scrolling unavailable:", ex)
        if self.multi:
            try:  # each controller gets its own SteamVR laser on the keyboard, like SteamVR's own keyboard
                self.ov.setOverlayFlag(h, vr.VROverlayFlags_MultiCursor, True)
            except Exception as e:
                LOG("multi-laser mode unavailable:", e)
                self.multi = False
        self.aim_apply_input(h)   # (see-through right now: a fresh copy lets the lasers through too)
        self.set_sort(h, 10)
        return h

    def send_keyboard_picture(self, new, old, buf, size):
        """Put the keyboard picture on the hidden copy. If SteamVR refuses it: try a lighter (smaller) version
        of the same picture, then a brand-new copy. The copy you're looking at is never touched, so the
        keyboard can't disappear while this sorts itself out."""
        attempts = [(1.0, False)]
        last = None
        for sc, fresh in attempts:
            if fresh:
                if time.time() - getattr(self, "last_rebuild", 0) < 1.0:
                    continue
                self.last_rebuild = time.time()
                new = self.fresh_copy(new)
            try:
                if sc >= 1.0:
                    self.timed_raw(new, buf, size[0], size[1])
                else:
                    from PIL import Image
                    w, h = max(8, int(size[0] * sc)), max(8, int(size[1] * sc))
                    small = Image.frombuffer("RGBA", size, bytes(buf), "raw", "RGBA", 0, 1).resize((w, h), Image.BILINEAR)
                    data = small.tobytes()
                    self.timed_raw(new, (ctypes.c_char * len(data)).from_buffer_copy(data), w, h)
                    if getattr(self, "tex_scale", 1.0) != sc:
                        LOG("SteamVR refused the full-size keyboard picture; using a %d%% one" % round(sc * 100))
                    self.tex_scale = sc
                    self.tex_since = time.time()
                if sc >= 1.0:
                    self.tex_scale = 1.0
                return new
            except Exception as ex:
                last = ex
        raise last if last else RuntimeError("keyboard picture refused")

    def reconnect(self, why):
        """SteamVR keeps a little of every picture an app sends it, and after enough of them it refuses any
        more from that app (the keyboard stops changing and buttons seem dead). Reconnecting hands all of
        that back: the keyboard disconnects from SteamVR and connects again, in under a second, and carries
        on exactly where it was (same spot, same keys)."""
        now = time.time()
        if now - getattr(self, "last_reconnect", 0) < 8:
            return False
        self.last_reconnect = now
        LOG("reconnecting to SteamVR (%s; %.0f MB of pictures sent)" % (why, getattr(self, "conn_bytes", 0) / 1e6))
        vis = self.visible
        pos, yaw, pitch = list(self.pos), self.yaw, self.pitch
        for h in list(getattr(self, "kbs", [])):
            try:
                self.ov.hideOverlay(h)
            except Exception:
                pass
        try:
            self.vr.shutdown()
        except Exception as ex:
            LOG("disconnect:", ex)
        # everything that belonged to the old connection is gone: start those parts fresh
        self.visible = False
        self.atlas, self.hls, self.hl_keys, self.beams, self.cursors = {}, {}, {}, {}, {}
        self.trail_ovs, self.trail_hide = None, None
        self.flick_ov, self.flick_pic = None, None
        self.words_ov, self.words_shown, self.words_tex, self.words_geom = None, False, None, None
        self.pop_ov, self.pop_tex, self.pop_geom, self.pop_shown = None, None, None, False
        self.img_size, self.kb_fail, self.fade, self.pending_hide = (1, 1), 0, None, None
        self.vr_refusing, self.refusals, self.conn_bytes = False, [], 0
        self.dirty = True
        self.start_vr()
        self.pos, self.yaw, self.pitch = pos, yaw, pitch
        if vis:
            self.set_visible(True, recenter=False)
        LOG("reconnected")
        return True

    def fresh_copy(self, h):
        """Replace one (hidden) copy of the keyboard with a brand-new one."""
        LOG("SteamVR stopped taking keyboard pictures: making a fresh copy")
        self.kb_gen += 1
        try:
            self.ov.hideOverlay(h)
            self.ov.destroyOverlay(h)
        except Exception:
            pass
        nh = self.make_kb_copy("betterframe.keyboard.r%d" % self.kb_gen, "BetterFrame Keyboard")
        self.kbs = [nh if x == h else x for x in self.kbs]
        for d in (self.kb_content, self.kb_scale, self.kb_width):
            d.pop(h, None)
        if self.pending_hide and self.pending_hide[0] == h:
            self.pending_hide = None
        return nh

    def upload_raw(self, handle, img, optional=False, soft=False):
        """Send a picture to SteamVR. Sending pictures is the one thing SteamVR can choke on if it gets too
        many (it starts refusing them and the whole keyboard lags), so extras like the letter bubble and
        the swipe line are skipped whenever SteamVR is busy; keys and highlights always go through."""
        now = time.time()
        if optional:
            recent = [t for t in self.up_times if now - t < 1.0]
            if now < self.up_backoff or len(recent) >= 8:
                return False
        if soft and now < self.up_backoff and now - getattr(self, "trail_ok", 0) < 0.25:
            return False  # (the swipe line: skip a frame while SteamVR is busy, but never for long, or it looks gone)
        data = img.tobytes()
        buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
        self.timed_raw(handle, buf, img.width, img.height, count=not soft)
        if soft:
            self.trail_ok = time.time()
        return True

    def timed_raw(self, handle, buf, w, h, count=True):
        now = time.time()
        t0 = time.perf_counter()
        if getattr(self, "vr_refusing", False):
            raise RuntimeError("OverlayError_RequestFailed (waiting to reconnect)")
        try:
            self.ov.setOverlayRaw(handle, buf, w, h, 4)
        except Exception:
            self.up_backoff = time.time() + 2.0  # SteamVR refused it: give it a break from extras
            if not count:
                raise  # a swipe-line frame: skipped, never a reason to reconnect
            self.refusals = [t for t in getattr(self, "refusals", []) if now - t < 10.0] + [now]
            recent = [t for t in self.refusals if now - t < 3.0]
            # SteamVR has stopped taking pictures from us: start over (see reconnect). That's only the real thing
            # after lots of pictures, or when it goes on and on: a few refused while the whole headset is struggling
            # are just that, and starting over then made the keyboard vanish, come back and jump around
            many = getattr(self, "conn_bytes", 0) > 60e6
            if (many and len(recent) >= 3) or (len(self.refusals) >= 12 and now - self.refusals[0] > 6.0):
                self.vr_refusing = True
            elif len(recent) >= 3 and now - getattr(self, "busy_said", 0) > 10:
                self.busy_said = now
                LOG("SteamVR is busy and refusing pictures for now: waiting it out (not reconnecting)")
            raise
        self.conn_bytes = getattr(self, "conn_bytes", 0) + w * h * 4
        dt = time.perf_counter() - t0
        self.up_times = [t for t in self.up_times if now - t < 2.0] + [now]
        self.up_count += 1
        self.up_slowest = max(self.up_slowest, dt)
        if dt > 0.03 and not count:  # a slow swipe-line frame: draw the line less often for a moment (never stop it)
            self.trail_slow = time.time() + 1.5
        elif dt > 0.03:  # SteamVR is struggling: hold off on extras for a moment
            self.up_backoff = time.time() + 1.5
            if now - self.up_logged > 10:
                self.up_logged = now
                LOG("SteamVR took %.0f ms to take a %dx%d picture; easing off" % (dt * 1000, w, h))

    def upload_toggle(self):
        if not self.tog:
            return
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((4, 4, 124, 124), radius=28, fill=(26, 143, 232, 235) if self.visible else (24, 33, 43, 235))
        for y in (44, 64):
            for i in range(4):
                d.rounded_rectangle((26 + i * 20, y - 7, 40 + i * 20, y + 7), radius=3, fill=(255, 255, 255, 255))
        d.rounded_rectangle((36, 77, 92, 91), radius=3, fill=(255, 255, 255, 255))
        self.upload_raw(self.tog, img)

    def attach_toggle(self):
        if not self.tog:
            return False
        vr = self.vr
        idx = self.system.getTrackedDeviceIndexForControllerRole(vr.TrackedControllerRole_LeftHand)
        if idx == vr.k_unTrackedDeviceIndexInvalid:
            return False
        self.ov.setOverlayTransformTrackedDeviceRelative(self.tog, idx, make_matrix(vr, (0.0, 0.03, 0.09), rot(0.0, -1.2)))
        return True

    def poses(self, predict=0.0):
        vr = self.vr
        arr = (vr.TrackedDevicePose_t * vr.k_unMaxTrackedDeviceCount)()
        return self.system.getDeviceToAbsoluteTrackingPose(vr.TrackingUniverseStanding, predict, arr)

    def head(self):
        """Where your head is. While SteamVR resets your view (or its menu restarts) it can briefly report a head
        at the floor or nowhere at all: those readings are ignored, so nothing gets placed in the ground."""
        p = self.poses()[0]
        good = None
        if p.bPoseIsValid:
            pos, rot = mat_to_pos_rot(p.mDeviceToAbsoluteTracking.m)
            det = sum(abs(rot[i][i]) for i in range(3)) + sum(abs(x) for r in rot for x in r)
            if det > 0.5 and pos[1] > 0.25 and not (abs(pos[0]) < 1e-6 and abs(pos[1]) < 1e-6 and abs(pos[2]) < 1e-6):
                good = (pos, rot)
        if good:
            self.last_head = good
            return good
        return getattr(self, "last_head", None) or ((0, 1.5, 0), [[1, 0, 0], [0, 1, 0], [0, 0, 1]])

    def elevation(self, p, head):
        dx, dy, dz = p[0] - head[0], p[1] - head[1], p[2] - head[2]
        return math.atan2(dy, math.hypot(dx, dz))

    # ---- noticing when something else catches the laser over the keyboard
    def note_laser(self, dev, x, y):
        """SteamVR told us this controller's laser is on the keyboard at (x, y): remember that, and (a few
        times a second) the laser's angle on the controller, so we can follow the laser ourselves."""
        now = time.time()
        self.dev_seen[dev] = now
        self.dev_moved[dev] = 0.0
        if now - self.lcal.get(dev, (None, 0))[1] < 0.15:
            return
        pose = self.device_pose(dev) if dev else None    # (controllers only, as always: not the headset's pointer)
        if not pose:
            return
        o, rr = pose
        P = self.px_to_world(x, y)
        v = [P[k] - o[k] for k in range(3)]
        n = math.sqrt(sum(a * a for a in v)) or 1.0
        self.lcal[dev] = ([sum(rr[i][j] * v[i] for i in range(3)) / n for j in range(3)], now)
        self.aim_learn(dev, self.lcal[dev][0])   # (so it can tell when this hand points back at it while see-through)

    def check_stolen(self):
        """If a laser is clearly moving over the keyboard but SteamVR sends the keyboard nothing, something
        else (the Steam bar, a window) is in front of it there and is getting your presses. Move the
        keyboard down out of its way, so the keys work again."""
        now = time.time()
        if now - self.stolen_t < 0.05 or self.drag or not self.visible or getattr(self, "dash_seen", None):
            return
        self.stolen_t = now
        vr = self.vr
        for dev, (dloc, _) in list(self.lcal.items()):
            pose = self.device_pose(dev)
            if not pose:
                continue
            o, rr = pose
            d = [rr[i][0] * dloc[0] + rr[i][1] * dloc[1] + rr[i][2] * dloc[2] for i in range(3)]
            params = vr.VROverlayIntersectionParams_t()
            params.vSource.v[0], params.vSource.v[1], params.vSource.v[2] = o
            params.vDirection.v[0], params.vDirection.v[1], params.vDirection.v[2] = d
            params.eOrigin = vr.TrackingUniverseStanding
            try:
                ok, res = self.ov.computeOverlayIntersection(self.handle, params)
            except Exception:
                return
            if not ok:
                self.dev_last_pt.pop(dev, None)
                continue
            pt = (res.vPoint.v[0], res.vPoint.v[1], res.vPoint.v[2])
            if self.dev_moved.get(dev) == 0.0 or dev not in self.dev_last_pt:
                self.dev_last_pt[dev] = pt  # where the laser was when SteamVR last reported it
                self.dev_moved[dev] = 1e-9
            away = math.dist(pt, self.dev_last_pt[dev])  # straight-line distance, so hand shake never adds up
            if now - self.dev_seen.get(dev, 0) > 0.3 and away > 0.04:
                # the laser moved 4 cm across the keyboard and SteamVR said nothing: it's going elsewhere
                self.dev_moved[dev] = 0.0
                self.dev_seen[dev] = now
                # (it used to move the keyboard down here, guessing the Steam bar was in the way. When the headset was
                # busy, SteamVR missed those messages for no reason and the keyboard sank toward the floor by itself.
                # The keyboard now opens below the Steam bar, so it's never moved without you)
                return

    def duck_under(self, pt):
        (hx, hy, hz), _ = self.head()
        head = (hx, hy, hz)
        target = self.elevation(pt, head) - math.radians(4)
        W, H = self.img_size
        moved, y_before = False, self.pos[1]
        for _ in range(4):
            tops = [self.local_point("main", x, 0)[0] for x in (0, W / 4, W / 2, W * 3 / 4, W)]
            top = max(tops, key=lambda p: self.elevation(p, head))
            cur = self.elevation(top, head)
            if cur <= target:
                break
            dh = math.hypot(top[0] - hx, top[2] - hz)
            dy = dh * (math.tan(cur) - math.tan(target)) + 0.005
            dy = min(dy, self.pos[1] - max(hy - 1.15, FLOOR_MIN + 0.1), 0.25 - (y_before - self.pos[1]))  # never more than 25 cm at once, never into the floor
            if dy <= 0.002:
                break
            self.pos[1] -= dy
            self.yaw, self.pitch = self.face(self.pos, head)
            moved = True
        if moved:
            self.ducked += y_before - self.pos[1]
            self.apply_transform()
            LOG("something in front of the keyboard was catching the laser (probably the Steam bar): moved the keyboard below it")

    def dashboard_spot(self):
        """Where Steam's menu is showing: the middle of its bottom edge (or of its bar), in the room. None if closed."""
        vr = self.vr
        try:
            if not self.ov.isDashboardVisible():
                return None
        except Exception:
            return None
        for key, bottom in (("valve.steam.gamepadui.main", True), ("valve.steam.gamepadui.bar", False)):
            try:
                h = self.ov.findOverlay(key)
                if not h or not self.ov.isOverlayVisible(h):
                    continue
                sc = self.ov.getOverlayMouseScale(h)
                if not (sc.v[0] > 0 and sc.v[1] > 0 and math.isfinite(sc.v[0]) and math.isfinite(sc.v[1])):
                    continue
                c = vr.HmdVector2_t()
                c.v[0], c.v[1] = sc.v[0] / 2, 0.0 if bottom else sc.v[1] / 2
                m = self.ov.getTransformForOverlayCoordinates(h, vr.TrackingUniverseStanding, c).m
                p = (m[0][3], m[1][3], m[2][3])
                if all(math.isfinite(v) for v in p):
                    return p
            except Exception:
                continue
        return None

    def recenter(self):
        (hx, hy, hz), r = self.head()
        d = self.conf["distance"]
        ahead = self.__dict__.pop("place_ahead", False)   # (opened with a controller: just in front of you)
        spot = None if ahead else self.dashboard_spot()
        if spot is not None and math.hypot(spot[0] - hx, spot[2] - hz) > 0.2:
            # Steam's menu is open: right under it, in the middle, like Steam's own keyboard (at your typing
            # distance, so it stays the same size and in reach)
            fx, fz = spot[0] - hx, spot[2] - hz
            n = math.hypot(fx, fz)
            fx, fz = fx / n, fz / n
            menu_bottom = math.atan2(spot[1] - hy, n)                     # how far below your eyes its bottom is
            h_m = self.width_m * self.img_size[1] / max(1, self.img_size[0])
            centre = menu_bottom - math.radians(4) - math.atan2(h_m / 2, d)
            lowest = -math.atan2(max(-0.3, min(0.95, float(self.conf["drop"]))), d)  # (never lower than the usual spot)
            centre = max(lowest, min(math.radians(-12), centre))
            off = self.conf.get("dash_off")
            if isinstance(off, (list, tuple)) and len(off) == 3:
                # where you last put it next to Steam's menu (moved while the menu was open): there again, the same
                # way round the menu, wherever the menu is this time
                try:
                    a, up, dd = (float(v) for v in off)
                    a = math.radians(max(-70.0, min(70.0, a)))
                    fx, fz = fx * math.cos(a) + fz * math.sin(a), -fx * math.sin(a) + fz * math.cos(a)
                    d = max(0.25, min(2.0, dd))
                    centre = max(math.radians(-60), min(math.radians(15), menu_bottom + math.radians(up)))
                except (TypeError, ValueError):
                    pass
            self.pos = [hx + fx * d, max(FLOOR_MIN + 0.1, hy + d * math.tan(centre)), hz + fz * d]
            LOG("placed by Steam's menu")
        else:
            fx, fz = -r[0][2], -r[2][2]
            n = math.hypot(fx, fz) or 1
            fx, fz = fx / n, fz / n
            a = math.radians(self.conf.get("side", 0.0))  # where you last put it, left/right of straight ahead
            fx, fz = fx * math.cos(a) + fz * math.sin(a), -fx * math.sin(a) + fz * math.cos(a)
            drop = max(-0.3, min(0.95, float(self.conf["drop"])))  # (an old saved spot can't put it in the floor)
            if ahead:
                drop = min(drop, 0.3)   # (comfortable to read while holding a controller in your lap)
                fx, fz = -r[0][2], -r[2][2]
                n = math.hypot(fx, fz) or 1
                fx, fz = fx / n, fz / n
            d = max(0.25, min(2.0, float(d)))
            self.pos = [hx + fx * d, max(FLOOR_MIN + 0.1, hy - drop), hz + fz * d]  # (never in the floor, even sitting low)
        # never far below or above your eyes, whatever a saved spot says (a spot remembered next to Steam's menu could
        # put it down by the floor when the menu sat low, e.g. opened with a Steam Controller while seated)
        lo = max(FLOOR_MIN + 0.1, hy - 0.8)
        if not lo <= self.pos[1] <= hy + 0.3:
            LOG("placed too low or high (%.2f m below your eyes): brought up in front of you" % (hy - self.pos[1]))
            self.pos[1] = min(hy + 0.3, max(lo, self.pos[1]))
        self.yaw, self.pitch = self.face(self.pos, (hx, hy, hz))
        # the middle of the keyboard straight in front of you
        self.turn_letters_to(math.atan2(fx, fz), (hx, hy, hz))
        self.apply_transform()

    def letters_px(self):
        """The middle of the whole keyboard (pixels): what Recenter puts straight in front of you, and what stays put
        when the layout changes. (It used to be the middle of the letter keys, which sit left of the middle on Full
        and Advanced: Recenter then put the keyboard off to the right)"""
        return self.img_size[0] / 2, self.img_size[1] / 2

    def letters_world(self):
        return self.local_point("main", *self.letters_px())[0]

    def turn_letters_to(self, want_yaw, head):
        """Swing the keyboard around you (same distance and height) until its letters sit in direction want_yaw."""
        hx, hy, hz = head
        if self.img_size[0] <= 1:
            return
        for _ in range(3):
            L = self.letters_world()
            err = (math.atan2(L[0] - hx, L[2] - hz) - want_yaw + math.pi) % (2 * math.pi) - math.pi
            if abs(err) < 0.002:
                break
            ang = math.atan2(self.pos[0] - hx, self.pos[2] - hz) - err
            rad = math.hypot(self.pos[0] - hx, self.pos[2] - hz)
            self.pos = [hx + rad * math.sin(ang), self.pos[1], hz + rad * math.cos(ang)]
            self.yaw, self.pitch = self.face(self.pos, head)


    def face(self, pos, head):
        """Turn toward your head, and lean back more the lower it sits (like a laptop keyboard)."""
        yaw, pitch = facing(pos, head)
        below = max(0.0, min(1.0, (head[1] - pos[1]) / max(0.05, self.conf["drop"])))
        return yaw, pitch - math.radians(self.conf.get("tilt", 15)) * below

    def R(self):
        # facing you, plus however far you've tilted it with the tilt handle (like a steering wheel: one side up,
        # the other down; it keeps that tilt wherever you move it)
        R = rot(self.yaw, self.pitch)
        a = float(self.conf.get("roll", 0.0))
        if not a:
            return R
        c, sn = math.cos(a), math.sin(a)
        return [[R[i][0] * c + R[i][1] * sn, -R[i][0] * sn + R[i][1] * c, R[i][2]] for i in range(3)]

    def wing_pose(self):
        """Where the wing is: hinged to the keyboard's side edge and turned toward you, so it curves around
        you instead of sticking out flat (easier to reach and to read)."""
        R = self.R()
        s = self.width_m / self.img_size[0]
        ww = self.wing_size[0] * s
        th = math.radians(self.conf.get("wing_angle", 24))
        side = -1 if self.conf.get("wing_side", "right") == "left" else 1
        hinge = side * (self.width_m / 2 + 0.006)
        cx = hinge + side * (ww / 2) * math.cos(th)
        cz = (ww / 2) * math.sin(th)
        a = -side * th  # left wing turns right (toward you), right wing turns left
        Ry = [[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]
        WR = [[sum(R[i][k] * Ry[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        pos = [self.pos[i] + R[i][0] * cx + R[i][2] * cz for i in range(3)]
        return pos, WR

    def frame(self, panel):
        """(position, rotation, metres per pixel, picture width, picture height) of the main keyboard or the wing."""
        s = self.width_m / self.img_size[0]
        if panel == "wing":
            pos, R = self.wing_pose()
            return pos, R, s, self.wing_size[0], self.wing_size[1]
        return self.pos, self.R(), s, self.img_size[0], self.img_size[1]

    def local_point(self, panel, x, y, z=0.0):
        """A spot on the keyboard (pixels) in the world, and the way the keyboard faces there. When it's curved,
        the surface bends toward you around a vertical axis, so things on it follow the bend."""
        pos, R, s, W, H = self.frame(panel)
        lx, ly = (x - W / 2) * s, (H / 2 - y) * s
        cr = self.curve_r() if panel == "main" else None
        if not cr:
            return [pos[i] + R[i][0] * lx + R[i][1] * ly + R[i][2] * z for i in range(3)], R
        th = lx / cr
        c, sn = math.cos(th), math.sin(th)
        X, Z = (cr - z) * sn, cr - (cr - z) * c
        Ry = [[c, 0, -sn], [0, 1, 0], [sn, 0, c]]
        RR = [[sum(R[i][k] * Ry[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        return [pos[i] + R[i][0] * X + R[i][1] * ly + R[i][2] * Z for i in range(3)], RR

    def set_kb_transform(self):
        m = make_matrix(self.vr, self.pos, self.R())
        for h in self.kbs:
            self.ov.setOverlayTransformAbsolute(h, self.vr.TrackingUniverseStanding, m)
        if getattr(self, "wing_on", False):
            pos, WR = self.wing_pose()
            self.ov.setOverlayTransformAbsolute(self.wing, self.vr.TrackingUniverseStanding, make_matrix(self.vr, pos, WR))
        self.aim_place_toggle()   # (the fade button moves with it)

    def curve_r(self):
        """Radius the keyboard bends around (metres), or None when it's flat."""
        if not self.st.get("curved", True) or getattr(self, "no_curve", False):
            return None
        return max(0.3, float(self.conf.get("curve_radius", 0.95)))

    def set_kb_width(self, w):
        for h in self.kbs:
            if abs(self.kb_width.get(h, 0) - w) > 1e-4:
                self.ov.setOverlayWidthInMeters(h, w)
                self.kb_width[h] = w
                R = self.curve_r()
                try:  # 0 = flat, 1 = a closed circle
                    self.ov.setOverlayCurvature(h, min(0.9, w / (2 * math.pi * R)) if R else 0.0)
                except Exception as ex:
                    if R:
                        LOG("curved keyboard unavailable here, staying flat:", ex)
                        self.no_curve = True
        if getattr(self, "wing_on", False):
            self.ov.setOverlayWidthInMeters(self.wing, self.wing_size[0] * w / self.img_size[0])
            self.set_kb_transform()

    def apply_transform(self):
        self.set_kb_transform()
        self.place_highlight()

    def px_to_local(self, x, y):
        s = self.width_m / self.img_size[0]
        return ((x - self.img_size[0] / 2) * s, (self.img_size[1] / 2 - y) * s)

    def render_key(self, st=None):
        c = self.conf
        return (tuple(sorted((st or self.st).items())), c.get("scale", 1.0), tuple(c["pitch_minimal"]), tuple(c["pitch_full"]), c.get("font", ""),
                tuple(c.get("pitch_advanced", ())),
                c.get("panel_opacity", 1.0), getattr(self, "look_gen", 0))  # (the colours too: a picture drawn in the
                # old theme is never shown again after you pick a new one)

    def render(self):
        """The keyboard picture for the current state. Each look (lower case, Shift, Caps, 123, ...) is drawn
        once and kept, ready to send, so switching back to it costs almost nothing."""
        key = self.render_key()
        with self.rlock:
            hit = self.rcache.pop(key, None)
        if hit is None and getattr(self, "async_render", False):
            # draw it in the background: the keyboard keeps responding (lasers, highlights, typing) meanwhile,
            # and the new look appears the moment it's ready. If the background painter is slow or stuck,
            # draw it right here after a moment, so what you see can never stay out of date.
            now = time.time()
            if self.wait_key != key:
                self.wait_key, self.wait_t = key, now
            alive = getattr(self, "painter", None) is not None and self.painter.is_alive()
            if alive and now - self.wait_t < 0.6:
                self.bg_draw(key, dict(self.st))
                return None
            if not alive and hasattr(self, "paint_q"):
                LOG("background drawing stopped; drawing directly")
            elif hasattr(self, "paint_q"):
                self.slow_paints = getattr(self, "slow_paints", 0) + 1
                LOG("background drawing was slow; drew this look directly")
            if not alive or self.slow_paints >= 3:  # it isn't working on this headset: just draw directly from now on
                self.async_render = False
                LOG("drawing directly from now on")
        self.wait_key = None
        if hit is None:
            hit = self.draw_look(self.renderer, self.st)
        with self.rlock:
            self.rcache[key] = hit  # most recent last
            while len(self.rcache) > 10:
                self.rcache.pop(next(iter(self.rcache)))
        self.prewarm()
        return key, hit

    def draw_look(self, renderer, st):
        img, items, grab, resize, width_m = renderer.draw(st, self.conf)
        data = img.tobytes()
        return (img.size, items, grab, resize, width_m, (ctypes.c_char * len(data)).from_buffer_copy(data), dict(renderer.metrics))

    def bg_draw(self, key, st):
        """Queue a look to be drawn by the background painter (one at a time, newest request first)."""
        import queue
        if not hasattr(self, "paint_q"):
            self.paint_q, self.painting = queue.LifoQueue(), set()
            self.renderer2 = Renderer(self.conf.get("font", ""))

            def painter():
                while True:
                    k, look = self.paint_q.get()
                    try:  # nothing may stop this loop: any problem is logged and it carries on
                        with self.rlock:
                            done = k in self.rcache
                        if not done:
                            hit = self.draw_look(self.renderer2, look)
                            with self.rlock:
                                self.rcache[k] = hit
                                while len(self.rcache) > 10:
                                    self.rcache.pop(next(iter(self.rcache)))
                            try:
                                current = self.render_key()
                            except RuntimeError:  # the keyboard changed while we looked: just check again
                                current = None
                            if k == current or current is None:
                                self.dirty = True  # it's the one on screen: show it
                    except BaseException as ex:
                        import traceback
                        LOG("couldn't draw the keyboard:", type(ex).__name__, ex)
                        LOG(traceback.format_exc().rstrip())
                    finally:
                        self.painting.discard(k)
            self.painter = threading.Thread(target=painter, daemon=True)
            self.painter.start()
        if key in self.painting:
            return
        self.painting.add(key)
        self.paint_q.put((key, st))

    def prewarm(self):
        """Draw the look you'll most likely need next (Shift) in the background, so pressing it never stalls,
        even on the big keyboards."""
        if getattr(self, "warming", False) or self.st.get("page") != "abc":
            return
        nxt = dict(self.st, shift=not self.st["shift"])
        key = self.render_key(nxt)
        with self.rlock:
            if key in self.rcache:
                return
        if getattr(self, "async_render", False):
            self.bg_draw(key, nxt)
            return
        self.warming = True

        def work():
            try:
                if not hasattr(self, "renderer2"):
                    self.renderer2 = Renderer(self.conf.get("font", ""))
                hit = self.draw_look(self.renderer2, nxt)
                with self.rlock:
                    if key not in self.rcache:
                        self.rcache[key] = hit
            except Exception as ex:
                LOG("couldn't prepare the next look:", ex)
            finally:
                self.warming = False
        threading.Thread(target=work, daemon=True).start()

    def update_wing(self, size):
        """Advanced layout: draw the wing (only when something on it changed) and keep it beside the keyboard."""
        want = False  # Advanced is now one continuous full-size keyboard (no separate wing)
        main = [it for it in self.items if it[0].get("panel") != "wing"]
        if not want:
            self.items = main
            if self.wing_shown:
                self.ov.hideOverlay(self.wing)
                self.wing_shown = False
            self.wing_on = False
            return
        wkey = (self.st.get("numlock", True), self.st.get("panel", True), self.st.get("fn"), size, self.conf.get("panel_opacity", 1.0),
                round(self.renderer.metrics["upx"], 2))
        if wkey != self.wing_key:
            img, witems = self.renderer.draw_wing(self.st, self.conf, size[1])
            self.upload_raw(self.wing, img)
            self.ov.setOverlayMouseScale(self.wing, self.vr.HmdVector2_t(img.width, img.height))
            self.wing_size, self.wing_key = img.size, wkey
            for k, _ in witems:
                k["panel"] = "wing"
            self.wing_items = witems
        self.items = main + list(getattr(self, "wing_items", []))
        self.wing_on = True
        self.ov.setOverlayWidthInMeters(self.wing, self.wing_size[0] * self.width_m / max(1, self.img_size[0]) if self.img_size[0] > 1 else 0.3)
        if self.visible and not self.wing_shown:
            self.ov.showOverlay(self.wing)
            self.wing_shown = True

    def redraw(self):
        self.redrew_at = time.perf_counter()
        got = self.render()
        if got is None:  # still being drawn in the background
            return
        # what the laser hits must always match the picture you see: if SteamVR refuses the new picture,
        # the old keys stay in charge (so pressing never hits a key that isn't shown yet)
        before = (getattr(self, "items", []), getattr(self, "grab", None), getattr(self, "resize", None),
                  getattr(self, "img_size", (1, 1)), getattr(self, "width_m", 0), list(getattr(self, "pos", [0, 0, 0])))
        try:
            self._redraw(got)
        except Exception:
            self.items, self.grab, self.resize, self.img_size, self.width_m, self.pos = before
            raise

    def _redraw(self, got):
        key, (size, self.items, self.grab, self.resize, width_m, buf, metrics) = got
        self.renderer.metrics = metrics
        img = type("Img", (), {"size": size, "width": size[0], "height": size[1]})  # just the size
        lay = (self.st["layout"], round(width_m, 4))
        if img.size[1] != self.img_size[1] and getattr(self, "last_lay", None) == lay and self.img_size[1] > 1:
            # the "Listening…" strip grew or shrank the top: move the overlay so the keys stay exactly where they were
            dh = img.size[1] - self.img_size[1]
            s = width_m / img.size[0]
            R = self.R()
            self.pos = [self.pos[k] + R[k][1] * dh / 2 * s for k in range(3)]
        self.last_lay = lay
        self.update_wing(size)
        old = self.handle
        if self.kb_content.get(old) == key:  # already showing exactly this
            self.dirty = False
            self.place_highlight()
            return
        # put the picture on the hidden copy while the old one stays on screen; if that copy already
        # holds this picture (e.g. Shift off -> on -> off), nothing needs sending to SteamVR at all
        new = self.kbs[1] if old == self.kbs[0] else self.kbs[0]
        self.finish_fade()
        if self.pending_hide and self.pending_hide[0] == new:
            self.pending_hide = None
        resized = tuple(self.img_size) != tuple(img.size) or abs(getattr(self, "width_m", 0) - width_m) > 1e-4
        if self.kb_content.get(new) != key:
            self.kb_content[new] = None
            new = self.send_keyboard_picture(new, old, buf, size)  # may swap in a fresh copy if SteamVR balks
            self.kb_content[new] = key
        if self.kb_scale.get(new) != img.size:
            self.ov.setOverlayMouseScale(new, self.vr.HmdVector2_t(img.width, img.height))
            self.kb_scale[new] = img.size
        self.img_size = img.size
        self.width_m = width_m
        self.set_kb_width(width_m)
        if getattr(self, "anchor_yaw", None) is not None and self.st.get("page") == "abc":
            self.turn_letters_to(self.anchor_yaw, self.head()[0])
            self.anchor_yaw = None
        if self.wing_on:
            self.ov.setOverlayWidthInMeters(self.wing, self.wing_size[0] * self.width_m / self.img_size[0])
        self.set_kb_transform()
        self.handle = new
        if self.visible:
            self.set_sort(new, 10)
            self.set_sort(old, 9)
            if resized and self.ov.isOverlayVisible(old):
                # switching between Minimal / Full / Advanced: fade one into the other instead of showing both at once
                self.ov.setOverlayAlpha(new, 0.0)
                self.ov.showOverlay(new)
                self.fade = {"new": new, "old": old, "t0": time.time()}
            else:
                self.ov.setOverlayAlpha(new, self.aim_alpha())
                self.ov.showOverlay(new)
                self.pending_hide = (old, time.time() + 0.03)  # hide the old picture once the new one is up
        self.dirty = False
        self.place_highlight()

    FADE = 0.22  # seconds to fade between keyboard sizes (old out, then new in)

    def update_fade(self):
        f = getattr(self, "fade", None)
        if not f:
            return
        t = (time.time() - f["t0"]) / self.FADE
        if t >= 1:
            self.finish_fade()
            return
        def ease(x):
            x = max(0.0, min(1.0, x))
            return x * x * (3 - 2 * x)
        # the old one is mostly gone before the new one comes in, so they never sit half-see-through on top of each other
        a = self.aim_alpha()   # (faded because a laser looked away: the switch between sizes stays faded)
        self.ov.setOverlayAlpha(f["old"], a * (1 - ease(t / 0.55)))
        self.ov.setOverlayAlpha(f["new"], a * ease((t - 0.4) / 0.6))

    def finish_fade(self):
        f = getattr(self, "fade", None)
        if not f:
            return
        self.fade = None
        self.ov.setOverlayAlpha(f["new"], self.aim_alpha())
        if f["old"] != self.handle:
            self.ov.hideOverlay(f["old"])
        self.ov.setOverlayAlpha(f["old"], self.aim_alpha())

    # ---- hover highlight on its own overlay (no keyboard redraw while you move the laser)
    def hl_for(self, slot):
        if slot == "mouse":
            return self.hl
        if slot not in self.hls:
            h = self.ov.createOverlay("betterframe.keyboard.highlight." + slot, "BetterFrame Keyboard highlight " + slot)
            self.set_sort(h, 11)
            self.hls[slot] = h
        return self.hls[slot]

    def place_highlight(self, slot=None):
        if not hasattr(self, "hl"):
            return
        if slot is None:  # refresh every highlight
            for sl in ["mouse"] + list(self.hovers):
                self.place_highlight(sl)
            return
        try:
            self._place_highlight(slot)
        except Exception as ex:  # a highlight that SteamVR won't take this moment must never cost a key press
            if slot == "mouse":
                self.hl_key = None
            else:
                self.hl_keys[slot] = None  # try again next time
            self.report_error(ex)

    def hl_overlay(self, slot, size):
        """A highlight overlay already holding the picture for this key size. Each size is sent to SteamVR
        once and then reused, so moving the laser around and pressing keys sends no new pictures at all."""
        # one pool shared by both lasers: size -> overlays holding that picture (most recently used last)
        pool = self.hl_pool
        mine = self.hl_shown.get(slot)
        busy = {h for s, h in self.hl_shown.items() if s != slot and h}
        if size in pool:
            free = [h for h in pool[size] if h not in busy]
            if free:
                h = mine if mine in free else free[0]
                pool[size] = pool.pop(size)  # mark as recently used
                return h
        total = sum(len(v) for v in pool.values())
        h = None
        if total >= 32:  # reuse the least recently used picture that no laser is showing right now
            for s in list(pool):
                for cand in pool[s]:
                    if cand not in busy and cand != mine:
                        pool[s].remove(cand)
                        if not pool[s]:
                            del pool[s]
                        h = cand
                        break
                if h:
                    break
        if h is None:
            n = self.hl_count = getattr(self, "hl_count", 0) + 1
            h = self.ov.createOverlay("betterframe.keyboard.hl%d" % n, "BetterFrame Keyboard highlight %d" % n)
            self.set_sort(h, 11)
        self.ov.hideOverlay(h)
        for s, shown in self.hl_shown.items():
            if shown == h:
                self.hl_shown[s] = None
        self.hl_tint[h] = None
        self.hl_width[h] = None
        self.upload_raw(h, self.renderer.highlight(size[0], size[1], False))  # if this fails, nothing is kept
        pool.setdefault(size, []).append(h)
        pool[size] = pool.pop(size)
        return h

    def hide_highlight(self, slot):
        h = self.hl_shown.get(slot)
        if h:
            self.ov.hideOverlay(h)
            self.hl_shown[slot] = None

    def place_bubble(self, slot, idx):
        """Bubble with the key's letter, floating just above the key the laser is on. For the icons in the top
        bar it's a small label saying what the icon does instead."""
        b = self.bubbles.get(slot)
        k = self.items[idx][0] if idx is not None and idx < len(self.items) else None
        tip = k.get("tip") if k else None
        text = self.char_for(k) if k and ("ch" in k or "sym" in k or "ins" in k) else None
        if k and "np" in k and not self.st.get("numlock", True):
            text = None
        if slot in self.swipes or (k and k.get("emoji") and not tip):
            text = None  # the emoji itself is already big on the key
        if tip and self.visible:
            text = tip if self.st.get("tips", True) else None   # (Settings > Keyboard > Button labels)
        elif not self.st.get("bubble", True):
            text = None
        if not text or not self.visible or text == " ":
            if b and self.bubble_shown.get(slot):
                self.ov.hideOverlay(b)
                self.bubble_shown[slot] = False
            return
        if b is None:
            b = self.ov.createOverlay("betterframe.keyboard.bubble." + slot, "BetterFrame Keyboard letter bubble " + slot)
            self.set_sort(b, 14)
            self.bubbles[slot] = b
        x0, y0, x1, y1 = self.items[idx][1]
        kw, kh = x1 - x0, y1 - y0
        s = self.width_m / self.img_size[0]
        bh = min(kh, kw * 1.4) * 1.05  # bubble: about one key tall
        bw = bh * BUB_W / BUB_H        # ...in the picture's own shape, so the letter is never stretched
        want = ("tip", text, round(kh * 0.85)) if tip else (text, round(bw), round(bh))
        now = time.time()
        need = ("t", text) if tip else ("b", text)
        cell = self.atlas_cell(b, need)
        if cell is None:  # SteamVR is busy right now: try again in a moment
            return self.bubble_later(slot, idx, b)
        if self.bubble_tex.get(slot) != want:
            u0, v0, u1, v1 = cell
            bounds = self.vr.VRTextureBounds_t()
            bounds.uMin, bounds.vMin, bounds.uMax, bounds.vMax = u0, v0, u1, v1
            self.ov.setOverlayTextureBounds(b, bounds)
            if tip:
                th = kh * 0.85
                self.ov.setOverlayWidthInMeters(b, TIP_W * (th * s / 44))
            else:
                self.ov.setOverlayWidthInMeters(b, bw * s)
            self.bubble_tex[slot] = want
        self.bubble_wait.pop(slot, None)
        rise = (kh * 0.85 / 2 + kh * 0.18) if tip else (bh / 2 + kh * 0.04)
        p, R = self.local_point(k.get("panel", "main"), (x0 + x1) / 2, y0 - rise, 0.012)
        self.ov.setOverlayTransformAbsolute(b, self.vr.TrackingUniverseStanding, make_matrix(self.vr, p, R))
        if not self.bubble_shown.get(slot):
            self.ov.showOverlay(b)
            self.bubble_shown[slot] = True

    # All the letter bubbles and icon labels for the keys on screen live in one picture (an "atlas"), sent to
    # SteamVR once; pointing at a key just picks its part of that picture. So moving the laser around sends
    # SteamVR no new pictures at all (sending lots of pictures is what made SteamVR stop taking them).
    ATLAS_W, ATLAS_H = 1152, 936          # always this size
    BCOLS, BROWS, TCOLS, TROWS = 12, 6, 2, 6

    def atlas_texts(self, need):
        st, lang = self.st, LANG.get(self.st.get("lang"))
        layer = self.layer_map()
        bubbles, tips = [], []
        for k, _ in self.items:
            if k.get("tip"):
                tips.append(k["tip"])
            if k.get("emoji"):
                continue
            if "ch" in k:
                c = layer.get(k["ch"], k["ch"])
                bubbles += [c, LANG.shifted(c)]
            elif "sym" in k:
                bubbles += list(k["sym"])
            elif "ins" in k:
                bubbles.append(k["ins"])
        bubbles = [t for t in dict.fromkeys(bubbles) if t and t != " "]
        tips = list(dict.fromkeys(tips))
        if need[0] == "b":
            bubbles = [need[1]] + [t for t in bubbles if t != need[1]]
        else:
            tips = [need[1]] + [t for t in tips if t != need[1]]
        return bubbles[:self.BCOLS * self.BROWS], tips[:self.TCOLS * self.TROWS]

    def atlas_cell(self, b, need):
        """Where `need` is in this bubble overlay's picture (u0, v0, u1, v1), making the picture if needed."""
        at = self.atlas.get(b)
        if at is None or need not in at["cells"]:
            if time.time() < self.up_backoff:
                return None
            from PIL import Image
            bubbles, tips = self.atlas_texts(need)
            img = Image.new("RGBA", (self.ATLAS_W, self.ATLAS_H), (0, 0, 0, 0))
            cells = {}
            AW, AH = float(self.ATLAS_W), float(self.ATLAS_H)
            for i, t in enumerate(bubbles):
                x, y = (i % self.BCOLS) * BUB_W, (i // self.BCOLS) * BUB_H
                img.alpha_composite(self.renderer.bubble(t, BUB_W, BUB_H), (x, y))
                cells[("b", t)] = (x / AW, y / AH, (x + BUB_W) / AW, (y + BUB_H) / AH)
            ty0 = self.BROWS * BUB_H
            for i, t in enumerate(tips):
                x, y = (i % self.TCOLS) * TIP_W, ty0 + (i // self.TCOLS) * 44
                lab = self.renderer.tooltip(t, 44)
                lab = lab.crop((0, 0, min(lab.width, TIP_W), 44))
                img.alpha_composite(lab, (x + (TIP_W - lab.width) // 2, y))
                cells[("t", t)] = (x / AW, y / AH, (x + TIP_W) / AW, (y + 44) / AH)
            try:
                self.upload_raw(b, img)
            except Exception:
                return None
            at = self.atlas[b] = {"cells": cells}
            for sl, h in self.bubbles.items():  # this overlay's bounds must be set again
                if h == b:
                    self.bubble_tex[sl] = None
        return at["cells"].get(need)

    def bubble_later(self, slot, idx, b):
        """SteamVR is busy: hide the bubble for now and show it once things calm down."""
        if self.bubble_shown.get(slot):
            self.ov.hideOverlay(b)
            self.bubble_shown[slot] = False
        self.bubble_tex[slot] = None
        self.bubble_wait[slot] = idx
        self.bubble_sent[slot] = time.time()

    def _place_highlight(self, slot):
        hv = self.hover if slot == "mouse" else self.hovers.get(slot)
        idx = hv if isinstance(hv, int) and not isinstance(hv, bool) else None
        if idx is None or not self.visible or idx >= len(self.items):
            self.hide_highlight(slot)
            self.place_bubble(slot, None)
            return
        try:
            self._light_key(slot, idx)
        finally:
            self.place_bubble(slot, idx)   # (after: the key lights up at once, even if its bubble has to wait)

    def _light_key(self, slot, idx):
        x0, y0, x1, y1 = self.items[idx][1]
        pressed = (self.pressed == idx) if slot == "mouse" else (time.time() < self.hpressed.get(slot, 0))
        if not self.st.get("hover", True) and not pressed:  # Hover is off: nothing under the laser
            self.hide_highlight(slot)
            return
        h = self.hl_overlay(slot, (round(x1 - x0), round(y1 - y0)))
        if self.hl_shown.get(slot) not in (None, h):
            self.ov.hideOverlay(self.hl_shown[slot])
        tint = 0.55 if pressed else 1.0  # pressed = the same picture, darker (no new picture needed)
        color = tuple(c * tint for c in Gaze.COLOR) if slot == "gaze" else (tint, tint, tint)   # where you look: blue
        if self.hl_tint.get(h) != color:
            self.ov.setOverlayColor(h, *color)
            self.hl_tint[h] = color
        w = (x1 - x0) * self.width_m / self.img_size[0]
        if self.hl_width.get(h) is None or abs(self.hl_width[h] - w) > 1e-5:
            self.ov.setOverlayWidthInMeters(h, w)
            self.hl_width[h] = w
        cr = self.curve_r()
        cv = round(min(0.9, w / (2 * math.pi * cr)), 4) if cr else 0.0
        if self.hl_curve.get(h) != cv:  # a wide key (Space) bends with the keyboard, so it's lit end to end
            try:
                self.ov.setOverlayCurvature(h, cv)
            except Exception:
                pass
            self.hl_curve[h] = cv
        p, R = self.local_point(self.items[idx][0].get("panel", "main"), (x0 + x1) / 2, (y0 + y1) / 2, 0.003)
        self.ov.setOverlayTransformAbsolute(h, self.vr.TrackingUniverseStanding, make_matrix(self.vr, p, R))
        if self.hl_shown.get(slot) != h:
            self.ov.showOverlay(h)
            self.hl_shown[slot] = h

    # ---- laser beams for the hand SteamVR isn't drawing a laser for
    def beam_for(self, slot):
        if slot not in self.beams:
            b = self.ov.createOverlay("betterframe.keyboard.beam." + slot, "BetterFrame Keyboard laser " + slot)
            self.set_sort(b, 12)
            self.beams[slot] = b
        return self.beams[slot]

    def show_beam(self, slot, o, hit):
        from PIL import Image
        b = self.beam_for(slot)
        d = [hit[k] - o[k] for k in range(3)]
        L = math.sqrt(sum(c * c for c in d))
        if L > 0.01:  # stop just in front of the keys, so it doesn't poke through the highlight
            d = [c * (L - 0.004) / L for c in d]
            L -= 0.004
        if L < 0.02:
            self.ov.hideOverlay(b)
            return
        x = [c / L for c in d]
        w = max(16, min(1024, int(L / 0.0022)))
        if self.beam_w.get(slot) != w:  # 2 px tall, so the beam stays about 4 mm thick
            img = Image.new("RGBA", (w, 2))
            px = img.load()
            for i in range(w):
                a = int(30 + 190 * min(1.0, i / (w * 0.6)))
                px[i, 0] = px[i, 1] = (150, 215, 255, a)
            self.upload_raw(b, img)
            self.beam_w[slot] = w
        self.ov.setOverlayWidthInMeters(b, L)
        (hx, hy, hz), _ = self.head()
        mid = [o[k] + d[k] / 2 for k in range(3)]
        tz = [(hx, hy, hz)[k] - mid[k] for k in range(3)]
        dp = sum(tz[k] * x[k] for k in range(3))
        z = [tz[k] - dp * x[k] for k in range(3)]
        zn = math.sqrt(sum(c * c for c in z)) or 1.0
        z = [c / zn for c in z]
        y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
        R = [[x[i], y[i], z[i]] for i in range(3)]
        self.ov.setOverlayTransformAbsolute(b, self.vr.TrackingUniverseStanding, make_matrix(self.vr, mid, R))
        self.ov.showOverlay(b)

    def hide_beam(self, slot):
        if slot in self.beams:
            self.ov.hideOverlay(self.beams[slot])
        if slot in self.cursors:
            self.ov.hideOverlay(self.cursors[slot])

    def show_cursor(self, slot, p):
        """Small dot where the laser meets the keyboard, like SteamVR's own."""
        if slot not in self.cursors:
            from PIL import Image, ImageDraw
            c = self.ov.createOverlay("betterframe.keyboard.cursor." + slot, "BetterFrame Keyboard dot " + slot)
            self.set_sort(c, 13)
            img = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((4, 4, 44, 44), fill=(150, 215, 255, 90))
            d.ellipse((14, 14, 34, 34), fill=(255, 255, 255, 240))
            self.upload_raw(c, img)
            self.ov.setOverlayWidthInMeters(c, 0.014)
            self.cursors[slot] = c
        R = self.R()
        q = [p[i] + R[i][2] * 0.005 for i in range(3)]
        self.ov.setOverlayTransformAbsolute(self.cursors[slot], self.vr.TrackingUniverseStanding, make_matrix(self.vr, q, R))
        self.ov.showOverlay(self.cursors[slot])

    def ray_to_px(self, o, d):
        """Where a ray hits the keyboard, in image pixels (None if it misses or comes from behind)."""
        R = self.R()
        n = [R[k][2] for k in range(3)]
        if sum(d[k] * n[k] for k in range(3)) >= 0:
            return None
        p = ray_plane(o, d, self.pos, n)
        if not p:
            return None
        rel = [p[k] - self.pos[k] for k in range(3)]
        lx = sum(rel[k] * R[k][0] for k in range(3))
        ly = sum(rel[k] * R[k][1] for k in range(3))
        s = self.width_m / self.img_size[0]
        x, y = lx / s + self.img_size[0] / 2, self.img_size[1] / 2 - ly / s
        if -60 <= x <= self.img_size[0] + 60 and -60 <= y <= self.img_size[1] + 60:
            return x, y, p
        return None

    def px_to_world(self, x, y):
        return self.local_point("main", x, y)[0]

    def aim(self, h):
        """This hand's ray, corrected to match SteamVR's laser angle once we've seen it."""
        c = self.calib.get(h.name)
        mirror = False
        if c is None:
            other = "right" if h.name == "left" else "left"
            c, mirror = self.calib.get(other), True
        if c is None or h.rot is None:
            return h.origin, h.dir
        lx = -c[0] if mirror else c[0]
        r = h.rot
        d = [r[i][0] * lx + r[i][1] * c[1] + r[i][2] * c[2] for i in range(3)]
        return h.origin, tuple(d)

    def learn_aim(self, h, x, y):
        if h.rot is None:
            return
        P = self.px_to_world(x, y)
        v = [P[k] - h.origin[k] for k in range(3)]
        n = math.sqrt(sum(a * a for a in v))
        if n < 0.05:
            return
        r = h.rot
        loc = [sum(r[i][j] * v[i] for i in range(3)) / n for j in range(3)]  # into the controller's frame
        old = self.calib.get(h.name)
        if old:
            loc = [old[j] * 0.85 + loc[j] * 0.15 for j in range(3)]
        m = math.sqrt(sum(a * a for a in loc)) or 1.0
        self.calib[h.name] = [a / m for a in loc]

    def steam_hand(self, hands):
        """Which hand SteamVR is drawing its laser on (while it's on the keyboard)."""
        if not self.steam_on or time.time() - self.steam_dev_t > 10 or not self.steam_px:
            return None
        for h in hands:
            if h.dev is not None and h.dev == self.steam_dev:
                return h
        # not told which device: pick the hand pointing most directly at SteamVR's dot
        P = self.px_to_world(*self.steam_px)
        best, ba = None, math.radians(40)
        for h in hands:
            o, d = self.aim(h)
            v = [P[k] - o[k] for k in range(3)]
            n = math.sqrt(sum(a * a for a in v)) or 1.0
            ang = math.acos(max(-1.0, min(1.0, sum(v[k] * d[k] for k in range(3)) / n)))
            if ang < ba:
                best, ba = h, ang
        return best

    def two_hands_on(self):
        return bool(self.hands and self.hands.working)

    def update_hands(self):
        """Hover, press, hold-to-repeat and drag for each hand, every frame."""
        hands = self.hands.update(self.poses())
        if not self.hands.working:
            return
        now = time.time()
        sh = self.steam_hand(hands)
        if sh and self.steam_px:
            self.learn_aim(sh, *self.steam_px)
        self.hand_rays = {h.name: self.aim(h) for h in hands}
        for h in self.hands.hands:
            slot = h.name
            if not h.ok or not self.visible:
                if self.hovers.get(slot) is not None:
                    self.hovers[slot] = None
                    self.place_highlight(slot)
                self.hide_beam(slot)
                continue
            if self.drag and self.drag.get("slot") == slot:
                if h.released:
                    self.end_drag()
                self.hide_beam(slot)
                continue
            o, d = self.hand_rays[slot]
            if h is sh:  # SteamVR draws this laser and its dot: follow it exactly, draw nothing extra
                item = self.item_at(*self.steam_px)
                self.hide_beam(slot)
            else:
                hit = self.ray_to_px(o, d)
                item = self.item_at(hit[0], hit[1]) if hit else None
                if hit and -10 <= hit[0] <= self.img_size[0] + 10 and -10 <= hit[1] <= self.img_size[1] + 10:
                    self.show_beam(slot, o, hit[2])
                    self.show_cursor(slot, hit[2])
                else:
                    self.hide_beam(slot)
            if item != self.hovers.get(slot):
                self.hovers[slot] = item
                self.place_highlight(slot)
            if h.pressed and item is not None:
                if item in ("grab", "resize", "rotate"):
                    self.start_drag({"grab": "move"}.get(item, item), ray=(o, d), slot=slot)
                else:
                    self.hpressed[slot] = now + 0.09
                    self.place_highlight(slot)
                    self.hands.buzz(h)
                    self.press(self.items[item][0])
                    k = self.items[item][0] if isinstance(item, int) and item < len(self.items) else {}
                    if k.get("act") in ("back", "del", "left", "right", "up", "down"):
                        self.repeat = {"slot": slot, "item": item, "next": now + 0.45}
            elif h.released and self.repeat and self.repeat["slot"] == slot:
                self.repeat = None
            if self.hpressed.get(slot) and now > self.hpressed[slot]:
                self.hpressed[slot] = 0
                self.place_highlight(slot)
        r = self.repeat
        if r and now >= r["next"]:
            hv = self.hovers.get(r["slot"])
            if hv == r["item"] and r["item"] < len(self.items):
                self.press(self.items[r["item"]][0])
                r["next"] = now + 0.055
            else:
                self.repeat = None

    # ---- hit testing
    def item_at(self, x, y, panel="main"):
        if panel == "wing":
            for i, (k, (x0, y0, x1, y1)) in enumerate(self.items):
                if k.get("panel") == "wing" and x0 - 4 <= x <= x1 + 4 and y0 - 4 <= y <= y1 + 4:
                    return i
            return None
        gx0, gy0, gx1, gy1 = self.grab
        if gx0 - 40 <= x <= gx1 + 40 and gy0 - 28 <= y <= gy1 + 28:
            return "grab"
        rx0, ry0, rx1, ry1 = self.resize
        if rx0 - 30 <= x <= rx1 + 20 and ry0 - 30 <= y <= ry1 + 20:
            return "resize"
        tb = getattr(self.renderer, "metrics", {}).get("rotate")
        if tb and tb[0] - 20 <= x <= tb[2] + 30 and tb[1] - 30 <= y <= tb[3] + 20:
            return "rotate"
        for i, (k, (x0, y0, x1, y1)) in enumerate(self.items):
            if k.get("panel") != "wing" and x0 - 4 <= x <= x1 + 4 and y0 - 4 <= y <= y1 + 4:
                return i
        return None

    # ---- moving and resizing with the laser
    def controller_rays(self):
        vr = self.vr
        out = []
        ps = self.poses()
        for i in range(1, vr.k_unMaxTrackedDeviceCount):
            if self.system.getTrackedDeviceClass(i) != vr.TrackedDeviceClass_Controller or not ps[i].bPoseIsValid:
                continue
            (px, py, pz), r = mat_to_pos_rot(ps[i].mDeviceToAbsoluteTracking.m)
            out.append((i, (px, py, pz), (-r[0][2], -r[1][2], -r[2][2])))
        return out

    def device_pose(self, dev):
        p = self.poses()[dev] if dev is not None and 0 <= dev < self.vr.k_unMaxTrackedDeviceCount else None   # (0: the headset)
        return mat_to_pos_rot(p.mDeviceToAbsoluteTracking.m) if p is not None and p.bPoseIsValid else None

    def start_drag_px(self, mode, x, y, dev, slot):
        """Grab exactly where SteamVR's laser touched the keyboard (x, y in pixels).
        The laser's angle is worked out from that point, so it never misses."""
        P = self.px_to_world(x, y)
        rays = self.controller_rays()
        ctrls = [i for i, _, _ in rays]
        # the headset's own pointer (its button, looking at the keyboard): the headset is what moves it then. It
        # wasn't counted at all, so with the headset button the bar, resize and tilt handles did nothing
        head = self.device_pose(0)
        if head:
            (hx, hy, hz), hr = head
            rays = rays + [(0, (hx, hy, hz), (-hr[0][2], -hr[1][2], -hr[2][2]))]
        if dev not in ctrls and dev != 0:  # SteamVR didn't say which: take the one pointing most directly at the spot
            best, ba = None, 9.0
            for i, o, dvec in rays:
                v = [P[k] - o[k] for k in range(3)]
                n = math.sqrt(sum(a * a for a in v)) or 1.0
                ang = math.acos(max(-1.0, min(1.0, sum(v[k] * dvec[k] for k in range(3)) / n)))
                if ang < ba:
                    best, ba = i, ang
            dev = best
        pose = self.device_pose(dev)
        if not pose:
            return False
        o, r = pose
        v = [P[k] - o[k] for k in range(3)]
        dist = math.sqrt(sum(a * a for a in v)) or 1e-3
        dloc = [sum(r[i][j] * v[i] for i in range(3)) / dist for j in range(3)]  # laser direction in the controller's frame
        self.drag = {"mode": mode, "dev": dev, "slot": slot, "dloc": dloc, "dist": dist, "gl": self.px_to_local(x, y), "sm": None,
                     "off": [self.pos[k] - P[k] for k in range(3)], "scale0": self.conf.get("scale", 1.0), "w0": self.width_m}
        if mode == "resize":
            R = self.R()
            rel = [P[k] - self.pos[k] for k in range(3)]
            self.drag["x0"] = max(0.05, abs(sum(rel[k] * R[k][0] for k in range(3))))
        if mode == "rotate":
            self.drag["v0"], self.drag["turn0"] = [P[k] - self.pos[k] for k in range(3)], float(self.conf.get("roll", 0.0))
        self.hovers[slot] = None
        self.place_highlight(slot)
        return True

    def start_drag(self, mode, ray=None, slot=None):
        vr = self.vr
        best = None
        if ray:
            hit = self.ray_to_px(*ray)
            if hit:
                p = hit[2]
                best = (None, math.sqrt(sum((p[k] - ray[0][k]) ** 2 for k in range(3))), p)
        for i, o, dvec in ([] if ray else self.controller_rays()):
            params = vr.VROverlayIntersectionParams_t()
            params.vSource = vr.HmdVector3_t(*o)
            params.vDirection = vr.HmdVector3_t(*dvec)
            params.eOrigin = vr.TrackingUniverseStanding
            ok, res = self.ov.computeOverlayIntersection(self.handle, params)
            if ok and (best is None or res.fDistance < best[1]):
                best = (i, res.fDistance, [res.vPoint.v[0], res.vPoint.v[1], res.vPoint.v[2]])
        if not best:
            return
        i, dist, hit = best
        self.drag = {"mode": mode, "dev": i, "slot": slot, "dist": dist, "off": [self.pos[k] - hit[k] for k in range(3)],
                     "scale0": self.conf.get("scale", 1.0), "w0": self.width_m, "t": 0}
        if mode == "resize":
            R = self.R()
            rel = [hit[k] - self.pos[k] for k in range(3)]
            self.drag["x0"] = max(0.05, abs(sum(rel[k] * R[k][0] for k in range(3))))
        if mode == "rotate":
            self.drag["v0"], self.drag["turn0"] = [hit[k] - self.pos[k] for k in range(3)], float(self.conf.get("roll", 0.0))
        if slot:
            self.hovers[slot] = None
            self.place_highlight(slot)
        else:
            self.hover = None
            self.place_highlight("mouse")

    def update_drag(self):
        if not self.drag:
            return
        if "dloc" in self.drag:
            ps = self.poses(0.012)  # a touch of prediction, so it doesn't lag behind your hand
            p = ps[self.drag["dev"]]
            if not p.bPoseIsValid:
                return
            o, r = mat_to_pos_rot(p.mDeviceToAbsoluteTracking.m)
            dl = self.drag["dloc"]
            d = [r[i][0] * dl[0] + r[i][1] * dl[1] + r[i][2] * dl[2] for i in range(3)]
            if self.drag["mode"] == "rotate":
                self.turn_to(o, d)
                return
            if self.drag["mode"] == "move":
                self.stick_push()
                hit = [o[k] + d[k] * self.drag["dist"] for k in range(3)]
                sm = self.drag["sm"]
                if sm is not None and math.dist(sm, hit) > 0.5:
                    # half a metre in one frame: the controller lost tracking for a moment, not your hand. Skipped,
                    # unless it stays there (then it's real: a stutter while you moved fast)
                    j = self.drag.setdefault("jump_t", time.time())
                    if time.time() - j < 0.25:
                        return
                self.drag.pop("jump_t", None)
                if sm is not None:  # steady out hand shake without adding noticeable lag
                    jump = math.dist(sm, hit)
                    a = 0.55 if jump < 0.01 else 0.9
                    hit = [sm[k] + (hit[k] - sm[k]) * a for k in range(3)]
                self.drag["sm"] = hit
                h0 = ps[0]
                head = mat_to_pos_rot(h0.mDeviceToAbsoluteTracking.m)[0] if h0.bPoseIsValid else self.head()[0]
                # the spot you grabbed stays exactly under your laser while the keyboard turns to face you
                gx, gy = self.drag["gl"]
                for _ in range(2):
                    self.yaw, self.pitch = self.face(self.pos, head)
                    R = self.R()
                    self.pos = [hit[k] - R[k][0] * gx - R[k][1] * gy for k in range(3)]
                self.apply_transform()
                return
            rays = [(None, o, d)]
        elif self.drag.get("slot"):
            ray = getattr(self, "hand_rays", {}).get(self.drag["slot"])
            rays = [(None, ray[0], ray[1])] if ray else []
        else:
            rays = [r for r in self.controller_rays() if r[0] == self.drag["dev"]]
        for i, o, dvec in rays:
            if self.drag["mode"] == "rotate":
                self.turn_to(o, dvec)
                return
            if self.drag["mode"] == "move":
                if i is not None:
                    self.stick_push()
                hit = [o[k] + dvec[k] * self.drag["dist"] for k in range(3)]
                self.pos = [hit[k] + self.drag["off"][k] for k in range(3)]
                (hx, hy, hz), _ = self.head()
                self.yaw, self.pitch = self.face(self.pos, (hx, hy, hz))
                self.apply_transform()
            else:  # resize: keep the centre, follow the corner
                R = self.R()
                p = ray_plane(o, dvec, self.pos, [R[k][2] for k in range(3)])
                if p:
                    x = abs(sum((p[k] - self.pos[k]) * R[k][0] for k in range(3)))
                    scale = max(0.3, min(1.8, self.drag["scale0"] * x / self.drag["x0"]))   # (half to three times the starting size)
                    if abs(scale - self.conf.get("scale", 1.0)) > 0.01:
                        self.conf["scale"] = scale
                        self.width_m = self.drag["w0"] * scale / self.drag["scale0"]
                        self.set_kb_width(self.width_m)
            return

    def stick_push(self):
        """While holding the move bar: the stick on that controller pushes the keyboard away (forward) or pulls it
        closer (back), along your laser. Only read while you're moving the keyboard, so it costs nothing otherwise."""
        dr, now = self.drag, time.time()
        dt = min(0.05, now - dr.get("st", now))
        dr["st"] = now
        dev = dr.get("dev")
        if dev is None or not dt:
            return
        vr = self.vr
        try:
            if not hasattr(self, "stick_axes"):
                self.stick_axes = {}
            axes = self.stick_axes.get(dev)
            if axes is None:
                # the axes SteamVR says are a stick or pad; if it doesn't say, the usual stick slots (never the
                # trigger and grip, 1 and 2)
                axes = []
                for n in range(5):
                    try:
                        t = self.system.getInt32TrackedDeviceProperty(dev, vr.Prop_Axis0Type_Int32 + n)
                    except Exception:
                        continue
                    if isinstance(t, tuple):
                        t = t[0]
                    if t in (vr.k_eControllerAxis_Joystick, vr.k_eControllerAxis_TrackPad):
                        axes.append(n)
                axes = axes or [0, 3, 4]
                self.stick_axes[dev] = axes
            ok, s = self.system.getControllerState(dev)
            y = max((float(s.rAxis[n].y) for n in axes), key=abs) if ok else 0.0
        except Exception:
            y = 0.0
        # the Frame's controllers give the older way no stick at all: SteamVR's scrolling over the keyboard (what makes
        # windows scroll with the stick) carries it instead. Whichever says more counts
        sy = self.scroll_stick()
        if abs(sy) > abs(y):
            y = sy
        if abs(y) < 0.25:  # a dead zone, so resting your thumb on the stick does nothing
            return
        y = (abs(y) - 0.25) / 0.75 * (1 if y > 0 else -1)
        if "d_lo" not in dr:  # (never jumps: a keyboard grabbed nearer or further than usual keeps its spot)
            dr["d_lo"], dr["d_hi"] = min(0.25, dr["dist"]), max(2.5, dr["dist"])
        # forward pushes it away, back pulls it closer, along your laser; faster the further away it is
        dr["dist"] = max(dr["d_lo"], min(dr["d_hi"], dr["dist"] * (1.0 + y * 1.6 * dt)))

    SCROLL_GAIN = 4.0   # SteamVR's smooth scroll steps -> stick (-1..1)

    def on_scroll(self, e):
        """The stick moved while a laser is on the keyboard (SteamVR sends it as scrolling, like over a window)."""
        try:
            y = float(e.data.scroll.ydelta)
        except Exception:
            return
        if e.eventType == 305:          # (a notch at a time, like a mouse wheel)
            y *= 0.25
        self.scroll_v, self.scroll_t = y, time.time()
        if self.drag and not getattr(self, "scroll_said", False):
            self.scroll_said = True
            LOG("stick (as scrolling) while moving the keyboard: %.3f" % y)

    def scroll_stick(self):
        """The stick's up/down from SteamVR's scrolling (-1..1), 0 once it stops coming."""
        if time.time() - getattr(self, "scroll_t", 0) > 0.12:
            return 0.0
        return max(-1.0, min(1.0, getattr(self, "scroll_v", 0.0) * self.SCROLL_GAIN))

    def turn_to(self, o, d):
        """Tilt handle: the keyboard tilts around its middle like a steering wheel (still facing you), so the corner
        you hold follows your laser. Close to level, it snaps level."""
        R0 = rot(self.yaw, self.pitch)  # (the keyboard without tilt: its right, up and facing directions)
        n = [R0[k][2] for k in range(3)]
        L = ray_plane(o, d, self.pos, n) or [o[k] + d[k] * self.drag["dist"] for k in range(3)]
        v0, v = self.drag["v0"], [L[k] - self.pos[k] for k in range(3)]

        def ang(w):
            return math.atan2(sum(w[k] * R0[k][1] for k in range(3)), sum(w[k] * R0[k][0] for k in range(3)))
        if math.hypot(sum(v[k] * R0[k][0] for k in range(3)), sum(v[k] * R0[k][1] for k in range(3))) < 0.03:
            return  # (too near the middle to tell which way)
        dlt = (ang(v) - ang(v0) + math.pi) % (2 * math.pi) - math.pi
        a = max(-1.4, min(1.4, self.drag["turn0"] + dlt))
        self.conf["roll"] = 0.0 if abs(a) < math.radians(3) else a
        self.apply_transform()

    def end_drag(self):
        if self.drag and self.drag["mode"] in ("resize", "rotate"):
            save_conf(self.conf)
        elif self.drag and self.drag["mode"] == "move":
            self.drag = None
            self.remember_spot()
        self.drag = None

    def remember_spot(self):
        """Where you put it (distance, height and direction from your head) is where it opens next time. Moved while
        Steam's menu is open: where it is next to the menu instead, for whenever it opens with the menu."""
        try:
            (hx, hy, hz), r = self.head()
            L = self.letters_world()  # where the letters are (that's what you placed)
            spot = self.dashboard_spot()
            if spot is not None and math.hypot(spot[0] - hx, spot[2] - hz) > 0.2:
                mx, mz = spot[0] - hx, spot[2] - hz
                n = math.hypot(mx, mz)
                mx, mz = mx / n, mz / n
                dx, dz = L[0] - hx, L[2] - hz
                d = math.hypot(dx, dz)
                if not 0.25 <= d <= 2.0 or L[1] < FLOOR_MIN + 0.1:
                    return
                side = math.degrees(math.atan2(mz * dx - mx * dz, mx * dx + mz * dz))
                up = math.degrees(math.atan2(L[1] - hy, d) - math.atan2(spot[1] - hy, n))
                if abs(side) > 70:
                    return   # (way off to one side of the menu: not a spot to come back to)
                self.conf["dash_off"] = [round(side, 1), round(up, 1), round(d, 3)]
                save_conf(self.conf)
                return
            dx, dz = L[0] - hx, L[2] - hz
            d = math.hypot(self.pos[0] - hx, self.pos[2] - hz)
            fx, fz = -r[0][2], -r[2][2]
            if d < 0.25 or d > 2.0 or math.hypot(fx, fz) < 0.3:
                return
            side = math.degrees(math.atan2(fz * dx - fx * dz, fx * dx + fz * dz))
            drop = hy - self.pos[1]
            if not -0.3 < drop < 0.95:  # (a spot near the floor is never remembered)
                return
            self.conf.update(distance=round(d, 3), drop=round(drop, 3), side=round(max(-60.0, min(60.0, side)), 1))
            save_conf(self.conf)
        except Exception as ex:
            LOG("couldn't remember the spot:", ex)

    def keep_in_reach(self):
        """A safety net: the keyboard must never end up in the floor, high overhead or far away. On the Frame the
        room's tracking can quietly realign itself (after you move around) without SteamVR saying so: the keyboard
        then keeps its old spot in the room's numbers, which can now be under the floor. Checked 10 times a second
        (a few sums, no cost): if it's been clearly out of reach for a third of a second, it comes back in front."""
        busy = any(time.time() - v.get("t", 0) < 3 for v in self.swipes.values())  # (a swipe stuck open doesn't count)
        if not self.visible or self.drag or busy:
            self.out_since = None
            return
        try:
            p = self.poses()[0]
            if not p.bPoseIsValid or int(p.eTrackingResult) != int(self.vr.TrackingResult_Running_OK):
                self.out_since = None   # (tracking hiccup, like when the headset is struggling: not a real reading)
                return
            (hx, hy, hz), _ = mat_to_pos_rot(p.mDeviceToAbsoluteTracking.m)
            if hy < 0.25:  # (a head at the floor is a bad reading, not you)
                return
            x, y, z = self.pos
            ok = all(math.isfinite(v) for v in (x, y, z))
            below, away = hy - y, math.hypot(x - hx, z - hz)
            # under the floor (the room's floor is height 0), far below your eyes (also when you're sitting), high
            # overhead, or far away
            out = (not ok) or y < FLOOR_MIN or below > 1.05 or below < -0.9 or away > 2.8
        except Exception:
            return
        now = time.time()
        if not out:
            self.out_since = None
            return
        if getattr(self, "out_since", None) is None:
            self.out_since, self.out_n = now, 1
            return
        self.out_n = getattr(self, "out_n", 0) + 1
        # out of reach for a while, over several readings (a headset that froze for a moment gives two readings a second
        # apart: that alone used to throw the keyboard back in front of you)
        if now - self.out_since < 0.6 or self.out_n < 5:
            return
        self.out_since = None
        LOG("keyboard was out of reach (%.2f m below your eyes, %.2f m away): brought back in front of you"
            % (below if ok else float("nan"), away if ok else float("nan")))
        self.recenter()

    # ---- key actions
    def press(self, k, quiet=False):
        if k.get("semo") and isinstance(getattr(self.vk, "stream", None), StreamText) and \
                not (getattr(self, "steam_field", False) and not getattr(self, "was_streaming", False)):
            # (in Steam's own chat they go through fine, whichever way the text gets there)
            # a Steam emoticon, typing into a game streamed from a PC: Steam can't send those (they came out as a string
            # of colons and letters). They only mean something in Steam's own chat anyway
            self.flash("Emoticons can't be sent to a streamed game" if getattr(self, "was_streaming", False)
                        else "Emoticons can't be typed here right now")
            return
        return self._press(k, quiet)

    def _press(self, k, quiet=False):
        self.prev_act, self.cur_act = getattr(self, "cur_act", None), k.get("act")
        self.last_press = time.time()
        self.last_key = k.get("act") or k.get("ch") or k.get("ins") or k.get("label")
        if self.st["sounds"] and not quiet:
            self.sounds.play("big" if k.get("act") in ("space", "enter") else "key")
        st, vk = self.st, self.vk
        up = st["shift"] != st["caps"]
        mods = tuple(c for c, on in ((KEY["LEFTCTRL"], self.ctrl), (KEY["LEFTALT"], self.alt), (KEY["LEFTMETA"], self.meta)) if on)
        # Shift (not Caps Lock) goes along as a real Shift key with Ctrl, Alt or Super (Ctrl + Shift + W), and with the
        # keys that aren't letters (Shift + arrows to select, Shift + Tab, Shift + Enter)
        shift_mod = (KEY["LEFTSHIFT"],) if st["shift"] else ()

        def out_char(c):
            if not vk:
                self.flash("Typing needs /dev/uinput access. Run install-overlay.sh.")
            elif mods and c.lower() in KEY:
                vk.tap(KEY[c.lower()], mods + shift_mod)
            else:
                self.type_text(c)

        redraw = False
        lang = LANG.get(st.get("lang"))
        if st.get("esearch") and self.esearch_press(k):
            return
        comp = self.composer()
        if comp is not None and self.ime_press(k, comp, mods):
            return
        if not str(k.get("act", "")).startswith("sugg:"):
            self.note_word(k)
            if self.auto_space:
                self.auto_space = False
                c = self.char_for(k) if ("ch" in k or "sym" in k or "ins" in k) else None
                if c and c in ".,!?;:" and vk:  # "word." not "word ."
                    vk.tap(KEY["BACKSPACE"])
                    self.type_text(c + " ")
                    return
        if "np" in k and not st.get("numlock", True):  # numpad with Num Lock off: 7 Home, 8 up, 9 PgUp, ...
            if vk and k["np"]:
                vk.tap(KEY[k["np"]], mods)
            return
        if st.get("fn") and k.get("act") in FN:  # Fn + key: Home / End / PgUp / PgDn / volume / media / Insert
            if vk:
                vk.tap(KEY[FN[k["act"]][1]], mods + shift_mod)
            self.mods_used()
            return
        if st.get("fn") and st.get("layout") == "minimal" and k.get("ch") in tuple("1234567890"):
            # Fn + a number on Minimal (no F keys there): F1 to F10
            if vk:
                vk.tap(KEY["F%d" % (int(k["ch"]) or 10)], mods + shift_mod)
            self.mods_used()
            return
        if "ch" in k or "sym" in k or "ins" in k:
            c = self.char_for(k)
            if "ch" in k and st.get("alt", -1) >= 0:  # an accent was picked: back to plain letters
                st["alt"] = -1
                redraw = True
            if lang["romaji"] and not mods:
                if "ch" in k and c.isascii() and c.isalpha() and c.islower():
                    self.type_text(c)
                    res = self.romaji.feed(c)
                    if res:
                        self.replace_typed(*res)
                else:
                    res = self.romaji.flush()
                    if res:
                        self.replace_typed(*res)
                    self.type_text(LANG.JA_PUNCT.get(c, c))
            else:
                out_char(c)
            self.last_char = c if c and len(c) == 1 else ""
            # (a word or sentence just ended right here, with no space yet: a swiped word next gets one first)
            self.after_letter = bool(c) and len(c) == 1 and (c.isalnum() or c in ".,!?;:)")
            if k.get("emoji") and c:  # remember it for the Recent tab (Steam emoticons too, as :name:)
                rec = [e for e in self.conf.get("emoji_recent", []) if self.emo_key(e) != self.emo_key(c)]
                self.conf["emoji_recent"] = ([c] + rec)[:30]
                save_conf(self.conf)
        else:
            a = k.get("act")
            redraw = True
            named = {"back": "BACKSPACE", "enter": "ENTER", "space": "SPACE", "tab": "TAB", "esc": "ESC", "del": "DELETE",
                     "left": "LEFT", "right": "RIGHT", "up": "UP", "down": "DOWN", "ins": "INSERT", "home": "HOME", "end": "END",
                     "pgup": "PAGEUP", "pgdn": "PAGEDOWN", "prtsc": "SYSRQ", "scrlk": "SCROLLLOCK", "pause": "PAUSE"}
            if lang["romaji"]:
                if a == "back":
                    self.romaji.back()
                elif a in ("space", "enter", "tab"):
                    res = self.romaji.flush()
                    if res:
                        self.replace_typed(*res)
                else:
                    self.romaji.reset()
            if a in named or (a and a.startswith("f") and a[1:].isdigit()):
                redraw = False
                self.after_letter = False
                if vk:
                    vk.tap(KEY[named.get(a, a.upper())], mods + (shift_mod if a != "space" else ()))
                    if shift_mod and a != "space" and "shift" not in self.locks:
                        st["shift"] = False   # (Shift is for one key, like after a letter)
                        redraw = True
                else:
                    self.flash("Typing needs /dev/uinput access. Run install-overlay.sh.")
                # (Enter used to close the keyboard when a game or text box had asked for it. The Frame's desktop
                # and streamed PCs ask the same way, so in Konsole, chats and documents every Enter closed it.
                # Enter now just types Enter; the keyboard closes with its X, B, or the keyboard button)
            elif a == "shift":  # tap twice quickly for caps lock
                now = time.time()
                self.shift_typed = False
                if st["caps"]:
                    st["caps"], st["shift"] = False, False
                elif now - self.last_shift < 0.35 and st["shift"] and self.prev_act == "shift":
                    # a quick second tap right after the first (nothing typed in between): Caps Lock
                    st["caps"], st["shift"] = True, False
                else:
                    st["shift"] = not st["shift"]
                self.last_shift = now
                LOG("Shift:", "Caps Lock" if st["caps"] else "on" if st["shift"] else "off")
            elif a == "caps":
                st["caps"] = not st["caps"]
                st["shift"] = False
            elif a == "ctrl":
                self.ctrl = self.lock_tap("ctrl", self.ctrl)
                st["ctrl"] = self.ctrl
            elif a == "swipe":  # swipe typing on/off
                st["swipe"] = not st.get("swipe", False)
                self.conf["swipe"] = st["swipe"]
                save_conf(self.conf)
                if st["swipe"] and not self.swipe_lang():
                    self.flash("Swipe typing isn't available for %s yet" % lang["name"])
            elif a and a.startswith("sugg:"):
                self.pick_suggestion(int(a[5:]))
                return
            elif a == "settings":  # BetterFrame Settings: its own program, in its own window
                self.open_settings()
                redraw = False
            elif a == "eyes":  # typing with your eyes on/off (look at a key, pinch)
                self.toggle_eyes()
            elif a == "words":  # word bar on/off
                st["words"] = not st.get("words", False)
                self.conf["words"] = st["words"]
                save_conf(self.conf)
                self.word_list, self.cur_word = [], ""
                if st["words"] and not self.swipe_lang():
                    self.flash("Word suggestions aren't available for %s yet" % lang["name"])
            elif a == "bubble":  # letter bubble above the key you point at, on/off
                st["bubble"] = not st.get("bubble", True)
                self.conf["bubble"] = st["bubble"]
                save_conf(self.conf)
                self.place_highlight()
            elif a in ("dakuten", "small", "flickmod"):  # change the kana just typed: か → が, つ → っ
                last = getattr(self, "last_char", "")
                fn = {"dakuten": LANG.dakuten, "small": LANG.small, "flickmod": LANG.flick_mod}[a]
                new = fn(last) if last else None
                if new:
                    self.replace_typed(1, new)
                    self.last_char = new
                redraw = False
            elif a == "fn":
                st["fn"] = self.lock_tap("fn", st.get("fn"))
            elif a == "start":  # like the Windows key: opens the app launcher (KDE's start menu)
                redraw = False
                if vk:
                    vk.tap(KEY["LEFTMETA"])
            elif a == "super":
                self.meta = self.lock_tap("super", self.meta)
                st["meta"] = self.meta
            elif a == "numlock":
                st["numlock"] = not st.get("numlock", True)
            elif a == "alt-mod":
                self.alt = self.lock_tap("alt-mod", self.alt)
                st["altm"] = self.alt
            elif a == "alt":  # accent key: next set of accented letters, then back to plain
                n = len(lang["layers"])
                st["alt"] = st.get("alt", -1) + 1 if st.get("alt", -1) + 1 < n else -1
            elif a == "fmts":  # key layout list
                if LANG.can_reformat(lang):
                    st["page"] = "abc" if st["page"] == "fmt" else "fmt"
                else:
                    self.flash("%s keeps its own layout" % lang["name"])
                st["alt"] = -1
            elif a and a.startswith("fmt:"):
                st["fmt"], st["page"], st["alt"] = a[4:], "abc", -1
                self.conf["fmt"] = st["fmt"]
                save_conf(self.conf)
            elif a == "langs":  # globe: open or close the language list (on the page with the language you use)
                st["page"] = "abc" if st["page"] == "lang" else "lang"
                st["alt"], st["lgroup"] = -1, None
                keys = [g[0] for g in LANG.groups()]
                cur = (st.get("lang") or "en").split("-")[0]
                st["lpage"] = (keys.index(cur) if cur in keys else 0) // (LANG_COLS * LANG_ROWS)
            elif a and a.startswith("lpage:"):
                st["lpage"] = max(0, st.get("lpage", 0) + int(a[6:]))
            elif a and a.startswith("lgroup:"):
                st["lgroup"] = a[7:]
            elif a == "lback":
                st["lgroup"] = None
            elif a and a.startswith("lang:"):
                st["lang"], st["page"], st["alt"] = a[5:], "abc", -1
                self.renderer.set_cjk(st["lang"])
                self.conf["lang"] = st["lang"]
                save_conf(self.conf)
                self.romaji.reset()
            elif a == "p123":
                st["page"] = "123"
            elif a == "psym":
                st["page"] = "sym"
            elif a == "abc":
                st["page"] = "abc"
            elif a in ("undo", "cut", "copy", "paste", "selall"):
                redraw = False
                if vk:
                    # Ctrl+C / Ctrl+V mean "stop" / a literal ^V in a terminal like Konsole, so Copy, Cut and Paste use
                    # the Insert/Delete versions, which terminals, KDE apps, GTK apps and browsers all understand
                    if self.conf.get("edit_keys", "universal") == "universal" and a in ("copy", "cut", "paste"):
                        vk.combo(*{"copy": ("LEFTCTRL", "INSERT"), "cut": ("LEFTSHIFT", "DELETE"), "paste": ("LEFTSHIFT", "INSERT")}[a])
                    else:
                        vk.combo("LEFTCTRL", {"undo": "z", "cut": "x", "copy": "c", "paste": "v", "selall": "a"}[a])
            elif a == "mic":
                if st["mic"]:
                    self.dict.stop()
                    st["mic"], st["live"] = False, ""
                    self.pop_live = ""
                elif self.voice_setting_up():
                    # (installed moments ago: voice typing is still setting itself up in the background. Only while that
                    # runs, and never more than 10 minutes after it started, so it can't get stuck saying this)
                    self.flash("Voice typing will be ready within 5 minutes", 4.0)
                else:
                    st["mic"] = True
                    self.dict.lang = (self.st.get("lang") or "en")[:2]
                    self.dict.start()
                    self.check_voice()
            elif a == "esearch":  # search emoji by name: the letters type into the word bar, which shows what's found
                st["page"], st["esearch"], st["alt"] = "abc", True, -1
                self.esq, self.es_page = "", 0
            elif a == "etone":  # skin tone for the emoji that have one: none, then light to dark
                st["etone"] = st.get("etone", -1) + 1 if st.get("etone", -1) < 4 else -1
                self.conf["emoji_tone"] = st["etone"]
                save_conf(self.conf)
            elif a == "emoji" and st["page"] == "emoji":   # (the top bar's emoji button again: back to the letters)
                st["page"] = "abc"
                st["esearch"] = False
            elif a == "emoji":
                self.fetch_semo()
                self.dedupe_emoji()
                rec = tuple(self.conf.get("emoji_recent", []))
                st["page"], st["epage"], st["erecent"] = "emoji", 0, rec
                st["efav"] = tuple(self.conf.get("emoji_fav", []))
                # (Recent first only once it has a row's worth: a nearly empty page was mostly blank space; then your
                # Favorites if you have any; otherwise the faces)
                st["ecat"] = 0 if len(rec) >= (10 if st.get("layout") == "minimal" else 14) else FAV_TAB if st["efav"] else 1
            elif a and a.startswith("ecat:"):
                st["ecat"], st["epage"] = int(a[5:]), 0
                st["erecent"] = tuple(self.conf.get("emoji_recent", []))
                st["efav"] = tuple(self.conf.get("emoji_fav", []))
            elif a and a.startswith("epage:"):
                # (from the page you see: pressing past the last page used to keep counting, so going back took as
                # many presses and the page seemed stuck)
                st["epage"] = max(0, min(st.get("epage", 0), EMOJI_PAGES[0] - 1) + int(a[6:]))
            elif a == "noop":
                redraw = False
            elif a == "curve":
                st["curved"] = not st.get("curved", True)
                self.conf["curved"] = st["curved"]
                save_conf(self.conf)
                self.kb_width.clear()  # re-apply the shape
                self.set_kb_width(self.width_m)
                self.place_highlight()
            elif a == "panel":
                st["panel"] = not st.get("panel", True)
                self.conf["panel"] = st["panel"]
                save_conf(self.conf)
            elif a == "sound":
                st["sounds"] = not st["sounds"]
                self.conf["sounds"] = st["sounds"]
                save_conf(self.conf)
            elif a and a.startswith("lay-"):
                try:  # keep the letters where they are when the keyboard changes size
                    L = self.letters_world()
                    (hx, hy, hz), _ = self.head()
                    self.anchor_yaw = math.atan2(L[0] - hx, L[2] - hz)
                except Exception:
                    self.anchor_yaw = None
                st["layout"], st["page"] = a[4:], "abc"
                self.conf["layout"] = st["layout"]
                save_conf(self.conf)
            elif a == "recenter":  # back to the standard spot right in front of you (and remember that)
                for k_ in ("distance", "drop", "side"):
                    self.conf[k_] = DEFAULTS[k_]
                self.conf["roll"] = 0.0      # (and level again, if you'd tilted it)
                self.conf.pop("turn", None)
                self.conf.pop("dash_off", None)   # (and right under Steam's menu again, when it opens with the menu)
                save_conf(self.conf)
                self.recenter()
                redraw = False
            elif a == "hide":
                self.set_visible(False)
                redraw = False
        if ("ch" in k or "sym" in k) and st["shift"]:
            if self.shift_held():  # Shift held down with the other laser: it stays on until you let go of it
                self.shift_typed = True
            else:
                st["shift"] = False
                redraw = True
        if st.get("fn") and k.get("act") not in ("fn", "ctrl", "alt-mod", "shift", "caps") and "fn" not in self.locks:
            st["fn"] = False  # Fn is for one key
            redraw = True
        if (self.ctrl or self.alt or self.meta) and k.get("act") not in ("ctrl", "alt-mod", "super", "shift", "caps", "fn"):
            # Ctrl / Alt / Super apply to the next key, then switch off (unless locked on with a double tap)
            if "ctrl" not in self.locks:
                self.ctrl = st["ctrl"] = False
            if "alt-mod" not in self.locks:
                self.alt = st["altm"] = False
            if "super" not in self.locks:
                self.meta = st["meta"] = False
            redraw = True
        if redraw:
            self.dirty = True

    def mods_used(self):
        """A key typed with Fn / Ctrl / Alt / Super / Shift on: they switch off again, except any locked on."""
        st = self.st
        for name, attr, sk in (("fn", None, "fn"), ("ctrl", "ctrl", "ctrl"), ("alt-mod", "alt", "altm"), ("super", "meta", "meta")):
            if name not in self.locks:
                if attr:
                    setattr(self, attr, False)
                st[sk] = False
        st["shift"] = False if not st.get("caps") else st["shift"]
        self.dirty = True

    @property
    def locks(self):
        return self.__dict__.setdefault("_locks", set())

    def lock_tap(self, name, on):
        """Ctrl, Alt, Super and Fn: one tap is for the next key; a quick second tap locks it on (for shortcuts like
        Alt + arrows, again and again); a tap while locked lets it go. Returns whether it's on now."""
        now = time.time()
        quick = now - self.__dict__.setdefault("lock_t", {}).get(name, 0) < 0.4
        self.lock_t[name] = now
        if name in self.locks:
            self.locks.discard(name)
            on = False
        elif on and quick:
            self.locks.add(name)
            on = True
        else:
            on = not on
        self.st["locks"] = tuple(sorted(self.locks))
        LOG("%s: %s" % (name, "locked on" if name in self.locks else "on" if on else "off"))
        return on

    # SteamVR's keyboard button (under each window) says "Show Keyboard" or "Hide Keyboard" by whether ITS keyboard
    # is open, which never is (ours replaces it): so while ours is open its label is set to say "Hide Keyboard".
    # Lives in SteamVR's menu page; only rewrites that one label, only while our keyboard is open.
    KB_LABEL_JS = r"""(() => {
      const V = 1, o = window.__bfKb;
      if (!o || o.v < V) {
        if (o && o.obs) o.obs.disconnect();
        const S = window.__bfKb = {v: V, open: false, obs: null};
        const NAMES = {'Show Keyboard': 'Hide Keyboard', 'Show keyboard': 'Hide keyboard'};
        S.fix = () => {
          for (const t of document.querySelectorAll('.ControlBarButtonTooltip')) {
            const want = NAMES[t.textContent];
            if (want) { t.textContent = want; t.__bfKb = true; }
          }
        };
        let soon = 0;
        S.set = on => {
          S.open = on;
          if (on && !S.obs) {
            S.obs = new MutationObserver(() => { if (!soon) soon = requestAnimationFrame(() => { soon = 0; S.fix(); }); });
            S.obs.observe(document.body, {childList: true, subtree: true, characterData: true});
            S.fix();
          } else if (!on && S.obs) {
            S.obs.disconnect(); S.obs = null;
            for (const t of document.querySelectorAll('.ControlBarButtonTooltip'))
              if (t.__bfKb) { const back = Object.keys(NAMES).find(k => NAMES[k] === t.textContent); if (back) t.textContent = back; t.__bfKb = false; }
          }
          return 'ok';
        };
      }
      return window.__bfKb.set(%s);
    })()"""

    def tell_kb_label(self, on):
        """Keep SteamVR's keyboard button saying Show or Hide Keyboard to match ours (in the background: SteamVR's
        menu page may take a moment to answer, and the keyboard never waits on it)."""
        def work():
            try:
                import dashpin
                url = dashpin.dashboard()
                if url:
                    dashpin.run_js(url, self.KB_LABEL_JS % ("true" if on else "false"))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True, name="kb-label").start()

    # Steam's own keyboard tells Steam "a keyboard is open" while it shows, so Steam's windows stop acting on the controller
    # (the trackpads and buttons then belong to the keyboard). Ours does the same while a Steam Controller or PS5
    # controller types on it: without it, every press also clicked or moved something in Steam behind the keyboard.
    # (Steam's keyboard says it again every moment while it's open, a watchdog: Steam takes the controller back as soon
    # as that stops. So it's said from inside Steam's page, over and over, until the keyboard closes; and if BetterFrame
    # itself ever stops, it stops after 15 s by itself, so the controller always goes back to Steam)
    PAD_KB_JS = r"""(on => { try { const I = window.SteamClient && SteamClient.Input;
      if (!I || typeof I.SetKeyboardActionset !== 'function') return 'none';
      const W = window; if (W.__bfPadKb) { clearInterval(W.__bfPadKb); W.__bfPadKb = null; }
      if (on) {
        W.__bfPadKbUntil = Date.now() + 15000;
        I.SetKeyboardActionset(true, true);
        W.__bfPadKb = setInterval(() => {
          if (Date.now() > W.__bfPadKbUntil) { clearInterval(W.__bfPadKb); W.__bfPadKb = null; I.SetKeyboardActionset(false, false); return; }
          I.SetKeyboardActionset(true, true); }, 250);
      } else I.SetKeyboardActionset(false, false);
      return 'ok'; } catch (e) { return 'err ' + e; } })(%s)"""
    PAD_KB_ALIVE = r"""(() => { window.__bfPadKbUntil = Date.now() + 15000; return window.__bfPadKb ? 'on' : 'off'; })()"""
    PAD_KB_HOW = r"""(() => { const out = [];
      for (const k of Object.keys(window)) { if (!k.startsWith('webpackChunk')) continue; let req = null;
        try { window[k].push([[Symbol('bf')], {}, r => { req = r; }]); } catch (e) {}
        if (!req) continue;
        for (const id of Object.keys(req.m)) { let s = ''; try { s = req.m[id].toString(); } catch (e) { continue; }
          let i = s.indexOf('SetKeyboardActionset(');
          while (i >= 0 && out.length < 6) { out.push(s.slice(Math.max(0, i - 90), i + 90)); i = s.indexOf('SetKeyboardActionset(', i + 1); } } }
      return JSON.stringify(out); })()"""

    # While a controller types on this keyboard, Steam's own menus (the bar, its pop-ups, SteamVR's settings) would also
    # move and click with every press: Steam sends each press to them as well. Inside each of those pages, presses are
    # stopped while the keyboard says so; it has to keep saying so every moment, so if the keyboard closes, the
    # controller is put down, or BetterFrame stops, the pages take presses again by themselves within 3.5 s.
    PAD_BLOCK_JS = r"""(ms => { try { const W = window;
      W.__bfPadUntil = ms > 0 ? Date.now() + ms : 0;
      if (!W.__bfPadOn) { W.__bfPadOn = true; W.__bfPadN = 0;
        const stop = e => { if (Date.now() < (W.__bfPadUntil || 0)) { e.preventDefault(); e.stopImmediatePropagation(); W.__bfPadN++; } };
        for (const t of ['vgp_onbuttondown', 'vgp_onbuttonup', 'gamepadbuttondown', 'gamepadbuttonup', 'gamepaddirection'])
          W.addEventListener(t, stop, true);
      }
      const n = W.__bfPadN; W.__bfPadN = 0; return String(n); } catch (e) { return 'err'; } })(%d)"""

    # (Steam's cursor mode, its laser mouse, is never switched by the keyboard: see pad_block)
    CURSOR_STOP_JS = r"""(() => { const W = window; if (W.__bfCur) { clearInterval(W.__bfCur); W.__bfCur = null; }
      W.__bfCurUntil = 0; return 'ok'; })()"""
    PAD_HOW = r"""(word => { const out = [];
      for (const k of Object.keys(window)) { if (!k.startsWith('webpackChunk')) continue; let req = null;
        try { window[k].push([[Symbol('bf')], {}, r => { req = r; }]); } catch (e) {}
        if (!req) continue;
        for (const id of Object.keys(req.m)) { let s = ''; try { s = req.m[id].toString(); } catch (e) { continue; }
          let i = s.indexOf(word);
          while (i >= 0 && out.length < 6) { out.push(s.slice(Math.max(0, i - 120), i + 120)); i = s.indexOf(word, i + 1); } } }
      return JSON.stringify(out); })(%s)"""

    def pad_block(self, on):
        """Steam's menus and Steam's stand-in mouse and keyboard stop acting on the controller while it types here
        (on=False: everything back to Steam at once). Called often; does the work only every moment or so."""
        now = time.time()
        self.grab_steam_inputs(on)
        if not on and not getattr(self, "pad_block_on", False):
            return
        if on and now - getattr(self, "pad_block_t", 0) < 1.2:
            return
        if getattr(self, "pad_block_busy", False):
            return
        self.pad_block_t, self.pad_block_on, self.pad_block_busy = now, on, True

        def work():
            try:
                import dashpin
                import steambridge
                pages = getattr(self, "pad_block_pages", None)
                if not pages or now - getattr(self, "pad_block_pages_t", 0) > 10:
                    pages = self.pad_block_pages = steambridge._targets()
                    self.pad_block_pages_t = now
                stopped = 0
                for url in pages:
                    try:
                        r = dashpin.run_js(url, self.PAD_BLOCK_JS % (3500 if on else 0))
                        stopped += int(r) if str(r).isdigit() else 0
                    except Exception:
                        continue
                if not getattr(self, "cursor_left_alone", False):
                    # Steam's cursor mode for the desktop window is never changed (it is Steam's own laser mouse:
                    # switching it back on after typing turned Steam's laser mouse on, so every press clicked both
                    # the keyboard and the window behind it). An older build's timer still running in Steam's page
                    # is stopped here, without touching the setting
                    try:
                        sp = dashpin.steam_page()
                        if sp:
                            dashpin.run_js(sp, self.CURSOR_STOP_JS)
                            self.cursor_left_alone = True
                    except Exception:
                        pass
                if stopped and not getattr(self, "pad_block_said", False):
                    self.pad_block_said = True
                    LOG("controller: kept Steam's menus from also acting on %d presses" % stopped)
            except Exception as ex:
                LOG("controller: couldn't reach Steam's menus:", ex)
            finally:
                self.pad_block_busy = False
        threading.Thread(target=work, daemon=True, name="pad-block").start()

    def steam_inputs(self):
        """Steam's stand-in mouse, keyboard and gamepads (what it turns controller presses into for the desktop and
        games): [(device file, name)]. Only Steam's own made-up devices, never a real one."""
        out = []
        base = "/sys/class/input"
        for n in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if not n.startswith("event"):
                continue
            try:
                path = os.path.realpath(os.path.join(base, n))
                if "/virtual/" not in path:
                    continue   # (a real device: never)
                d = os.path.join(base, n, "device")
                name = open(os.path.join(d, "name")).read().strip()
                vid = int(open(os.path.join(d, "id", "vendor")).read(), 16)
                if (vid == 0x28DE or "steam" in name.lower()) and "betterframe" not in name.lower():
                    out.append(("/dev/input/" + n, name))
            except (OSError, ValueError):
                continue
        return out

    def grab_steam_inputs(self, on):
        """While a controller types here: Steam's stand-in mouse and keyboard are held by the keyboard alone, so the
        desktop and games don't also get the cursor moves, clicks and keys Steam makes from the same presses. Let go the
        moment it's off (and the system lets go by itself if BetterFrame ever stops)."""
        import fcntl
        held = self.__dict__.setdefault("steam_grabs", {})
        EVIOCGRAB = 0x40044590
        if not on:
            for dev, fd in list(held.items()):
                try:
                    fcntl.ioctl(fd, EVIOCGRAB, 0)
                except OSError:
                    pass
                try:
                    os.close(fd)
                except OSError:
                    pass
                held.pop(dev, None)
            return
        now = time.time()
        if now - getattr(self, "steam_grab_t", 0) < 2:
            # (what's held is read and dropped, so it never fills up)
            for fd in held.values():
                try:
                    while os.read(fd, 4096):
                        pass
                except OSError:
                    pass
            return
        self.steam_grab_t = now
        said = self.__dict__.setdefault("steam_grab_said", set())
        for dev, name in self.steam_inputs():
            if dev in held:
                continue
            try:
                fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as ex:
                if dev not in said:
                    said.add(dev)
                    LOG("controller: can't hold Steam's %s (%s)" % (name, ex.strerror))
                continue
            try:
                # never while one of its keys or buttons is down: the desktop would never hear it let go (a Shift
                # held forever). Tried again in a moment, once nothing's pressed
                keys = bytearray(96)
                fcntl.ioctl(fd, (2 << 30) | (96 << 16) | (ord("E") << 8) | 0x18, keys)
                if any(keys):
                    os.close(fd)
                    self.steam_grab_t = now - 1.8
                    continue
                fcntl.ioctl(fd, EVIOCGRAB, 1)
                held[dev] = fd
                if dev not in said:
                    said.add(dev)
                    LOG("controller: holding Steam's %s while typing with the controller" % name)
            except OSError:
                os.close(fd)

    def tell_controller(self, on):
        """Steam Controller / PS5 typing on this keyboard: Steam hands the controller to the keyboard while it's open, and
        takes it back when it closes (in the background: the keyboard never waits on Steam)."""
        mark = os.path.join(CONF_DIR, "pad-keyboard-mode")
        if on:
            return   # (not used: it put the controller into Steam's keyboard mode, which made Steam react more, not less)
        if not on and not os.path.exists(mark):
            return

        def work():
            try:
                import dashpin
                import steambridge
                url = dashpin.steam_page() or next((u for u in steambridge._targets() if ":8080/" in u), None)
                if not url:
                    return
                res = dashpin.run_js(url, self.PAD_KB_JS % ("true" if on else "false"))
                if on:
                    open(mark, "w").close()
                else:
                    try:
                        os.remove(mark)
                    except OSError:
                        pass
                if res != getattr(self, "pad_kb_said", None):
                    self.pad_kb_said = res
                    LOG("controller: Steam told a keyboard is %s (%s)" % ("open" if on else "closed", res))
                    if not getattr(self, "pad_kb_how", False):   # (how Steam itself calls it: noted once, for checking)
                        self.pad_kb_how = True
                        LOG("controller: how Steam's keyboard does it:", str(dashpin.run_js(url, self.PAD_KB_HOW))[:600])
            except Exception as ex:
                LOG("controller: couldn't tell Steam:", ex)
        threading.Thread(target=work, daemon=True, name="pad-kb").start()

    def set_visible(self, on, recenter=True):
        if on == self.visible:
            return
        self.visible = on
        self.tell_kb_label(on)
        self.tell_controller(on)
        if not on:
            self.asked = False      # (closed: whatever asked for it has had its answer)
            self.steam_field = False
        self.ducked = 0.0
        try:
            self.sounds.open_async() if on and self.st.get("sounds") else self.sounds.close()   # (key sound Off: no audio at all)
        except Exception:
            pass
        if on:
            self.warm_swipe()
            if recenter:
                self.recenter()
            else:
                self.apply_transform()
            if self.dirty:
                self.redraw()
            self.ov.showOverlay(self.handle)
            if self.wing_on:
                self.set_kb_transform()
                self.ov.showOverlay(self.wing)
                self.wing_shown = True
        else:
            self.finish_fade()
            for h in self.kbs:
                self.ov.hideOverlay(h)
            self.ov.hideOverlay(self.wing)
            self.wing_shown = False
            self.pending_hide = None
            self.ov.hideOverlay(self.hl)
            for sl in list(self.hovers):
                self.hovers[sl] = None
                self.place_highlight(sl)
                self.hide_beam(sl)
            self.repeat = None
            self.held.clear()
            self.ehold.clear()
            self.swipes.clear()
            self.trail_dirty = True
            # next time it opens on the page it was left on (emoji, numbers, symbols), so a quick close doesn't lose
            # your place. Only the pickers (languages, key layouts) and emoji search go back to normal: those are for
            # one choice, and letters typed into emoji search would be lost to the next text box
            if self.st.get("page") in ("lang", "fmt") or self.st.get("esearch"):
                self.st["page"] = "emoji" if self.st.get("esearch") else "abc"
                self.st["esearch"], self.st["alt"] = False, -1
                self.esq = ""
                self.dirty = True
            self.word_list, self.cur_word, self.preview_word = [], "", ""
            if self.comp is not None and not self.comp.empty():
                self.ime_commit_all()
            self.steam_on = False
            if self.calib and self.calib != self.conf.get("aim_calib"):
                self.conf["aim_calib"] = {k: [round(a, 4) for a in v] for k, v in self.calib.items()}
                save_conf(self.conf)
            self.end_drag()
            if self.st["mic"]:
                self.dict.stop()
                self.st["mic"], self.st["live"] = False, ""
                self.pop_live = ""
                self.dirty = True
        self.aim_on_visible(on)
        self.upload_toggle()

    def toggle(self):
        if time.time() < self.toggle_block_until:  # ignore echoes from SteamVR's own keyboard
            return
        self.toggle_block_until = time.time() + 0.8
        self.suspended = False
        self.set_visible(not self.visible)

    STEAM_UI = ("valve.steam.gamepadui.main", "valve.steam.gamepadui.bar")

    def asked_by_steam(self, ev):
        """Was it one of Steam's own windows that asked for the keyboard (friend chat, search, Settings...)? Those
        don't take key presses from a keyboard: Steam's own keyboard hands them its text through Steam. SteamVR says
        which window asked."""
        try:
            h = int(ev.data.keyboard.overlayHandle) if ev is not None else 0
        except Exception:
            h = 0
        if not h:
            # (opened with the keyboard button, no window named) while Steam's menu is up with one of its text boxes
            # selected: type into that box. Never while a game or app is in front: those take key presses
            return False   # (Steam asks for the keyboard itself as soon as one of its boxes is clicked)
        # SteamVR names Steam's windows differently from version to version (the Store and Library window isn't
        # "gamepadui.main" any more on the Frame, so search there was typed as key presses, which Steam ignores):
        # any of Steam's own windows counts
        try:
            name = str(self.ov.getOverlayKey(h) or "")
        except Exception:
            name = ""
        if name != getattr(self, "asked_key", None):
            self.asked_key = name
            LOG("keyboard asked for by:", name or "(unknown window)")
        if name.startswith("valve.steam.") or name == "valve.steam":
            return True
        for key in self.STEAM_UI:
            try:
                if int(self.ov.findOverlay(key) or 0) == h:
                    return True
            except Exception:
                continue
        return False

    def on_system_keyboard(self, ev=None):
        """The system asked for a keyboard (the keyboard button, or a text box asking for one by itself).
        Close the system one, and show ours. Only close ours if it has been left alone for a bit,
        so a text box asking for a keyboard while you type never takes yours away."""
        now = time.time()
        if now - getattr(self, "pad_toggle_t", 0) < 1.5:
            # (the controller's open/close shortcut also made Steam ask for its keyboard: already handled)
            self.close_steam_keyboard()
            self.kill_kb_until = now + 1.5
            return
        if self.gamepad_typing():
            # typing with a Steam Controller (the Frame's own controllers put down): Steam's keyboard, which types
            # with the trackpads, is left open this time (Settings > Keyboard > Steam Controller)
            LOG("keyboard asked for while using a Steam Controller: Steam's own keyboard this time")
            self.kill_kb_until, self.sys_kb_open = 0, False
            self.steam_kb_mine = True   # (Steam's own keyboard is the one open: its button says "Hide Keyboard")
            if self.visible:
                self.set_visible(False)
            return
        self.sys_kb_open = True   # (closed below; and again for as long as it keeps coming back while ours is up)
        since_key = now - self.last_press
        self.close_steam_keyboard()
        steam = self.asked_by_steam(ev)
        try:
            self.asked_handle = int(ev.data.keyboard.overlayHandle) if (steam and ev is not None) else 0
        except Exception:
            self.asked_handle = 0
        if isinstance(getattr(self.vk, "stream", None), SteamUIText):
            self.vk.stream = None   # (a new box asked: find its page again, never type into the last one's)
        if steam != getattr(self, "steam_field", False):
            LOG("typing into: %s" % ("Steam's own text box (through Steam, like its keyboard)" if steam else "apps (key presses)"))
        self.steam_field = steam
        self.check_stream()
        self.kill_kb_until = now + 2.5  # it can take a moment to finish opening, so keep closing it
        if now < self.toggle_block_until:  # the same press reported twice
            LOG("keyboard button: repeat ignored")
            return
        self.toggle_block_until = now + 0.4
        # a game or text box asking (Steam's menu closed): the keyboard opens, or stays open, and never closes. (It
        # was taken as the keyboard button, which toggles: with the keyboard already open, a game's request closed
        # it, so it seemed to show up only sometimes.) Enter then sends the text and closes it, back to the game
        try:
            menu = bool(self.ov.isDashboardVisible())
        except Exception:
            menu = True
        try:   # which window asked (none: a game itself; a window: its keyboard button, like a pinned window's)
            asker = int(ev.data.keyboard.overlayHandle) if ev is not None else 0
        except Exception:
            asker = 0
        LOG("keyboard asked for (Steam menu %s, by %s)" % ("open" if menu else "closed", "a window" if asker else "a game or nothing named"))
        # a game asking: open and keep open (Enter finishes). A window's keyboard button (even with the menu closed, like a
        # pinned window's) is a button: it opens AND closes. (It was taken as a game asking, so it never closed: only X did)
        if (not menu and not asker) or self.streaming():
            self.asked = True
            if not self.visible:
                LOG("a game or text box asked for the keyboard: open")
                self.suspended = False
                self.dash_hide_pending = False
                self.set_visible(True)
                self.asked = True
            elif not self.in_view() or not self.ov.isOverlayVisible(self.handle):
                LOG("a game or text box asked for the keyboard: brought it back in front")
                self.recenter()
                self.ov.showOverlay(self.handle)
            else:
                LOG("a game or text box asked for the keyboard: already open")
            return
        if not self.visible:
            LOG("keyboard button: open")
            self.suspended = False
            self.dash_hide_pending = False
            self.set_visible(True)
        elif since_key < 1.5:  # a text box asked for a keyboard while you're using it: keep yours
            LOG("keyboard asked for while typing: kept open")
        elif not self.in_view() or not self.ov.isOverlayVisible(self.handle):
            # it's open but you can't see it (behind you, or SteamVR hid it): bring it here instead of closing it
            LOG("keyboard button: keyboard was out of sight, brought it back in front")
            self.recenter()
            self.ov.showOverlay(self.handle)
        else:
            LOG("keyboard button: close")
            self.set_visible(False)

    STREAM_OVERLAYS = ("steamlink_openvr-overlay",)

    def streaming(self):
        """Is a game being streamed to the headset from a PC right now?"""
        on, why = False, ""
        for key in self.STREAM_OVERLAYS:
            try:
                h = self.ov.findOverlay(key)
                if h and self.ov.isOverlayVisible(h):
                    on, why = True, key
                    break
            except Exception:
                continue
        # on the Frame that window can be up in everyday use (the desktop in your headset too), so it's only streaming
        # when Steam's streaming client is actually running as well. (Taking the window alone sent everything you typed
        # through Steam's streaming text: slower, and emoji came out as numbers and colons)
        if on:
            client = self.stream_client()
            if not client:
                on, why = False, why + " is showing, but no streaming client is running"
            else:
                why += ", " + client
        if on != getattr(self, "was_streaming", None):   # (said once each time it changes, so a test shows it)
            self.was_streaming = on
            LOG("streaming from a PC: %s" % ("yes (%s)" % why if on else "no" + (" (%s)" % why if why else "")))
        return on

    def pad_tick(self):
        """The Steam Controller on the keyboard (Settings > Keyboard > Steam Controller):
        - each trackpad has its own highlight; click the pad (or press firmly), or pull that side's trigger, to type it
        - the sticks and D-pad step that side's highlight from key to key (left stick and D-pad: left; right stick:
          right); A types the key that last moved
        - X Backspace, Y Space, Menu Enter, B closes the keyboard; left stick click (or left bumper) Shift, twice
          quickly for Caps Lock
        - Steam + X (or View + Menu) opens and closes the keyboard from anywhere
        Read only while a Steam Controller is connected; it's left alone otherwise."""
        if not getattr(self, "pad_kb_reset", False):
            # (started fresh, maybe after the keyboard stopped while open: Steam gets the controller back for its own use)
            self.pad_kb_reset = True
            if not self.visible:
                self.tell_controller(False)
        mode = self.st.get("padkb", "pads")
        pr = self.__dict__.get("pads")
        if mode not in ("pads", "split") or not self.steam_pad():
            self.pad_block(False)
            if pr is not None and pr.running:
                pr.stop()
                self.pad_clear()
            return
        if pr is None:
            pr = self.pads = PadReader()
            pr.press_at = getattr(self, "pad_press_at", 2000)
            pr.press_frac = getattr(self, "pad_press_frac", 0.3)
        if not pr.running and self.visible:
            self.tell_controller(True)
        now_ = time.time()
        if self.visible:
            if now_ - getattr(self, "pad_kb_alive_t", 0) > 5 and os.path.exists(os.path.join(CONF_DIR, "pad-keyboard-mode")):
                self.pad_kb_alive_t = now_

                def alive():
                    try:
                        import dashpin
                        url = dashpin.steam_page()
                        if url and dashpin.run_js(url, self.PAD_KB_ALIVE) == "off":
                            self.tell_controller(True)   # (Steam's page restarted: said again)
                    except Exception:
                        pass
                threading.Thread(target=alive, daemon=True, name="pad-kb-alive").start()
        pr.start()
        st = pr.state
        now = time.time()
        b = st["buttons"]
        prev = self.__dict__.get("pad_prev", 0)
        self.pad_prev = b
        new = b & ~prev
        P = PadReader
        # open / close from anywhere: Steam + X, or View + Menu
        if (new & P.X and b & P.STEAM) or (new & (P.VIEW | P.MENU) and b & P.VIEW and b & P.MENU):
            if now - getattr(self, "pad_toggle_t", 0) > 0.8:
                self.pad_toggle_t = now
                self.toggle_block_until = 0
                if self.visible:
                    self.toggle()
                else:   # (opened with the controller: straight in front of you, a little below your eyes)
                    self.suspended = False
                    self.place_ahead = True
                    self.set_visible(True)
                LOG("Steam Controller: keyboard", "opened" if self.visible else "closed")
            return
        if not self.visible or not self.items:
            self.pad_block(False)
            self.pad_clear()
            return
        if b & P.STEAM:
            self.pad_block(False)   # (Steam's own shortcuts: all Steam's)
            return   # (Steam's own shortcuts with the Steam button: not keys)
        # the controller put down: its highlights go after a few seconds (back as soon as it's used again)
        used = b or st["L"][0] or st["R"][0] or max(st["trig"]) > 0.2 or \
            any(math.hypot(*v) > 0.35 for v in st["sticks"])
        if used:
            self.pad_used_t = now
        # typing with the game controller right now (used in the last 3 s, and the Frame's own controllers not
        # pointing at the keyboard): Steam's menus and its stand-in mouse and keyboard leave the controller to the
        # keyboard. The moment a laser is used, or the controller is put down, all of it goes straight back to Steam
        # (always on while the keyboard was open, it got in the way of the Frame's lasers too)
        # (only a real laser: a key typed with the game controller counted as one, and every key typed let Steam's
        # menus have the controller back for 1.5 s, so presses went to both)
        laser_recent = now - getattr(self, "laser_t", 0) < 1.5
        self.pad_block(now - getattr(self, "pad_used_t", 0) < 3.0 and not laser_recent)
        if not used and now - getattr(self, "pad_used_t", 0) > 4 and self.__dict__.get("pad_focus"):
            self.pad_clear()
            return
        # ---- the trackpads: where each thumb is
        bx0 = min(r[0] for _, r in self.items)
        by0 = min(r[1] for _, r in self.items)
        bx1 = max(r[2] for _, r in self.items)
        by1 = max(r[3] for _, r in self.items)
        focus = self.__dict__.setdefault("pad_focus", {})
        clicks = self.__dict__.setdefault("pad_click", {})
        smooth = self.__dict__.setdefault("pad_smooth", {})
        for side in ("L", "R"):
            touch, x, y, click = st[side]
            slot = "pad" + side
            if touch:
                # steadier: the position eases toward the thumb (no jitter between two keys), and the highlight
                # only moves on once the thumb is clearly over another key
                ox, oy = smooth.get(side, (x, y))
                x, y = ox + (x - ox) * 0.45, oy + (y - oy) * 0.45
                smooth[side] = (x, y)
                m = st.get("margin", 0.12)   # (a round pad's edges are hard to reach: a little in reaches the last keys)
                fx = min(1.0, max(0.0, (x - m) / (1 - 2 * m)))
                fy = min(1.0, max(0.0, (y - m) / (1 - 2 * m)))
                if mode == "split" and not st.get("one_pad"):   # (a PS5 controller has one pad: always all of it)
                    fx = fx / 2 + (0.5 if side == "R" else 0.0)
                px, py = bx0 + fx * (bx1 - bx0), by0 + fy * (by1 - by0)
                cur = focus.get(side)
                if not (isinstance(cur, int) and cur < len(self.items) and self.near_key(cur, px, py)):
                    self.pad_set(side, self.nearest_key(px, py))
                self.pad_last = side
            else:
                smooth.pop(side, None)
            was = clicks.get(side, False)
            clicks[side] = click
            if click and not was:
                self.pad_hold(("pad", side), self.pad_press(side), now)
        if b & P.L3 and not prev & P.L3 and now - getattr(self, "l3_t", 0) > 0.1:
            # Shift: the left stick pressed in (twice quickly: Caps Lock). One click is one press, even if the button
            # flickers as it goes down
            self.l3_t = now
            k = next((k for k, _ in self.items if k.get("act") == "shift"), None) or {"act": "shift", "label": "Shift"}
            self.press(k)
        # ---- triggers: type that side's key
        for i, side in enumerate(("L", "R")):
            key = "trig" + side
            down = st["trig"][i] > 0.6 or (getattr(self, key, False) and st["trig"][i] > 0.35)
            if down and not getattr(self, key, False):
                self.pad_hold(("trig", side), self.pad_press(side), now)
            setattr(self, key, down)
        self.pad_repeat(st, b, now)
        # ---- sticks and D-pad: step from key to key (held: keeps stepping)
        moves = {"L": st["sticks"][0], "R": st["sticks"][1]}
        dx = (1 if b & P.DRIGHT else 0) - (1 if b & P.DLEFT else 0)
        dy = (1 if b & P.DUP else 0) - (1 if b & P.DDOWN else 0)
        if dx or dy:
            moves["L"] = (dx, dy)
        steps = self.__dict__.setdefault("pad_step", {})
        for side, (sx, sy) in moves.items():
            if math.hypot(sx, sy) < 0.55:
                steps.pop(side, None)
                continue
            due = steps.get(side)
            if due is not None and now < due:
                continue
            steps[side] = now + (0.38 if due is None else 0.11)   # (a moment before it starts repeating)
            cur = focus.get(side)
            if not (isinstance(cur, int) and cur < len(self.items)):
                cur = self.nearest_key((bx0 + bx1) / 2, (by0 + by1) / 2)
                self.pad_set(side, cur)
            else:
                self.pad_set(side, self.key_toward(cur, sx, -sy))
            self.pad_last = side
        # ---- face buttons and bumpers: only when asked for (Settings > Keyboard > Controller buttons too)
        if not self.st.get("padbuttons", True):
            return
        named = {P.A: None, P.X: "back", P.Y: "space", P.MENU: "enter", P.B: "close", P.LB: "shift"}
        for bit, act in named.items():
            if not new & bit or now - self.__dict__.setdefault("btn_t", {}).get(bit, 0) < 0.06:
                continue
            self.btn_t[bit] = now
            self.last_touch = now
            if bit == P.A:
                self.pad_press(getattr(self, "pad_last", "R"))
            elif act == "close":
                self.set_visible(False)
                return
            else:
                k = next((k for k, _ in self.items if k.get("act") == act), None) or {"act": act, "label": act}
                self.press(k)
                if bit == P.X:   # (held: keeps deleting, like a held Backspace key)
                    self.pad_rep = {"src": ("btn", P.X), "key": k, "next": now + 0.45}

    PAD_REPEATS = ("back", "del", "left", "right", "up", "down")

    def pad_hold(self, src, idx, now):
        """A key typed with a trackpad or trigger: Backspace, Delete and the arrows keep going while it's held."""
        if idx is None:
            return
        k = self.items[idx][0]
        if k.get("act") in self.PAD_REPEATS:
            self.pad_rep = {"src": src, "idx": idx, "key": k, "next": now + 0.45}

    def pad_repeat(self, st, b, now):
        r = self.__dict__.get("pad_rep")
        if not r:
            return
        kind, which = r["src"]
        if kind == "btn":
            held = bool(b & which)
        else:
            held = (self.__dict__.get("pad_click", {}).get(which, False) if kind == "pad"
                    else getattr(self, "trig" + which, False)) and \
                self.__dict__.get("pad_focus", {}).get(which) == r["idx"]
        if not held:
            self.pad_rep = None
            return
        if now >= r["next"]:
            r["next"] = now + 0.055
            self.last_touch = now
            self.press(r["key"], quiet=True)

    def pad_set(self, side, idx):
        slot = "pad" + side
        self.pad_focus[side] = idx
        if self.hovers.get(slot) != idx:
            if idx is None:
                self.hovers.pop(slot, None)
            else:
                self.hovers[slot] = idx
            self.place_highlight(slot)

    def pad_press(self, side):
        idx = self.__dict__.get("pad_focus", {}).get(side)
        if not (isinstance(idx, int) and idx < len(self.items)):
            return
        now = time.time()
        last = self.__dict__.setdefault("pad_press_t", {})
        if now - last.get(side, 0) < 0.06:   # (a pad or trigger wobbling at the edge of a press: still one press)
            return
        last[side] = now
        slot = "pad" + side
        self.last_touch = time.time()
        self.hpressed[slot] = time.time() + 0.09
        self.place_highlight(slot)
        self.press(self.items[idx][0])
        return idx

    def pad_clear(self):
        for side in ("L", "R"):
            if self.hovers.pop("pad" + side, None) is not None:
                self.place_highlight("pad" + side)
        self.__dict__.get("pad_focus", {}).clear()

    def near_key(self, idx, x, y):
        """Still over this key, or only just past its edge (so the highlight doesn't flicker between two keys)?"""
        x0, y0, x1, y1 = self.items[idx][1]
        mx, my = (x1 - x0) * 0.18, (y1 - y0) * 0.18
        return x0 - mx <= x <= x1 + mx and y0 - my <= y <= y1 + my

    def key_toward(self, idx, dx, dy):
        """The next key from this one in a direction (dx, dy: screen directions, y down): the nearest one roughly
        that way, preferring keys in line with it."""
        x0, y0, x1, y1 = self.items[idx][1]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        n = math.hypot(dx, dy) or 1
        ux, uy = dx / n, dy / n
        best, bs = idx, None
        for i, (k, (a0, b0, a1, b1)) in enumerate(self.items):
            if i == idx or k.get("panel") == "wing" or k.get("spacer") or \
                    (k.get("ghost") and not str(k.get("act", "")).startswith(("sugg:", "ime:"))):
                continue
            vx, vy = (a0 + a1) / 2 - cx, (b0 + b1) / 2 - cy
            along = vx * ux + vy * uy
            if along <= 2:
                continue
            side_off = abs(vx * uy - vy * ux)
            if side_off > along * 1.2:      # (more sideways than that way: not in this direction)
                continue
            score = along + side_off * 2.5
            if bs is None or score < bs:
                best, bs = i, score
        return best

    def is_laser(self, dev):
        """Is this device one of the VR controllers (a real laser)? Remembered per device."""
        cache = self.__dict__.setdefault("laser_dev", {})
        if dev not in cache:
            try:
                cache[dev] = 0 < int(dev) < self.vr.k_unMaxTrackedDeviceCount and \
                    self.system.getTrackedDeviceClass(int(dev)) == self.vr.TrackedDeviceClass_Controller
            except Exception:
                cache[dev] = True   # (can't tell: treated as before)
        return cache[dev]

    def nearest_key(self, x, y):
        """The key under a point, or the closest one (a thumb between two keys still lands on one)."""
        best, bd = None, None
        for i, (k, (x0, y0, x1, y1)) in enumerate(self.items):
            if k.get("panel") == "wing" or k.get("spacer") or \
                    (k.get("ghost") and not str(k.get("act", "")).startswith(("sugg:", "ime:"))):
                continue   # (the word bar's spots count: picking a suggested word with a thumb works too)
            dx = max(x0 - x, 0, x - x1)
            dy = max(y0 - y, 0, y - y1)
            d = dx * dx + dy * dy
            if bd is None or d < bd:
                best, bd = i, d
                if d == 0:
                    break
        return best

    PAD_IDS = {0x1102, 0x1142, 0x1106, 0x1302, 0x1303, 0x1304}   # Valve's Steam Controllers: the 2015 one (wired, dongle,
    # Bluetooth) and the new one and its puck

    def steam_pad(self):
        """Is a Steam Controller connected (looked at every 5 s)?"""
        now = time.time()
        if now - getattr(self, "pad_t", 0) < 5:
            return getattr(self, "pad_on", False)
        self.pad_t, found = now, False
        try:
            for d in os.listdir("/sys/bus/hid/devices"):
                try:
                    with open("/sys/bus/hid/devices/%s/uevent" % d) as f:
                        u = dict(l.split("=", 1) for l in f.read().splitlines() if "=" in l)
                except OSError:
                    continue
                parts = u.get("HID_ID", "").split(":")
                name = u.get("HID_NAME", "")
                ids = (int(parts[1], 16), int(parts[2], 16)) if len(parts) == 3 else (0, 0)
                if (ids[0] == 0x28DE and ids[1] in self.PAD_IDS) or PadReader.kind_of(*ids) or \
                        re.search(r"\bSteam Controller\b", name):
                    found = True
                    break
        except OSError:
            pass
        self.pad_trackpads = found   # (a controller with trackpads: typing on this keyboard with them)
        if not found:
            try:   # any other controller (Xbox, Switch Pro, 8BitDo...)
                found = bool(PadReader.gamepads())
            except Exception:
                pass
        if found != getattr(self, "pad_on", None):
            LOG("game controller:", "connected" if found else "none")
        self.pad_on = found
        return found

    def watch_hands(self):
        """When the Frame's own controllers last moved (looked at once a second): put down or asleep for a while
        means you're using something else."""
        try:
            now = time.time()
            last = self.__dict__.setdefault("hand_pos", {})
            for i, pos, _ in self.controller_rays():
                old = last.get(i)
                if old is None or math.dist(old, pos) > 0.015:
                    last[i] = pos
                    self.hands_t = now
        except Exception:
            pass

    def gamepad_typing(self):
        """Typing with a Steam Controller right now? It's connected, the Frame's controllers have been still (or off)
        for 20 s, and Settings > Keyboard > Steam Controller is on."""
        mode = self.st.get("padkb", "pads")
        if mode == "off":
            return False
        if mode != "steam":
            # trackpad typing is set, but the controller in use has no trackpads (Xbox, Switch Pro, 8BitDo...) and its
            # buttons are left to Steam: Steam's keyboard, which those controllers type with, is the better one
            if not self.steam_pad() or getattr(self, "pad_trackpads", True) or self.st.get("padbuttons", True):
                return False
        if time.time() - max(getattr(self, "hands_t", 0), getattr(self, "last_touch", 0)) < 8:
            return False
        return self.steam_pad()

    def set_focus_watch(self, on):
        """Settings > Keyboard > Open automatically: watch for text boxes being selected on the desktop."""
        w = self.__dict__.get("focus_watch")
        if on and w is None:
            try:
                import a11yfocus
                import importlib.util
                if importlib.util.find_spec("jeepney") is None:
                    LOG("text box focus: its part isn't installed (run the install again)")
                    return
                # (it finds the VR desktop's own bus itself, from KDE's running programs, and follows it if it restarts)
                self.focus_watch = a11yfocus.FocusWatch(self.on_text_box, log=LOG)
                self.focus_watch.start()
            except Exception as ex:
                LOG("text box focus: unavailable:", ex)
        elif not on and w is not None:
            w.stop()
            self.focus_watch = None
            try:
                import a11yfocus
                threading.Thread(target=a11yfocus.turn_off, daemon=True).start()
            except Exception:
                pass

    def on_text_box(self):
        # called from the watcher's thread: the main loop opens the keyboard (open_for_text_box)
        self.text_box_t = time.time()

    def open_for_text_box(self):
        t = getattr(self, "text_box_t", 0)
        if not t or t == getattr(self, "text_box_done", 0):
            return
        self.text_box_done = t
        if self.visible or time.time() - t > 2 or not self.st.get("autoopen", False):
            return
        if self.gamepad_typing():
            return   # (typing with a Steam Controller on Steam's keyboard: that's the one)
        try:
            menu = bool(self.ov.isDashboardVisible())
        except Exception:
            menu = True
        game = False
        try:
            game = bool(self.vr.VRApplications().getCurrentSceneProcessId())
        except Exception:
            pass
        if game and not menu:
            return   # (in a game with the menu closed: something on the desktop behind it took focus, not you)
        LOG("a text box was selected on the desktop: keyboard opened")
        self.suspended = False
        self.dash_hide_pending = False
        self.set_visible(True)

    def lookup(self, key, fn):
        """Ask Steam's pages something in the background, never on the keyboard's own loop: a busy Steam page can
        take seconds to answer, and the keyboard froze meanwhile (no highlights, no voice bubble, sounds stuck).
        Returns (result, True) once it's answered, (None, False) while it's still being asked."""
        jobs = self.__dict__.setdefault("lookups", {})
        j = jobs.get(key)
        if j is None:
            j = jobs[key] = {"done": False, "res": None}

            def run():
                try:
                    j["res"] = fn()
                except Exception:
                    j["res"] = None
                j["done"] = True
            threading.Thread(target=run, daemon=True, name="steam-lookup").start()
            return None, False
        if not j["done"]:
            return None, False
        del jobs[key]
        return j["res"], True

    def left_steam(self):
        """Is the Steam window whose text box asked for the keyboard gone from view (another tab of the menu, the
        desktop, the menu closed)?"""
        try:
            h = getattr(self, "asked_handle", 0)
            if h:
                return not self.ov.isOverlayVisible(h)
            return not self.ov.isDashboardVisible()
        except Exception:
            return False

    def stream_client(self):
        """The name of Steam's streaming client if it's running (looked at every 3 s), or "". Also notes, once, which
        programs with "stream" or "link" in their name are running, to tell streaming apart in the log."""
        now = time.time()
        if now - getattr(self, "client_t", 0) < 3:
            return getattr(self, "client_name", "")
        self.client_t = now
        found, seen = "", set()
        uid = os.getuid()
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                if os.stat("/proc/" + pid).st_uid != uid:
                    continue
                with open("/proc/%s/comm" % pid) as f:
                    name = f.read().strip()
            except OSError:
                continue
            low = name.lower()
            if "stream" in low or "link" in low:
                seen.add(name)
            if low.startswith("streaming_clien") or low in ("steamlink", "steam-link", "steamlinkvr"):
                found = name
        if seen != getattr(self, "client_seen", None):
            self.client_seen = seen
            LOG("programs named like streaming:", ", ".join(sorted(seen)) or "none")
        self.client_name = found
        return found

    def check_stream(self):
        """Streamed game on: text goes through Steam to the PC (Settings > Keyboard > Streamed games)."""
        if not isinstance(self.vk, QueuedKeyboard):
            return
        if getattr(self, "steam_field", False) and self.left_steam():
            # you've moved on from Steam's window (to the desktop, a game...): typing goes back to key presses there
            self.steam_field = False
            LOG("typing into: apps (key presses): Steam's window isn't in front any more")
        # (also Steam's own text boxes: friend chat, search... they only take text the way Steam's keyboard sends it)
        want = (self.streaming() and getattr(self, "stream_mode", "steam") == "steam") or \
            getattr(self, "steam_field", False)
        if want and isinstance(self.vk.stream, StreamText) and getattr(self, "steam_field", False) and \
                not self.streaming() and time.time() - getattr(self, "box_retry", 0) > 2:
            # Steam's text box wasn't selected yet when the keyboard opened (friend chat focuses its box a moment
            # later): keep looking for it, and type straight into it once it's there
            url, done = self.lookup("box", SteamUIText.find)
            if done:
                self.box_retry = time.time()
            if url:
                self.vk.stream = SteamUIText(url)
                LOG("typing into: Steam's text box, at its cursor (found a moment later)")
                return
        if want and not self.vk.stream and getattr(self, "steam_field", False) and not self.streaming():
            # one of Steam's own text boxes: type straight into it (at its cursor) when its page can be found
            url, done = self.lookup("box", SteamUIText.find)
            if not done:
                return   # (still asking Steam's pages: decided on a later check, a moment from now)
            if url:
                self.vk.stream = SteamUIText(url)
                LOG("typing into: Steam's text box, at its cursor")
                return
        if want and not self.vk.stream:
            if time.time() - getattr(self, "stream_fail", 0) < 30:
                return
            url, done = self.lookup("send", StreamText.find)
            if not done:
                return
            if not url:
                self.stream_fail = time.time()
            if url:
                self.vk.stream = StreamText(url)
                self.vk.call(self.vk.stream.let_go, True)   # (anything left held down from before: let go)
                self.vk.stream.ascii_only = bool(self.streaming())
                self.vk.stream.on_drop = lambda: self.flash("Emoji and accented letters can't be sent to a streamed PC"
                                                             if getattr(self, "was_streaming", False)
                                                             else "Emoji can't be typed here right now")
                self.vk.stream.on_fail = lambda: self.flash("Only letters, Backspace, Enter and Tab reach a streamed PC")
                LOG("streamed game: typing goes through Steam to the PC")
            if not url and not getattr(self, "stream_said", False):
                self.stream_said = True
                LOG("streamed game, but Steam's text sending isn't reachable: typing as keys")
        elif not want and self.vk.stream:
            if hasattr(self.vk.stream, "let_go"):
                self.vk.call(self.vk.stream.let_go, True)
            self.vk.stream = None
            LOG("streamed game typing: back to normal keys")

    def follow_dashboard(self):
        """Hide with the Steam menu and come back with it (same spot). The change has to last half a
        second and never fires while you're using the keyboard, so a flicker can't take it away."""
        try:
            dash = bool(self.ov.isDashboardVisible())
        except Exception:
            return
        now = time.time()
        if getattr(self, "dash", None) is None:
            self.dash, self.dash_seen = dash, None
            return
        if dash == self.dash:
            self.dash_seen = None
            return
        if self.dash_seen is None:
            self.dash_seen = now
            return
        # (closing: a fifth of a second, so it goes away with the menu; opening: half a second, so a flicker
        # can't bring it back)
        if now - self.dash_seen < (0.5 if dash else 0.2):
            return
        LOG("Steam menu", "opened" if dash else "closed")
        self.dash, self.dash_seen = dash, None
        if not dash and self.visible:
            self.dash_hide_pending = True
        elif dash:
            self.dash_hide_pending = False
            if getattr(self, "suspended", False):
                self.suspended = False
                self.set_visible(True, recenter=False)

    def finish_dash_hide(self):
        if self.dash_hide_pending and self.visible and time.time() - self.last_press > 0.4 and not self.drag:
            self.dash_hide_pending = False
            self.suspended = True
            self.set_visible(False)

    @staticmethod
    def repeatable(k):
        return ("ch" in k or "sym" in k or "ins" in k) and not k.get("emoji") or k.get("act") in ("back", "del", "left", "right", "up", "down", "space",
                                                                         "pgup", "pgdn")

    def held_variant(self, k, typed):
        """Hold-to-shift: what a held key types instead (its capital, or its upper character: 1 -> !)."""
        if "sym" in k and len(k["sym"]) > 1:
            other = k["sym"][1] if typed == k["sym"][0] else k["sym"][0]
            return LANG.TYPES.get(other, other)
        if len(typed) == 1 and typed.isalpha():
            up = LANG.shifted(typed)
            return up if up != typed else typed.lower()
        return None

    def repeat_text(self, k):
        """The exact character the first press typed, so a held key keeps typing the same thing."""
        lang = LANG.get(self.st.get("lang"))
        if self.ctrl or self.alt or lang["romaji"] or lang.get("ime"):
            return None  # (a held key presses again instead, so it goes through the converter)
        return self.char_for(k)

    # ---- emoji search
    def esearch_results(self):
        import emoji_data as E
        key = (self.esq, self.st.get("etone", -1))
        if getattr(self, "_es_for", None) != key:
            self._es_for, self._es_found = key, E.search(self.esq, self.st.get("etone", -1), n=70) if self.esq.strip() else []
        return self._es_found

    def esearch_want(self):
        found = self.esearch_results()
        pages = max(1, -(-len(found) // 7))
        pg = min(self.es_page, pages - 1)
        return ("esearch", self.esq, tuple(found[pg * 7:pg * 7 + 7]), pages > 1)

    def esearch_close(self):
        self.st["esearch"], self.esq, self.es_page = False, "", 0
        self.dirty = True

    def after_held_letter(self):
        """A letter typed by holding it (swipe typing on): Shift goes off after it, like after any letter."""
        self.last_press = time.time()
        if self.st.get("shift") and not self.shift_held():
            self.st["shift"] = False
            self.dirty = True

    def fetch_semo(self):
        """Steam's emoticons you own, from Steam itself (its chat keeps the list), and their pictures: in the
        background, so the emoji page opens at once; they appear on its Steam tab as they arrive."""
        if time.time() - getattr(self, "semo_t", 0) < 30 or getattr(self, "semo_busy", False):
            return
        self.semo_t, self.semo_busy = time.time(), True

        def work():
            try:
                import dashpin
                url = dashpin.steam_page()
                got = json.loads(dashpin.run_js(url, SEMO_JS) or "{}") if url else {}
                if got.get("ok") and not got.get("n") and not got.get("owned"):
                    # empty: Steam hasn't loaded them yet. Ask it to, then look again for a few seconds
                    asked = json.loads(dashpin.run_js(url, SEMO_LOAD_JS) or "{}")
                    LOG("Steam emoticons: none loaded yet; asked Steam to load them (called: %s; its functions: %s)" % (
                        ", ".join(asked.get("called") or []) or "nothing fitting", ", ".join(asked.get("fns") or [])[:400]))
                    for _ in range(8):
                        time.sleep(1.0)
                        got = json.loads(dashpin.run_js(url, SEMO_JS) or "{}")
                        if got.get("n") or got.get("owned"):
                            break
                if not got.get("ok"):
                    LOG("Steam emoticons: Steam's list isn't reachable right now (%s)" % (str(got)[:120] if got else "no answer"))
                    self.semo_t = time.time() - 20           # (try again shortly)
                    return
                seen, names = set(), []
                for e in sorted(got.get("l") or [], key=lambda e: -(e.get("r") or 0)):   # most recently used first
                    n = str(e.get("n") or "").strip(":").strip()
                    if n and n not in seen and len(n) < 64:
                        seen.add(n)
                        names.append(n)
                LOG("Steam emoticons: %d (list %s, owned %s, name from %s of %s; one looks like %s; owned one: %s)" % (
                    len(names), got.get("n"), got.get("owned"), got.get("key"), ",".join(got.get("keys") or [])[:200],
                    got.get("sample"), got.get("osample")))
                if tuple(names) != self.st.get("semo"):
                    self.st["semo"] = tuple(names)
                    self.dirty = True
                os.makedirs(SEMO_DIR, exist_ok=True)
                import urllib.request
                for i, n in enumerate(names):
                    p = semo_path(n)
                    if os.path.exists(p):
                        continue
                    try:
                        with urllib.request.urlopen(SEMO_URL % n, timeout=8) as r:
                            data = r.read(512 * 1024)
                        with open(p + ".tmp", "wb") as f:
                            f.write(data)
                        os.replace(p + ".tmp", p)
                    except Exception as ex:
                        if i < 3:
                            LOG("Steam emoticon picture %s: %s" % (n, ex))
                        continue
                    if i % 8 == 7 or i == len(names) - 1:   # (show them in batches, not one redraw each)
                        self.st["semo_gen"] = self.st.get("semo_gen", 0) + 1
                        self.dirty = True
                self.st["semo_gen"] = self.st.get("semo_gen", 0) + 1
                self.dirty = True
            except Exception as ex:
                LOG("Steam emoticons: couldn't get them:", ex)
            finally:
                self.semo_busy = False
        threading.Thread(target=work, daemon=True).start()

    def type_emoji(self, e):
        self.type_text(e)
        rec = [x for x in self.conf.get("emoji_recent", []) if self.emo_key(x) != self.emo_key(e)]
        self.conf["emoji_recent"] = ([e] + rec)[:30]
        save_conf(self.conf)

    def esearch_press(self, k):
        """Keys while searching emoji. True if handled here."""
        a = k.get("act")
        if a and a.startswith("ime:"):
            what = a[4:]
            if what == "raw":
                self.esearch_close()
            elif what == "more":
                found = self.esearch_results()
                self.es_page = (self.es_page + 1) % max(1, -(-len(found) // 7))
            else:
                found = self.esearch_results()
                i = self.es_page * 7 + int(what)
                if i < len(found):
                    self.type_emoji(found[i])
            return True
        if ("ch" in k or "sym" in k or "ins" in k) and not k.get("emoji"):
            c = self.char_for(k) or ""
            if c.isascii() and (c.isalnum() or c in "-' "):
                self.esq = (self.esq + c.lower())[:30]
                self.es_page = 0
            elif not c.isascii():
                self.flash("Emoji search uses English names: switch to an English keyboard to search")
            if self.st["shift"] and not self.st["caps"]:
                self.st["shift"] = False
                self.dirty = True
            return True
        if a == "back":
            if self.esq:
                self.esq, self.es_page = self.esq[:-1], 0
            else:
                self.esearch_close()
            return True
        if a == "space":
            if self.esq and not self.esq.endswith(" "):
                self.esq += " "
            return True
        if a == "enter":
            found = self.esearch_results()
            if found:
                self.type_emoji(found[0])
            return True
        if a in ("shift", "caps", "bubble", "sound", "panel", "curve", "noop"):
            return False
        self.esearch_close()           # anything else ends the search (and does what it does)
        return False

    # ---- Japanese / Chinese / Korean conversion
    NEUTRAL_ACTS = {"shift", "caps", "bubble", "sound", "panel", "curve", "words", "swipe", "eyes", "noop", "settings", "p123",
                    "psym", "abc", "emoji", "langs", "fmts", "numlock", "fn", "recenter", "alt"}

    def composer(self):
        """The converter for the current language (None for languages typed directly)."""
        lang = LANG.get(self.st.get("lang"))
        kind = lang.get("ime")
        if not kind or not IME.available(kind):
            return None
        if self.comp is None or self.comp_lang != lang["code"]:
            if self.comp is not None and not self.comp.empty():
                self.ime_commit_all()
            self.comp = IME.Composer("pinyin" if kind == "pinyin-s" else kind, simplified=kind == "pinyin-s")
            if lang.get("romaji"):
                self.comp.romaji = LANG.Romaji()
            self.comp_lang = lang["code"]
            self.ime_changed()
            threading.Thread(target=self.comp.warm, daemon=True).start()
        return self.comp

    def ime_changed(self):
        self.ime_sel, self.ime_page = -1, 0

    def ime_after_char(self):
        st = self.st
        if st["shift"]:
            if self.shift_held():
                self.shift_typed = True
            else:
                st["shift"] = False
                self.dirty = True

    def ime_press(self, k, comp, mods):
        """Keys while typing a converted language. True if handled here (nothing else to do)."""
        a = k.get("act")
        if a and a.startswith("ime:"):
            self.ime_pick(a[4:])
            return True
        if mods:
            self.ime_commit_all()
            return False
        if "ch" in k or "sym" in k or "ins" in k:
            if k.get("emoji"):
                self.ime_commit_all()
                return False
            c = self.char_for(k)
            if not c:
                return False
            kind = comp.kind
            if kind == "ja":
                c = LANG.JA_PUNCT.get(c, c)  # 、。？！「」ー
            if kind in ("ja", "zhuyin") and self.ime_sel >= 0 and not (kind == "zhuyin" and c in IME.TONES):
                self.ime_take(self.ime_sel)  # typing on after picking a conversion with Space: that one is sent
            if comp.add(c):
                self.ime_changed()
            else:
                if not comp.empty():
                    self.ime_commit_all()
                if kind in ("zhuyin", "pinyin", "cangjie", "quick"):
                    c = LANG.ZH_PUNCT.get(c, c)
                self.type_text(c)
            self.last_char = ""
            self.ime_after_char()
            return True
        if a == "back":
            if comp.empty():
                return False
            comp.back()
            self.ime_changed()
            return True
        if a in ("dakuten", "small", "flickmod"):
            fn = {"dakuten": LANG.dakuten, "small": LANG.small, "flickmod": LANG.flick_mod}[a]
            if not comp.empty():
                if comp.change_last(fn):
                    self.ime_changed()
                return True
            return False
        if a == "space":
            if comp.empty():
                return False
            kind = comp.kind
            if kind == "zhuyin" and comp.wants_space():
                comp.add(" ")  # the 1st tone
                self.ime_changed()
            elif kind in ("ja", "zhuyin"):  # Space: next way to write it (Enter sends it)
                cands = comp.candidates()
                if cands:
                    self.ime_sel = (self.ime_sel + 1) % len(cands)
                    self.ime_page = self.ime_sel // 4
            elif kind in ("ko", "vi"):
                self.ime_commit_all()
                self.type_text(" ")
            else:  # Pinyin / Cangjie / Quick: Space sends the first (or chosen) one
                self.ime_take(max(0, self.ime_sel))
            return True
        if a == "enter":
            if comp.empty():
                return False
            if self.ime_sel >= 0 or comp.kind in ("zhuyin", "cangjie", "quick"):
                self.ime_take(max(0, self.ime_sel))
                if comp.kind == "zhuyin":
                    self.ime_commit_all()
            else:  # Japanese kana, Pinyin letters, Hangul: as typed
                self.type_text(comp.raw())
                self.ime_changed()
            return True
        if a in self.NEUTRAL_ACTS or (a and a.startswith(("ecat:", "epage:", "fmt:", "lay-", "lpage:", "lgroup:", "lback"))):
            return False
        if not comp.empty():  # anything else (Tab, arrows, another language...): send what's waiting first
            self.ime_commit_all()
        return False

    def sync_preedit(self):
        """Japanese / Chinese being typed into one of Steam's boxes: what's typed so far shows in the box live."""
        stream = getattr(self.vk, "stream", None) if self.vk else None
        if not isinstance(stream, SteamUIText):
            return
        comp = self.comp
        want = comp.text() if comp is not None and not comp.empty() and LANG.get(self.st.get("lang")).get("ime") else ""
        now = (id(stream), want)
        last = getattr(self, "pre_sent", (id(stream), ""))
        if last[0] != id(stream):
            last = (id(stream), "")   # (another box: nothing of ours in it yet)
        if now != last:
            self.pre_sent = now
            self.vk.call(stream.preedit, want)

    def ime_take(self, i, cands=None):
        comp = self.comp
        cands = cands if cands is not None else comp.candidates()
        if not (0 <= i < len(cands)):
            return
        text, used = cands[i]
        self.type_text(comp.take(text, used))
        self.ime_changed()

    def ime_commit_all(self):
        """Send everything that's waiting, written the chosen (or most likely) way."""
        comp = self.comp
        for _ in range(8):
            if comp is None or comp.empty():
                break
            cands = comp.candidates()
            if not cands:
                self.type_text(comp.raw())
                break
            self.ime_take(self.ime_sel if 0 <= self.ime_sel < len(cands) else 0, cands)
        self.ime_changed()

    def ime_pick(self, what):
        """A spot in the word bar was tapped."""
        comp = self.comp
        if comp is None or comp.empty():
            return
        if self.st["sounds"]:
            self.sounds.play("key")
        if what == "raw":
            self.type_text(comp.raw())
            self.ime_changed()
            return
        cands = self.ime_shown[1] if self.ime_shown and self.ime_shown[0] == comp.key() else comp.candidates()
        if what == "more":
            pages = max(1, -(-len(cands) // 4))
            self.ime_page = (self.ime_page + 1) % pages
            return
        self.ime_take(self.ime_page * 4 + int(what), cands)

    def ime_want(self):
        """What the word bar shows while typing a converted language."""
        comp = self.comp
        if comp is None or comp.empty():
            self.ime_shown = None
            return ("ime", "", (), -1, False)
        key = comp.key()
        if comp.ready():
            cands = comp.candidates()
            self.ime_shown = (key, cands)
        elif not self.ime_busy and comp.kind not in ("ko", "vi"):
            self.ime_busy = True

            def job():
                try:
                    comp.candidates()
                finally:
                    self.ime_busy = False
            threading.Thread(target=job, daemon=True).start()
        cands = self.ime_shown[1] if self.ime_shown else []
        pages = max(1, -(-len(cands) // 4))
        page = min(self.ime_page, pages - 1)
        shown = tuple(t for t, _ in cands[page * 4:page * 4 + 4])
        sel = self.ime_sel - page * 4 if self.ime_sel >= 0 and self.ime_sel // 4 == page else -1
        return ("ime", comp.text(), shown, sel, pages > 1)

    # ---- swipe typing
    def swipe_lang(self):
        lang = LANG.get(self.st.get("lang"))
        if lang.get("kana") or lang.get("romaji") or lang.get("ime"):
            return None
        code = lang["code"].split("-")[0]
        return code if self.decoder and self.decoder.available(code) else None

    def load_look(self):
        """Colours, backdrop and controller clicks from Settings > Keyboard (checked once a second, only re-read
        when the file changed)."""
        path = os.path.join(CONF_DIR, "prefs.json")
        try:
            mt = os.path.getmtime(path)
        except OSError:
            mt = 0
        if mt == getattr(self, "look_mt", None):
            return
        self.look_mt = mt
        try:
            with open(path) as f:
                p = json.load(f)
        except Exception:
            p = {}
        self.haptics = bool(p.get("kb_haptics", False))
        self.hold_shift = p.get("kb_hold", "repeat") == "shift"
        # key sound (Settings > Keyboard): Light, Deep (the original) or Off. Someone who'd muted it with the old
        # speaker button keeps it off until they pick a sound
        mode = p.get("kb_sound") or ("deep" if self.conf.get("sounds", True) else "off")   # (Original unless you pick another)
        on = mode != "off"
        style = "deep" if mode == "deep" else "light"
        vol = max(0.0, min(1.0, float(self.conf.get("volume", 0.5) or 0.5)))
        if style != getattr(self.sounds, "style", "light"):
            self.sounds.set_volume(vol, style)
        if on != self.st.get("sounds"):
            self.st["sounds"] = on
            self.dirty = True
            try:
                if on and self.visible:
                    self.sounds.open_async()
                elif not on:
                    self.sounds.close()
            except Exception:
                pass
        if (mode, vol) != getattr(self, "sound_said", None):
            self.sound_said = (mode, vol)
            LOG("key sound:", mode)
        # word suggestions and the key layout (Settings > Keyboard; they used to be buttons on the keyboard, so until
        # they're set there, what you'd picked with those buttons stays)
        words = bool(p["kb_words"]) if "kb_words" in p else bool(self.conf.get("words", False))
        if words != bool(self.st.get("words")):
            self.st["words"] = self.conf["words"] = words
            save_conf(self.conf)
            self.word_list, self.cur_word = [], ""
            self.dirty = True
            LOG("word suggestions:", "on" if words else "off")
        prev = bool(p["kb_preview"]) if "kb_preview" in p else bool(self.conf.get("bubble", True))   # (Settings > Keyboard)
        if prev != bool(self.st.get("bubble", True)):
            self.st["bubble"] = self.conf["bubble"] = prev
            save_conf(self.conf)
            self.place_highlight()
            LOG("key preview:", "on" if prev else "off")
        code = p.get("kb_lang") or self.conf.get("lang", "en-US")   # (until it's set there: what you'd picked on the keyboard)
        if LANG.get(code).get("code") == code and code != self.st.get("lang"):
            self.st["lang"] = self.conf["lang"] = code
            self.st["page"], self.st["alt"] = "abc", -1
            self.renderer.set_cjk(code)
            self.romaji.reset()
            save_conf(self.conf)
            self.dirty = True
            LOG("language:", code)
        fmt = p.get("kb_fmt") or self.conf.get("fmt", "default")
        if fmt not in LANG.FORMAT_ORDER:
            fmt = "default"
        if fmt != self.st.get("fmt", "default"):
            self.st["fmt"] = self.conf["fmt"] = fmt
            self.st["alt"] = -1
            if self.st.get("page") == "fmt":
                self.st["page"] = "abc"
            save_conf(self.conf)
            self.dirty = True
            LOG("key layout:", fmt)
        if self.st.get("autoopen") is not False:   # (opening by itself for text boxes: taken out, it didn't work)
            self.st["autoopen"] = False
            self.set_focus_watch(False)
            try:   # the desktop's accessibility reporting back off, if we were the ones who turned it on
                import a11yfocus
                if os.path.exists(a11yfocus.MARK):
                    threading.Thread(target=a11yfocus.turn_off, daemon=True).start()
            except Exception:
                pass
        self.st["padbuttons"] = bool(p.get("kb_padbuttons", True))
        # trackpad click force, for controllers whose pads only say how hard they're pressed
        press = p.get("kb_padpress", "light")
        self.pad_press_at = {"light": 2000, "normal": 3500, "firm": 6000}.get(press, 2000)
        # (how far toward the pad's own click a press has to go: the pad's own scale, learnt from its clicks)
        self.pad_press_frac = {"light": 0.3, "normal": 0.55, "firm": 0.8}.get(press, 0.3)
        if getattr(self, "pads", None) is not None:
            self.pads.press_at = self.pad_press_at
            self.pads.press_frac = self.pad_press_frac
        pad = p.get("kb_gamepad", "pads")   # game controllers: their trackpads on this keyboard (or Steam's keyboard)
        pad = {True: "steam", False: "off"}.get(pad, pad) if isinstance(pad, bool) else pad
        pad = pad if pad in ("pads", "split", "steam", "off") else "pads"
        if pad != self.st.get("padkb", "pads"):
            self.st["padkb"] = pad
            LOG("Steam Controller:", pad)
        tips = bool(p.get("kb_tips", True))  # the little labels over the top bar's buttons
        if tips != self.st.get("tips", True):
            self.st["tips"] = tips
            LOG("button labels:", "on" if tips else "off")
        br = "laptop" if p.get("kb_bottom") == "laptop" else "default"   # (Bottom row, Settings > Keyboard)
        if br != self.st.get("bottomrow", "default"):
            self.st["bottomrow"] = br
            self.dirty = True
            LOG("bottom row:", br)
        bp = p.get("kb_bar") if p.get("kb_bar") in ("bottom", "off") else "top"
        if bp != self.st.get("barpos", "top"):
            self.st["barpos"] = bp
            LOG("top bar:", {"bottom": "below the keys", "off": "off"}.get(bp, "above the keys"))
            self.dirty = True
        top = bool(p.get("kb_ontop", False))
        if top != getattr(self, "on_top", False):
            self.on_top = top
            LOG("always on top:", "on" if top else "off")
            self.resort()
        self.stream_mode = p.get("kb_stream", "steam")
        changed = set_theme(p.get("kb_theme", "steam"))
        op = max(0.0, min(1.0, float(p.get("kb_backdrop", 100)) / 100.0))
        if abs(op - self.conf.get("panel_opacity", 1.0)) > 1e-3:
            self.conf["panel_opacity"] = op
            changed = True
        if changed:
            LOG("look:", p.get("kb_theme", "steam"), "backdrop %d%%" % round(op * 100))
            self.look_gen = getattr(self, "look_gen", 0) + 1
            try:
                with self.rlock:
                    self.rcache.clear()  # (pictures kept from the old colours: gone)
            except Exception:
                pass
            self.bubble_tex = {}
            self.wing_key = None      # the number pad and the word bar are drawn again in the new colours too
            self.words_tex = None
            self.dirty = True
            try:
                self.place_highlight()
            except Exception:
                pass
        self.aim_prefs(p)   # Fade when not aiming, and how visible it is then

    def click_feel(self, dev):
        """A short tick in the controller that typed (Settings > Keyboard > Controller click)."""
        if not getattr(self, "haptics", False) or dev is None:
            return
        try:
            self.system.triggerHapticPulse(dev, 0, 900)
        except Exception:
            pass

    def toggle_eyes(self):
        """The eye button: typing by look + pinch on or off. If eye control is off altogether, this turns it on
        (Look and pinch); turning it off here only stops it on the keyboard."""
        path = os.path.join(CONF_DIR, "prefs.json")
        try:
            with open(path) as f:
                p = json.load(f)
        except Exception:
            p = {}
        try:
            import bfmode
            live = bfmode.apply(p)
        except ImportError:
            live = p
        on = (bool(live.get("gaze_ui")) and live.get("gaze_kb", True) is not False) or bool(live.get("gaze_glow")) \
            or bool(live.get("gaze_type"))
        if on:
            p["gaze_kb"] = False
            p["gaze_glow"] = p["gaze_type"] = False
            self.flash("Eyes off for the keyboard")
        else:
            p["gaze_kb"] = True
            if not live.get("gaze_ui"):
                p["ctl_mode"] = "look_pinch"
                self.flash("Eyes on: look at a key and pinch (put the controllers down)")
            else:
                self.flash("Eyes on for the keyboard")
        try:
            with open(path + ".tmp", "w") as f:
                json.dump(p, f)
            os.replace(path + ".tmp", path)
        except OSError:
            pass
        self.gaze.load()
        self.st["eyes"] = not on

    def swipe_ready(self, k):
        st = self.st
        return (st.get("swipe") and "ch" in k and st["page"] == "abc" and st.get("alt", -1) < 0
                and not (self.ctrl or self.alt or self.meta) and self.swipe_lang() is not None)

    def finish_swipe(self, slot):
        sw = self.swipes.pop(slot, None)
        self.trail_dirty = True
        if not sw or sw.get("held"):
            return  # (a held, repeating letter: already typed)
        keys = {}
        widths = []
        for k, (x0, y0, x1, y1) in self.items:
            if "ch" in k and k.get("panel") != "wing":
                keys[k["ch"]] = ((x0 + x1) / 2, (y0 + y1) / 2)
                widths.append(x1 - x0)
        kw = sum(widths) / max(1, len(widths))
        pts = sw["pts"]
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
        start = self.items[sw["start"]][0] if sw["start"] < len(self.items) else None
        # a tap where the laser drifted a little (hand shake, pulling the trigger) is still a tap: only a real
        # sweep across the keys counts as a swipe, so a word is never typed when you meant one letter
        if len(sw["keys"]) < 2 or length < kw * 1.3 or (len(sw["keys"]) < 3 and length < kw * 2.0):
            if start and not sw.get("typed"):
                self.hpressed[slot] = time.time() + 0.09
                self.place_highlight(slot)
                self.press(start, quiet=True)  # (its click already played when you pressed)
            return  # a tap: just its letter
        lang2 = self.swipe_lang()
        if not lang2:  # the language was switched mid-swipe to one without swipe typing: count it as a tap
            if start and not sw.get("typed"):
                self.press(start, quiet=True)
            return
        with self.decode_lock:
            words = self.decoder.decode(lang2, pts, keys, kw) if self.decoder else []
        self.preview_word = ""
        if not words:
            self.flash("Didn't catch that word")
            return
        st = self.st
        shift, caps = sw.get("shift", st["shift"]), sw.get("caps", st["caps"])

        def shape(w):  # Shift / Caps Lock apply to swiped words too (as they were when the swipe began)
            if caps:
                return "".join(LANG.upper(c) for c in w)
            if shift:
                return LANG.upper(w[0]) + w[1:]
            return w
        words = [shape(w) for w in words]
        if sw.get("typed") and self.vk:
            self.vk.tap(KEY["BACKSPACE"])  # (only if its first letter was typed already)
        # a word typed by tapping just before ("I", "a", "OK"): a space between it and the swiped one
        lead = " " if sw.get("after") and not sw.get("typed") else ""
        self.type_text(lead + words[0] + " ")
        self.after_letter = False
        self.last_swipe, self.auto_space = words[0] + " ", True
        if st["shift"]:
            if self.shift_held():
                self.shift_typed = True
            else:
                st["shift"] = False
        # with the word bar on, the next best guesses wait there in case it picked the wrong one
        self.word_list, self.word_mode, self.word_sel, self.cur_word = words[:3], "swipe", 0, ""
        self.dirty = True
        self.last_press = time.time()

    def pick_suggestion(self, i):
        """A word in the word bar was tapped."""
        wl = self.word_list
        if not self.st.get("words") or not (0 <= i < len(wl)):
            return
        if self.st["sounds"]:
            self.sounds.play("key")
        new = wl[i]
        if self.word_mode == "swipe":  # swap the swiped word for this one
            if not self.last_swipe or i == self.word_sel:
                return
            self.replace_typed(len(self.last_swipe), new + " ")
            self.last_swipe, self.word_sel, self.auto_space = new + " ", i, True
        else:  # finish the word being typed with this one
            self.replace_typed(len(self.cur_word), new + " ")
            self.last_swipe, self.auto_space = new + " ", True
            self.word_list, self.cur_word = [], ""
        if self.st["shift"] and not self.st["caps"]:
            self.st["shift"] = False
            self.dirty = True

    def maybe_welcome(self):
        """Just installed: the welcome window (setup and a quick tour), once, when SteamVR is up."""
        if getattr(self, "welcome_started", False) or not os.path.exists(os.path.join(CONF_DIR, "welcome-pending")) \
                or not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bfwelcome.py")):
            return
        self.welcome_started = True
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            log = open(os.path.join(CONF_DIR, "welcome.log"), "a")
            subprocess.Popen([sys.executable, os.path.join(here, "bfwelcome.py")], cwd=here, stdout=log, stderr=log,
                             stdin=subprocess.DEVNULL, start_new_session=True)
            LOG("welcome window opened")
        except Exception as ex:
            LOG("couldn't open the welcome window:", ex)

    def open_settings(self):
        """Opens BetterFrame Settings (or brings it back in front of you if it's already open)."""
        if time.time() - getattr(self, "settings_opened", 0) < 2:
            return
        self.settings_opened = time.time()
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            log = open(os.path.join(CONF_DIR, "settings.log"), "a")
            subprocess.Popen([sys.executable, os.path.join(here, "bfpanel.py")], cwd=here, stdout=log, stderr=log,
                             stdin=subprocess.DEVNULL, start_new_session=True)
            LOG("settings opened")
        except Exception as ex:
            LOG("couldn't open settings:", ex)
            self.flash("Couldn't open Settings")

    def note_word(self, k):
        """Keep track of the word being typed, for the word bar's suggestions."""
        if not self.st.get("words"):
            return
        a = k.get("act")
        c = self.char_for(k) if "ch" in k else None
        if c and len(c) == 1 and (c.isalpha() or c == "'") and not (self.ctrl or self.alt or self.meta):
            self.cur_word += c
        elif a == "back":
            self.cur_word = self.cur_word[:-1]
        elif a in ("shift", "caps", "langs", "fmts", "bubble", "sound", "panel", "curve", "words", "swipe", "eyes"):
            return  # (doesn't end the word)
        else:
            self.cur_word = ""
        self.word_mode, self.word_sel = "type", -1
        self.words_due = True

    def completions(self, lang2, typed, n=2):
        """The most common words that start with what's been typed so far."""
        import bisect
        import heapq
        idx = self.comp_index.get(lang2)
        if idx is None:
            ws = self.decoder.words(lang2) if self.decoder else []
            idx = sorted((w.lower(), r, w) for r, w in enumerate(ws))
            self.comp_index = {lang2: idx}
        p = typed.lower()
        lo = bisect.bisect_left(idx, (p,))
        hi = bisect.bisect_left(idx, (p + "\U0010ffff",))
        best = heapq.nsmallest(n + 1, (e for e in idx[lo:hi] if len(e[0]) > len(p)), key=lambda e: e[1])
        out = []
        for _, _, w in best:
            if len(typed) > 1 and typed.isupper():
                w = LANG.upper(w)
            elif typed[:1].isupper():
                w = LANG.upper(w[0]) + w[1:]
            if w != typed and w not in out:
                out.append(w)
        return out[:n]

    def swipe_keys(self):
        keys, widths = {}, []
        for k, (x0, y0, x1, y1) in self.items:
            if "ch" in k and k.get("panel") != "wing":
                keys[k["ch"]] = ((x0 + x1) / 2, (y0 + y1) / 2)
                widths.append(x1 - x0)
        return keys, sum(widths) / max(1, len(widths))

    def warm_swipe(self):
        """Get swipe typing's word list ready in the background when the keyboard opens, so the first swipe
        doesn't pause while it loads."""
        if not (self.decoder and self.st.get("swipe")):
            return
        lang2 = self.swipe_lang()
        if not lang2:
            return
        keys, _ = self.swipe_keys()

        def job():
            try:
                with self.decode_lock:
                    self.decoder._index(lang2, keys)
            except Exception:
                pass
        threading.Thread(target=job, daemon=True).start()

    def preview_job(self, lang2, pts, keys, kw, shift, caps):
        try:
            with self.decode_lock:
                ws = self.decoder.decode(lang2, pts, keys, kw, n=1)
            w = ws[0] if ws else ""
            if w and caps:
                w = "".join(LANG.upper(c) for c in w)
            elif w and shift:
                w = LANG.upper(w[0]) + w[1:]
            if self.preview_gen == self.swipe_gen:
                self.preview_word = w
        except Exception:
            pass
        finally:
            self.preview_busy = False

    def update_words(self):
        """The word bar above the keys (when it's on): the word your swipe is spelling as you go, the other
        guesses after a swipe, and the words you might be typing. Its own little overlay, so changing a word
        never redraws the keyboard."""
        st = self.st
        if st.get("esearch"):
            if getattr(self, "_boxes_for", None) is not self.items:
                self._boxes_for = self.items
                self._boxes = [b for k, b in self.items if str(k.get("act", "")).startswith(("sugg:", "ime:"))]
            if len(self._boxes) == len(EMOJI_CELLS):
                on = self.visible and not st["mic"]
                self.paint_words(self.esearch_want() if on else None, self._boxes, time.time(),
                                 maker=lambda w, tw, th, f, c: emoji_bar_picture(w, tw, th, self.renderer, c))
                return
        imel = bool(LANG.get(st.get("lang")).get("ime")) and self.composer() is not None
        if not st.get("words") and not imel and not self.words_shown and not self.preview_word and not getattr(self, "was_swiping", False):
            return  # word bar off: nothing to do (this runs every pass of the main loop)
        if getattr(self, "_boxes_for", None) is not self.items:   # where the word bar sits: only changes with the layout
            self._boxes_for = self.items
            self._boxes = [b for k, b in self.items if str(k.get("act", "")).startswith(("sugg:", "ime:"))]
        boxes = self._boxes
        if imel and boxes and len(boxes) == len(IME_CELLS):  # Japanese / Chinese / Korean
            on = self.visible and not st["mic"]
            want = self.ime_want() if on else None
            self.paint_words(want, boxes, now=time.time(), maker=ime_picture)
            return
        on = st.get("words") and self.visible and boxes and not st["mic"]
        now = time.time()
        sw = next(iter(self.swipes.values()), None)
        swiping = bool(on and sw and len(sw["pts"]) > 1 and self.real_swipe(sw))
        if swiping:
            if not self.preview_busy and now - self.preview_t > 0.12 and len(sw["pts"]) != self.preview_n:
                lang2 = self.swipe_lang()
                if lang2:
                    keys, kw = self.swipe_keys()
                    self.preview_busy, self.preview_t, self.preview_n = True, now, len(sw["pts"])
                    self.preview_gen = self.swipe_gen
                    threading.Thread(target=self.preview_job, daemon=True,
                                     args=(lang2, list(sw["pts"]), keys, kw, sw.get("shift", st["shift"]),
                                           sw.get("caps", st["caps"]))).start()
        elif self.preview_word or getattr(self, "was_swiping", False):
            self.preview_word = ""
            self.swipe_gen += 1
        self.was_swiping = swiping
        if on and self.words_due and self.word_mode == "type":
            self.words_due = False
            lang2 = self.swipe_lang()
            comps = self.completions(lang2, self.cur_word) if (lang2 and self.cur_word) else []
            self.word_list = ([self.cur_word] + comps) if self.cur_word else []
        if swiping:
            want = ("preview", self.preview_word)
        elif on:
            want = ("words", tuple(self.word_list), self.word_sel, self.word_mode)
        else:
            want = None
        self.paint_words(want, boxes, now)

    def paint_words(self, want, boxes, now, maker=None):
        """Put the word bar's picture up (or take it down)."""
        maker = maker or words_picture
        h = self.words_ov
        if want is None:
            if h and self.words_shown:
                self.ov.hideOverlay(h)
                self.words_shown = False
            return
        x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
        x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
        tw = WORDS_W
        th = max(8, int(round(tw * (y1 - y0) / max(1, x1 - x0))))
        try:
            if h is None:
                h = self.words_ov = self.ov.createOverlay("betterframe.keyboard.words", "BetterFrame Keyboard word bar")
                self.set_sort(h, 10)
                self.words_tex = self.words_geom = None
            if self.words_tex != (want, th):
                if now - self.words_sent < 0.05:
                    return  # a moment later (at most 20 pictures a second)
                self.renderer.set_cjk(self.st.get("lang"))
                self.upload_raw(h, maker(want, tw, th, self.renderer.font, [((b[0] - x0) / (x1 - x0), (b[2] - x0) / (x1 - x0)) for b in boxes]))
                self.words_tex, self.words_sent = (want, th), now
            s = self.width_m / self.img_size[0]
            cr = self.curve_r()
            geom = (tuple(round(v, 5) for v in self.pos), self.yaw, self.pitch, round(self.width_m, 5), cr, x0, y0, x1, y1, self.img_size)
            if self.words_geom != geom:
                wm = (x1 - x0) * s
                self.ov.setOverlayWidthInMeters(h, wm)
                try:
                    self.ov.setOverlayCurvature(h, min(0.9, wm / (2 * math.pi * cr)) if cr else 0.0)
                except Exception:
                    pass
                p, R = self.local_point("main", (x0 + x1) / 2, (y0 + y1) / 2, 0.0)
                Rm = self.R()
                p = [p[i] + Rm[i][2] * 0.003 for i in range(3)]
                self.ov.setOverlayTransformAbsolute(h, self.vr.TrackingUniverseStanding, make_matrix(self.vr, p, R if not cr else Rm))
                self.words_geom = geom
            if not self.words_shown:
                self.ov.showOverlay(h)
                self.words_shown = True
        except Exception as ex:  # never let the word bar cost a key press
            self.words_tex = self.words_geom = None
            self.report_error(ex)

    def update_popup(self):
        """A small rounded pop-up centred just above the keyboard: short messages ("Added to Favorites") and voice
        typing ("Listening…", then the words as they're heard, growing as you speak). Its own little overlay, so the
        keyboard itself is never redrawn for it."""
        msg = getattr(self, "pop_msg", "") if time.time() <= getattr(self, "msg_until", 0) else ""
        live = getattr(self, "pop_live", "")
        mic = bool(self.st.get("mic"))
        text = msg or live or ("Listening…" if mic else "")
        h = getattr(self, "pop_ov", None)
        if not text or not self.visible or not self.items:
            if h is not None and getattr(self, "pop_shown", False):
                self.ov.hideOverlay(h)
                self.pop_shown = False
            return
        try:
            if h is None:
                h = self.pop_ov = self.ov.createOverlay("betterframe.keyboard.popup", "BetterFrame Keyboard message")
                self.set_sort(h, 14)
                self.pop_tex = self.pop_geom = None
            uph = self.renderer.metrics.get("uph", 60)
            ph = uph * 0.62                                   # its height, in the keyboard's own pixels
            want = (text, mic and not msg, bool(live) and not msg, self.img_size[0], getattr(self, "look_gen", 0))
            now = time.time()
            if getattr(self, "pop_tex", None) != want:
                if now - getattr(self, "pop_sent", 0) < 0.08:
                    return   # (a moment later: at most about 12 pictures a second)
                img = self.renderer.popup(text, rec=mic and not msg, live=bool(live) and not msg,
                                          max_w=self.img_size[0] * 0.82 / ph)
                if not self.upload_raw(h, img, soft=True):
                    return
                self.pop_tex, self.pop_sent, self.pop_aspect = want, now, img.width / img.height
                self.pop_geom = None
            s = self.width_m / self.img_size[0]
            top = min(b[1] for _, b in self.items)
            geom = (tuple(round(v, 4) for v in self.pos), self.yaw, self.pitch, round(self.width_m, 4), top, self.img_size,
                    self.conf.get("roll", 0.0), self.pop_aspect)
            if self.pop_geom != geom:
                self.ov.setOverlayWidthInMeters(h, ph * self.pop_aspect * s)
                p, R = self.local_point("main", self.img_size[0] / 2, top - ph * 0.95, 0.006)
                self.ov.setOverlayTransformAbsolute(h, self.vr.TrackingUniverseStanding, make_matrix(self.vr, p, R))
                self.pop_geom = geom
            if not getattr(self, "pop_shown", False):
                self.ov.showOverlay(h)
                self.pop_shown = True
        except Exception as ex:   # (never let a message cost a key press)
            self.pop_tex = self.pop_geom = None
            self.report_error(ex)

    def fresh_trail(self, why="SteamVR stopped taking swipe-line pictures"):
        """Throw away the swipe line's two overlays; new ones are made the next time the line is drawn."""
        LOG(why + ": making fresh swipe-line overlays")
        for h in getattr(self, "trail_ovs", None) or []:
            try:
                self.ov.hideOverlay(h)
                self.ov.destroyOverlay(h)
            except Exception:
                pass
        self.trail_ovs, self.trail_hide, self.trail_shown, self.trail_sent = None, None, 0, 0
        self.trail_gen = getattr(self, "trail_gen", 0) + 1

    def update_trail(self):
        """The glowing line behind a swipe: a small overlay covering just the part of the keyboard the swipe
        has crossed, redrawn up to 60 times a second while swiping (a few KB each time), so it keeps up smoothly."""
        if not getattr(self, "trail_dirty", False):
            return
        now = time.time()
        # the newest swipe (if a press from the other hand was left behind, it never hides this one's line)
        sw = max((v for v in self.swipes.values() if not v.get("held")),
                 key=lambda v: (v.get("trail_t") or [v["t"]])[-1], default=None)
        pts = (sw.get("trail") or sw["pts"]) if sw and len(sw["pts"]) > 1 and self.draw_swipe(sw) else []
        # (a tap, even with a little wobble, draws no line: nothing extra for SteamVR to do while you type)
        if pts and sw.get("trail_t"):  # only the last moment of the swipe: a short tail behind your laser...
            cut = next((i for i, t in enumerate(sw["trail_t"]) if now - t < 0.35), len(pts) - 2)
            # ...but never shorter than about two keys, so pausing on a letter doesn't make the line vanish
            need, got, i = self.key_w() * 2.0, 0.0, len(pts) - 1
            while i > 0 and got < need:
                got += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
                i -= 1
            cut = min(cut, i)
            pts = pts[max(0, min(cut, len(pts) - 2)):]
        rate = 12 if now < getattr(self, "trail_slow", 0) else 30   # (fewer while SteamVR is slow to take them)
        if pts and now - getattr(self, "trail_t", 0) < 1 / rate:  # up to 36 times a second: smooth, not jumpy
            return  # keep it dirty: drawn on a later frame
        self.trail_dirty, self.trail_t = False, now
        if not pts:
            for h in getattr(self, "trail_ovs", None) or []:
                self.ov.hideOverlay(h)
            self.trail_shown = 0
            # SteamVR can also quietly stop showing a line overlay's new pictures without refusing them, so after a
            # good amount of swiping the two are swapped for fresh ones anyway, between swipes, where it can't be seen
            if getattr(self, "trail_reconnect", False):
                self.trail_reconnect = False
                self.reconnect("SteamVR stopped taking swipe-line pictures")
                return
            if getattr(self, "trail_sent", 0) >= 400:
                self.trail_sent = 0
                self.fresh_trail("routine swap after a lot of swiping")
            return
        # two copies of the line, taking turns: the new picture goes on the hidden one, which is shown before
        # the other is hidden, so the line never blinks out between pictures
        if not getattr(self, "trail_ovs", None):
            self.trail_ovs, self.trail_i, self.trail_geoms = [], 0, {}
            for n in range(2):
                h = self.ov.createOverlay("betterframe.keyboard.trail%d.%d" % (getattr(self, "trail_gen", 0), n),
                                          "BetterFrame Keyboard swipe trail")
                self.set_sort(h, 12)
                self.trail_ovs.append(h)
        import swipe as _sw
        line = _sw._resample(pts[-160:], min(40, max(8, len(pts))))
        for _ in range(2):  # round off the corners (Chaikin), so the line is one smooth curve
            sm = [line[0]]
            for (x0, y0), (x1, y1) in zip(line, line[1:]):
                sm += [(x0 * 0.75 + x1 * 0.25, y0 * 0.75 + y1 * 0.25), (x0 * 0.25 + x1 * 0.75, y0 * 0.25 + y1 * 0.75)]
            line = sm + [line[-1]]
        line[-1] = pts[-1]
        W, H = self.img_size
        box = trail_box(line, W, H, self.key_w())
        img = trail_picture_box(line, box)
        old = self.trail_ovs[self.trail_i]
        new = self.trail_ovs[1 - self.trail_i]
        try:
            if not self.upload_raw(new, img, soft=True):
                self.trail_dirty = True  # SteamVR is busy: draw it on a later frame
                return
            self.trail_fails = 0
            self.trail_sent = getattr(self, "trail_sent", 0) + 1
        except Exception:
            self.trail_dirty = True
            self.trail_t = time.time() + 0.1  # it refused this frame: try again in a moment, the swipe carries on
            # SteamVR keeps a little of every picture an overlay is sent, and after a lot of swiping it stops taking
            # new ones for the line (the keys, sent far less often, carry on): the line vanished for good. A few
            # refusals in a row: two brand-new line overlays, which SteamVR takes pictures for again
            self.trail_fails = getattr(self, "trail_fails", 0) + 1
            if self.trail_fails >= 3:
                self.trail_fails = 0
                if time.time() - getattr(self, "trail_fresh_t", 0) < 10:
                    self.trail_reconnect = True   # (fresh ones were refused too: done once this swipe ends)
                self.trail_fresh_t = time.time()
                self.fresh_trail()
            return
        # just over the part of the keyboard the line is on: sized, bent and placed to sit exactly on the keys there
        x0, y0, bw, bh, k = box
        bwm = self.width_m * bw / W
        cr = self.curve_r()
        geom = (round(bwm, 5), cr)
        if self.trail_geoms.get(new) != geom:
            self.trail_geoms[new] = geom
            self.ov.setOverlayWidthInMeters(new, bwm)
            try:
                self.ov.setOverlayCurvature(new, min(0.9, bwm / (2 * math.pi * cr)) if cr else 0.0)
            except Exception:
                pass
        p, Rm = self.local_point("main", x0 + bw / 2, y0 + bh / 2, 0.005)
        self.ov.setOverlayTransformAbsolute(new, self.vr.TrackingUniverseStanding, make_matrix(self.vr, p, Rm))
        self.set_sort(new, 12)
        self.set_sort(old, 11)
        self.ov.showOverlay(new)
        if self.trail_shown:
            self.trail_hide = (old, time.time() + 0.03)  # hide the older line once the new one is up
        self.trail_i = 1 - self.trail_i
        self.trail_shown = 1

    # ---- Japanese flick keypad
    def move_flick(self, slot, x, y):
        f = self.flicks[slot]
        x0, y0, x1, y1 = self.items[f["item"]][1]
        dx, dy = x - f["x"], y - f["y"]
        if math.hypot(dx, dy) < max(x1 - x0, y1 - y0) * 0.22:
            d = 0
        elif abs(dx) > abs(dy):
            d = 1 if dx < 0 else 3
        else:
            d = 2 if dy < 0 else 4
        if d >= len(self.items[f["item"]][0]["flick"]):
            d = 0  # this key has nothing that way
        if d != f["dir"]:
            f["dir"] = d
            self.show_flick_guide(slot)

    def finish_flick(self, slot):
        f = self.flicks.pop(slot, None)
        if self.flick_ov:
            try:
                self.ov.hideOverlay(self.flick_ov)
            except Exception:
                pass
        if not f or f["item"] >= len(self.items):
            return
        chars = self.items[f["item"]][0]["flick"]
        c = chars[f["dir"]] if f["dir"] < len(chars) else chars[0]
        self.press({"ch": c, "label": c})

    def show_flick_guide(self, slot):
        """The cross of choices around the key being flicked, with the one you'd get lit up."""
        f = self.flicks.get(slot)
        if not f or not self.visible:
            return
        try:
            k = self.items[f["item"]][0]
            chars = k["flick"]
            if self.st["shift"] != self.st["caps"]:
                chars = "".join(LANG.upper(c) for c in chars)
            x0, y0, x1, y1 = self.items[f["item"]][1]
            cell = min(x1 - x0, y1 - y0) * 1.05
            if not self.flick_ov:
                self.flick_ov = self.ov.createOverlay("betterframe.keyboard.flick", "BetterFrame Keyboard flick guide")
                self.set_sort(self.flick_ov, 13)
            want = (chars, f["dir"])
            if self.flick_pic != want:
                if not self.upload_raw(self.flick_ov, self.renderer.flick_guide(chars, f["dir"]), soft=True):
                    return
                self.flick_pic = want
            s = self.width_m / self.img_size[0]
            self.ov.setOverlayWidthInMeters(self.flick_ov, cell * 3 * s)
            p, R = self.local_point(k.get("panel", "main"), (x0 + x1) / 2, (y0 + y1) / 2, 0.02)
            self.ov.setOverlayTransformAbsolute(self.flick_ov, self.vr.TrackingUniverseStanding, make_matrix(self.vr, p, R))
            self.ov.showOverlay(self.flick_ov)
        except Exception as ex:
            self.report_error(ex)

    def key_w(self):
        ws = [x1 - x0 for k, (x0, y0, x1, y1) in self.items if "ch" in k]
        return (sum(ws) / len(ws)) if ws else 60

    def held_still(self, sw, item):
        """Is this press still sitting on its first key (so holding it repeats the letter)?"""
        if item >= len(self.items):
            return False
        x0, y0, x1, y1 = self.items[item][1]
        pad = (x1 - x0) * 0.15
        return all(x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad for x, y in sw["pts"][-12:]) and \
            len(sw.get("keys", ())) < 2

    def draw_swipe(self, sw):
        """Show the line as soon as the laser is clearly sweeping from one key to the next (a little sooner
        than it counts as a swipe for typing, so slow or short swipes show their line straight away)."""
        if self.real_swipe(sw):
            return True
        if len(sw.get("keys", ())) < 2:
            return False
        p = sw["pts"]
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(p, p[1:])) >= self.key_w() * 0.8

    def real_swipe(self, sw):
        """Has this press become a real swipe (moved across a few keys), rather than a tap?"""
        if sw.get("real"):
            return True
        ws = [x1 - x0 for k, (x0, y0, x1, y1) in self.items if "ch" in k]
        kw = (sum(ws) / len(ws)) if ws else 60
        p = sw["pts"]
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(p, p[1:]))
        if len(sw.get("keys", ())) >= 2 and length >= kw * 1.3:
            sw["real"] = True
        return sw.get("real", False)

    def keep_in_sync(self):
        """SteamVR can hide overlays by itself (for example while the Steam menu opens or closes).
        A few times a second, make sure what you see matches what the keyboard thinks: if it should be
        open but SteamVR hid it, show it again straight away. Otherwise the next button press would
        'close' a keyboard you can't see."""
        now = time.time()
        if now - getattr(self, "last_sync", 0) < 0.25:
            return
        self.last_sync = now
        try:
            shown = bool(self.ov.isOverlayVisible(self.handle))
        except Exception:
            return
        if self.visible and not shown:
            LOG("keyboard was hidden by SteamVR, showing it again")
            if self.dirty:
                self.redraw()
            self.set_kb_transform()
            self.ov.showOverlay(self.handle)
            if self.wing_on:
                self.ov.showOverlay(self.wing)
        elif not self.visible and shown:
            for h in self.kbs:
                self.ov.hideOverlay(h)
            self.ov.hideOverlay(self.wing)

    def health(self):
        """Once a minute: how much the keyboard itself uses, and how busy the whole headset is.
        Makes it easy to tell from the log whether a slowdown is the keyboard or something else."""
        now = time.time()
        last = getattr(self, "health_at", None)
        if last is None:
            self.health_at, self.health_cpu = now, sum(os.times()[:2])
            return
        if now - last < 60:
            return
        cpu = sum(os.times()[:2])
        mine = (cpu - self.health_cpu) / (now - last) * 100
        self.health_at, self.health_cpu = now, cpu
        try:
            load = open("/proc/loadavg").read().split()[0]
            mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith(("MemAvailable", "MemTotal"))}
            free = "%.1f of %.1f GB free" % (mem["MemAvailable"] / 1e6, mem["MemTotal"] / 1e6)
        except Exception:
            load, free = "?", "?"
        LOG("health: keyboard %.1f%% CPU, headset load %s (%d cores), %s, %s, %d pictures sent (slowest %.0f ms), %.0f MB on this connection" % (
            mine, load, os.cpu_count() or 0, free, "open" if self.visible else "hidden", self.up_count, self.up_slowest * 1000,
            getattr(self, "conn_bytes", 0) / 1e6))
        self.up_count, self.up_slowest = 0, 0.0

    def report_error(self, ex):
        import traceback
        now = time.time()
        tb = traceback.format_exc()
        # the full details once per kind of error, then just a count every 10 s (no log spam)
        where = [l.strip() for l in tb.splitlines() if l.strip().startswith("File ")]
        kind = (type(ex).__name__, where[-3] if len(where) >= 3 else tb)
        seen = self.err_seen = getattr(self, "err_seen", {})
        first = kind not in seen
        n, last = seen.get(kind, (0, 0))
        seen[kind] = (n + 1, last)
        if first:
            LOG("error (kept running):", type(ex).__name__, ex)
            LOG(tb.rstrip())
            seen[kind] = (1, now)
            try:
                with open(os.path.join(CONF_DIR, "errors.log"), "a") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + tb + "\n")
            except Exception:
                pass
        elif now - last > 10:
            LOG("error again: %s x%d in the last %.0f s (kept running)" % (type(ex).__name__, n + 1, now - last))
            seen[kind] = (0, now)

    def kb_events(self, ev):
        """Laser events from both copies of the keyboard and from the wing: (which panel, event)."""
        vr = self.vr
        mouse = (vr.VREvent_MouseMove, vr.VREvent_MouseButtonDown, vr.VREvent_MouseButtonUp)
        for h in self.kbs + [self.wing]:
            while True:
                ok, e = self.ov.pollNextOverlayEvent(h, ev)
                if not ok:
                    break
                if e.eventType in mouse and self.is_eye_pointer(e.trackedDeviceIndex):
                    continue    # the eye / hand pointer's laser: the keyboard has its own look-and-pinch (or none)
                yield ("wing" if h == self.wing else "main"), e

    def is_eye_pointer(self, dev):
        cache = self.__dict__.setdefault("_ptr_cache", {})
        if dev not in cache:
            try:
                cache[dev] = self.system.getStringTrackedDeviceProperty(dev, self.vr.Prop_ControllerType_String) == "bf_pointer"
            except Exception:
                cache[dev] = False
        return cache[dev]

    def shift_held(self):
        """Is a laser holding Shift down right now (like holding Shift on a real keyboard)? Only while that laser is
        still pointing at Shift: SteamVR sometimes loses the "let go", and Shift then stayed "held" so everything typed
        with the other hand came out in capitals."""
        for sl, i in self.held.items():
            if isinstance(i, int) and i < len(self.items) and self.items[i][0].get("act") == "shift" \
                    and self.hovers.get(sl) == i:
                return True
        return False

    def release(self, slot):
        """The laser's trigger let go (or we noticed it's no longer held)."""
        eh = self.ehold.pop(slot, None)
        if eh and not eh["done"] and eh["item"] < len(self.items):   # an emoji tapped (not held): type it now
            self.press(self.items[eh["item"]][0], quiet=True)   # (its click already played when pressed)
        i = self.held.get(slot)
        if isinstance(i, int) and i < len(self.items) and self.items[i][0].get("act") == "shift" \
                and getattr(self, "shift_typed", False):
            # let go of a Shift that was held while typing: it turns off, like a real keyboard
            self.shift_typed = False
            if self.st["shift"]:
                self.st["shift"] = False
                self.dirty = True
                LOG("Shift: off (let go)")
        self.held.pop(slot, None)
        self.grip.pop(slot, None)
        if slot in self.flicks:
            self.finish_flick(slot)
        if slot in self.swipes:
            self.finish_swipe(slot)
        if self.drag and (self.drag.get("slot") == slot or not self.multi):
            self.end_drag()
        if self.repeat and self.repeat["slot"] == slot:
            self.repeat = None

    def buttons_down(self, dev):
        """(packet number, button bits, axes pulled past 0.2, axes still past 0.08) for a controller, or None."""
        try:
            ok, s = self.system.getControllerState(dev)
        except Exception:
            return None
        if not ok or not s.unPacketNum:
            return None  # SteamVR isn't sharing this controller's buttons with us
        return (int(s.unPacketNum), int(s.ulButtonPressed), frozenset(i for i in (1, 2) if s.rAxis[i].x > 0.2),
                frozenset(i for i in (1, 2) if s.rAxis[i].x > 0.08))

    def note_grip(self, slot, dev):
        """When a laser presses, note which button/trigger is doing it, so we can tell when it lets go even if
        SteamVR loses the 'let go' message (which made keys keep repeating, like a stuck key)."""
        st = self.buttons_down(dev)
        if st and (st[1] or st[2]):
            self.grip[slot] = {"dev": dev, "pkt": st[0], "bits": st[1], "axes": st[2], "t0": time.time(), "off": None}
        else:
            self.grip.pop(slot, None)

    def check_grips(self):
        now = time.time()
        for slot, g in list(self.grip.items()):
            if now - g["t0"] < 0.1:
                continue
            st = self.buttons_down(g["dev"])
            if st is None or st[0] == g["pkt"]:
                continue  # no fresh reading: trust SteamVR's own messages
            if (st[1] & g["bits"]) or (st[3] & g["axes"]):
                g["off"] = None
                continue
            g["off"] = g["off"] or now
            if now - g["off"] >= 0.15:  # clearly let go for a moment, not a flicker
                LOG("laser %s: let go without SteamVR saying so, released it" % slot)
                self.release(slot)

    def stale_hovers(self):
        """A laser that left without SteamVR saying so would leave its key lit forever: clear it."""
        now = time.time()
        for sl, t in list(self.slot_seen.items()):
            if now - t > 2.5 and sl not in self.held and self.hovers.get(sl) is not None and not (self.drag and self.drag.get("slot") == sl):
                self.hovers[sl] = None
                self.place_highlight(sl)

    def in_view(self):
        """Is the keyboard roughly in front of you (not behind you, or way off where you left it)?"""
        try:
            (hx, hy, hz), r = self.head()
            v = [self.pos[0] - hx, self.pos[1] - hy, self.pos[2] - hz]
            n = math.sqrt(sum(a * a for a in v)) or 1
            f = [-r[0][2], -r[1][2], -r[2][2]]
            return n < 2.5 and sum(v[i] * f[i] for i in range(3)) / n > math.cos(math.radians(60))
        except Exception:
            return True

    def close_steam_keyboard(self):
        try:
            self.ov.hideKeyboard()
        except Exception:
            pass

    # ---- main loop
    def run(self):
        vr = self.vr
        ev = vr.VREvent_t()
        last_attach = 0
        off_flag, off_check = os.path.join(CONF_DIR, "disabled"), 0
        streamer_flag = os.path.join(CONF_DIR, "streamer-on")
        while True:
            t_pass = time.perf_counter()
            if t_pass - off_check > 1:  # turned off in Settings: step aside so SteamVR's own keyboard comes back
                off_check = t_pass
                try:
                    self.maybe_welcome()
                    self.gaze.load()
                except Exception as ex:   # (never a reason for the keyboard to stop)
                    self.report_error(ex)
                if self.visible or (isinstance(self.vk, QueuedKeyboard) and self.vk.stream):
                    self.check_stream()
                self.watch_hands()
                on = os.path.exists(streamer_flag)
                if on != self.streamer or on != bool(self.st.get("streamer")):
                    self.streamer = on
                    LOG("streamer mode", "on" if on else "off")
                    self.st["streamer"] = on
                    self.trail_dirty = True
                    self.place_highlight()
                reset_flag = os.path.join(CONF_DIR, "reset-keyboard")
                if os.path.exists(reset_flag):   # Settings > Keyboard > Reset keyboard
                    try:
                        os.remove(reset_flag)
                    except OSError:
                        pass
                    self.reset_keyboard()
                if os.path.exists(off_flag):
                    LOG("turned off in Settings: SteamVR's own keyboard is back")
                    self.kb_label_sync(final=True)
                    self.gaze.stop()
                    try:
                        self.ov.hideOverlay(self.handle)
                    except Exception:
                        pass
                    return
            try:
                if self.gaze.sock is not None:
                    self.gaze.tick()
                self.pad_tick()
                self.sync_preedit()
                hl_dirty = set()
                for panel, e in self.kb_events(ev):
                    if e.eventType in (309, 305):   # (the stick, scrolling over the keyboard: VREvent_ScrollSmooth / Discrete)
                        self.on_scroll(e)
                        continue
                    t = e.eventType
                    if t in (vr.VREvent_MouseMove, vr.VREvent_MouseButtonDown, vr.VREvent_MouseButtonUp):
                        self.last_touch = time.time()
                        if self.is_laser(e.trackedDeviceIndex):
                            self.laser_t = self.last_touch   # (a Frame controller's laser, not a game controller)
                    if self.two_hands_on():
                        if t in (vr.VREvent_MouseMove, vr.VREvent_MouseButtonDown):
                            self.steam_dev, self.steam_dev_t = e.trackedDeviceIndex, time.time()
                            self.steam_px, self.steam_on = (e.data.mouse.x, self.img_size[1] - e.data.mouse.y), True
                        elif t == vr.VREvent_FocusLeave:
                            self.steam_on = False
                        if self.hover is not None:
                            self.hover = None
                            self.place_highlight("mouse")
                        continue  # each hand is handled by update_hands
                    # each SteamVR laser (one per controller in multi-cursor mode) has its own slot
                    slot = "c%d" % (e.data.mouse.cursorIndex if self.multi else 0)
                    self.slot_seen[slot] = time.time()
                    if t in (vr.VREvent_MouseMove, vr.VREvent_MouseButtonDown) and panel == "main":
                        try:
                            self.note_laser(e.trackedDeviceIndex, e.data.mouse.x, self.img_size[1] - e.data.mouse.y)
                        except Exception:
                            pass
                    if t == vr.VREvent_MouseButtonDown:
                        self.no_repeat_slot = None
                    if t in (vr.VREvent_MouseButtonDown, vr.VREvent_MouseButtonUp) and not self.is_laser(e.trackedDeviceIndex):
                        # a click that isn't from a VR controller's laser (Steam turning a PS5 touchpad or a controller
                        # into a pointer): never held, never repeated, and not a second copy of a key the controller's
                        # own touch just typed
                        if t == vr.VREvent_MouseButtonDown:
                            pads = self.__dict__.get("pads")
                            if pads is not None and pads.running and not getattr(self, "laser_mouse_said", False):
                                # Steam is pointing with the controller too (its "laser mouse"): every press also
                                # clicks wherever that points, behind the keyboard. Said once
                                self.laser_mouse_said = True
                                LOG("controller: Steam's laser mouse is on as well")
                            if time.time() - max(self.__dict__.get("pad_press_t", {}).values(), default=0) < 0.35:
                                continue
                            self.no_repeat_slot = slot
                    if t == vr.VREvent_MouseButtonDown and (slot in self.swipes or slot in self.ehold or slot in self.flicks):
                        # this laser pressed again, but SteamVR never said the last press let go (it loses that message
                        # when the headset is busy). The last key is typed now, before this one: it used to be lost, or
                        # stay "held" and start repeating by itself
                        self.lost_ups = getattr(self, "lost_ups", 0) + 1
                        if self.lost_ups <= 3 or self.lost_ups % 25 == 0:
                            LOG("laser %s pressed again without letting go first (%d so far): typed the last key first"
                                % (slot, self.lost_ups))
                        self.release(slot)
                    if t == vr.VREvent_MouseButtonDown:
                        if self.repeat and self.repeat.get("slot") != slot:
                            # a new key pressed: the old one stops repeating, like a real keyboard (and a key whose
                            # "let go" got lost can't keep typing by itself while you carry on)
                            o = self.repeat["slot"]
                            if o in self.swipes and not self.swipes[o].get("held"):
                                self.repeat = None   # (the other hand mid-press or mid-swipe: just no repeating)
                            else:
                                LOG("laser %s pressed: stopped %s's repeating key" % (slot, o))
                                self.release(o)
                        self.note_grip(slot, e.trackedDeviceIndex)
                        self.click_feel(e.trackedDeviceIndex)
                    if t in (vr.VREvent_MouseMove, vr.VREvent_MouseButtonDown):
                        if slot not in self.seen_cursors:
                            self.seen_cursors.add(slot)
                            LOG("laser %s on the keyboard (controller %d)" % (slot, e.trackedDeviceIndex))
                        x, y = e.data.mouse.x, (self.wing_size[1] if panel == "wing" else self.img_size[1]) - e.data.mouse.y
                        h = self.item_at(x, y, panel)
                        if self.drag and self.drag.get("slot") == slot:
                            pass  # this laser is moving the keyboard
                        elif t == vr.VREvent_MouseMove and slot in self.flicks:
                            self.move_flick(slot, x, y)  # flicking: the key stays lit, the guide shows the pick
                        elif t == vr.VREvent_MouseMove:
                            sw = self.swipes.get(slot)
                            if sw is not None and panel == "main":  # swiping: follow the laser
                                sw["pts"].append((x, y))
                                tp = sw.setdefault("trail", [(x, y)])  # a steadied copy for drawing: no hand-shake zigzag
                                tt = sw.setdefault("trail_t", [time.time()])
                                lx, ly = tp[-1]
                                tp.append((lx + (x - lx) * 0.45, ly + (y - ly) * 0.45))
                                tt.append(time.time())
                                if isinstance(h, int) and "ch" in self.items[h][0] and h not in sw["keys"]:
                                    sw["keys"].append(h)
                                self.trail_dirty = True
                            if h != self.hovers.get(slot):
                                self.hovers[slot] = h
                                hl_dirty.add(slot)  # placed once after all of this frame's laser moves are read
                        elif h in ("grab", "resize", "rotate"):
                            if not self.start_drag_px({"grab": "move"}.get(h, h), x, y, e.trackedDeviceIndex, slot):
                                LOG("couldn't grab: no controller pose")
                        elif isinstance(h, int) and panel == "main" and self.items[h][0].get("flick"):
                            # flick key: nothing types yet; where the laser goes before letting go picks the kana
                            self.flicks[slot] = {"item": h, "x": x, "y": y, "dir": 0}
                            self.hovers[slot], self.held[slot] = h, h
                            self.hpressed[slot] = time.time() + 0.09
                            self.place_highlight(slot)
                            self.show_flick_guide(slot)
                        elif isinstance(h, int) and panel == "main" and self.swipe_ready(self.items[h][0]):
                            # swipe typing: nothing is typed yet. Let go without sweeping and the letter types then;
                            # sweep across the keys and only the word is typed. (It used to type the letter at once
                            # and take it back with Backspace when a word came: if that Backspace got lost, the
                            # first letter came out twice, "ttest")
                            twin = any(v["start"] == h and time.time() - v["t"] < 0.08 for s2, v in self.swipes.items() if s2 != slot)
                            if twin:
                                continue  # the same press reported twice: one swipe is enough
                            self.swipes[slot] = {"start": h, "pts": [(x, y)], "keys": [h], "t": time.time(),
                                                 "shift": self.st["shift"], "caps": self.st["caps"], "typed": False,
                                                 "after": getattr(self, "after_letter", False)}
                            self.hovers[slot], self.held[slot] = h, h
                            self.hpressed[slot] = time.time() + 0.09
                            self.place_highlight(slot)
                            if self.st["sounds"]:
                                self.sounds.play("key")  # (the click straight away, so it still feels instant)
                            # held still on this one letter for a little longer than usual (0.6 s): that's holding the
                            # key (it repeats, or types its capital, as set in Settings). Moving off it sooner makes it a
                            # swipe. (Nothing has been typed yet, so the held letter is typed then, never twice)
                            text = self.repeat_text(self.items[h][0])
                            self.repeat = {"slot": slot, "item": h, "text": text, "fn": None, "first": True,
                                           "next": time.time() + max(0.6, self.conf.get("repeat_delay", 0.5))} \
                                if text and self.__dict__.get("no_repeat_slot") != slot else None
                        elif isinstance(h, int) and panel == "main" and self.st.get("page") == "emoji" \
                                and self.items[h][0].get("emoji") and self.items[h][0].get("ins"):
                            # an emoji: nothing typed yet. Let go and it types; hold it and it goes in (or out of) Favorites
                            now = time.time()
                            self.hovers[slot], self.hpressed[slot], self.held[slot] = h, now + 0.09, h
                            self.place_highlight(slot)
                            self.ehold[slot] = {"item": h, "t": now, "done": False}
                            if self.st["sounds"]:
                                self.sounds.play("key")
                        elif h is not None:
                            now = time.time()
                            self.hovers[slot], self.hpressed[slot], self.held[slot] = h, now + 0.09, h
                            self.place_highlight(slot)
                            k = self.items[h][0]
                            text = self.repeat_text(k)
                            fn_key = FN[k["act"]][1] if self.st.get("fn") and k.get("act") in FN else None
                            self.press(k)
                            if k.get("act") == "shift" and self.st["shift"]:  # hold Shift: it locks (Caps Lock)
                                self.shift_lock = {"slot": slot, "item": h, "at": now + 0.6}
                            if self.__dict__.pop("no_repeat_slot", None) == slot:
                                pass   # (no way to tell when this kind of click lets go: one press, one key)
                            elif self.repeatable(k) or (fn_key and fn_key in ("HOME", "END", "PAGEUP", "PAGEDOWN", "VOLUMEUP", "VOLUMEDOWN")):
                                # hold half a second and it keeps going, like a real keyboard (Fn keys repeat their Fn action)
                                self.repeat = {"slot": slot, "item": h, "text": text, "fn": fn_key, "next": now + self.conf.get("repeat_delay", 0.5)}
                    elif t == vr.VREvent_MouseButtonUp:
                        self.release(slot)
                    elif t == vr.VREvent_FocusLeave:
                        for sl in [k for k in self.hovers if k.startswith("c")]:
                            if not (self.drag and self.drag.get("slot") == sl) and self.hovers[sl] is not None:
                                self.hovers[sl] = None
                                self.place_highlight(sl)
                        self.repeat = None
                for sl in hl_dirty:
                    self.place_highlight(sl)
                while self.tog:
                    ok, e = self.ov.pollNextOverlayEvent(self.tog, ev)
                    if not ok:
                        break
                    if e.eventType == vr.VREvent_MouseButtonDown:
                        self.toggle()
                self.aim_events(ev)   # the fade button (takes the laser even while the keyboard is see-through)
                while self.system.pollNextEvent(ev):
                    t = ev.eventType
                    if t == vr.VREvent_Quit:
                        self.system.acknowledgeQuit_Exiting()
                        return
                    if t == vr.VREvent_KeyboardOpened_Global and self.conf.get("replace_system_keyboard"):
                        self.on_system_keyboard(ev)
                    elif t == vr.VREvent_KeyboardClosed_Global:
                        self.sys_kb_open = False
                        self.steam_kb_mine = False
                        LOG("system keyboard closed")
                    elif t == getattr(vr, "VREvent_DashboardDeactivated", -1) and self.visible and getattr(self, "dash", None):
                        # the Steam menu closing: go with it straight away (SteamVR says so itself)
                        self.dash, self.dash_seen, self.dash_hide_pending = False, None, True
                        self.finish_dash_hide()
                    elif t in (getattr(vr, "VREvent_ChaperoneUniverseHasChanged", -1), getattr(vr, "VREvent_StandingZeroPoseReset", -1),
                               getattr(vr, "VREvent_SeatedZeroPoseReset", -1), getattr(vr, "VREvent_ChaperoneDataHasChanged", -1)):
                        self.space_changed = time.time()
                if getattr(self, "space_changed", 0) and time.time() - self.space_changed > 0.5:
                    self.space_changed = 0  # you recentred your view: bring the keyboard back in front of you
                    if self.visible and not self.drag:
                        LOG("view recentred: keyboard moved back in front of you")
                        self.recenter()
                self.health()
                if time.time() - self.last_checks >= 0.1:  # background checks 10 times a second, not every frame
                    self.last_checks = time.time()
                    self.keep_in_reach()     # (first: nothing else can stop the keyboard coming back from the floor)
                    self.load_look()         # a new theme from Settings shows straight away (only reads the file when it changed)
                    self.follow_dashboard()
                    self.finish_dash_hide()
                    self.keep_in_sync()
                    if getattr(self, "lookups", None):   # (an answer from Steam's pages: used straight away)
                        self.check_stream()
                    self.open_for_text_box()
                    self.kb_label_sync()
                if self.live_pending is not None and time.time() - self.last_live >= 0.15:
                    self.pop_live = self.live_pending   # (the words heard so far: shown in the pop-up)
                    self.live_pending, self.last_live = None, time.time()
                if time.time() - last_attach > 3:
                    last_attach = time.time()
                    try:
                        self.attach_toggle()
                    except Exception:
                        pass
                if self.hands:
                    try:
                        self.update_hands()
                    except Exception as ex:
                        LOG("two-hand input error:", ex)
                        self.hands = None
                if self.grip:
                    self.check_grips()
                try:
                    self.check_stolen()
                except Exception as ex:
                    self.report_error(ex)
                if getattr(self, "vr_refusing", False) and (self.swipes or self.held):
                    pass  # never start over in the middle of a swipe or a held key: right after it ends
                elif getattr(self, "vr_refusing", False):
                    if self.reconnect("SteamVR stopped taking pictures"):
                        continue
                    self.vr_refusing, self.refusals = False, []  # reconnected moments ago: just keep trying
                elif not self.visible and getattr(self, "conn_bytes", 0) > 200e6 and time.time() - self.last_press > 3:
                    # lots of pictures sent on this connection: refresh it now, while the keyboard is closed,
                    # so SteamVR never gets to the point of refusing them while you type
                    self.reconnect("routine refresh while closed")
                self.stale_hovers()
                for sl, idx in list(self.bubble_wait.items()):  # a bubble held back while sweeping
                    if time.time() - self.bubble_sent.get(sl, 0) >= 0.12:
                        self.bubble_wait.pop(sl, None)
                        if self.hovers.get(sl) == idx:
                            self.place_bubble(sl, idx)
                self.update_drag()
                self.update_fade()
                self.aim_tick()       # solid while both lasers are on it, see-through (and let through) when one looks away
                self.update_trail()
                self.update_words()
                self.update_popup()
                th = getattr(self, "trail_hide", None)
                if th and time.time() > th[1]:
                    self.trail_hide = None
                    if self.trail_shown and self.trail_ovs and th[0] != self.trail_ovs[self.trail_i]:
                        self.ov.hideOverlay(th[0])
                now = time.time()
                if self.visible and getattr(self, "sys_kb_open", False) and now - self.last_kill > 0.25:
                    # SteamVR's keyboard still up (or back again) while ours is showing: never both at once
                    self.close_steam_keyboard()
                    self.last_kill = now
                if now < self.kill_kb_until and now - self.last_kill > 0.05:
                    self.close_steam_keyboard()
                    self.last_kill = now
                if self.pending_hide and now > self.pending_hide[1]:
                    if self.pending_hide[0] != self.handle:
                        self.ov.hideOverlay(self.pending_hide[0])
                    self.pending_hide = None
                for sl, until in list(self.hpressed.items()):  # end the short "pressed" look
                    if until and now > until and not self.hands:
                        self.hpressed[sl] = 0
                        self.place_highlight(sl)
                r = self.repeat
                sw_ = self.swipes.get(r["slot"]) if r else None
                if sw_ is not None and not sw_.get("held") and self.real_swipe(sw_):
                    self.repeat = r = None  # it turned into a swipe: no repeating
                if r and sw_ is not None and not sw_.get("held") and now >= r["next"] and not self.held_still(sw_, r["item"]):
                    self.repeat = r = None  # the laser has left the first letter: a slow swipe, not a held key
                if r and r["slot"] not in self.grip and now - r.setdefault("since", now) > 4.0:
                    # SteamVR isn't telling us whether the trigger is still held (the Frame often doesn't): a key
                    # that's been repeating for 4 s is let go, so a lost "let go" can't type on and on
                    LOG("laser %s: repeating for 4 s without being able to check the trigger: stopped" % r["slot"])
                    self.release(r["slot"])
                    r = None
                elif r and now - getattr(self, "pass_t", now) > 0.3:
                    # the keyboard was held up (the headset busy): a "let go" may be among what got lost, so no
                    # repeating on until the next press
                    LOG("keyboard was held up %.1f s: stopped the repeating key" % (now - self.pass_t))
                    self.repeat = r = None
                if r and not self.hands and now >= r["next"]:  # hold a key to repeat it
                    if sw_ is not None:
                        sw_["held"] = True  # held still on one letter: that's repeating, not a swipe
                    if self.held.get(r["slot"]) is not None and self.hovers.get(r["slot"]) == r["item"] and r["item"] < len(self.items):
                        if r.get("fn"):
                            if self.vk:
                                self.vk.tap(KEY[r["fn"]])
                        elif r.get("text") and getattr(self, "hold_shift", False):
                            # held: the capital (or the key's other character) instead of the one typed, once
                            k_ = self.items[r["item"]][0]
                            alt = self.held_variant(k_, r["text"]) or r["text"]
                            if r.get("first"):     # (a swipe-typing letter: nothing typed yet, so just the capital)
                                self.type_text(alt)
                                if self.st["sounds"]:
                                    self.sounds.play("key")
                                self.after_held_letter()
                            elif alt != r["text"] and self.vk:
                                self.vk.tap(KEY["BACKSPACE"])
                                self.type_text(alt)
                                if self.st["sounds"]:
                                    self.sounds.play("key")
                            self.repeat = None
                        elif r.get("text"):
                            if self.st["sounds"]:
                                self.sounds.play("key")
                            self.type_text(r["text"])
                            if r.pop("first", False):   # (a swipe-typing letter: its first one now, repeats after a moment)
                                r["next"] = now + 0.3
                                self.after_held_letter()
                        else:
                            self.press(self.items[r["item"]][0])
                        if self.repeat is not None and r["next"] <= now:
                            r["next"] = now + self.conf.get("repeat_rate", 0.05)
                    else:
                        self.repeat = None
                for sl, eh in list(self.ehold.items()):   # an emoji held for half a second: Favorites
                    if eh["done"] or now - eh["t"] < 0.55:
                        continue
                    eh["done"] = True
                    if self.hovers.get(sl) == eh["item"] and eh["item"] < len(self.items):
                        self.toggle_fav(self.items[eh["item"]][0])
                    # (slid off it before then: nothing, like a phone keyboard)
                self.pass_t = now   # (when the keyboard last got round to this: a long gap means it was held up)
                sl_ = getattr(self, "shift_lock", None)
                if sl_ and now >= sl_["at"]:
                    self.shift_lock = None
                    if self.held.get(sl_["slot"]) == sl_["item"] and self.hovers.get(sl_["slot"]) == sl_["item"] \
                            and self.st["shift"] and not self.st["caps"] and not getattr(self, "shift_typed", False):
                        self.st["caps"], self.st["shift"] = True, False
                        self.dirty = True
                        LOG("Shift held: Caps Lock")
                if self.pressed is not None and time.time() > self.pressed_until:
                    self.pressed = None
                    self.place_highlight()
                if getattr(self, "pop_msg", "") and time.time() > self.msg_until:
                    self.pop_msg = ""
                if self.dirty and self.visible:
                    self.redraw()
                pass  # update fast while moving it, so it follows your hand smoothly
            except Exception as ex:  # never let one error close the keyboard
                self.report_error(ex)
            took = time.perf_counter() - t_pass
            if took > 0.25:  # freeze detector: say what was slow
                LOG("slow moment: %.0f ms (last key: %s, redrew: %s)" % (took * 1000, getattr(self, "last_key", "-"),
                                                                       getattr(self, "redrew_at", 0) >= t_pass))
            # fast while moving it (follows your hand smoothly), normal while open, and mostly asleep while hidden
            busy = self.kill_kb_until > time.time() or self.pending_hide or self.dash_hide_pending
            # a laser on the keyboard: check 120 times a second so the highlight keeps up with your hand
            active = self.drag or self.swipes or time.time() - self.last_touch < 1.0
            period = 1 / 120 if active else 1 / 60 if self.visible else 1 / 30 if busy else 1 / 20
            time.sleep(max(0.001, period - (time.perf_counter() - t_pass)))  # count the work, so the rate is steady


def steamvr_running():
    """True if SteamVR is already up. Uses the 'background' connection, which never starts SteamVR itself
    (the normal overlay connection can launch SteamVR, which at boot can leave the Frame stuck)."""
    import openvr
    try:
        openvr.init(openvr.VRApplication_Background)
    except Exception:
        return False
    try:
        openvr.shutdown()
    except Exception:
        pass
    return True


def wait_for_steamvr(off_flag, settle=None):
    """Wait until SteamVR has been running steadily for a few seconds. Right after the Frame boots, wait a
    little longer so Steam finishes starting first; any other time (e.g. SteamVR restarted) connect quickly."""
    if settle is None:
        try:
            uptime = float(open("/proc/uptime").read().split()[0])
        except Exception:
            uptime = 999
        settle = 6 if uptime < 120 else 2
    since = None
    said = False
    while True:
        if os.path.exists(off_flag):
            return False
        if steamvr_running():
            since = since or time.time()
            if time.time() - since >= settle:
                return True
        else:
            if since is not None or not said:
                LOG("waiting for SteamVR to start (won't start it myself)")
                said = True
            since = None
        time.sleep(1)


def main():
    # only one copy at a time: a second one (started by hand while the service runs) would fight over the keyboard
    import fcntl
    os.makedirs(CONF_DIR, exist_ok=True)
    lock = open(os.path.join(CONF_DIR, "overlay.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        LOG("already running in the background, so this copy won't start. Use: systemctl --user restart betterframe-overlay")
        return
    try:
        os.nice(5)  # a little below normal, so games and SteamVR always come first
    except Exception:
        pass
    off_flag = os.path.join(CONF_DIR, "disabled")
    try:  # pin buttons on SteamVR's floating windows (dashpin.py): kept in place in the background
        import dashpin
        dashpin.Keeper(log=LOG).start()
    except Exception as ex:
        LOG("pin buttons unavailable:", ex)
    try:  # BetterFrame's pages in Steam's own Settings (steambridge.py), when they're turned on
        import steambridge
        steambridge.Keeper(log=LOG).start()
        steambridge.Hider(log=LOG).start()
    except Exception as ex:
        LOG("settings pages unavailable:", ex)
    said_off = False
    while True:
        if os.path.exists(off_flag):  # turned off (Settings > Plugins, or touch ~/.config/betterframe-keyboard/disabled)
            if not said_off:
                LOG("turned off (%s exists), not starting" % off_flag)
                said_off = True
            time.sleep(2)
            continue
        said_off = False
        if not wait_for_steamvr(off_flag):
            continue
        app = None
        try:
            app = App()
            app.start_vr()
            LOG("connected to SteamVR")
            app.async_render = True  # new looks are drawn in the background (with a safety net: see render)
            app.run()
            LOG("SteamVR closed, waiting for it to start again")
        except KeyboardInterrupt:
            break
        except Exception as e:
            import traceback
            LOG("waiting for SteamVR:", e)
            LOG(traceback.format_exc().rstrip())
        finally:
            try:
                if app:
                    app.gaze.stop()
                    app.dict.stop()
                    if app.vk:
                        app.vk.close()
                import openvr
                openvr.shutdown()
            except Exception:
                pass
        time.sleep(3)


if __name__ == "__main__":
    if "--preview" in sys.argv:
        from PIL import Image
        conf = load_conf()
        r = Renderer(conf.get("font", ""))
        outdir = sys.argv[-1] if len(sys.argv) > 2 else "."
        for lay in ("minimal", "full", "advanced"):
            for page in ("abc", "123", "sym"):
                st = {"layout": lay, "page": page, "shift": False, "caps": page == "sym", "mic": page == "123", "sounds": page != "123",
                      "live": "", "msg": "", "lang": conf.get("lang", "en-US"), "fmt": conf.get("fmt", "default")}
                img = r.draw(st, conf)[0]
                bg = Image.new("RGBA", img.size, (7, 11, 18, 255))
                bg.alpha_composite(img)
                out = os.path.join(outdir, "preview-%s-%s.png" % (lay, page))
                bg.save(out)
                print(out, img.size)
        sys.exit(0)
    main()
