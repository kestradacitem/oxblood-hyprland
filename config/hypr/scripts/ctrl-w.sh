#!/bin/sh
# Smart Ctrl+W: tabbed apps close one tab per press (and the window after the last tab);
# apps without tabs close the window.
cls=$(hyprctl activewindow -j | jq -r '.class // empty' | tr 'A-Z' 'a-z')
[ -z "$cls" ] && exit 0
case "$cls" in
  # apps whose own Ctrl+W closes a tab, then the window when no tabs are left
  *thorium*|*chromium*|*chrome*|firefox*|*nautilus*|*vscodium*|codium*|*texteditor*|*onlyoffice*|*okular*|*thunderbird*|*zoom*)
    @HOME@/.local/bin/hl-dsp 'hl.dsp.send_shortcut({mods="CTRL",key="W"})' sendshortcut "CTRL, W, activewindow" ;;
  # Ptyxis closes tabs with Ctrl+Shift+W (last tab closes the window)
  *ptyxis*)
    @HOME@/.local/bin/hl-dsp 'hl.dsp.send_shortcut({mods="CTRL SHIFT",key="W"})' sendshortcut "CTRL SHIFT, W, activewindow" ;;
  # remote desktop: pass Ctrl+W to the remote machine, never kill the RDP session
  *remmina*)
    @HOME@/.local/bin/hl-dsp 'hl.dsp.send_shortcut({mods="CTRL",key="W"})' sendshortcut "CTRL, W, activewindow" ;;
  *)
    @HOME@/.local/bin/hl-dsp 'hl.dsp.window.close()' killactive ;;
esac
