#!/usr/bin/env python3
"""Drag-to-edge window snapping for floating windows (GNOME/KDE/Windows style).

While a window is being dragged, its position changes. If the pointer reaches an edge
and the window then stops moving (button released), snap it:
  left/right edge -> half, top edge -> maximize (work area), corners -> quarter.
Dragging a snapped/maximized window away restores its previous size under the pointer: done in the kb-minimize
plugin (a move from here would cancel Hyprland's drag). Snaps save the previous geometry for it and for kb-maximize in
$XDG_RUNTIME_DIR/kb-maximize/<address> as "x y w h sw sh" (2026-10-05).
Windows are kept fully inside the work area: too-big windows are fitted + centred, off-screen drops slide back in.
Talks to Hyprland's IPC socket directly (no process spawning) and polls only every 80 ms.
"""
import json, os, re, socket, time

SOCK = f"{os.environ['XDG_RUNTIME_DIR']}/hypr/{os.environ['HYPRLAND_INSTANCE_SIGNATURE']}/.socket.sock"
EDGE = 6        # px from the screen edge that triggers a snap
CORNER = 60     # px from a corner that counts as a corner
GAP = 0        # no gap around snapped windows (sleek)
POLL = 0.04
# hyprbars draws its bar ABOVE a window's own area. Windows that get a bar are placed BAR px lower,
# or the bar ends up behind the top panel (no buttons, nothing to drag). Mirrors titlebars.lua.
BAR = 26        # plugin:hyprbars:bar_height
NOBAR_CLASS = re.compile(r"^(org\.gnome\..*|(?i:.*codium.*)|(?i:onlyoffice.*)|(?i:firefox)|(?i:discord))$")

def bar(w):
    """Height of the hyprbars bar above window w (0 for apps that draw their own title bar)."""
    if "kbcsd" in (w.get("tags") or []) or NOBAR_CLASS.match(w.get("class") or ""): return 0
    if w.get("class") == "org.remmina.Remmina" and w.get("title") == "Remmina Remote Desktop Client": return 0
    return BAR
SETTLE = 0.12   # seconds without movement = drag ended
MAXDIR = f"{os.environ.get('XDG_RUNTIME_DIR', '/tmp')}/kb-maximize"

def ipc(cmd):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK); s.sendall(cmd.encode())
    out = b""
    while True:
        b = s.recv(65536)
        if not b: break
        out += b
    s.close()
    return out.decode()

def dsp(lua, legacy):
    """Dispatch in Lua syntax (hyprland.lua); fall back to the old syntax in a hyprland.conf session."""
    if ipc("dispatch " + lua).strip() != "ok":
        ipc("dispatch " + legacy)

def place(a, w, h, x, y):
    """Resize + move window `a` to exact logical pixels."""
    if w is not None:
        dsp(f'hl.dsp.window.resize({{x={w},y={h},window="address:{a}"}})', f"resizewindowpixel exact {w} {h},address:{a}")
    dsp(f'hl.dsp.window.move({{x={x},y={y},window="address:{a}"}})', f"movewindowpixel exact {x} {y},address:{a}")

def j(cmd):
    try: return json.loads(ipc("j/" + cmd))
    except Exception: return None

def workarea(mon):
    W = int(mon["width"] / mon["scale"]); H = int(mon["height"] / mon["scale"])
    l, t, r, b = mon["reserved"]
    return mon["x"] + l + GAP, mon["y"] + t + GAP, W - l - r - 2 * GAP, H - t - b - 2 * GAP

def clamp(w, mon):
    """Keep a floating window fully inside the work area (below the bar, inside the screen)."""
    X, Y, W, H = workarea(mon)
    b = bar(w); Y += b; H -= b
    x, y = w["at"]; cw, ch = w["size"]
    nw, nh = min(cw, W), min(ch, H)
    nx = min(max(x, X), X + W - nw); ny = min(max(y, Y), Y + H - nh)
    if (nw, nh) != (cw, ch) or (nx, ny) != (x, y):
        a = w["address"]
        if (nw, nh) != (cw, ch):   # too big: fit and centre
            nx = X + (W - nw) // 2; ny = Y + (H - nh) // 2
            place(a, nw, nh, nx, ny)
        else:
            place(a, None, None, nx, ny)
        return True
    return False

def zone(cx, cy, mon):
    W = mon["width"] / mon["scale"]; H = mon["height"] / mon["scale"]
    x, y = cx - mon["x"], cy - mon["y"]
    top_reserved = mon["reserved"][1]
    left, right = x <= EDGE, x >= W - 1 - EDGE
    top = y <= max(EDGE, top_reserved)   # pointer at the very top / on the panel
    bottom = y >= H - 1 - EDGE
    if left and y < CORNER + top_reserved: return "tl"
    if right and y < CORNER + top_reserved: return "tr"
    if left and y > H - CORNER: return "bl"
    if right and y > H - CORNER: return "br"
    if top and x < CORNER: return "tl"
    if top and x > W - CORNER: return "tr"
    if left: return "l"
    if right: return "r"
    if top: return "max"
    return None

def geometry(z, mon, b=0):
    X, Y, W, H = workarea(mon)
    hw, hh = (W - GAP) // 2, (H - GAP) // 2
    x, y, w, h = {
        "l": (X, Y, hw, H), "r": (X + hw + GAP, Y, hw, H), "max": (X, Y, W, H),
        "tl": (X, Y, hw, hh), "tr": (X + hw + GAP, Y, hw, hh),
        "bl": (X, Y + hh + GAP, hw, hh), "br": (X + hw + GAP, Y + hh + GAP, hw, hh),
    }[z]
    return x, y + b, w, h - b   # the zone includes the window's title bar

# GNOME-style preview + snap on release (2026-10-05). Needs the kb-minimize build that reports drags: it keeps
# $XDG_RUNTIME_DIR/kb-drag while a window is moved with the mouse (init.log "dragstate=1"). Without it we fall back
# to snapping when the window stops moving.
DRAGF = f"{os.environ.get('XDG_RUNTIME_DIR', '/tmp')}/kb-drag"
INITLOG = "@HOME@/.cache/kb-minimize/init.log"
_dm = {"t": 0.0, "on": False}
def dragmode():
    if time.time() - _dm["t"] > 5:
        _dm["t"] = time.time()
        try: _dm["on"] = "dragstate=1" in open(INITLOG).read()
        except OSError: _dm["on"] = False
    return _dm["on"]

_pv = {"p": None, "shown": None}
def preview(g):
    """Show the snap preview at g = (x, y, w, h), or hide it (None). Runs kbshell/snap_preview.py on demand."""
    if g == _pv["shown"]: return
    _pv["shown"] = g
    import subprocess
    for _ in range(2):
        p = _pv["p"]
        if p is None or p.poll() is not None:
            if g is None: return
            env = dict(os.environ, LD_PRELOAD="/usr/lib/libgtk4-layer-shell.so")
            p = _pv["p"] = subprocess.Popen(["python3", "@HOME@/.local/lib/kbshell/snap_preview.py"], stdin=subprocess.PIPE,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, text=True)
        try:
            p.stdin.write(("%d %d %d %d" % g if g else "hide") + "\n"); p.stdin.flush(); return
        except (BrokenPipeError, OSError):
            _pv["p"] = None

def snap(a, w, z, mon, snapped, last):
    x, y, gw, gh = geometry(z, mon, bar(w))
    orig = snapped.get(a, (None, tuple(w["size"])))[1]
    X, Y, W, H = workarea(mon)
    try:      # previous geometry (centred) + snapped size, for the plugin's drag-restore and kb-maximize
        os.makedirs(MAXDIR, exist_ok=True)
        with open(f"{MAXDIR}/{a}", "w") as f:
            f.write(f"{X + (W - orig[0]) // 2} {Y + (H - orig[1]) // 2} {orig[0]} {orig[1]} {gw} {gh}\n")
    except OSError: pass
    place(a, gw, gh, x, y)
    time.sleep(0.05)
    snapped[a] = ((x, y, gw, gh), orig)
    nw = j("activewindow")
    if nw and nw.get("address") == a: last[a] = (tuple(nw["at"]), time.time())

def main():
    snapped = {}            # address -> (snapped geometry, original size)
    last = {}               # address -> (at, last move time)
    pending = None          # (address, zone)
    slow = {"t": 0.0, "pos": {}}
    while True:
        time.sleep(POLL)
        if time.time() - slow["t"] > 0.5:      # slow pass: keep NON-active floating windows on screen
            slow["t"] = time.time()
            cl = j("clients") or []; aw = j("activewindow") or {}
            mons = j("monitors") or []; slow["mons"] = mons
            vis = {m.get("activeWorkspace", {}).get("id") for m in mons}
            for c in cl:
                ad = c.get("address")
                if ad == aw.get("address") or not c.get("floating") or c.get("fullscreen") or ad in snapped: continue
                if c.get("workspace", {}).get("id") not in vis or not c.get("mapped", True): continue
                pos = (tuple(c["at"]), tuple(c["size"]))
                if slow["pos"].get(ad) == pos:          # unchanged for a full pass
                    mon = next((m for m in mons if m["id"] == c.get("monitor")), mons[0] if mons else None)
                    if mon: clamp(c, mon)
                slow["pos"][ad] = pos
        w = j("activewindow")
        if not w or not w.get("address") or not w.get("floating") or w.get("fullscreen"):
            pending = None; preview(None); continue
        a, at = w["address"], tuple(w["at"])
        now = time.time()
        prev = last.get(a)
        moving = prev is not None and prev[0] != at
        dm = dragmode()
        if dm:
            dragging = os.path.exists(DRAGF)
            if dragging and not moving and prev and now - prev[1] > 5:
                try: dragging = time.time() - os.path.getmtime(DRAGF) < 60   # stale (missed release): give up after 60 s still
                except OSError: dragging = False
            if dragging:
                if moving: snapped.pop(a, None)      # the plugin restores the size (see the docstring)
                if moving or prev is None: last[a] = (at, now)
                cur = j("cursorpos")
                mon = next((m for m in (slow.get("mons") or []) if m["id"] == w.get("monitor")), None)
                z = zone(cur["x"], cur["y"], mon) if cur and mon else None
                pending = (a, z)
                preview(geometry(z, mon) if z else None)   # the whole slot, title bar included
                continue
            preview(None)
            if pending and pending[0] == a and pending[1]:   # released in a snap zone
                mons = j("monitors") or []
                mon = next((m for m in mons if m["id"] == w.get("monitor")), None)
                if mon: snap(a, w, pending[1], mon, snapped, last)
                pending = None; continue
            pending = None
        if moving:
            last[a] = (at, now)
            snapped.pop(a, None)      # the plugin restores the size (see the docstring)
            cur = j("cursorpos"); mons = j("monitors") or []
            mon = next((m for m in mons if m["focused"]), mons[0] if mons else None)
            pending = (a, zone(cur["x"], cur["y"], mon)) if cur and mon and not dm else None
            continue
        if prev is None:
            last[a] = (at, now)
            # maximized with no saved size (opened that way / after a reboot): save the uniform size, so the
            # restore button (kb-maximize) and a title-bar drag (kb-minimize) can un-maximize it
            mon = next((m for m in (slow.get("mons") or []) if m["id"] == w.get("monitor")), None)
            f = f"{MAXDIR}/{a}"
            if mon and a not in snapped and not os.path.exists(f):
                X, Y, W, H = workarea(mon); b = bar(w)
                if all(abs(p - q) <= 2 for p, q in zip((*w["at"], *w["size"]), (X, Y + b, W, H - b))):
                    try:
                        os.makedirs(MAXDIR, exist_ok=True)
                        with open(f, "w") as fh:
                            fh.write(f"{X + (W - 1092) // 2} {Y + b + (H - b - 564) // 2} 1092 564 {W} {H - b}\n")
                    except OSError: pass
            continue
        # not moving: if a drag just ended at an edge, snap
        if pending and pending[0] == a and pending[1] and now - prev[1] >= SETTLE:
            mons = j("monitors") or []
            mon = next((m for m in mons if m["focused"]), mons[0] if mons else None)
            if mon: snap(a, w, pending[1], mon, snapped, last)
            pending = None
        elif pending and now - prev[1] >= SETTLE:
            pending = None
        elif not pending and now - prev[1] >= SETTLE and a not in snapped:
            mons = j("monitors") or []
            mon = next((m for m in mons if m["focused"]), mons[0] if mons else None)
            if mon and clamp(w, mon):
                time.sleep(0.05); nw = j("activewindow")
                if nw and nw.get("address") == a: last[a] = (tuple(nw["at"]), time.time())

if __name__ == "__main__":
    while True:
        try: main()
        except Exception: time.sleep(1)
