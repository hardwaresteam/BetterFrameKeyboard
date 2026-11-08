"""Fade when not aiming: the keyboard is solid and takes the lasers only while both controllers point at it.

Aim one controller away and the keyboard turns see-through and lets the lasers pass through it to whatever is
behind (the Steam menu, a window, a game). Point both back at it and it's solid and typeable again.

SteamVR only tells an overlay about a laser while that overlay takes laser input, so while the keyboard is
see-through it watches the controllers itself: each controller's ray, at the angle SteamVR's own laser leaves it
(learned while you type, and remembered between sessions), tested against the keyboard.

A small button on the keyboard's bottom edge (its own overlay, so it always takes the laser) turns the whole
feature on and off. So does Steam's Settings > Keyboard > Fade when not aiming.

Mixed into overlay.App (see `class App(AimFade)`): it uses the App's SteamVR handles and helpers.
"""
import json
import math
import os
import time

PREFS_NAME = "prefs.json"
TOG_PX = 128                  # the button's picture (square)
FADE_S = 0.18                 # seconds to fade between solid and see-through
LEAVE_S = 0.2                 # a laser has to be off the keyboard this long before it fades (no flicker at its edges)
OPEN_GRACE_S = 0.75           # just opened: stays solid this long, so there's time to bring both hands up
PAD_GRACE_S = 8.0             # typing with a game controller's trackpads: stays solid (the VR controllers may be lying anywhere)
DEFAULT_AIM = (0.0, -0.42, -0.907)   # where SteamVR's laser leaves a controller, in its own frame, until it's been learned
LOOSE_PX = 60                 # while solid, a laser this close to the edge (in keyboard pixels) still counts as on it

# overlay.py's own helpers, handed over with bind() (overlay.py runs as __main__, so importing it here would
# load a second copy of it, with its own colours)
H = {}


def bind(**helpers):
    H.update(helpers)


def _norm(v):
    n = math.sqrt(sum(a * a for a in v)) or 1.0
    return [a / n for a in v]


class AimFade:
    # ------------------------------------------------------------------ setup
    def aim_init(self):
        """Called from start_vr (again after every reconnect): the button overlay and fresh state."""
        vr = self.vr
        self.aim_on = getattr(self, "aim_on", True)        # (Settings > Keyboard; read in load_look)
        self.aim_op = getattr(self, "aim_op", 0.25)        # how visible it is while faded
        self.aim_passive = False
        self.aim_a, self.aim_a_sent, self.aim_prev_t = 1.0, None, time.time()
        self.aim_off_since, self.aim_grace, self.aim_check_t, self.aim_away = None, 0.0, 0.0, False
        self.aim_role = {}
        for h in list(self.kbs) + [self.wing]:   # (after a reconnect: every copy takes the laser again)
            self.aim_apply_input(h, False)
        if not hasattr(self, "aim_dirs"):
            self.aim_dirs = {k: list(v) for k, v in (self.conf.get("aim_dirs") or {}).items()
                             if isinstance(v, (list, tuple)) and len(v) == 3}
            self.aim_dirs_saved, self.aim_save_t = dict(self.aim_dirs), 0.0
        self.aim_tog, self.aim_tog_pic, self.aim_tog_shown = None, None, False
        try:
            h = self.ov.createOverlay("betterframe.keyboard.aimtoggle", "BetterFrame Keyboard fade button")
            self.ov.setOverlayInputMethod(h, vr.VROverlayInputMethod_Mouse)
            self.ov.setOverlayFlag(h, vr.VROverlayFlags_MakeOverlaysInteractiveIfVisible, True)
            self.ov.setOverlayMouseScale(h, vr.HmdVector2_t(TOG_PX, TOG_PX))
            self.ov.setOverlayWidthInMeters(h, 0.03)
            self.set_sort(h, 12)
            self.aim_tog = h
            self.aim_draw_toggle()
        except Exception as ex:
            self.aim_tog = None
            self.log_aim("fade button unavailable:", ex)

    def log_aim(self, *a):
        print("[overlay]", *a, flush=True)

    def aim_alpha(self):
        """The keyboard's alpha right now (1 when solid). Everything that sets the keyboard's alpha goes through this."""
        return getattr(self, "aim_a", 1.0)

    def aim_apply_input(self, h, passive=None):
        """Laser input on (solid) or off (see-through: the lasers pass through to what's behind)."""
        vr = self.vr
        if passive is None:
            passive = getattr(self, "aim_passive", False)
        try:
            self.ov.setOverlayInputMethod(h, getattr(vr, "VROverlayInputMethod_None", 0) if passive
                                          else vr.VROverlayInputMethod_Mouse)
            self.ov.setOverlayFlag(h, vr.VROverlayFlags_MakeOverlaysInteractiveIfVisible, not passive)
        except Exception as ex:
            self.log_aim("couldn't change the keyboard's laser input:", ex)

    # ------------------------------------------------------------------ the button
    def aim_draw_toggle(self):
        if not getattr(self, "aim_tog", None):
            return
        pal = H["pal"]()   # (the colours of the current theme)
        want = (bool(self.aim_on), tuple(pal["on"]), tuple(pal["bar"]), getattr(self, "look_gen", 0))
        if want == self.aim_tog_pic:
            return
        from PIL import Image, ImageDraw
        k = 4   # drawn four times larger and scaled down: smooth edges
        S = TOG_PX * k
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        on = bool(self.aim_on)
        bg = tuple(pal["on"][:3]) + (235,) if on else tuple(pal["bar"][:3]) + (235,)
        d.rounded_rectangle((4 * k, 4 * k, S - 4 * k, S - 4 * k), radius=30 * k, fill=bg, outline=(255, 255, 255, 70), width=3 * k)
        white = (255, 255, 255, 255) if on else (190, 198, 208, 255)
        # a little keyboard at the top, with two lasers coming up to it from below: "both lasers on it"
        kx0, ky0, kx1, ky1 = 34 * k, 26 * k, 94 * k, 56 * k
        d.rounded_rectangle((kx0, ky0, kx1, ky1), radius=6 * k, outline=white, width=5 * k)
        for i in range(4):
            x = 44 * k + i * 13 * k
            d.rectangle((x - 2 * k, 35 * k, x + 2 * k, 39 * k), fill=white)
        d.rectangle((50 * k, 45 * k, 78 * k, 48 * k), fill=white)
        for (x0, y0), (x1, y1) in (((24 * k, 106 * k), (52 * k, 60 * k)), ((104 * k, 106 * k), (76 * k, 60 * k))):
            d.line((x0, y0, x1, y1), fill=white, width=6 * k)
            d.ellipse((x1 - 6 * k, y1 - 6 * k, x1 + 6 * k, y1 + 6 * k), fill=white)
        if not on:   # off: struck through
            d.line((26 * k, 26 * k, 102 * k, 102 * k), fill=tuple(pal.get("slash", (235, 87, 87, 255))), width=9 * k)
        img = img.resize((TOG_PX, TOG_PX), Image.LANCZOS)
        self.upload_raw(self.aim_tog, img)
        self.aim_tog_pic = want

    def aim_place_toggle(self):
        """On the keyboard's bottom edge, between the turn handle and the move bar (follows it when it moves)."""
        h = getattr(self, "aim_tog", None)
        if not h or self.img_size[0] <= 1 or not getattr(self, "grab", None):
            return
        rb = getattr(self.renderer, "metrics", {}).get("rotate")
        if not rb:
            return
        cy = (rb[1] + rb[3]) / 2
        cx = (rb[2] + self.grab[0]) / 2
        size_px = (rb[3] - rb[1]) * 1.25
        s = self.width_m / self.img_size[0]
        try:
            pos, RR = self.local_point("main", cx, cy, z=0.004)   # (a few mm in front of the keys, so it's always hit first)
            self.ov.setOverlayWidthInMeters(h, max(0.015, size_px * s))
            self.ov.setOverlayTransformAbsolute(h, self.vr.TrackingUniverseStanding, H["make_matrix"](self.vr, pos, RR))
            self.aim_tog_box = (cx - size_px / 2, cy - size_px / 2, cx + size_px / 2, cy + size_px / 2)
        except Exception as ex:
            self.log_aim("couldn't place the fade button:", ex)

    def aim_on_visible(self, on):
        """The keyboard opened or closed."""
        if not hasattr(self, "aim_passive"):
            return
        if on:
            self.aim_grace = time.time() + OPEN_GRACE_S
            if self.aim_tog:
                self.aim_place_toggle()
                self.aim_draw_toggle()
                self.ov.showOverlay(self.aim_tog)
                self.aim_tog_shown = True
        else:
            if self.aim_tog:
                self.ov.hideOverlay(self.aim_tog)
                self.aim_tog_shown = False
            self.aim_set_passive(False)
            self.aim_a, self.aim_a_sent = 1.0, None   # (opens solid next time)
            self.aim_save_dirs(force=True)

    def aim_events(self, ev):
        """The button's laser events (it always takes the laser, even while the keyboard is see-through)."""
        h = getattr(self, "aim_tog", None)
        while h:
            ok, e = self.ov.pollNextOverlayEvent(h, ev)
            if not ok:
                break
            if e.eventType == self.vr.VREvent_MouseButtonDown and self.visible:
                self.aim_toggle_feature()

    def aim_toggle_feature(self):
        self.aim_on = not self.aim_on
        self.log_aim("fade when not aiming:", "on" if self.aim_on else "off", "(the keyboard's button)")
        path = os.path.join(os.path.expanduser("~/.config/betterframe-keyboard"), PREFS_NAME)
        try:   # the same setting as Steam's Settings > Keyboard > Fade when not aiming
            try:
                with open(path) as f:
                    p = json.load(f)
            except Exception:
                p = {}
            p["kb_aimfade"] = bool(self.aim_on)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w") as f:
                json.dump(p, f)
            os.replace(path + ".tmp", path)
        except Exception as ex:
            self.log_aim("couldn't save the fade setting:", ex)
        self.aim_draw_toggle()
        self.flash("Fade when not aiming: " + ("on" if self.aim_on else "off"))
        if self.st.get("sounds"):
            try:
                self.sounds.play("key")
            except Exception:
                pass

    def aim_prefs(self, p):
        """From load_look: Settings > Keyboard > Fade when not aiming / How visible when faded."""
        on = bool(p.get("kb_aimfade", True))
        try:
            op = max(0.0, min(1.0, float(p.get("kb_aimfade_op", 25)) / 100.0))
        except (TypeError, ValueError):
            op = 0.25
        if on != getattr(self, "aim_on", None) or abs(op - getattr(self, "aim_op", -1)) > 1e-3:
            self.log_aim("fade when not aiming:", "on" if on else "off", "(%d%% visible when faded)" % round(op * 100))
        self.aim_on, self.aim_op = on, op
        self.aim_draw_toggle()

    # ------------------------------------------------------------------ the controllers' rays
    def aim_learn(self, dev, loc):
        """SteamVR's laser was just seen on the keyboard: remember its angle on this hand's controller."""
        name = self.aim_role.get(dev) if hasattr(self, "aim_role") else None
        if name is None:
            try:
                vr = self.vr
                r = self.system.getControllerRoleForTrackedDeviceIndex(dev)
                name = {vr.TrackedControllerRole_LeftHand: "left", vr.TrackedControllerRole_RightHand: "right"}.get(r)
            except Exception:
                name = None
        if name and hasattr(self, "aim_dirs"):
            self.aim_dirs[name] = [round(a, 4) for a in _norm(loc)]

    def aim_save_dirs(self, force=False):
        if not hasattr(self, "aim_dirs") or self.aim_dirs == self.aim_dirs_saved:
            return
        now = time.time()
        if not force and now - self.aim_save_t < 20:
            return
        self.aim_save_t = now
        self.conf["aim_dirs"] = dict(self.aim_dirs)
        self.aim_dirs_saved = dict(self.aim_dirs)
        try:
            H["save_conf"](self.conf)
        except Exception:
            pass

    def aim_dir_local(self, dev, name):
        c = self.lcal.get(dev)
        if c:
            return c[0]
        if name in self.aim_dirs:
            return self.aim_dirs[name]
        other = self.aim_dirs.get("right" if name == "left" else "left")
        if other:   # only the other hand's known: its mirror image
            return [-other[0], other[1], other[2]]
        return list(DEFAULT_AIM)

    def aim_rays(self):
        """(device, hand, origin, direction) for each hand controller that's tracked right now."""
        vr = self.vr
        ps = self.poses()
        out = []
        for role, name in ((vr.TrackedControllerRole_LeftHand, "left"), (vr.TrackedControllerRole_RightHand, "right")):
            try:
                dev = self.system.getTrackedDeviceIndexForControllerRole(role)
            except Exception:
                continue
            if dev == vr.k_unTrackedDeviceIndexInvalid or not 0 < dev < vr.k_unMaxTrackedDeviceCount:
                continue
            p = ps[dev]
            if not p.bPoseIsValid or not p.bDeviceIsConnected or self.is_eye_pointer(dev):
                continue
            o, r = H["mat_to_pos_rot"](p.mDeviceToAbsoluteTracking.m)
            self.aim_role[dev] = name
            loc = self.aim_dir_local(dev, name)
            d = [r[i][0] * loc[0] + r[i][1] * loc[1] + r[i][2] * loc[2] for i in range(3)]
            out.append((dev, name, tuple(o), tuple(d)))
        return out

    def aim_hits(self, o, d, loose):
        """Does this ray hit the keyboard? SteamVR's own test first (it knows the curve), then our own plane test
        (with a margin while solid, so a laser right at the edge doesn't make it flicker)."""
        vr = self.vr
        try:
            params = vr.VROverlayIntersectionParams_t()
            params.vSource.v[0], params.vSource.v[1], params.vSource.v[2] = o
            params.vDirection.v[0], params.vDirection.v[1], params.vDirection.v[2] = d
            params.eOrigin = vr.TrackingUniverseStanding
            for h in [self.handle] + ([self.aim_tog] if self.aim_tog else []):
                ok, _ = self.ov.computeOverlayIntersection(h, params)
                if ok:
                    return True
        except Exception:
            pass
        hit = self.ray_to_px(o, d)
        if not hit:
            return False
        m = LOOSE_PX if loose else 0
        W, H = self.img_size
        return -m <= hit[0] <= W + m and -m <= hit[1] <= H + m

    def aim_busy(self):
        """In the middle of something with the laser (a held key, a swipe, moving it): never fade then."""
        now = time.time()
        if self.drag or self.swipes or self.flicks or self.ehold or self.repeat:
            return True
        if any(v is not None for v in self.held.values()) and now - self.last_touch < 1.5:
            return True
        if now - max(self.__dict__.get("pad_press_t", {}).values(), default=0) < PAD_GRACE_S:
            return True
        try:
            if self.gaze.on():   # typing by looking: no lasers needed
                return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------ every frame
    def aim_set_passive(self, passive):
        if passive == getattr(self, "aim_passive", False):
            return
        self.aim_passive = passive
        for h in list(self.kbs) + [self.wing]:
            self.aim_apply_input(h, passive)
        if passive:   # nothing stays lit under a laser that's gone
            self.hover = None
            for sl in list(self.hovers):
                if self.hovers[sl] is not None:
                    self.hovers[sl] = None
            self.place_highlight()
            self.aim_save_dirs()
        self.aim_off_since = None
        if time.time() - getattr(self, "aim_said", 0) > 5:
            self.aim_said = time.time()
            self.log_aim("keyboard", "see-through (a laser looked away)" if passive else "solid (both lasers on it)")

    def aim_tick(self):
        if not hasattr(self, "aim_passive"):
            return
        now = time.time()
        dt, self.aim_prev_t = now - self.aim_prev_t, now
        if not (self.visible and self.aim_on) or now < self.aim_grace or self.aim_busy():
            self.aim_set_passive(False)
        elif now - self.aim_check_t >= 1 / 60:
            self.aim_check_t = now
            try:
                rays = self.aim_rays()
            except Exception as ex:
                rays = []
                self.report_error(ex)
            # every hand controller that's tracked has to point at it (just one controller on: that one)
            away = bool(rays) and not all(self.aim_hits(o, d, loose=not self.aim_passive) for _, _, o, d in rays)
            if not away:
                self.aim_set_passive(False)
            elif not self.aim_passive:
                if self.aim_off_since is None:
                    self.aim_off_since = now
                elif now - self.aim_off_since >= LEAVE_S:
                    self.aim_set_passive(True)
        # fade toward solid or see-through
        target = self.aim_op if self.aim_passive else 1.0
        if abs(self.aim_a - target) > 1e-4:
            step = max(0.0, min(dt, 0.1)) / FADE_S
            self.aim_a = min(target, self.aim_a + step) if self.aim_a < target else max(target, self.aim_a - step)
        words = getattr(self, "words_ov", None)
        if (self.aim_a != self.aim_a_sent or words != getattr(self, "aim_words_sent", None)) and self.visible:
            self.aim_a_sent, self.aim_words_sent = self.aim_a, words   # (a word bar made since: faded to match)
            try:
                if not getattr(self, "fade", None):   # (switching layouts: update_fade sets it, scaled by this)
                    self.ov.setOverlayAlpha(self.handle, self.aim_a)
                if getattr(self, "words_ov", None):
                    self.ov.setOverlayAlpha(self.words_ov, self.aim_a)
                if getattr(self, "wing_shown", False):
                    self.ov.setOverlayAlpha(self.wing, self.aim_a)
            except Exception as ex:
                self.report_error(ex)
