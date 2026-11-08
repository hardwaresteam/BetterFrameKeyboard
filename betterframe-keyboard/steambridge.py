#!/usr/bin/env python3
"""BetterFrame pages in Steam's own Settings (VR, BetterFrame, Plugins).

steampages.js lives in Steam's interface and draws the pages with Steam's own toggles, sliders and dropdowns;
this side (running inside the keyboard service) gives it the values and makes the changes it asks for.

    python3 steambridge.py on       add the pages (kept from now on)
    python3 steambridge.py off      take them out straight away, and stop adding them
    python3 steambridge.py status   what's going on
    python3 steambridge.py divider on|off   the line between the VR group and Steam's own pages
    python3 steambridge.py fold on|off      small Steam pages folded into related ones
    python3 steambridge.py streamer on|off  streamer mode
    python3 steambridge.py probe            what Steam offers for typing into streamed games
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bfsettings  # noqa: E402
import dashpin  # noqa: E402

CONF = os.path.expanduser("~/.config/betterframe-keyboard")
ON = os.path.join(CONF, "steam-pages-on")
KB_OFF = os.path.join(CONF, "disabled")

NO_DIVIDER = os.path.join(CONF, "steam-pages-no-divider")
NO_FOLD = os.path.join(CONF, "steam-pages-no-fold")

# the VR group at the top of Steam's Settings: (page id, title, icon, [(category, section) or category, ...])
VR_PAGES = [
    ("headset", "Headset Display", "video", ["Display"]),
    ("tracking", "Tracking", "controller", [("Controls", "Controllers"), ("Controls", "Laser"), "Tracking"]),
    ("play-area", "Play Area", "playarea", ["Play Area"]),
    ("windows", "Windows & Menus", "dashboard", ["Windows", "People"]),
]
# SteamVR settings that belong with one of Steam's own pages: shown there, under their own heading
INTO = {"audio": ("Sound", "Headset "), "power": ("Power", "Headset ")}

KB_ROW = {"id": "plugin_keyboard", "label": "Enabled", "kind": "switch",
          "desc": "Turn off to use SteamVR's own keyboard again"}
STREAMER = os.path.join(CONF, "streamer-on")
STREAMER_TOASTS = os.path.join(CONF, "streamer-toasts-before")
STREAMER_ROW = {"id": "streamer", "label": "Enabled", "kind": "switch",
                "desc": "For recording and streaming. Hides names, profile pictures, friend codes and what friends are "
                        "playing, and doesn't show what you type"}
UNINSTALL_ROW = {"id": "kb_uninstall", "label": "Uninstall BetterFrame Keyboard", "kind": "button", "button": "Uninstall",
                 "confirm": "Sure?",
                 "desc": "Puts SteamVR's own keyboard back. Restart SteamVR afterwards"}
RESET_ROW = {"id": "kb_reset", "label": "Reset keyboard", "kind": "button", "button": "Reset",
             "confirm": "Sure?",
             "desc": "Puts the keyboard's size, position and tilt back to how they started"}
RESET_FLAG = os.path.join(CONF, "reset-keyboard")
_RESET = ("idle", 0.0)
PIN_ROW = {"id": "pins", "label": "Enabled", "kind": "switch",
           "desc": "Adds a pin button under floating windows to keep them in front of you"}


def _d(x, desc=None):
    ex = x[7]
    return {"id": x[0], "label": x[3], "kind": x[4], "min": ex.get("min"), "max": ex.get("max"), "step": ex.get("step", 1),
            "unit": ex.get("unit", ""), "options": ex.get("options"), "desc": desc or ex.get("desc")}


def _sections(rows):
    secs = []
    for x in rows:
        sec = next((sc for sc in secs if sc["title"] == x[2]), None)
        if not sec:
            sec = {"title": x[2], "rows": []}
            secs.append(sec)
        sec["rows"].append(_d(x))
    return secs


def _ours():
    return [x for x in bfsettings.S if x[5] in ("vr", "bf", "pref")]


def merge():
    """Settings shown inside Steam's own pages."""
    out = {}
    for key, (cat, prefix) in ({} if os.path.exists(KB_ONLY) else INTO).items():
        secs = _sections([x for x in _ours() if x[1] == cat])
        for sc in secs:
            sc["title"] = prefix + sc["title"].lower()
        if secs:
            out[key] = secs
    # the keyboard's settings, at the top of Steam's own Keyboard page: on/off (and Uninstall, for the keyboard on its
    # own) first, then how it looks
    secs = _sections([x for x in _ours() if x[1] == "Keyboard"])
    for sc in secs:
        for r in sc["rows"]:
            if r["id"] == "kb_backdrop":
                r["desc"] = "Transparency of the BetterFrame Keyboard backdrop"
    first = [KB_ROW, RESET_ROW, UNINSTALL_ROW] if os.path.exists(KB_ONLY) else [KB_ROW, RESET_ROW]
    # all under one heading: on/off (and Uninstall), then the rest in order
    out["keyboard"] = [{"title": "BetterFrame Keyboard", "rows": first + [r for sc in secs for r in sc["rows"]]}]
    return out


KB_ONLY = os.path.join(CONF, "keyboard-only")


def pages():
    """Our pages, in the VR group at the top of Steam's Settings."""
    if os.path.exists(KB_ONLY):  # the keyboard on its own: its settings live in Steam's own Keyboard page (see merge)
        return []
    out = []
    for pid, title, icon, picks in VR_PAGES:
        rows = [x for p in picks for x in _ours() if (x[1] == p if isinstance(p, str) else (x[1], x[2]) == p)]
        if rows:
            out.append({"id": pid, "title": title, "icon": icon, "sections": _sections(rows)})
    out.append({"id": "plugins", "title": "Plugins", "icon": "plugins", "sections": [
        {"title": "BetterFrame Keyboard", "rows": [KB_ROW] + [r for sc in _sections([x for x in _ours() if x[1] == "Keyboard"])
                                                             for r in sc["rows"]]}] + [
        {"title": "Pin to Head", "rows": [PIN_ROW]},
        {"title": "Streamer Mode", "rows": [STREAMER_ROW]}]})
    return out


def values():
    out = {k: v.get("v") for k, v in bfsettings.read_all().items() if "v" in v}
    out["plugin_keyboard"] = not os.path.exists(KB_OFF)
    out["streamer"] = os.path.exists(STREAMER)
    st, t = _UNINSTALL
    out["kb_uninstall"] = st if (st == "go" or time.time() - t < 5) else "idle"
    st, t = _RESET
    out["kb_reset"] = st if time.time() - t < (2 if st == "go" else 5) else "idle"
    return out


def streamer(on):
    """Streamer mode on/off: the keyboard notices by itself; Steam's pop-ups go off, and back to how they were after."""
    if on:
        if not os.path.exists(STREAMER_TOASTS):
            before = bfsettings.read_all().get("sc_no_toasts", {}).get("v")
            with open(STREAMER_TOASTS, "w") as f:
                json.dump(before, f)
        open(STREAMER, "w").close()
        bfsettings.write("sc_no_toasts", True)
    else:
        if os.path.exists(STREAMER):
            os.remove(STREAMER)
        try:
            with open(STREAMER_TOASTS) as f:
                before = json.load(f)
            os.remove(STREAMER_TOASTS)
        except Exception:
            before = None
        if before is not None:
            bfsettings.write("sc_no_toasts", bool(before))
    return "ok"


_UNINSTALL = ("idle", 0.0)      # (the Uninstall button: idle, confirm, go; and when it last changed)


def uninstall():
    """Settings > Keyboard > Uninstall: runs uninstall.sh on its own (outside the keyboard's service, which it stops)."""
    import subprocess
    script = os.path.join(HERE, "uninstall.sh")
    if not os.path.exists(script):
        return "no uninstall.sh"
    log = os.path.join(CONF, "uninstall.log")
    cmd = ["bash", "-c", 'bash "%s" > "%s" 2>&1' % (script, log)]
    try:
        subprocess.Popen(["systemd-run", "--user", "--collect", "--quiet"] + cmd,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        subprocess.Popen(["setsid"] + cmd, stdin=subprocess.DEVNULL, start_new_session=True)
    return "ok"


def apply(sid, value):
    if sid == "kb_uninstall":
        global _UNINSTALL
        if value == "go" and _UNINSTALL[0] == "go" and time.time() - _UNINSTALL[1] < 30:
            return "ok"   # (already started: the same click handed over again)
        _UNINSTALL = (value, time.time())
        return uninstall() if value == "go" else "ok"
    if sid == "kb_reset":   # the keyboard picks this up within a second
        global _RESET
        _RESET = (value, time.time())
        if value == "go":
            try:
                open(RESET_FLAG, "w").close()
            except OSError as ex:
                return "couldn't reset: %s" % ex
        return "ok"
    if sid == "streamer":
        return streamer(bool(value))
    if sid == "plugin_keyboard":
        if value and os.path.exists(KB_OFF):
            os.remove(KB_OFF)
        elif not value:
            open(KB_OFF, "w").close()
        return "ok"
    return bfsettings.write(sid, value)


def script():
    with open(os.path.join(HERE, "steampages.js")) as f:
        return f.read()


def put_in(url):
    have = dashpin.run_js(url, "window.__bfSteam ? window.__bfSteam.version : (window.__bfSteamWait ? -1 : 0)")
    if have == -1:
        return "waiting for Steam's Settings to load (they're added the moment it does)"
    if not isinstance(have, int) or have < 11:
        res = dashpin.run_js(url, script())
        if not str(res).startswith(("installed", "already")):
            return "couldn't add the pages: %s" % res
    if os.path.exists(NO_DIVIDER) or os.path.exists(KB_ONLY):
        dashpin.run_js(url, "window.__bfSteam && (__bfSteam.sep = false)")
    dashpin.run_js(url, "(__bfSteam.update(%s), __bfSteam.on = true, 'on')" % json.dumps({"pages": pages(), "merge": merge(), "top": ["keyboard"], "vals": values(),
                                                                        "fold": not os.path.exists(NO_FOLD) and not os.path.exists(KB_ONLY)}))
    return "ok"


# streamer mode, in SteamVR's menu and Steam's own pages: every profile picture shows Steam's happy face, your
# name shows as "User", other people's names too, and what friends are playing is hidden. (A style sheet and a
# small script put into each page; taken out again, and everything put back, when it's turned off)
HAPPY = "https://community.fastly.steamstatic.com/economy/emoticonlarge/steamhappy"
HIDE_CSS = """
img[src*="avatar" i], img[srcset*="avatar" i], [class*="avatar" i] img, [class*="Avatar"] img
  { content: url("%(h)s") !important; object-fit: contain !important; background: #2a3442 !important; }
[class*="avatar" i]:not(body):not(html) > [style*="background-image"], [style*="avatars." i], [style*="/avatar" i]
  { background-image: url("%(h)s") !important; background-size: contain !important; background-repeat: no-repeat !important;
    background-position: center !important; background-color: #2a3442 !important; }
/* one face per picture: animated pictures, frames and a second copy laid on top showed it twice, offset */
[class*="avatar" i] img ~ img, [class*="avatar" i] video, [class*="avatarframe" i], [class*="AvatarFrame"],
[class*="avatar_frame" i], img[src*="/items/" i], img[src*="avatarframe" i] { display: none !important; }
[class*="RichPresence" i], [class*="InGameName" i], [class*="PlayingGame" i], [class*="FriendGame" i]
  { visibility: hidden !important; }
#wishlist_item_count_value, #cart_item_count_value, [class*="WishlistCount" i], [class*="wishlist_count" i],
[class*="CartCount" i], [class*="cart_count" i], [class*="cartcount" i] { display: none !important; }
""" % {"h": HAPPY}
SHOW_AS = "Framer"
HIDE_JS = """(function(on, css, names, as){
var id='bf-streamer-hide', el=document.getElementById(id), W=window, mine=names.slice();
function who(tx){ return mine.indexOf(tx)>=0 ? as : 'Friend'; }   /* you: Framer; everyone else: Friend */
var NAME_CLS=/persona_?name|player_?name|account_?name|user_?name|friend_?name|nickname/i;
var LABEL=/friend\\s*code|steam\\s*id|account\\s*id|e-?mail|phone/i;
var STATUS=/\\b(online|offline|away|snooze|invisible|in-game|playing|busy|looking to)\\b/i;
var ONLY_STATUS=/^(online|offline|away|snooze|invisible|busy|in-game|playing .{1,40}|in .{1,40}|looking to .{1,30})$/i;
function nearProfile(e){ /* a very short name (one or two letters) only where a name sits: by a profile picture or a status */
  for(var k=0;e && k<3 && e!==document.body && e!==document.documentElement;k++, e=e.parentElement){
    var tx=(e.textContent||''); if(tx.length>120) break;
    if(e.querySelector && e.querySelector('img[src*="avatar" i],[class*="avatar" i]')) return true;
    if(STATUS.test(tx)) return true; }
  return false; }
function nearCard(e){ /* a profile picture in the same card, a few levels up */
  for(var k=0;e && k<5 && e!==document.body && e!==document.documentElement;k++, e=e.parentElement){
    if((e.textContent||'').length>200) break;
    var n=e.querySelectorAll ? e.querySelectorAll('img[src*="avatar" i],[class*="avatar" i],[style*="avatars." i],[style*="/avatar" i]').length : 0;
    if(n===1) return true;   /* one picture: this card's own */
    if(n>1) return false; }  /* several: gone past the card into a list of them */
  return false; }
function popup(e){ /* something that pops up holding nothing but your name (the hover label under your picture): Framer */
  var tx=(e.textContent||'').trim(); if(!tx || tx===as) return;
  if(names.indexOf(tx)<0) return;
  var w=document.createTreeWalker(e, NodeFilter.SHOW_TEXT), n; while((n=w.nextNode())){
    if(n.nodeValue.trim()===tx){ rec([n,n.nodeValue]); n.nodeValue=n.nodeValue.replace(tx,as); } } }
function rec(x){ (W.__bfOrig=W.__bfOrig||[]).push(x); }
function swap(t){ var v=t.nodeValue; if(!v||!v.trim()) return; var o=v;
  for(var i=0;i<names.length;i++){ var nm=names[i]; if(!nm) continue;
    if(nm.length>=3){ if(v.indexOf(nm)>=0) v=v.split(nm).join(as); }
    else if(v.trim()===nm && nearProfile(t.parentElement)) v=v.replace(nm,as); }
  v=v.replace(/\\b7656\\d{13}\\b/g,'\\u2022\\u2022\\u2022\\u2022\\u2022\\u2022').replace(/[\\w.+-]+@[\\w-]+\\.[\\w.]+/g,'\\u2022\\u2022\\u2022\\u2022@\\u2022\\u2022\\u2022');
  var p=t.parentElement, ctx=p ? ((p.parentElement||p).textContent||'') : '';
  /* whatever sits right above "Online"/"Away"/... next to a profile picture is a name, whatever it is */
  if(v===o && p && v.trim().length<=32 && v.trim()!==as && v.trim()!=='Friend'){
    var sib=p.nextElementSibling || (p.parentElement && p.parentElement.nextElementSibling);
    if(sib && /^\\s*(online|offline|away|snooze|invisible|busy|in-game|playing\\b.*)\\s*$/i.test(sib.textContent||'') && nearProfile(p)) v=who(v.trim()); }
  /* a friend's name on a card (Library search's Friends, and the like): a short label right after a little person icon,
     in a card with a profile picture */
  if(v===o && p && v.trim().length>0 && v.trim().length<=32 && v.trim()!==as && v.trim()!=='Friend'){
    var ic=t.previousSibling, pe=p.previousElementSibling;
    var isIcon=function(x){ return x && x.nodeType===1 && (x.tagName.toLowerCase()==='svg' || (x.querySelector && x.querySelector('svg') && !(x.textContent||'').trim())); };
    if((isIcon(ic) || isIcon(pe)) && nearCard(p)) v=who(v.trim()); }
  if(LABEL.test(ctx) && ctx.length<120) v=v.replace(/\\d{5,}/g,'\\u2022\\u2022\\u2022\\u2022\\u2022\\u2022');
  /* the store's wishlist and cart counts: gone */
  if(p && p.closest && p.closest('a[href*="/wishlist" i],a[href*="/cart" i],#wishlist_link,#cart_link,#cart_status_data,[class*="WishlistLink" i],[class*="CartLink" i],[class*="CartButton" i]'))
    v=v.replace(/\\(?\\d+\\)?/g,'');
  if(v!==o){ rec([t,o]); t.nodeValue=v; } }
function nameEl(e){ /* a name element (coloured names are one piece per letter, nicknames add "(name)"): one plain name */
  if(!e.className || typeof e.className!=='string' || !NAME_CLS.test(e.className)) return;
  var tx=(e.textContent||'').trim(); if(!tx || tx===as || tx.length>64) return;
  if(e.querySelector('img,svg,button,input')) return;
  rec([e,null,e.innerHTML]); e.textContent=/^\\(.*\\)$/.test(tx) ? '' : as; }
function attrs(root){ if(!root.querySelectorAll) return; root.querySelectorAll('[title],[alt],[aria-label],[data-tooltip-text]').forEach(function(e){
    ['title','alt','aria-label','data-tooltip-text'].forEach(function(a){ var v=e.getAttribute(a); if(!v) return; var o=v;
      names.forEach(function(nm){ if(!nm) return; if(nm.length>=3){ if(v.indexOf(nm)>=0) v=v.split(nm).join(as); }
        else if(v.trim()===nm) v=as; });
      if(NAME_CLS.test(e.className||'') && v!==as) v=as;
      if(v!==o){ rec([e,a,o]); e.setAttribute(a,v); } }); }); }
function byStatus(root){ /* the name right above "Online", "Away"... next to a profile picture: that's a name, whatever it
  is and whatever Steam calls its box (it learns your real name from it, to hide it everywhere else too) */
  var all=[root].concat(Array.prototype.slice.call(root.querySelectorAll('*')));
  all.forEach(function(st){ if(st.children.length) return; var stx=(st.textContent||'').trim();
    if(!stx || stx.length>40 || !ONLY_STATUS.test(stx)) return;
    var nm=st.previousElementSibling; if(!nm && st.parentElement) nm=st.parentElement.previousElementSibling;
    if(!nm) return; var tx=(nm.textContent||'').trim();
    if(!tx || tx===as || tx==='Friend' || tx.length>40 || NOT_NAME.test(tx) || nm.querySelector('img,svg,input,button')) return;
    if(!nearProfile(nm)) return;
    rec([nm,null,nm.innerHTML]); nm.textContent=who(tx); }); }
/* lines that are about someone, never a name (a name can have digits or any word in it: "100°c", "Snowman") */
var NOT_NAME=/^(online|offline|away|snooze|invisible|busy|in-?game|playing\\b.*|now playing.*|last online.*|.*\\bago|.*played recently|[\\d.,]+\\s*(hrs?|hours?|mins?|minutes?|days?)\\b.*|in library|friends?|\\d+\\s+friends?\\b.*|(online|offline) friends.*|select a friend.*|[\\d\\s:./,-]+\\s*([ap]\\.?m\\.?)?)$/i;   /* (also a time or date: the clock by your picture is never a name) */
function tiles(root){ /* a person's tile (profile picture, name, a line about them): its first bit of text is their name */
  var avs=Array.prototype.slice.call(root.querySelectorAll('img[src*="avatar" i],[class*="avatar" i]'));
  if(root.matches && root.matches('img[src*="avatar" i],[class*="avatar" i]')) avs.push(root);
  avs.forEach(function(av){
    /* the closest box around the picture that has any words in it: the picture with its name (not the whole card, where
       a game's title came first and hid the name after it) */
    var tile=null, e=av.parentElement;
    for(var k=0;e && k<4 && e!==document.body;k++, e=e.parentElement){
      if((e.textContent||'').length>160 || e.querySelectorAll('img[src*="avatar" i]').length>1) break;   /* (one person only: never a row of them) */
      if((e.textContent||'').trim()){ tile=e; break; } }
    if(!tile) return;
    var w=document.createTreeWalker(tile, NodeFilter.SHOW_TEXT), n;
    while((n=w.nextNode())){ var tx=n.nodeValue.trim(); if(!tx || /^[|\\u2022\\u00b7:,-]$/.test(tx)) continue;
      if(tx===as || tx==='Friend' || tx.length>40) break;
      if(NOT_NAME.test(tx)) continue;          /* a line about them ("Online", "3 days ago"): their name is further on */
      rec([n,n.nodeValue]); n.nodeValue=n.nodeValue.replace(tx, who(tx)); break; } }); }
function walk(root){
  if(root.nodeType===1){ byStatus(root); tiles(root); nameEl(root); root.querySelectorAll('[class]').forEach(nameEl); attrs(root);
    if(root.hasAttribute && root.hasAttribute('title')) attrs(root.parentElement||root); }
  var w=document.createTreeWalker(root, NodeFilter.SHOW_TEXT), n; while((n=w.nextNode())) swap(n); }
if(!on){ if(el) el.remove(); if(W.__bfObs){ W.__bfObs.disconnect(); W.__bfObs=null; } W.__bfVer=0;
  (W.__bfOrig||[]).reverse().forEach(function(x){ if(!x[0].isConnected) return;
    if(x.length===2) x[0].nodeValue=x[1]; else if(x[1]===null) x[0].innerHTML=x[2]; else x[0].setAttribute(x[1],x[2]); });
  W.__bfOrig=[]; return 'off'; }
if(!el){ el=document.createElement('style'); el.id=id; (document.head||document.documentElement).appendChild(el); }
if(el.textContent!==css) el.textContent=css;
if(W.__bfObs && W.__bfVer!==3){ W.__bfObs.disconnect(); W.__bfObs=null; }   /* (an older version's watcher: replaced) */
W.__bfVer=3;
if(document.body){ walk(document.body);
  if(W.__bfObs && W.__bfObsV!==6){ W.__bfObs.disconnect(); W.__bfObs=null; }   /* an older BetterFrame's: replaced */
  if(!W.__bfObs){ W.__bfObsV=6; W.__bfObs=new MutationObserver(function(ms){ ms.forEach(function(m){
      if(m.type==='characterData'){ swap(m.target); var pe=m.target.parentElement; if(pe) nameEl(pe); }
      else if(m.type==='attributes'){ attrs(m.target.parentElement||m.target); }
      else m.addedNodes.forEach(function(n){ if(n.nodeType===3){ swap(n); if(n.parentElement) nameEl(n.parentElement); } else if(n.nodeType===1){ popup(n); walk(n); } }); }); });
    W.__bfObs.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['title','aria-label','data-tooltip-text']}); } }
return 'on'; })(%s, %s, %s, %s)"""


def my_names():
    """Your Steam name and account name (from Steam's list of who's logged in), to show as "User"."""
    import re
    for path in ("~/.local/share/Steam/config/loginusers.vdf", "~/.steam/steam/config/loginusers.vdf"):
        try:
            with open(os.path.expanduser(path), encoding="utf-8", errors="replace") as f:
                txt = f.read()
        except OSError:
            continue
        blocks = re.findall(r'"\d{17}"\s*\{([^{}]*)\}', txt)
        def get(b, k):
            m = re.search(r'"%s"\s*"([^"]*)"' % k, b, re.I)
            return m.group(1) if m else ""
        pick = [b for b in blocks if get(b, "MostRecent") == "1"] or blocks
        out = []
        for b in pick[:1]:
            out += [get(b, "PersonaName"), get(b, "AccountName")]
        # (the login list keeps the name you had when you last signed in: your current one is in your own settings)
        import glob as _g
        for lc in _g.glob(os.path.expanduser("~/.local/share/Steam/userdata/*/config/localconfig.vdf")):
            try:
                with open(lc, encoding="utf-8", errors="replace") as f:
                    m = re.search(r'"PersonaName"\s*"([^"]*)"', f.read())
                if m:
                    out.append(m.group(1))
            except OSError:
                pass
        return list(dict.fromkeys(n for n in out if n.strip()))      # (a name can be a single letter: "r")
    return []


def _targets():
    """Every Steam and SteamVR page that draws something (not the hidden script contexts)."""
    import urllib.request
    out = []
    for port in (8080, dashpin.PORT):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json" % port, timeout=2) as r:
                for t in json.load(r):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl") and t.get("title") != "SharedJSContext":
                        out.append(t["webSocketDebuggerUrl"])
        except Exception:
            pass
    return out


class Hider(threading.Thread):
    """Streamer mode: keeps profile pictures and names hidden in every page (new windows included), every 3 s."""
    def __init__(self, log=print):
        super().__init__(daemon=True, name="streamer-hide")
        self.log, self.was = log, False

    def preload(self, urls, names):
        """Also registered to run as each page loads, before it draws anything: so after the headset wakes up, or a
        page reloads, your name and picture never show even for a moment. (Kept on a connection of its own per
        page: Steam forgets the registration when that connection closes, so turning streamer mode off closes it)"""
        pre = self.__dict__.setdefault("pre", {})
        for u in list(pre):
            if u not in urls:
                try:
                    pre.pop(u).close()
                except Exception:
                    pass
        if not urls:
            return
        src = ("(function(){function go(){ %s } if(document.body) go(); else document.addEventListener('DOMContentLoaded', go);})()"
               % (HIDE_JS % ("true", json.dumps(HIDE_CSS), json.dumps(names), json.dumps(SHOW_AS))))
        for u in urls:
            if u in pre:
                continue
            try:
                ws = dashpin.WS(u)
                ws.s.settimeout(4)
                # (the page's events have to be on for it to run scripts as pages load)
                ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
                ws.send(json.dumps({"id": 2, "method": "Page.addScriptToEvaluateOnNewDocument", "params": {"source": src}}))
                for _ in range(50):
                    try:
                        r = json.loads(ws.recv())
                    except ValueError:
                        continue
                    if r.get("id") == 2:
                        break
                ws.s.settimeout(None)
                pre[u] = ws

                def drain(w=ws):          # (the page's events are read and dropped, so nothing ever backs up)
                    try:
                        while True:
                            w.recv()
                    except Exception:
                        pass
                threading.Thread(target=drain, daemon=True, name="streamer-drain").start()
            except Exception as ex:
                self.log("streamer mode: couldn't set it up to run as a page loads (%s)" % ex)
                pre[u] = None          # (not tried again for this page)

    def run(self):
        time.sleep(8)
        done = set()
        while True:
            on = os.path.exists(STREAMER)
            if on and not getattr(self, "names", None):
                self.names = my_names()
            names = getattr(self, "names", None) or []
            if on or self.was:
                try:
                    urls = _targets()
                    self.preload(urls if on else [], names)
                    for u in urls:
                        if on and u in done:
                            continue
                        try:
                            dashpin.run_js(u, HIDE_JS % ("true" if on else "false", json.dumps(HIDE_CSS), json.dumps(names), json.dumps(SHOW_AS)))
                            if on:
                                done.add(u)
                        except Exception:
                            dashpin.forget(u)
                    if on:
                        done &= set(urls)       # (closed pages forgotten; a page reloaded gets it again below)
                        for u in list(done):
                            try:
                                if dashpin.run_js(u, "document.getElementById('bf-streamer-hide') ? 1 : 0") != 1:
                                    done.discard(u)
                            except Exception:
                                done.discard(u)
                    else:
                        done.clear()
                    if on != self.was:
                        self.log("streamer mode: profile pictures and names %s" % ("hidden" if on else "shown again"))
                    self.was = on
                except Exception as ex:
                    self.log("streamer mode: couldn't reach Steam's pages (%s)" % ex)
            # (new windows looked for twice a second when it's on: a page you open is covered before you see it)
            time.sleep(0.25 if on else 3)


class Keeper(threading.Thread):
    """Inside the keyboard service: keeps the pages in Steam's Settings and carries out changes made there."""
    def __init__(self, log=print):
        super().__init__(daemon=True, name="steampages")
        self.log, self.said = log, None

    def note(self, msg):
        if msg != self.said:
            self.log("steam settings pages: " + msg)
            self.said = msg

    def run(self):
        """Almost idle unless Steam's Settings is open on one of our pages: then changes are picked up
        4 times a second and the values shown kept fresh."""
        time.sleep(10)
        last_check, last_vals, was_open, missing = 0, 0, False, 0
        while True:
            time.sleep(0.25 if was_open else 1.0)
            if not os.path.exists(ON):
                was_open = False
                continue
            try:
                url = dashpin.steam_page()
                now = time.time()
                if not url:
                    missing = missing or now
                    if now - missing > 60:
                        self.note("waiting: Steam's interface isn't reachable (CEF remote debugging off?)")
                    continue
                missing = 0
                if now - last_check > (5 if self.said == "added" else 2):
                    last_check = now
                    # (an older copy of the page script, from before an update: replaced, or its changes wouldn't be read)
                    state = dashpin.run_js(url, "window.__bfSteam ? (__bfSteam.on && __bfSteam.version >= 11 ? 'on' : 'off') : 'missing'")
                    # the settings list changed (an update added or renamed settings): hand Steam the new one too. (It
                    # was only ever handed over once, so after an update Steam kept showing the old list)
                    sig = json.dumps([pages(), merge()], sort_keys=True, default=str)
                    if state != "on" or sig != getattr(self, "sent_sig", None):
                        res = put_in(url)
                        self.note("added" if res == "ok" else res)
                        if res == "ok":
                            self.sent_sig = sig
                        last_vals = now
                got = dashpin.run_js(url, "window.__bfSteam ? JSON.stringify(Object.assign({open: __bfSteam.subs.size}, __bfSteam.take())) : ''")
                try:
                    got = json.loads(got) if isinstance(got, str) and got else {}
                except ValueError:
                    self.note("unexpected answer from Steam: %r" % str(got)[:200])
                    got = {}
                if not isinstance(got, dict):
                    got = {}
                writes = got.get("w") or {}
                for sid, value in writes.items():
                    res = apply(sid, value)
                    if res != "ok":
                        self.log("steam settings pages: %s -> %s" % (sid, res))
                    else:
                        self.log("steam settings pages: %s = %s" % (sid, value))
                if writes:   # saved: now the page can let them go
                    dashpin.run_js(url, "window.__bfSteam && __bfSteam.ack && __bfSteam.ack(%d)" % int(got.get("seq") or 0))
                is_open = bool(got.get("open"))
                if is_open and (writes or not was_open or now - last_vals > 2):
                    last_vals = now
                    dashpin.run_js(url, "window.__bfSteam && __bfSteam.update(%s)" % json.dumps({"vals": values()}))
                was_open = is_open
            except Exception as ex:
                import traceback
                tb = traceback.extract_tb(ex.__traceback__)
                where = ", ".join("%s:%d" % (os.path.basename(f.filename), f.lineno) for f in tb[-3:])
                self.note("error: %s (%s) %s" % (ex, where, ("odd message: %r" % dashpin.LAST_ODD) if dashpin.LAST_ODD else ""))
                time.sleep(2)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    os.makedirs(CONF, exist_ok=True)
    url = dashpin.steam_page()
    if cmd == "on":
        open(ON, "w").close()
        print(put_in(url) if url else "Steam's interface isn't reachable right now; the pages will be added when it is.")
    elif cmd == "off":
        if os.path.exists(ON):
            os.remove(ON)
        print(dashpin.run_js(url, "window.__bfSteam ? __bfSteam.undo() : 'not in'") if url else "off")
    elif cmd == "streamer" and len(sys.argv) > 2:
        print("streamer mode", sys.argv[2], streamer(sys.argv[2] == "on"))
    elif cmd == "probe":
        if not url:
            print("Steam's interface isn't reachable")
            return
        print(dashpin.run_js(url, "(function(){var o = window.SteamClient && SteamClient.OpenVR; if (!o) return 'no SteamClient.OpenVR';"
                                  " var out = {OpenVR: Object.keys(o)}; for (var k in o) { try { if (o[k] && typeof o[k] === 'object')"
                                  " out[k] = Object.keys(o[k]); } catch (e) {} } return JSON.stringify(out); })()"))
    elif cmd in ("divider", "fold") and len(sys.argv) > 2:
        flag = NO_DIVIDER if cmd == "divider" else NO_FOLD
        if sys.argv[2] == "off":
            open(flag, "w").close()
        elif os.path.exists(flag):
            os.remove(flag)
        if url:   # put the pages back in fresh with the new choice
            dashpin.run_js(url, "window.__bfSteam ? __bfSteam.undo() : ''")
            print(put_in(url))
        print("%s %s" % (cmd, sys.argv[2]))
    else:
        print(dashpin.run_js(url, "window.__bfSteam ? JSON.stringify({version: __bfSteam.version, on: __bfSteam.on, injected: __bfSteam.injected,"
                                  " errors: __bfSteam.errors, lastError: __bfSteam.lastError, divider: __bfSteam.sep, fold: __bfSteam.fold,"
                                  " found: __bfSteam.found, pages: __bfSteam.pages.length, steamPages: __bfSteam.keys}) : 'not in'")
              if url else "Steam's interface isn't reachable")


if __name__ == "__main__":
    main()
