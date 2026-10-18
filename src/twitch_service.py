import os
import re
import time
import asyncio
import logging
from typing import Optional, Dict, Tuple, List
import requests
import websockets
from dotenv import load_dotenv
from src.spotify_service import SpotifyService
from src.request_limiter import RequestLimiter

load_dotenv()
logger = logging.getLogger("TwitchService")

class TwitchBot:
    """
    Asynchronous Twitch Chat Bot for song requests.
    Connects to Twitch IRC WebSocket and listens for '!sr' commands.
    """

    WS_URI = "wss://irc-ws.chat.twitch.tv:443"

    def __init__(
        self,
        spotify_service: SpotifyService,
        request_limiter: Optional[RequestLimiter] = None,
        token: Optional[str] = None,
        channel: Optional[str] = None,
        nick: Optional[str] = None,
        prefix: str = "!",
        cooldown_seconds: int = 10
    ):
        self.spotify = spotify_service
        self.limiter = request_limiter or RequestLimiter()
        raw_token = token or os.getenv("TWITCH_TOKEN", "")
        if raw_token and not raw_token.startswith("oauth:"):
            self.token = f"oauth:{raw_token}"
        else:
            self.token = raw_token

        raw_channel = channel or os.getenv("TWITCH_CHANNEL", "")
        self.channel = raw_channel.lower().lstrip("#")
        raw_nick = nick or os.getenv("TWITCH_NICK", "")
        self.nick = raw_nick.lower().lstrip("#") if raw_nick else self.channel
        self.prefix = prefix
        self.cooldown_seconds = cooldown_seconds

        self._user_last_request: Dict[str, float] = {}
        self._running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

        if not self.token or not self.channel:
            raise ValueError("TWITCH_TOKEN and TWITCH_CHANNEL must be configured.")

    async def send_chat_message(self, message: str) -> None:
        """Sends a message to the Twitch channel chat."""
        if self._ws:
            try:
                await self._ws.send(f"PRIVMSG #{self.channel} :{message}")
                logger.info(f"[Twitch -> #{self.channel}]: {message}")
            except Exception as e:
                logger.error(f"Failed to send Twitch chat message: {e}")

    def _parse_irc_message(self, line: str):
        """
        Parses raw IRC lines into (sender, command, target, message).
        Example line: :user!user@user.tmi.twitch.tv PRIVMSG #channel :!sr song
        """
        match = re.match(r"^:(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #(\w+) :(.+)$", line)
        if match:
            sender, target_chan, content = match.groups()
            return sender, target_chan, content
        return None, None, None

    async def handle_song_request(self, username: str, query: str) -> None:
        """Processes the !sr command and replies in Twitch chat."""
        now = time.time()
        last_req = self._user_last_request.get(username, 0)
        if now - last_req < self.cooldown_seconds:
            wait_time = int(self.cooldown_seconds - (now - last_req))
            await self.send_chat_message(f"@{username} Please wait {wait_time}s before requesting another song.")
            return

        self._user_last_request[username] = now

        # Check quota limit before doing anything else
        allowed, limit_msg = self.limiter.can_request("twitch", username)
        if not allowed:
            await self.send_chat_message(f"@{username} {limit_msg}")
            return

        logger.info(f"Processing Twitch request from @{username}: '{query}'")
        # Run Spotify request (Spotify API call is synchronous requests-based, run in executor)
        loop = asyncio.get_running_loop()
        success, reply_msg, track = await loop.run_in_executor(
            None,
            self.spotify.add_song_request,
            query,
            username,
            True
        )

        if success:
            count = self.limiter.record_request("twitch", username)
            if self.limiter.max_songs > 0 and not self.limiter.is_broadcaster(username):
                reply_msg += f" (Song #{count}/{self.limiter.max_songs})"

        await self.send_chat_message(f"@{username} {reply_msg}")

    async def start(self) -> None:
        """Main loop that connects to Twitch WebSocket with automatic reconnection."""
        self._running = True
        logger.info(f"Connecting to Twitch chat for channel #{self.channel}...")

        backoff = 2
        while self._running:
            try:
                async with websockets.connect(self.WS_URI) as ws:
                    self._ws = ws
                    # Authenticate and join
                    await ws.send(f"PASS {self.token}")
                    await ws.send(f"NICK {self.nick}")
                    await ws.send(f"JOIN #{self.channel}")
                    logger.info(f"[Twitch] Connected and joined #{self.channel}!")
                    backoff = 2

                    async for raw_message in ws:
                        if not self._running:
                            break

                        for line in raw_message.strip().split("\r\n"):
                            # Handle Ping/Pong keep-alive
                            if line.startswith("PING"):
                                await ws.send("PONG :tmi.twitch.tv")
                                continue

                            sender, target_chan, content = self._parse_irc_message(line)
                            if not sender or not content:
                                continue

                            clean_content = content.strip()

                            # Broadcaster command to reset limits
                            if clean_content.lower() in ("!resetrequests", "!clearlimits"):
                                if sender.lower() == self.channel:
                                    self.limiter.reset_limits()
                                    await self.send_chat_message(f"@{sender} All song request limits have been reset!")
                                else:
                                    await self.send_chat_message(f"@{sender} Only the broadcaster can reset limits.")
                                continue

                            # Query current user requests
                            if clean_content.lower() in ("!myrequests", "!requests"):
                                count = self.limiter.get_user_count("twitch", sender)
                                max_s = self.limiter.max_songs
                                if self.limiter.is_broadcaster(sender):
                                    await self.send_chat_message(f"@{sender} You are the broadcaster (unlimited requests).")
                                elif max_s > 0:
                                    await self.send_chat_message(f"@{sender} You have requested {count}/{max_s} songs.")
                                else:
                                    await self.send_chat_message(f"@{sender} Song requests are currently unlimited!")
                                continue

                            # Check for !sr or !songrequest command
                            if clean_content.lower().startswith("!sr ") or clean_content.lower().startswith("!songrequest "):
                                parts = clean_content.split(" ", 1)
                                if len(parts) > 1 and parts[1].strip():
                                    query = parts[1].strip()
                                    asyncio.create_task(self.handle_song_request(sender, query))
                                else:
                                    await self.send_chat_message(f"@{sender} Usage: !sr <song title, artist, or Spotify link>")

            except asyncio.CancelledError:
                logger.info("[Twitch] Listener cancelled.")
                break
            except Exception as e:
                logger.warning(f"[Twitch] Connection dropped ({e}). Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                self._ws = None

    def stop(self) -> None:
        """Stops the Twitch listener."""
        self._running = False


def validate_twitch_token(token: str) -> Tuple[bool, Optional[str], List[str], Optional[str]]:
    """
    Validates a Twitch OAuth token using Twitch's official token validation endpoint:
    GET https://id.twitch.tv/oauth2/validate

    Returns:
        (is_valid, login_name, scopes, error_message)
    """
    clean_token = token.strip()
    if clean_token.startswith("oauth:"):
        clean_token = clean_token[6:].strip()

    if not clean_token:
        return False, None, [], "Empty token provided."

    url = "https://id.twitch.tv/oauth2/validate"
    headers = {"Authorization": f"OAuth {clean_token}"}

    try:
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            login = data.get("login", "")
            scopes = data.get("scopes", [])
            return True, login, scopes, None
        elif resp.status_code == 401:
            return False, None, [], "Invalid or expired Twitch token."
        else:
            return False, None, [], f"Twitch validation failed (HTTP {resp.status_code})"
    except Exception as e:
        return False, None, [], f"Connection error during validation: {e}"

