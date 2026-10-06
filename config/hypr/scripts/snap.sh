#!/bin/sh
# Half-screen snapping for floating windows. $1 = left|right|max|restore
w=$(hyprctl activewindow -j); [ "$(echo "$w" | jq -r '.address // empty')" ] || exit 0
case "$1" in
  max) exec @HOME@/.local/bin/kb-maximize ;;
  restore) [ -f "${XDG_RUNTIME_DIR:-/tmp}/kb-maximize/$(echo "$w" | jq -r .address)" ] && exec @HOME@/.local/bin/kb-maximize; exit 0 ;;
esac
[ "$(echo "$w" | jq -r '.fullscreen')" != 0 ] && @HOME@/.local/bin/hl-dsp 'hl.dsp.window.fullscreen({mode="maximized"})' fullscreen 1
eval "$(hyprctl monitors -j | jq -r '.[] | select(.focused) |
  "X=\(.x); Y=\(.y); W=\((.width/.scale)|floor); H=\((.height/.scale)|floor); RL=\(.reserved[0]); RT=\(.reserved[1]); RR=\(.reserved[2]); RB=\(.reserved[3])"')"
G=0
# hyprbars bar (26 px) sits above the window: leave room for it, or it hides behind the panel (see titlebars.lua)
B=$(echo "$w" | jq -r 'if ((.tags // []) | index("kbcsd")) or (.class | test("^(org\\.gnome\\..*|(?i:.*codium.*)|(?i:onlyoffice.*)|(?i:firefox)|(?i:discord))$")) or (.class == "org.remmina.Remmina" and .title == "Remmina Remote Desktop Client") then 0 else 26 end')
AW=$((W - RL - RR - 2*G)); AH=$((H - RT - RB - 2*G - B)); HW=$(((AW - G) / 2))
TOP=$((Y + RT + G + B)); LEFT=$((X + RL + G))
case "$1" in
  left)  PX=$LEFT ;;
  right) PX=$((LEFT + HW + G)) ;;
  *) exit 0 ;;
esac
@HOME@/.local/bin/hl-dsp "hl.dsp.window.resize({x=$HW,y=$AH})" resizeactive exact $HW $AH
@HOME@/.local/bin/hl-dsp "hl.dsp.window.move({x=$PX,y=$TOP})" moveactive exact $PX $TOP
