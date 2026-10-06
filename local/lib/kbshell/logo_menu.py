#!/usr/bin/env python3
"""GNOME 'Logo Menu' look-alike for the Arch button."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import base
from base import Gtk, run_popup, spawn

# compact, separator-free list (same card/padding scale as the dashboard)
base.CSS += """
.card.logo { padding: 6px; border-radius: 0; }
.logo .menuitem { padding: 7px 12px; border-radius: 0; font-size: 14px; min-height: 0; }
.logo .menuitem:hover { background: #1a0b0c; }
"""

GNOME_ENV = "env XDG_CURRENT_DESKTOP=GNOME"
ITEMS = [
    ("About My System", f"{GNOME_ENV} gnome-control-center system about || {GNOME_ENV} gnome-control-center about"),
    ("System Monitor", "gnome-system-monitor"),
    ("Lock Screen", "loginctl lock-session"),
]

def build(win):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); box.add_css_class("card"); box.add_css_class("logo")
    for text, cmd in ITEMS:
        b = Gtk.Button(); b.add_css_class("menuitem")
        l = Gtk.Label(label=text, xalign=0); b.set_child(l)
        b.connect("clicked", lambda _b, c=cmd: (spawn(c), win.close()))
        box.append(b)
    return box

run_popup("logo", build, edge="left", width=230)
