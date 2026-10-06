// kb-minimize: make client "minimize" requests (GTK/Qt/X11 minimize buttons) work in Hyprland.
// A minimize request parks the window in special:minimized; focusing it again (dock click,
// focuswindow, Alt+Tab) brings it back to the current workspace, like GNOME.
// Also: tags native-Wayland windows whose app draws its own title bar (asked for client-side
// decorations, or negotiated none) as "kbcsd", so hyprbars skips them (titlebars.conf). Every other
// window gets the uniform hyprbars bar -> exactly one set of min/max/close buttons per window.
// Also: clears the xdg "maximized" state Hyprland sends to tiled windows (to suppress CSD) once a window
// is floating and not maximized (and sets it while maximized) - otherwise every floating app thinks it is maximized, shows a "restore"
// button and its own maximize button does nothing (VSCodium, GTK apps).
// Also: apps' own maximize requests (CSD maximize button / title double-click: OnlyOffice, GTK) are swallowed by
// the float-all rule's suppress_event=maximize, so they did nothing (2026-10-05). They now run kb-maximize instead.
// Also: dragging a maximized or edge-snapped window by its title bar restores its previous size under the pointer,
// like GNOME (2026-10-05). Hyprland would otherwise drag the screen-sized window around.
#include <format>
#include <chrono>
#include <unordered_map>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>
#include <algorithm>
#include <hyprland/src/Compositor.hpp>
#define private public
#include <hyprland/src/protocols/XDGShell.hpp>
#undef private
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/xwayland/XSurface.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#define private public
#include <hyprland/src/protocols/XDGDecoration.hpp>
#include <hyprland/src/protocols/ServerDecorationKDE.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/pass/SurfacePassElement.hpp>
#include <hyprland/src/desktop/view/Popup.hpp>
#undef private
#include <hyprland/src/desktop/state/ViewHitTester.hpp>
#define private public
#include <hyprland/src/layout/supplementary/DragController.hpp>
#undef private
#include <fstream>

inline HANDLE PHANDLE = nullptr;

struct SWatch {
    PHLWINDOWREF        window;
    CHyprSignalListener listener;
};
static std::vector<SWatch> g_watches;

static std::string addr(const PHLWINDOW& w) { return std::format("0x{:x}", (uintptr_t)w.get()); }

// hyprland.lua sessions take Lua dispatchers, hyprland.conf sessions the old syntax
static void dispatch(const std::string& lua, const std::string& legacy) {
    HyprlandAPI::invokeHyprctlCommand("dispatch", Config::mgr()->type() == Config::CONFIG_LUA ? lua : legacy);
}

static void minimize(PHLWINDOWREF ref) {
    g_pEventLoopManager->doLater([ref] {
        auto w = ref.lock();
        if (!w || w->onSpecialWorkspace()) return;
        dispatch(std::format("hl.dsp.window.move({{workspace=\"special:minimized\",follow=false,window=\"address:{}\"}})", addr(w)),
                 "movetoworkspacesilent special:minimized,address:" + addr(w));
    });
}

// 1 = app draws its own decorations (CSD), 0 = wants the compositor's, -1 = unknown yet
static int clientDecorates(const PHLWINDOW& w) {
    if (w->m_isX11) return 0;
    auto xdg = w->m_xdgSurface.lock();
    if (!xdg) return -1;
    auto tl = xdg->m_toplevel.lock();
    if (!tl || !tl->m_resource) return -1;
    if (PROTO::xdgDecoration) {
        auto it = PROTO::xdgDecoration->m_decorations.find(tl->m_resource->resource());
        if (it != PROTO::xdgDecoration->m_decorations.end() && it->second)
            return it->second->mostRecentlyRequested == 1 ? 1 : 0;
    }
    if (PROTO::serverDecorationKDE) {
        auto surf = w->resource();
        for (auto& d : PROTO::serverDecorationKDE->m_decos)
            if (d && d->m_surf == surf) return d->m_mostRecentlyRequested == 1 ? 1 : 0;
    }
    return 1; // no decoration protocol at all: the client decorates itself
}

static void classify(PHLWINDOWREF ref) {
    auto w = ref.lock();
    if (!w || !w->m_isMapped) return;
    const int csd = clientDecorates(w);
    if (csd < 0) return;
    const bool tagged = w->m_ruleApplicator && w->m_ruleApplicator->m_tagKeeper.isTagged("kbcsd");
    if ((csd == 1) != tagged)
        dispatch(std::format("hl.dsp.window.tag({{tag=\"{}kbcsd\",window=\"address:{}\"}})", csd ? "+" : "-", addr(w)),
                 std::format("tagwindow {}kbcsd address:{}", csd ? "+" : "-", addr(w)));
}

// xdg "tiled" states: CSD apps (GTK, Chromium) then drop their invisible shadow/resize margin, so the
// window has no border/padding around its content (Hyprland handles edge resizing itself)
static void setTiled(const SP<CXDGToplevelResource>& tl) {
    if (!tl->m_resource || wl_resource_get_version(tl->m_resource->resource()) < 2) return;
    auto& st = tl->m_pendingApply.states;
    bool changed = false;
    for (auto s : {XDG_TOPLEVEL_STATE_TILED_LEFT, XDG_TOPLEVEL_STATE_TILED_RIGHT, XDG_TOPLEVEL_STATE_TILED_TOP, XDG_TOPLEVEL_STATE_TILED_BOTTOM})
        if (std::ranges::find(st, s) == st.end()) { st.push_back(s); changed = true; }
    // GTK >= 4.16 keeps a 12 px invisible resize strip on every edge that is not "constrained" (xdg v7)
    if (wl_resource_get_version(tl->m_resource->resource()) >= 7)
        for (auto s : {XDG_TOPLEVEL_STATE_CONSTRAINED_LEFT, XDG_TOPLEVEL_STATE_CONSTRAINED_RIGHT, XDG_TOPLEVEL_STATE_CONSTRAINED_TOP, XDG_TOPLEVEL_STATE_CONSTRAINED_BOTTOM})
            if (std::ranges::find(st, s) == st.end()) { st.push_back(s); changed = true; }
    // advertise minimize (Hyprland only lists maximize/fullscreen), else GTK4 greys out its minimize button
    if (wl_resource_get_version(tl->m_resource->resource()) >= 5) {
        wl_array caps;
        wl_array_init(&caps);
        for (uint32_t c : {XDG_TOPLEVEL_WM_CAPABILITIES_MAXIMIZE, XDG_TOPLEVEL_WM_CAPABILITIES_FULLSCREEN, XDG_TOPLEVEL_WM_CAPABILITIES_MINIMIZE})
            *static_cast<uint32_t*>(wl_array_add(&caps, sizeof(uint32_t))) = c;
        tl->m_resource->sendWmCapabilities(&caps);
        wl_array_release(&caps);
        changed = true; // capabilities only apply with the next configure
    }
    if (changed) tl->scheduleStateApplication();
}

// floating windows: the xdg "maximized" state must match Hyprland's maximized mode
static void unstickMaximized(PHLWINDOWREF ref) {
    g_pEventLoopManager->doLater([ref] {
        auto w = ref.lock();
        if (!w || !w->m_isMapped || w->m_isX11 || !w->m_isFloating) return;
        const auto fs = Fullscreen::controller()->getFullscreenModes(w);
        if (fs.internal == Fullscreen::FSMODE_FULLSCREEN) return;
        auto xdg = w->m_xdgSurface.lock();
        if (!xdg) return;
        auto tl = xdg->m_toplevel.lock();
        if (!tl) return;
        tl->setMaximized(fs.internal == Fullscreen::FSMODE_MAXIMIZED);
        setTiled(tl);
    });
}

// Hyprland 0.56 ignores the xdg window-geometry offset when drawing AND when hit-testing the pointer (its own
// renderer has it as a FIXME; it relies on MAXIMIZED, which we clear above for floating windows). GTK 4.22 always
// keeps a 12 px invisible resize border on non-maximized CSD windows (gtkwindow.c get_shadow_width: MAX(shadow, 12)),
// no matter the tiled/constrained states or CSS. Result: a 12 px gap top/left and the right edge (close button)
// cut off - and it came back whenever the stale MAXIMIZED flag happened to be cleared. Fix it in the compositor:
// draw the main surface from its geometry offset, move its subsurfaces by the same amount, and shift pointer
// hit-testing to match. Popups are positioned relative to the window geometry already, so they are left alone.
static Vector2D csdOffset(const PHLWINDOW& w) {
    if (!w || w->m_isX11 || !w->wlSurface()) return {};
    auto xdg = w->m_xdgSurface.lock();
    if (!xdg) return {};
    const CBox g = xdg->m_current.geometry;
    auto       s = w->wlSurface()->resource();
    if ((g.x <= 0 && g.y <= 0) || !s || s->m_current.viewport.hasSource) return {};
    return {std::max(g.x, 0.0), std::max(g.y, 0.0)};
}

typedef void (*origUV)(void*, PHLWINDOW, SP<CWLSurfaceResource>, PHLMONITOR, bool, const Vector2D&, const Vector2D&, bool);
inline CFunctionHook* g_uvHook = nullptr;

static void hkCalculateUV(void* self, PHLWINDOW w, SP<CWLSurfaceResource> s, PHLMONITOR m, bool main, const Vector2D& proj, const Vector2D& projU, bool fix) {
    ((origUV)g_uvHook->m_original)(self, w, s, m, main, proj, projU, fix);
    if (!main || !s || !w || !w->wlSurface() || w->wlSurface()->resource() != s) return;
    const Vector2D o = csdOffset(w);
    if (o.x == 0 && o.y == 0) return;
    // GTK sets a viewport destination (fractional scale) equal to the logical size
    const Vector2D sz = s->m_current.viewport.hasDestination ? s->m_current.viewport.destination : s->m_current.size;
    if (sz.x <= o.x || sz.y <= o.y) return;
    auto&    rd = g_pHyprRenderer->m_renderData;
    Vector2D tl = rd.primarySurfaceUVTopLeft, br = rd.primarySurfaceUVBottomRight;
    if (tl == Vector2D{-1, -1}) { tl = {0, 0}; br = {1, 1}; }
    const Vector2D off = {o.x / sz.x, o.y / sz.y};
    rd.primarySurfaceUVTopLeft     = tl + off;
    rd.primarySurfaceUVBottomRight = Vector2D{std::min(br.x + off.x, 1.0), std::min(br.y + off.y, 1.0)};
}

// subsurfaces (GTK graphics offload, video) sit relative to the buffer origin: move them with the content
typedef void (*origSurfCtor)(void*, const CSurfacePassElement::SRenderData&);
inline CFunctionHook* g_surfHook = nullptr;

static void hkSurfCtor(void* self, const CSurfacePassElement::SRenderData& data) {
    if (data.pWindow && !data.popup && data.surface && data.pWindow->wlSurface() && data.pWindow->wlSurface()->resource() != data.surface) {
        const Vector2D o = csdOffset(data.pWindow);
        if (o.x != 0 || o.y != 0) {
            auto d     = data;
            d.localPos = d.localPos - o;
            ((origSurfCtor)g_surfHook->m_original)(self, d);
            return;
        }
    }
    ((origSurfCtor)g_surfHook->m_original)(self, data);
}

// damage: clients report damage in buffer coords, and Hyprland places it at the unshifted position. Shift it like
// the drawing, else redrawn regions (terminal lines while typing/scrolling) are repainted 12 px off and leave
// half-drawn stale strips until something forces a full repaint (2026-10-05)
typedef void (*origDamageSurf)(void*, SP<CWLSurfaceResource>, double, double, double);
inline CFunctionHook* g_damageHook = nullptr;

static void hkDamageSurface(void* self, SP<CWLSurfaceResource> s, double x, double y, double scale) {
    if (s) {
        for (auto& w : Desktop::windowState()->windows()) {
            if (!w->m_isMapped || !w->wlSurface() || !w->wlSurface()->resource()) continue;
            const Vector2D o = csdOffset(w);
            if (o.x == 0 && o.y == 0) continue;
            bool owned = false;
            w->wlSurface()->resource()->breadthfirst([&](SP<CWLSurfaceResource> c, const Vector2D&, void*) { owned = owned || c == s; }, nullptr);
            if (owned) {
                ((origDamageSurf)g_damageHook->m_original)(self, s, x - o.x, y - o.y, scale);
                return;
            }
        }
    }
    ((origDamageSurf)g_damageHook->m_original)(self, s, x, y, scale);
}

// pointer: hit-test the window's surface tree as if it were drawn at the shifted position (popups unchanged)
typedef SP<CWLSurfaceResource> (*origSurfAt)(const void*, const Vector2D&, PHLWINDOW, Vector2D&);
typedef Vector2D (*origLocalAt)(const void*, const Vector2D&, PHLWINDOW, SP<CWLSurfaceResource>);
inline CFunctionHook* g_surfAtHook  = nullptr;
inline CFunctionHook* g_localAtHook = nullptr;

static Vector2D inputShift(const PHLWINDOW& w, const Vector2D& pos) {
    const Vector2D o = csdOffset(w);
    if (o.x == 0 && o.y == 0) return {};
    if (w->m_popupHead && w->m_popupHead->at(pos, true)) return {};
    return o;
}

static SP<CWLSurfaceResource> hkSurfAt(const void* self, const Vector2D& pos, PHLWINDOW w, Vector2D& local) {
    return ((origSurfAt)g_surfAtHook->m_original)(self, pos + inputShift(w, pos), w, local);
}

static Vector2D hkLocalAt(const void* self, const Vector2D& pos, PHLWINDOW w, SP<CWLSurfaceResource> s) {
    return ((origLocalAt)g_localAtHook->m_original)(self, pos + inputShift(w, pos), w, s);
}

// Waydroid (multi-window mode) gives every Android app a toplevel the size of the whole Android screen: a transparent
// main surface with the app's layers as subsurfaces. Without this, the invisible part swallows clicks meant for the
// windows behind it (you had to Alt+Tab first). A point only hits a Waydroid window if it lies over one of its
// subsurfaces; otherwise the window below gets it. Windows without subsurfaces (full-UI mode) are unchanged.
typedef PHLWINDOW (*origWinAt)(const void*, const Vector2D&, uint16_t, PHLWINDOW);
inline CFunctionHook* g_winAtHook = nullptr;

static bool isWaydroid(const PHLWINDOW& w) {
    if (!w || w->m_isX11) return false;
    std::string c = w->m_class;
    std::ranges::transform(c, c.begin(), ::tolower);
    return c.starts_with("waydroid");
}

static bool overContent(const void* self, const Vector2D& pos, const PHLWINDOW& w) {
    auto main = w->wlSurface() ? w->wlSurface()->resource() : nullptr;
    if (!main || main->m_subsurfaces.empty() || !g_localAtHook) return true;
    const Vector2D local = ((origLocalAt)g_localAtHook->m_original)(self, pos, w, main);
    bool any = false, hit = false;
    main->breadthfirst([&](SP<CWLSurfaceResource> s, const Vector2D& off, void*) {
        if (s == main) return;
        const Vector2D sz = s->m_current.viewport.hasDestination ? s->m_current.viewport.destination : s->m_current.size;
        if (sz.x <= 0 || sz.y <= 0) return;
        any = true;
        if (CBox{off, sz}.containsPoint(local)) hit = true;
    }, nullptr);
    return !any || hit;
}

static PHLWINDOW hkWinAt(const void* self, const Vector2D& pos, uint16_t props, PHLWINDOW ignore) {
    auto w = ((origWinAt)g_winAtHook->m_original)(self, pos, props, ignore);
    if (!w || ignore || !isWaydroid(w) || w->hasPopupAt(pos) || overContent(self, pos, w)) return w;
    // only one window can be ignored per call: a second transparent Waydroid window right below still wins (rare)
    return ((origWinAt)g_winAtHook->m_original)(self, pos, props, w);
}

// app asked to (un)maximize: toggle kb-maximize (requests in the first 1.5 s after mapping are an app
// restoring its saved maximized state - ignored, every window opens at the uniform size)
using Clock = std::chrono::steady_clock;
static std::unordered_map<uintptr_t, Clock::time_point> g_mapped, g_lastMax;
static void maximizeRequest(PHLWINDOWREF ref) {
    g_pEventLoopManager->doLater([ref] {
        auto w = ref.lock();
        if (!w || !w->m_isMapped || !w->m_isFloating) return;
        const auto now = Clock::now();
        const auto key = (uintptr_t)w.get();
        if (auto it = g_mapped.find(key); it != g_mapped.end() && now - it->second < std::chrono::milliseconds(1500)) return;
        if (auto it = g_lastMax.find(key); it != g_lastMax.end() && now - it->second < std::chrono::milliseconds(400)) return;
        g_lastMax[key] = now;
        const std::string a = addr(w);
        pid_t pid = fork();
        if (pid == 0) {
            setsid();
            if (fork() == 0) {
                execl("@HOME@/.local/bin/kb-maximize", "kb-maximize", a.c_str(), (char*)nullptr);
                _exit(127);
            }
            _exit(0);
        }
        if (pid > 0) waitpid(pid, nullptr, 0);
    });
}

// Dragging a maximized/snapped window un-maximizes it (GNOME). kb-maximize and edge-snap.py save the window's previous
// geometry in $XDG_RUNTIME_DIR/kb-maximize/<address> as "x y w h [sw sh]" (sw sh = the maximized/snapped size).
// Hyprland moves a dragged window to beginDragPosition + pointer delta, so once the pointer has moved a few px we
// shrink the window back and shift that anchor: the same spot of the title bar (proportionally) stays under the pointer.
typedef void (*origMouseMove)(Layout::Supplementary::CDragStateController*, const Vector2D&);
inline CFunctionHook* g_dragHook = nullptr;

static std::string maxFile(const PHLWINDOW& w) {
    const char* rt = getenv("XDG_RUNTIME_DIR");
    return std::format("{}/kb-maximize/{}", rt ? rt : "/tmp", addr(w));
}

// $XDG_RUNTIME_DIR/kb-drag exists while a window is being moved with the mouse: edge-snap.py shows its snap
// preview while it exists and snaps when it disappears (button released), like GNOME (2026-10-05)
static bool        g_dragging = false;
inline CFunctionHook* g_dragEndHook = nullptr;
typedef void (*origDragEnd)(Layout::Supplementary::CDragStateController*);
static std::string dragFile() {
    const char* rt = getenv("XDG_RUNTIME_DIR");
    return std::format("{}/kb-drag", rt ? rt : "/tmp");
}
static void hkDragEnd(Layout::Supplementary::CDragStateController* self) {
    ((origDragEnd)g_dragEndHook->m_original)(self);
    if (g_dragging) { g_dragging = false; unlink(dragFile().c_str()); }
}

static void hkMouseMove(Layout::Supplementary::CDragStateController* self, const Vector2D& mouse) {
    static Layout::Supplementary::CDragStateController* lastSelf = nullptr;
    static Vector2D                                    lastBegin = {-1e9, -1e9}, lastPos;
    static bool                                        armed     = false;
    static Vector2D                                    restore;
    auto t = self->m_target.lock();
    auto w = t ? t->window() : nullptr;
    if (t && w && self->m_dragMode == MBIND_MOVE && !g_dragging) { // tell edge-snap.py a window is being dragged
        g_dragging = true;
        if (FILE* f = fopen(dragFile().c_str(), "w")) { fprintf(f, "%s\n", addr(w).c_str()); fclose(f); }
    }
    if (t && w && self->m_dragMode == MBIND_MOVE && w->m_isFloating && self->m_beginDragSizeXY != Vector2D()) {
        if (self != lastSelf || self->m_beginDragXY != lastBegin || self->m_beginDragPositionXY != lastPos) { // a new drag: maximized/snapped?
            lastSelf = self; lastBegin = self->m_beginDragXY; lastPos = self->m_beginDragPositionXY; armed = false;
            std::ifstream f(maxFile(w));
            double x, y, rw, rh, sw = -1, sh = -1;
            if (f >> x >> y >> rw >> rh) {
                f >> sw >> sh;
                const Vector2D cur = t->position().size();
                const bool snapped = sw > 0 ? std::abs(cur.x - sw) <= 3 && std::abs(cur.y - sh) <= 3
                                            : (w->m_monitor && cur.x >= w->m_monitor->m_size.x - 4); // old kb-maximize file: full width
                if (snapped && (std::abs(cur.x - rw) > 3 || std::abs(cur.y - rh) > 3)) { armed = true; restore = {rw, rh}; }
            }
        }
        if (armed && self->m_beginDragXY.distanceSq(mouse) >= 64) {
            armed = false;
            const Vector2D bpos = self->m_beginDragPositionXY, bsize = self->m_beginDragSizeXY, grab = self->m_beginDragXY - bpos;
            Vector2D sz = restore;
            if (auto mn = t->minSize()) sz = Vector2D{std::max(sz.x, mn->x), std::max(sz.y, mn->y)};
            const double fx  = std::clamp(grab.x / bsize.x, 0.0, 1.0);
            const double offY = std::min(grab.y, sz.y - 10); // pointer stays on the title bar (hyprbars: above the window)
            const Vector2D pos = Vector2D{mouse.x - fx * sz.x, mouse.y - offY}.round();
            t->setPositionGlobal({pos, sz});
            t->warpPositionSize();
            self->m_beginDragPositionXY = pos - (mouse - self->m_beginDragXY);
            self->m_beginDragSizeXY     = sz;
            lastPos                     = self->m_beginDragPositionXY;
            unlink(maxFile(w).c_str());
        }
    }
    ((origMouseMove)g_dragHook->m_original)(self, mouse);
}

static void watch(PHLWINDOW w) {
    classify(w);
    std::erase_if(g_watches, [](const SWatch& s) { return s.window.expired(); });
    PHLWINDOWREF ref = w;
    if (!w->m_isX11) {
        auto xdg = w->m_xdgSurface.lock();
        if (!xdg) return;
        auto tl = xdg->m_toplevel.lock();
        if (!tl) return;
        WP<CXDGToplevelResource> wtl = tl;
        g_watches.push_back({ref, tl->m_events.stateChanged.listen([ref, wtl] {
            auto t = wtl.lock();
            if (t && t->m_state.requestsMinimize.value_or(false)) minimize(ref);
            if (t && t->m_state.requestsMaximize.has_value()) maximizeRequest(ref);
        })});
    } else {
        auto xs = w->m_xwaylandSurface.lock();
        if (!xs) return;
        WP<CXWaylandSurface> wxs = xs;
        g_watches.push_back({ref, xs->m_events.stateChanged.listen([ref, wxs] {
            auto s = wxs.lock();
            if (s && s->m_state.requestsMinimize.value_or(false)) minimize(ref);
            if (s && s->m_state.requestsMaximize.has_value()) maximizeRequest(ref);
        })});
    }
}

APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    PHANDLE = handle;
    if (std::string{__hyprland_api_get_hash()} != std::string{__hyprland_api_get_client_hash()})
        throw std::runtime_error("[kb-minimize] version mismatch");

    static auto P1 = Event::bus()->m_events.window.open.listen([](PHLWINDOW w) {
        g_mapped[(uintptr_t)w.get()] = Clock::now();
        watch(w);
        // the decoration mode can be (re)negotiated right after mapping: check again shortly after
        PHLWINDOWREF ref = w;
        g_pEventLoopManager->doLater([ref] { classify(ref); });
        unstickMaximized(ref);
    });
    static auto P3 = Event::bus()->m_events.window.floating.listen([](PHLWINDOW w) { unstickMaximized(w); });
    // the fullscreen event fires before the new mode is stored: check one loop iteration later
    static auto P4 = Event::bus()->m_events.window.fullscreen.listen([](PHLWINDOW w) {
        PHLWINDOWREF ref = w;
        g_pEventLoopManager->doLater([ref] { unstickMaximized(ref); });
    });
    // un-minimize: when a parked window gets focus, bring it to the current workspace
    static auto P2 = Event::bus()->m_events.window.active.listen([](PHLWINDOW w, Desktop::eFocusReason) {
        if (!w || !w->m_workspace || w->m_workspace->m_name != "special:minimized") return;
        PHLWINDOWREF ref = w;
        g_pEventLoopManager->doLater([ref] {
            auto win = ref.lock();
            if (!win) return;
            dispatch("hl.dsp.workspace.toggle_special(\"minimized\")", "togglespecialworkspace minimized");
            dispatch(std::format("hl.dsp.window.move({{workspace=\"e+0\",window=\"address:{}\"}})", addr(win)), "movetoworkspace e+0,address:" + addr(win));
        });
    });
    auto hookFn = [](const std::string& name, const std::string& demangled, void* fn) -> CFunctionHook* {
        for (auto& f : HyprlandAPI::findFunctionsByName(PHANDLE, name))
            if (f.demangled.contains(demangled)) {
                auto h = HyprlandAPI::createFunctionHook(PHANDLE, f.address, fn);
                if (h && h->hook()) return h;
                return nullptr;
            }
        return nullptr;
    };
    g_uvHook      = hookFn("calculateUVForSurface", "IElementRenderer::calculateUVForSurface", (void*)&hkCalculateUV);
    g_surfHook    = hookFn("CSurfacePassElement", "CSurfacePassElement::CSurfacePassElement(CSurfacePassElement::SRenderData const&)", (void*)&hkSurfCtor);
    g_surfAtHook  = hookFn("windowSurfaceAt", "CViewHitTester::windowSurfaceAt", (void*)&hkSurfAt);
    g_localAtHook = hookFn("surfaceLocalAt", "CViewHitTester::surfaceLocalAt", (void*)&hkLocalAt);
    // all-or-nothing: drawing shifted without input shifted (or vice versa) would make clicks miss
    if (!g_uvHook || !g_surfHook || !g_surfAtHook || !g_localAtHook) {
        for (auto* h : {g_uvHook, g_surfHook, g_surfAtHook, g_localAtHook})
            if (h) h->unhook();
        g_uvHook = g_surfHook = g_surfAtHook = g_localAtHook = nullptr;
        HyprlandAPI::addNotification(PHANDLE, "[kb-minimize] CSD offset hooks not installed (12 px GTK gap fix off)", CHyprColor{1, 0.3, 0.3, 1}, 5000);
    }
    if (g_uvHook) g_damageHook = hookFn("damageSurface", "IHyprRenderer::damageSurface(Hyprutils::Memory::CSharedPointer<CWLSurfaceResource>", (void*)&hkDamageSurface);
    if (g_uvHook && !g_damageHook)
        HyprlandAPI::addNotification(PHANDLE, "[kb-minimize] CSD damage hook not installed (redraw glitches)", CHyprColor{1, 0.3, 0.3, 1}, 5000);
    if (g_localAtHook) g_winAtHook = hookFn("windowAt", "CViewHitTester::windowAt", (void*)&hkWinAt);
    if (!g_winAtHook)
        HyprlandAPI::addNotification(PHANDLE, "[kb-minimize] Waydroid click-through hook not installed", CHyprColor{1, 0.3, 0.3, 1}, 5000);
    g_dragHook = hookFn("mouseMove", "CDragStateController::mouseMove", (void*)&hkMouseMove);
    if (!g_dragHook)
        HyprlandAPI::addNotification(PHANDLE, "[kb-minimize] drag-to-unmaximize hook not installed", CHyprColor{1, 0.3, 0.3, 1}, 5000);
    unlink(dragFile().c_str());
    if (g_dragHook) g_dragEndHook = hookFn("dragEnd", "CDragStateController::dragEnd", (void*)&hkDragEnd);
    for (auto& w : Desktop::windowState()->windows())
        if (w->m_isMapped) { watch(w); unstickMaximized(w); }
    // startup report: which hooks are active (checked after reboots/updates; 2026-10-05)
    if (FILE* f = fopen("@HOME@/.cache/kb-minimize/init.log", "w")) {
        fprintf(f, "uv=%d surf=%d damage=%d surfAt=%d localAt=%d winAt=%d drag=%d dragstate=%d\n", !!g_uvHook, !!g_surfHook, !!g_damageHook, !!g_surfAtHook, !!g_localAtHook, !!g_winAtHook, !!g_dragHook, !!g_dragEndHook);
        fclose(f);
    }

    return {"kb-minimize", "Honor client minimize requests (park in special:minimized)", "kb", "1.0"};
}

APICALL EXPORT void PLUGIN_EXIT() { g_watches.clear(); }
