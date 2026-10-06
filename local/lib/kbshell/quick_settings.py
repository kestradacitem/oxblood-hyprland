#!/usr/bin/env python3
"""GNOME Quick Settings look-alike for Hyprland (OLED black + maroon)."""
import json, os, re, subprocess, sys, threading
sys.path.insert(0, os.path.dirname(__file__))
from base import Gtk, GLib, run_popup, sh, spawn, label

ST = os.path.expanduser("~/.cache/kb-qs")
os.makedirs(ST, exist_ok=True)
def sget(k, d=""):
    try: return open(f"{ST}/{k}").read().strip()
    except OSError: return d
def sset(k, v): open(f"{ST}/{k}", "w").write(str(v))
def bg(fn, *a):  # run a slow command off the UI thread
    threading.Thread(target=fn, args=a, daemon=True).start()

# ---------------- system state ----------------
def battery():
    b = "/sys/class/power_supply/BAT1"
    try: return int(open(f"{b}/capacity").read()), open(f"{b}/status").read().strip()
    except OSError: return None, ""
def vol(dev):
    o = sh("wpctl", "get-volume", dev)          # "Volume: 0.40 [MUTED]"
    m = re.search(r"([\d.]+)", o)
    return (float(m.group(1)) if m else 0.0), "MUTED" in o
def devname(dev):
    o = sh("wpctl", "inspect", dev)
    m = re.search(r'node\.description = "([^"]+)"', o)
    n = m.group(1) if m else ""
    return n.replace(" Analog Stereo", "")
def brightness(dev=None):
    a = ["brightnessctl"] + (["-d", dev] if dev else []) + ["-m"]
    p = sh(*a).split(",")
    try: return int(p[2]), int(p[4])          # current, max
    except Exception: return 0, 1
def wifi():
    on = sh("nmcli", "-t", "-f", "WIFI", "radio") == "enabled"
    ssid = ""
    for l in sh("nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "dev").splitlines():   # cached, no scan
        p = l.split(":", 2)
        if len(p) == 3 and p[0] == "wifi" and p[1] == "connected": ssid = p[2]; break
    return on, ssid
def bt():
    s = sh("bluetoothctl", "show")
    on = "Powered: yes" in s
    conn = [l.split(" ", 2)[2] for l in sh("bluetoothctl", "devices", "Connected").splitlines() if l.count(" ") >= 2]
    return on, conn
PROFILES = [("power-saver", "Power Saver"), ("balanced", "Balanced"), ("performance", "Performance")]
def profile(): return sh("powerprofilesctl", "get") or "balanced"
def night(): return bool(sh("pgrep", "-x", "hyprsunset"))
def dark(): return "dark" in sh("gsettings", "get", "org.gnome.desktop.interface", "color-scheme")
def dnd(): return sget("dnd", "Disabled") == "Enabled"
def airplane():
    return sh("nmcli", "-t", "-f", "WIFI", "radio") != "enabled" and "Powered: yes" not in sh("bluetoothctl", "show")
def boost(): return sget("boost", "0") == "1"

# ---------------- widgets ----------------
class Tile(Gtk.Box):
    def __init__(self, icon, title, on_toggle, sub_builder=None):
        super().__init__(); self.add_css_class("tile"); self.set_hexpand(True)
        self.main = Gtk.Button(hexpand=True); self.main.add_css_class("tilemain")
        h = Gtk.Box(spacing=10)
        self.ic = label(icon, "tileicon"); h.append(self.ic)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.t = label(title, "tiletitle"); self.t.set_ellipsize(3); self.t.set_max_width_chars(11)
        self.s = label("", "tilesub"); self.s.set_ellipsize(3); self.s.set_max_width_chars(14)
        v.append(self.t); v.append(self.s); h.append(v)
        self.main.set_child(h); self.main.connect("clicked", lambda *_: on_toggle()); self.append(self.main)
        self.sub_builder = sub_builder
        if sub_builder:
            a = Gtk.Button(label="›"); a.add_css_class("tilearrow"); self.arrow = a; self.append(a)
    def set(self, on, sub=""):
        (self.add_css_class if on else self.remove_css_class)("on")
        self.s.set_text(sub); self.s.set_visible(bool(sub))

def build(win):
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); root.add_css_class("card")
    root.set_size_request(430, -1)

    # --- top row: battery | screenshot settings lock power
    top = Gtk.Box(spacing=8)
    batt = Gtk.Button(); batt.add_css_class("pill"); top.append(batt)
    batt.connect("clicked", lambda *_: (spawn("env XDG_CURRENT_DESKTOP=GNOME gnome-control-center power"), win.close()))
    top.append(Gtk.Box(hexpand=True))
    for ic, cmd in [("󰹑", "sleep 0.4; ~/.config/hypr/scripts/screenshot.sh area"),
                    ("󰒓", "env XDG_CURRENT_DESKTOP=GNOME gnome-control-center"),
                    ("󰌾", "loginctl lock-session"),
                    ("⏻", "~/.config/hypr/scripts/power-menu.sh")]:
        b = Gtk.Button(label=ic); b.add_css_class("round")
        b.connect("clicked", lambda _b, c=cmd: (spawn(c), win.close())); top.append(b)
    root.append(top)

    # --- sliders
    sliders = {}
    def slider(key, icon_on, icon_off, getter, setter, mute=None, maxv=1.0):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name = label("", "slabel"); box.append(name)
        row = Gtk.Box(spacing=6)
        ib = Gtk.Button(label=icon_on); ib.add_css_class("sicon"); row.append(ib)
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, maxv, 0.01); sc.set_hexpand(True); sc.set_draw_value(False)
        row.append(sc); box.append(row)
        st = {"lock": False, "pending": None}
        def changed(s):
            if st["lock"]: return
            v = s.get_value()
            if st["pending"]: GLib.source_remove(st["pending"])
            st["pending"] = GLib.timeout_add(60, lambda: (bg(setter, v), st.__setitem__("pending", None), False)[2])
        sc.connect("value-changed", changed)
        if mute: ib.connect("clicked", lambda *_: (bg(mute), GLib.timeout_add(250, lambda: (refresh(), False)[1])))
        sliders[key] = (sc, ib, name, st, icon_on, icon_off, getter)
        root.append(box); return sc
    slider("spk", "󰕾", "󰖁", lambda: vol("@DEFAULT_AUDIO_SINK@"),
           lambda v: sh("wpctl", "set-volume", "-l", "1.5" if boost() else "1.0", "@DEFAULT_AUDIO_SINK@", f"{v:.2f}"),
           lambda: sh("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"), maxv=1.5 if boost() else 1.0)
    slider("mic", "󰍬", "󰍭", lambda: vol("@DEFAULT_AUDIO_SOURCE@"),
           lambda v: sh("wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", f"{v:.2f}"),
           lambda: sh("wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"))
    slider("bri", "󰃠", "󰃠", lambda: (lambda c, m: (c / m, False))(*brightness()),
           lambda v: sh("brightnessctl", "-q", "set", f"{max(1, int(v * 100))}%"))
    sliders["bri"][2].set_visible(False)

    # --- tiles grid with expandable sub-panels
    grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True); root.append(grid)
    subwrap = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.NONE); root.append(subwrap)
    cur_sub = {"name": None}
    def toggle_sub(name, builder):
        if cur_sub["name"] == name:
            subwrap.set_reveal_child(False); cur_sub["name"] = None; return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); box.add_css_class("sub")
        builder(box); subwrap.set_child(box); subwrap.set_reveal_child(True); cur_sub["name"] = name
    def subitem(box, text, cmd_fn, active=False, dim=""):
        b = Gtk.Button(); b.add_css_class("subitem")
        if active: b.add_css_class("active")
        h = Gtk.Box(spacing=8); h.append(label(text, xalign=0)); 
        if dim: h.append(label(dim, "dim"))
        b.set_child(h)
        b.connect("clicked", lambda *_: (bg(cmd_fn), GLib.timeout_add(700, lambda: (refresh(), reopen(), False)[2])))
        box.append(b)
    def reopen():
        n = cur_sub["name"]
        if n: cur_sub["name"] = None; toggle_sub(n, SUBS[n])

    def sub_wifi(box):
        box.append(label("Wi-Fi Networks", "subhead"))
        spawn("nmcli dev wifi rescan")
        saved = set(sh("nmcli", "-t", "-f", "NAME", "con", "show").splitlines())
        seen = set()
        for l in sh("nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "no").splitlines()[:30]:
            p = re.split(r"(?<!\\):", l)
            if len(p) < 4 or not p[1] or p[1] in seen: continue
            seen.add(p[1]); act = p[0] == "yes"; ssid = p[1].replace("\\:", ":")
            known = ssid in saved
            cmd = (lambda s=ssid: sh("nmcli", "con", "up", "id", s, timeout=25)) if known else \
                  (lambda s=ssid: spawn(f"ptyxis -- nmcli --ask dev wifi connect '{s}'"))
            subitem(box, ("✓ " if act else "") + ssid, cmd, act, f"{p[2]}%{' · saved' if known else ''}")
            if len(seen) >= 8: break
        subitem(box, "Wi-Fi Settings…", lambda: spawn("env XDG_CURRENT_DESKTOP=GNOME gnome-control-center wifi"))
    def sub_bt(box):
        box.append(label("Bluetooth Devices", "subhead"))
        conn = set(l.split(" ", 2)[1] for l in sh("bluetoothctl", "devices", "Connected").splitlines() if " " in l)
        for l in sh("bluetoothctl", "devices", "Paired").splitlines():
            p = l.split(" ", 2)
            if len(p) < 3: continue
            mac, name = p[1], p[2]; on = mac in conn
            subitem(box, ("✓ " if on else "") + name,
                    (lambda m=mac, o=on: sh("bluetoothctl", "disconnect" if o else "connect", m, timeout=15)), on,
                    "connected" if on else "")
        subitem(box, "Bluetooth Settings…", lambda: spawn("env XDG_CURRENT_DESKTOP=GNOME gnome-control-center bluetooth"))
    def sub_power(box):
        box.append(label("Power Mode", "subhead")); cur = profile()
        for k, n in PROFILES:
            subitem(box, ("✓ " if k == cur else "") + n, lambda k=k: sh("powerprofilesctl", "set", k), k == cur)
    def sub_kbd(box):
        box.append(label("Keyboard Backlight", "subhead")); c, m = brightness("asus::kbd_backlight")
        for i, n in enumerate(["Off", "Low", "Medium", "High"][: m + 1]):
            subitem(box, ("✓ " if i == c else "") + n,
                    lambda i=i: sh("brightnessctl", "-q", "-d", "asus::kbd_backlight", "set", str(i)), i == c)
    def sub_mixer(box):
        box.append(label("Volume Mixer", "subhead"))
        try: streams = json.loads(sh("pactl", "-f", "json", "list", "sink-inputs") or "[]")
        except Exception: streams = []
        if not streams: box.append(label("  No apps are playing audio", "dim"))
        for s in streams:
            pr = s.get("properties", {})
            name = pr.get("application.name") or pr.get("media.name") or "App"
            v = s.get("volume", {}); ch = next(iter(v.values()), {}) if v else {}
            pct = int(str(ch.get("value_percent", "100%")).rstrip("%") or 100)
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); row.append(label(name, "slabel"))
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150 if boost() else 100, 1)
            sc.set_draw_value(False); sc.set_value(pct); sc.set_hexpand(True)
            sid = str(s.get("index"))
            sc.connect("value-changed", lambda w, i=sid: bg(sh, "pactl", "set-sink-input-volume", i, f"{int(w.get_value())}%"))
            row.append(sc); box.append(row)
        subitem(box, "Sound Settings…", lambda: spawn("env XDG_CURRENT_DESKTOP=GNOME gnome-control-center sound"))

    SUBS = {"wifi": sub_wifi, "bt": sub_bt, "power": sub_power, "kbd": sub_kbd, "mixer": sub_mixer}

    def t_wifi(): bg(lambda: sh("nmcli", "radio", "wifi", "off" if wifi()[0] else "on")); later()
    def t_bt(): bg(lambda: sh("bluetoothctl", "power", "off" if bt()[0] else "on")); later()
    def t_power():
        cur = profile(); nxt = {"power-saver": "balanced", "balanced": "power-saver", "performance": "balanced"}[cur]
        bg(lambda: sh("powerprofilesctl", "set", nxt)); later()
    def t_night():
        if night(): sh("pkill", "-x", "hyprsunset")
        else: spawn("hyprsunset -t 4000")
        later()
    def t_dark():
        v = "default" if dark() else "prefer-dark"
        bg(lambda: sh("gsettings", "set", "org.gnome.desktop.interface", "color-scheme", v)); later()
    def t_dnd():
        def f(): sset("dnd", sh("hyprpanel", "toggleDnd", timeout=5) or sget("dnd", "Disabled"))
        bg(f); later()
    def t_kbd():
        c, m = brightness("asus::kbd_backlight")
        bg(lambda: sh("brightnessctl", "-q", "-d", "asus::kbd_backlight", "set", "0" if c else str(min(2, m)))); later()
    def t_air():
        if airplane(): bg(lambda: (sh("nmcli", "radio", "wifi", "on"), sh("bluetoothctl", "power", "on")))
        else: bg(lambda: (sh("nmcli", "radio", "all", "off"), sh("bluetoothctl", "power", "off")))
        later(1500)
    def t_boost():
        on = not boost(); sset("boost", "1" if on else "0")
        sc = sliders["spk"][0]; sc.set_range(0, 1.5 if on else 1.0)
        if not on: bg(lambda: sh("wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{min(1.0, vol('@DEFAULT_AUDIO_SINK@')[0]):.2f}"))
        later()
    def t_mute(): bg(lambda: sh("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")); later()

    tiles = {
        "wifi": Tile("󰖩", "Wi-Fi", t_wifi, True), "bt": Tile("󰂯", "Bluetooth", t_bt, True),
        "power": Tile("󰌪", "Power Mode", t_power, True), "night": Tile("󰖔", "Night Light", t_night),
        "dark": Tile("󰔎", "Dark Style", t_dark), "dnd": Tile("󰂛", "Do Not Disturb", t_dnd),
        "kbd": Tile("󰌌", "Keyboard", t_kbd, True), "air": Tile("󰀝", "Airplane Mode", t_air),
        "boost": Tile("󰝝", "Volume Boost", t_boost), "mixer": Tile("󰕾", "Mixer", t_mute, True),
    }
    order = ["wifi", "bt", "power", "night", "dark", "dnd", "kbd", "air", "boost", "mixer"]
    for i, k in enumerate(order):
        t = tiles[k]; grid.attach(t, i % 2, i // 2, 1, 1)
        if t.sub_builder: t.arrow.connect("clicked", lambda *_, k=k: toggle_sub(k, SUBS[k]))

    def gather():
        c, stt = battery()
        return {
            "batt": (c, stt),
            "sl": {k: v[6]() for k, v in sliders.items()},
            "spkname": devname("@DEFAULT_AUDIO_SINK@"), "micname": devname("@DEFAULT_AUDIO_SOURCE@"),
            "wifi": wifi(), "bt": bt(), "profile": profile(), "night": night(), "dark": dark(), "dnd": dnd(),
            "kbd": brightness("asus::kbd_backlight"), "air": airplane(), "boost": boost(),
            "spk": vol("@DEFAULT_AUDIO_SINK@"),
        }
    def apply(d):
        c, stt = d["batt"]
        batt.set_label(f"{'\U000F0084' if stt == 'Charging' else '\U000F0079'}  {c}%" if c is not None else "No battery")
        for key, (sc, ib, name, st, ion, ioff, getter) in sliders.items():
            v, muted = d["sl"][key]
            if not st["pending"]:
                st["lock"] = True; sc.set_value(v); st["lock"] = False
            ib.set_label(ioff if muted else ion)
        sliders["spk"][2].set_text(f"Speakers – {d['spkname']}")
        sliders["mic"][2].set_text(f"Internal Microphone – {d['micname']}")
        w_on, ssid = d["wifi"]; tiles["wifi"].set(w_on, ssid if w_on else "Off")
        b_on, conn = d["bt"]; tiles["bt"].set(b_on, ", ".join(conn) if conn else ("" if b_on else "Off"))
        p = d["profile"]; tiles["power"].set(p != "balanced", dict(PROFILES).get(p, p))
        tiles["night"].set(d["night"]); tiles["dark"].set(d["dark"]); tiles["dnd"].set(d["dnd"])
        kc, km = d["kbd"]; tiles["kbd"].set(kc > 0, ["Off", "Low", "Medium", "High"][min(kc, 3)])
        tiles["air"].set(d["air"]); tiles["boost"].set(d["boost"], "Up to 150%" if d["boost"] else "")
        muted = d["spk"][1]; tiles["mixer"].set(not muted, "Muted" if muted else "")
        return False
    busy = {"on": False}
    def refresh():
        if busy["on"]: return True
        busy["on"] = True
        def work():
            try:
                d = gather(); GLib.idle_add(apply, d)
            finally:
                busy["on"] = False
        threading.Thread(target=work, daemon=True).start()
        return True
    def later(ms=500): GLib.timeout_add(ms, lambda: (refresh(), False)[1])
    globals()["refresh"] = refresh
    GLib.idle_add(lambda: (refresh(), False)[1]); GLib.timeout_add_seconds(2, refresh)
    return root

run_popup("quick", build, edge="right", width=430)
