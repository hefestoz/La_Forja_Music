import os
import re
import time
import asyncio
import logging
from typing import Optional, Dict, Tuple, Any
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
        self.unique_id = raw_username.lstrip("@").strip().lower()
        self.cooldown_seconds = cooldown_seconds
        self.retry_interval = retry_interval

        self._user_last_request: Dict[str, float] = {}
        self._running = False
        self._client: Optional[TikTokLiveClient] = None

        if not self.unique_id:
            raise ValueError("TIKTOK_USERNAME must be configured.")

    @staticmethod
    def _extract_user_info(user: Any) -> Tuple[str, str]:
        """
        Extracts (tracking_id, display_name) from a TikTokLive user object.
        - tracking_id: persistent identifier (unique_id or numeric ID) used for rate limits and cooldowns.
        - display_name: chatter's profile nickname shown in chat, stripping auto-generated numbers.
        """
        if not user:
            return "anonymous", "Anonymous"

        # Unique handle or numeric ID (e.g. "3564346218" or "hefestoz")
        raw_unique_id = getattr(user, "unique_id", None) or getattr(user, "display_id", None)
        user_num_id = getattr(user, "user_id", None) or getattr(user, "id", None)
        tracking_id = str(raw_unique_id or user_num_id or "anonymous").strip()

        # Nickname / Profile display name (e.g. "Juan Perez 🔥")
        raw_nickname = getattr(user, "nick_name", None) or getattr(user, "nickname", None)
        nickname = str(raw_nickname).strip() if raw_nickname else ""

        # Check if unique_id is an auto-generated random numeric ID (e.g. "3564346218" or "user12345678")
        is_numeric_handle = bool(re.match(r"^(user)?\d+$", tracking_id, re.IGNORECASE))

        if nickname:
            display_name = nickname
        elif not is_numeric_handle and tracking_id != "anonymous":
            display_name = f"@{tracking_id}"
        elif tracking_id != "anonymous":
            display_name = "TikTok Viewer"
        else:
            display_name = "Anonymous"

        return tracking_id, display_name

    async def handle_comment(
        self,
        username: str,
        comment_text: str,
        display_name: Optional[str] = None
    ) -> None:
        """
        Processes a comment text for !sr commands.
        - username: tracking ID used for rate limits and cooldowns.
        - display_name: human-readable profile nickname shown on OBS overlay and Spotify queue.
        """
        clean_text = comment_text.strip()
        if not (clean_text.lower().startswith("!sr ") or clean_text.lower().startswith("!songrequest ")):
            return

        resolved_display = (display_name or username).strip()

        parts = clean_text.split(" ", 1)
        if len(parts) < 2 or not parts[1].strip():
            logger.info(f"[TikTok] User {resolved_display} used !sr without query.")
            return

        query = parts[1].strip()

        # Cooldown check (keyed on persistent username/tracking_id)
        now = time.time()
        last_req = self._user_last_request.get(username, 0)
        if now - last_req < self.cooldown_seconds:
            logger.info(f"[TikTok] Cooldown: {resolved_display} requested too quickly.")
            return
        self._user_last_request[username] = now

        # Quota check (keyed on persistent username/tracking_id)
        allowed, limit_msg = self.limiter.can_request("tiktok", username)
        if not allowed:
            logger.info(f"[TikTok LIMIT] {resolved_display}: {limit_msg}")
            return

        logger.info(f"[TikTok] Song request received from {resolved_display} ({username}): '{query}'")
        is_broadcaster = self.limiter.is_broadcaster(username)
        prevent_duplicates = not is_broadcaster
        loop = asyncio.get_running_loop()
        success, reply_msg, track = await loop.run_in_executor(
            None,
            self.spotify.add_song_request,
            query,
            f"TikTok/{resolved_display}",
            prevent_duplicates
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
            tracking_id, display_name = self._extract_user_info(event.user)
            await self.handle_comment(tracking_id, event.comment, display_name=display_name)

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
                logger.warning(
                    f"[TikTok] User '{self.unique_id}' was not found or has no active TikTok LIVE stream. "
                    f"Checking again in 60s... (Note: TikTok requires the exact lowercase username handle, and the account must be live or have streamed before)."
                )
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
