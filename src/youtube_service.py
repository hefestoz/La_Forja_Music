import os
import re
import json
import time
import logging
import urllib.parse
from typing import Optional, Dict, Any, Tuple, List
import requests

from src.base_music_service import BaseMusicService

logger = logging.getLogger("YouTubeService")

class YouTubeService(BaseMusicService):
    """
    No-Login YouTube music & song request engine.
    - Zero Google accounts or API keys required.
    - Resolves direct YouTube links or searches music titles via public endpoints.
    - Filters and restricts requests strictly to music/songs under max duration limit.
    - Maintains an in-memory stream queue with duplicate prevention and requester history.
    - Synchronizes state with the in-app embedded player and OBS overlay.
    """

    def __init__(
        self,
        initial_playlist: Optional[str] = None,
        music_only: bool = True,
        max_duration_seconds: int = 600
    ):
        self.initial_playlist_url = initial_playlist or ""
        self.initial_playlist_id = self.extract_playlist_id(self.initial_playlist_url)
        self.music_only = music_only
        self.max_duration_seconds = max_duration_seconds

        self._queue: List[Dict[str, Any]] = []
        self._history: List[Dict[str, Any]] = []
        self._recent_requests: List[Dict[str, Any]] = []
        self._current_track: Optional[Dict[str, Any]] = None
        self._is_playing: bool = False
        self._volume: int = 100
        self._progress_ms: int = 0
        self._search_cache: Dict[str, Dict[str, Any]] = {}

    @property
    def service_type(self) -> str:
        return "youtube"

    def is_authorized(self) -> bool:
        """No-Login mode is always authorized and ready to accept requests."""
        return True

    def get_playlist_name(self) -> str:
        """Returns name of the active playlist/queue."""
        if self.initial_playlist_id:
            return f"YouTube Playlist ({self.initial_playlist_id})"
        return "YouTube In-App Stream Queue"

    # ------------------------------------------------------------------
    # URL & ID Extraction Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def extract_video_id(query: str) -> Optional[str]:
        """
        Extracts the 11-character YouTube video ID from various link formats or raw ID.
        Supports:
            - https://www.youtube.com/watch?v=dQw4w9WgXcQ
            - https://youtu.be/dQw4w9WgXcQ
            - https://music.youtube.com/watch?v=dQw4w9WgXcQ
            - https://www.youtube.com/embed/dQw4w9WgXcQ
            - Raw 11-char ID (e.g. dQw4w9WgXcQ)
        """
        q = query.strip()
        if re.fullmatch(r"[0-9A-Za-z_-]{11}", q):
            return q

        m = re.search(r"youtu\.be/([0-9A-Za-z_-]{11})", q)
        if m:
            return m.group(1)

        m = re.search(r"(?:youtube\.com|music\.youtube\.com)/watch\?(?:.*&)?v=([0-9A-Za-z_-]{11})", q)
        if m:
            return m.group(1)

        m = re.search(r"youtube\.com/(?:embed|v)/([0-9A-Za-z_-]{11})", q)
        if m:
            return m.group(1)

        return None

    @staticmethod
    def extract_playlist_id(query: str) -> Optional[str]:
        """Extracts playlist ID from a YouTube playlist URL."""
        if not query:
            return None
        m = re.search(r"[?&]list=([0-9A-Za-z_-]+)", query.strip())
        if m:
            return m.group(1)
        return None

    @staticmethod
    def clean_title(raw_title: str, author_name: str = "") -> Tuple[str, str]:
        """
        Cleans video title suffixes like '(Official Music Video)', '[Lyrics]' and splits
        'Artist - Title' into (title, artist) components.
        """
        cleaned = re.sub(
            r"\s*[\(\[](?:Official|Music|Video|Audio|Lyric|Lyrics|HD|4K|Visualizer|Remastered)[\w\s\.\-]*[\)\]]",
            "",
            raw_title,
            flags=re.IGNORECASE
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        for delim in [" - ", " – ", " — "]:
            if delim in cleaned:
                parts = cleaned.split(delim, 1)
                artist = parts[0].strip()
                title = parts[1].strip()
                return title, artist

        return cleaned or raw_title, author_name or "YouTube Artist"

    # ------------------------------------------------------------------
    # Track Lookup & Public Search (No API Key Required)
    # ------------------------------------------------------------------
    def get_video_details_by_id(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves video title, author, duration, category, and thumbnail.
        Checks whether the video is music and measures duration for limit enforcement.
        Zero API keys required.
        """
        if video_id in self._search_cache:
            return dict(self._search_cache[video_id])

        url = f"https://www.youtube.com/watch?v={video_id}"
        oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"

        raw_title = f"YouTube Video ({video_id})"
        author = "YouTube"
        duration_sec = 0
        category = "Unknown"
        is_music = True

        # 1. Fetch official title & author via public oEmbed
        try:
            resp = requests.get(oembed_url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                raw_title = data.get("title", raw_title)
                author = data.get("author_name", author)
        except Exception as e:
            logger.debug(f"oEmbed lookup failed for {video_id}: {e}")

        # 2. Fetch watch page metadata for duration and category verification
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9"
            }
            watch_resp = requests.get(url, headers=headers, timeout=5)
            if watch_resp.status_code == 200:
                html = watch_resp.text

                # Extract Duration
                dur_match = re.search(r'"lengthSeconds":"(\d+)"', html)
                if dur_match:
                    duration_sec = int(dur_match.group(1))
                else:
                    approx_dur = re.search(r'"approxDurationMs":"(\d+)"', html)
                    if approx_dur:
                        duration_sec = int(int(approx_dur.group(1)) / 1000)

                # Extract Category
                cat_match = re.search(r'"category":"([^"]+)"', html)
                if not cat_match:
                    cat_match = re.search(r'itemprop="genre" content="([^"]+)"', html)
                if cat_match:
                    category = cat_match.group(1)

                is_music_category = (category.lower() == "music")
                has_music_channel = author.endswith(" - Topic") or "vevo" in author.lower()
                has_music_title = bool(re.search(
                    r"\b(official\s+(?:audio|video|music\s+video|lyric\s+video)|lyrics?|soundtrack|ost|remix|cover|feat\.?|ft\.?)\b",
                    raw_title,
                    re.I
                ))

                non_music_categories = {
                    "gaming", "news & politics", "howto & style", "science & technology",
                    "travel & events", "people & blogs", "film & animation", "sports",
                    "autos & vehicles", "pets & animals", "comedy", "entertainment"
                }

                if is_music_category or has_music_channel or has_music_title:
                    is_music = True
                elif category.lower() in non_music_categories:
                    # Explicit non-music category without any song indicators
                    is_music = False
                else:
                    is_music = True
        except Exception as e:
            logger.debug(f"Watch page metadata lookup failed for {video_id}: {e}")

        title, artist = self.clean_title(raw_title, author)

        track_dict = {
            "id": video_id,
            "uri": f"youtube:video:{video_id}",
            "name": title,
            "artists": [artist],
            "artist_str": artist,
            "album_name": "YouTube",
            "album_art": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "duration_ms": duration_sec * 1000,
            "duration_sec": duration_sec,
            "category": category,
            "is_music": is_music,
            "external_url": url
        }
        self._search_cache[video_id] = track_dict
        return track_dict

    def search_track(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Resolves a search query (direct URL/ID or song text) into a track object.
        Automatically steers queries toward music/audio when music_only is enabled.
        Zero API keys required.
        """
        q = query.strip()
        if not q:
            return None

        # Check in-memory cache
        if q in self._search_cache:
            return dict(self._search_cache[q])

        # 1. Direct Link or ID
        vid = self.extract_video_id(q)
        if vid:
            track = self.get_video_details_by_id(vid)
            if track:
                self._search_cache[q] = track
                return track

        # 2. Public YouTube Search Query
        # If music_only is enabled, steer search terms toward music/audio
        search_query = q
        if self.music_only:
            q_lower = q.lower()
            if not any(k in q_lower for k in ["music", "song", "audio", "video", "official", "remix"]):
                search_query = f"{q} song"

        encoded_q = urllib.parse.quote(search_query)
        search_url = f"https://www.youtube.com/results?search_query={encoded_q}&sp=EgIQAQ%253D%253D"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9"
        }

        try:
            resp = requests.get(search_url, headers=headers, timeout=6)
            if resp.status_code == 200:
                html = resp.text

                # Parse videoId from ytInitialData or regex fallback
                vid_matches = re.findall(r"\"videoId\":\"([0-9A-Za-z_-]{11})\"", html)
                if not vid_matches:
                    vid_matches = re.findall(r"/watch\?v=([0-9A-Za-z_-]{11})", html)

                if vid_matches:
                    # Test candidate videos for validity & music criteria
                    for candidate_id in vid_matches[:5]:
                        track = self.get_video_details_by_id(candidate_id)
                        if track:
                            if self.music_only and not track.get("is_music", True):
                                continue
                            self._search_cache[q] = track
                            return track

                    # Fallback to first found video if loop exhausted
                    first_vid = vid_matches[0]
                    track = self.get_video_details_by_id(first_vid)
                    if track:
                        self._search_cache[q] = track
                        return track
        except Exception as e:
            logger.debug(f"Public YouTube search failed for query '{q}': {e}")

        return None

    # ------------------------------------------------------------------
    # Song Request Processing
    # ------------------------------------------------------------------
    def is_track_in_queue(self, video_id: str) -> bool:
        """Checks if the video is already in the queue or currently playing."""
        if self._current_track and self._current_track.get("id") == video_id:
            return True
        for item in self._queue:
            if item.get("id") == video_id:
                return True
        return False

    def add_song_request(
        self,
        query: str,
        requested_by: str = "Anonymous",
        prevent_duplicates: bool = True
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Main entry point for song requests from chat (!sr).
        Resolves track, validates duration and music policy, prevents duplicates,
        and queues the song cleanly without interrupting currently playing music.
        """
        track = self.search_track(query)
        if not track:
            return False, f"Could not find any song matching '{query}' on YouTube.", None

        vid = track["id"]
        title_str = f"\"{track['name']}\" by {track['artist_str']}"

        # 1. Duplicate check
        if prevent_duplicates and self.is_track_in_queue(vid):
            return False, f"{title_str} is already in the queue!", track

        # 2. Duration limit check (default max 10 minutes = 600 seconds)
        duration_sec = track.get("duration_sec", 0)
        if self.max_duration_seconds > 0 and duration_sec > self.max_duration_seconds:
            dur_m = duration_sec // 60
            dur_s = duration_sec % 60
            max_m = self.max_duration_seconds // 60
            return False, f"{title_str} is too long ({dur_m}m {dur_s:02d}s). Maximum allowed length is {max_m} minutes!", track

        # 3. Music-only policy check
        if self.music_only and not track.get("is_music", True):
            return False, f"{title_str} does not appear to be a song/music video. Only music can be requested in this stream!", track

        now = time.time()
        queue_item = dict(track)
        queue_item["requested_by"] = requested_by
        queue_item["time"] = now

        # Recent requests for UI & OBS overlay
        self._recent_requests.insert(0, {
            "title": track["name"],
            "artist": track["artist_str"],
            "requested_by": requested_by,
            "time": now,
            "url": track["external_url"]
        })
        if len(self._recent_requests) > 30:
            self._recent_requests.pop()

        # If nothing is currently loaded/playing, set as active track.
        # If a song is actively playing, ALWAYS append to queue to never replace the playing song!
        if self._current_track is None or not self._is_playing:
            self._current_track = queue_item
            self._progress_ms = 0
            self._is_playing = True
            logger.info(f"[YouTube Play] Set as active track: {title_str} (requested by {requested_by})")
        else:
            self._queue.append(queue_item)
            logger.info(f"[YouTube Queue] Placed in queue: {title_str} (requested by {requested_by}). Queue pending: {len(self._queue)}")

        return True, f"Added {title_str} to the queue! (requested by {requested_by})", track

    # ------------------------------------------------------------------
    # Playback & State Reporting
    # ------------------------------------------------------------------
    def get_currently_playing(self) -> Optional[Dict[str, Any]]:
        """Returns details of the currently loaded/playing track."""
        if not self._current_track:
            return None

        t = self._current_track
        return {
            "id": t.get("id"),
            "uri": t.get("uri"),
            "title": t.get("name"),
            "artists": t.get("artists", ["YouTube Artist"]),
            "artist_str": t.get("artist_str", "YouTube Artist"),
            "album_name": t.get("album_name", "YouTube"),
            "album_art": t.get("album_art", f"https://i.ytimg.com/vi/{t.get('id')}/hqdefault.jpg"),
            "duration_ms": t.get("duration_ms", 0),
            "progress_ms": self._progress_ms,
            "is_playing": self._is_playing,
            "volume_percent": self._volume,
            "requested_by": t.get("requested_by")
        }

    def get_recent_requests(self) -> List[Dict[str, Any]]:
        """Returns recent requests list for OBS overlay /queue endpoint."""
        return list(self._recent_requests)

    def get_queue(self) -> List[Dict[str, Any]]:
        """Returns the active queue of pending tracks."""
        return list(self._queue)

    def pop_next_track(self) -> Optional[Dict[str, Any]]:
        """Pops and advances to the next track in the queue."""
        if self._current_track:
            self._history.append(self._current_track)

        if self._queue:
            self._current_track = self._queue.pop(0)
            self._progress_ms = 0
            self._is_playing = True
            logger.info(f"[YouTube Next] Playing: {self._current_track.get('name')} by {self._current_track.get('artist_str')}")
            return self._current_track
        else:
            self._current_track = None
            self._is_playing = False
            return None

    def next_track(self) -> bool:
        """Advances to the next track in queue."""
        next_t = self.pop_next_track()
        return next_t is not None

    def previous_track(self) -> bool:
        """Plays the previous track from history if available."""
        if self._history:
            if self._current_track:
                self._queue.insert(0, self._current_track)
            self._current_track = self._history.pop()
            self._progress_ms = 0
            self._is_playing = True
            return True
        elif self._current_track:
            self._progress_ms = 0
            return True
        return False

    def toggle_playback(self) -> bool:
        """Toggles play / pause."""
        self._is_playing = not self._is_playing
        return True

    def set_volume(self, volume_percent: int) -> bool:
        """Sets volume (0 - 100)."""
        self._volume = max(0, min(100, volume_percent))
        return True

    def clear_playlist(self) -> bool:
        """Clears all pending songs in the queue."""
        self._queue.clear()
        logger.info("[YouTube Queue] Queue cleared by user.")
        return True

    def update_progress(self, progress_ms: int, duration_ms: Optional[int] = None):
        """Called by the embedded player to update live playback progress."""
        self._progress_ms = progress_ms
        if duration_ms and self._current_track:
            self._current_track["duration_ms"] = duration_ms
