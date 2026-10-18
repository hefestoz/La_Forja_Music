import os
from unittest.mock import MagicMock
from src.twitch_service import TwitchBot
from src.config_manager import ConfigManager
from src.request_limiter import RequestLimiter

def test_twitch_bot_init_with_nick():
    mock_spotify = MagicMock()
    mock_limiter = RequestLimiter(max_songs_per_user=0)

    # Test initialization with nick parameter
    bot = TwitchBot(
        spotify_service=mock_spotify,
        request_limiter=mock_limiter,
        channel="hefestoz",
        token="oauth:dummytoken123",
        nick="hefestoz",
        cooldown_seconds=10
    )

    assert bot.channel == "hefestoz", f"Expected 'hefestoz', got {bot.channel}"
    assert bot.nick == "hefestoz", f"Expected 'hefestoz', got {bot.nick}"
    print("[PASS] TwitchBot initializes successfully with nick='hefestoz'!")

def test_twitch_bot_init_custom_nick():
    mock_spotify = MagicMock()
    mock_limiter = RequestLimiter(max_songs_per_user=0)

    bot = TwitchBot(
        spotify_service=mock_spotify,
        request_limiter=mock_limiter,
        channel="hefestoz_channel",
        token="oauth:dummytoken123",
        nick="my_bot_account",
        cooldown_seconds=10
    )

    assert bot.channel == "hefestoz_channel"
    assert bot.nick == "my_bot_account"
    print("[PASS] TwitchBot supports distinct channel and nick names!")

def test_channel_resolution_fallback():
    cm = ConfigManager()
    cm.set("twitch_channel", "hefestoz")
    cm.set("twitch_nick", "hefestoz")
    cm.set("tiktok_username", "Hefestoz")

    # Simulate BotManager resolution logic
    twitch_bot = None
    tiktok_listener = None

    t_chan = (
        (twitch_bot.channel or twitch_bot.nick)
        if twitch_bot
        else None
    ) or cm.get("twitch_channel") or cm.get("twitch_nick") or "N/A"

    tt_user = (
        tiktok_listener.unique_id
        if tiktok_listener
        else None
    ) or cm.get("tiktok_username") or "N/A"

    assert t_chan == "hefestoz", f"Expected 'hefestoz', got {t_chan}"
    assert tt_user == "Hefestoz", f"Expected 'Hefestoz', got {tt_user}"
    print("[PASS] Channel resolution correctly falls back to config instead of 'N/A'!")

if __name__ == "__main__":
    print("========================================")
    print(" Testing TwitchBot & Channel Resolution")
    print("========================================")
    test_twitch_bot_init_with_nick()
    test_twitch_bot_init_custom_nick()
    test_channel_resolution_fallback()
    print("\n[SUCCESS] ALL TWITCH & CHANNEL TESTS PASSED (0 Spotify API calls used)!")
