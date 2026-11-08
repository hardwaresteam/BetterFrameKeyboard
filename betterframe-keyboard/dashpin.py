#!/usr/bin/env python3
"""Pin to head for SteamVR's floating windows.

SteamVR's dashboard (a web page inside SteamVR) owns its floating windows, so the pin button and the
head follow live in that page (dashpin.js). BetterFrame puts them in whenever SteamVR starts. It needs
SteamVR's dashboard debug port, on 127.0.0.1 only:

    python3 dashpin.py enable     turn the port on (from SteamVR's next start)
    python3 dashpin.py disable    turn it off again (only if this turned it on)
    python3 dashpin.py try        add the pin icons now, just until SteamVR restarts
    python3 dashpin.py on         add them, and keep adding them whenever SteamVR starts
    python3 dashpin.py off        take them out, and stop adding them
    python3 dashpin.py status     are they in?
    python3 dashpin.py smooth on|off   pinned windows glide after your head, or stay locked in view
    python3 dashpin.py list | pin [N] | follow [N] | unpin [N|all]

Off unless turned on (dashpin.py on).
"""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8089  # (not 8087: SteamOS forwards 8088 to that one from the network)
BIN = "/opt/steamvr/bin/linuxarm64"
CONF = os.path.expanduser("~/.config/betterframe-keyboard")
MARK = os.path.join(CONF, "dash-debug-on")
OFF = os.path.join(CONF, "no-dash-pin")
ON = os.path.join(CONF, "dash-pin-on")
SMOOTH = os.path.join(CONF, "pin-smooth")   # pinned windows glide after your head instead of being locked in place   # BetterFrame only adds the pin icons by itself once this exists


class WS:
    """A tiny websocket client, enough for the debug protocol."""
    def __init__(self, url, timeout=4):
        hp, path = url[5:].split("/", 1)
        host, port = hp.rsplit(":", 1)
        self.s = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, hp, key)).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            c = self.s.recv(4096)
            if not c:
                raise OSError("closed")
            buf += c
        if b" 101 " not in buf.split(b"\r\n")[0]:
            raise OSError(buf.split(b"\r\n")[0].decode(errors="replace"))
        self.buf = buf.split(b"\r\n\r\n", 1)[1]

    def send(self, text):
        d, m = text.encode(), os.urandom(4)
        n = len(d)
        hdr = struct.pack(">BB", 0x81, 0x80 | n) if n < 126 else struct.pack(">BBH", 0x81, 0xFE, n) if n < 65536 \
            else struct.pack(">BBQ", 0x81, 0xFF, n)
        mask = int.from_bytes((m * (n // 4 + 1))[:n], "big")   # mask the whole message in one go (fast)
        self.s.sendall(hdr + m + (int.from_bytes(d, "big") ^ mask).to_bytes(n, "big") if n else hdr + m)

    def take(self, n):
        while len(self.buf) < n:
            c = self.s.recv(65536)
            if not c:
                raise OSError("closed")
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        msg = b""
        while True:
            b0, b1 = self.take(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self.take(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self.take(8))[0]
            data = self.take(n)
            op = b0 & 0x0F
            if op == 8:
                raise OSError("closed")
            if op in (9, 10):   # ping / pong: not part of an answer
                continue
            msg += data
            if b0 & 0x80:
                return msg.decode(errors="replace")

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


_URLS = {}   # page -> (address, when looked up): asking the debug port for its pages every time costs a little each


def _cached(name, look, ttl=10.0):
    got = _URLS.get(name)
    if got and got[0] and time.time() - got[1] < ttl:
        return got[0]
    url = look()
    _URLS[name] = (url, time.time())
    return url


def forget(url):
    for k, v in list(_URLS.items()):
        if v[0] == url:
            _URLS.pop(k, None)


def dashboard():
    """The dashboard page's debug address, or None (SteamVR not running, or the port is off)."""
    return _cached("dash", _dashboard)


def _dashboard():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT, timeout=2) as r:
            for t in json.load(r):
                if t.get("title") == "systemui":
                    return t.get("webSocketDebuggerUrl")
    except Exception:
        return None


def steam_page():
    """Steam's own UI page (its shared script context), or None."""
    return _cached("steam", _steam_page)


def _steam_page():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/json", timeout=2) as r:
            for t in json.load(r):
                if t.get("title") == "SharedJSContext":
                    return t.get("webSocketDebuggerUrl")
    except Exception:
        return None


_CONNS, _CONNS_LOCK, _LOCKS, _USED = {}, threading.Lock(), {}, {}
LAST_ODD = None   # the last message from a page that wasn't an answer (for the log)


def run_js(url, expr, wait=False):
    """Run a script in the page and return its result. The connection is kept open and reused, so frequent
    small checks cost almost nothing (a new connection each time is a lot more work for both sides)."""
    with _CONNS_LOCK:
        lock = _LOCKS.setdefault(url, threading.Lock())
    with lock:
        for attempt in (0, 1):
            ws = _CONNS.get(url)
            fresh = ws is None
            try:
                if ws is None:
                    ws = WS(url)
                    with _CONNS_LOCK:
                        _CONNS[url] = ws
                        # pages that have gone (old SteamVR or Steam sessions): closed once unused for a minute. Never
                        # one in use: streamer mode talks to every page several times a second, and closing the
                        # oldest connections straight away cut the one Settings was using mid-answer, so changes
                        # made in Steam's Settings (themes, hand and eye tracking) were often lost
                        now_ = time.time()
                        for old in [u for u in _CONNS if u != url and now_ - _USED.get(u, 0) > 60]:
                            lk = _LOCKS.get(old)
                            if lk is not None and lk.acquire(blocking=False):
                                try:
                                    _CONNS.pop(old).close()
                                finally:
                                    lk.release()
                ws.n = getattr(ws, "n", 0) + 1
                _USED[url] = time.time()
                ws.s.settimeout(30 if wait else 6)
                ws.send(json.dumps({"id": ws.n, "method": "Runtime.evaluate",
                                    "params": {"expression": expr, "returnByValue": True, "awaitPromise": bool(wait)}}))
                while True:
                    raw = ws.recv()
                    try:
                        r = json.loads(raw)
                    except ValueError:
                        global LAST_ODD
                        LAST_ODD = raw[:120]
                        continue        # not an answer (an empty or odd message from the page): wait for ours
                    if isinstance(r, dict) and r.get("id") == ws.n:
                        break
                break
            except Exception:
                ws and ws.close()
                with _CONNS_LOCK:
                    _CONNS.pop(url, None)
                if fresh or attempt:
                    forget(url)   # the page may have gone (SteamVR or Steam restarted): look it up again next time
                    raise
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return "error: " + json.dumps(res["exceptionDetails"])[:400]
    return res.get("result", {}).get("value")


def helper_js():
    with open(os.path.join(HERE, "dashpin.js")) as f:
        return f.read()


def helper_version():
    import re
    m = re.search(r"const VERSION = (\d+);", helper_js())
    return int(m.group(1)) if m else 0


def put_in(url):
    """Puts the helper (and its pin buttons) in the dashboard page, unless the same version is there."""
    have = run_js(url, "window.__bfPin ? window.__bfPin.version : 0")
    if isinstance(have, int) and have >= helper_version():
        return False
    run_js(url, helper_js() + ";'ok'")
    return True


class Keeper(threading.Thread):
    """Runs inside the keyboard service: every few seconds, makes sure the pin buttons are in
    SteamVR's dashboard (it starts fresh whenever SteamVR restarts). Does nothing when the debug port
    is off or the feature is turned off."""
    def __init__(self, log=print):
        super().__init__(daemon=True, name="dashpin")
        self.log = log
        self.last_url = None

    def run(self):
        time.sleep(8)
        while True:
            try:
                if os.path.exists(ON) and not os.path.exists(OFF):
                    url = dashboard()
                    if url:
                        put_in(url)
                        if run_js(url, "window.__bfPin ? (__bfPin.mode = '%s', __bfPin.off ? (__bfPin.off = false, __bfPin.scan(), 'on') : '') : ''"
                                  % ("follow" if os.path.exists(SMOOTH) else "pin")) == "on":
                            self.log("pin icons added to SteamVR's windows")
            except Exception as ex:
                if self.last_url != str(ex):
                    self.log("pin buttons: %s" % ex)
                    self.last_url = str(ex)
            time.sleep(5)


# --------------------------------------------------------------------------- settings
ENV = dict(os.environ, LD_LIBRARY_PATH=BIN, XDG_CONFIG_HOME=os.path.expanduser("~/.config"))


def vrcmd(*args):
    try:
        return subprocess.run([BIN + "/vrcmd", *args], capture_output=True, text=True, timeout=15, env=ENV).stdout
    except Exception as ex:
        return "vrcmd failed: %s" % ex


def port_setting():
    return (vrcmd("--settings-bool", "VRWebHelper.DebuggerEnabled").strip(),
            vrcmd("--settings-int", "VRWebHelper.DebuggerPort").strip())


INSPECT = r"""
(() => {
  const out = {windows: [], panels: []};
  const EL = Symbol.for('react.element');
  const nm = t => typeof t === 'string' ? t : t ? (t.displayName || t.name || (t.type && (t.type.displayName || t.type.name)) || String(t.$$typeof || typeof t)) : String(t);
  const tree = (n, d) => {
    if (!n || d > 9 || typeof n !== 'object') return null;
    if (Array.isArray(n)) return n.map(c => tree(c, d)).filter(Boolean);
    if (n.$$typeof !== EL) return null;
    const p = n.props || {};
    const keys = Object.keys(p).filter(k => k !== 'children');
    const small = {};
    for (const k of keys) { const v = p[k]; if (v == null || typeof v !== 'function' && typeof v !== 'object' || k === 'translation' || k === 'rotation') small[k] = typeof v === 'function' ? 'fn' : v; else small[k] = typeof v; }
    return {t: nm(n.type), p: small, c: tree(p.children, d + 1)};
  };
  const seen = new Set(), wins = [];
  for (const el of document.querySelectorAll('*')) for (const k of Object.keys(el)) {
    if (!k.startsWith('__reactContainer$')) continue;
    const st = [el[k]];
    while (st.length) {
      const f = st.pop(); if (!f || seen.has(f)) continue; seen.add(f);
      const n = f.stateNode, p = f.memoizedProps;
      if (n && typeof n.startFloatingWindowMove === 'function' && !wins.includes(n)) wins.push(n);
      if (p && typeof p === 'object' && typeof p.debug_name === 'string' && out.panels.length < 40)
        out.panels.push({type: nm(f.type), props: Object.keys(p).filter(k => k !== 'children').slice(0, 30), debug_name: p.debug_name, width: p.width, mpp: p.meters_per_pixel});
      if (f.child) st.push(f.child); if (f.sibling) st.push(f.sibling);
    }
  }
  for (const w of wins) {
    const r = w.__bfPatched || w.render;
    let t = null; try { t = tree(r.call(w), 0); } catch (e) { t = 'render error ' + e; }
    out.windows.push({grabID: w.m_sDragSnapLineOriginID, state: {parent: w.state.sParentDevice, xf: w.state.xfTransform}, tree: t});
  }
  out.chosen = window.__bfPin && window.__bfPin.Panel ? nm(window.__bfPin.Panel) : null;
  return JSON.stringify(out);
})()
"""


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd in ("enable", "disable"):
        on = cmd == "enable"
        before = port_setting()
        if not on and not os.path.exists(MARK):
            print("Left as it is (BetterFrame didn't turn it on).", before)
            return
        if on and "=true" in before[0] and before[1].endswith("=%d" % PORT):
            print("Already on.", before)
            return
        vrcmd("--set-settings-bool", "VRWebHelper.DebuggerEnabled", "1" if on else "0")
        if on:
            vrcmd("--set-settings-int", "VRWebHelper.DebuggerPort", str(PORT))
            os.makedirs(CONF, exist_ok=True)
            with open(MARK, "w") as f:
                f.write("turned on by BetterFrame; before: %s\n" % (before,))
        else:
            os.remove(MARK)
        print("before:", before)
        print("now:   ", port_setting())
        print("Takes effect when SteamVR restarts.")
        return
    if cmd == "smooth" and arg in ("on", "off"):  # remembered even while SteamVR isn't running
        os.makedirs(CONF, exist_ok=True)
        if arg == "on":
            open(SMOOTH, "w").close()
        elif os.path.exists(SMOOTH):
            os.remove(SMOOTH)
    url = dashboard()
    if not url:
        print("SteamVR's dashboard isn't reachable (SteamVR not running, or run: python3 dashpin.py enable, then restart SteamVR).")
        return
    if cmd == "inspect":  # looks only: what a floating window draws, and which pieces the button would use
        print(run_js(url, INSPECT))
        return
    if cmd == "off":  # take the icons out now, and don't put them back by itself
        os.makedirs(CONF, exist_ok=True)
        open(OFF, "w").close()
        if os.path.exists(ON):
            os.remove(ON)
        print(run_js(url, "window.__bfPin ? (__bfPin.unpatchAll(), 'pin icons off') : 'pin icons off'"))
        return
    if cmd == "on":  # keep them: BetterFrame adds them whenever SteamVR starts
        os.makedirs(CONF, exist_ok=True)
        open(ON, "w").close()
        if os.path.exists(OFF):
            os.remove(OFF)
    put_in(url)
    if cmd in ("try", "on"):
        print(run_js(url, "(__bfPin.off = false, __bfPin.errors = 0, __bfPin.scan(), 'pin icons: ' + document.querySelectorAll('.bf-pin').length + ' added' + ('%s' ? ', and kept from now on' : ' (just until SteamVR restarts)'))" % ("1" if cmd == "on" else "")))
        return
    if cmd == "status":
        js = ("JSON.stringify({version: __bfPin.version, windows: __bfPin.windows().length, pinned: __bfPin.pinned.size,"
              " icons: document.querySelectorAll('.bf-pin').length, docks: __bfPin.docks(), labels: __bfPin.labels || 0, size: __bfPin.lastSize || null, measure: __bfPin.measure(), universe: __bfPin.std(), rescued: __bfPin.rescued || 0, errors: __bfPin.errors, lastError: __bfPin.lastError, off: !!__bfPin.off})")
    elif cmd == "list":
        js = "JSON.stringify(__bfPin.windows().map(__bfPin.describe))"
    elif cmd in ("pin", "follow"):
        n = int(arg) if arg else -1
        js = ("(() => { const ws = __bfPin.windows(); let w = %d >= 0 ? ws[%d] : ws.find(x => x.state.xfTransform);"
              " if (!w) return 'no floating window (pop one out first)'; const r = __bfPin.pin(w, '%s');"
              " try { w.forceUpdate(); } catch (e) {} return r; })()" % (n, n, cmd))
    elif cmd == "unpin":
        if arg in (None, "all"):
            js = "JSON.stringify([...__bfPin.pinned.keys()].map(w => { const r = __bfPin.unpin(w); try { w.forceUpdate(); } catch (e) {} return r; }))"
        else:
            js = "(() => { const w = __bfPin.windows()[%d]; return w ? __bfPin.unpin(w) : 'no window %d'; })()" % (int(arg), int(arg))
    elif cmd == "smooth" and arg in ("on", "off"):  # pinned windows glide after you (on) or stay locked in view (off)
        mode = "follow" if arg == "on" else "pin"
        js = ("(() => { __bfPin.mode = '%s'; let n = 0; for (const w of [...__bfPin.pinned.keys()]) { __bfPin.unpin(w); __bfPin.pin(w, '%s'); n++; }"
              " return 'smooth follow %s' + (n ? ', re-pinned ' + n : ''); })()" % (mode, mode, arg))
    elif cmd == "drop" and arg:  # move pinned windows up or down: 0 = higher ... 0.5 = lower
        js = ("(() => { __bfPin.drop = %f; let n = 0; for (const w of [...__bfPin.pinned.keys()]) { __bfPin.unpin(w); __bfPin.pin(w, 'pin'); n++; }"
              " return 'drop ' + __bfPin.drop + ', re-pinned ' + n; })()" % float(arg))
    elif cmd == "button" and len(sys.argv) >= 5:  # place the pin button: dx dy size (metres)
        dx, dy, size = (float(x) for x in sys.argv[2:5])
        js = "(() => { Object.assign(__bfPin.btn, {dx: %f, dy: %f, size: %f}); __bfPin.windows().forEach(w => w.forceUpdate()); return 'moved'; })()" % (dx, dy, size)
    else:
        print(__doc__)
        return
    print(run_js(url, js))


if __name__ == "__main__":
    main()
