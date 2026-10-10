import sys
import asyncio
import logging
import argparse
import threading
from dotenv import load_dotenv

from src.spotify_service import SpotifyService
from src.request_limiter import RequestLimiter
from src.twitch_service import TwitchBot
from src.tiktok_service import TikTokListener
from src.overlay_server import OverlayServer

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("MusicBot")

class BotManager:
    """Orchestrates all background streaming bot services."""

    def __init__(self):
        self.spotify: SpotifyService = None
        self.limiter: RequestLimiter = None
        self.twitch_bot: TwitchBot = None
        self.tiktok_listener: TikTokListener = None
        self.overlay_server: OverlayServer = None
        self.loop: asyncio.AbstractEventLoop = None
        self._thread: threading.Thread = None

    def initialize(self):
        # 1. Limiter
        self.limiter = RequestLimiter()

        # 2. Spotify
        self.spotify = SpotifyService(open_browser=False)
        if not self.spotify.is_authorized():
            print("\n[ERROR] Spotify is not authorized yet.")
            print("Please run: .\\.venv\\Scripts\\python authorize_spotify.py")
            sys.exit(1)

        # 3. Twitch
        try:
            self.twitch_bot = TwitchBot(spotify_service=self.spotify, request_limiter=self.limiter)
        except Exception as e:
            logger.error(f"Twitch bot initialization failed: {e}")

        # 4. TikTok
        try:
            self.tiktok_listener = TikTokListener(spotify_service=self.spotify, request_limiter=self.limiter)
        except Exception as e:
            logger.error(f"TikTok listener initialization failed: {e}")

        # 5. OBS Overlay Server
        try:
            self.overlay_server = OverlayServer(spotify_service=self.spotify, port=5000)
        except Exception as e:
            logger.error(f"Overlay server initialization failed: {e}")

    async def _run_async_services(self):
        tasks = []
        if self.overlay_server:
            await self.overlay_server.start()
        if self.twitch_bot:
            tasks.append(asyncio.create_task(self.twitch_bot.start()))
        if self.tiktok_listener:
            tasks.append(asyncio.create_task(self.tiktok_listener.start()))

        await asyncio.gather(*tasks)

    def start_background(self):
        """Starts the async services inside a background thread."""
        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self._run_async_services())
            except Exception as e:
                logger.debug(f"Async loop finished: {e}")

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stops all running bot components."""
        logger.info("Stopping all bot components...")
        if self.twitch_bot:
            self.twitch_bot.stop()
        if self.tiktok_listener:
            self.tiktok_listener.stop()
        if self.overlay_server and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.overlay_server.stop(), self.loop)

def print_banner(manager: BotManager):
    print("==========================================================")
    print("        LA FORJA MUSIC BOT - TWITCH & TIKTOK TO SPOTIFY   ")
    print("==========================================================")
    
    lim = manager.limiter
    if lim.max_songs <= 0:
        desc = "Unlimited"
    elif lim.window_minutes > 0:
        desc = f"Max {lim.max_songs} songs per {lim.window_minutes} minutes"
    else:
        desc = f"Max {lim.max_songs} songs per stream session"
    print(f"[OK] Quota Policy        -> {desc}")

    p_name = manager.spotify.get_playlist_name()
    print(f"[OK] Spotify Playlist    -> '{p_name}'")

    if manager.twitch_bot:
        print(f"[OK] Twitch Channel      -> #{manager.twitch_bot.channel}")
    if manager.tiktok_listener:
        print(f"[OK] TikTok Streamer     -> @{manager.tiktok_listener.unique_id}")
    if manager.overlay_server:
        print(f"[OK] OBS Browser Source  -> http://localhost:5000/overlay")

    print("\n----------------------------------------------------------")
    print(" Active Commands in Chat:")
    print("   !sr <song title, artist, or Spotify link>")
    print("   !songrequest <song title, artist, or Spotify link>")
    print("   !myrequests (check your quota)")
    print("   !resetrequests (broadcaster: reset all quotas)")
    print("----------------------------------------------------------\n")

def main():
    parser = argparse.ArgumentParser(description="La Forja Music Bot")
    parser.add_argument("--no-gui", action="store_true", help="Run without Desktop Mini-App GUI")
    args = parser.parse_args()

    manager = BotManager()
    manager.initialize()
    print_banner(manager)

    # If GUI is requested (default)
    if not args.no_gui:
        try:
            from src.mini_app import MiniApp
            manager.start_background()

            t_chan = manager.twitch_bot.channel if manager.twitch_bot else "N/A"
            tt_user = manager.tiktok_listener.unique_id if manager.tiktok_listener else "N/A"

            app = MiniApp(
                spotify_service=manager.spotify,
                request_limiter=manager.limiter,
                twitch_channel=t_chan,
                tiktok_username=tt_user
            )

            def on_close():
                manager.stop()
                app.destroy()
                sys.exit(0)

            app.protocol("WM_DELETE_WINDOW", on_close)
            logger.info("Opening Desktop Mini-App Controller...")
            app.mainloop()

        except Exception as e:
            logger.warning(f"Failed to launch GUI ({e}). Falling back to terminal mode.")
            args.no_gui = True

    # Terminal / Headless mode
    if args.no_gui:
        print("Running in headless terminal mode. Press Ctrl+C to exit.")
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(manager._run_async_services())
        except KeyboardInterrupt:
            manager.stop()
            print("\nBot exited by user.")

if __name__ == "__main__":
    main()
