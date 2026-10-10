import os
import re
import logging
from typing import Optional, Dict, Any, Tuple
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("SpotifyService")

class SpotifyService:
    """
    Manages authentication and interactions with the Spotify Web API.
    Handles searching songs and adding tracks to a designated playlist.
    """

    SPOTIFY_SCOPES = [
        "playlist-modify-public",
        "playlist-modify-private",
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-read-currently-playing",
        "user-read-playback-state",
        "user-modify-playback-state"
    ]

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        playlist_id: Optional[str] = None,
        open_browser: bool = True
    ):
        self.client_id = client_id or os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("SPOTIFY_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
        self.playlist_id = playlist_id or os.getenv("SPOTIFY_PLAYLIST_ID")

        if not self.client_id or not self.client_secret:
            raise ValueError("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set.")
        if not self.playlist_id:
            raise ValueError("SPOTIFY_PLAYLIST_ID must be set.")

        self.auth_manager = SpotifyOAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=" ".join(self.SPOTIFY_SCOPES),
            open_browser=open_browser,
            cache_path=".cache-spotify"
        )
        self.sp = spotipy.Spotify(auth_manager=self.auth_manager)
        self._playlist_name: Optional[str] = None
        self._requester_history: Dict[str, Dict[str, Any]] = {}
        self._recent_requests: list[Dict[str, Any]] = []

    def is_authorized(self) -> bool:
        """Checks if a valid Spotify OAuth token exists in cache, automatically refreshing if expired."""
        token = self.auth_manager.cache_handler.get_cached_token()
        if not token:
            return False
        valid_token = self.auth_manager.validate_token(token)
        return valid_token is not None


    def get_playlist_name(self) -> str:
        """Retrieves and caches the name of the target playlist."""
        if self._playlist_name:
            return self._playlist_name
        try:
            playlist_data = self.sp.playlist(self.playlist_id, fields="name")
            self._playlist_name = playlist_data.get("name", "Target Playlist")
            return self._playlist_name
        except Exception as e:
            logger.error(f"Error fetching playlist details: {e}")
            return "Target Playlist"

    @staticmethod
    def extract_track_id(query: str) -> Optional[str]:
        """
        Extracts Spotify track ID from a URL or URI if provided.
        Example:
            https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=... -> 4cOdK2wGLETKBW3PvgPWqT
            spotify:track:4cOdK2wGLETKBW3PvgPWqT -> 4cOdK2wGLETKBW3PvgPWqT
        """
        query = query.strip()
        # Direct track ID match (22 alphanumeric chars)
        if re.fullmatch(r"[0-9A-Za-z]{22}", query):
            return query

        # URI match (spotify:track:ID)
        uri_match = re.search(r"spotify:track:([0-9A-Za-z]{22})", query)
        if uri_match:
            return uri_match.group(1)

        # URL match (open.spotify.com/track/ID)
        url_match = re.search(r"open\.spotify\.com/track/([0-9A-Za-z]{22})", query)
        if url_match:
            return url_match.group(1)

        return None

    def search_track(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Resolves a search query (free text or Spotify link/URI) into a track object.
        """
        query = query.strip()
        if not query:
            return None

        track_id = self.extract_track_id(query)

        try:
            if track_id:
                track = self.sp.track(track_id)
            else:
                results = self.sp.search(q=query, type="track", limit=1)
                items = results.get("tracks", {}).get("items", [])
                if not items:
                    return None
                track = items[0]

            artists = [a["name"] for a in track.get("artists", [])]
            return {
                "id": track["id"],
                "uri": track["uri"],
                "name": track["name"],
                "artists": artists,
                "artist_str": ", ".join(artists) if artists else "Unknown Artist",
                "duration_ms": track["duration_ms"],
                "external_url": track["external_urls"].get("spotify", "")
            }
        except SpotifyException as e:
            logger.error(f"Spotify API error during search: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error searching track: {e}")
            return None

    def is_track_in_playlist(self, track_uri: str, limit_check: int = 100) -> bool:
        """
        Checks if the track is already present in the most recent items of the playlist.
        """
        try:
            playlist_items = self.sp.playlist_items(
                self.playlist_id,
                limit=limit_check
            )
            for raw_item in playlist_items.get("items", []):
                t = raw_item.get("item") or raw_item.get("track")
                if t and t.get("uri") == track_uri:
                    return True
            return False
        except Exception as e:
            logger.warning(f"Could not verify duplicate status in playlist: {e}")
            return False

    def add_song_request(
        self,
        query: str,
        requested_by: str = "Anonymous",
        prevent_duplicates: bool = True
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Main entry point for song requests from chat (!sr).
        Searches the song, verifies duplicates, and adds it to the playlist.
        Returns:
            (success: bool, user_message: str, track_info: Optional[dict])
        """
        track = self.search_track(query)
        if not track:
            return False, f"Could not find any song matching '{query}' on Spotify.", None

        track_title = f"\"{track['name']}\" by {track['artist_str']}"

        if prevent_duplicates and self.is_track_in_playlist(track["uri"]):
            return False, f"{track_title} is already in the playlist!", track

        try:
            self.sp.playlist_add_items(self.playlist_id, [track["uri"]])
            
            # Record requester metadata
            import time
            self._requester_history[track["uri"]] = {
                "requested_by": requested_by,
                "title": track["name"],
                "artist": track["artist_str"],
                "time": time.time()
            }
            self._recent_requests.insert(0, {
                "title": track["name"],
                "artist": track["artist_str"],
                "requested_by": requested_by,
                "time": time.time(),
                "url": track["external_url"]
            })
            if len(self._recent_requests) > 30:
                self._recent_requests.pop()

            logger.info(f"Added {track_title} (requested by {requested_by}) to playlist {self.playlist_id}")
            return True, f"Added {track_title} to the playlist! (requested by {requested_by})", track
        except SpotifyException as e:
            logger.error(f"Failed to add track to playlist: {e}")
            return False, f"Failed to add track to Spotify playlist: {e.msg if hasattr(e, 'msg') else str(e)}", track
        except Exception as e:
            logger.error(f"Unexpected error adding track: {e}")
            return False, "An unexpected error occurred while adding the song.", track

    def get_currently_playing(self) -> Optional[Dict[str, Any]]:
        """
        Fetches currently playing track status, progress, and requester attribution.
        """
        try:
            playback = self.sp.current_playback()
            if not playback or not playback.get("item"):
                return None

            item = playback["item"]
            track_uri = item.get("uri")
            requester_info = self._requester_history.get(track_uri)

            artists = [a["name"] for a in item.get("artists", [])]
            album = item.get("album", {})
            images = album.get("images", [])
            album_art = images[0]["url"] if images else ""

            return {
                "id": item.get("id"),
                "uri": track_uri,
                "title": item.get("name"),
                "artists": artists,
                "artist_str": ", ".join(artists) if artists else "Unknown",
                "album_name": album.get("name", ""),
                "album_art": album_art,
                "duration_ms": item.get("duration_ms", 0),
                "progress_ms": playback.get("progress_ms", 0),
                "is_playing": playback.get("is_playing", False),
                "volume_percent": playback.get("device", {}).get("volume_percent", 100),
                "requested_by": requester_info.get("requested_by") if requester_info else None
            }
        except Exception as e:
            logger.debug(f"Could not fetch current playback: {e}")
            return None

    def next_track(self) -> bool:
        """Skips to the next track on Spotify."""
        try:
            self.sp.next_track()
            return True
        except Exception as e:
            logger.warning(f"Failed to skip track: {e}")
            return False

    def previous_track(self) -> bool:
        """Plays the previous track on Spotify."""
        try:
            self.sp.previous_track()
            return True
        except Exception as e:
            logger.warning(f"Failed to play previous track: {e}")
            return False

    def toggle_playback(self) -> bool:
        """Toggles play/pause on Spotify."""
        try:
            playback = self.sp.current_playback()
            if playback and playback.get("is_playing"):
                self.sp.pause_playback()
            else:
                self.sp.start_playback()
            return True
        except Exception as e:
            logger.warning(f"Failed to toggle playback: {e}")
            return False

    def set_volume(self, volume_percent: int) -> bool:
        """Sets Spotify volume (0 - 100)."""
        try:
            vol = max(0, min(100, volume_percent))
            self.sp.volume(vol)
            return True
        except Exception as e:
            logger.warning(f"Failed to set volume: {e}")
            return False

    def get_recent_requests(self) -> list[Dict[str, Any]]:
        """Returns the list of recently requested songs."""
        return list(self._recent_requests)

    def clear_playlist(self) -> bool:
        """Clears all songs currently in the request playlist."""
        try:
            items = self.sp.playlist_items(self.playlist_id, fields="items(item(uri),track(uri))")
            uris = []
            for raw_item in items.get("items", []):
                t = raw_item.get("item") or raw_item.get("track")
                if t and t.get("uri"):
                    uris.append(t["uri"])
            if uris:
                self.sp.playlist_remove_all_occurrences_of_items(self.playlist_id, uris)
            return True
        except Exception as e:
            logger.error(f"Failed to clear playlist: {e}")
            return False
