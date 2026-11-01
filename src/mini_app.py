import os
import io
import time
import threading
import logging
from typing import Optional, Dict, Any
from urllib.request import urlopen, Request
from PIL import Image, ImageTk
import customtkinter as ctk

from src.base_music_service import BaseMusicService
from src.request_limiter import RequestLimiter
from src.embedded_player import EmbeddedPlayer

logger = logging.getLogger("MiniApp")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")

class MiniApp(ctk.CTk):
    """
    Compact desktop controller window for streamers on their secondary screen.
    Provides live playback info, skip/pause controls, volume, moderation, queue feed,
    and native in-app embedded video playback for YouTube.
    """

    def __init__(
        self,
        spotify_service: Any,
        request_limiter: RequestLimiter,
        twitch_channel: str = "N/A",
        tiktok_username: str = "N/A",
        config_manager: Optional[Any] = None,
        bot_manager: Optional[Any] = None
    ):
        super().__init__()

        self.music_service = spotify_service
        self.spotify = spotify_service  # Backward compatibility alias
        self.limiter = request_limiter
        self.config_manager = config_manager
        self.bot_manager = bot_manager
        self.service_type = getattr(self.music_service, "service_type", "spotify")

        self.embedded_player: Optional[EmbeddedPlayer] = None
        self._video_visible = True

        # Fallback to config if not provided or N/A
        enable_tw = self.config_manager.get("enable_twitch", True) if self.config_manager else True
        enable_tt = self.config_manager.get("enable_tiktok", True) if self.config_manager else True

        if not enable_tw or twitch_channel == "Disabled":
            self.twitch_channel = "Disabled"
        else:
            tw_name = twitch_channel if (twitch_channel and twitch_channel != "N/A") else ""
            if not tw_name and self.config_manager:
                tw_name = self.config_manager.get("twitch_channel") or self.config_manager.get("twitch_nick") or ""
            self.twitch_channel = tw_name or "N/A"

        if not enable_tt or tiktok_username == "Disabled":
            self.tiktok_username = "Disabled"
        else:
            tt_name = tiktok_username if (tiktok_username and tiktok_username != "N/A") else ""
            if not tt_name and self.config_manager:
                tt_name = self.config_manager.get("tiktok_username") or ""
            self.tiktok_username = tt_name or "N/A"

        # Window settings
        self.title("La Forja Music - Stream Controller")
        self.geometry("440x780")
        self.minsize(420, 720)
        self.configure(fg_color="#121318")

        self._always_on_top = False
        self._current_track_id: Optional[str] = None
        self._last_art_url: Optional[str] = None
        self._cached_art_image: Optional[ctk.CTkImage] = None
        self._is_updating = False

        self._build_ui()
        self._start_polling()

    def _build_ui(self):
        # 1. Header Frame
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 6))

        title_label = ctk.CTkLabel(
            header,
            text="🎧 LA FORJA",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#FFFFFF"
        )
        title_label.pack(side="left")

        self.platform_badge = ctk.CTkLabel(
            header,
            text="🔴 YouTube Active" if self.service_type == "youtube" else "🟢 Spotify Active",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#FE2C55" if self.service_type == "youtube" else "#1DB954",
            fg_color="#3b1219" if self.service_type == "youtube" else "#102d1d",
            corner_radius=6,
            padx=6,
            pady=2
        )
        self.platform_badge.pack(side="left", padx=(8, 0))

        self.pin_btn = ctk.CTkButton(
            header,
            text="📌 Pin",
            width=48,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#252836",
            hover_color="#32364a",
            command=self._toggle_always_on_top
        )
        self.pin_btn.pack(side="right")

        self.settings_btn = ctk.CTkButton(
            header,
            text="⚙ Settings",
            width=66,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#252836",
            hover_color="#32364a",
            command=self._open_settings
        )
        self.settings_btn.pack(side="right", padx=(0, 4))

        self.video_toggle_btn = ctk.CTkButton(
            header,
            text="👁 Hide",
            width=68,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#FE2C55" if self.service_type == "youtube" else "#252836",
            hover_color="#E11D48" if self.service_type == "youtube" else "#32364a",
            command=self._toggle_video_panel
        )
        if self.service_type == "youtube":
            self.video_toggle_btn.pack(side="right", padx=(0, 4))

        # 2. Connection Status Bar
        status_bar = ctk.CTkFrame(self, fg_color="#1a1c24", corner_radius=10)
        status_bar.pack(fill="x", padx=16, pady=6)

        self.twitch_status = ctk.CTkLabel(
            status_bar,
            text="",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.twitch_status.pack(side="left", padx=12, pady=6)

        self.tiktok_status = ctk.CTkLabel(
            status_bar,
            text="",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.tiktok_status.pack(side="right", padx=12, pady=6)

        self._update_connection_status()

        # 2.5 In-App Embedded Video Player (YouTube Mode)
        ov_port = self.config_manager.get("overlay_port", 5000) if self.config_manager else 5000
        self.embedded_player = EmbeddedPlayer(self, on_video_ended=self._on_video_ended, overlay_port=ov_port, height=260)
        self.embedded_player.set_music_service(self.music_service)
        if self.service_type == "youtube":
            self.embedded_player.pack(fill="x", padx=16, pady=(4, 6))
            self.after(400, self.embedded_player.start_player)
        else:
            self.embedded_player.pack_forget()

        # 3. Now Playing Card
        self.np_card = ctk.CTkFrame(self, fg_color="#1a1c24", corner_radius=14)
        self.np_card.pack(fill="x", padx=16, pady=8)

        card_top = ctk.CTkFrame(self.np_card, fg_color="transparent")
        card_top.pack(fill="x", padx=14, pady=12)

        # Album artwork placeholder
        self.art_label = ctk.CTkLabel(
            card_top,
            text="🎵",
            font=ctk.CTkFont(size=28),
            width=84,
            height=84,
            fg_color="#262938",
            corner_radius=10
        )
        self.art_label.pack(side="left", padx=(0, 12))

        # Track meta
        meta_frame = ctk.CTkFrame(card_top, fg_color="transparent")
        meta_frame.pack(side="left", fill="both", expand=True)

        self.title_lbl = ctk.CTkLabel(
            meta_frame,
            text="Waiting for Spotify...",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#FFFFFF",
            anchor="w"
        )
        self.title_lbl.pack(fill="x", pady=(2, 2))

        self.artist_lbl = ctk.CTkLabel(
            meta_frame,
            text="Play a song to begin",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF",
            anchor="w"
        )
        self.artist_lbl.pack(fill="x")

        self.requester_lbl = ctk.CTkLabel(
            meta_frame,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#1DB954",
            anchor="w"
        )
        self.requester_lbl.pack(fill="x", pady=(4, 0))

        # Progress bar
        prog_wrap = ctk.CTkFrame(self.np_card, fg_color="transparent")
        prog_wrap.pack(fill="x", padx=14, pady=(0, 12))

        self.progress_bar = ctk.CTkProgressBar(prog_wrap, height=6, progress_color="#1DB954")
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(0, 4))

        self.time_lbl = ctk.CTkLabel(
            prog_wrap,
            text="0:00 / 0:00",
            font=ctk.CTkFont(size=11),
            text_color="#6B7280"
        )
        self.time_lbl.pack(anchor="e")

        # 4. Playback Controls
        ctrl_frame = ctk.CTkFrame(self, fg_color="#1a1c24", corner_radius=14)
        ctrl_frame.pack(fill="x", padx=16, pady=6)

        btn_row = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(10, 6))

        prev_btn = ctk.CTkButton(
            btn_row,
            text="⏮ Prev",
            width=80,
            height=32,
            fg_color="#2b2f42",
            hover_color="#3b4059",
            command=self._on_prev
        )
        prev_btn.pack(side="left", expand=True, padx=4)

        self.play_btn = ctk.CTkButton(
            btn_row,
            text="⏯ Play/Pause",
            width=110,
            height=32,
            fg_color="#1DB954",
            hover_color="#1aa34a",
            text_color="#FFFFFF",
            command=self._on_toggle_play
        )
        self.play_btn.pack(side="left", expand=True, padx=4)

        skip_btn = ctk.CTkButton(
            btn_row,
            text="⏭ Skip",
            width=80,
            height=32,
            fg_color="#2b2f42",
            hover_color="#3b4059",
            command=self._on_skip
        )
        skip_btn.pack(side="left", expand=True, padx=4)

        # Volume row
        vol_row = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        vol_row.pack(fill="x", padx=16, pady=(4, 10))

        self.vol_lbl = ctk.CTkLabel(
            vol_row,
            text="🔊 75%",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#9CA3AF",
            width=50
        )
        self.vol_lbl.pack(side="left")

        self.vol_slider = ctk.CTkSlider(
            vol_row,
            from_=0,
            to=100,
            number_of_steps=100,
            command=self._on_volume_change
        )
        self.vol_slider.set(75)
        self.vol_slider.pack(side="left", fill="x", expand=True, padx=8)

        # 5. Quick Moderation Tools
        mod_frame = ctk.CTkFrame(self, fg_color="#1a1c24", corner_radius=14)
        mod_frame.pack(fill="x", padx=16, pady=6)

        mod_title = ctk.CTkLabel(
            mod_frame,
            text="MODERATION TOOLS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#6B7280"
        )
        mod_title.pack(anchor="w", padx=14, pady=(8, 4))

        mod_btn_row = ctk.CTkFrame(mod_frame, fg_color="transparent")
        mod_btn_row.pack(fill="x", padx=12, pady=(0, 10))

        reset_btn = ctk.CTkButton(
            mod_btn_row,
            text="🔄 Reset Limits",
            height=30,
            fg_color="#2b2f42",
            hover_color="#3b4059",
            command=self._on_reset_limits
        )
        reset_btn.pack(side="left", fill="x", expand=True, padx=4)

        clear_btn = ctk.CTkButton(
            mod_btn_row,
            text="🗑 Clear Playlist",
            height=30,
            fg_color="#842029",
            hover_color="#a82834",
            command=self._on_clear_playlist
        )
        clear_btn.pack(side="left", fill="x", expand=True, padx=4)

        # 6. Live Request Queue Feed
        queue_header = ctk.CTkFrame(self, fg_color="transparent")
        queue_header.pack(fill="x", padx=18, pady=(8, 2))

        q_title = ctk.CTkLabel(
            queue_header,
            text="RECENT SONG REQUESTS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#6B7280"
        )
        q_title.pack(side="left")

        self.queue_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="#1a1c24",
            corner_radius=12,
            height=130
        )
        self.queue_frame.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        self.empty_q_lbl = ctk.CTkLabel(
            self.queue_frame,
            text="No song requests yet.\nChatters can type !sr <song> in Twitch or TikTok!",
            font=ctk.CTkFont(size=11),
            text_color="#6B7280"
        )
        self.empty_q_lbl.pack(pady=20)

    def _toggle_always_on_top(self):
        self._always_on_top = not self._always_on_top
        self.attributes("-topmost", self._always_on_top)
        if self._always_on_top:
            self.pin_btn.configure(text="📌 Pinned", fg_color="#1DB954")
        else:
            self.pin_btn.configure(text="📌 Pin", fg_color="#252836")

    def _format_time(self, ms: int) -> str:
        sec = int(ms / 1000)
        return f"{sec // 60}:{sec % 60:02d}"

    def _fetch_art_image(self, url: str) -> Optional[ctk.CTkImage]:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=3) as resp:
                data = resp.read()
            pil_img = Image.open(io.BytesIO(data)).resize((84, 84))
            return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(84, 84))
        except Exception:
            return None

    def _start_polling(self):
        def worker():
            while True:
                try:
                    self._poll_spotify_state()
                except Exception as e:
                    logger.debug(f"Error in polling loop: {e}")
                time.sleep(1.2)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _poll_spotify_state(self):
        try:
            playback = self.spotify.get_currently_playing()
            recent = self.spotify.get_recent_requests()
            pending = self.spotify.get_queue() if hasattr(self.spotify, "get_queue") else []
        except Exception as e:
            logger.debug(f"Error fetching playback/recent requests: {e}")
            playback = None
            recent = []
            pending = []

        # In YouTube mode, sync active video ID with embedded player
        if self.service_type == "youtube" and playback and playback.get("id"):
            if playback["id"] != self._current_track_id:
                self._current_track_id = playback["id"]
                if self.embedded_player:
                    try:
                        if self.winfo_exists():
                            self.after(0, lambda: self.embedded_player.load_video(
                                playback["id"],
                                title=playback.get("title"),
                                artist=playback.get("artist_str")
                            ))
                    except Exception:
                        pass

        def update_gui():
            if not self.winfo_exists():
                return
            if playback and playback.get("title"):
                # Title & Artist
                self.title_lbl.configure(text=playback["title"][:28])
                self.artist_lbl.configure(text=playback["artist_str"][:32])

                # Requester
                req = playback.get("requested_by")
                if req:
                    self.requester_lbl.configure(text=f"🎵 {req}")
                else:
                    self.requester_lbl.configure(text="")

                # Progress
                prog = playback.get("progress_ms", 0)
                dur = playback.get("duration_ms", 1)
                self.progress_bar.set(min(1.0, prog / max(1, dur)))
                self.time_lbl.configure(text=f"{self._format_time(prog)} / {self._format_time(dur)}")

                # Play/Pause label
                if playback.get("is_playing"):
                    self.play_btn.configure(text="⏸ Pause")
                else:
                    self.play_btn.configure(text="▶ Play")

                # Album art update
                art_url = playback.get("album_art")
                if art_url and art_url != self._last_art_url:
                    self._last_art_url = art_url
                    # Load in thread
                    threading.Thread(target=self._load_and_set_art, args=(art_url,), daemon=True).start()

            else:
                self.title_lbl.configure(text="No Track Playing")
                idle_desc = "YouTube queue is idle" if self.service_type == "youtube" else "Spotify is paused or idle"
                self.artist_lbl.configure(text=idle_desc)
                self.requester_lbl.configure(text="")
                self.progress_bar.set(0)
                self.time_lbl.configure(text="0:00 / 0:00")
                self.play_btn.configure(text="▶ Play")

            # Update Queue Feed with both pending and recent requests
            self._update_queue_ui(recent, pending)

        try:
            if self.winfo_exists():
                self.after(0, update_gui)
        except Exception:
            pass

    def _load_and_set_art(self, url: str):
        img = self._fetch_art_image(url)
        if img:
            def apply():
                try:
                    if self.winfo_exists():
                        self.art_label.configure(image=img, text="")
                except Exception:
                    pass
            try:
                if self.winfo_exists():
                    self.after(0, apply)
            except Exception:
                pass

    def _update_queue_ui(self, recent: list, pending: Optional[list] = None):
        # Clear existing rows
        for child in self.queue_frame.winfo_children():
            child.destroy()

        display_items = []
        # 1. Pending tracks in queue (Up next)
        if pending:
            for item in pending:
                display_items.append({
                    "title": item.get("name") or item.get("title", "Unknown"),
                    "artist": item.get("artist_str") or item.get("artist", "YouTube"),
                    "requested_by": item.get("requested_by", "Chatter"),
                    "badge": "⏳ Up Next",
                    "badge_color": "#FE2C55"
                })

        # 2. Recent requests
        if recent:
            for item in recent:
                t_key = f"{item.get('title')} - {item.get('artist')}"
                if not any(f"{p['title']} - {p['artist']}" == t_key for p in display_items):
                    display_items.append({
                        "title": item.get("title", "Unknown"),
                        "artist": item.get("artist", "YouTube"),
                        "requested_by": item.get("requested_by", "Chatter"),
                        "badge": "✔ Requested",
                        "badge_color": "#1DB954"
                    })

        if not display_items:
            lbl = ctk.CTkLabel(
                self.queue_frame,
                text="No song requests yet.\nChatters can type !sr <song> in Twitch or TikTok!",
                font=ctk.CTkFont(size=11),
                text_color="#6B7280"
            )
            lbl.pack(pady=20)
            return

        for item in display_items[:12]:
            row = ctk.CTkFrame(self.queue_frame, fg_color="#212430", corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)

            meta = ctk.CTkFrame(row, fg_color="transparent")
            meta.pack(side="left", fill="both", expand=True, padx=8, pady=4)

            t_lbl = ctk.CTkLabel(
                meta,
                text=f"{item['title']} - {item['artist']}"[:34],
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#FFFFFF",
                anchor="w"
            )
            t_lbl.pack(fill="x")

            r_lbl = ctk.CTkLabel(
                meta,
                text=f"{item.get('badge', '🎵')} | Requested by: {item.get('requested_by', 'Chatter')}",
                font=ctk.CTkFont(size=10),
                text_color=item.get("badge_color", "#1DB954"),
                anchor="w"
            )
            r_lbl.pack(fill="x")

    def _on_video_ended(self):
        logger.info("[MiniApp] In-app player finished video, advancing queue...")
        self._on_skip()

    def _toggle_video_panel(self):
        if not self.embedded_player or self.service_type != "youtube":
            return
        self._video_visible = not self._video_visible
        if self._video_visible:
            self.embedded_player.pack(fill="x", padx=16, pady=(4, 6), before=self.np_card)
            self.video_toggle_btn.configure(text="👁 Hide", fg_color="#FE2C55", hover_color="#E11D48")
        else:
            self.embedded_player.pack_forget()
            self.video_toggle_btn.configure(text="👁 Show", fg_color="#252836", hover_color="#32364a")

    def _on_skip(self):
        def do_skip():
            self.music_service.next_track()
            if self.service_type == "youtube":
                curr = self.music_service.get_currently_playing()
                if curr and curr.get("id"):
                    self._current_track_id = curr["id"]
                    if self.embedded_player:
                        self.after(0, lambda: self.embedded_player.load_video(
                            curr["id"],
                            title=curr.get("title"),
                            artist=curr.get("artist_str")
                        ))
                else:
                    self._current_track_id = None
                    if self.embedded_player:
                        self.after(0, self.embedded_player.stop)
        threading.Thread(target=do_skip, daemon=True).start()

    def _on_prev(self):
        def do_prev():
            self.music_service.previous_track()
            if self.service_type == "youtube":
                curr = self.music_service.get_currently_playing()
                if curr and curr.get("id"):
                    self._current_track_id = curr["id"]
                    if self.embedded_player:
                        self.after(0, lambda: self.embedded_player.load_video(
                            curr["id"],
                            title=curr.get("title"),
                            artist=curr.get("artist_str")
                        ))
        threading.Thread(target=do_prev, daemon=True).start()

    def _on_toggle_play(self):
        def do_toggle():
            self.music_service.toggle_playback()
            if self.service_type == "youtube" and self.embedded_player:
                self.after(0, self.embedded_player.toggle_playback)
        threading.Thread(target=do_toggle, daemon=True).start()

    def _on_volume_change(self, val):
        vol = int(val)
        self.vol_lbl.configure(text=f"🔊 {vol}%")
        def do_vol():
            self.music_service.set_volume(vol)
            if self.service_type == "youtube" and self.embedded_player:
                self.after(0, lambda: self.embedded_player.set_volume(vol))
        threading.Thread(target=do_vol, daemon=True).start()

    def _on_reset_limits(self):
        self.limiter.reset_limits()
        btn = self.focus_get()
        # Show quick confirmation
        self.title_lbl.configure(text="[LIMITS RESET!]")
        self.after(1500, lambda: None)

    def _on_clear_playlist(self):
        def do_clear():
            self.music_service.clear_playlist()
            if self.service_type == "youtube" and self.embedded_player:
                self.after(0, self.embedded_player.pause)
        threading.Thread(target=do_clear, daemon=True).start()

    def _update_connection_status(self):
        enable_tw = True
        enable_tt = True
        if self.config_manager:
            enable_tw = bool(self.config_manager.get("enable_twitch", True))
            enable_tt = bool(self.config_manager.get("enable_tiktok", True))

        # Twitch status
        if not enable_tw or self.twitch_channel == "Disabled":
            tw_text = "🟣 Twitch: (Disabled)"
            tw_color = "#64748B"
        elif self.twitch_channel and self.twitch_channel != "N/A":
            tw_text = f"🟣 Twitch: #{self.twitch_channel}"
            tw_color = "#A970FF"
        else:
            tw_text = "🟣 Twitch: (Not connected)"
            tw_color = "#7A8098"

        # TikTok status
        if not enable_tt or self.tiktok_username == "Disabled":
            tt_text = "🔴 TikTok: (Disabled)"
            tt_color = "#64748B"
        elif self.tiktok_username and self.tiktok_username != "N/A":
            tt_text = f"🔴 TikTok: @{self.tiktok_username}"
            tt_color = "#FE2C55"
        else:
            tt_text = "🔴 TikTok: (Not connected)"
            tt_color = "#7A8098"

        if hasattr(self, "twitch_status") and self.twitch_status:
            self.twitch_status.configure(text=tw_text, text_color=tw_color)
        if hasattr(self, "tiktok_status") and self.tiktok_status:
            self.tiktok_status.configure(text=tt_text, text_color=tt_color)

    def _open_settings(self):
        from src.setup_wizard import SettingsModal
        modal = SettingsModal(self, config_manager=self.config_manager)
        self.wait_window(modal)
        self._apply_settings_update()

    def _apply_settings_update(self):
        if not self.config_manager:
            return

        self.config_manager.load()
        enable_tw = self.config_manager.get("enable_twitch", True)
        enable_tt = self.config_manager.get("enable_tiktok", True)
        tw = (self.config_manager.get("twitch_channel") or self.config_manager.get("twitch_nick") or "N/A") if enable_tw else "Disabled"
        tt = (self.config_manager.get("tiktok_username") or "N/A") if enable_tt else "Disabled"
        self.twitch_channel = tw
        self.tiktok_username = tt
        self._update_connection_status()

        new_platform = self.config_manager.get("music_platform", "spotify")
        logger.info(f"[MiniApp] Settings applied. Current service: {self.service_type}, Target service: {new_platform}")

        if new_platform != self.service_type:
            logger.info(f"[MiniApp] Switching platform from {self.service_type} to {new_platform}...")
            if self.bot_manager:
                new_service = self.bot_manager.switch_music_service(new_platform)
            else:
                if new_platform == "youtube":
                    from src.youtube_service import YouTubeService
                    new_service = YouTubeService(
                        initial_playlist=self.config_manager.get("youtube_initial_playlist"),
                        music_only=self.config_manager.get("youtube_music_only", True),
                        max_duration_seconds=self.config_manager.get("youtube_max_duration_seconds", 600)
                    )
                else:
                    from src.spotify_service import SpotifyService
                    new_service = SpotifyService(
                        client_id=self.config_manager.get("spotify_client_id"),
                        client_secret=self.config_manager.get("spotify_client_secret"),
                        redirect_uri=self.config_manager.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback"),
                        playlist_id=self.config_manager.get("spotify_playlist_id"),
                        open_browser=False
                    )
            self.music_service = new_service
            self.spotify = new_service
            self.service_type = new_platform
            self._current_track_id = None
            self._last_art_url = None
            if self.embedded_player:
                self.embedded_player.set_music_service(new_service)

        self._update_platform_ui()

    def _update_platform_ui(self):
        """Updates UI components (badge, video button, embedded player) for the active platform."""
        if hasattr(self, "platform_badge"):
            if self.service_type == "youtube":
                self.platform_badge.configure(text="🔴 YouTube Active", fg_color="#3b1219", text_color="#FE2C55")
            else:
                self.platform_badge.configure(text="🟢 Spotify Active", fg_color="#102d1d", text_color="#1DB954")

        if self.service_type == "youtube":
            self._video_visible = True
            if self.embedded_player:
                self.embedded_player.pack(fill="x", padx=16, pady=(4, 6), before=self.np_card)
                self.after(300, self.embedded_player.start_player)
            if hasattr(self, "video_toggle_btn"):
                self.video_toggle_btn.configure(text="👁 Hide", fg_color="#FE2C55", hover_color="#E11D48")
                self.video_toggle_btn.pack(side="right", padx=(0, 6), before=self.settings_btn)
        else:
            self._video_visible = False
            if self.embedded_player:
                self.embedded_player.stop()
                self.embedded_player.pack_forget()
            if hasattr(self, "video_toggle_btn"):
                self.video_toggle_btn.pack_forget()

            # Reset Now Playing card to Spotify waiting state
            self.title_lbl.configure(text="Waiting for Spotify...")
            self.artist_lbl.configure(text="Play a song to begin")
            self.requester_lbl.configure(text="")
            self.progress_bar.set(0)
            self.time_lbl.configure(text="0:00 / 0:00")
            self.play_btn.configure(text="▶ Play")
            self.art_label.configure(image=None, text="🎵")
