import sys
import os
import subprocess

# Auto-switch to virtual environment interpreter if run from global python
_proj_dir = os.path.dirname(os.path.abspath(__file__))
_venv_python = (
    os.path.join(_proj_dir, ".venv", "Scripts", "python.exe")
    if os.name == "nt"
    else os.path.join(_proj_dir, ".venv", "bin", "python")
)
if os.path.exists(_venv_python) and os.path.abspath(sys.executable).lower() != os.path.abspath(_venv_python).lower():
    try:
        sys.exit(subprocess.call([_venv_python] + sys.argv))
    except Exception as _e:
        print(f"[Warning] Failed to re-spawn in .venv: {_e}", file=sys.stderr)

import asyncio
import logging
import argparse
import threading
from typing import Optional
from dotenv import load_dotenv

from src.config_manager import ConfigManager
from src.spotify_service import SpotifyService
from src.request_limiter import RequestLimiter
from src.twitch_service import TwitchBot
from src.tiktok_service import TikTokListener
from src.overlay_server import OverlayServer
from src.setup_wizard import SetupWizard

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("MusicBot")

class BotManager:
    """Orchestrates all background streaming bot services."""

    def __init__(self, config: Optional[ConfigManager] = None):
        self.config = config or ConfigManager()
        self.spotify: SpotifyService = None
        self.limiter: RequestLimiter = None
        self.twitch_bot: TwitchBot = None
        self.tiktok_listener: TikTokListener = None
        self.overlay_server: OverlayServer = None
        self.loop: asyncio.AbstractEventLoop = None
        self._thread: threading.Thread = None
        self._stop_event: Optional[asyncio.Event] = None

    def initialize(self):
        # 1. Limiter
        tw_chan = self.config.get("twitch_channel", "")
        tt_user = self.config.get("tiktok_username", "")
        enable_tw = self.config.get("enable_twitch", True)
        enable_tt = self.config.get("enable_tiktok", True)
        broadcaster = (tw_chan if enable_tw else "") or (tt_user if enable_tt else "")

        max_tw = self.config.get("max_songs_per_user_twitch")
        if max_tw is None:
            max_tw = self.config.get("max_songs_per_user", 3)
        max_tt = self.config.get("max_songs_per_user_tiktok")
        if max_tt is None:
            max_tt = self.config.get("max_songs_per_user", 3)

        self.limiter = RequestLimiter(
            max_songs_per_user=self.config.get("max_songs_per_user", 3),
            window_minutes=self.config.get("user_limit_window_minutes", 0),
            broadcaster_username=broadcaster,
            max_songs_twitch=max_tw,
            max_songs_tiktok=max_tt
        )

        # 2. Music Service (Spotify or YouTube)
        music_platform = self.config.get("music_platform", "spotify")
        if music_platform == "youtube":
            from src.youtube_service import YouTubeService
            self.spotify = YouTubeService(
                initial_playlist=self.config.get("youtube_initial_playlist"),
                music_only=self.config.get("youtube_music_only", True),
                max_duration_seconds=self.config.get("youtube_max_duration_seconds", 600)
            )
            logger.info("Initialized YouTube In-App Music Service (No-Login Mode).")
        else:
            self.spotify = SpotifyService(
                client_id=self.config.get("spotify_client_id"),
                client_secret=self.config.get("spotify_client_secret"),
                redirect_uri=self.config.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback"),
                playlist_id=self.config.get("spotify_playlist_id"),
                open_browser=False
            )
            if not self.spotify.is_authorized():
                # Launch GUI Setup Wizard automatically so the streamer can connect or switch to YouTube
                try:
                    logger.warning("Spotify is selected but not authorized. Launching Setup Wizard...")
                    wizard = SetupWizard(config_manager=self.config)
                    wizard.mainloop()
                    self.config.load()
                    if self.config.get("music_platform") == "youtube":
                        from src.youtube_service import YouTubeService
                        self.spotify = YouTubeService(
                            initial_playlist=self.config.get("youtube_initial_playlist"),
                            music_only=self.config.get("youtube_music_only", True),
                            max_duration_seconds=self.config.get("youtube_max_duration_seconds", 600)
                        )
                        logger.info("Initialized YouTube In-App Music Service (No-Login Mode).")
                    else:
                        self.spotify = SpotifyService(
                            client_id=self.config.get("spotify_client_id"),
                            client_secret=self.config.get("spotify_client_secret"),
                            redirect_uri=self.config.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback"),
                            playlist_id=self.config.get("spotify_playlist_id"),
                            open_browser=False
                        )
                except Exception as e:
                    logger.error(f"Could not open Setup Wizard: {e}")

                if getattr(self.spotify, "service_type", None) != "youtube" and not self.spotify.is_authorized():
                    print("\n[INFO] Spotify is not authorized yet. Launching with YouTube No-Login mode as fallback.")
                    from src.youtube_service import YouTubeService
                    self.spotify = YouTubeService(
                        initial_playlist=self.config.get("youtube_initial_playlist"),
                        music_only=self.config.get("youtube_music_only", True),
                        max_duration_seconds=self.config.get("youtube_max_duration_seconds", 600)
                    )

        # 3. Twitch
        if enable_tw and tw_chan:
            try:
                self.twitch_bot = TwitchBot(
                    spotify_service=self.spotify,
                    request_limiter=self.limiter,
                    channel=tw_chan,
                    token=self.config.get("twitch_token"),
                    nick=self.config.get("twitch_nick") or tw_chan,
                    cooldown_seconds=self.config.get("cooldown_seconds", 10)
                )
            except Exception as e:
                logger.error(f"Twitch bot initialization failed: {e}")

        # 4. TikTok
        if enable_tt and tt_user:
            try:
                self.tiktok_listener = TikTokListener(
                    spotify_service=self.spotify,
                    request_limiter=self.limiter,
                    unique_id=tt_user,
                    cooldown_seconds=self.config.get("cooldown_seconds", 10)
                )
            except Exception as e:
                logger.error(f"TikTok listener initialization failed: {e}")

        # 5. OBS Overlay Server
        try:
            self.overlay_server = OverlayServer(
                spotify_service=self.spotify,
                port=self.config.get("overlay_port", 5000)
            )
        except Exception as e:
            logger.error(f"Overlay server initialization failed: {e}")

    async def _run_async_services(self):
        self._stop_event = asyncio.Event()
        if self.overlay_server:
            await self.overlay_server.start()
        if self.twitch_bot:
            asyncio.create_task(self.twitch_bot.start())
        if self.tiktok_listener:
            asyncio.create_task(self.tiktok_listener.start())

        # Keep server running until explicitly stopped
        await self._stop_event.wait()

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

    def switch_music_service(self, new_platform: str):
        """Dynamically switches active music service between Spotify and YouTube."""
        logger.info(f"Switching active music backend to '{new_platform}'...")
        if new_platform == "youtube":
            from src.youtube_service import YouTubeService
            self.spotify = YouTubeService(
                initial_playlist=self.config.get("youtube_initial_playlist"),
                music_only=self.config.get("youtube_music_only", True),
                max_duration_seconds=self.config.get("youtube_max_duration_seconds", 600)
            )
            logger.info("Initialized YouTube In-App Music Service (No-Login Mode).")
        else:
            self.spotify = SpotifyService(
                client_id=self.config.get("spotify_client_id"),
                client_secret=self.config.get("spotify_client_secret"),
                redirect_uri=self.config.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback"),
                playlist_id=self.config.get("spotify_playlist_id"),
                open_browser=False
            )
            logger.info("Initialized Spotify Music Service.")

        if self.twitch_bot:
            self.twitch_bot.spotify = self.spotify
        if self.tiktok_listener:
            self.tiktok_listener.spotify = self.spotify
        if self.overlay_server:
            self.overlay_server.spotify = self.spotify

        return self.spotify

    def stop(self):
        """Stops all running bot components."""
        logger.info("Stopping all bot components...")
        if self.twitch_bot:
            self.twitch_bot.stop()
        if self.tiktok_listener:
            self.tiktok_listener.stop()
        if self.overlay_server and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.overlay_server.stop(), self.loop)
        if self._stop_event and self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._stop_event.set)

def print_banner(manager: BotManager):
    print("==========================================================")
    print("        LA FORJA MUSIC BOT - TWITCH & TIKTOK TO SPOTIFY   ")
    print("==========================================================")
    
    lim = manager.limiter
    tw_limit = lim.get_max_songs("twitch")
    tt_limit = lim.get_max_songs("tiktok")
    tw_desc = "Unlimited" if tw_limit <= 0 else f"Max {tw_limit} songs"
    tt_desc = "Unlimited" if tt_limit <= 0 else f"Max {tt_limit} songs"
    win_str = f" per {lim.window_minutes}m" if lim.window_minutes > 0 else " per stream session"
    print(f"[OK] Quota Policy        -> Twitch: {tw_desc}{win_str} | TikTok: {tt_desc}{win_str}")

    if getattr(manager.spotify, "service_type", "spotify") == "youtube":
        print(f"[OK] Music Backend       -> YouTube In-App Player (No-Login Mode)")
    else:
        p_name = getattr(manager.spotify, "get_playlist_name", lambda: "Target Playlist")()
        print(f"[OK] Spotify Playlist    -> '{p_name}'")

    if manager.twitch_bot:
        print(f"[OK] Twitch Channel      -> #{manager.twitch_bot.channel}")
    else:
        print(f"[--] Twitch Integration  -> Disabled")

    if manager.tiktok_listener:
        print(f"[OK] TikTok Streamer     -> @{manager.tiktok_listener.unique_id}")
    else:
        print(f"[--] TikTok Integration  -> Disabled")
    if manager.overlay_server:
        port = manager.overlay_server.port
        lan_ip = getattr(manager.overlay_server, "lan_ip", "127.0.0.1")
        print(f"[OK] OBS Browser Source  -> http://localhost:{port}/overlay (or http://127.0.0.1:{port}/overlay)")
        if lan_ip and lan_ip != "127.0.0.1":
            print(f"                            http://{lan_ip}:{port}/overlay (For Remote/Dual-PC OBS)")

    print("\n----------------------------------------------------------")
    print(" Active Commands in Chat:")
    print("   !sr <song title, artist, or YouTube/Spotify link>")
    print("   !songrequest <song title, artist, or link>")
    print("   !skip (requester only: skip your currently playing song)")
    print("   !myrequests (check your quota)")
    print("   !resetrequests (broadcaster: reset all quotas)")
    print("----------------------------------------------------------\n")

def is_spotify_authorized(config: ConfigManager) -> bool:
    """Checks if Spotify credentials exist and have a valid authorized session."""
    cid = config.get("spotify_client_id")
    csec = config.get("spotify_client_secret")
    if not cid or not csec:
        return False
    try:
        sp = SpotifyService(
            client_id=cid,
            client_secret=csec,
            redirect_uri=config.get("spotify_redirect_uri", "http://127.0.0.1:8888/callback"),
            open_browser=False
        )
        return sp.is_authorized()
    except Exception:
        return False

def main():
    parser = argparse.ArgumentParser(description="La Forja Music Bot")
    parser.add_argument("--no-gui", action="store_true", help="Run without Desktop Mini-App GUI")
    parser.add_argument("--setup", action="store_true", help="Launch the Setup Wizard to configure settings")
    args = parser.parse_args()

    config = ConfigManager()

    # Automatically launch Setup Wizard if first-time setup or Spotify authorization is missing
    needs_setup = args.setup or not config.is_configured()
    if not needs_setup and config.get("music_platform") == "spotify":
        if not is_spotify_authorized(config):
            logger.info("Spotify is selected but authorization is missing. Launching Setup Wizard...")
            needs_setup = True

    if needs_setup:
        if args.no_gui:
            print("[ERROR] Configuration is incomplete. Please run without --no-gui to configure via Setup Wizard, or edit config.json.")
            sys.exit(1)

        logger.info("Opening Setup Wizard...")
        wizard = SetupWizard(config_manager=config)
        wizard.mainloop()

        config.load()
        if not config.is_configured():
            print("\nSetup cancelled or incomplete. Exiting.")
            sys.exit(0)

    manager = BotManager(config=config)
    manager.initialize()
    print_banner(manager)

    # If GUI is requested (default)
    if not args.no_gui:
        try:
            from src.mini_app import MiniApp
            manager.start_background()

            enable_tw = config.get("enable_twitch", True)
            enable_tt = config.get("enable_tiktok", True)

            t_chan = (
                (manager.twitch_bot.channel or manager.twitch_bot.nick)
                if (manager.twitch_bot and enable_tw)
                else (config.get("twitch_channel") or config.get("twitch_nick") if enable_tw else "Disabled")
            ) or "N/A"
            tt_user = (
                manager.tiktok_listener.unique_id
                if (manager.tiktok_listener and enable_tt)
                else (config.get("tiktok_username") if enable_tt else "Disabled")
            ) or "N/A"

            app = MiniApp(
                spotify_service=manager.spotify,
                request_limiter=manager.limiter,
                twitch_channel=t_chan,
                tiktok_username=tt_user,
                config_manager=config,
                bot_manager=manager
            )

            def on_close():
                if hasattr(app, "embedded_player") and app.embedded_player:
                    app.embedded_player.stop()
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
