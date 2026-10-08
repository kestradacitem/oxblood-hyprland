#!/usr/bin/env python3
"""kb dock: GNOME-like autohide dock for Hyprland with monochrome icons (pure white on OLED black, like the dashboard).
- full-width bottom-edge trigger (pointer polled over IPC while hidden); hides 0.5 s after the pointer leaves
- grid button (opens kb app grid), pinned apps (~/.cache/nwg-dock-pinned), then running unpinned apps
- dot = running, red underline = focused; click: focus (restores minimized) / launch via hyprctl (clean env)
- right click: Dash-to-Dock style menu (open windows, the app's desktop actions / New Window, Pin/Unpin, App Details, Quit)
Icons: Nerd Font glyphs for known apps (GLYPHS); other apps get a 2-tone white silhouette of their icon.
Rendered once and cached in ~/.cache/kb-dock-icons (only the dock uses them)."""
import json, os, socket, subprocess, sys, threading, hashlib
sys.path.insert(0, os.path.dirname(__file__))
import base, mono_icon
from base import Gtk, Gdk, GLib, LS, sh
from gi.repository import Gio

PINNED = os.path.expanduser("~/.cache/nwg-dock-pinned")
SIZE = 48
HYPR = f"{os.environ['XDG_RUNTIME_DIR']}/hypr/{os.environ['HYPRLAND_INSTANCE_SIGNATURE']}"

base.CSS += """
window.kbdock, window.kbhot { background: transparent; }
.dock { background: rgba(0, 0, 0, 0.96); border: 1px solid #5f0d11; border-radius: 16px; padding: 6px 8px; }
.dbtn { background: transparent; border: none; border-radius: 12px; padding: 4px 6px 2px; min-width: 0; }
.dbtn:hover { background: #2a0a0d; }
.dot { background: transparent; min-height: 3px; min-width: 6px; border-radius: 99px; margin-top: 2px; }
.dot.run { background: #9e1b24; }
.dot.focus { background: #e04450; min-width: 18px; }
.sep { background: #241112; min-width: 1px; margin: 8px 4px; }
popover.dmenu > contents { background: rgba(0, 0, 0, 0.96); border: 1px solid #5f0d11; border-radius: 12px; padding: 6px; }
popover.dmenu > arrow { background: rgba(0, 0, 0, 0.96); border-color: #5f0d11; }
popover.dmenu modelbutton { color: #e8dede; border-radius: 8px; padding: 6px 12px; min-height: 0; }
popover.dmenu modelbutton:hover, popover.dmenu modelbutton:focus { background: #2a0a0d; }
popover.dmenu separator { background: #241112; margin: 4px 6px; }
"""

def ipc(cmd):
    try:
        s = socket.socket(socket.AF_UNIX); s.connect(f"{HYPR}/.socket.sock"); s.sendall(cmd.encode())
        out = b""
        while (b := s.recv(65536)): out += b
        s.close(); return out.decode()
    except Exception:
        return ""

def dsp(lua, legacy):
    """Dispatch in Lua syntax (hyprland.lua); fall back to the old syntax in a hyprland.conf session."""
    if ipc("dispatch " + lua).strip() != "ok":
        ipc("dispatch " + legacy)

# ---- app lookup -------------------------------------------------------------
APPS = {}       # desktop id (no .desktop) -> DesktopAppInfo
WMCLASS = {}    # lowercase StartupWMClass / id -> id
def load_apps():
    for a in Gio.AppInfo.get_all():
        try: i = a.get_id()
        except Exception: continue
        if not i: continue
        k = i[:-8] if i.endswith(".desktop") else i
        APPS[k] = a
        WMCLASS.setdefault(k.lower(), k)
        try:
            wm = a.get_startup_wm_class()
            if wm: WMCLASS.setdefault(wm.lower(), k)
        except Exception: pass
def app_for(name):
    if not name: return None
    n = name.lower()
    k = WMCLASS.get(n) or WMCLASS.get(n.split(".")[-1]) or next((v for kk, v in WMCLASS.items() if kk.endswith("." + n)), None)
    return k

# ---- monochrome icons (shared with the app grid: mono_icon.py) -------------------------
THEME = None
glyph_icon = mono_icon.glyph_icon
def tinted(app_id, cb):
    """Calls cb(path) with the cached pure white-on-transparent PNG for the app's icon."""
    a = APPS.get(app_id)
    icon = a.get_string("Icon") if a else None
    p = mono_icon.cached(app_id, icon)
    if p: return cb(p)
    src = mono_icon.icon_file(THEME, icon)
    def work():
        out = mono_icon.render(app_id, icon, src)
        if out: GLib.idle_add(lambda: (cb(out), False)[1])
    threading.Thread(target=work, daemon=True).start()

# ---- dock ------------------------------------------------------------------------
class Dock:
    def __init__(self, app):
        self.app = app; self.hide_src = None; self.inside = False
        self.win = Gtk.Window(application=app); self.win.add_css_class("kbdock")
        LS.init_for_window(self.win); LS.set_namespace(self.win, "kb-dock"); LS.set_layer(self.win, LS.Layer.OVERLAY)
        LS.set_anchor(self.win, LS.Edge.BOTTOM, True); LS.set_margin(self.win, LS.Edge.BOTTOM, 8)
        LS.set_exclusive_zone(self.win, -1); LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)
        self.box = Gtk.Box(spacing=2); self.box.add_css_class("dock"); self.win.set_child(self.box)
        m = Gtk.EventControllerMotion(); m.connect("enter", lambda *_: self.enter()); m.connect("leave", lambda *_: self.leave())
        self.win.add_controller(m)
        # bottom-edge trigger: poll the pointer via Hyprland IPC while hidden (no input-blocking hotspot window)
        GLib.timeout_add(70, self.poll_edge)
        self.win.set_default_size(1, 1)
        self.buttons = {}; self.menu_open = False
        self.acts = Gio.SimpleActionGroup(); self.win.insert_action_group("dock", self.acts)
        import signal as _sig
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, _sig.SIGUSR1, lambda: (self.show(), True)[1])
        self.rebuild()
        threading.Thread(target=self.events, daemon=True).start()

    # visibility
    def poll_edge(self):
        if not self.win.get_visible():
            try:
                c = json.loads(ipc("j/cursorpos") or "{}")
                m = next(x for x in json.loads(ipc("j/monitors") or "[]") if x.get("focused"))
                bottom = m["y"] + int(m["height"] / m["scale"]) - 1
                if c and c["y"] >= bottom - 1: self.show()
            except Exception:
                pass
        return True
    def show(self):
        if self.hide_src: GLib.source_remove(self.hide_src); self.hide_src = None
        self.rebuild(); self.win.present()
        self.hide_src = GLib.timeout_add(1200, self.maybe_hide)   # hide if the pointer never comes onto the dock
    def enter(self):
        self.inside = True
        if self.hide_src: GLib.source_remove(self.hide_src); self.hide_src = None
    def leave(self):
        self.inside = False
        if self.hide_src: GLib.source_remove(self.hide_src)
        self.hide_src = GLib.timeout_add(500, self.maybe_hide)
    def maybe_hide(self):
        self.hide_src = None
        if not self.inside and not self.menu_open: self.win.set_visible(False)
        return False

    # content
    def state(self):
        try: clients = json.loads(ipc("j/clients") or "[]")
        except Exception: clients = []
        try: active = json.loads(ipc("j/activewindow") or "{}").get("address")
        except Exception: active = None
        run = {}
        for c in clients:
            k = app_for(c.get("class") or c.get("initialClass"))
            if not k: continue
            run.setdefault(k, []).append(c)
        focus = next((k for k, cs in run.items() if any(c["address"] == active for c in cs)), None)
        return run, focus
    def pins(self):
        try: raw = [l.strip() for l in open(PINNED) if l.strip()]
        except OSError: raw = []
        out = []
        for p in raw:
            k = p if p in APPS else app_for(p)
            if k and k not in out: out.append(k)
        return out
    def rebuild(self):
        if self.menu_open: return   # rebuilding would destroy the open right-click menu
        run, focus = self.state(); pins = self.pins()
        order = pins + [k for k in run if k not in pins]
        c = self.box.get_first_child()
        while c: n = c.get_next_sibling(); self.box.remove(c); c = n
        g = self.button(None, glyph_icon("kb-grid"), False, False, lambda *_: (self.win.set_visible(False), subprocess.run(["setsid", "-f", "@HOME@/.local/bin/kb-popup", "appgrid"])))
        self.box.append(g)
        s = Gtk.Box(); s.add_css_class("sep"); self.box.append(s)
        for k in order:
            a = APPS.get(k)
            b = self.button(k, None, k in run, k == focus, lambda _b, k=k: self.activate(k, run.get(k)),
                            tip=a.get_display_name() if a else k)
            rc = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
            rc.connect("pressed", lambda g, n, x, y, b=b, k=k: self.menu(b, k, run.get(k, []), k in pins))
            b.add_controller(rc)
            self.box.append(b)
    def button(self, k, path, running, focused, cb, tip=None):
        b = Gtk.Button(); b.add_css_class("dbtn")
        if tip: b.set_tooltip_text(tip)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        img = Gtk.Image(); img.set_pixel_size(SIZE); v.append(img)
        if path: img.set_from_file(path)
        else:
            img.set_from_icon_name("application-x-executable")
            tinted(k, lambda p, img=img: img.set_from_file(p))
        d = Gtk.Box(halign=Gtk.Align.CENTER); d.add_css_class("dot")
        if running: d.add_css_class("run")
        if focused: d.add_css_class("focus")
        v.append(d); b.set_child(v); b.connect("clicked", cb)
        return b
    def activate(self, k, wins):
        if wins:
            try: active = json.loads(ipc("j/activewindow") or "{}").get("address")
            except Exception: active = None
            addrs = [w["address"] for w in wins]
            nxt = addrs[(addrs.index(active) + 1) % len(addrs)] if active in addrs else addrs[0]
            dsp(f'hl.dsp.focus({{window="address:{nxt}"}})', f"focuswindow address:{nxt}")
        else:
            a = APPS.get(k)
            if a:
                cmd = (a.get_commandline() or "").replace("%U", "").replace("%u", "").replace("%F", "").replace("%f", "").replace("%i", "").replace("%c", "").replace("%k", "").strip()
                c = cmd or f"gtk-launch {k}"
                dsp(f"hl.dsp.exec_cmd({json.dumps(c)})", f"exec {c}")
        GLib.timeout_add(300, lambda: (self.rebuild(), False)[1])

    # ---- right-click menu (same entries as Dash to Dock / GNOME dash) ----
    def run_cmd(self, c):
        dsp(f"hl.dsp.exec_cmd({json.dumps(c)})", f"exec {c}")
    def launch(self, k, action=None):
        """Launch the app (or one of its [Desktop Action ...] entries) through Hyprland so it gets a clean env."""
        a = APPS.get(k)
        if not a: return
        cmd = a.get_commandline() or ""
        if action:
            kf = GLib.KeyFile()
            try:
                kf.load_from_file(a.get_filename(), GLib.KeyFileFlags.NONE)
                cmd = kf.get_string(f"Desktop Action {action}", "Exec")
            except Exception:
                return
        for f in ("%U", "%u", "%F", "%f", "%i", "%c", "%k"): cmd = cmd.replace(f, "")
        self.run_cmd(cmd.strip() or f"gtk-launch {k}")
    def set_pinned(self, k, pin):
        try: raw = [l.strip() for l in open(PINNED) if l.strip()]
        except OSError: raw = []
        raw = [p for p in raw if (p if p in APPS else app_for(p)) != k]
        if pin: raw.append(k)
        with open(PINNED, "w") as f: f.write("\n".join(raw) + "\n")
    def menu(self, btn, k, wins, pinned):
        a = APPS.get(k)
        for n in self.acts.list_actions(): self.acts.remove_action(n)
        def act(name, fn):
            x = Gio.SimpleAction.new(name, None)
            x.connect("activate", lambda *_: (self.win.set_visible(False), fn(), GLib.timeout_add(300, lambda: (self.rebuild(), False)[1])))
            self.acts.add_action(x); return "dock." + name
        m = Gio.Menu()
        if wins:
            sec = Gio.Menu()
            for i, w in enumerate(wins):
                t = (w.get("title") or (a.get_display_name() if a else k)).replace("_", "__")
                sec.append(t[:60] + ("…" if len(t) > 60 else ""), act(f"win{i}", lambda ad=w["address"]: dsp(f'hl.dsp.focus({{window="address:{ad}"}})', f"focuswindow address:{ad}")))
            m.append_section(None, sec)
        sec = Gio.Menu()
        own = a.list_actions() if a else []
        if not any(x.lower() in ("new-window", "newwindow", "new_window") for x in own):
            sec.append("New Window", act("new", lambda: self.launch(k)))
        for i, x in enumerate(own):
            sec.append(a.get_action_name(x), act(f"da{i}", lambda x=x: self.launch(k, x)))
        m.append_section(None, sec)
        sec = Gio.Menu()
        sec.append("Unpin" if pinned else "Pin to Dash", act("pin", lambda: self.set_pinned(k, not pinned)))
        if a and os.path.exists("/usr/bin/gnome-software"):
            sec.append("App Details", act("details", lambda: self.run_cmd(f"gnome-software --details={k}.desktop")))
        m.append_section(None, sec)
        if wins:
            sec = Gio.Menu()
            sec.append("Quit" if len(wins) == 1 else f"Quit {len(wins)} Windows", act("quit", lambda: [
                dsp(f'hl.dsp.window.close({{window="address:{w["address"]}"}})', f"closewindow address:{w['address']}") for w in wins]))
            m.append_section(None, sec)
        pop = Gtk.PopoverMenu.new_from_model(m); pop.add_css_class("dmenu")
        pop.set_parent(btn); pop.set_position(Gtk.PositionType.TOP); pop.set_has_arrow(False)
        def closed(*_):
            self.menu_open = False
            GLib.idle_add(lambda: (pop.unparent(), False)[1])
            if not self.inside: self.leave()
        pop.connect("closed", closed)
        self.menu_open = True
        if self.hide_src: GLib.source_remove(self.hide_src); self.hide_src = None
        pop.popup()

    def events(self):
        """Refresh running/focused state from Hyprland's event socket."""
        while True:
            try:
                s = socket.socket(socket.AF_UNIX); s.connect(f"{HYPR}/.socket2.sock"); buf = b""
                while True:
                    d = s.recv(4096)
                    if not d: break
                    buf += d
                    if any(t in buf for t in (b"openwindow>>", b"closewindow>>", b"activewindowv2>>", b"movewindow>>")):
                        buf = b""
                        if self.win.get_visible(): GLib.idle_add(lambda: (self.rebuild(), False)[1])
                    elif len(buf) > 65536: buf = b""
            except Exception:
                import time; time.sleep(2)

def main():
    global THEME
    load_apps()
    prov = Gtk.CssProvider(); prov.load_from_data(base.CSS.encode(), -1)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    THEME = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    app = Gtk.Application(application_id="ph.kb.dock", flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", lambda a: setattr(a, "dock", Dock(a)))
    app.hold(); app.run([])

main()
