#!/usr/bin/env bash
# Oxblood — installer for the kb Hyprland + HyprPanel rice.
# Copies the configs into your home (backing up whatever is there), fills in your $HOME,
# and builds the two Hyprland plugins (hyprbars + kb-minimize) for your Hyprland version.
#
#   ./install.sh            install everything
#   ./install.sh --no-build install configs only (skip building plugins)
#   ./install.sh --greeter  also install the login screen (greetd + cage, needs sudo)
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
BUILD=1; GREETER=0
for a in "$@"; do
    case "$a" in
        --no-build) BUILD=0 ;;
        --greeter)  GREETER=1 ;;
    esac
done
BACKUP="$HOME/.oxblood-backup-$(date +%Y%m%d-%H%M%S)"

say()  { printf '\033[1;31m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

# --- 1. dependencies (warn only) ---
need=(Hyprland hyprctl hyprpaper hypridle hyprlock hyprpanel gjs python3 jq magick grim slurp brightnessctl nmcli notify-send pactl)
missing=()
for c in "${need[@]}"; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
python3 -c 'import gi; gi.require_version("Gtk","4.0")' 2>/dev/null || missing+=("python-gobject + gtk4")
[ -e /usr/lib/libgtk4-layer-shell.so ] || missing+=("gtk4-layer-shell")
fc-list | grep -qi "Adwaita Sans" || missing+=("font: Adwaita Sans")
if [ ${#missing[@]} -gt 0 ]; then
    warn "Missing: ${missing[*]}"
    warn "On Arch: see the README 'Dependencies' section. Continuing anyway in 5 s (Ctrl+C to stop)…"
    sleep 5
fi

# --- 2. back up and copy ---
say "Backing up your current files to $BACKUP"
mkdir -p "$BACKUP"
for p in .config/hypr .config/hyprpanel .config/gtk-3.0/gtk.css .config/gtk-4.0/gtk.css .config/systemd/user/kb-autounmute.service .config/systemd/user/kb-avatar-sync.path .config/systemd/user/kb-avatar-sync.service; do
    if [ -e "$HOME/$p" ]; then mkdir -p "$BACKUP/$(dirname "$p")"; cp -a "$HOME/$p" "$BACKUP/$p"; fi
done
for f in "$REPO"/local/bin/*; do
    if [ -e "$HOME/.local/bin/$(basename "$f")" ]; then mkdir -p "$BACKUP/.local/bin"; cp -a "$HOME/.local/bin/$(basename "$f")" "$BACKUP/.local/bin/"; fi
done

say "Installing configs"
install_tree() {  # install_tree <src dir> <dest dir>: copy, replacing @HOME@ with your home
    local src="$1" dst="$2"
    (cd "$src" && find . -type f) | while read -r rel; do
        mkdir -p "$dst/$(dirname "$rel")"
        sed "s#@HOME@#$HOME#g" "$src/$rel" > "$dst/$rel"
        if [ -x "$src/$rel" ]; then chmod +x "$dst/$rel"; fi
    done
}
install_tree "$REPO/config"    "$HOME/.config"
install_tree "$REPO/local/bin" "$HOME/.local/bin"
install_tree "$REPO/local/lib" "$HOME/.local/lib"
chmod +x "$HOME"/.local/bin/{hyprpanel,hl-dsp,kb-*} "$HOME"/.config/hypr/scripts/* 2>/dev/null || true
mkdir -p "$HOME/.local/share/backgrounds"
cp "$REPO/wallpapers/kb-oled-arch.png" "$HOME/.local/share/backgrounds/"

# audio: unmute the speaker/mic whenever its volume is changed (default.target, because Hyprland never
# starts graphical-session.target)
if command -v systemctl >/dev/null; then
    systemctl --user daemon-reload && systemctl --user enable --now kb-autounmute.service >/dev/null 2>&1 \
        || warn "Could not enable kb-autounmute.service (run: systemctl --user enable --now kb-autounmute)"
    # avatar: re-sync the bar/dashboard picture when it is changed in GNOME Settings → Users (or ~/.face)
    systemctl --user enable --now kb-avatar-sync.path >/dev/null 2>&1 \
        || warn "Could not enable kb-avatar-sync.path (run: systemctl --user enable --now kb-avatar-sync.path)"
fi

case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) warn "Add ~/.local/bin to your PATH (it must come before /usr/bin so the patched 'hyprpanel' wins)";; esac

# --- 3. plugins ---
if [ $BUILD = 1 ]; then
    PLUG="$HOME/.local/lib/hyprland"; mkdir -p "$PLUG"
    TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

    say "Building kb-minimize (needs the Hyprland headers: hyprland package + cmake + a C++23 compiler)"
    cmake -S "$REPO/plugins/kb-minimize" -B "$TMP/kbm" -DCMAKE_BUILD_TYPE=Release >/dev/null
    cmake --build "$TMP/kbm" -j"$(nproc)" >/dev/null
    cp "$TMP/kbm/libkbminimize.so" "$PLUG/"

    say "Building hyprbars (title bars) from hyprwm/hyprland-plugins"
    git clone -q https://github.com/hyprwm/hyprland-plugins "$TMP/hp"
    ver="v$(hyprctl version -j 2>/dev/null | jq -r .tag | sed 's/^v//; s/-.*//')"
    git -C "$TMP/hp" checkout -q "$ver" 2>/dev/null || git -C "$TMP/hp" checkout -q "${ver%.*}.0" 2>/dev/null \
        || warn "No hyprland-plugins tag for $ver, building main"
    make -C "$TMP/hp/hyprbars" all >/dev/null
    cp "$TMP/hp/hyprbars/hyprbars.so" "$PLUG/libhyprbars.so"
else
    warn "Skipped plugin build: title bars and the GNOME-style maximize/snap won't load until you build them."
fi

# --- 4. login screen (optional) ---
if [ $GREETER = 1 ]; then
    say "Installing the login screen (greetd + cage). sudo will ask for your password."
    command -v greetd >/dev/null && command -v cage >/dev/null || sudo pacman -S --needed greetd cage
    sudo install -Dm644 "$REPO/system/kb-greeter/greeter.py" /usr/local/share/kb-greeter/greeter.py
    [ -f /etc/greetd/config.toml ] && sudo cp /etc/greetd/config.toml "/etc/greetd/config.toml.bak-$(date +%Y%m%d)"
    sed "s#@USER@#$USER#" "$REPO/system/greetd/config.toml" | sudo tee /etc/greetd/config.toml >/dev/null
    say "Test it first: KB_GREETER_TEST=1 python3 $REPO/system/kb-greeter/greeter.py  (type ok and press Enter to close it)"
    say "Then switch login managers: sudo systemctl disable gdm sddm lightdm 2>/dev/null; sudo systemctl enable greetd"
fi

say "Done. Log out and pick the Hyprland session (or run: hyprctl reload)."
say "Your old files are in $BACKUP"
