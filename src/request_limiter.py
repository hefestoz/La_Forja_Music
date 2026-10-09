import os
import time
import math
import logging
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("RequestLimiter")

class RequestLimiter:
    """
    Manages and enforces per-user request limits across platforms.
    Supports:
      - Per Stream mode (window_minutes = 0): Count accumulates until reset.
      - Rolling Window mode (window_minutes > 0): Count resets based on a sliding time window.
      - Broadcaster / VIP bypass.
    """

    def __init__(
        self,
        max_songs_per_user: Optional[int] = None,
        window_minutes: Optional[int] = None,
        broadcaster_username: Optional[str] = None
    ):
        if max_songs_per_user is not None:
            self.max_songs = max_songs_per_user
        else:
            self.max_songs = int(os.getenv("MAX_SONGS_PER_USER", "3"))

        if window_minutes is not None:
            self.window_minutes = window_minutes
        else:
            self.window_minutes = int(os.getenv("USER_LIMIT_WINDOW_MINUTES", "0"))

        raw_broadcaster = broadcaster_username or os.getenv("TWITCH_CHANNEL") or os.getenv("TIKTOK_USERNAME") or ""
        self.broadcaster = raw_broadcaster.lower().lstrip("@#").strip()

        # Storage: key -> list of float timestamps of successful requests
        # key format: "platform:username" (e.g. "twitch:viewer1", "tiktok:viewer2")
        self._history: Dict[str, List[float]] = defaultdict(list)

    @staticmethod
    def _make_key(platform: str, username: str) -> str:
        return f"{platform.lower()}:{username.lower().lstrip('@#')}"

    def is_broadcaster(self, username: str) -> bool:
        """Checks if the user is the streamer/broadcaster."""
        clean = username.lower().lstrip("@#").strip()
        return bool(self.broadcaster and clean == self.broadcaster)

    def can_request(self, platform: str, username: str) -> Tuple[bool, str]:
        """
        Determines whether a user is allowed to request another song.
        Returns:
            (allowed: bool, reason_message: str)
        """
        # 0 or negative means unlimited
        if self.max_songs <= 0:
            return True, ""

        # Broadcaster is always exempt
        if self.is_broadcaster(username):
            return True, ""

        key = self._make_key(platform, username)
        now = time.time()
        timestamps = self._history[key]

        # Mode 1: Rolling time window (window_minutes > 0)
        if self.window_minutes > 0:
            cutoff = now - (self.window_minutes * 60)
            # Retain only timestamps within the window
            valid_timestamps = [ts for ts in timestamps if ts > cutoff]
            self._history[key] = valid_timestamps

            if len(valid_timestamps) >= self.max_songs:
                # Time until the oldest request falls outside the window
                oldest = valid_timestamps[0]
                remaining_seconds = int((oldest + (self.window_minutes * 60)) - now)
                remaining_minutes = max(1, math.ceil(remaining_seconds / 60))
                return False, (
                    f"You have reached your limit of {self.max_songs} song(s) per {self.window_minutes}m. "
                    f"You can request again in ~{remaining_minutes} min."
                )

        # Mode 2: Per stream / session (window_minutes == 0)
        else:
            if len(timestamps) >= self.max_songs:
                return False, f"You have reached your limit of {self.max_songs} song(s) for this stream!"

        return True, ""

    def record_request(self, platform: str, username: str) -> int:
        """
        Records a successful track addition for the user.
        Returns current total count for the user.
        """
        if self.is_broadcaster(username):
            return 0

        key = self._make_key(platform, username)
        self._history[key].append(time.time())
        current_count = len(self._history[key])
        logger.info(f"Recorded request for {key} (total: {current_count}/{self.max_songs if self.max_songs > 0 else 'unlimited'})")
        return current_count

    def get_user_count(self, platform: str, username: str) -> int:
        """Returns the current number of valid requests for a user."""
        key = self._make_key(platform, username)
        if self.window_minutes > 0:
            cutoff = time.time() - (self.window_minutes * 60)
            return len([ts for ts in self._history[key] if ts > cutoff])
        return len(self._history[key])

    def reset_limits(self, platform: Optional[str] = None, username: Optional[str] = None) -> None:
        """Resets limits for a specific user, or for all users if none specified."""
        if platform and username:
            key = self._make_key(platform, username)
            self._history.pop(key, None)
            logger.info(f"Reset request limit for {key}")
        else:
            self._history.clear()
            logger.info("Reset request limits for ALL users.")
