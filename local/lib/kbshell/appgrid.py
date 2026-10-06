#!/usr/bin/env python3
"""GNOME-style overview + app grid for Hyprland (Super key).
Top 60%: live thumbnails of the windows on the current workspace (click = focus; hover shows a close
button, middle-click also closes - like GNOME).
Bottom 40%: one row of the GNOME app folders (same dconf folders as GNOME), click = folder popup.
Typing searches every app. Esc / Super / click on empty space closes."""
import json, os, subprocess, sys, threading, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import base, mono_icon
from concurrent.futures import ThreadPoolExecutor
from base import Gtk, Gdk, GLib, LS, sh, RUN, close_others
from gi.repository import Gio, GdkPixbuf

base.CSS += """
window.grid { background: rgba(0, 0, 0, 0.95); }
.search { background: #120a0a; color: #e8dede; border: 1px solid #5f0d11; border-radius: 99px; padding: 6px 16px; min-height: 30px; font-size: 14px; caret-color: #c41e2a; }
.wincard { background: transparent; border: none; padding: 6px; border-radius: 14px; }
.wincard:hover { background: rgba(95, 13, 17, 0.35); }
.thumb { border-radius: 10px; }
.wintitle { color: #e8dede; font-size: 12px; }
.winclose { background: #5f0d11; color: #ffffff; border: none; border-radius: 99px; min-width: 28px; min-height: 28px; padding: 0; margin: 0; }
.winclose:hover { background: #c41e2a; }
.folder { background: transparent; border: none; border-radius: 22px; padding: 10px; }
.folder:hover, .folder.open { background: rgba(95, 13, 17, 0.45); }
.foldericon { background: rgba(255, 255, 255, 0.08); border-radius: 24px; padding: 12px; }
.fname, .aname { color: #e8dede; font-size: 13px; font-weight: 600; }
.popup { background: #0c0707; border: 1px solid #5f0d11; border-radius: 26px; padding: 18px; }
.ptitle { color: #c41e2a; font-weight: 800; font-size: 18px; margin-bottom: 8px; }
.app { background: transparent; border: none; border-radius: 16px; padding: 8px; }
.app:hover { background: rgba(95, 13, 17, 0.45); }
.app.sel { background: rgba(196, 30, 42, 0.45); box-shadow: inset 0 0 0 2px #c41e2a; }
.empty { color: #8c7a7a; font-size: 14px; }
"""

def app_infos():
    infos = {}
    for a in Gio.AppInfo.get_all():
        if isinstance(a, Gio.DesktopAppInfo) and a.should_show():
            infos[a.get_id()] = a
    return infos

def folders(infos):
    s = Gio.Settings.new("org.gnome.desktop.app-folders")
    out, used = [], set()
    for fid in s.get_strv("folder-children"):
        f = Gio.Settings.new_with_path("org.gnome.desktop.app-folders.folder", f"/org/gnome/desktop/app-folders/folders/{fid}/")
        apps = [a for a in f.get_strv("apps") if a in infos]
        used.update(apps)
        if apps: out.append((f.get_string("name"), apps))
    loose = sorted([a for a in infos if a not in used], key=lambda a: infos[a].get_display_name().casefold())
    return out, loose

POOL = ThreadPoolExecutor(4)
def icon_img(info, size):
    """Monochrome icon, the same as the dock's: white on transparent (mono_icon.py, shared cache)."""
    img = Gtk.Image(); img.set_pixel_size(size)
    aid = info.get_id() if info else None
    icon = info.get_string("Icon") if info else None
    p = mono_icon.cached(aid, icon)
    if p: img.set_from_file(p); return img
    src = mono_icon.icon_file(Gtk.IconTheme.get_for_display(Gdk.Display.get_default()), icon)
    def done(f):
        out = f.result()
        if out: GLib.idle_add(lambda: (img.set_from_file(out), False)[1])
    POOL.submit(mono_icon.render, aid, icon, src).add_done_callback(done)
    return img

def launch(info):
    try: info.launch([], None)
    except Exception: spawn_id = info.get_id(); base.spawn(f"gtk-launch '{spawn_id}'")

def windows():
    try:
        clients = json.loads(sh("hyprctl", "clients", "-j"))
        ws = json.loads(sh("hyprctl", "activeworkspace", "-j"))["id"]
    except Exception:
        return []
    return [c for c in clients if c.get("workspace", {}).get("id") == ws and c.get("mapped", True)
            and c["size"][0] > 40 and c["size"][1] > 40]

def iter_children(w):
    c = w.get_first_child()
    while c:
        yield c; c = c.get_next_sibling()

def build(win, infos):
    root = Gtk.Overlay()
    W, H = win.mon_w, win.mon_h
    col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); root.set_child(col)

    # search
    entry = Gtk.Entry(placeholder_text="Type to search", halign=Gtk.Align.CENTER, width_chars=36)
    entry.add_css_class("search"); entry.set_margin_top(base.bar_height() + 14); col.append(entry)

    # top 60%: windows
    top = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False, max_children_per_line=6,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, column_spacing=18, row_spacing=18)
    topwrap = Gtk.Box(); topwrap.set_size_request(-1, int(H * 0.6) - base.bar_height() - 60)
    topwrap.append(top); top.set_hexpand(True); col.append(topwrap)
    wins = windows()
    n = max(1, len(wins)); per = min(n, 3 if n <= 6 else 4); rows = (n + per - 1) // per
    maxw = int((W * 0.82) / per) - 30; maxh = int((H * 0.6 - 140) / rows) - 40
    thumbs = []
    for c in wins:
        cw, ch = c["size"]; sc = min(maxw / cw, maxh / ch, 0.6)
        tw, th = max(80, int(cw * sc)), max(60, int(ch * sc))
        b = Gtk.Button(); b.add_css_class("wincard")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        pic = Gtk.Picture(); pic.add_css_class("thumb"); pic.set_size_request(tw, th); pic.set_can_shrink(True)
        v.append(pic)
        t = Gtk.Label(label=c.get("title") or c.get("class", ""), max_width_chars=30, ellipsize=3); t.add_css_class("wintitle")
        v.append(t); b.set_child(v)
        b.connect("clicked", lambda _b, a=c["address"]: (sh("@HOME@/.local/bin/hl-dsp", f'hl.dsp.focus({{window="address:{a}"}})', "focuswindow", f"address:{a}"), win.close()))
        # close button on hover (top-right corner, like GNOME) + middle-click on the preview
        card = Gtk.Overlay(); card.set_child(b)
        x = Gtk.Button(icon_name="window-close-symbolic", halign=Gtk.Align.END, valign=Gtk.Align.START, tooltip_text="Close")
        x.add_css_class("winclose"); x.set_visible(False); card.add_overlay(x)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_a, x=x: x.set_visible(True))
        hover.connect("leave", lambda *_a, x=x: x.set_visible(False))
        card.add_controller(hover)
        x.connect("clicked", lambda _b, a=c["address"], card=card: close_window(a, card))
        mid = Gtk.GestureClick(button=2)
        mid.connect("released", lambda *_a, a=c["address"], card=card: close_window(a, card))
        b.add_controller(mid)
        top.append(card); thumbs.append((c, pic))

    def close_window(a, card):
        sh("@HOME@/.local/bin/hl-dsp", f'hl.dsp.window.close({{window="address:{a}"}})', "closewindow", f"address:{a}")
        child = card.get_parent()  # the FlowBoxChild wrapping the card
        if child: child.set_visible(False)
        def check():
            # still open after a moment = the app is asking something (unsaved changes): show it
            if any(c["address"] == a for c in windows()):
                sh("@HOME@/.local/bin/hl-dsp", f'hl.dsp.focus({{window="address:{a}"}})', "focuswindow", f"address:{a}")
                win.close()
            elif not any(ch.get_visible() for ch in iter_children(top)):
                top.append(Gtk.Label(label="No open windows", css_classes=["empty"]))
            return False
        GLib.timeout_add(700, check)

    if not wins:
        top.append(Gtk.Label(label="No open windows", css_classes=["empty"]))

    # bottom 40%: folders row (+ loose apps after them)
    fl, loose = folders(infos)
    row = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True)
    grid_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True); grid_area.append(row); col.append(grid_area)
    ICON = 112 if W >= 1700 else 88
    pop_holder = {"w": None, "btn": None}
    def close_popup():
        if pop_holder["w"]: root.remove_overlay(pop_holder["w"]); pop_holder["w"] = None
        if pop_holder["btn"]: pop_holder["btn"].remove_css_class("open"); pop_holder["btn"] = None
    def app_grid(apps, title=None, btns=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); box.add_css_class("popup")
        box.set_halign(Gtk.Align.CENTER); box.set_valign(Gtk.Align.END); box.set_margin_bottom(int(H * 0.40) - 20)
        if title: box.append(Gtk.Label(label=title, css_classes=["ptitle"]))
        fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8, min_children_per_line=min(8, max(1, len(apps))),
                         homogeneous=True, column_spacing=6, row_spacing=6)
        for aid in apps:
            info = infos[aid]
            b = Gtk.Button(); b.add_css_class("app"); b.set_tooltip_text(info.get_description() or info.get_display_name())
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6); v.append(icon_img(info, 64))
            l = Gtk.Label(label=info.get_display_name(), max_width_chars=12, ellipsize=3, justify=Gtk.Justification.CENTER); l.add_css_class("aname")
            v.append(l); b.set_child(v); b.set_size_request(118, -1)
            b.connect("clicked", lambda _b, i=info: (launch(i), win.close()))
            fb.append(b)
            if btns is not None: btns.append(b)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True, propagate_natural_width=True)
        sc.set_max_content_height(int(H * 0.5) - 120); sc.set_child(fb); box.append(sc)
        return box
    def open_folder(btn, name, apps):
        was = pop_holder["btn"] is btn
        close_popup()
        if was: return
        p = app_grid(apps, name); root.add_overlay(p); pop_holder["w"] = p; pop_holder["btn"] = btn; btn.add_css_class("open")
    def folder_tile(name, apps):
        b = Gtk.Button(); b.add_css_class("folder")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        g = Gtk.Grid(row_spacing=8, column_spacing=8, halign=Gtk.Align.CENTER); g.add_css_class("foldericon")
        g.set_size_request(ICON, ICON)
        mini = (ICON - 24 - 8) // 2
        for i, aid in enumerate(apps[:4]):
            g.attach(icon_img(infos[aid], mini), i % 2, i // 2, 1, 1)
        v.append(g)
        l = Gtk.Label(label=name, max_width_chars=12, ellipsize=3); l.add_css_class("fname"); v.append(l)
        b.set_child(v); b.connect("clicked", lambda _b: open_folder(b, name, apps))
        return b
    for name, apps in fl: row.append(folder_tile(name, apps))
    for aid in loose[:max(0, 10 - len(fl))]:
        info = infos[aid]; b = Gtk.Button(); b.add_css_class("folder")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); v.append(icon_img(info, ICON))
        l = Gtk.Label(label=info.get_display_name(), max_width_chars=12, ellipsize=3); l.add_css_class("fname"); v.append(l)
        b.set_child(v); b.connect("clicked", lambda _b, i=info: (launch(i), win.close())); row.append(b)
    if len(loose) > max(0, 10 - len(fl)):
        rest = loose[max(0, 10 - len(fl)):]
        row.append(folder_tile("Other Apps", rest))

    # search: replaces the overview with matching apps
    results = {"w": None, "btns": [], "sel": 0}
    def select(i):
        bs = results["btns"]
        if not bs: return
        if 0 <= results["sel"] < len(bs): bs[results["sel"]].remove_css_class("sel")
        results["sel"] = i = max(0, min(i, len(bs) - 1)); bs[i].add_css_class("sel")
    def on_search(e):
        q = e.get_text().strip().casefold()
        if results["w"]: root.remove_overlay(results["w"]); results["w"] = None
        results["btns"] = []; results["sel"] = 0
        close_popup()
        topwrap.set_visible(not q); grid_area.set_visible(not q)
        if not q: return
        hits = [aid for aid, i in infos.items()
                if q in i.get_display_name().casefold() or q in (i.get_description() or "").casefold()
                or any(q in k.casefold() for k in (i.get_keywords() or []))]
        hits.sort(key=lambda a: (not infos[a].get_display_name().casefold().startswith(q), infos[a].get_display_name().casefold()))
        if hits:
            w = app_grid(hits[:32], f"{len(hits)} result{'s' if len(hits) != 1 else ''}", results["btns"])
            w.set_valign(Gtk.Align.START); w.set_margin_bottom(0); w.set_margin_top(base.bar_height() + 70)
        else:
            w = Gtk.Label(label="No results", css_classes=["empty"], valign=Gtk.Align.START); w.set_margin_top(base.bar_height() + 90)
        root.add_overlay(w); results["w"] = w
        select(0)   # first result is pre-selected: Enter opens it
    entry.connect("changed", on_search)
    def on_activate(e):
        bs = results["btns"]
        if bs: bs[results["sel"]].emit("clicked")
    entry.connect("activate", on_activate)

    # thumbnails: grab each window region after we're shown (cheap, async)
    for c, pic in thumbs:   # captured before the overlay was mapped (see main)
        f = SHOTS.get(c["address"])
        if f and os.path.exists(f): pic.set_filename(f)

    # click on empty space closes (folder popup first, then the overview)
    click = Gtk.GestureClick(); click.set_button(0)
    def pressed(g, n, x, y):
        w = win.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and not isinstance(w, (Gtk.Button, Gtk.Entry, Gtk.ScrolledWindow)) and not (w.has_css_class("popup") if hasattr(w, "has_css_class") else False):
            w = w.get_parent()
        if w is None:
            if pop_holder["w"]: close_popup()
            else: win.close()
    click.connect("pressed", pressed); win.add_controller(click)
    keys = Gtk.EventControllerKey()
    def key(c, k, code, mods):
        if k == Gdk.KEY_Escape:
            if entry.get_text(): entry.set_text(""); return True
            if pop_holder["w"]: close_popup(); return True
            win.close(); return True
        # arrows / Tab move the highlighted search result (8 per row)
        if results["btns"]:
            step = {Gdk.KEY_Right: 1, Gdk.KEY_Left: -1, Gdk.KEY_Down: 8, Gdk.KEY_Up: -8,
                    Gdk.KEY_Tab: 1, Gdk.KEY_ISO_Left_Tab: -1}.get(k)
            if step: select(results["sel"] + step); return True
        return False
    keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)   # before the search box eats arrows/Tab
    keys.connect("key-pressed", key); win.add_controller(keys)
    return root, entry

SHOTS = {}
def capture_windows():
    """Grab the current workspace's windows in parallel before our overlay appears."""
    procs = []
    for c in windows():
        x, y = c["at"]; w_, h_ = c["size"]
        f = os.path.join(tempfile.gettempdir(), f"kbgrid-{c['address']}.png")
        procs.append((c["address"], f, subprocess.Popen(["grim", "-s", "0.4", "-g", f"{x},{y} {w_}x{h_}", f],
                                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
    for a, f, p in procs:
        try: p.wait(timeout=2); SHOTS[a] = f
        except Exception: pass

def main():
    capture_windows()
    name = "appgrid"; pidf = os.path.join(RUN, f"kbpop-{name}.pid")
    close_others(name); open(pidf, "w").write(str(os.getpid()))
    # snapshot windows BEFORE our overlay maps, so thumbnails don't include the grid
    prov = Gtk.CssProvider(); prov.load_from_data(base.CSS.encode(), -1)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    app = Gtk.Application(application_id="ph.kb.pop.appgrid", flags=Gio.ApplicationFlags.NON_UNIQUE)
    def act(app):
        infos = app_infos()
        win = Gtk.ApplicationWindow(application=app); win.add_css_class("kbpop"); win.add_css_class("grid")
        LS.init_for_window(win); LS.set_namespace(win, "kb-appgrid"); LS.set_layer(win, LS.Layer.OVERLAY)
        for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT): LS.set_anchor(win, e, True)
        LS.set_exclusive_zone(win, -1); LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
        try:
            m = next(x for x in json.loads(sh("hyprctl", "monitors", "-j")) if x.get("focused"))
            win.mon_w, win.mon_h = int(m["width"] / m["scale"]), int(m["height"] / m["scale"])
        except Exception:
            win.mon_w, win.mon_h = 1920, 1200
        root, entry = build(win, infos)
        win.set_child(root); win.present(); entry.grab_focus()
    app.connect("activate", act)
    try: app.run([])
    finally:
        try: os.remove(pidf)
        except OSError: pass

main()
