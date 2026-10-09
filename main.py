import asyncio
import logging
import signal
import sys
from dotenv import load_dotenv
from src.spotify_service import SpotifyService
from src.twitch_service import TwitchBot
from src.tiktok_service import TikTokListener

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("MusicBot")

async def main():
    print("==========================================================")
    print("        LA FORJA MUSIC BOT - TWITCH & TIKTOK TO SPOTIFY   ")
    print("==========================================================")

    # 1. Initialize Spotify
    try:
        spotify = SpotifyService(open_browser=False)
        if not spotify.is_authorized():
            print("\n[ERROR] Spotify is not authorized yet.")
            print("Please run: .\\.venv\\Scripts\\python authorize_spotify.py")
            sys.exit(1)
        playlist_name = spotify.get_playlist_name()
        print(f"[OK] Spotify Connected -> Playlist: '{playlist_name}'")
    except Exception as e:
        logger.critical(f"Spotify initialization failed: {e}")
        sys.exit(1)

    # 2. Initialize Twitch Bot
    try:
        twitch_bot = TwitchBot(spotify_service=spotify)
        print(f"[OK] Twitch Configured  -> Channel: #{twitch_bot.channel}")
    except Exception as e:
        logger.error(f"Failed to initialize Twitch bot: {e}")
        twitch_bot = None

    # 3. Initialize TikTok Listener
    try:
        tiktok_listener = TikTokListener(spotify_service=spotify)
        print(f"[OK] TikTok Configured  -> Streamer: @{tiktok_listener.unique_id}")
    except Exception as e:
        logger.error(f"Failed to initialize TikTok listener: {e}")
        tiktok_listener = None

    if not twitch_bot and not tiktok_listener:
        logger.critical("Neither Twitch nor TikTok could be initialized. Exiting.")
        sys.exit(1)

    print("\n----------------------------------------------------------")
    print(" Active Commands in Chat:")
    print("   !sr <song title, artist, or Spotify link>")
    print("   !songrequest <song title, artist, or Spotify link>")
    print(" Press Ctrl+C at any time to safely shut down.")
    print("----------------------------------------------------------\n")

    # 4. Run listeners concurrently
    tasks = []
    if twitch_bot:
        tasks.append(asyncio.create_task(twitch_bot.start()))
    if tiktok_listener:
        tasks.append(asyncio.create_task(tiktok_listener.start()))

    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutdown requested...")
    finally:
        logger.info("Stopping services...")
        if twitch_bot:
            twitch_bot.stop()
        if tiktok_listener:
            tiktok_listener.stop()
        logger.info("All services safely stopped. Goodbye!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot exited by user.")
