import asyncio
import logging
import argparse
import sys
from dotenv import load_dotenv
from src.spotify_service import SpotifyService
from src.tiktok_service import TikTokListener

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S"
)

async def test_simulation(listener: TikTokListener):
    print("\n--- Running Simulation Test ---")
    test_cases = [
        ("tiktok_fan1", "!sr Radiohead Creep"),
        ("tiktok_fan2", "!sr https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"),
        ("tiktok_fan1", "!sr Daft Punk Around the World"),  # Should hit cooldown
        ("random_user", "Hola amigo como estas?"),         # Should ignore
        ("music_lover", "!songrequest Gorillaz Feel Good Inc")
    ]

    for user, text in test_cases:
        print(f"\n[Incoming Comment] @{user}: \"{text}\"")
        await listener.handle_comment(user, text)
        await asyncio.sleep(1)

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
