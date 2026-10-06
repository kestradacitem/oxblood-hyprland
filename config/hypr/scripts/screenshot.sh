#!/bin/sh
# GNOME-like: save to ~/Pictures/Screenshots and copy to clipboard. $1 = area|full
f="$HOME/Pictures/Screenshots/Screenshot From $(date '+%Y-%m-%d %H-%M-%S').png"
if [ "$1" = area ]; then g=$(slurp) || exit 0; grim -g "$g" "$f"; else grim "$f"; fi
wl-copy < "$f" && notify-send -i "$f" "Screenshot captured" "Saved to Pictures/Screenshots"
