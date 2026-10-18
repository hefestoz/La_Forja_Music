import os
import json
import tempfile
from src.config_manager import ConfigManager

def test_config_defaults_and_override():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = tf.name

    try:
        # 1. Initialize empty
        cm = ConfigManager(config_path=temp_path)
        assert cm.get("max_songs_per_user") == 3
        assert cm.get("overlay_port") == 5000

        # 2. Set and Save
        cm.set("tiktok_username", "streamer_test")
        cm.set("twitch_client_id", "tw_client_999")
        cm.set("spotify_playlist_id", "playlist_123")
        cm.set("spotify_client_id", "client_abc")
        cm.set("spotify_client_secret", "secret_xyz")
        assert cm.save() is True

        # 3. Reload from disk
        cm2 = ConfigManager(config_path=temp_path)
        assert cm2.get("tiktok_username") == "streamer_test"
        assert cm2.get("twitch_client_id") == "tw_client_999"
        assert cm2.get("spotify_playlist_id") == "playlist_123"
        assert cm2.is_configured() is True

        # 4. Unlimited songs quota (value 0)
        cm2.set("max_songs_per_user", 0)
        assert cm2.get("max_songs_per_user") == 0
        assert cm2.save() is True

        # 5. Full Reset
        assert cm2.reset() is True
        assert not os.path.exists(temp_path)
        assert cm2.get("max_songs_per_user") == 3
        assert cm2.is_configured() is False
        print("[PASS] ConfigManager defaults, saving, reloading, unlimited quota, and reset verified!")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def test_platform_flexibility_configured():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = tf.name

    try:
        cm = ConfigManager(config_path=temp_path)
        cm.set("spotify_client_id", "cid_123")
        cm.set("spotify_client_secret", "sec_123")
        cm.set("spotify_playlist_id", "playlist_test")

        # Case 1: Both enabled, but no channels configured -> False
        cm.set("enable_twitch", True)
        cm.set("enable_tiktok", True)
        assert cm.is_configured() is False

        # Case 2: Twitch-only enabled & configured -> True
        cm.set("enable_twitch", True)
        cm.set("enable_tiktok", False)
        cm.set("twitch_channel", "hefestoz")
        assert cm.is_configured() is True

        # Case 3: TikTok-only enabled & configured -> True
        cm.set("enable_twitch", False)
        cm.set("enable_tiktok", True)
        cm.set("tiktok_username", "hefestoz")
        assert cm.is_configured() is True

        # Case 4: Both enabled and configured -> True
        cm.set("enable_twitch", True)
        cm.set("enable_tiktok", True)
        assert cm.is_configured() is True

        # Case 5: Both disabled -> False
        cm.set("enable_twitch", False)
        cm.set("enable_tiktok", False)
        assert cm.is_configured() is False

        print("[PASS] ConfigManager platform flexibility (Twitch-only, TikTok-only, Both, Neither) verified!")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    test_config_defaults_and_override()
    test_platform_flexibility_configured()
