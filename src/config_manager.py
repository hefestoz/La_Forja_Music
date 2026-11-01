import os
import json
import logging
from typing import Any, Dict, Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("ConfigManager")

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

class ConfigManager:
    """
    Manages loading, persisting, and validating configuration for La Forja Music.
    Supports JSON persistence with seamless fallback to environment variables (.env).
    """

    DEFAULT_SETTINGS = {
        "music_platform": "youtube",
        "spotify_client_id": "",
        "spotify_client_secret": "",
        "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
        "spotify_playlist_id": "",
        "spotify_playlist_name": "",
        "youtube_initial_playlist": "",
        "youtube_music_only": True,
        "youtube_max_duration_seconds": 600,
        "enable_twitch": True,
        "twitch_client_id": "",
        "twitch_token": "",
        "twitch_nick": "",
        "twitch_channel": "",
        "enable_tiktok": True,
        "tiktok_username": "",
        "max_songs_per_user": 3,
        "user_limit_window_minutes": 0,
        "cooldown_seconds": 10,
        "overlay_port": 5000,
        "auto_launch_browser": True
    }

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._config: Dict[str, Any] = dict(self.DEFAULT_SETTINGS)
        self.load()

    def load(self) -> Dict[str, Any]:
        """Loads configuration from JSON file and merges with .env fallbacks."""
        # 1. Start with defaults
        loaded_data: Dict[str, Any] = {}

        # 2. Read from config.json if exists and non-empty
        if os.path.exists(self.config_path) and os.path.getsize(self.config_path) > 0:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                logger.info(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to read {self.config_path}: {e}")

        # 3. Apply loaded data over defaults
        self._config.update(loaded_data)

        # 4. Fallback to environment variables if not present in config.json
        env_mappings = {
            "spotify_client_id": os.getenv("SPOTIFY_CLIENT_ID", ""),
            "spotify_client_secret": os.getenv("SPOTIFY_CLIENT_SECRET", ""),
            "spotify_redirect_uri": os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            "spotify_playlist_id": os.getenv("SPOTIFY_PLAYLIST_ID", ""),
            "twitch_client_id": os.getenv("TWITCH_CLIENT_ID", ""),
            "twitch_token": os.getenv("TWITCH_TOKEN", ""),
            "twitch_nick": os.getenv("TWITCH_NICK", ""),
            "twitch_channel": os.getenv("TWITCH_CHANNEL", ""),
            "tiktok_username": os.getenv("TIKTOK_USERNAME", ""),
        }

        for key, val in env_mappings.items():
            if val and not self._config.get(key):
                self._config[key] = val

        # Handle numeric limits from env if not set
        if "max_songs_per_user" not in loaded_data and os.getenv("MAX_SONGS_PER_USER"):
            try:
                self._config["max_songs_per_user"] = int(os.getenv("MAX_SONGS_PER_USER"))
            except ValueError:
                pass

        if "user_limit_window_minutes" not in loaded_data and os.getenv("USER_LIMIT_WINDOW_MINUTES"):
            try:
                self._config["user_limit_window_minutes"] = int(os.getenv("USER_LIMIT_WINDOW_MINUTES"))
            except ValueError:
                pass

        return self._config

    def save(self) -> bool:
        """Persists current configuration dictionary to JSON file."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.config_path)), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved configuration to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving configuration to {self.config_path}: {e}")
            return False

    def is_configured(self) -> bool:
        """
        Validates whether minimum required streaming settings are set.
        Must have:
          - A valid music platform configuration:
            * If 'spotify': Spotify client ID, client secret, and target playlist ID
            * If 'youtube': Instantly configured (no Google accounts or API keys required)
          - At least one active chat channel (Twitch or TikTok)
        """
        platform = self.get("music_platform", "spotify")

        if platform == "youtube":
            has_music = True
        else:
            has_music = bool(
                self.get("spotify_client_id") and
                self.get("spotify_client_secret") and
                self.get("spotify_playlist_id")
            )

        has_chat = bool(
            (self.get("enable_twitch", True) and (self.get("twitch_channel") or self.get("twitch_token"))) or
            (self.get("enable_tiktok", True) and self.get("tiktok_username"))
        )

        return has_music and has_chat

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value

    def update(self, new_data: Dict[str, Any]) -> None:
        self._config.update(new_data)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._config)

    def reset(self) -> bool:
        """Resets configuration back to default empty settings and removes config.json file."""
        self._config = dict(self.DEFAULT_SETTINGS)
        try:
            if os.path.exists(self.config_path):
                os.remove(self.config_path)
            logger.info("Configuration reset to defaults.")
            return True
        except Exception as e:
            logger.error(f"Failed to remove config file during reset: {e}")
            return False

