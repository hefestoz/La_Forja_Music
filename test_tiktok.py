import asyncio
import logging
import argparse
import sys
from dotenv import load_dotenv
from src.spotify_service import SpotifyService
from src.tiktok_service import TikTokListener

load_dotenv()

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S"
)

class MockTikTokUser:
    def __init__(self, unique_id=None, nick_name=None, user_id=None):
        self.unique_id = unique_id
        self.nick_name = nick_name
        self.user_id = user_id

def test_user_info_extraction(listener: TikTokListener):
    print("\n--- Testing TikTok User Info & Nickname Extraction ---")
    cases = [
        (MockTikTokUser("3564346218", "Juan Perez 🔥"), ("3564346218", "Juan Perez 🔥")),
        (MockTikTokUser("user987654321", "Sofia ✨"), ("user987654321", "Sofia ✨")),
        (MockTikTokUser("alex_rocker", "Alex R."), ("alex_rocker", "Alex R.")),
        (MockTikTokUser("alex_rocker", ""), ("alex_rocker", "@alex_rocker")),
        (MockTikTokUser("3564346218", None), ("3564346218", "TikTok Viewer")),
        (None, ("anonymous", "Anonymous")),
    ]

    for mock_u, (expected_id, expected_display) in cases:
        tid, dname = listener._extract_user_info(mock_u)
        assert tid == expected_id, f"Expected ID {expected_id}, got {tid}"
        assert dname == expected_display, f"Expected display name {expected_display}, got {dname}"
        print(f"  [PASS] ID: '{mock_u.unique_id if mock_u else 'None'}' + Nick: '{mock_u.nick_name if mock_u else 'None'}' -> Display: '{dname}', TrackID: '{tid}'")
    print("[OK] All user extraction tests passed!\n")

async def test_simulation(listener: TikTokListener):
    test_user_info_extraction(listener)

    print("--- Running Chat Simulation Test ---")
    test_cases = [
        ("3564346218", "Juan Perez 🔥", "!sr Radiohead Creep"),
        ("user987654321", "Sofia ✨", "!sr https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"),
        ("1234567890", "Random Chat", "Hola amigo como estas?"),  # Ignored non-sr comment
        ("quota_id_123", "Quota Tester", "!sr Michael Jackson Billie Jean"),
        ("quota_id_123", "Quota Tester", "!sr Queen Bohemian Rhapsody"),
        ("quota_id_123", "Quota Tester", "!sr AC/DC Back in Black"),
        ("quota_id_123", "Quota Tester", "!sr Led Zeppelin Stairway to Heaven"), # Exceeds limit
    ]

    for uid, display, text in test_cases:
        # Clear cooldown timestamp for test purposes
        listener._user_last_request[uid] = 0
        print(f"\n[Incoming Comment] {display} (ID: {uid}): \"{text}\"")
        await listener.handle_comment(uid, text, display_name=display)
        await asyncio.sleep(0.5)

    print("\n[OK] Simulation test completed!")

async def main():
    parser = argparse.ArgumentParser(description="Test TikTok Live Song Request Listener")
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Simulate TikTok comments without requiring an active live stream"
    )
    args = parser.parse_args()

    print("========================================")
    print(" TikTok Live Song Request Listener")
    print("========================================")

    try:
        spotify = SpotifyService(open_browser=False)
        if not spotify.is_authorized():
            print("[ERROR] Spotify is not authorized yet. Run authorize_spotify.py first.")
            sys.exit(1)
        print(f"[OK] Spotify ready -> Playlist: '{spotify.get_playlist_name()}'")
    except Exception as e:
        print(f"[ERROR] Failed to initialize SpotifyService: {e}")
        sys.exit(1)

    try:
        listener = TikTokListener(spotify_service=spotify)
        print(f"[OK] Configured for TikTok user: @{listener.unique_id}")

        if args.simulate:
            await test_simulation(listener)
        else:
            print("\nAttempting to connect to live stream...")
            print("Tip: Use '--simulate' if you are not currently streaming live.\n")
            await listener.start()
    except KeyboardInterrupt:
        print("\nStopping listener...")
        listener.stop()
    except Exception as e:
        print(f"\n[ERROR] TikTok listener failed: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
