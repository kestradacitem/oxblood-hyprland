"""Turn any app icon into a 2-tone icon: white where the icon is bright, transparent (OLED black) elsewhere.
The threshold is Otsu's over the icon's opaque pixels only, so a light glyph on a coloured plate
(e.g. a white star on an orange square) becomes the white part instead of the whole plate. Free-form icons
become a white silhouette with their dark details cut out."""
import hashlib, os, subprocess, sys
import numpy as np
from PIL import Image

CACHE = os.path.expanduser("~/.cache/kb-dock-icons")   # shared by the dock and the app grid
os.makedirs(CACHE, exist_ok=True)
NERD_FONT = "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFont-SemiBold.ttf"
# desktop id -> Nerd Font codepoint, or (outer, inner) for a glyph drawn inside another
GLYPHS = {
    "kb-grid": 0xF003B,                 # apps grid
    "kb-app": 0xF08C6,                  # generic app (icon missing / unreadable)
    "org.gnome.Nautilus": 0xF024B,      # folder
    "thorium-browser": 0xF268,          # chromium
    "vscodium-wayland": 0xF0A1E, "vscodium": 0xF0A1E, "codium": 0xF0A1E,
    "org.gnome.Calculator": 0xF00EC,
    "org.gnome.Ptyxis": 0xF018D,        # console
    "viber": (0xF0365, 0xF03F2),        # speech bubble + phone
    "org.remmina.Remmina": 0xF08B9,     # remote desktop
    "Spotify": 0xF1BC, "spotify": 0xF1BC, "com.spotify.Client": 0xF1BC,
}

def _glyph(cp, pt):
    return ["-font", NERD_FONT, "-pointsize", str(pt), "label:" + chr(cp)]

def render_glyph(g, out):
    """White glyph on transparent, trimmed and centred in a 128 px square."""
    if isinstance(g, tuple):
        outer, inner = g
        cmd = ["magick", "-background", "none", "-fill", "white", *_glyph(outer, 120), "-trim", "+repage",
               "-resize", "104x104", "-gravity", "center", "-extent", "128x128",
               "(", "-background", "none", "-fill", "white", *_glyph(inner, 60), "-trim", "+repage", "-resize", "50x50", ")",
               "-gravity", "center", "-geometry", "+0-6", "-composite", out]
    else:
        cmd = ["magick", "-background", "none", "-fill", "white", *_glyph(g, 120), "-trim", "+repage",
               "-resize", "100x100", "-gravity", "center", "-extent", "128x128", out]
    subprocess.run(cmd, capture_output=True)

def glyph_icon(key):
    """Path to the cached glyph PNG for a GLYPHS key (rendered on first use; tiny)."""
    out = f"{CACHE}/mono-{key}.png"
    if not os.path.exists(out): render_glyph(GLYPHS[key], out)
    return out

def app_key(app_id):
    """'org.gnome.Nautilus.desktop' -> 'org.gnome.Nautilus'"""
    return app_id[:-8] if app_id and app_id.endswith(".desktop") else app_id

def cached(app_id, icon):
    """Path of the finished mono icon for an app, or None if it still has to be rendered."""
    k = app_key(app_id)
    if k in GLYPHS: return glyph_icon(k)
    p = f"{CACHE}/{hashlib.md5(('mono:' + (icon or 'application-x-executable')).encode()).hexdigest()[:12]}.png"
    return p if os.path.exists(p) else None

def render(app_id, icon, src):
    """Render (blocking) the mono icon for an app from its icon file `src`; returns the path or None."""
    k = app_key(app_id)
    if k in GLYPHS: return glyph_icon(k)
    out = f"{CACHE}/{hashlib.md5(('mono:' + (icon or 'application-x-executable')).encode()).hexdigest()[:12]}.png"
    if os.path.exists(out): return out
    if not src or not os.path.exists(src): return glyph_icon("kb-app")
    tmp = out + f".{os.getpid()}.src.png"
    if src.endswith(".svg"):
        subprocess.run(["rsvg-convert", "-w", "128", "-h", "128", "-a", src, "-o", tmp], capture_output=True)
    else:
        subprocess.run(["magick", src + "[0]", "-resize", "128x128", tmp], capture_output=True)   # [0]: first frame of .ico
    try: mono(tmp, out + ".part.png"); os.replace(out + ".part.png", out)
    except Exception: pass
    try: os.remove(tmp)
    except OSError: pass
    return out if os.path.exists(out) else glyph_icon("kb-app")

def icon_file(theme, icon):
    """Resolve an icon name (or absolute path) to a file via a Gtk.IconTheme."""
    if not icon: icon = "application-x-executable"
    if icon.startswith("/"): return icon
    try:
        from gi.repository import Gtk
        pt = theme.lookup_icon(icon, None, 256, 1, Gtk.TextDirection.NONE, 0)
        f = pt.get_file() if pt else None
        return f.get_path() if f else None
    except Exception:
        return None

def mono(src, out):
    im = Image.open(src).convert("RGBA").resize((128, 128), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32)
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    opaque = a[..., 3] > 127
    vals = lum[opaque]
    if vals.size == 0:
        return
    hist, _ = np.histogram(vals, bins=256, range=(0, 256))
    total, sum_all = vals.size, np.dot(np.arange(256), hist)
    w0 = s0 = 0.0; best_t, best = 128, -1.0
    for t in range(256):
        w0 += hist[t]; s0 += t * hist[t]
        if w0 == 0 or w0 == total: continue
        m0, m1 = s0 / w0, (sum_all - s0) / (total - w0)
        var = w0 * (total - w0) * (m0 - m1) ** 2
        if var > best: best, best_t = var, t
    ys, xs = np.nonzero(opaque)
    plate = opaque.sum() > 0.75 * (np.ptp(ys) + 1) * (np.ptp(xs) + 1)   # icon is a filled tile/circle
    if vals.max() - vals.min() < 40:
        white = opaque                        # flat single-colour icon: its silhouette
    elif plate:
        white = opaque & (lum > best_t)       # glyph on a coloured plate: just the bright glyph
    else:
        white = opaque & (lum > 75)           # free-form icon: silhouette with its dark details cut out
    o = np.zeros((128, 128, 4), np.uint8)
    o[..., :3] = 255
    o[..., 3] = np.where(white, 255, 0)
    Image.fromarray(o, "RGBA").save(out)

if __name__ == "__main__":
    mono(sys.argv[1], sys.argv[2])
