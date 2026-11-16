"""Both-hands input for the BetterFrame Keyboard overlay.

SteamVR's own overlay laser belongs to one hand at a time, so typing with two
hands loses clicks while it switches. Here each hand gets its own aim ray and
its own trigger reading, read every frame:

  1. SteamVR Input (input/actions.json, with bindings for frame_controller)
  2. if that isn't delivering anything, the older controller-state API

Config "two_hands": "auto" (default), "actions", "legacy" or "off".
"""
import math
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))


class Hand:
    def __init__(self, name):
        self.name = name
        self.dev = None
        self.src = 0
        self.origin = None
        self.dir = None
        self.rot = None
        self.value = 0.0
        self.down = False
        self.pressed = False
        self.released = False

    @property
    def ok(self):
        return self.origin is not None


def _pose(m):
    o = (m[0][3], m[1][3], m[2][3])
    r = [[m[i][j] for j in range(3)] for i in range(3)]
    d = (-m[0][2], -m[1][2], -m[2][2])
    n = math.sqrt(sum(c * c for c in d)) or 1.0
    return o, tuple(c / n for c in d), r


class Hands:
    def __init__(self, openvr, system, conf, log):
        self.vr, self.system, self.log = openvr, system, log
        self.press_at = float(conf.get("trigger_press", 0.35))
        self.release_at = float(conf.get("trigger_release", 0.2))
        self.mode = str(conf.get("two_hands", "auto")).lower()
        self.hands = [Hand("left"), Hand("right")]
        self.inp = None
        self.working = False
        self.started = time.time()
        self.legacy_seen = False
        if self.mode in ("auto", "actions"):
            self._init_actions()
        if self.mode == "off":
            log("two-hand typing off (config)")

    # SteamVR Input
    def _init_actions(self):
        vr = self.vr
        try:
            self.inp = vr.VRInput()
            self.inp.setActionManifestPath(os.path.join(HERE, "input", "actions.json"))
            self.set = self.inp.getActionSetHandle("/actions/betterframe")
            self.a_trig = self.inp.getActionHandle("/actions/betterframe/in/trigger")
            self.a_aim = self.inp.getActionHandle("/actions/betterframe/in/aim")
            self.a_hap = self.inp.getActionHandle("/actions/betterframe/out/haptic")
            for h in self.hands:
                h.src = self.inp.getInputSourceHandle("/user/hand/" + h.name)
            self.sets = (vr.VRActiveActionSet_t * 1)()
            self.sets[0].ulActionSet = self.set
            self.sets[0].ulRestrictedToDevice = vr.k_ulInvalidInputValueHandle
            self.log("two-hand typing: using SteamVR Input")
        except Exception as e:
            self.log("SteamVR Input unavailable (%s), using controller state" % e)
            self.inp = None

    def _read_actions(self, h):
        vr = self.vr
        a = self.inp.getAnalogActionData(self.a_trig, h.src)
        value = a.x if a.bActive else None
        try:
            p = self.inp.getPoseActionDataForNextFrame(self.a_aim, vr.TrackingUniverseStanding, h.src)
            if p.bActive and p.pose.bPoseIsValid:
                h.origin, h.dir, h.rot = _pose(p.pose.mDeviceToAbsoluteTracking.m)
        except Exception:
            pass
        return value

    # older API
    def _read_legacy(self, h):
        vr = self.vr
        if h.dev is None:
            return None
        try:
            ok, s = self.system.getControllerState(h.dev)
        except Exception:
            return None
        if not ok:
            return None
        v = float(s.rAxis[1].x)
        if s.ulButtonPressed & (1 << vr.k_EButton_SteamVR_Trigger):
            v = max(v, 1.0)
        if v > 0.05:
            self.legacy_seen = True
        return v

    def update(self, poses):
        """Read both hands."""
        vr = self.vr
        if self.mode == "off":
            return []
        if self.inp:
            try:
                self.inp.updateActionState(self.sets)
            except Exception as e:
                self.log("SteamVR Input stopped (%s), using controller state" % e)
                self.inp = None
        for h, role in zip(self.hands, (vr.TrackedControllerRole_LeftHand, vr.TrackedControllerRole_RightHand)):
            idx = self.system.getTrackedDeviceIndexForControllerRole(role)
            h.dev = None if idx == vr.k_unTrackedDeviceIndexInvalid else idx
            h.origin = h.dir = h.rot = None
            value = None
            if self.inp:
                try:
                    value = self._read_actions(h)
                except Exception:
                    value = None
            elif self.mode not in ("actions", "aim"):
                value = self._read_legacy(h)
            if h.origin is None and h.dev is not None and poses[h.dev].bPoseIsValid:
                h.origin, h.dir, h.rot = _pose(poses[h.dev].mDeviceToAbsoluteTracking.m)
            if value is not None and not self.working and (self.inp or self.legacy_seen):
                self.working = True
                self.log("two-hand typing on (%s)" % ("SteamVR Input" if self.inp else "controller state"))
            v = value or 0.0
            h.value = v
            was = h.down
            h.down = v >= self.press_at if not was else v > self.release_at
            h.pressed = h.down and not was
            h.released = was and not h.down
        if not self.working and self.inp is None and time.time() - self.started > 20 and not getattr(self, "_warned", False):
            self._warned = True
            self.log("no trigger readings yet; pull a trigger once. Until then only SteamVR's single laser types.")
        return [h for h in self.hands if h.ok]

    def buzz(self, h, strength=0.25):
        try:
            if self.inp:
                self.inp.triggerHapticVibrationAction(self.a_hap, 0, 0.012, 180, strength, h.src)
            elif h.dev is not None:
                self.system.triggerHapticPulse(h.dev, 0, int(400 + 1600 * strength))
        except Exception:
            pass
