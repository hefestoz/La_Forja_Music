import asyncio
import logging
import sys
from dotenv import load_dotenv
from src.spotify_service import SpotifyService
from src.twitch_service import TwitchBot

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S"
)

async def main():
    print("========================================")
    print(" Twitch Chat Song Request Bot (Test)")
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
        bot = TwitchBot(spotify_service=spotify)
        print(f"[OK] Twitch configured -> Channel: #{bot.channel}")
        print("\nListening for chat commands:")
        print("   - !sr <song title, artist, or link>")
        print("   - !songrequest <song title, artist, or link>")
        print("\nPress Ctrl+C to exit.\n")
        await bot.start()
    except KeyboardInterrupt:
        print("\nStopping bot...")
        bot.stop()
    except Exception as e:
        print(f"\n[ERROR] Twitch bot failed: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
