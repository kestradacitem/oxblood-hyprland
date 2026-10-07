#!/usr/bin/env python3
"""HyprPanel-style dashboard (profile + power, shortcuts, toggles, folders, system stats)
in kb's OLED black + vampire red theme. Opens from the bar's top-right status icons."""
import json, os, re, shutil, subprocess, sys, threading, time
sys.path.insert(0, os.path.dirname(__file__))
import base
from base import Gtk, GLib, run_popup, sh, spawn, label

base.CSS += """
.card.dash { padding: 6px; border-radius: 0; }
.panel { background: #0c0707; border-radius: 0; padding: 5px 8px; }
.avatar { border-radius: 0; }
.avbtn { background: transparent; border: none; border-radius: 0; padding: 2px; min-height: 0; min-width: 0; }
.avbtn:hover { background: #2a0a0d; }
.uname { color: #e8dede; font-weight: 400; font-size: 14px; }
.usub { color: #8c7a7a; font-size: 11px; }
/* every dashboard button: dark red background, white icon */
.pbtn, .sbtn, .tbtn { background: #7a0f16; color: #ffffff; border: none; border-radius: 0; padding: 0; box-shadow: none; }
.pbtn:hover, .sbtn:hover, .tbtn:hover { background: #9e1b24; }
.pbtn { min-width: 34px; min-height: 34px; font-size: 15px; }
.pbtn.confirm { background: #c41e2a; font-size: 11px; font-weight: 400; }
.sbtn { min-height: 34px; font-size: 17px; }
.sbtn.rec { background: #c41e2a; }
.tbtn { min-height: 32px; font-size: 17px; background: #2e080b; color: rgba(255,255,255,0.55); }
.tbtn.on { background: #7a0f16; color: #ffffff; }
.dir { background: transparent; border: none; border-radius: 0; padding: 3px 6px; min-height: 0; }
.dir:hover { background: #1a0b0c; }
.diricon { color: #c41e2a; font-size: 15px; min-width: 18px; }
.dirname { color: #e8dede; font-weight: 400; font-size: 14px; }
.sicon2 { color: #c41e2a; font-size: 15px; min-width: 20px; }
progressbar trough { background: #2a0a0d; min-height: 8px; border-radius: 0; }
progressbar progress { background: #c41e2a; min-height: 8px; border-radius: 0; }
progressbar.mem progress { background: #e04450; } progressbar.disk progress { background: #9e1b24; }
.stat { color: #e8dede; font-weight: 400; font-size: 12px; font-feature-settings: "tnum"; }
.nhead { color: #e8dede; font-weight: 400; font-size: 14px; }
.nclear { background: #7a0f16; color: #ffffff; border: none; border-radius: 0; padding: 1px 10px; font-size: 11px; min-height: 0; }
.nclear:hover { background: #9e1b24; }
.nitem { background: #120a0a; border-radius: 0; padding: 6px 8px; }
.napp { color: #e04450; font-weight: 400; font-size: 11px; }
.ntime { color: #8c7a7a; font-size: 11px; }
.nsum { color: #e8dede; font-weight: 400; font-size: 14px; }
.nbody { color: #bfb0b0; font-size: 12px; }
.nx { background: #7a0f16; border: none; color: #ffffff; min-width: 20px; min-height: 20px; padding: 0; border-radius: 0; font-size: 10px; }
.nx:hover { background: #9e1b24; }
.nempty { color: #8c7a7a; font-size: 12px; }
.cname { color: #e8dede; font-weight: 400; font-size: 13px; }
.cstat { color: #8c7a7a; font-size: 11px; }
.cstat.up { color: #e04450; }
.cbtn { background: #7a0f16; color: #ffffff; border: none; border-radius: 0; padding: 0; min-width: 26px; min-height: 22px; font-size: 13px; box-shadow: none; }
.cbtn:hover { background: #9e1b24; }
.cinfo { padding: 2px 4px; }
.cinfo label { font-weight: 400; }
.cbtn.off { background: #2e080b; color: rgba(255,255,255,0.35); }
"""
HOME = os.path.expanduser("~")
REC_PID = os.path.join(base.RUN, "kb-recorder.pid")
GNOME = "env XDG_CURRENT_DESKTOP=GNOME "

def recording():
    try: os.kill(int(open(REC_PID).read()), 0); return True
    except Exception: return False
def toggle_record():
    if recording():
        try: os.kill(int(open(REC_PID).read()), 2)
        except Exception: pass
        try: os.remove(REC_PID)
        except OSError: pass
        sh("notify-send", "Screen recording saved", "~/Videos/Screencasts")
    else:
        os.makedirs(f"{HOME}/Videos/Screencasts", exist_ok=True)
        f = time.strftime(f"{HOME}/Videos/Screencasts/Recording %Y-%m-%d %H-%M-%S.mp4")
        p = subprocess.Popen(["wf-recorder", "-f", f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        open(REC_PID, "w").write(str(p.pid))

def panel(child, hexpand=True):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=hexpand); b.add_css_class("panel"); b.append(child); return b

def build(win):
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); root.add_css_class("card"); root.add_css_class("dash")

    # --- row 1: profile (avatar + name) | power buttons, one compact row
    r1 = Gtk.Box(spacing=10)
    subprocess.run(["@HOME@/.local/bin/kb-avatar-sync"], timeout=5)
    av = Gtk.Image.new_from_file(f"{HOME}/.cache/kb-qs/avatar.png"); av.set_pixel_size(48); av.add_css_class("avatar")
    avb = Gtk.Button(valign=Gtk.Align.CENTER); avb.add_css_class("avbtn"); avb.set_child(av); avb.set_tooltip_text("Change profile picture")
    avb.connect("clicked", lambda *_: (win.close(), spawn("@HOME@/.local/bin/kb-avatar-pick")))
    r1.append(avb)
    who = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
    up = int(float(open("/proc/uptime").read().split()[0]) // 60)
    who.append(label(os.environ.get("USER", "kb"), "uname")); who.append(label(f"up {up // 60} h {up % 60} min" if up >= 60 else f"up {up} min", "usub"))
    r1.append(who)
    pw = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
    for ic, tip, cmd in [("⏻", "Power off", "systemctl poweroff"), ("󰜉", "Restart", "systemctl reboot"),
                         ("󰍃", "Log out", "@HOME@/.local/bin/hl-dsp 'hl.dsp.exit()' exit"), ("󰒲", "Suspend", "systemctl suspend")]:
        b = Gtk.Button(label=ic); b.add_css_class("pbtn"); b.set_tooltip_text(tip)
        def click(btn, ic=ic, cmd=cmd):
            if btn.has_css_class("confirm"): win.close(); spawn(cmd); return
            btn.add_css_class("confirm"); btn.set_label("OK?")
            GLib.timeout_add(2500, lambda: (btn.remove_css_class("confirm"), btn.set_label(ic), False)[2])
        b.connect("clicked", click); pw.append(b)
    r1.append(pw)
    root.append(panel(r1))

    # --- row 2: shortcuts, one row
    r2 = Gtk.Box(spacing=6, homogeneous=True)
    def sbtns(items):
        for ic, tip, fn in items:
            b = Gtk.Button(label=ic); b.add_css_class("sbtn"); b.set_tooltip_text(tip)
            if tip == "Record" and recording(): b.add_css_class("rec")
            b.connect("clicked", lambda _b, fn=fn: fn()); r2.append(b)
    go = lambda cmd: (lambda: (spawn(cmd), win.close()))
    sbtns([("\U000F02AF", "Thorium", go("thorium-browser")), ("\U000F0361", "Viber", go("viber")),
           ("\U000F04C7", "Spotify", go("spotify")), ("\U000F0349", "Search apps", go("@HOME@/.local/bin/kb-popup appgrid")),
           ("\U000F0379", "Remmina", go("remmina")), ("\U000F0100", "Screenshot", go("sleep 0.4; ~/.config/hypr/scripts/screenshot.sh area")),
           ("\U000F0493", "Settings", go(GNOME + "gnome-control-center")),
           ("\U000F044A", "Record", lambda: (toggle_record(), win.close()))])
    root.append(panel(r2))

    # --- row 3: toggles
    toggles = Gtk.Box(spacing=6, homogeneous=True)
    tb = {}
    def tbtn(key, ic_on, ic_off, fn):
        b = Gtk.Button(label=ic_on); b.add_css_class("tbtn"); b.ic = (ic_on, ic_off)
        b.connect("clicked", lambda *_: (threading.Thread(target=fn, daemon=True).start(), GLib.timeout_add(400, lambda: (refresh(), False)[1])))
        toggles.append(b); tb[key] = b
    tbtn("wifi", "󰖩", "󰖪", lambda: sh("nmcli", "radio", "wifi", "off" if sh("nmcli", "-t", "-f", "WIFI", "radio") == "enabled" else "on"))
    tbtn("bt", "󰂯", "󰂲", lambda: sh("bluetoothctl", "power", "off" if "Powered: yes" in sh("bluetoothctl", "show") else "on"))
    def dnd():
        st = os.path.expanduser("~/.cache/kb-qs/dnd"); r = sh("hyprpanel", "toggleDnd", timeout=5)
        if r: open(st, "w").write(r)
    tbtn("dnd", "󰂚", "󰂛", dnd)
    tbtn("spk", "󰕾", "󰖁", lambda: sh("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"))
    tbtn("mic", "󰍬", "󰍭", lambda: sh("wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"))
    root.append(panel(toggles))

    # --- row 4: folders
    dirs = Gtk.Grid(column_spacing=6, row_spacing=2, column_homogeneous=True)
    for i, (ic, name, path) in enumerate([("\U000F024D", "Downloads", "Downloads"), ("\U000F19F6", "Documents", "Documents"),
                                          ("\U000F024F", "Videos", "Videos"), ("\U000F024F", "Pictures", "Pictures"),
                                          ("\U000F075A", "Music", "Music"), ("\U000F10B5", "Home", "")]):
        b = Gtk.Button(); b.add_css_class("dir"); b.set_tooltip_text(f"{HOME}/{path}")
        row = Gtk.Box(spacing=10); row.append(label(ic, "diricon", xalign=0.5)); row.append(label(name, "dirname"))
        b.set_child(row)
        b.connect("clicked", lambda _b, p=path: (spawn(f"xdg-open '{HOME}/{p}'"), win.close()))
        dirs.attach(b, i % 2, i // 2, 1, 1)
    root.append(panel(dirs))

    # --- row 5: stats
    stats = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    bars = {}
    for key, ic, cls in [("cpu", "\U000F0EE0", "cpu"), ("mem", "\U000F061A", "mem"), ("disk", "\U000F02CA", "disk")]:
        row = Gtk.Box(spacing=10); row.append(label(ic, "sicon2", xalign=0.5))
        pb = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER); pb.add_css_class(cls); row.append(pb)
        val = label("", "stat", xalign=1); val.set_size_request(84, -1); row.append(val)
        stats.append(row); bars[key] = (pb, val)
    root.append(panel(stats))

    # --- row 6: docker containers (status + start/stop + restart)
    cbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    chead = Gtk.Box(); chead.append(label("Containers", "nhead")); cbox.append(chead)
    clist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); cbox.append(clist)
    cstate = {"sig": None, "busy": set()}
    def docker_list():
        # never wake docker.service just to look (it is socket-activated)
        if sh("systemctl", "is-active", "docker.service") != "active": return None
        out = sh("docker", "ps", "-a", "--format", "{{.Names}}|{{.State}}|{{.Status}}")
        return [l.split("|", 2) for l in out.splitlines() if l.count("|") == 2]
    def cact(name, verb):
        cstate["busy"].add(name); crender(cstate.get("last"), force=True)
        def work():
            t = ["-t", "120"] if verb in ("stop", "restart") else []
            sh("docker", verb, *t, name, timeout=180)
            cstate["busy"].discard(name); refresh()
        threading.Thread(target=work, daemon=True).start()
    def copen(name):
        # kb-container-open starts the container if needed, waits for its web UI, then opens the browser
        spawn(f"{HOME}/.local/bin/kb-container-open '{name}'"); win.close()
    def crender(rows, force=False):
        cstate["last"] = rows
        sig = (repr(rows), tuple(sorted(cstate["busy"])))
        if sig == cstate["sig"] and not force: return
        cstate["sig"] = sig
        c = clist.get_first_child()
        while c: n = c.get_next_sibling(); clist.remove(c); c = n
        if rows is None: clist.append(label("Docker is not running", "nempty")); return
        if not rows: clist.append(label("No containers", "nempty")); return
        for name, state, status in rows:
            up = state in ("running", "paused", "restarting")
            row = Gtk.Box(spacing=8)
            info = Gtk.Box(spacing=8)
            info.append(label("\U000F05B3" if name == "WinApps" else "\U000F0868", "sicon2", xalign=0.5))
            info.append(label(name, "cname"))
            busy = name in cstate["busy"]
            txt = "working…" if busy else re.sub(r" \(.*?\)", "", status).replace("Up ", "up ").replace("Exited", "stopped").replace(" ago", "")
            st = label(txt, "cstat"); st.set_hexpand(True); st.set_ellipsize(3)
            if up: st.add_css_class("up")
            info.append(st)
            ib = Gtk.Button(hexpand=True); ib.add_css_class("dir"); ib.add_css_class("cinfo"); ib.set_child(info)
            ib.set_tooltip_text("Open in browser" if up else "Start and open in browser")
            ib.connect("clicked", lambda _b, n=name: copen(n))
            row.append(ib)
            b1 = Gtk.Button(label="\U000F04DB" if up else "\U000F040A"); b1.add_css_class("cbtn"); b1.set_tooltip_text("Turn off" if up else "Start")
            b1.connect("clicked", lambda _b, n=name, v=("stop" if up else "start"): cact(n, v))
            b2 = Gtk.Button(label="\U000F0709"); b2.add_css_class("cbtn"); b2.set_tooltip_text("Restart")
            if not up: b2.add_css_class("off"); b2.set_sensitive(False)
            b2.connect("clicked", lambda _b, n=name: cact(n, "restart"))
            for b in (b1, b2):
                b.set_valign(Gtk.Align.CENTER)
                if busy: b.set_sensitive(False)
                row.append(b)
            clist.append(row)
    root.append(panel(cbox))

    # --- row 7 (bottom): notifications
    NF = os.path.expanduser("~/.cache/kb-qs/notifs.json")
    nbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    head = Gtk.Box(); head.append(label("Notifications", "nhead")); head.append(Gtk.Box(hexpand=True))
    clr = Gtk.Button(label="Clear all"); clr.add_css_class("nclear"); head.append(clr); nbox.append(head)
    nlist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    nsc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
    nsc.set_max_content_height(200); nsc.set_child(nlist); nbox.append(nsc)
    def ago(t):
        d = int(time.time() - t)
        return "now" if d < 60 else f"{d // 60} min ago" if d < 3600 else f"{d // 3600} h ago" if d < 86400 else time.strftime("%-d %b", time.localtime(t))
    def nload():
        try: return json.load(open(NF))
        except Exception: return []
    def nsave(data):
        tmp = NF + ".tmp"; json.dump(data, open(tmp, "w"), ensure_ascii=False); os.replace(tmp, NF)
    def nrender():
        c = nlist.get_first_child()
        while c: n = c.get_next_sibling(); nlist.remove(c); c = n
        data = nload()
        clr.set_visible(bool(data))
        if not data: nlist.append(label("No notifications", "nempty")); return
        for it in data[:20]:
            row = Gtk.Box(spacing=8); row.add_css_class("nitem")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
            top = Gtk.Box(spacing=6); top.append(label(it.get("app", ""), "napp")); top.append(label("· " + ago(it.get("t", 0)), "ntime")); v.append(top)
            if it.get("summary"):
                l = label(it["summary"], "nsum"); l.set_wrap(True); l.set_max_width_chars(40); v.append(l)
            if it.get("body"):
                b = label(re.sub(r"<[^>]+>", "", it["body"]), "nbody"); b.set_wrap(True); b.set_max_width_chars(44); b.set_lines(3); b.set_ellipsize(3); v.append(b)
            row.append(v)
            x = Gtk.Button(label="✕"); x.add_css_class("nx"); x.set_valign(Gtk.Align.START)
            x.connect("clicked", lambda _b, i=it.get("id"): (nsave([d for d in nload() if d.get("id") != i]), nrender()))
            row.append(x); nlist.append(row)
    clr.connect("clicked", lambda *_: (nsave([]), nrender()))
    nrender()
    root.append(panel(nbox))

    cpu_prev = {"t": None}
    def cpu_pct():
        a = list(map(int, open("/proc/stat").readline().split()[1:]))
        idle, total = a[3] + a[4], sum(a)
        p = cpu_prev["t"]; cpu_prev["t"] = (idle, total)
        if not p: return 0.0
        dt = total - p[1]; return 0.0 if dt <= 0 else 100.0 * (1 - (idle - p[0]) / dt)
    def gather():
        mi = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
        mt, ma = mi["MemTotal"] * 1024, mi["MemAvailable"] * 1024
        du = shutil.disk_usage("/")
        return {"cpu": cpu_pct(), "mem": (mt - ma, mt), "disk": (du.used, du.total),
                "wifi": sh("nmcli", "-t", "-f", "WIFI", "radio") == "enabled", "bt": "Powered: yes" in sh("bluetoothctl", "show"),
                "dnd": open(os.path.expanduser("~/.cache/kb-qs/dnd")).read().strip() == "Enabled" if os.path.exists(os.path.expanduser("~/.cache/kb-qs/dnd")) else False,
                "spk": "MUTED" not in sh("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"),
                "mic": "MUTED" not in sh("wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"),
                "docker": docker_list()}
    def apply(d):
        G = 1024 ** 3
        bars["cpu"][0].set_fraction(d["cpu"] / 100); bars["cpu"][1].set_text(f"{d['cpu']:.0f}%")
        u, t = d["mem"]; bars["mem"][0].set_fraction(u / t); bars["mem"][1].set_text(f"{u / G:.0f}/{t / G:.0f} GiB")
        u, t = d["disk"]; bars["disk"][0].set_fraction(u / t); bars["disk"][1].set_text(f"{u / G:.0f}/{t / G:.0f} GiB")
        for k in ("wifi", "bt", "spk", "mic"):
            b = tb[k]; on = d[k]; (b.add_css_class if on else b.remove_css_class)("on"); b.set_label(b.ic[0] if on else b.ic[1])
        crender(d["docker"])
        b = tb["dnd"]; on = not d["dnd"]; (b.add_css_class if on else b.remove_css_class)("on"); b.set_label(b.ic[0] if on else b.ic[1])
        return False
    busy = {"on": False}
    def refresh():
        if busy["on"]: return True
        busy["on"] = True
        def work():
            try: GLib.idle_add(apply, gather())
            finally: busy["on"] = False
        threading.Thread(target=work, daemon=True).start(); return True
    cpu_pct()
    GLib.timeout_add(150, lambda: (refresh(), False)[1]); GLib.timeout_add_seconds(2, refresh)
    return root

run_popup("dashboard", build, edge="right", width=400)
