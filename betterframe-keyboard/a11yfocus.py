"""BetterFrame: notice when a text box on the desktop is selected, so the keyboard can open by itself.

Uses the desktop's accessibility system (AT-SPI, the same thing Linux on-screen keyboards use): apps report which
part of them has focus, and whether it's a place you can type. Only listens; it never changes anything in the apps.

    python3 a11yfocus.py test     prints every text box you select for 30 seconds (to check it on a computer)
"""
import os
import threading
import time

EDITABLE, FOCUSED, READ_ONLY = 7, 12, 43            # AT-SPI state numbers
TERMINAL = 59                                       # AT-SPI role: a terminal (Konsole) is a place to type too
EVENT = "object:state-changed:focused"
MARK = os.path.expanduser("~/.config/betterframe-keyboard/a11y-by-betterframe")   # (we turned it on: off again later)


def _state_has(states, n):
    return bool(states[n // 32] & (1 << (n % 32))) if n // 32 < len(states) else False


def kde_bus_address():
    """The message bus of the desktop you see in VR. On the Frame that desktop is a KDE session of its own, with its
    own bus (not the one the keyboard's service starts on), so it's read from KDE's own running programs."""
    uid = os.getuid()
    for name in ("plasmashell", "kwin_wayland", "kwin_x11", "krunner", "konsole", "dolphin"):
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
                    for item in f.read().split(b"\0"):
                        if item.startswith(b"DBUS_SESSION_BUS_ADDRESS="):
                            return item.split(b"=", 1)[1].decode()
            except OSError:
                continue
    return None


def session_bus_address():
    """The desktop's message bus: KDE's own, else the usual one."""
    return kde_bus_address() or os.environ.get("DBUS_SESSION_BUS_ADDRESS") or "unix:path=/run/user/%d/bus" % os.getuid()


class FocusWatch(threading.Thread):
    """Calls on_text() each time a text box (or a terminal) gets focus on the desktop."""

    def __init__(self, on_text, log=print, session=None):
        super().__init__(daemon=True, name="text-box-focus")
        self.on_text, self.log = on_text, log
        self.fixed = session          # (a test's own bus; normally the desktop's is found each time it connects)
        self.seen = 0
        self.running = True
        self.enabled_by_us = False

    def stop(self):
        self.running = False

    # ---- talking to the desktop
    def _call(self, conn, dest, path, iface, member, sig=None, body=(), timeout=2):
        from jeepney import new_method_call, DBusAddress
        msg = new_method_call(DBusAddress(path, bus_name=dest, interface=iface), member, sig, body)
        return conn.send_and_get_reply(msg, timeout=timeout).body

    def _a11y_address(self, sess):
        from jeepney import new_method_call, DBusAddress
        bus = DBusAddress("/org/a11y/bus", bus_name="org.a11y.Bus", interface="org.a11y.Bus")
        # apps only report focus once accessibility is on: turn it on (it stays as it is if it already was)
        try:
            props = DBusAddress("/org/a11y/bus", bus_name="org.a11y.Bus", interface="org.freedesktop.DBus.Properties")
            on = sess.send_and_get_reply(new_method_call(props, "Get", "ss", ("org.a11y.Status", "IsEnabled")), timeout=2).body
            if not (on and on[0][1]):
                sess.send_and_get_reply(new_method_call(props, "Set", "ssv", ("org.a11y.Status", "IsEnabled", ("b", True))), timeout=2)
                self.enabled_by_us = True
                os.makedirs(os.path.dirname(MARK), exist_ok=True)
                open(MARK, "w").close()
                self.log("text box focus: turned on the desktop's accessibility reporting")
        except Exception as ex:
            self.log("text box focus: couldn't turn on accessibility reporting:", ex)
        return sess.send_and_get_reply(new_method_call(bus, "GetAddress"), timeout=2).body[0]

    def _register(self, conn):
        """Ask apps to send focus changes (newer desktops only send the events someone asked for)."""
        for sig, body in (("sass", (EVENT, [], "")), ("s", (EVENT,))):
            try:
                self._call(conn, "org.a11y.atspi.Registry", "/org/a11y/atspi/registry",
                           "org.a11y.atspi.Registry", "RegisterEvent", sig, body)
                return True
            except Exception:
                continue
        return False

    def note_apps(self, conn):
        """Which apps take part in accessibility (said in the log when it changes): an app that isn't in the list never
        reports its text boxes, so this shows which ones can open the keyboard by themselves."""
        try:
            kids = self._call(conn, "org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root",
                              "org.a11y.atspi.Accessible", "GetChildren")[0]
            names = []
            for bus, path in kids[:40]:
                try:
                    v = self._call(conn, bus, path, "org.freedesktop.DBus.Properties", "Get", "ss",
                                   ("org.a11y.atspi.Accessible", "Name"), timeout=1)[0]
                    names.append(v[1] if isinstance(v, tuple) else str(v))
                except Exception:
                    names.append("?")
            names = sorted(n or "?" for n in names)
        except Exception as ex:
            names = ["(couldn't ask: %s)" % ex]
        if names != getattr(self, "apps_said", None):
            self.apps_said = names
            self.log("text box focus: apps taking part: %s" % (", ".join(names) or "none"))

    def is_text_box(self, conn, sender, path):
        try:
            states = self._call(conn, sender, path, "org.a11y.atspi.Accessible", "GetState")[0]
            if _state_has(states, EDITABLE) and not _state_has(states, READ_ONLY):
                return True
            role = self._call(conn, sender, path, "org.a11y.atspi.Accessible", "GetRole")[0]
            return role == TERMINAL
        except Exception:
            return False

    def run(self):
        from jeepney import MatchRule
        from jeepney.io.blocking import open_dbus_connection
        said = None
        while self.running:
            try:
                self.session = self.fixed or session_bus_address()
                sess = open_dbus_connection(self.session)
                addr = self._a11y_address(sess)
                listen = open_dbus_connection(addr)
                ask = open_dbus_connection(addr)
                self._register(ask)
                rule = MatchRule(type="signal", interface="org.a11y.atspi.Event.Object", member="StateChanged")
                rule.add_arg_condition(0, "focused")
                rule2 = MatchRule(type="signal", interface="org.a11y.atspi.Event.Focus", member="Focus")
                from jeepney.bus_messages import message_bus
                listen.send_and_get_reply(message_bus.AddMatch(rule), timeout=2)
                listen.send_and_get_reply(message_bus.AddMatch(rule2), timeout=2)
                self.log("text box focus: listening (desktop bus %s)" % self.session)
                self.note_apps(ask)
                said = None
                checked = time.time()
                with listen.filter(rule, bufsize=50) as queue, listen.filter(rule2, queue=queue, bufsize=50):
                    while self.running:
                        if time.time() - checked > 10:   # (the desktop restarted: its new bus, from scratch)
                            checked = time.time()
                            self.note_apps(ask)
                            if not self.fixed and (kde_bus_address() or self.session) != self.session:
                                self.log("text box focus: the desktop restarted, listening to the new one")
                                break
                        try:
                            msg = listen.recv_until_filtered(queue, timeout=1.0)
                        except TimeoutError:
                            continue
                        body = msg.body
                        member = msg.header.fields.get(3)
                        if member == "StateChanged" and (len(body) < 2 or body[0] != "focused" or body[1] != 1):
                            continue
                        from jeepney import HeaderFields
                        sender = msg.header.fields.get(HeaderFields.sender)
                        path = msg.header.fields.get(HeaderFields.path)
                        box = bool(sender and path and self.is_text_box(ask, sender, path))
                        if self.seen < 5:   # (the first few, in the log: shows it's hearing the desktop at all)
                            self.seen += 1
                            self.log("text box focus: something was selected (%s)" % ("a text box" if box else "not a text box"))
                        if box:
                            self.on_text()
            except Exception as ex:
                if str(ex) != said:
                    self.log("text box focus: not available right now (%s); trying again in a moment" % ex)
                    said = str(ex)
                for _ in range(20):
                    if not self.running:
                        break
                    time.sleep(0.5)


def turn_off():
    """Accessibility reporting back off, only if BetterFrame turned it on (the setting switched off, or uninstalled)."""
    if not os.path.exists(MARK):
        return "left as it was"
    from jeepney import new_method_call, DBusAddress
    from jeepney.io.blocking import open_dbus_connection
    try:
        props = DBusAddress("/org/a11y/bus", bus_name="org.a11y.Bus", interface="org.freedesktop.DBus.Properties")
        open_dbus_connection(session_bus_address()).send_and_get_reply(
            new_method_call(props, "Set", "ssv", ("org.a11y.Status", "IsEnabled", ("b", False))), timeout=2)
    except Exception as ex:
        return "couldn't: %s" % ex
    os.remove(MARK)
    return "turned off again"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "off":
        print("accessibility reporting:", turn_off())
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        w = FocusWatch(lambda: print(time.strftime("%H:%M:%S"), "a text box was selected"))
        w.start()
        print("Click into some text boxes for 30 seconds...")
        time.sleep(30)
        w.stop()
