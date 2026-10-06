#!/usr/bin/env python3
"""kb-greeter: login screen that looks like the hyprlock lock screen.

Pure OLED black, the time, and one password box for one user ($KB_GREETER_USER, set in the greetd config).
Talks to greetd ($GREETD_SOCK) and starts Hyprland. Runs inside cage (greetd default_session).
Installed to /usr/local/share/kb-greeter/greeter.py because the greeter user can't read your home.

Test without greetd: KB_GREETER_TEST=1 python3 greeter.py  (any password "ok" logs in, anything else fails).
"""
import json, os, pwd, socket, struct, threading, time
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio

def _first_user():
    # fallback when KB_GREETER_USER isn't set: the first normal account (uid 1000+ with a login shell)
    for u in sorted(pwd.getpwall(), key=lambda u: u.pw_uid):
        if 1000 <= u.pw_uid < 60000 and not u.pw_shell.endswith(("nologin", "false")):
            return u.pw_name
    return "root"

USER = os.environ.get("KB_GREETER_USER") or _first_user()
SESSION = ["/usr/bin/start-hyprland"]
SESSION_ENV = ["XDG_SESSION_TYPE=wayland", "XDG_CURRENT_DESKTOP=Hyprland", "XDG_SESSION_DESKTOP=Hyprland"]
RED, RED_FAIL = "#c41e2a", "#ff3b4a"   # same outline as hyprlock's input-field
TEST = os.environ.get("KB_GREETER_TEST") == "1"


class Greetd:
    """Minimal greetd IPC client: 4-byte native-endian length + JSON."""
    def __init__(self):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.connect(os.environ["GREETD_SOCK"])

    def req(self, msg):
        data = json.dumps(msg).encode()
        self.s.sendall(struct.pack("=I", len(data)) + data)
        n = struct.unpack("=I", self._read(4))[0]
        return json.loads(self._read(n))

    def _read(self, n):
        b = b""
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c: raise ConnectionError("greetd closed the socket")
            b += c
        return b


def login(password):
    """Returns None on success (session started), else an error text."""
    if TEST:
        time.sleep(0.5)
        return None if password == "ok" else "Wrong password"
    g = Greetd()
    r = g.req({"type": "create_session", "username": USER})
    while r.get("type") == "auth_message":
        kind = r.get("auth_message_type")
        resp = password if kind in ("secret", "visible") else None
        r = g.req({"type": "post_auth_message_response", "response": resp})
    if r.get("type") != "success":
        g.req({"type": "cancel_session"})
        return "Wrong password" if r.get("error_type") == "auth_error" else (r.get("description") or "Login failed")
    r = g.req({"type": "start_session", "cmd": SESSION, "env": SESSION_ENV})
    if r.get("type") != "success":
        return r.get("description") or "Could not start Hyprland"
    return None


def main():
    app = Gtk.Application(application_id="ph.kb.greeter", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(a):
        win = Gtk.Window(application=a, title="kb-greeter")
        # cage runs at scale 1 on the 2880x1800 panel: size everything for a 1920-px-wide logical screen
        mon = Gdk.Display.get_default().get_monitors().get_item(0)
        k = max(mon.get_geometry().width / 1920, 1.0) if mon else 1.0
        css = f"""
        window, window.background {{ background: #000; }}
        .clock {{ color: #fff; font-size: {int(64 * k)}px; font-weight: 600; }}
        entry.pw, passwordentry.pw {{
            min-width: {int(300 * k)}px; min-height: {int(50 * k)}px; padding: 0 {int(18 * k)}px;
            background: #000; color: #fff; caret-color: #fff; font-size: {int(18 * k)}px;
            border: {max(int(3 * k), 2)}px solid {RED}; border-radius: 999px; box-shadow: none; outline: none;
        }}
        passwordentry.pw text {{ background: transparent; color: #fff; }}
        passwordentry.pw text placeholder {{ color: #8a8a8a; font-style: italic; }}
        passwordentry.pw.fail {{ border-color: {RED_FAIL}; }}
        passwordentry.pw image {{ color: #555; }}
        """
        prov = Gtk.CssProvider(); prov.load_from_data(css.encode(), -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=int(40 * k), halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        clock = Gtk.Label(css_classes=["clock"])
        pw = Gtk.PasswordEntry(css_classes=["pw"], placeholder_text="Password", show_peek_icon=False, halign=Gtk.Align.CENTER)
        pw.set_property("placeholder-text", "Password")
        pw.set_alignment(0.5)                       # text/dots centred, like hyprlock
        box.append(clock); box.append(pw)
        win.set_child(box)

        def tick():
            clock.set_label(time.strftime("%H:%M")); return True
        tick(); GLib.timeout_add_seconds(1, tick)

        busy = {"on": False}
        def done(err):
            busy["on"] = False; pw.set_sensitive(True)
            if err is None:
                a.quit(); return False
            pw.set_text(""); pw.add_css_class("fail"); pw.set_property("placeholder-text", err); pw.grab_focus()
            def reset():
                pw.remove_css_class("fail"); pw.set_property("placeholder-text", "Password"); return False
            GLib.timeout_add(2500, reset)
            return False

        def submit(*_):
            text = pw.get_text()
            if busy["on"] or not text: return     # empty Enter is not a failed attempt (like ignore_empty_input)
            busy["on"] = True; pw.set_sensitive(False)
            def work():
                try: err = login(text)
                except Exception as e: err = f"Login error: {e}"
                GLib.idle_add(done, err)
            threading.Thread(target=work, daemon=True).start()
        pw.connect("activate", submit)

        win.fullscreen(); win.present(); pw.grab_focus()

    app.connect("activate", activate)
    app.run([])


if __name__ == "__main__":
    main()
