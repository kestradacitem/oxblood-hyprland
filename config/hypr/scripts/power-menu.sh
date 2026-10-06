#!/bin/sh
# GNOME-style "interactive" power button menu
c=$(printf 'Lock\nSuspend\nLog Out\nRestart\nPower Off\n' | fuzzel --dmenu --prompt 'Power: ' --lines 5) || exit 0
case "$c" in
  Lock) loginctl lock-session ;;
  Suspend) systemctl suspend ;;
  "Log Out") @HOME@/.local/bin/hl-dsp 'hl.dsp.exit()' exit ;;
  Restart) systemctl reboot ;;
  "Power Off") systemctl poweroff ;;
esac
