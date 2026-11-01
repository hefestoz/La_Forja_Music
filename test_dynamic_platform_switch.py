import os
import unittest
from unittest.mock import MagicMock, patch

from src.config_manager import ConfigManager
from src.youtube_service import YouTubeService
from src.spotify_service import SpotifyService
from src.request_limiter import RequestLimiter
from src.embedded_player import EmbeddedPlayer, find_chromium_browser
from main import BotManager

class TestDynamicPlatformSwitch(unittest.TestCase):
    """
    Tests dynamic switching between Spotify and YouTube services,
    ensuring all bot components (TwitchBot, OverlayServer, MiniApp)
    immediately update their music backend references, and that
    YouTube song reproduction works seamlessly.
    """

    def setUp(self):
        self.config = ConfigManager()
        self.config.set("music_platform", "spotify")
        self.config.set("spotify_client_id", "mock_spotify_client_id")
        self.config.set("spotify_client_secret", "mock_spotify_client_secret")
        self.config.set("twitch_channel", "test_channel")
        self.config.set("twitch_token", "oauth:fake")
        self.config.set("enable_twitch", True)
        self.config.set("enable_tiktok", False)
        self.config.set("overlay_port", 5001)

    @patch("src.spotify_service.SpotifyService.is_authorized", return_value=True)
    def test_manager_dynamic_switch_to_youtube_and_back(self, mock_auth):
        manager = BotManager(config=self.config)
        manager.initialize()

        # Initially Spotify
        self.assertIsInstance(manager.spotify, SpotifyService)
        self.assertIs(manager.twitch_bot.spotify, manager.spotify)
        self.assertIs(manager.overlay_server.spotify, manager.spotify)

        # Switch to YouTube
        yt_service = manager.switch_music_service("youtube")
        self.assertIsInstance(yt_service, YouTubeService)
        self.assertIs(manager.spotify, yt_service)
        self.assertIs(manager.twitch_bot.spotify, yt_service)
        self.assertIs(manager.overlay_server.spotify, yt_service)

        # Switch back to Spotify
        sp_service = manager.switch_music_service("spotify")
        self.assertIsInstance(sp_service, SpotifyService)
        self.assertIs(manager.spotify, sp_service)
        self.assertIs(manager.twitch_bot.spotify, sp_service)
        self.assertIs(manager.overlay_server.spotify, sp_service)

    @patch("src.spotify_service.SpotifyService.is_authorized", return_value=True)
    def test_twitch_bot_uses_swapped_youtube_service(self, mock_auth):
        """
        Verifies that after switching to YouTube, the TwitchBot's music service
        is YouTubeService and calling add_song_request routes directly to YouTube.
        """
        manager = BotManager(config=self.config)
        manager.initialize()

        # Switch to YouTube
        manager.switch_music_service("youtube")
        yt_service = manager.twitch_bot.spotify
        self.assertIsInstance(yt_service, YouTubeService)

        # Add song request to the swapped service
        with patch.object(yt_service, "search_track") as mock_search:
            mock_search.return_value = {
                "id": "dQw4w9WgXcQ",
                "uri": "youtube:video:dQw4w9WgXcQ",
                "name": "Never Gonna Give You Up",
                "artists": ["Rick Astley"],
                "artist_str": "Rick Astley",
                "album_name": "YouTube",
                "album_art": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                "duration_ms": 212000,
                "external_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            }
            ok, msg, track = manager.twitch_bot.spotify.add_song_request(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                requested_by="cool_viewer"
            )

        self.assertTrue(ok)
        self.assertIn("Never Gonna Give You Up", msg)
        self.assertEqual(track["id"], "dQw4w9WgXcQ")

        # Verify currently playing is now the YouTube track
        curr = manager.twitch_bot.spotify.get_currently_playing()
        self.assertIsNotNone(curr)
        self.assertEqual(curr["id"], "dQw4w9WgXcQ")
        self.assertEqual(curr["requested_by"], "cool_viewer")
        self.assertTrue(curr["is_playing"])

    def test_find_chromium_browser(self):
        """Verifies that an Edge/Chrome executable is located on Windows."""
        path = find_chromium_browser()
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))

    def test_youtube_queue_advancement_logic(self):
        """Tests that YouTube queue advances to next track and does not repeat track 1."""
        yt = YouTubeService()
        
        # Add Song 1
        with patch.object(yt, "search_track") as mock_search:
            mock_search.return_value = {
                "id": "vid_111",
                "uri": "youtube:video:vid_111",
                "name": "Song 1",
                "artists": ["Artist 1"],
                "artist_str": "Artist 1",
                "album_name": "YouTube",
                "album_art": "https://i.ytimg.com/vi/vid_111/hqdefault.jpg",
                "duration_ms": 180000,
                "external_url": "https://www.youtube.com/watch?v=vid_111"
            }
            yt.add_song_request("Song 1", requested_by="User1")

            # Add Song 2
            mock_search.return_value = {
                "id": "vid_222",
                "uri": "youtube:video:vid_222",
                "name": "Song 2",
                "artists": ["Artist 2"],
                "artist_str": "Artist 2",
                "album_name": "YouTube",
                "album_art": "https://i.ytimg.com/vi/vid_222/hqdefault.jpg",
                "duration_ms": 200000,
                "external_url": "https://www.youtube.com/watch?v=vid_222"
            }
            yt.add_song_request("Song 2", requested_by="User2")

        # Active is Song 1, Pending is Song 2
        self.assertEqual(yt.get_currently_playing()["id"], "vid_111")
        self.assertEqual(len(yt.get_queue()), 1)
        self.assertEqual(yt.get_queue()[0]["id"], "vid_222")

        # Skip Song 1 -> Song 2 plays
        self.assertTrue(yt.next_track())
        self.assertEqual(yt.get_currently_playing()["id"], "vid_222")
        self.assertEqual(len(yt.get_queue()), 0)

        # Skip Song 2 -> Queue empty
        self.assertFalse(yt.next_track())
        self.assertIsNone(yt.get_currently_playing())

    def test_embedded_player_ui_state(self):
        """Tests EmbeddedPlayer controls and state without launching external browser."""
        import customtkinter as ctk
        root = ctk.CTk()
        root.withdraw()
        player = EmbeddedPlayer(root, overlay_port=5001)

        with patch.object(player, "start_player") as mock_start:
            player.load_video("test_vid_123", title="Lo-Fi Beats", artist="ChilledCow")
            mock_start.assert_called_once_with(video_id="test_vid_123")

        self.assertEqual(player.current_video_id, "test_vid_123")
        self.assertEqual(player.track_lbl.cget("text"), "Lo-Fi Beats")
        self.assertEqual(player.status_badge.cget("text"), "▶ Playing")

        player.pause()
        self.assertEqual(player.status_badge.cget("text"), "⏸ Paused")

        player.play()
        self.assertEqual(player.status_badge.cget("text"), "▶ Playing")

        player.stop()
        self.assertIsNone(player.current_video_id)
        self.assertEqual(player.status_badge.cget("text"), "● Idle")
        root.destroy()

    def test_settings_modal_is_toplevel_and_not_root(self):
        """Verifies that SettingsModal inherits from CTkToplevel to prevent freezing MiniApp."""
        import customtkinter as ctk
        from src.setup_wizard import SettingsModal, SetupWizard

        self.assertTrue(issubclass(SettingsModal, ctk.CTkToplevel))
        self.assertFalse(issubclass(SettingsModal, ctk.CTk))
        self.assertTrue(issubclass(SetupWizard, ctk.CTk))

    def test_spotify_toggle_playback_device_fallback(self):
        """Verifies that Spotify toggle_playback wakes up available devices when no active session."""
        sp_service = SpotifyService(
            client_id="dummy_cid",
            client_secret="dummy_secret",
            redirect_uri="http://127.0.0.1:8888/callback",
            open_browser=False
        )

        mock_sp = MagicMock()
        mock_sp.current_playback.return_value = None
        # First call without device_id fails
        from spotipy.exceptions import SpotifyException
        def fake_start(*args, **kwargs):
            if not kwargs.get("device_id"):
                raise SpotifyException(404, "No active device")
            return None
        mock_sp.start_playback.side_effect = fake_start
        mock_sp.devices.return_value = {"devices": [{"id": "dev_pc_1", "name": "Desktop PC"}]}
        sp_service.sp = mock_sp

        ok = sp_service.toggle_playback()
        self.assertTrue(ok)
        mock_sp.start_playback.assert_called_with(device_id="dev_pc_1")

    @patch("src.embedded_player.EmbeddedPlayer.start_player")
    def test_miniapp_platform_badge_and_toggle(self, mock_start):
        """Verifies that MiniApp platform badge and embedded player adapt to Spotify and YouTube."""
        import customtkinter as ctk
        from src.mini_app import MiniApp

        mock_spotify = MagicMock()
        mock_spotify.service_type = "spotify"
        mock_spotify.get_currently_playing.return_value = None
        mock_spotify.get_recent_requests.return_value = []

        limiter = MagicMock()
        app = MiniApp(
            spotify_service=mock_spotify,
            request_limiter=limiter,
            config_manager=self.config
        )
        app.withdraw()

        def is_packed(widget):
            try:
                return bool(widget.pack_info())
            except Exception:
                return False

        try:
            # Starts in Spotify mode
            self.assertEqual(app.service_type, "spotify")
            self.assertIn("Spotify", app.platform_badge.cget("text"))

            # Switch to YouTube
            app.service_type = "youtube"
            app._update_platform_ui()
            self.assertIn("YouTube", app.platform_badge.cget("text"))
            self.assertTrue(is_packed(app.embedded_player))
            self.assertTrue(is_packed(app.video_toggle_btn))

            # Test toggling video panel inside the app
            app._toggle_video_panel()
            self.assertFalse(is_packed(app.embedded_player))
            self.assertIn("Show", app.video_toggle_btn.cget("text"))

            app._toggle_video_panel()
            self.assertTrue(is_packed(app.embedded_player))
            self.assertIn("Hide", app.video_toggle_btn.cget("text"))

            # Switch back to Spotify
            app.service_type = "spotify"
            app._update_platform_ui()
            self.assertIn("Spotify", app.platform_badge.cget("text"))
            self.assertFalse(is_packed(app.embedded_player))
            self.assertFalse(is_packed(app.video_toggle_btn))
            self.assertEqual(app.title_lbl.cget("text"), "Waiting for Spotify...")

        finally:
            app.destroy()

if __name__ == "__main__":
    unittest.main()
