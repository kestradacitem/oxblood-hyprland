#!/usr/bin/env python3
"""GNOME-style snap preview for edge-snap.py (2026-10-05).

Reads commands on stdin, one per line:  "X Y W H" (logical px, global) = show the preview there, "hide" = hide it.
A click-through, keyboard-less layer surface (translucent accent fill + border), so it never steals input.
Must run with LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so (like the other kbshell surfaces).
"""
import sys, threading
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, GLib, Gio, Gtk4LayerShell as LS
import cairo

CSS = """
window.kb-snap { background: transparent; }
.kb-snap-box { background: rgba(216, 50, 90, 0.16); border: 2px solid rgba(216, 50, 90, 0.75); border-radius: 10px; }
"""
INSET = 6   # px inside the target slot, like GNOME's preview


def main():
    app = Gtk.Application(application_id="ph.kb.snappreview", flags=Gio.ApplicationFlags.NON_UNIQUE)
    def activate(a):
        prov = Gtk.CssProvider(); prov.load_from_data(CSS.encode(), -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = Gtk.Window(application=a); win.add_css_class("kb-snap")
        LS.init_for_window(win); LS.set_namespace(win, "kb-snap-preview"); LS.set_layer(win, LS.Layer.TOP)
        LS.set_anchor(win, LS.Edge.TOP, True); LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_exclusive_zone(win, -1); LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        box = Gtk.Box(); box.add_css_class("kb-snap-box"); win.set_child(box)
        win.set_can_target(False)

        def clickthrough(*_):
            s = win.get_surface()
            if s: s.set_input_region(cairo.Region())
        win.connect("realize", clickthrough); win.connect("map", clickthrough)

        def apply(line):
            p = line.split()
            if len(p) == 4:
                x, y, w, h = (int(float(v)) for v in p)
                win.set_visible(False)       # a mapped layer surface didn't resize reliably: remap at the new size
                LS.set_margin(win, LS.Edge.LEFT, x + INSET); LS.set_margin(win, LS.Edge.TOP, y + INSET)
                win.set_default_size(max(w - 2 * INSET, 1), max(h - 2 * INSET, 1))
                box.set_size_request(max(w - 2 * INSET, 1), max(h - 2 * INSET, 1))
                win.set_visible(True)
            else:
                win.set_visible(False)
            return False

        def reader():
            for line in sys.stdin:
                GLib.idle_add(apply, line.strip())
            GLib.idle_add(a.quit)          # edge-snap went away
        threading.Thread(target=reader, daemon=True).start()
        a.hold()
    app.connect("activate", activate)
    app.run([])


main()
