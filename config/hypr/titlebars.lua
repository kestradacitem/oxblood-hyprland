-- GNOME-style window controls (hyprbars), OLED black + maroon. Required from hyprland.lua.
hl.plugin.load("@HOME@/.local/lib/hyprland/libhyprbars.so")
hl.plugin.load("@HOME@/.local/lib/hyprland/libkbminimize.so")

-- Plugins load after the first pass over the config and then trigger a reload, so the hyprbars
-- options, buttons and rule effects only exist on that second pass.
if not hl.plugin.hyprbars then return end

local dsp = "@HOME@/.local/bin/hl-dsp "

hl.config({
    plugin = {
        hyprbars = {
            bar_height                 = 26,
            bar_color                  = "rgb(000000)",
            col                        = { text = "rgb(e8dede)" },
            bar_text_size              = 10,
            bar_text_font              = "Adwaita Sans",
            bar_text_weight            = "bold",
            bar_text_align             = "center",
            bar_buttons_alignment      = "right",
            bar_padding                = 10,
            bar_button_padding         = 8,
            bar_part_of_window         = true,
            bar_precedence_over_border = true,
            inactive_button_color      = "rgba(00000000)", -- 0 = off: buttons look the same when unfocused (universal rule, gtk-*/gtk.css)
            on_double_click            = "@HOME@/.local/bin/kb-maximize",
        },
    },
})

-- UNIVERSAL WINDOW-CONTROL RULE (also in ~/.config/gtk-3.0 + gtk-4.0/gtk.css): 16 px circles, 8 px apart,
-- 10 px from the right edge, min/max #241112, close #5f0d11. Change both places together.
-- buttons listed right -> left, GNOME order: minimize, maximize, close
hl.plugin.hyprbars.add_button({ bg_color = "rgb(5f0d11)", fg_color = "rgb(ffffff)", size = 16, icon = "󰖭",
    action = "@HOME@/.local/bin/kb-close" })
hl.plugin.hyprbars.add_button({ bg_color = "rgb(241112)", fg_color = "rgb(e8dede)", size = 16, icon = "󰖯",
    action = "@HOME@/.local/bin/kb-maximize" })
hl.plugin.hyprbars.add_button({ bg_color = "rgb(241112)", fg_color = "rgb(e8dede)", size = 16, icon = "󰖰",
    action = dsp .. "'hl.dsp.window.move({workspace=\"special:minimized\",follow=false})' movetoworkspacesilent special:minimized" })

-- apps that draw their own title bar + buttons get no second bar. The kb-minimize plugin tags them
-- "kbcsd" automatically (they asked Wayland for client-side decorations); the class list below
-- covers XWayland/self-drawn cases the plugin can't see.
hl.window_rule({ name = "nobar-csd-tag", match = { tag = "kbcsd", class = "negative:(?i)waydroid\\..*" }, ["hyprbars:no_bar"] = true })
-- Waydroid app windows ask for CSD but Android's own caption is turned off (persist.wm.debug.caption_on_shell,
-- it covered the game), so they are left out of the no-bar rule above and get the normal bar.
-- persist.waydroid.height = 1166 - 26 so the game fits under it.
-- fixed list: apps that already draw their own GNOME-style header bar and buttons: no second bar
hl.window_rule({
    name  = "nobar-csd-apps",
    match = { class = "^(org\\.gnome\\..*|(?i:.*codium.*)|(?i:onlyoffice.*)|(?i:firefox)|(?i:discord))$" },
    ["hyprbars:no_bar"] = true,
})
hl.window_rule({
    name  = "nobar-remmina-main",
    match = { class = "^(org\\.remmina\\.Remmina)$", title = "^(Remmina Remote Desktop Client)$" },
    ["hyprbars:no_bar"] = true,
})
