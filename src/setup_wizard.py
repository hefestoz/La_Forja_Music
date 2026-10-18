import os
import re
import sys
import webbrowser
import threading
import logging
import tkinter as tk
from typing import Optional, Callable, Dict, Any
import customtkinter as ctk

from src.config_manager import ConfigManager
from src.auth_server import OAuthServer
from src.spotify_service import SpotifyService
from src.twitch_service import validate_twitch_token

logger = logging.getLogger("SetupWizard")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")

class SetupWizard(ctk.CTk):
    """
    Interactive Setup and Configuration Wizard for Streamers.
    Guides non-technical streamers through Spotify authorization,
    playlist selection/creation, Twitch OAuth login / validation,
    TikTok handles, and rule settings.
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        on_complete: Optional[Callable[[], None]] = None,
        edit_mode: bool = False
    ):
        super().__init__()

        self.config = config_manager or ConfigManager()
        self.on_complete = on_complete
        self.edit_mode = edit_mode

        # Window settings
        self.title("La Forja Music - Setup Wizard" if not edit_mode else "La Forja Music - Settings")
        self.geometry("540x860")
        self.minsize(500, 720)
        self.configure(fg_color="#121318")

        self.spotify_service: Optional[SpotifyService] = None
        self.oauth_server: Optional[OAuthServer] = None
        self.playlists_cache: list[Dict[str, Any]] = []
        self._twitch_validate_timer: Optional[Any] = None
        self._guide_visible = False
        self._twitch_guide_visible = False

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._init_spotify_service()
        self._build_ui()

        # Keep instruction windows closed by default; expand dev keys entry if keys not set
        has_spotify = bool(self.config.get("spotify_client_id") and self.config.get("spotify_client_secret"))
        if not has_spotify:
            self.dev_toggle_var.set(True)
            self._toggle_dev_mode()

        # Apply initial toggle states for Twitch and TikTok
        self._on_twitch_enable_toggle()
        self._on_tiktok_enable_toggle()

        # Validate existing Twitch token if already present in config and Twitch is enabled
        existing_tw_token = self.config.get("twitch_token")
        if self.enable_twitch_var.get() and existing_tw_token:
            self._validate_twitch_token_async(existing_tw_token)

    def _on_close(self):
        """Clean up loopback server on window close."""
        if self.oauth_server:
            self.oauth_server.stop()
        self.destroy()

    def _ensure_oauth_server(self) -> Optional[OAuthServer]:
        """Ensures the background OAuth loopback server is running on port 8888."""
        if not self.oauth_server:
            self.oauth_server = OAuthServer(
                port=8888,
                on_code_callback=self._handle_spotify_oauth_code,
                on_twitch_token_callback=self._handle_twitch_oauth_token
            )
            ok = self.oauth_server.start()
            if not ok:
                return None
        return self.oauth_server

    def _init_spotify_service(self):
        """Attempts to initialize SpotifyService if credentials exist."""
        cid = self.config.get("spotify_client_id")
        csecret = self.config.get("spotify_client_secret")
        r_uri = self.config.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback")
        pid = self.config.get("spotify_playlist_id")

        if cid and csecret:
            try:
                self.spotify_service = SpotifyService(
                    client_id=cid,
                    client_secret=csecret,
                    redirect_uri=r_uri,
                    playlist_id=pid if pid else None,
                    open_browser=False
                )
            except Exception as e:
                logger.debug(f"Could not pre-init SpotifyService: {e}")

    def _build_ui(self):
        # Scrollable container for all configuration cards
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=16, pady=(16, 10))

        # 1. Header
        header_title = "🎧 STREAMER SETUP WIZARD" if not self.edit_mode else "⚙️ STREAMER SETTINGS"
        header_sub = "Configure your streaming channels and Spotify playlist below."

        lbl_title = ctk.CTkLabel(
            self.scroll,
            text=header_title,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#FFFFFF"
        )
        lbl_title.pack(anchor="w", pady=(0, 2))

        lbl_sub = ctk.CTkLabel(
            self.scroll,
            text=header_sub,
            font=ctk.CTkFont(size=12),
            text_color="#8E92A8"
        )
        lbl_sub.pack(anchor="w", pady=(0, 14))

        # 2. Spotify Card
        self._build_spotify_card()

        # 3. Chat Channels Card
        self._build_chat_card()

        # 4. Stream Rules Card
        self._build_rules_card()

        # 5. OBS Overlay Card
        self._build_obs_card()

        # 6. Danger Zone / Reset & Logout Card
        self._build_danger_card()

        # Footer Frame (Status message & Save/Start button)
        footer = ctk.CTkFrame(self, fg_color="#181a22", corner_radius=0, height=80)
        footer.pack(fill="x", side="bottom")

        self.lbl_status = ctk.CTkLabel(
            footer,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#8E92A8"
        )
        self.lbl_status.pack(side="left", padx=16, pady=16)

        btn_action_text = "🚀 Save & Start Bot" if not self.edit_mode else "💾 Save Settings"
        self.btn_save = ctk.CTkButton(
            footer,
            text=btn_action_text,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1DB954",
            hover_color="#1AA34A",
            height=42,
            width=160,
            command=self._save_and_launch
        )
        self.btn_save.pack(side="right", padx=16, pady=16)

    # ------------------------------------------------------------------
    # Card 1: Spotify Account & Playlist
    # ------------------------------------------------------------------
    def _build_spotify_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#181a22", corner_radius=14)
        card.pack(fill="x", pady=8)

        lbl = ctk.CTkLabel(
            card,
            text="1. Spotify Connection",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#1DB954"
        )
        lbl.pack(anchor="w", padx=16, pady=(12, 6))

        # Status text
        self.spotify_status = ctk.CTkLabel(
            card,
            text="Checking Spotify authorization...",
            font=ctk.CTkFont(size=12),
            text_color="#A0A5BA"
        )
        self.spotify_status.pack(anchor="w", padx=16, pady=(0, 8))

        # Buttons frame
        self.btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.btn_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.btn_connect_spotify = ctk.CTkButton(
            self.btn_frame,
            text="🟢 Connect Spotify Account",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1DB954",
            hover_color="#1AA34A",
            command=self._start_spotify_login
        )
        self.btn_connect_spotify.pack(side="left", padx=(0, 8))

        self.btn_spotify_guide = ctk.CTkButton(
            self.btn_frame,
            text="❓ How to Get Spotify Keys",
            font=ctk.CTkFont(size=12),
            fg_color="#1E293B",
            hover_color="#334155",
            text_color="#38BDF8",
            command=self._toggle_spotify_guide
        )
        self.btn_spotify_guide.pack(side="left")

        # Step-by-Step Spotify Guide Panel (Collapsible)
        self.spotify_guide_frame = ctk.CTkFrame(card, fg_color="#0F172A", corner_radius=10, border_width=1, border_color="#1E3A8A")

        lbl_g_title = ctk.CTkLabel(
            self.spotify_guide_frame,
            text="📘 How to Get Free Spotify Developer Keys (Step-by-Step):",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38BDF8"
        )
        lbl_g_title.pack(anchor="w", padx=14, pady=(10, 4))

        guide_step1 = (
            "1. Click the button below to open the official Spotify Developer Dashboard:\n"
            "   (Log in with your existing Spotify account)"
        )
        ctk.CTkLabel(self.spotify_guide_frame, text=guide_step1, font=ctk.CTkFont(size=11), text_color="#E2E8F0", justify="left").pack(anchor="w", padx=14, pady=(2, 4))

        btn_dash = ctk.CTkButton(
            self.spotify_guide_frame,
            text="🌐 1. Open Spotify Developer Dashboard",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0284C7",
            hover_color="#0369A1",
            height=30,
            command=lambda: webbrowser.open("https://developer.spotify.com/dashboard")
        )
        btn_dash.pack(anchor="w", padx=14, pady=(0, 8))

        guide_step2 = (
            "2. Click the green \"Create app\" button on the top right.\n"
            "3. Fill in the simple form:\n"
            "   • App name: La Forja Music (or your stream name)\n"
            "   • App description: Interactive song request bot\n"
            "   • Redirect URI (Click Copy button below):"
        )
        ctk.CTkLabel(self.spotify_guide_frame, text=guide_step2, font=ctk.CTkFont(size=11), text_color="#E2E8F0", justify="left").pack(anchor="w", padx=14, pady=(2, 2))

        uri_row = ctk.CTkFrame(self.spotify_guide_frame, fg_color="transparent")
        uri_row.pack(fill="x", padx=14, pady=(2, 6))

        uri_val = self.config.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback")
        ctk.CTkLabel(uri_row, text=uri_val, font=ctk.CTkFont(size=11, weight="bold"), text_color="#10B981").pack(side="left")

        btn_copy_uri = ctk.CTkButton(
            uri_row,
            text="📋 Copy Redirect URI",
            font=ctk.CTkFont(size=11),
            width=140,
            height=26,
            fg_color="#1E293B",
            hover_color="#334155",
            command=self._copy_redirect_uri
        )
        btn_copy_uri.pack(side="left", padx=(10, 0))

        guide_step3 = (
            "   • Which API are you planning to use? -> Check the \"Web API\" checkbox.\n"
            "   • Check the terms checkbox and click \"Save\".\n"
            "4. On your new app's page, click \"Settings\" (top right) -> click \"View client secret\".\n"
            "5. Copy your Client ID and Client Secret, and click Paste below!"
        )
        ctk.CTkLabel(self.spotify_guide_frame, text=guide_step3, font=ctk.CTkFont(size=11), text_color="#E2E8F0", justify="left").pack(anchor="w", padx=14, pady=(2, 10))

        # Playlist selection frame
        self.playlist_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.playlist_frame.pack(fill="x", padx=16, pady=(4, 12))

        lbl_pl = ctk.CTkLabel(
            self.playlist_frame,
            text="Target Playlist for Song Requests:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#FFFFFF"
        )
        lbl_pl.pack(anchor="w", pady=(2, 4))

        self.playlist_var = ctk.StringVar(value="Select or create a playlist...")
        self.playlist_dropdown = ctk.CTkOptionMenu(
            self.playlist_frame,
            variable=self.playlist_var,
            values=["(Log in to view playlists)"],
            width=260,
            command=self._on_playlist_selected
        )
        self.playlist_dropdown.pack(side="left", padx=(0, 8))

        self.btn_create_pl = ctk.CTkButton(
            self.playlist_frame,
            text="+ Create 'Stream Requests'",
            width=170,
            fg_color="#252836",
            hover_color="#32364a",
            command=self._auto_create_playlist
        )
        self.btn_create_pl.pack(side="left")

        # Developer Credentials Accordion
        self.dev_toggle_var = ctk.BooleanVar(value=False)
        self.dev_toggle = ctk.CTkCheckBox(
            card,
            text="Advanced Developer Credentials (Spotify & Twitch API)",
            variable=self.dev_toggle_var,
            font=ctk.CTkFont(size=11),
            text_color="#7A8098",
            command=self._toggle_dev_mode
        )
        self.dev_toggle.pack(anchor="w", padx=16, pady=(4, 8))

        self.dev_frame = ctk.CTkFrame(card, fg_color="#13141a", corner_radius=10)

        ctk.CTkLabel(self.dev_frame, text="Spotify Client ID:", font=ctk.CTkFont(size=11), text_color="#A0A5BA").pack(anchor="w", padx=12, pady=(6, 1))

        cid_row = ctk.CTkFrame(self.dev_frame, fg_color="transparent")
        cid_row.pack(fill="x", padx=12, pady=(0, 4))

        self.entry_client_id = ctk.CTkEntry(cid_row, placeholder_text="Spotify Client ID")
        self.entry_client_id.insert(0, self.config.get("spotify_client_id", ""))
        self.entry_client_id.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_paste_cid = ctk.CTkButton(
            cid_row,
            text="📋 Paste",
            width=70,
            fg_color="#252836",
            hover_color="#32364a",
            command=self._paste_client_id
        )
        btn_paste_cid.pack(side="right")

        ctk.CTkLabel(self.dev_frame, text="Spotify Client Secret:", font=ctk.CTkFont(size=11), text_color="#A0A5BA").pack(anchor="w", padx=12, pady=(4, 1))

        csec_row = ctk.CTkFrame(self.dev_frame, fg_color="transparent")
        csec_row.pack(fill="x", padx=12, pady=(0, 6))

        self.entry_client_secret = ctk.CTkEntry(csec_row, show="•", placeholder_text="Spotify Client Secret")
        self.entry_client_secret.insert(0, self.config.get("spotify_client_secret", ""))
        self.entry_client_secret.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_paste_csec = ctk.CTkButton(
            csec_row,
            text="📋 Paste",
            width=70,
            fg_color="#252836",
            hover_color="#32364a",
            command=self._paste_client_secret
        )
        btn_paste_csec.pack(side="right")

        ctk.CTkLabel(self.dev_frame, text="Twitch Client ID (Optional for custom app OAuth redirect):", font=ctk.CTkFont(size=11), text_color="#A0A5BA").pack(anchor="w", padx=12, pady=(4, 1))

        tw_cid_row = ctk.CTkFrame(self.dev_frame, fg_color="transparent")
        tw_cid_row.pack(fill="x", padx=12, pady=(0, 8))

        self.entry_twitch_client_id = ctk.CTkEntry(tw_cid_row, placeholder_text="Twitch Application Client ID (Optional)")
        self.entry_twitch_client_id.insert(0, self.config.get("twitch_client_id", ""))
        self.entry_twitch_client_id.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_tw_dev = ctk.CTkButton(
            tw_cid_row,
            text="🌐 Dev Console",
            width=110,
            fg_color="#252836",
            hover_color="#32364a",
            command=lambda: webbrowser.open("https://dev.twitch.tv/console/apps")
        )
        btn_tw_dev.pack(side="right")

        self._refresh_spotify_ui()

    def _toggle_spotify_guide(self):
        if self._guide_visible:
            self.spotify_guide_frame.pack_forget()
            self._guide_visible = False
            self.btn_spotify_guide.configure(text="❓ How to Get Spotify Keys")
        else:
            self.spotify_guide_frame.pack(fill="x", padx=16, pady=(4, 10), after=self.btn_frame)
            self._guide_visible = True
            self.btn_spotify_guide.configure(text="✖ Close Guide")

    def _toggle_twitch_guide(self):
        if self._twitch_guide_visible:
            self.twitch_guide_frame.pack_forget()
            self._twitch_guide_visible = False
            self.btn_twitch_guide.configure(text="❓ How to Connect Twitch")
        else:
            self.twitch_guide_frame.pack(fill="x", padx=16, pady=(4, 10), after=self.tw_btn_frame)
            self._twitch_guide_visible = True
            self.btn_twitch_guide.configure(text="✖ Close Guide")

    def _on_twitch_enable_toggle(self):
        enabled = self.enable_twitch_var.get()
        state = "normal" if enabled else "disabled"
        entry_fg = ["#F9F9FA", "#343638"] if enabled else ["#E2E8F0", "#1E2029"]
        entry_text = ["#000000", "#FFFFFF"] if enabled else ["#94A3B8", "#64748B"]

        self.entry_twitch_token.configure(state=state, fg_color=entry_fg, text_color=entry_text)
        self.entry_twitch_channel.configure(state=state, fg_color=entry_fg, text_color=entry_text)
        self.btn_get_twitch_token.configure(state=state)
        self.btn_twitch_guide.configure(state=state)
        self.btn_connect_twitch.configure(state=state)
        if hasattr(self, "btn_paste_tw"):
            self.btn_paste_tw.configure(state=state)

        if not enabled:
            if self._twitch_guide_visible:
                self._toggle_twitch_guide()
            self.twitch_status.configure(text="⚪ Twitch integration disabled for this session", text_color="#64748B")
        else:
            token = self.entry_twitch_token.get().strip()
            if token:
                self._validate_twitch_token_async(token)
            else:
                self.twitch_status.configure(text="⚪ Not connected to Twitch", text_color="#A0A5BA")

    def _on_tiktok_enable_toggle(self):
        enabled = self.enable_tiktok_var.get()
        state = "normal" if enabled else "disabled"
        entry_fg = ["#F9F9FA", "#343638"] if enabled else ["#E2E8F0", "#1E2029"]
        entry_text = ["#000000", "#FFFFFF"] if enabled else ["#94A3B8", "#64748B"]

        self.entry_tiktok_user.configure(state=state, fg_color=entry_fg, text_color=entry_text)

        if not enabled:
            self.tiktok_status.configure(text="⚪ TikTok integration disabled for this session", text_color="#64748B")
        else:
            user = self.entry_tiktok_user.get().strip().lstrip("@")
            if user:
                self.tiktok_status.configure(text=f"🟢 Enabled for @{user} (Listens when Live)", text_color="#FE2C55")
            else:
                self.tiktok_status.configure(text="⚪ Ready (Enter TikTok username below)", text_color="#A0A5BA")

    def _copy_redirect_uri(self):
        uri = self.config.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback")
        self.clipboard_clear()
        self.clipboard_append(uri)
        self._show_success("Redirect URI copied to clipboard!")

    def _paste_client_id(self):
        try:
            val = self.clipboard_get().strip()
            if val:
                self.entry_client_id.delete(0, "end")
                self.entry_client_id.insert(0, val)
                self._show_success("Client ID pasted!")
        except Exception:
            pass

    def _paste_client_secret(self):
        try:
            val = self.clipboard_get().strip()
            if val:
                self.entry_client_secret.delete(0, "end")
                self.entry_client_secret.insert(0, val)
                self._show_success("Client Secret pasted!")
        except Exception:
            pass

    def _toggle_dev_mode(self):
        if self.dev_toggle_var.get():
            self.dev_frame.pack(fill="x", padx=16, pady=(0, 12))
        else:
            self.dev_frame.pack_forget()

    def _refresh_spotify_ui(self):
        """Updates Spotify status banner and playlists list."""
        if self.spotify_service and self.spotify_service.is_authorized():
            profile = self.spotify_service.get_current_user_profile()
            name = profile.get("display_name", "Spotify User") if profile else "Spotify User"
            self.spotify_status.configure(
                text=f"🟢 Connected as: {name}",
                text_color="#1DB954"
            )
            self.btn_connect_spotify.configure(text="🔄 Re-Authorize Account")
            self._load_playlists()
        else:
            self.spotify_status.configure(
                text="⚠️ Not connected. Please authorize your Spotify account.",
                text_color="#FFB020"
            )

    def _load_playlists(self):
        def fetch():
            if not self.spotify_service:
                return
            pls = self.spotify_service.get_user_playlists(limit=50)
            self.playlists_cache = pls
            names = [p["name"] for p in pls]

            current_pid = self.config.get("spotify_playlist_id")
            selected_name = "Select a playlist..."
            if current_pid:
                for p in pls:
                    if p["id"] == current_pid:
                        selected_name = p["name"]
                        break

            def update():
                if names:
                    self.playlist_dropdown.configure(values=names)
                    self.playlist_var.set(selected_name)
                else:
                    self.playlist_dropdown.configure(values=["No playlists found"])

            try:
                if self.winfo_exists():
                    self.after(0, update)
            except Exception:
                pass

        threading.Thread(target=fetch, daemon=True).start()

    def _on_playlist_selected(self, chosen_name: str):
        for p in self.playlists_cache:
            if p["name"] == chosen_name:
                self.config.set("spotify_playlist_id", p["id"])
                self.config.set("spotify_playlist_name", p["name"])
                if self.spotify_service:
                    self.spotify_service.playlist_id = p["id"]
                    self.spotify_service._playlist_name = p["name"]
                logger.info(f"Selected playlist: {p['name']} ({p['id']})")
                break

    def _auto_create_playlist(self):
        if not self.spotify_service or not self.spotify_service.is_authorized():
            self._show_error("Please connect your Spotify account first.")
            return

        def create():
            ok, pid, pname = self.spotify_service.create_stream_playlist()
            if ok:
                self.config.set("spotify_playlist_id", pid)
                self.config.set("spotify_playlist_name", pname)
                self._load_playlists()
                self.after(0, lambda: self._show_success(f"Created playlist '{pname}'!"))
            else:
                self.after(0, lambda: self._show_error(f"Failed to create playlist: {pid}"))

        threading.Thread(target=create, daemon=True).start()

    def _start_spotify_login(self):
        cid = self.entry_client_id.get().strip() or self.config.get("spotify_client_id")
        csecret = self.entry_client_secret.get().strip() or self.config.get("spotify_client_secret")

        if not cid or not csecret:
            self._show_error("Please enter Spotify Client ID and Secret in Advanced mode.")
            self.dev_toggle_var.set(True)
            self._toggle_dev_mode()
            return

        self.config.set("spotify_client_id", cid)
        self.config.set("spotify_client_secret", csecret)

        try:
            self.spotify_service = SpotifyService(
                client_id=cid,
                client_secret=csecret,
                redirect_uri=self.config.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback"),
                playlist_id=self.config.get("spotify_playlist_id") or None,
                open_browser=False
            )
        except Exception as e:
            self._show_error(f"Spotify init failed: {e}")
            return

        server = self._ensure_oauth_server()
        if server:
            auth_url = self.spotify_service.get_authorize_url()
            logger.info(f"Opening Spotify authorization: {auth_url}")
            webbrowser.open(auth_url)
            self.spotify_status.configure(
                text="⏳ Authorizing in your browser... Complete approval to continue.",
                text_color="#3B82F6"
            )
        else:
            self._show_error("Could not start loopback server on port 8888.")

    def _handle_spotify_oauth_code(self, code: str):
        logger.info("Received Spotify OAuth code, exchanging for tokens...")
        if not self.spotify_service:
            return
        ok = self.spotify_service.exchange_code(code)
        if ok:
            self.after(0, self._refresh_spotify_ui)
            self.after(0, lambda: self._show_success("Spotify connected successfully!"))
        else:
            self.after(0, lambda: self._show_error("Failed to exchange Spotify token."))

    # ------------------------------------------------------------------
    # Card 2: Chat Channels (Twitch & TikTok)
    # ------------------------------------------------------------------
    def _build_chat_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#181a22", corner_radius=14)
        card.pack(fill="x", pady=8)

        lbl = ctk.CTkLabel(
            card,
            text="2. Streaming Chat Channels",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#A970FF"
        )
        lbl.pack(anchor="w", padx=16, pady=(12, 6))

        # --- Twitch Section ---
        tw_header_row = ctk.CTkFrame(card, fg_color="transparent")
        tw_header_row.pack(fill="x", padx=16, pady=(4, 2))

        lbl_tw_title = ctk.CTkLabel(tw_header_row, text="🟣 Twitch Integration", font=ctk.CTkFont(size=13, weight="bold"), text_color="#FFFFFF")
        lbl_tw_title.pack(side="left")

        tw_enabled_val = self.config.get("enable_twitch", True)
        self.enable_twitch_var = ctk.BooleanVar(value=tw_enabled_val)
        self.sw_enable_twitch = ctk.CTkSwitch(
            tw_header_row,
            text="Enable Twitch",
            variable=self.enable_twitch_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            progress_color="#9146FF",
            command=self._on_twitch_enable_toggle
        )
        self.sw_enable_twitch.pack(side="right")

        self.twitch_status = ctk.CTkLabel(
            card,
            text="Checking Twitch authorization...",
            font=ctk.CTkFont(size=12),
            text_color="#A0A5BA"
        )
        self.twitch_status.pack(anchor="w", padx=16, pady=(0, 6))

        self.tw_btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.tw_btn_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.btn_get_twitch_token = ctk.CTkButton(
            self.tw_btn_frame,
            text="🔑 1. Generate Token Online",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#9146FF",
            hover_color="#772CE8",
            command=self._open_twitch_token_generator
        )
        self.btn_get_twitch_token.pack(side="left", padx=(0, 8))

        self.btn_twitch_guide = ctk.CTkButton(
            self.tw_btn_frame,
            text="❓ How to Connect Twitch",
            font=ctk.CTkFont(size=12),
            fg_color="#1E293B",
            hover_color="#334155",
            text_color="#C084FC",
            command=self._toggle_twitch_guide
        )
        self.btn_twitch_guide.pack(side="left", padx=(0, 8))

        self.btn_connect_twitch = ctk.CTkButton(
            self.tw_btn_frame,
            text="🟣 Direct OAuth (Custom App)",
            font=ctk.CTkFont(size=12),
            fg_color="#252836",
            hover_color="#32364a",
            command=self._start_twitch_login
        )
        self.btn_connect_twitch.pack(side="left")

        # Step-by-Step Twitch Guide Panel (Collapsible, closed by default)
        self.twitch_guide_frame = ctk.CTkFrame(card, fg_color="#13101E", corner_radius=10, border_width=1, border_color="#581C87")

        lbl_tw_g_title = ctk.CTkLabel(
            self.twitch_guide_frame,
            text="📘 How to Connect Your Twitch Account (Step-by-Step):",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#C084FC"
        )
        lbl_tw_g_title.pack(anchor="w", padx=14, pady=(10, 4))

        tw_guide_step1 = (
            "1. Click the button below to open TwitchTokenGenerator in your browser:"
        )
        ctk.CTkLabel(self.twitch_guide_frame, text=tw_guide_step1, font=ctk.CTkFont(size=11), text_color="#E2E8F0", justify="left").pack(anchor="w", padx=14, pady=(2, 4))

        btn_tw_gen_guide = ctk.CTkButton(
            self.twitch_guide_frame,
            text="🌐 1. Open TwitchTokenGenerator.com",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#9146FF",
            hover_color="#772CE8",
            height=30,
            command=self._open_twitch_token_generator
        )
        btn_tw_gen_guide.pack(anchor="w", padx=14, pady=(0, 8))

        tw_guide_step2 = (
            "2. On that webpage, click the green button named \"Bot Chat Token\".\n"
            "   (This automatically selects the required 'chat:read' and 'chat:edit' permissions).\n"
            "3. Click \"Authorize\" on the Twitch authorization screen.\n"
            "4. Scroll down to the \"ACCESS TOKEN\" box, select and copy your token.\n"
            "5. Come back here and click [ 📋 2. Paste Token ] below!\n"
            "   • Your channel name will be verified and auto-detected automatically."
        )
        ctk.CTkLabel(self.twitch_guide_frame, text=tw_guide_step2, font=ctk.CTkFont(size=11), text_color="#E2E8F0", justify="left").pack(anchor="w", padx=14, pady=(2, 10))

        lbl_tw_tok = ctk.CTkLabel(card, text="Twitch Chat Token (Copy & paste Access Token here):", font=ctk.CTkFont(size=11, weight="bold"), text_color="#FFFFFF")
        lbl_tw_tok.pack(anchor="w", padx=16, pady=(6, 2))

        tok_row = ctk.CTkFrame(card, fg_color="transparent")
        tok_row.pack(fill="x", padx=16, pady=(0, 6))

        self.entry_twitch_token = ctk.CTkEntry(tok_row, show="•", placeholder_text="Paste your Access Token here (oauth:xxxx or raw token)")
        self.entry_twitch_token.insert(0, self.config.get("twitch_token", ""))
        self.entry_twitch_token.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_twitch_token.bind("<KeyRelease>", self._on_twitch_token_key)
        self.entry_twitch_token.bind("<FocusOut>", lambda e: self._on_twitch_token_changed())

        self.btn_paste_tw = ctk.CTkButton(
            tok_row,
            text="📋 2. Paste Token",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=120,
            fg_color="#9146FF",
            hover_color="#772CE8",
            command=self._paste_twitch_token
        )
        self.btn_paste_tw.pack(side="right")

        lbl_tw = ctk.CTkLabel(card, text="Twitch Channel Name (Auto-detected from token):", font=ctk.CTkFont(size=11), text_color="#7A8098")
        lbl_tw.pack(anchor="w", padx=16, pady=(2, 1))

        self.entry_twitch_channel = ctk.CTkEntry(card, placeholder_text="e.g. hefestoz")
        self.entry_twitch_channel.insert(0, self.config.get("twitch_channel", ""))
        self.entry_twitch_channel.pack(fill="x", padx=16, pady=(0, 12))

        # --- TikTok Section ---
        tt_header_row = ctk.CTkFrame(card, fg_color="transparent")
        tt_header_row.pack(fill="x", padx=16, pady=(12, 2))

        lbl_tt_title = ctk.CTkLabel(tt_header_row, text="🔴 TikTok Integration", font=ctk.CTkFont(size=13, weight="bold"), text_color="#FFFFFF")
        lbl_tt_title.pack(side="left")

        tt_enabled_val = self.config.get("enable_tiktok", True)
        self.enable_tiktok_var = ctk.BooleanVar(value=tt_enabled_val)
        self.sw_enable_tiktok = ctk.CTkSwitch(
            tt_header_row,
            text="Enable TikTok",
            variable=self.enable_tiktok_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            progress_color="#FE2C55",
            command=self._on_tiktok_enable_toggle
        )
        self.sw_enable_tiktok.pack(side="right")

        self.tiktok_status = ctk.CTkLabel(
            card,
            text="Checking TikTok status...",
            font=ctk.CTkFont(size=12),
            text_color="#A0A5BA"
        )
        self.tiktok_status.pack(anchor="w", padx=16, pady=(0, 6))

        lbl_tt = ctk.CTkLabel(card, text="TikTok Username (lowercase, without @):", font=ctk.CTkFont(size=11), text_color="#7A8098")
        lbl_tt.pack(anchor="w", padx=16, pady=(2, 1))

        self.entry_tiktok_user = ctk.CTkEntry(card, placeholder_text="e.g. hefestoz")
        self.entry_tiktok_user.insert(0, self.config.get("tiktok_username", ""))
        self.entry_tiktok_user.pack(fill="x", padx=16, pady=(0, 14))

    def _start_twitch_login(self):
        tw_cid = self.entry_twitch_client_id.get().strip() or self.config.get("twitch_client_id")
        self._ensure_oauth_server()

        if tw_cid:
            # Browser-based OAuth Implicit Grant
            auth_url = (
                f"https://id.twitch.tv/oauth2/authorize"
                f"?client_id={tw_cid}"
                f"&redirect_uri=http://127.0.0.1:8888/callback"
                f"&response_type=token"
                f"&scope=chat%3Aread+chat%3Aedit+user%3Aread%3Achat"
            )
            logger.info(f"Opening Twitch authorization URL: {auth_url}")
            webbrowser.open(auth_url)
            self.twitch_status.configure(
                text="⏳ Authorizing in browser... Complete Twitch approval to connect.",
                text_color="#9146FF"
            )
        else:
            # 1-Click online token generator
            self._open_twitch_token_generator()

    def _open_twitch_token_generator(self):
        url = "https://twitchtokengenerator.com/"
        logger.info(f"Opening TwitchTokenGenerator: {url}")
        webbrowser.open(url)
        self.twitch_status.configure(
            text="ℹ️ Click 'Bot Chat Token' on TwitchTokenGenerator, authorize, and paste your Access Token below.",
            text_color="#3B82F6"
        )
        self.entry_twitch_token.focus()

    def _handle_twitch_oauth_token(self, token: str):
        logger.info("Received Twitch OAuth token from loopback redirect.")
        clean_token = token.strip()
        if not clean_token.startswith("oauth:"):
            clean_token = f"oauth:{clean_token}"

        def update():
            self.entry_twitch_token.delete(0, "end")
            self.entry_twitch_token.insert(0, clean_token)
            self._validate_twitch_token_async(clean_token)

        self.after(0, update)

    def _on_twitch_token_key(self, event=None):
        if self._twitch_validate_timer:
            self.after_cancel(self._twitch_validate_timer)
        self._twitch_validate_timer = self.after(600, self._on_twitch_token_changed)

    def _on_twitch_token_changed(self):
        token = self.entry_twitch_token.get().strip()
        if token:
            self._validate_twitch_token_async(token)
        else:
            self.twitch_status.configure(
                text="⚪ Not connected to Twitch",
                text_color="#A0A5BA"
            )

    def _paste_twitch_token(self):
        try:
            val = self.clipboard_get().strip()
            if val:
                self.entry_twitch_token.delete(0, "end")
                self.entry_twitch_token.insert(0, val)
                self._on_twitch_token_changed()
                self._show_success("Twitch token pasted! Validating...")
            else:
                self._show_error("Clipboard is empty. Copy your token first.")
        except Exception as e:
            self._show_error(f"Clipboard error: {e}")

    def _validate_twitch_token_async(self, token: str):
        clean_token = token.strip()
        if not clean_token:
            self.twitch_status.configure(
                text="⚪ Not connected to Twitch",
                text_color="#A0A5BA"
            )
            return

        self.twitch_status.configure(
            text="⏳ Validating Twitch credentials...",
            text_color="#3B82F6"
        )

        def worker():
            ok, login, scopes, err = validate_twitch_token(clean_token)

            def apply():
                if ok and login:
                    scope_info = ", ".join(s for s in scopes if "chat" in s) or "chat:read, chat:edit"
                    self.twitch_status.configure(
                        text=f"🟢 Connected as: @{login} ({scope_info})",
                        text_color="#9146FF"
                    )
                    current_chan = self.entry_twitch_channel.get().strip()
                    if not current_chan:
                        self.entry_twitch_channel.delete(0, "end")
                        self.entry_twitch_channel.insert(0, login)
                    self.config.set("twitch_token", clean_token if clean_token.startswith("oauth:") else f"oauth:{clean_token}")
                    self.config.set("twitch_channel", login)
                    self.config.set("twitch_nick", login)
                    self.btn_connect_twitch.configure(text="🔄 Re-Connect Twitch")
                    self._show_success(f"Twitch account @{login} verified!")
                else:
                    self.twitch_status.configure(
                        text=f"❌ {err or 'Invalid token'}",
                        text_color="#FF4B4B"
                    )

            try:
                if self.winfo_exists():
                    self.after(0, apply)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Card 3: Stream Rules
    # ------------------------------------------------------------------
    def _build_rules_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#181a22", corner_radius=14)
        card.pack(fill="x", pady=8)

        lbl = ctk.CTkLabel(
            card,
            text="3. Request Quotas & Stream Rules",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#FFFFFF"
        )
        lbl.pack(anchor="w", padx=16, pady=(12, 8))

        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkLabel(row1, text="Max Songs Per Chatter:", font=ctk.CTkFont(size=12), text_color="#A0A5BA").pack(side="left")

        current_max = self.config.get("max_songs_per_user", 3)
        is_unlimited = (current_max == 0)

        self.entry_max_songs = ctk.CTkEntry(row1, width=60)
        display_val = "0" if is_unlimited else str(current_max)
        self.entry_max_songs.insert(0, display_val)
        if is_unlimited:
            self.entry_max_songs.configure(state="disabled", fg_color="#1e2029", text_color="#64748b")
        self.entry_max_songs.pack(side="right")

        self.unlimited_songs_var = ctk.BooleanVar(value=is_unlimited)
        self.chk_unlimited_songs = ctk.CTkCheckBox(
            row1,
            text="Unlimited",
            variable=self.unlimited_songs_var,
            font=ctk.CTkFont(size=11),
            text_color="#10B981",
            command=self._on_unlimited_toggle
        )
        self.chk_unlimited_songs.pack(side="right", padx=(0, 10))

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkLabel(row2, text="Chatter Cooldown (Seconds):", font=ctk.CTkFont(size=12), text_color="#A0A5BA").pack(side="left")
        self.entry_cooldown = ctk.CTkEntry(row2, width=70)
        self.entry_cooldown.insert(0, str(self.config.get("cooldown_seconds", 10)))
        self.entry_cooldown.pack(side="right")

        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(row3, text="Quota Duration Mode:", font=ctk.CTkFont(size=12), text_color="#A0A5BA").pack(side="left")
        current_w = self.config.get("user_limit_window_minutes", 0)
        mode_val = "Per Stream Session" if current_w == 0 else f"Rolling {current_w} Minutes"
        self.mode_var = ctk.StringVar(value=mode_val)
        self.mode_dropdown = ctk.CTkOptionMenu(
            row3,
            variable=self.mode_var,
            values=["Per Stream Session", "Rolling 30 Minutes", "Rolling 60 Minutes"]
        )
        self.mode_dropdown.pack(side="right")

    def _on_unlimited_toggle(self):
        if self.unlimited_songs_var.get():
            self.entry_max_songs.configure(state="normal")
            self.entry_max_songs.delete(0, "end")
            self.entry_max_songs.insert(0, "0")
            self.entry_max_songs.configure(state="disabled", fg_color="#1e2029", text_color="#64748b")
        else:
            self.entry_max_songs.configure(state="normal", fg_color=["#F9F9FA", "#343638"], text_color=["#000000", "#FFFFFF"])
            self.entry_max_songs.delete(0, "end")
            self.entry_max_songs.insert(0, "3")

    # ------------------------------------------------------------------
    # Card 4: OBS Overlay
    # ------------------------------------------------------------------
    def _build_obs_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#181a22", corner_radius=14)
        card.pack(fill="x", pady=8)

        lbl = ctk.CTkLabel(
            card,
            text="4. OBS Studio Overlay Source",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#FF75C3"
        )
        lbl.pack(anchor="w", padx=16, pady=(12, 6))

        port = self.config.get("overlay_port", 5000)
        lbl_hint = ctk.CTkLabel(
            card,
            text="Add a 'Browser Source' in OBS with the URL below (340x500 px):",
            font=ctk.CTkFont(size=12),
            text_color="#A0A5BA"
        )
        lbl_hint.pack(anchor="w", padx=16, pady=(0, 4))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 12))

        lbl_obs_val = ctk.CTkLabel(
            row,
            text=f"http://127.0.0.1:{port}/overlay",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#FF75C3"
        )
        lbl_obs_val.pack(side="left")

        btn_copy = ctk.CTkButton(
            row,
            text="📋 Copy URL",
            width=100,
            fg_color="#252836",
            hover_color="#32364a",
            command=lambda: self._copy_obs_url(port)
        )
        btn_copy.pack(side="right")

    def _copy_obs_url(self, port: int):
        url = f"http://127.0.0.1:{port}/overlay"
        self.clipboard_clear()
        self.clipboard_append(url)
        self._show_success("OBS Overlay URL copied to clipboard!")

    # ------------------------------------------------------------------
    # Card 5: Danger Zone / Log Out & Reset All
    # ------------------------------------------------------------------
    def _build_danger_card(self):
        card = ctk.CTkFrame(self.scroll, fg_color="#181a22", corner_radius=14, border_width=1, border_color="#3B181E")
        card.pack(fill="x", pady=8)

        lbl = ctk.CTkLabel(
            card,
            text="⚠️ Account Management & Log Out",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#F87171"
        )
        lbl.pack(anchor="w", padx=16, pady=(12, 4))

        lbl_desc = ctk.CTkLabel(
            card,
            text="Disconnect your Spotify, Twitch, and TikTok credentials, clear tokens, and reset all settings.",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8"
        )
        lbl_desc.pack(anchor="w", padx=16, pady=(0, 10))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))

        btn_logout = ctk.CTkButton(
            btn_row,
            text="🚪 Log Out & Disconnect All Accounts",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#7F1D1D",
            hover_color="#991B1B",
            text_color="#FEE2E2",
            height=36,
            command=self._confirm_logout
        )
        btn_logout.pack(side="left")

    def _confirm_logout(self):
        modal = ctk.CTkToplevel(self)
        modal.title("Confirm Log Out")
        modal.geometry("450x270")
        modal.resizable(False, False)
        modal.configure(fg_color="#14151B")
        modal.transient(self)
        modal.grab_set()

        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 450) // 2
        y = self.winfo_y() + (self.winfo_height() - 270) // 2
        modal.geometry(f"+{max(0, x)}+{max(0, y)}")

        lbl_warn = ctk.CTkLabel(
            modal,
            text="⚠️ ARE YOU SURE?",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#EF4444"
        )
        lbl_warn.pack(pady=(22, 8))

        msg = (
            "This will disconnect your Spotify, Twitch, and TikTok accounts,\n"
            "clear cached authentication tokens (.cache-spotify),\n"
            "and reset your configuration file (config.json) to defaults.\n\n"
            "You will need to reconnect your accounts to use the bot again."
        )
        lbl_msg = ctk.CTkLabel(
            modal,
            text=msg,
            font=ctk.CTkFont(size=12),
            text_color="#CBD5E1",
            justify="center"
        )
        lbl_msg.pack(padx=20, pady=(0, 20))

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=24, pady=(0, 16))

        btn_cancel = ctk.CTkButton(
            btn_row,
            text="✖ Cancel",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#252836",
            hover_color="#32364a",
            width=130,
            height=38,
            command=modal.destroy
        )
        btn_cancel.pack(side="left", padx=(0, 10))

        def on_confirm():
            modal.destroy()
            self._perform_full_logout()

        btn_confirm = ctk.CTkButton(
            btn_row,
            text="🚪 Yes, Log Out Everything",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#DC2626",
            hover_color="#B91C1C",
            width=230,
            height=38,
            command=on_confirm
        )
        btn_confirm.pack(side="right")

    def _perform_full_logout(self):
        # 1. Reset ConfigManager & remove config.json
        self.config.reset()

        # 2. Delete Spotify cache files
        proj_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for cache_name in [".cache-spotify", ".cache"]:
            cp = os.path.join(proj_dir, cache_name)
            if os.path.exists(cp):
                try:
                    os.remove(cp)
                except Exception as e:
                    logger.warning(f"Could not remove {cp}: {e}")

        # 3. Stop loopback server if running
        if self.oauth_server:
            self.oauth_server.stop()
            self.oauth_server = None

        self.spotify_service = None

        # 4. Reset UI entries
        self.entry_client_id.delete(0, "end")
        self.entry_client_secret.delete(0, "end")
        self.entry_twitch_token.delete(0, "end")
        self.entry_twitch_channel.delete(0, "end")
        self.entry_twitch_client_id.delete(0, "end")
        self.entry_tiktok_user.delete(0, "end")

        self.unlimited_songs_var.set(False)
        self.entry_max_songs.configure(state="normal", fg_color=["#F9F9FA", "#343638"], text_color=["#000000", "#FFFFFF"])
        self.entry_max_songs.delete(0, "end")
        self.entry_max_songs.insert(0, "3")

        self.entry_cooldown.delete(0, "end")
        self.entry_cooldown.insert(0, "10")

        self.mode_var.set("Per Stream Session")

        self.playlist_dropdown.configure(values=["(Log in to view playlists)"])
        self.playlist_var.set("Select or create a playlist...")

        # 5. Reset status badges
        self.spotify_status.configure(
            text="⚠️ Not connected. Please authorize your Spotify account.",
            text_color="#FFB020"
        )
        self.btn_connect_spotify.configure(text="🟢 Connect Spotify Account")

        self.twitch_status.configure(
            text="⚪ Not connected to Twitch",
            text_color="#A0A5BA"
        )
        self.btn_connect_twitch.configure(text="🟣 Direct OAuth (Custom App)")

        # 6. Reset guides to closed by default
        if self._guide_visible:
            self._toggle_spotify_guide()
        if self._twitch_guide_visible:
            self._toggle_twitch_guide()

        self.enable_twitch_var.set(True)
        self.enable_tiktok_var.set(True)
        self._on_twitch_enable_toggle()
        self._on_tiktok_enable_toggle()

        self._show_success("Successfully logged out from all accounts and reset settings.")

    # ------------------------------------------------------------------
    # Save & Validation Logic
    # ------------------------------------------------------------------
    def _save_and_launch(self):
        # 1. Update config values
        enable_tw = self.enable_twitch_var.get()
        enable_tt = self.enable_tiktok_var.get()

        tw_chan = self.entry_twitch_channel.get().strip().lstrip("#")
        tw_tok = self.entry_twitch_token.get().strip()
        if tw_tok and not tw_tok.startswith("oauth:"):
            tw_tok = f"oauth:{tw_tok}"
        tt_user = self.entry_tiktok_user.get().strip().lstrip("@").lower()

        cid = self.entry_client_id.get().strip() or self.config.get("spotify_client_id")
        csecret = self.entry_client_secret.get().strip() or self.config.get("spotify_client_secret")
        tw_cid = self.entry_twitch_client_id.get().strip() or self.config.get("twitch_client_id")

        if self.unlimited_songs_var.get():
            max_songs = 0
        else:
            try:
                max_songs = int(self.entry_max_songs.get().strip())
            except ValueError:
                max_songs = 3

        try:
            cooldown = int(self.entry_cooldown.get().strip())
        except ValueError:
            cooldown = 10

        mode_str = self.mode_var.get()
        if "30" in mode_str:
            window_mins = 30
        elif "60" in mode_str:
            window_mins = 60
        else:
            window_mins = 0

        # If Twitch is enabled and channel was left empty but token is present, auto-resolve via validation
        if enable_tw and not tw_chan and tw_tok:
            try:
                ok, login, _, _ = validate_twitch_token(tw_tok)
                if ok and login:
                    tw_chan = login
                    self.entry_twitch_channel.delete(0, "end")
                    self.entry_twitch_channel.insert(0, login)
            except Exception as e:
                logger.warning(f"Could not auto-resolve channel from token: {e}")

        self.config.set("enable_twitch", enable_tw)
        self.config.set("enable_tiktok", enable_tt)
        self.config.set("spotify_client_id", cid)
        self.config.set("spotify_client_secret", csecret)
        self.config.set("twitch_client_id", tw_cid)
        self.config.set("twitch_channel", tw_chan)
        self.config.set("twitch_token", tw_tok)
        if tw_chan:
            self.config.set("twitch_nick", self.config.get("twitch_nick") or tw_chan)
        self.config.set("tiktok_username", tt_user)
        self.config.set("max_songs_per_user", max_songs)
        self.config.set("cooldown_seconds", cooldown)
        self.config.set("user_limit_window_minutes", window_mins)

        # 2. Validation
        if not self.config.get("spotify_playlist_id"):
            self._show_error("Please select or create a Spotify playlist above!")
            return

        if not enable_tw and not enable_tt:
            self._show_error("Please enable at least one platform: Twitch, TikTok, or both!")
            return

        if enable_tw and not tw_chan:
            self._show_error("Twitch is enabled, but no Twitch channel was provided or detected.")
            return

        if enable_tt and not tt_user:
            self._show_error("TikTok is enabled, but no TikTok username was provided.")
            return

        # 3. Save to disk
        self.config.save()
        logger.info("Configuration saved successfully!")

        if self.oauth_server:
            self.oauth_server.stop()

        self._show_success("Settings saved! Launching...")

        def proceed():
            self.destroy()
            if self.on_complete:
                self.on_complete()

        self.after(500, proceed)

    def _show_error(self, msg: str):
        self.lbl_status.configure(text=f"❌ {msg}", text_color="#FF4B4B")

    def _show_success(self, msg: str):
        self.lbl_status.configure(text=f"✅ {msg}", text_color="#1DB954")

if __name__ == "__main__":
    app = SetupWizard()
    app.mainloop()
