import os
from unittest.mock import MagicMock
from src.config_manager import ConfigManager
from src.setup_wizard import SetupWizard

def test_instruction_windows_closed_by_default():
    cm = ConfigManager()
    wizard = SetupWizard(config_manager=cm)
    wizard.withdraw()  # keep offscreen during automated test

    try:
        # Verify both instruction guides are CLOSED by default
        assert wizard._guide_visible is False, "Spotify instruction guide must be closed by default"
        assert wizard._twitch_guide_visible is False, "Twitch instruction guide must be closed by default"
        assert wizard.btn_spotify_guide.cget("text") == "❓ How to Get Spotify Keys"
        assert wizard.btn_twitch_guide.cget("text") == "❓ How to Connect Twitch"
        print("[PASS] Both Spotify and Twitch instruction panels are closed by default!")

        # Toggle Twitch guide ON
        wizard._toggle_twitch_guide()
        assert wizard._twitch_guide_visible is True
        assert wizard.btn_twitch_guide.cget("text") == "✖ Close Guide"
        print("[PASS] Twitch instruction guide expands on button click!")

        # Toggle Twitch guide OFF
        wizard._toggle_twitch_guide()
        assert wizard._twitch_guide_visible is False
        assert wizard.btn_twitch_guide.cget("text") == "❓ How to Connect Twitch"
        print("[PASS] Twitch instruction guide collapses on second click!")

        # Toggle Spotify guide ON
        wizard._toggle_spotify_guide()
        assert wizard._guide_visible is True
        assert wizard.btn_spotify_guide.cget("text") == "✖ Close Guide"
        print("[PASS] Spotify instruction guide expands on button click!")

        # Toggle Spotify guide OFF
        wizard._toggle_spotify_guide()
        assert wizard._guide_visible is False
        assert wizard.btn_spotify_guide.cget("text") == "❓ How to Get Spotify Keys"
        print("[PASS] Spotify instruction guide collapses on second click!")

    finally:
        wizard.destroy()

def test_platform_toggle_switches():
    cm = ConfigManager()
    wizard = SetupWizard(config_manager=cm)
    wizard.withdraw()

    try:
        # Default state: both enabled
        assert wizard.enable_twitch_var.get() is True
        assert wizard.enable_tiktok_var.get() is True
        print("[PASS] Both Twitch and TikTok default to enabled in SetupWizard!")

        # Toggle Twitch off
        wizard.enable_twitch_var.set(False)
        wizard._on_twitch_enable_toggle()
        assert wizard.entry_twitch_token.cget("state") == "disabled"
        assert wizard.entry_twitch_channel.cget("state") == "disabled"
        assert wizard.btn_get_twitch_token.cget("state") == "disabled"
        assert "disabled" in wizard.twitch_status.cget("text").lower()
        print("[PASS] Disabling Twitch switches fields to disabled state with clear status label!")

        # Toggle Twitch back on
        wizard.enable_twitch_var.set(True)
        wizard._on_twitch_enable_toggle()
        assert wizard.entry_twitch_token.cget("state") == "normal"
        assert wizard.entry_twitch_channel.cget("state") == "normal"
        assert wizard.btn_get_twitch_token.cget("state") == "normal"
        print("[PASS] Re-enabling Twitch restores input fields to normal!")

        # Toggle TikTok off
        wizard.enable_tiktok_var.set(False)
        wizard._on_tiktok_enable_toggle()
        assert wizard.entry_tiktok_user.cget("state") == "disabled"
        assert "disabled" in wizard.tiktok_status.cget("text").lower()
        print("[PASS] Disabling TikTok disables username field with clear status label!")

        # Toggle TikTok back on
        wizard.enable_tiktok_var.set(True)
        wizard._on_tiktok_enable_toggle()
        assert wizard.entry_tiktok_user.cget("state") == "normal"
        print("[PASS] Re-enabling TikTok restores username field to normal!")

    finally:
        wizard.destroy()

def test_miniapp_platform_status():
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
            assert app.twitch_status.cget("text") == "🟣 Twitch: #hefestoz"
            assert app.tiktok_status.cget("text") == "🔴 TikTok: (Disabled)"
            print("[PASS] MiniApp correctly displays Twitch connected and TikTok: (Disabled)!")

            # Switch to TikTok-only
            cm.set("enable_twitch", False)
            cm.set("enable_tiktok", True)
            app.twitch_channel = "Disabled"
            app.tiktok_username = "hefestoz"
            app._update_connection_status()

            assert app.twitch_status.cget("text") == "🟣 Twitch: (Disabled)"
            assert app.tiktok_status.cget("text") == "🔴 TikTok: @hefestoz"
            print("[PASS] MiniApp dynamically switches to Twitch: (Disabled) and TikTok connected!")
        finally:
            app.destroy()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    print("========================================")
    print(" Testing Setup Wizard & MiniApp UI")
    print("========================================")
    test_instruction_windows_closed_by_default()
    test_platform_toggle_switches()
    test_miniapp_platform_status()
    print("\n[SUCCESS] ALL PLATFORM FLEXIBILITY & UI TESTS PASSED (0 Spotify API calls used)!")
