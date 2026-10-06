-- kb Hyprland config (Lua; converted from hyprland.conf 2026-10-02 because Hyprland 0.57 drops .conf).
-- Shares $HOME with GNOME; touches no GNOME settings. hyprland.conf is kept only as a fallback:
-- Hyprland reads this file whenever it exists. Check after edits: hyprctl configerrors

hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1.5 })

hl.env("XCURSOR_THEME", "Adwaita")
hl.env("XCURSOR_SIZE", "24")
hl.env("QT_QPA_PLATFORM", "wayland;xcb")
hl.env("ELECTRON_OZONE_PLATFORM_HINT", "auto")

local home     = "@HOME@"
local terminal = "ptyxis"
local browser  = "thorium-browser"
local files    = "nautilus"
local scripts  = home .. "/.config/hypr/scripts"

-- --- session services ---
hl.on("hyprland.start", function()
    hl.exec_cmd("dbus-update-activation-environment --systemd --all")
    hl.exec_cmd("gnome-keyring-daemon --start --components=secrets")
    hl.exec_cmd("systemctl --user start hyprpolkitagent")
    hl.exec_cmd("systemd-inhibit --what=handle-power-key --who=hyprland --why='power menu' sleep infinity")
    hl.exec_cmd("hyprpaper")
    hl.exec_cmd("hypridle")
    hl.exec_cmd(home .. "/.local/bin/kb-avatar-sync")
    hl.exec_cmd(home .. "/.local/bin/hyprpanel")
    hl.exec_cmd(home .. "/.local/bin/kb-notif-log")
    hl.exec_cmd(home .. "/.local/bin/kb-plugin-check")
    hl.exec_cmd(scripts .. "/minimize-listener.sh")
    hl.exec_cmd(scripts .. "/edge-snap.py")
    -- fallback dock: nwg-dock-hyprland -d -p bottom -i 48 -lp start -c "@HOME@/.local/bin/kb-popup appgrid" -ico @HOME@/.config/nwg-dock-hyprland/app-grid.svg -mb 8 -hd 0
    hl.exec_cmd("env LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so python3 " .. home .. "/.local/lib/kbshell/dock.py")
end)

hl.config({
    general = {
        gaps_in     = 0,
        gaps_out    = 0,
        border_size = 0,
        col = {
            active_border   = "rgb(c41e2a)",
            inactive_border = "rgb(180c0d)",
        },
        layout = "dwindle",
        -- resize any window by dragging its edges (no visible border needed)
        resize_on_border        = true,
        extend_border_grab_area = 12,
        hover_icon_on_border    = true,
        snap = {
            enabled        = true,
            window_gap     = 0,
            monitor_gap    = 0,
            border_overlap = false,
        },
    },

    decoration = {
        rounding = 0,
        blur     = { enabled = false },
        shadow   = { enabled = false },
    },

    -- matches GNOME: animations off
    animations = { enabled = false },

    input = {
        kb_layout          = "us",
        repeat_rate        = 33,
        repeat_delay       = 500,
        follow_mouse       = 2, -- click to focus + raise (GNOME-style); hover only scrolls
        numlock_by_default = true,
        touchpad = {
            natural_scroll = true,
            tap_to_click   = true,
        },
    },

    -- a click on a title bar / Super+click never moves the window; dragging starts after 8 px (GNOME).
    -- Dragging a fullscreen window un-fullscreens it (Hyprland); a maximized/snapped one is restored by kb-minimize.
    binds = { drag_threshold = 8 },

    misc = {
        disable_hyprland_logo   = true,
        focus_on_activate       = true,
        key_press_enables_dpms  = true, -- a key/mouse wakes the screen at once (lock screen typing went into a dark screen)
        mouse_move_enables_dpms = true, -- tray icon / notification / "open" from another app brings that window up (GNOME)
        force_default_wallpaper = 0,
    },

    xwayland = { force_zero_scaling = true },

    ecosystem = {
        no_update_news  = true,
        no_donation_nag = true,
    },
})

-- GNOME: whichever window gets focus comes to the front. Hyprland's focus (dock click, overview thumbnail,
-- tray activation) does NOT change the stacking order, so a maximized window kept covering it (2026-10-05).
-- Only when focus moves to ANOTHER window: "window.active" also fires on every title change of the active
-- window (e.g. a terminal's animated title), and raising on each of those made the terminal flicker (2026-10-05).
local last_active = nil
hl.on("window.active", function()
    local w = hl.get_active_window()
    local a = w and w.address or nil
    if a == nil or a == last_active then return end
    last_active = a
    hl.dispatch(hl.dsp.window.bring_to_top())
end)

hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
-- GNOME touchpad gestures (2026-10-05): 3 fingers up = overview/app grid, down = close it (kb-popup toggles, so check first)
local grid_pid = "$XDG_RUNTIME_DIR/kbpop-appgrid.pid"
hl.gesture({ fingers = 3, direction = "up", action = function()
    hl.exec_cmd("sh -c '[ -f " .. grid_pid .. " ] && kill -0 $(cat " .. grid_pid .. ") 2>/dev/null || exec " .. home .. "/.local/bin/kb-popup appgrid'")
end })
hl.gesture({ fingers = 3, direction = "down", action = function()
    hl.exec_cmd("sh -c '[ -f " .. grid_pid .. " ] && kill -0 $(cat " .. grid_pid .. ") 2>/dev/null && exec " .. home .. "/.local/bin/kb-popup appgrid'")
end })

-- floating desktop (no tiling): every window floats and opens centred, like GNOME
-- apps asking to be maximized are ignored: Hyprland's maximized state draws above all floating windows
-- (Remmina stayed on top of everything, 2026-10-03). Maximize = kb-maximize (fills the screen, stacks normally).
hl.window_rule({ name = "float-all", match = { class = ".*" }, float = true, center = true, suppress_event = "maximize" })
-- uniform default size for every app window (= the Ptyxis terminal size the user picked, 2026-10-02).
-- Dialogs (modal), the polkit password prompt, picture-in-picture and Waydroid keep their own size
-- (Waydroid sizes the whole Android screen from its first window, so forcing 1092x564 cropped portrait games).
hl.window_rule({
    name  = "uniform-size",
    match = { class = "negative:(?i)(.*polkit.*|waydroid.*)", title = "negative:^(Picture.in.picture)$", modal = false },
    size  = "1092 564",
})

require("titlebars")

-- --- keybinds: mirrors your GNOME shortcuts (SUPER = Windows key) ---
local mod  = "SUPER"
local exec = hl.dsp.exec_cmd
local function bind(keys, dsp, opts) hl.bind(keys, dsp, opts) end

-- GNOME: tap Super = overview/apps, Super+A = app grid
bind(mod .. " + SUPER_L", exec(home .. "/.local/bin/kb-popup appgrid"), { release = true })
bind(mod .. " + A", exec(home .. "/.local/bin/kb-popup appgrid"))
-- your custom GNOME shortcuts
bind("CTRL + ALT + T", exec("ptyxis -x fish"))
bind(mod .. " + SHIFT + S", exec(scripts .. "/screenshot.sh area"))
-- GNOME defaults
bind("Print", exec(scripts .. "/screenshot.sh area"))
bind("SHIFT + Print", exec(scripts .. "/screenshot.sh full"))
bind("ALT + F4", exec(home .. "/.local/bin/kb-close"))
bind("CTRL + W", exec(scripts .. "/ctrl-w.sh"))
bind("ALT + Tab", function()
    hl.dispatch(hl.dsp.window.cycle_next())
    hl.dispatch(hl.dsp.window.bring_to_top())
end)
bind("ALT + SHIFT + Tab", hl.dsp.window.cycle_next({ next = false }))
bind(mod .. " + L", exec("loginctl lock-session"))
bind(mod .. " + H", hl.dsp.window.move({ workspace = "special:minimized", follow = false }))
bind(mod .. " + SHIFT + H", hl.dsp.workspace.toggle_special("minimized"))
bind(mod .. " + V", exec("hyprpanel toggleWindow notificationsmenu"))
bind(mod .. " + E", exec(files))
bind("CTRL + ALT + Delete", exec(scripts .. "/power-menu.sh"))
bind("XF86PowerOff", exec(scripts .. "/power-menu.sh"))
bind(mod .. " + Page_Up", hl.dsp.focus({ workspace = "e-1" }))
bind(mod .. " + Page_Down", hl.dsp.focus({ workspace = "e+1" }))
-- Hyprland extras (no GNOME equivalent you use)
bind(mod .. " + Return", exec(terminal))
bind(mod .. " + B", exec(browser))
bind(mod .. " + Q", exec(home .. "/.local/bin/kb-close"))
bind(mod .. " + F", exec(home .. "/.local/bin/kb-maximize"))
bind(mod .. " + SHIFT + F", hl.dsp.window.fullscreen({ mode = "fullscreen" }))
bind(mod .. " + T", hl.dsp.window.float())
bind(mod .. " + SHIFT + M", hl.dsp.exit())
bind(mod .. " + left", exec(scripts .. "/snap.sh left"))
bind(mod .. " + right", exec(scripts .. "/snap.sh right"))
bind(mod .. " + up", exec(scripts .. "/snap.sh max"))
bind(mod .. " + down", exec(scripts .. "/snap.sh restore"))
for _, dir in ipairs({ "left", "right", "up", "down" }) do
    bind(mod .. " + SHIFT + " .. dir, hl.dsp.window.move({ direction = dir }))
end
for i = 1, 4 do
    bind(mod .. " + " .. i, hl.dsp.focus({ workspace = i }))
    bind(mod .. " + SHIFT + " .. i, hl.dsp.window.move({ workspace = i }))
end
bind(mod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- media / hardware keys (same as GNOME)
local held   = { locked = true, repeating = true }
local locked = { locked = true }
bind("XF86AudioRaiseVolume", exec("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), held)
bind("XF86AudioLowerVolume", exec("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"), held)
bind("XF86AudioMute", exec("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"), locked)
bind("XF86AudioMicMute", exec("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), locked)
bind("XF86MonBrightnessUp", exec("brightnessctl s 5%+"), held)
bind("XF86MonBrightnessDown", exec("brightnessctl s 5%-"), held)
bind("XF86AudioPlay", exec("playerctl play-pause"), locked)
bind("XF86AudioNext", exec("playerctl next"), locked)
bind("XF86AudioPrev", exec("playerctl previous"), locked)
