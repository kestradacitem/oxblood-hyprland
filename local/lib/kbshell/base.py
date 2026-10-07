"""Shared bits for kb's GNOME-style Hyprland popups (GTK4 + gtk4-layer-shell, OLED black + maroon)."""
import json, os, subprocess, signal
# gtk4-layer-shell is LD_PRELOADed into this process; never let it leak into apps we launch
# (GTK3 apps abort with GTK3+GTK4 in one process, and glycin loaders get SIGSYS from their seccomp sandbox).
os.environ.pop("LD_PRELOAD", None)
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, GLib, Gtk4LayerShell as LS

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
ACCENT, MAROON = "#c41e2a", "#5f0d11"

CSS = f"""
window.kbpop {{ background: transparent; }}
.card {{ background: #000000; border: 1px solid {MAROON}; border-radius: 0; padding: 12px; }}
.menuitem {{ background: transparent; color: #e8dede; border: none; border-radius: 0; padding: 10px 16px; font-size: 14px; font-weight: 400; }}
.menuitem:hover {{ background: #180c0d; }}
separator.sep {{ background: #241112; min-height: 1px; margin: 6px 10px; }}
.pill {{ background: #180c0d; color: #e8dede; border-radius: 0; padding: 8px 16px; border: none; font-weight: 400; }}
.round {{ background: #180c0d; color: {ACCENT}; border-radius: 0; min-width: 40px; min-height: 40px; padding: 0; border: none; font-size: 16px; }}
.round:hover, .pill:hover {{ background: #241112; }}
.slabel {{ color: #e8dede; font-size: 12px; margin-left: 2px; }}
.sicon {{ background: transparent; border: none; color: {ACCENT}; font-size: 16px; min-width: 32px; padding: 0; }}
scale trough {{ background: #241112; min-height: 6px; border-radius: 0; }}
scale highlight {{ background: {MAROON}; border-radius: 0; }}
scale slider {{ background: #f2eaea; min-width: 20px; min-height: 20px; border-radius: 0; margin: -8px; }}
.tile {{ background: #180c0d; border-radius: 0; min-height: 48px; }}
.tile.on {{ background: {MAROON}; }}
.tilemain {{ background: transparent; border: none; color: #e8dede; border-radius: 0; padding: 4px 14px; }}
.tilemain:hover {{ background: rgba(255,255,255,0.05); }}
.tileicon {{ color: {ACCENT}; font-size: 17px; }}
.tile.on .tileicon {{ color: #ffffff; }}
.tiletitle {{ font-weight: 400; font-size: 14px; color: #e8dede; }}
.tilesub {{ font-size: 11px; color: #bfb0b0; }}
.tilearrow {{ background: rgba(255,255,255,0.06); border: none; color: {ACCENT}; border-radius: 0; min-width: 40px; padding: 0; font-size: 15px; }}
.tile.on .tilearrow {{ background: rgba(255,255,255,0.12); color: #ffffff; }}
.tilearrow:hover {{ background: rgba(255,255,255,0.18); }}
.sub {{ background: #0c0707; border-radius: 0; padding: 8px; margin-top: 6px; }}
.subhead {{ color: #e8dede; font-weight: 400; font-size: 14px; margin: 2px 8px 6px; }}
.subitem {{ background: transparent; border: none; color: #e8dede; border-radius: 0; padding: 8px 10px; font-size: 14px; }}
.subitem:hover {{ background: #180c0d; }}
.subitem.active {{ color: {ACCENT}; font-weight: 400; }}
.dim {{ color: #8c7a7a; font-size: 11px; }}
"""

def sh(*cmd, timeout=6):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""

def spawn(cmd):
    subprocess.Popen(["setsid", "-f", "sh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def bar_height():
    try:
        m = json.loads(sh("hyprctl", "monitors", "-j"))
        return next(x for x in m if x.get("focused"))["reserved"][1]
    except Exception:
        return 34

def close_others(me):
    for f in os.listdir(RUN):
        if (f.startswith("kbpop-") and f.endswith(".pid") and f != f"kbpop-{me}.pid") or f == "kb-agenda-popup.pid":
            try: os.kill(int(open(os.path.join(RUN, f)).read()), signal.SIGTERM)
            except Exception: pass
            try: os.remove(os.path.join(RUN, f))
            except OSError: pass

def label(text, cls=None, xalign=0, wrap=False):
    l = Gtk.Label(label=text, xalign=xalign)
    if cls: l.add_css_class(cls)
    if wrap: l.set_wrap(True)
    return l

def run_popup(name, build, edge="right", width=None):
    """Full-screen transparent overlay with the card placed under the bar.
    Mouse movement never closes it; a click outside the card, Esc, or toggling again does.
    edge: left | right | center | button (centred under the pointer). build(win) -> widget."""
    pidf = os.path.join(RUN, f"kbpop-{name}.pid")
    close_others(name)
    open(pidf, "w").write(str(os.getpid()))
    prov = Gtk.CssProvider(); prov.load_from_data(CSS.encode(), -1)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    from gi.repository import Gio
    app = Gtk.Application(application_id=f"ph.kb.pop.{name}", flags=Gio.ApplicationFlags.NON_UNIQUE)
    def act(app):
        win = Gtk.ApplicationWindow(application=app); win.add_css_class("kbpop")
        LS.init_for_window(win); LS.set_namespace(win, f"kb-{name}")
        LS.set_layer(win, LS.Layer.OVERLAY)
        for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(win, e, True)
        LS.set_exclusive_zone(win, -1)          # cover the bar too, so a click on it just closes
        LS.set_keyboard_mode(win, LS.KeyboardMode.ON_DEMAND)
        card = build(win)
        if width: card.set_size_request(width, -1)
        card.set_valign(Gtk.Align.START)
        card.set_margin_top(bar_height() + 6); card.set_margin_start(6); card.set_margin_end(6)
        if edge == "button" and width:
            # centred under the bar button that was clicked (the pointer is on it), like HyprPanel's
            # menus; kept 6 px from the screen edges
            try:
                cx = int(sh("hyprctl", "cursorpos").split(",")[0])
                m = next(x for x in json.loads(sh("hyprctl", "monitors", "-j")) if x.get("focused"))
                sw = round((m["width"] if m["transform"] % 2 == 0 else m["height"]) / m["scale"]); cx -= m["x"]
                card.set_halign(Gtk.Align.START); card.set_margin_start(max(6, min(cx - width // 2, sw - width - 6)))
            except Exception:
                card.set_halign(Gtk.Align.CENTER)
        else:
            card.set_halign({"left": Gtk.Align.START, "right": Gtk.Align.END}.get(edge, Gtk.Align.CENTER))
        win.set_child(card)
        click = Gtk.GestureClick(); click.set_button(0)
        def pressed(g, n, x, y):
            w = win.pick(x, y, Gtk.PickFlags.DEFAULT)
            while w is not None and w is not card: w = w.get_parent()
            if w is None: win.close()
        click.connect("pressed", pressed); win.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda c, k, *_: (win.close(), True)[1] if k == Gdk.KEY_Escape else False)
        win.add_controller(keys)
        win.present()
    app.connect("activate", act)
    try: app.run([])
    finally:
        try: os.remove(pidf)
        except OSError: pass
