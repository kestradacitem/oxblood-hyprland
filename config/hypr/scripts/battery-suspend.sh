#!/bin/sh
# GNOME: suspend after 20 min idle on battery, never on AC
[ "$(cat /sys/class/power_supply/ACAD/online 2>/dev/null)" = 0 ] && systemctl suspend
