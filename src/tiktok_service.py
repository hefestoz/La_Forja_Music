import os
import time
import asyncio
import logging
from typing import Optional, Dict
from dotenv import load_dotenv
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent, LiveEndEvent
from TikTokLive.client.errors import UserOfflineError, UserNotFoundError, TikTokLiveError
from src.spotify_service import SpotifyService
from src.request_limiter import RequestLimiter

load_dotenv()
logger = logging.getLogger("TikTokService")

class TikTokListener:
    """
    Asynchronous TikTok Live listener for song requests.
    Listens to live chat comments for '!sr' commands and feeds them to Spotify.
    """

    def __init__(
        self,
        spotify_service: SpotifyService,
        request_limiter: Optional[RequestLimiter] = None,
        unique_id: Optional[str] = None,
        cooldown_seconds: int = 10,
        retry_interval: int = 30
    ):
        self.spotify = spotify_service
        self.limiter = request_limiter or RequestLimiter()
        raw_username = unique_id or os.getenv("TIKTOK_USERNAME", "")
        self.unique_id = raw_username.lstrip("@").strip()
        self.cooldown_seconds = cooldown_seconds
        self.retry_interval = retry_interval

        self._user_last_request: Dict[str, float] = {}
        self._running = False
        self._client: Optional[TikTokLiveClient] = None

        if not self.unique_id:
            raise ValueError("TIKTOK_USERNAME must be configured.")

    async def handle_comment(self, username: str, comment_text: str) -> None:
        """Processes a comment text for !sr commands."""
        clean_text = comment_text.strip()
        if not (clean_text.lower().startswith("!sr ") or clean_text.lower().startswith("!songrequest ")):
            return

        parts = clean_text.split(" ", 1)
        if len(parts) < 2 or not parts[1].strip():
            logger.info(f"[TikTok] User @{username} used !sr without query.")
            return

        query = parts[1].strip()

        # Cooldown check
        now = time.time()
        last_req = self._user_last_request.get(username, 0)
        if now - last_req < self.cooldown_seconds:
            logger.info(f"[TikTok] Cooldown: @{username} requested too quickly.")
            return
        self._user_last_request[username] = now

        # Quota check
        allowed, limit_msg = self.limiter.can_request("tiktok", username)
        if not allowed:
            logger.info(f"[TikTok LIMIT] @{username}: {limit_msg}")
            return

        logger.info(f"[TikTok] Song request received from @{username}: '{query}'")
        loop = asyncio.get_running_loop()
        success, reply_msg, track = await loop.run_in_executor(
            None,
            self.spotify.add_song_request,
            query,
            f"TikTok/@{username}",
            True
        )

        if success:
            count = self.limiter.record_request("tiktok", username)
            if self.limiter.max_songs > 0 and not self.limiter.is_broadcaster(username):
                reply_msg += f" (Song #{count}/{self.limiter.max_songs})"
            logger.info(f"[TikTok SUCCESS] {reply_msg}")
        else:
            logger.info(f"[TikTok NOTICE] {reply_msg}")

    def _setup_client(self) -> TikTokLiveClient:
        """Instantiates client and registers event handlers."""
        client = TikTokLiveClient(unique_id=self.unique_id)

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            logger.info(f"[TikTok] Successfully connected to live stream of @{self.unique_id}!")

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            logger.warning(f"[TikTok] Disconnected from @{self.unique_id} live stream.")

        @client.on(LiveEndEvent)
        async def on_live_end(event: LiveEndEvent):
            logger.info(f"[TikTok] Live stream ended for @{self.unique_id}.")

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            username = event.user.unique_id if event.user else "Anonymous"
            await self.handle_comment(username, event.comment)

        return client

    async def start(self) -> None:
        """Runs the listener loop with auto-reconnect when offline."""
        self._running = True
        logger.info(f"Starting TikTok listener for @{self.unique_id}...")

        while self._running:
            try:
                self._client = self._setup_client()
                await self._client.connect()
            except UserOfflineError:
                logger.info(f"[TikTok] @{self.unique_id} is currently OFFLINE. Checking again in {self.retry_interval}s...")
                await asyncio.sleep(self.retry_interval)
            except UserNotFoundError:
                logger.error(f"[TikTok] User @{self.unique_id} not found. Please check TIKTOK_USERNAME.")
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                logger.info("[TikTok] Listener cancelled.")
                break
            except Exception as e:
                logger.warning(f"[TikTok] Connection error ({e}). Retrying in {self.retry_interval}s...")
                await asyncio.sleep(self.retry_interval)

    def stop(self) -> None:
        """Stops the listener."""
        self._running = False
        if self._client and self._client.connected:
            try:
                asyncio.create_task(self._client.disconnect())
            except Exception:
                pass
