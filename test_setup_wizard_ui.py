import os
import unittest
from unittest.mock import MagicMock, patch
from src.config_manager import ConfigManager
from src.setup_wizard import SetupWizard

class TestSetupWizardUI(unittest.TestCase):
    def test_instruction_windows_closed_by_default(self):
        cm = ConfigManager()
        wizard = SetupWizard(config_manager=cm)
        wizard.withdraw()  # keep offscreen during automated test

        try:
            # Verify both instruction guides are CLOSED by default
            self.assertFalse(wizard._guide_visible, "Spotify instruction guide must be closed by default")
            self.assertFalse(wizard._twitch_guide_visible, "Twitch instruction guide must be closed by default")
            self.assertEqual(wizard.btn_spotify_guide.cget("text"), "❓ How to Get Spotify Keys")
            self.assertEqual(wizard.btn_twitch_guide.cget("text"), "❓ How to Connect Twitch")

            # Toggle Twitch guide ON
            wizard._toggle_twitch_guide()
            self.assertTrue(wizard._twitch_guide_visible)
            self.assertEqual(wizard.btn_twitch_guide.cget("text"), "✖ Close Guide")

            # Toggle Twitch guide OFF
            wizard._toggle_twitch_guide()
            self.assertFalse(wizard._twitch_guide_visible)
            self.assertEqual(wizard.btn_twitch_guide.cget("text"), "❓ How to Connect Twitch")

            # Toggle Spotify guide ON
            wizard._toggle_spotify_guide()
            self.assertTrue(wizard._guide_visible)
            self.assertEqual(wizard.btn_spotify_guide.cget("text"), "✖ Close Guide")

            # Toggle Spotify guide OFF
            wizard._toggle_spotify_guide()
            self.assertFalse(wizard._guide_visible)
            self.assertEqual(wizard.btn_spotify_guide.cget("text"), "❓ How to Get Spotify Keys")

        finally:
            wizard._on_close()

    def test_platform_toggle_switches(self):
        cm = ConfigManager()
        wizard = SetupWizard(config_manager=cm)
        wizard.withdraw()

        try:
            # Default state: both enabled
            self.assertTrue(wizard.enable_twitch_var.get())
            self.assertTrue(wizard.enable_tiktok_var.get())

            # Toggle Twitch off
            wizard.enable_twitch_var.set(False)
            wizard._on_twitch_enable_toggle()
            self.assertEqual(wizard.entry_twitch_token.cget("state"), "disabled")
            self.assertEqual(wizard.entry_twitch_channel.cget("state"), "disabled")
            self.assertEqual(wizard.btn_get_twitch_token.cget("state"), "disabled")
            self.assertIn("disabled", wizard.twitch_status.cget("text").lower())

            # Toggle Twitch back on
            wizard.enable_twitch_var.set(True)
            wizard._on_twitch_enable_toggle()
            self.assertEqual(wizard.entry_twitch_token.cget("state"), "normal")
            self.assertEqual(wizard.entry_twitch_channel.cget("state"), "normal")
            self.assertEqual(wizard.btn_get_twitch_token.cget("state"), "normal")

            # Toggle TikTok off
            wizard.enable_tiktok_var.set(False)
            wizard._on_tiktok_enable_toggle()
            self.assertEqual(wizard.entry_tiktok_user.cget("state"), "disabled")
            self.assertIn("disabled", wizard.tiktok_status.cget("text").lower())

            # Toggle TikTok back on
            wizard.enable_tiktok_var.set(True)
            wizard._on_tiktok_enable_toggle()
            self.assertEqual(wizard.entry_tiktok_user.cget("state"), "normal")

        finally:
            wizard._on_close()

    def test_miniapp_platform_status(self):
        from src.mini_app import MiniApp
        mock_spotify = MagicMock()
        mock_spotify.get_current_playback.return_value = None
        mock_spotify.get_recent_playlist_tracks.return_value = []
        mock_limiter = MagicMock()
        mock_limiter.get_stats.return_value = {"active_users": 0, "total_requests": 0, "max_songs": 3, "window_minutes": 0}

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            temp_path = tf.name

        try:
            cm = ConfigManager(config_path=temp_path)
            cm.set("spotify_playlist_id", "pl_test")
            cm.set("enable_twitch", True)
            cm.set("enable_tiktok", False)
            cm.set("twitch_channel", "hefestoz")
            cm.set("tiktok_username", "hefestoz")

            app = MiniApp(
                spotify_service=mock_spotify,
                request_limiter=mock_limiter,
                config_manager=cm
            )
            app.withdraw()

            try:
                self.assertEqual(app.twitch_status.cget("text"), "🟣 Twitch: #hefestoz")
                self.assertEqual(app.tiktok_status.cget("text"), "🔴 TikTok: (Disabled)")

                # Switch to TikTok-only
                cm.set("enable_twitch", False)
                cm.set("enable_tiktok", True)
                app.twitch_channel = "Disabled"
                app.tiktok_username = "hefestoz"
                app._update_connection_status()

                self.assertEqual(app.twitch_status.cget("text"), "🟣 Twitch: (Disabled)")
                self.assertEqual(app.tiktok_status.cget("text"), "🔴 TikTok: @hefestoz")
            finally:
                app.destroy()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_music_platform_segmented_button(self):
        cm = ConfigManager()
        wizard = SetupWizard(config_manager=cm)
        wizard.withdraw()

        try:
            self.assertIn(wizard.platform_var.get(), ["Spotify", "YouTube"])

            # Toggle to YouTube
            wizard.platform_var.set("YouTube")
            wizard._on_platform_changed("YouTube")
            self.assertTrue(bool(wizard.youtube_container.pack_info()))
            try:
                wizard.spotify_container.pack_info()
                spotify_packed = True
            except Exception:
                spotify_packed = False
            self.assertFalse(spotify_packed)

            # Toggle back to Spotify
            wizard.platform_var.set("Spotify")
            wizard._on_platform_changed("Spotify")
            self.assertTrue(bool(wizard.spotify_container.pack_info()))
            try:
                wizard.youtube_container.pack_info()
                youtube_packed = True
            except Exception:
                youtube_packed = False
            self.assertFalse(youtube_packed)
        finally:
            wizard._on_close()

    def test_twitch_1click_and_manual_accordion(self):
        cm = ConfigManager()
        wizard = SetupWizard(config_manager=cm)
        wizard.withdraw()

        try:
            # 1. Verify 1-click connect button exists and is labeled properly
            self.assertIn("Connect with Twitch", wizard.btn_connect_twitch.cget("text"))

            # 2. Verify manual token setup accordion is collapsed by default
            self.assertFalse(wizard._manual_twitch_visible)
            try:
                wizard.manual_twitch_frame.pack_info()
                manual_packed = True
            except Exception:
                manual_packed = False
            self.assertFalse(manual_packed)

            # 3. Toggle manual token setup accordion
            wizard._toggle_manual_twitch()
            self.assertTrue(wizard._manual_twitch_visible)
            self.assertTrue(bool(wizard.manual_twitch_frame.pack_info()))

            wizard._toggle_manual_twitch()
            self.assertFalse(wizard._manual_twitch_visible)

            # 4. Verify 1-click zero-key login initiates automated flow without invalid client ID error
            mock_create_resp = MagicMock()
            mock_create_resp.json.return_value = {
                "success": True,
                "id": "flow_abc123",
                "message": "https://twitchtokengenerator.com/api/flow_abc123"
            }
            mock_status_resp = MagicMock()
            mock_status_resp.json.return_value = {
                "success": True,
                "token": "oauth:mock_token_xyz"
            }

            with patch("src.setup_wizard.requests.get", side_effect=[mock_create_resp, mock_status_resp]) as mock_get, \
                 patch("src.setup_wizard.webbrowser.open") as mock_open, \
                 patch.object(wizard, "_handle_twitch_oauth_token") as mock_handle:
                wizard.entry_twitch_client_id.delete(0, "end")
                wizard.config.set("twitch_client_id", "")
                wizard._start_twitch_login()
                # Give worker thread a moment to start and call open
                import time
                time.sleep(0.3)
                mock_open.assert_called_once_with("https://twitchtokengenerator.com/api/flow_abc123")

            # 5. Verify custom client ID direct OAuth flow when supplied
            with patch("src.setup_wizard.webbrowser.open") as mock_custom_open:
                wizard.entry_twitch_client_id.delete(0, "end")
                wizard.entry_twitch_client_id.insert(0, "custom_client_id_999")
                wizard._start_twitch_login()
                mock_custom_open.assert_called_once()
                custom_url = mock_custom_open.call_args[0][0]
                self.assertIn("client_id=custom_client_id_999", custom_url)
                self.assertIn("127.0.0.1:8888/callback", custom_url)

        finally:
            wizard._on_close()

    def test_spotify_credentials_save_buttons(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            temp_path = tf.name

        try:
            cm = ConfigManager(config_path=temp_path)
            wizard = SetupWizard(config_manager=cm)
            wizard.withdraw()

            # 1. Verify developer save buttons exist
            self.assertTrue(hasattr(wizard, "btn_save_spotify_keys"))
            self.assertTrue(hasattr(wizard, "btn_save_keys_only"))
            self.assertEqual(wizard.btn_save_spotify_keys.cget("text"), "💾 Save Keys & Connect Spotify")
            self.assertEqual(wizard.btn_save_keys_only.cget("text"), "💾 Save Keys Only")

            # 2. Test empty credentials error
            wizard.entry_client_id.delete(0, "end")
            wizard.entry_client_secret.delete(0, "end")
            wizard._save_spotify_keys_only()
            self.assertIn("Please enter both Spotify Client ID", wizard.lbl_status.cget("text"))

            # 3. Test saving credentials directly
            wizard.entry_client_id.insert(0, "test_client_id_123")
            wizard.entry_client_secret.insert(0, "test_client_secret_456")
            wizard._save_spotify_keys_only()
            self.assertEqual(wizard.config.get("spotify_client_id"), "test_client_id_123")
            self.assertEqual(wizard.config.get("spotify_client_secret"), "test_client_secret_456")
            self.assertIn("saved", wizard.lbl_status.cget("text").lower())

            # 4. Test save and connect calls start_spotify_login
            with patch.object(wizard, "_start_spotify_login") as mock_login:
                wizard._save_and_connect_spotify()
                mock_login.assert_called_once()

            # 5. Verify footer btn_save is present
            self.assertTrue(hasattr(wizard, "btn_save"))
            self.assertIn("Save", wizard.btn_save.cget("text"))

        finally:
            if "wizard" in locals():
                wizard.destroy()
            if os.path.exists(temp_path):
                os.remove(temp_path)

if __name__ == "__main__":
    unittest.main()
