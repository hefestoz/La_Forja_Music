from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple, List

class BaseMusicService(ABC):
    """
    Abstract base class defining the unified contract for music services (Spotify, YouTube).
    Allows bot components (TwitchBot, TikTokListener, MiniApp, OverlayServer) to operate
    interchangeably regardless of the active music backend.
    """

    @property
    @abstractmethod
    def service_type(self) -> str:
        """Returns the identifier of the service, e.g. 'spotify' or 'youtube'."""
        pass

    @abstractmethod
    def is_authorized(self) -> bool:
        """Returns whether the service is authorized and ready to accept requests."""
        pass

    @abstractmethod
    def search_track(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Resolves a search query (song title, artist, or direct URL) into a standardized track dict:
        {
            "id": str,
            "uri": str,
            "name": str,
            "artists": List[str],
            "artist_str": str,
            "duration_ms": int,
            "external_url": str,
            "album_art": str
        }
        """
        pass

    @abstractmethod
    def add_song_request(
        self,
        query: str,
        requested_by: str = "Anonymous",
        prevent_duplicates: bool = True
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Processes a song request from chat (!sr).
        Returns:
            (success: bool, user_message: str, track_info: Optional[dict])
        """
        pass

    @abstractmethod
    def get_currently_playing(self) -> Optional[Dict[str, Any]]:
        """
        Retrieves currently playing track details, playback progress, and requester info:
        {
            "id": str,
            "uri": str,
            "title": str,
            "artists": List[str],
            "artist_str": str,
            "album_name": str,
            "album_art": str,
            "duration_ms": int,
            "progress_ms": int,
            "is_playing": bool,
            "volume_percent": int,
            "requested_by": Optional[str]
        }
        """
        pass

    @abstractmethod
    def get_recent_requests(self) -> List[Dict[str, Any]]:
        """Returns the list of recently requested tracks in queue."""
        pass

    @abstractmethod
    def next_track(self) -> bool:
        """Skips to the next track."""
        pass

    @abstractmethod
    def previous_track(self) -> bool:
        """Plays the previous track."""
        pass

    @abstractmethod
    def toggle_playback(self) -> bool:
        """Toggles play/pause."""
        pass

    @abstractmethod
    def set_volume(self, volume_percent: int) -> bool:
        """Sets playback volume (0 - 100)."""
        pass

    @abstractmethod
    def clear_playlist(self) -> bool:
        """Clears the request queue or playlist."""
        pass
