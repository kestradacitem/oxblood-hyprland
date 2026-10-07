#!/usr/bin/env python3
"""Outlook agenda dropdown (click the bar's next-meeting item)."""
import json, os, subprocess, sys, threading, time
sys.path.insert(0, os.path.dirname(__file__))
import base
from base import Gtk, Gdk, run_popup
AG_CSS = """

.card {{ background: #000000; border: 1px solid #5f0d11; border-radius: 0; padding: 14px 16px; }}
.head {{ color: #e8dede; font-weight: 400; font-size: 14px; }}
.agsub {{ color: #8c7a7a; font-size: 11px; }}
.day {{ color: #e8dede; font-weight: 400; font-size: 14px; margin-top: 12px; margin-bottom: 4px; }}
.ev {{ background: #0c0707; border-radius: 0; padding: 8px 10px; margin-bottom: 5px; }}
.ev.now {{ background: #2a0a0d; border-left: 3px solid #c41e2a; }}
.when {{ color: #e04450; font-weight: 400; font-size: 12px; }}
.title {{ color: #e8dede; font-weight: 400; font-size: 14px; }}
.loc {{ color: #8c7a7a; font-size: 11px; }}
.empty {{ color: #8c7a7a; font-size: 13px; margin: 18px 0; }}
button.join {{ background: #5f0d11; color: #ffffff; border: none; border-radius: 0; padding: 3px 10px; min-height: 0; margin-top: 4px; font-size: 12px; font-weight: 400; }}
button.join:hover {{ background: #7a1218; }}
.plat {{ color: #e8dede; background: #241112; border-radius: 0; padding: 1px 6px; font-size: 11px; margin-top: 4px; }}
button.close {{ background: #120a0a; color: #e8dede; border-radius: 0; min-width: 24px; min-height: 24px; padding: 0; border: none; }}
button.close:hover {{ background: #5f0d11; }}
"""
base.CSS += AG_CSS.replace("{{", "{").replace("}}", "}")
def lbl(text, cls, wrap=False):
    l = Gtk.Label(label=text, xalign=0); l.add_css_class(cls)
    if wrap: l.set_wrap(True); l.set_max_width_chars(48)
    return l

def fetch(force=False):
    env = dict(os.environ, **({"KB_FORCE": "1"} if force else {}))
    try:
        return json.loads(subprocess.run(["@HOME@/.local/bin/kb-next-meeting", "--agenda"], env=env,
                                         capture_output=True, text=True, timeout=30).stdout or "[]")
    except Exception:
        return None

def open_link(win, url):
    # detached so the browser / Teams / Zoom app outlives the popup
    subprocess.Popen(["setsid", "-f", "xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    win.close()

def body_for(win, data):
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    if not data:
        body.append(lbl("No meetings in the next 8 days", "empty"))
    for d in data or []:
        body.append(lbl(d["day"], "day"))
        for e in d["events"]:
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); b.add_css_class("ev")
            if e.get("now"): b.add_css_class("now")
            b.append(lbl(e["when"] + ("  · now" if e.get("now") else ""), "when"))
            b.append(lbl(e["title"], "title", wrap=True))
            loc = e.get("location", "")
            # drop the generic "Microsoft Teams Meeting"/"Zoom"/link location when a join button says it
            if e.get("join") and (loc.startswith("http") or loc.lower().replace(" meeting", "") in
                                  ("microsoft teams", "zoom", "google meet", "teams")): loc = ""
            if loc: b.append(lbl(loc, "loc", wrap=True))
            if e.get("join"):
                row = Gtk.Box(spacing=8)
                j = Gtk.Button(label="Join ↗"); j.add_css_class("join"); j.set_tooltip_text(e["join"])
                j.connect("clicked", lambda _b, u=e["join"]: open_link(win, u))
                row.append(j); row.append(lbl(e["platform"], "plat"))
                b.append(row)
            body.append(b)
    return body

def build(win):
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); card.add_css_class("card")
    top = Gtk.Box(spacing=8)
    hv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
    sub = lbl("Next 8 days · calendar · refreshing…", "agsub")
    hv.append(lbl("Outlook agenda", "head")); hv.append(sub)
    top.append(hv)
    x = Gtk.Button(label="✕"); x.add_css_class("close"); x.set_valign(Gtk.Align.START)
    x.connect("clicked", lambda *_: win.close()); top.append(x)
    card.append(top)
    sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
    sc.set_max_content_height(620); sc.set_child(body_for(win, fetch()))
    card.append(sc)
    # cached agenda shows at once; every open re-downloads the ICS and swaps the list in place
    def refresh():
        data = fetch(force=True)
        def apply():
            if data is None:
                sub.set_label("Next 8 days · calendar · offline, cached")
            else:
                sc.set_child(body_for(win, data))
                sub.set_label(f"Next 8 days · calendar · updated {time.strftime('%H:%M')}")
            return False
        base.GLib.idle_add(apply)
    threading.Thread(target=refresh, daemon=True).start()
    return card

run_popup("agenda", build, edge="button", width=460)
