import os
import sys
import time
import json
import logging
import tempfile
import threading
import subprocess
import urllib.request
import asyncio
from typing import Optional, Callable, Dict, Any
import tkinter as tk
import customtkinter as ctk

logger = logging.getLogger("EmbeddedPlayer")

def find_chromium_browser() -> Optional[str]:
    """Finds an installed Edge, Chrome, or Chromium executable on Windows."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

class PersistentCDP:
    """
    Maintains a robust, auto-reconnecting WebSocket connection to Chromium DevTools Protocol.
    Handles instantaneous play/pause/seek execution, active ad-skipping, and clean video view.
    """

    def __init__(self, port: int = 9222):
        self.port = port
        self.ws = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._msg_id = 0
        self.connected = False
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        t = threading.Thread(target=self._run_loop, daemon=True)
        t.start()

    def stop(self):
        self._running = False
        self.connected = False
        if self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._connect_and_serve())
        except Exception as e:
            logger.debug(f"[CDP] Loop terminated: {e}")

    async def _connect_and_serve(self):
        import websockets

        while self._running:
            if not self.connected or not self.ws:
                try:
                    req = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=1)
                    tabs = json.loads(req.read().decode())
                    pages = [t for t in tabs if t.get("type") == "page"]
                    if pages:
                        ws_url = pages[0].get("webSocketDebuggerUrl")
                        if ws_url:
                            self.ws = await websockets.connect(ws_url, close_timeout=2)
                            self.connected = True
                            logger.info("[CDP] Connected to persistent WebSocket debugger.")
                            # Immediately inject full shield (ad skipper + clean CSS)
                            try:
                                await self._eval_async(self._get_shield_script())
                            except Exception:
                                pass
                except Exception:
                    self.connected = False
                    self.ws = None
            await asyncio.sleep(0.4)

    def eval(self, expr: str, timeout: float = 2.0) -> Any:
        if not self.connected or not self.loop or not self.loop.is_running():
            return None
        try:
            future = asyncio.run_coroutine_threadsafe(self._eval_async(expr), self.loop)
            return future.result(timeout=timeout)
        except Exception as e:
            logger.debug(f"[CDP] eval error: {e}")
            return None

    async def _eval_async(self, expr: str) -> Any:
        if not self.ws:
            return None
        self._msg_id += 1
        mid = self._msg_id
        payload = {
            "id": mid,
            "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True}
        }
        try:
            await self.ws.send(json.dumps(payload))
            while True:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2.5)
                data = json.loads(raw)
                if data.get("id") == mid:
                    return data.get("result", {}).get("result", {}).get("value")
        except Exception as e:
            self.connected = False
            self.ws = None
            raise e

    def _get_shield_script(self) -> str:
        """
        Comprehensive in-page script:
        1. Injects aggressive CSS to hide YouTube desktop header, search bar, sidebars, ads.
        2. Starts a persistent 100ms interval that auto-skips YouTube video ads & mutes ad audio.
        3. Autoplays video if paused.
        """
        return """
        (() => {
            // 1. Inject Clean View and Ad Blocker CSS
            if (!document.getElementById('la-forja-full-shield')) {
                const style = document.createElement('style');
                style.id = 'la-forja-full-shield';
                style.innerHTML = `
                    #masthead-container, #masthead, ytd-masthead, #header, #secondary, #comments, #below, #chat,
                    tp-yt-app-drawer, ytd-miniplayer, .ytp-endscreen-content,
                    .video-ads, .ytp-ad-module, .ytp-ad-overlay-container, #player-ads,
                    ytd-ad-slot-renderer, ytd-in-feed-ad-layout-renderer, ytd-banner-promo-renderer,
                    ytd-ad-inline-playback-meta-block, tp-yt-paper-dialog, ytd-mealbar-promo-renderer,
                    #masthead-ad, ytd-rich-item-renderer:has(.ytd-ad-slot-renderer) {
                        display: none !important;
                        visibility: hidden !important;
                        width: 0 !important;
                        height: 0 !important;
                    }
                    html, body {
                        overflow: hidden !important;
                        background: #000000 !important;
                        margin: 0 !important;
                        padding: 0 !important;
                        width: 100% !important;
                        height: 100% !important;
                    }
                    #player-container-outer, #player-container-inner, #player-container, ytd-player, #movie_player, .html5-video-player, video {
                        position: fixed !important;
                        top: 0 !important;
                        left: 0 !important;
                        width: 100vw !important;
                        height: 100vh !important;
                        max-width: 100vw !important;
                        max-height: 100vh !important;
                        z-index: 999999 !important;
                        margin: 0 !important;
                        padding: 0 !important;
                        background: #000000 !important;
                    }
                    .ytp-chrome-top, .ytp-chrome-bottom {
                        opacity: 0.85 !important;
                    }
                `;
                document.head.appendChild(style);
            }

            // 2. High-speed In-Page Ad Skipper (Runs every 100ms)
            if (!window.__la_forja_ad_skipper_active) {
                window.__la_forja_ad_skipper_active = true;
                setInterval(() => {
                    // Click skip button immediately
                    const skipSelectors = [
                        '.ytp-skip-ad-button',
                        '.ytp-ad-skip-button',
                        '.ytp-ad-skip-button-modern',
                        '.ytp-ad-skip-button-slot',
                        'button.ytp-ad-skip-button-modern',
                        '.ytp-ad-overlay-close-button',
                        '.ytp-ad-feedback-dialog-close-button'
                    ];
                    for (const sel of skipSelectors) {
                        const btn = document.querySelector(sel);
                        if (btn) {
                            try { btn.click(); } catch(e) {}
                        }
                    }

                    // Fast-forward and mute video if ad is showing
                    const player = document.getElementById("movie_player") || document.querySelector(".html5-video-player");
                    const isAd = player && (player.classList.contains("ad-showing") || player.classList.contains("ad-interrupting"));
                    const v = document.querySelector("video");

                    if (isAd && v) {
                        v.muted = true;
                        v.playbackRate = 16.0;
                        if (v.duration && !isNaN(v.duration)) {
                            v.currentTime = v.duration;
                        }
                    }
                }, 100);
            }

            // 3. Auto click play button if video is ready and paused
            const playBtn = document.querySelector(".ytp-large-play-button") || document.querySelector(".ytp-play-button");
            const v = document.querySelector("video");
            if (v && v.paused) {
                if (playBtn) playBtn.click();
                else v.play().catch(() => {});
            }
            return "SHIELD_ACTIVE";
        })()
        """

    def inject_clean_view(self):
        """Hides YouTube chrome/sidebars/ads and expands video to 100% of container."""
        return self.eval(self._get_shield_script())

    def skip_ads(self):
        """Explicitly executes ad skip logic from Python on monitor ticks."""
        script = """
        (() => {
            const skipBtns = document.querySelectorAll(
                '.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, ' +
                '.ytp-ad-skip-button-slot, button.ytp-ad-skip-button-modern, .ytp-ad-overlay-close-button'
            );
            for (const btn of skipBtns) {
                try { btn.click(); } catch(e) {}
            }
            const player = document.getElementById("movie_player") || document.querySelector(".html5-video-player");
            const isAd = player && (player.classList.contains("ad-showing") || player.classList.contains("ad-interrupting"));
            const v = document.querySelector("video");
            if (isAd && v) {
                v.muted = true;
                v.playbackRate = 16.0;
                if (v.duration && !isNaN(v.duration)) {
                    v.currentTime = v.duration;
                }
                return "AD_SKIPPED";
            }
            return "NO_AD";
        })()
        """
        return self.eval(script)

    def load_video_by_id(self, video_id: str, target_url: str) -> Optional[str]:
        """
        Transitions to a new video inside the running YouTube player instance
        without a full page navigation if possible (eliminates cold pre-roll ads).
        """
        script = f"""
        (() => {{
            const mp = document.getElementById("movie_player");
            if (mp && typeof mp.loadVideoById === "function") {{
                mp.loadVideoById("{video_id}");
                mp.playVideo();
                return "PLAYER_LOADED";
            }} else {{
                window.location.href = "{target_url}";
                return "NAVIGATED";
            }}
        }})()
        """
        return self.eval(script)

    def toggle_play(self) -> Optional[bool]:
        """Toggles play/pause reliably by clicking YouTube's player button."""
        script = """
        (() => {
            const playBtn = document.querySelector(".ytp-play-button");
            if (playBtn) {
                playBtn.click();
            } else {
                const v = document.querySelector("video");
                if (v) { if (v.paused) v.play(); else v.pause(); }
            }
            const v = document.querySelector("video");
            return v ? !v.paused : false;
        })()
        """
        return self.eval(script)

    def play(self):
        script = """
        (() => {
            const v = document.querySelector("video");
            if (v && v.paused) {
                const playBtn = document.querySelector(".ytp-play-button");
                if (playBtn) playBtn.click();
                else v.play().catch(() => {});
            }
        })()
        """
        return self.eval(script)

    def pause(self):
        script = """
        (() => {
            const v = document.querySelector("video");
            if (v && !v.paused) {
                const playBtn = document.querySelector(".ytp-play-button");
                if (playBtn) playBtn.click();
                else v.pause();
            }
        })()
        """
        return self.eval(script)

    def set_volume(self, percent: int):
        pct = max(0, min(100, percent)) / 100.0
        script = f"""
        (() => {{
            const v = document.querySelector("video");
            if (v) {{
                v.muted = false;
                v.volume = {pct};
            }}
        }})()
        """
        return self.eval(script)

    def get_status(self) -> Optional[Dict[str, Any]]:
        script = """
        (() => {
            const player = document.getElementById("movie_player") || document.querySelector(".html5-video-player");
            const isAd = player && (player.classList.contains("ad-showing") || player.classList.contains("ad-interrupting") || Boolean(document.querySelector(".ad-showing, .ad-interrupting")));
            const v = document.querySelector("video");
            if (!v) return null;

            let playerState = -1;
            let currentVidId = null;
            if (player && typeof player.getPlayerState === "function") {
                try { playerState = player.getPlayerState(); } catch(e) {}
            }
            if (player && typeof player.getVideoData === "function") {
                try { currentVidId = player.getVideoData()?.video_id; } catch(e) {}
            }

            return {
                currentTime: v.currentTime,
                duration: v.duration,
                paused: v.paused,
                ended: v.ended,
                isAd: Boolean(isAd),
                playerState: playerState,
                videoId: currentVidId
            };
        })()
        """
        return self.eval(script)

class EmbeddedPlayer(ctk.CTkFrame):
    """
    Dedicated in-app YouTube Player Controller & Native Docked View.
    - Docks the real Chromium window directly inside the Tkinter frame (Part of the app itself).
    - Strips window caption and offsets top bar by 34px to completely hide the app header.
    - Zero separate window/tab or taskbar entry.
    - Plays any YouTube video directly on YouTube's watch platform without Error 150/101 embed blocks.
    - In-page high-frequency ad-skipper actively neutralizes and skips ads.
    - Automatically advances through song requests smoothly without race conditions.
    """

    TITLE_BAR_OFFSET = 34  # Pixels to push Chromium title bar above container to hide it

    def __init__(
        self,
        master,
        on_video_ended: Optional[Callable[[], None]] = None,
        overlay_port: int = 5000,
        height: int = 260,
        cdp_port: int = 9222,
        **kwargs
    ):
        super().__init__(master, height=height, fg_color="#181a24", corner_radius=12, **kwargs)
        self.pack_propagate(False)

        self.on_video_ended = on_video_ended
        self.overlay_port = overlay_port
        self.cdp_port = cdp_port
        self.current_video_id: Optional[str] = None
        self._is_playing = False
        self._volume = 100
        self._browser_proc: Optional[subprocess.Popen] = None
        self._user_data_dir = os.path.join(tempfile.gettempdir(), "la_forja_music_player")
        self._docked_hwnd: Optional[int] = None
        self.music_service: Optional[Any] = None
        self.cdp = PersistentCDP(port=self.cdp_port)
        self._monitor_active = False

        # Advancement state tracking (prevents double-skip race condition)
        self._is_advancing: bool = False
        self._last_ended_video_id: Optional[str] = None

        self._build_ui()

    def set_music_service(self, service: Any):
        self.music_service = service

    def _build_ui(self):
        # 1. Header Row
        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.pack(fill="x", padx=14, pady=(8, 2))

        title_lbl = ctk.CTkLabel(
            header_row,
            text="🔴 YOUTUBE IN-APP PLAYER",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#FE2C55"
        )
        title_lbl.pack(side="left")

        self.status_badge = ctk.CTkLabel(
            header_row,
            text="● Idle",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#9CA3AF"
        )
        self.status_badge.pack(side="right")

        # 2. In-App Docked Video Screen (Black container where player lives)
        self.embed_container = tk.Frame(self, bg="#000000", width=388, height=195)
        self.embed_container.pack(fill="x", padx=10, pady=(2, 4))
        self.embed_container.pack_propagate(False)
        self.embed_container.bind("<Configure>", self._on_container_configure)

        # 3. Track Status Label
        self.track_lbl = ctk.CTkLabel(
            self,
            text="Waiting for song requests (!sr)...",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#FFFFFF",
            anchor="w"
        )
        self.track_lbl.pack(fill="x", padx=14, pady=(2, 6))

    def _on_container_configure(self, event):
        """Keep the docked window sized to match the container frame with title bar offset."""
        if self._docked_hwnd and os.name == "nt":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                if user32.IsWindow(self._docked_hwnd):
                    w = max(event.width, 388)
                    h = max(event.height, 195)
                    # Push window up by TITLE_BAR_OFFSET so the Chromium caption is completely hidden
                    user32.MoveWindow(self._docked_hwnd, 0, -self.TITLE_BAR_OFFSET, w, h + self.TITLE_BAR_OFFSET, True)
            except Exception:
                pass

    def _is_browser_running(self) -> bool:
        """Returns True if the docked player process is active."""
        if self._browser_proc is None:
            return False
        return self._browser_proc.poll() is None

    def start_player(self, video_id: Optional[str] = None):
        """Launches the player process off-screen and docks the real browser window into the frame."""
        if self._is_browser_running():
            return

        browser_path = find_chromium_browser()
        if not browser_path:
            logger.warning("No Chromium-based browser (Edge/Chrome) found for in-app player.")
            self.track_lbl.configure(text="⚠ Edge/Chrome executable not found.")
            return

        os.makedirs(self._user_data_dir, exist_ok=True)
        vid = video_id or self.current_video_id
        if vid:
            target_url = f"https://www.youtube.com/watch?v={vid}"
        else:
            target_url = f"http://127.0.0.1:{self.overlay_port}/player"

        cmd = [
            browser_path,
            f"--user-data-dir={self._user_data_dir}",
            f"--remote-debugging-port={self.cdp_port}",
            f"--app={target_url}",
            "--window-size=388,195",
            "--window-position=-10000,-10000",
            "--disable-gpu",
            "--autoplay-policy=no-user-gesture-required",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate"
        ]

        try:
            self._browser_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info(f"Launched in-app player process (PID: {self._browser_proc.pid}) on port {self.cdp_port}")
            self.status_badge.configure(text="● Active", text_color="#1DB954")
            self._dock_window_async(self._browser_proc.pid)
            self.cdp.start()
            self._start_monitor_loop()
        except Exception as e:
            logger.error(f"Failed to launch in-app player: {e}")

    def _dock_window_async(self, pid: Optional[int] = None):
        """Background worker to find the REAL top-level Chromium window and dock it."""
        if os.name != "nt":
            return

        def worker():
            try:
                import ctypes
                user32 = ctypes.windll.user32

                def get_class(h):
                    buff = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(h, buff, 256)
                    return buff.value

                for _ in range(80):
                    time.sleep(0.1)
                    found_hwnd = None

                    def enum_cb(h_curr, lparam):
                        nonlocal found_hwnd
                        w_pid = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(h_curr, ctypes.byref(w_pid))
                        if pid and w_pid.value == pid:
                            cname = get_class(h_curr)
                            rect = (ctypes.c_long * 4)()
                            user32.GetWindowRect(h_curr, rect)
                            w_win = rect[2] - rect[0]
                            h_win = rect[3] - rect[1]
                            # Only target the REAL top-level rendered window (not 0x0 helper windows)
                            if cname == "Chrome_WidgetWin_1" and w_win > 100 and h_win > 100:
                                found_hwnd = h_curr
                                return False
                        return True

                    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                    user32.EnumWindows(WNDPROC(enum_cb), 0)

                    if found_hwnd:
                        try:
                            parent_hwnd = self.embed_container.winfo_id()
                            user32.SetParent(found_hwnd, parent_hwnd)

                            # Strip taskbar icon and set as true child with no caption/borders
                            GWL_STYLE = -16
                            GWL_EXSTYLE = -20
                            WS_CHILD = 0x40000000
                            WS_VISIBLE = 0x10000000
                            WS_CLIPCHILDREN = 0x02000000
                            WS_POPUP = 0x80000000
                            WS_CAPTION = 0x00C00000
                            WS_THICKFRAME = 0x00040000
                            WS_SYSMENU = 0x00080000
                            WS_MINIMIZEBOX = 0x00020000
                            WS_MAXIMIZEBOX = 0x00010000
                            WS_EX_TOOLWINDOW = 0x00000080
                            WS_EX_APPWINDOW = 0x00040000

                            old_style = user32.GetWindowLongW(found_hwnd, GWL_STYLE)
                            new_style = (old_style & ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_POPUP)) | WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN
                            user32.SetWindowLongW(found_hwnd, GWL_STYLE, new_style)

                            ex = user32.GetWindowLongW(found_hwnd, GWL_EXSTYLE)
                            ex = (ex & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW
                            user32.SetWindowLongW(found_hwnd, GWL_EXSTYLE, ex)

                            w = self.embed_container.winfo_width()
                            h = self.embed_container.winfo_height()
                            if w <= 10:
                                w = 388
                            if h <= 10:
                                h = 195

                            SWP_NOACTIVATE = 0x0010
                            SWP_FRAMECHANGED = 0x0020
                            SWP_SHOWWINDOW = 0x0040
                            # Position at y = -TITLE_BAR_OFFSET to completely hide the top caption bar
                            user32.SetWindowPos(
                                found_hwnd,
                                0,
                                0,
                                -self.TITLE_BAR_OFFSET,
                                w,
                                h + self.TITLE_BAR_OFFSET,
                                SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
                            )
                            user32.ShowWindow(found_hwnd, 5)  # SW_SHOW

                            self._docked_hwnd = found_hwnd
                            logger.info(f"Successfully docked real player window ({found_hwnd}) into frame ({parent_hwnd}) [w={w}, h={h}]")
                            break
                        except Exception as ex:
                            logger.debug(f"Error during dock: {ex}")
                            break
            except Exception as e:
                logger.debug(f"Dock worker encountered error: {e}")

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _start_monitor_loop(self):
        if self._monitor_active:
            return
        self._monitor_active = True

        def monitor_worker():
            while self._monitor_active and self._is_browser_running():
                try:
                    if self.cdp.connected:
                        # Periodically refresh clean view and trigger active ad-skip
                        self.cdp.inject_clean_view()
                        self.cdp.skip_ads()

                        status = self.cdp.get_status()
                        if status and isinstance(status, dict):
                            is_ad = status.get("isAd", False)
                            cur_sec = status.get("currentTime", 0)
                            dur_sec = status.get("duration", 0)
                            paused = status.get("paused", False)
                            ended = status.get("ended", False)
                            player_state = status.get("playerState", -1)
                            active_vid_id = status.get("videoId")

                            # If an ad is currently playing, ad-skipper is handling it.
                            # NEVER update track progress or trigger track advancement while in an ad!
                            if is_ad:
                                time.sleep(0.5)
                                continue

                            # Clear advancing debounce once the new song has successfully begun playing
                            if self._is_advancing and cur_sec > 2.0 and cur_sec < (dur_sec - 3):
                                self._is_advancing = False

                            # Keep internal playback state synchronized
                            self._is_playing = not paused
                            if not paused:
                                self.status_badge.configure(text="▶ Playing", text_color="#FE2C55")
                            else:
                                if self.current_video_id:
                                    self.status_badge.configure(text="⏸ Paused", text_color="#EAB308")
                                else:
                                    self.status_badge.configure(text="● Idle", text_color="#9CA3AF")

                            # Sync progress to YouTubeService for MiniApp progress bar
                            if self.music_service and hasattr(self.music_service, "update_progress"):
                                if dur_sec > 0:
                                    self.music_service.update_progress(
                                        progress_ms=int(cur_sec * 1000),
                                        duration_ms=int(dur_sec * 1000)
                                    )

                            # Detect true song ending:
                            # 1. NOT an ad
                            # 2. Must match the current track ID if reported by YouTube player
                            # 3. Must have played for at least 8 seconds and have a real track duration (> 15s)
                            # 4. Either YouTube player state == 0 (ENDED) or ended flag or reached duration
                            vid_matches = (not active_vid_id) or (not self.current_video_id) or (active_vid_id == self.current_video_id)
                            is_finished = (player_state == 0) or ended or (dur_sec > 15 and cur_sec >= dur_sec - 1.0)

                            if vid_matches and not is_ad and dur_sec > 15 and cur_sec > 8 and is_finished:
                                if not self._is_advancing and self.current_video_id != self._last_ended_video_id:
                                    self._is_advancing = True
                                    self._last_ended_video_id = self.current_video_id
                                    logger.info(f"[EmbeddedPlayer] Track {self.current_video_id} completed naturally, triggering queue advance.")
                                    if self.on_video_ended:
                                        self.on_video_ended()
                except Exception as e:
                    logger.debug(f"[EmbeddedPlayer] Monitor tick error: {e}")
                time.sleep(0.8)
            self._monitor_active = False

        t = threading.Thread(target=monitor_worker, daemon=True)
        t.start()

    def close_player(self):
        """Closes the docked player process if running (called on application shutdown)."""
        self._monitor_active = False
        self.cdp.stop()
        if self._is_browser_running() and self._browser_proc:
            try:
                self._browser_proc.terminate()
                self._browser_proc.wait(timeout=1.5)
            except Exception:
                try:
                    self._browser_proc.kill()
                except Exception:
                    pass
            self._browser_proc = None
            logger.info("Terminated in-app player process.")

        self._docked_hwnd = None
        if not self.current_video_id:
            self.status_badge.configure(text="● Idle", text_color="#9CA3AF")

    def load_video(self, video_id: str, title: Optional[str] = None, artist: Optional[str] = None):
        """Loads and autoplays a YouTube video directly in the in-app player."""
        self.current_video_id = video_id
        self._is_playing = True
        self._is_advancing = False  # Reset debounce for new track

        display_title = title or f"Playing Video ({video_id})"
        self.track_lbl.configure(text=display_title[:38])

        target_url = f"https://www.youtube.com/watch?v={video_id}"

        if not self._is_browser_running():
            self.start_player(video_id=video_id)
        else:
            threading.Thread(target=self._navigate_and_setup, args=(video_id, target_url), daemon=True).start()

        self.status_badge.configure(text="▶ Playing", text_color="#FE2C55")

    def _navigate_and_setup(self, video_id: str, target_url: str):
        try:
            res = self.cdp.load_video_by_id(video_id, target_url)
            logger.info(f"[EmbeddedPlayer] Video transition result: {res}")
            time.sleep(0.4)
            self.cdp.inject_clean_view()
            self.cdp.skip_ads()
        except Exception as e:
            logger.debug(f"[EmbeddedPlayer] navigate_and_setup error: {e}")

    def play(self):
        """Resumes playback."""
        self._is_playing = True
        self.status_badge.configure(text="▶ Playing", text_color="#FE2C55")
        threading.Thread(target=self.cdp.play, daemon=True).start()

    def pause(self):
        """Pauses playback."""
        self._is_playing = False
        self.status_badge.configure(text="⏸ Paused", text_color="#EAB308")
        threading.Thread(target=self.cdp.pause, daemon=True).start()

    def toggle_playback(self):
        """Toggles between play and pause."""
        threading.Thread(target=self._do_toggle_playback, daemon=True).start()

    def _do_toggle_playback(self):
        is_now_playing = self.cdp.toggle_play()
        if is_now_playing is not None:
            self._is_playing = is_now_playing
            if is_now_playing:
                self.status_badge.configure(text="▶ Playing", text_color="#FE2C55")
            else:
                self.status_badge.configure(text="⏸ Paused", text_color="#EAB308")
        else:
            if self._is_playing:
                self.pause()
            else:
                self.play()

    def set_volume(self, volume_percent: int):
        """Sets player volume (0 - 100)."""
        self._volume = max(0, min(100, volume_percent))
        threading.Thread(target=self.cdp.set_volume, args=(self._volume,), daemon=True).start()

    def toggle_player_window(self):
        """Toggles the in-app player visibility."""
        if self.winfo_ismapped():
            self.pack_forget()
        else:
            self.pack(fill="x", padx=16, pady=(4, 6))

    def stop(self):
        """
        Pauses player and switches state to Idle without closing the browser process.
        Keeps the browser session warm and docked, avoiding cold-start pre-roll ads on next request.
        """
        self.current_video_id = None
        self._is_playing = False
        self._is_advancing = False
        self._last_ended_video_id = None
        self.track_lbl.configure(text="Waiting for song requests (!sr)...")
        self.status_badge.configure(text="● Idle", text_color="#9CA3AF")
        threading.Thread(target=self.cdp.pause, daemon=True).start()
