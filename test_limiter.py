import time
from src.request_limiter import RequestLimiter

def test_per_stream_limit():
    print("Testing Per-Stream Limits (window_minutes = 0)...")
    limiter = RequestLimiter(max_songs_per_user=2, window_minutes=0, broadcaster_username="hefestoz")

    user = "chatter1"
    # First request
    allowed, msg = limiter.can_request("twitch", user)
    assert allowed, "1st request should be allowed"
    limiter.record_request("twitch", user)

    # Second request
    allowed, msg = limiter.can_request("twitch", user)
    assert allowed, "2nd request should be allowed"
    limiter.record_request("twitch", user)

    # Third request (should be blocked)
    allowed, msg = limiter.can_request("twitch", user)
    assert not allowed, "3rd request should be blocked"
    assert "limit of 2 song(s)" in msg
    print(f"  [OK] Block message: {msg}")

    # Another chatter should still be allowed
    allowed, _ = limiter.can_request("twitch", "chatter2")
    assert allowed, "Different chatter should not be blocked"
    print("  [OK] Separate chatters have independent quotas")

def test_broadcaster_bypass():
    print("\nTesting Broadcaster Bypass...")
    limiter = RequestLimiter(max_songs_per_user=1, window_minutes=0, broadcaster_username="hefestoz")

    for i in range(5):
        allowed, _ = limiter.can_request("twitch", "hefestoz")
        assert allowed, "Broadcaster should never be blocked"
        limiter.record_request("twitch", "hefestoz")
    print("  [OK] Broadcaster made 5 requests without being blocked")

def test_rolling_window():
    print("\nTesting Rolling Window Limits (window_minutes = 1)...")
    # 1-minute window, max 2 songs
    limiter = RequestLimiter(max_songs_per_user=2, window_minutes=1, broadcaster_username="hefestoz")
    user = "window_chatter"

    # Fill quota
    limiter.record_request("twitch", user)
    limiter.record_request("twitch", user)

    allowed, msg = limiter.can_request("twitch", user)
    assert not allowed, "Should be blocked when quota is full"
    print(f"  [OK] Block message: {msg}")

    # Artificially age the first timestamp to simulate time passage (> 60s ago)
    key = "twitch:window_chatter"
    limiter._history[key][0] = time.time() - 70

    allowed, _ = limiter.can_request("twitch", user)
    assert allowed, "Should be allowed after oldest request expires past window"
    print("  [OK] Quota unlocked after window elapsed")

def test_reset_limits():
    print("\nTesting Reset Limits...")
    limiter = RequestLimiter(max_songs_per_user=1, window_minutes=0, broadcaster_username="hefestoz")
    limiter.record_request("twitch", "chatterA")
    assert not limiter.can_request("twitch", "chatterA")[0]

    limiter.reset_limits()
    assert limiter.can_request("twitch", "chatterA")[0], "Should be allowed after global reset"
    print("  [OK] Global reset cleared all quotas")

def test_unlimited_mode():
    print("\nTesting Unlimited Mode (max_songs_per_user = 0)...")
    limiter = RequestLimiter(max_songs_per_user=0, window_minutes=0, broadcaster_username="hefestoz")
    for i in range(10):
        allowed, msg = limiter.can_request("twitch", "regular_chatter")
        assert allowed, "Unlimited mode should allow any number of requests"
        limiter.record_request("twitch", "regular_chatter")
    print("  [OK] Regular chatter made 10 requests without being blocked under Unlimited mode")

if __name__ == "__main__":
    print("========================================")
    print(" Running Request Limiter Unit Tests")
    print("========================================")
    test_per_stream_limit()
    test_broadcaster_bypass()
    test_rolling_window()
    test_reset_limits()
    test_unlimited_mode()
    print("\n[SUCCESS] ALL REQUEST LIMITER TESTS PASSED!")
