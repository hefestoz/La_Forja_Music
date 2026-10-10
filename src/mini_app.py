import os
import io
import time
import threading
import logging
from typing import Optional, Dict, Any
from urllib.request import urlopen, Request
from PIL import Image, ImageTk
import customtkinter as ctk

from src.spotify_service import SpotifyService
from src.request_limiter import RequestLimiter

logger = logging.getLogger("MiniApp")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")

class MiniApp(ctk.CTk):
    """
    Compact desktop controller window for streamers on their secondary screen.
    Provides live playback info, skip/pause controls, volume, moderation, and queue feed.
    """

    def __init__(
        self,
        spotify_service: SpotifyService,
        request_limiter: RequestLimiter,
        twitch_channel: str = "hefestoz",
        tiktok_username: str = "hefestoz"
    ):
        super().__init__()

        self.spotify = spotify_service
        self.limiter = request_limiter
        self.twitch_channel = twitch_channel
        self.tiktok_username = tiktok_username

        # Window settings
        self.title("La Forja Music - Stream Controller")
        self.geometry("420x700")
        self.minsize(400, 650)
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
        header.pack(fill="x", padx=16, pady=(14, 6))

        title_label = ctk.CTkLabel(
            header,
            text="🎧 LA FORJA MUSIC",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color="#FFFFFF"
        )
        title_label.pack(side="left")

        self.pin_btn = ctk.CTkButton(
            header,
            text="📌 Pin",
            width=60,
            height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#252836",
            hover_color="#32364a",
            command=self._toggle_always_on_top
        )
        self.pin_btn.pack(side="right")

        # 2. Connection Status Bar
        status_bar = ctk.CTkFrame(self, fg_color="#1a1c24", corner_radius=10)
        status_bar.pack(fill="x", padx=16, pady=6)

        self.twitch_status = ctk.CTkLabel(
            status_bar,
            text=f"🟣 Twitch: #{self.twitch_channel}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#A970FF"
        )
        self.twitch_status.pack(side="left", padx=12, pady=6)

        self.tiktok_status = ctk.CTkLabel(
            status_bar,
            text=f"🔴 TikTok: @{self.tiktok_username}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#FE2C55"
        )
        self.tiktok_status.pack(side="right", padx=12, pady=6)

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
        playback = self.spotify.get_currently_playing()
        recent = self.spotify.get_recent_requests()

        def update_gui():
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
                self.artist_lbl.configure(text="Spotify is paused or idle")
                self.requester_lbl.configure(text="")
                self.progress_bar.set(0)
                self.time_lbl.configure(text="0:00 / 0:00")
                self.play_btn.configure(text="▶ Play")

            # Update Queue Feed
            self._update_queue_ui(recent)

        self.after(0, update_gui)

    def _load_and_set_art(self, url: str):
        img = self._fetch_art_image(url)
        if img:
            def apply():
                self.art_label.configure(image=img, text="")
            self.after(0, apply)

    def _update_queue_ui(self, recent: list):
        # Clear existing rows
        for child in self.queue_frame.winfo_children():
            child.destroy()

        if not recent:
            lbl = ctk.CTkLabel(
                self.queue_frame,
                text="No song requests yet.\nChatters can type !sr <song> in Twitch or TikTok!",
                font=ctk.CTkFont(size=11),
                text_color="#6B7280"
            )
            lbl.pack(pady=20)
            return

        for item in recent[:10]:
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
                text=f"Requested by: {item.get('requested_by', 'Chatter')}",
                font=ctk.CTkFont(size=10),
                text_color="#1DB954",
                anchor="w"
            )
            r_lbl.pack(fill="x")

    def _on_skip(self):
        threading.Thread(target=self.spotify.next_track, daemon=True).start()

    def _on_prev(self):
        threading.Thread(target=self.spotify.previous_track, daemon=True).start()

    def _on_toggle_play(self):
        threading.Thread(target=self.spotify.toggle_playback, daemon=True).start()

    def _on_volume_change(self, val):
        vol = int(val)
        self.vol_lbl.configure(text=f"🔊 {vol}%")
        threading.Thread(target=self.spotify.set_volume, args=(vol,), daemon=True).start()

    def _on_reset_limits(self):
        self.limiter.reset_limits()
        btn = self.focus_get()
        # Show quick confirmation
        self.title_lbl.configure(text="[LIMITS RESET!]")
        self.after(1500, lambda: None)

    def _on_clear_playlist(self):
        threading.Thread(target=self.spotify.clear_playlist, daemon=True).start()
