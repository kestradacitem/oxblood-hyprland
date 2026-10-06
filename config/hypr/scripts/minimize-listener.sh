#!/bin/sh
# Window event helper:
#  (minimize buttons are handled by the kb-minimize Hyprland plugin: Hyprland emits no event for them)
#  - a window that opens maximized/fullscreen is restored to normal floating size (apps never start maximized);
#    maximizing later (buttons, double-click, Super+Up, drag to top) still works.
last_open=0
socat -U - "UNIX-CONNECT:$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock" | while IFS= read -r line; do
  case "$line" in
    openwindow\>\>*) last_open=$(date +%s)
      a=${line#openwindow>>}; a=${a%%,*}
      ( sleep 0.4
        fs=$(hyprctl clients -j | jq -r ".[] | select(.address==\"0x${a#0x}\") | .fullscreen")
        [ -n "$fs" ] && [ "$fs" != 0 ] && [ "$fs" != false ] && \
          @HOME@/.local/bin/hl-dsp "hl.dsp.window.fullscreen_state({internal=0,client=0,window=\"address:0x${a#0x}\"})" fullscreenstate "0 0,address:0x${a#0x}"
      ) & ;;
    fullscreen\>\>1) [ $(( $(date +%s) - last_open )) -le 2 ] && @HOME@/.local/bin/hl-dsp 'hl.dsp.window.fullscreen_state({internal=0,client=0})' fullscreenstate 0 0 ;;
  esac
done
