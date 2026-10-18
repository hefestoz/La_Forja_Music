import os
import re
import logging
from difflib import SequenceMatcher
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

    def get_authorize_url(self) -> str:
        """Returns the Spotify OAuth authorization URL."""
        return self.auth_manager.get_authorize_url()

    def exchange_code(self, code: str) -> bool:
        """Exchanges an authorization code for cached tokens."""
        try:
            token = self.auth_manager.get_access_token(code=code, as_dict=True)
            return token is not None
        except Exception as e:
            logger.error(f"Failed to exchange Spotify authorization code: {e}")
            return False

    def get_current_user_profile(self) -> Optional[Dict[str, Any]]:
        """Retrieves currently logged-in user profile info (name, image, product)."""
        try:
            me = self.sp.me()
            images = me.get("images", [])
            return {
                "id": me.get("id"),
                "display_name": me.get("display_name", "Spotify User"),
                "image_url": images[0]["url"] if images else "",
                "product": me.get("product", "unknown")
            }
        except Exception as e:
            logger.debug(f"Could not fetch current user profile: {e}")
            return None

    def get_user_playlists(self, limit: int = 50) -> list[Dict[str, Any]]:
        """Retrieves list of user's playlists for selection in Setup Wizard."""
        try:
            res = self.sp.current_user_playlists(limit=limit)
            items = res.get("items", [])
            playlists = []
            for p in items:
                playlists.append({
                    "id": p["id"],
                    "name": p["name"],
                    "tracks_total": p.get("tracks", {}).get("total", 0)
                })
            return playlists
        except Exception as e:
            logger.error(f"Error fetching user playlists: {e}")
            return []

    def create_stream_playlist(
        self,
        name: str = "Stream Song Requests",
        description: str = "Live song requests powered by La Forja Music"
    ) -> Tuple[bool, str, str]:
        """Automatically creates a new public playlist on the user's Spotify account."""
        try:
            me = self.sp.me()
            user_id = me["id"]
            new_p = self.sp.user_playlist_create(
                user=user_id,
                name=name,
                public=True,
                description=description
            )
            self.playlist_id = new_p["id"]
            self._playlist_name = new_p["name"]
            logger.info(f"Created new playlist '{name}' (ID: {self.playlist_id})")
            return True, self.playlist_id, self._playlist_name
        except Exception as e:
            logger.error(f"Failed to create playlist: {e}")
            return False, "", str(e)

    def get_playlist_name(self) -> str:
        """Retrieves and caches the name of the target playlist."""
        if not self.playlist_id:
            return "No Playlist Selected"
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
        Supports:
            - https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=...
            - https://open.spotify.com/intl-es/track/4cOdK2wGLETKBW3PvgPWqT?si=...
            - spotify:track:4cOdK2wGLETKBW3PvgPWqT
            - Direct 22-character ID
        """
        query = query.strip()
        # Direct track ID match (22 alphanumeric chars)
        if re.fullmatch(r"[0-9A-Za-z]{22}", query):
            return query

        # URI match (spotify:track:ID)
        uri_match = re.search(r"spotify:track:([0-9A-Za-z]{22})", query)
        if uri_match:
            return uri_match.group(1)

        # URL match (supports international localized links like /intl-es/track/ID and query parameters)
        url_match = re.search(r"open\.spotify\.com/(?:intl-[a-z]{2}/)?track/([0-9A-Za-z]{22})", query)
        if url_match:
            return url_match.group(1)

        return None

    @staticmethod
    def _format_track_dict(track: Dict[str, Any]) -> Dict[str, Any]:
        """Formats a raw Spotify track API object into standard dictionary."""
        artists = [a["name"] for a in track.get("artists", [])]
        return {
            "id": track["id"],
            "uri": track["uri"],
            "name": track["name"],
            "artists": artists,
            "artist_str": ", ".join(artists) if artists else "Unknown Artist",
            "duration_ms": track.get("duration_ms", 0),
            "external_url": track.get("external_urls", {}).get("spotify", "")
        }

    @staticmethod
    def _rank_candidates(query: str, items: list) -> list:
        """
        Ranks candidates by title similarity, word coverage, and relevance,
        penalizing spam, karaoke, tribute bands, covers, and instrumental tracks
        unless the user explicitly asked for them.
        """
        if not items:
            return []

        query_clean = query.lower().strip()
        user_wants_karaoke = "karaoke" in query_clean
        user_wants_cover = "cover" in query_clean
        user_wants_live = "live" in query_clean
        user_wants_instrumental = "instrumental" in query_clean
        user_wants_remix = "remix" in query_clean
        user_wants_tribute = "tribute" in query_clean

        query_tokens = set(re.findall(r"\w+", query_clean))

        scored = []
        for idx, t in enumerate(items):
            name = (t.get("name") or "").lower()
            artists = [(a.get("name") or "").lower() for a in t.get("artists", [])]
            artists_str = " ".join(artists)
            full_track_str = f"{name} {artists_str}"
            track_tokens = set(re.findall(r"\w+", full_track_str))

            # Base score preserves Spotify's default algorithmic preference
            # Index 0 gets +10, index 9 gets +1
            score = 10.0 - (idx * 0.9)

            # Popularity contribution if available
            pop = t.get("popularity")
            if isinstance(pop, (int, float)):
                score += (pop / 100.0) * 20.0

            # Sequence similarity against title alone or full title+artist
            sim_title = SequenceMatcher(None, query_clean, name).ratio()
            sim_full = SequenceMatcher(None, query_clean, full_track_str).ratio()
            score += max(sim_title, sim_full) * 35.0

            # Token overlap: fraction of user's query words found in track title or artists
            if query_tokens:
                matched_tokens = query_tokens.intersection(track_tokens)
                token_ratio = len(matched_tokens) / len(query_tokens)
                score += token_ratio * 35.0

            # Exact title match bonus
            if name == query_clean:
                score += 20.0

            # Exact artist match bonus
            for art in artists:
                if art in query_clean or query_clean in art:
                    score += 15.0
                    break

            # Penalties for junk / low-quality / unwanted track types
            if not user_wants_karaoke and "karaoke" in name:
                score -= 70.0
            if not user_wants_cover and not user_wants_tribute and any(
                x in name for x in ["originally performed", "tribute to", "tribute band", "in the style of"]
            ):
                score -= 60.0
            if not user_wants_cover and "cover" in name:
                score -= 40.0
            if not user_wants_instrumental and "instrumental" in name:
                score -= 45.0
            if not user_wants_remix and "remix" in name:
                score -= 15.0
            if not user_wants_live and any(
                x in name for x in ["live at", "live in", "live from", "(live)", "- live"]
            ):
                score -= 15.0

            scored.append((score, t))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored]

    def search_track(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Resolves a search query (free text or Spotify link/URI) into a track object.
        Uses a multi-tier search process:
          1. Direct Spotify URL / URI / ID extraction (supports localized intl-* links)
          2. Delimiter parsing ('Artist - Title' or 'Title by Artist') using Spotify field filters
          3. Sanitized broad search with candidate ranking and junk/karaoke filtering
        """
        query = query.strip()
        if not query:
            return None

        # -------------------------------------------------------------
        # Tier 1: Direct Spotify Link / URI / ID
        # -------------------------------------------------------------
        track_id = self.extract_track_id(query)
        if track_id:
            try:
                track = self.sp.track(track_id)
                if track:
                    return self._format_track_dict(track)
            except Exception as e:
                logger.warning(f"Failed to fetch track by direct ID {track_id}: {e}")

        # -------------------------------------------------------------
        # Tier 2: Structured Query Detection ('Artist - Title', 'Title by Artist', etc.)
        # -------------------------------------------------------------
        candidate_items = []
        delimiters = [" - ", " – ", " — ", " by ", " // "]
        detected_parts = None

        for delim in delimiters:
            if delim in query.lower() if delim == " by " else delim in query:
                parts = re.split(re.escape(delim), query, flags=re.IGNORECASE, maxsplit=1)
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    detected_parts = (parts[0].strip(), parts[1].strip())
                    break

        if detected_parts:
            part1, part2 = detected_parts
            # Try both (artist, track) and (track, artist)
            structured_queries = [
                f'track:"{part2}" artist:"{part1}"',
                f'track:"{part1}" artist:"{part2}"'
            ]
            for sq in structured_queries:
                try:
                    res = self.sp.search(q=sq, type="track", limit=5)
                    items = res.get("tracks", {}).get("items", [])
                    if items:
                        candidate_items.extend(items)
                except Exception as e:
                    logger.debug(f"Structured search '{sq}' error: {e}")

        # -------------------------------------------------------------
        # Tier 3: Sanitized Broad Search with Candidate Ranking
        # -------------------------------------------------------------
        if not candidate_items:
            # Replace hyphens/dashes with spaces to prevent Spotify Lucene negation
            clean_query = re.sub(r"[-–—]", " ", query)
            clean_query = re.sub(r"\s+", " ", clean_query).strip()

            try:
                res = self.sp.search(q=clean_query, type="track", limit=10)
                items = res.get("tracks", {}).get("items", [])
                if items:
                    candidate_items.extend(items)
            except Exception as e:
                logger.error(f"Spotify broad search error for '{clean_query}': {e}")

        if not candidate_items:
            return None

        # Deduplicate items by track ID while preserving order
        seen_ids = set()
        unique_items = []
        for item in candidate_items:
            t_id = item.get("id")
            if t_id and t_id not in seen_ids:
                seen_ids.add(t_id)
                unique_items.append(item)

        # Rank candidates using intelligent scoring
        ranked = self._rank_candidates(query, unique_items)
        if not ranked:
            return None

        best_track = ranked[0]
        return self._format_track_dict(best_track)

    def is_track_in_playlist(self, track_uri: str, limit_check: int = 100) -> bool:
        """
        Checks if the track is already present in the most recent items of the playlist.
        """
        if not self.playlist_id:
            return False
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
        if not self.playlist_id:
            return False, "Target Spotify playlist is not configured.", None

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
