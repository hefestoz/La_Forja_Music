import unittest
from unittest.mock import patch, MagicMock
from src.youtube_service import YouTubeService

class TestYouTubeService(unittest.TestCase):

    def setUp(self):
        self.service = YouTubeService()

    def test_extract_video_id(self):
        cases = [
            ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ?si=test12345", "dQw4w9WgXcQ"),
            ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&feature=share", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("invalid_query_text", None),
        ]
        for query, expected in cases:
            self.assertEqual(self.service.extract_video_id(query), expected)

    def test_extract_playlist_id(self):
        cases = [
            ("https://www.youtube.com/playlist?list=PL1234567890abcdef", "PL1234567890abcdef"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1234567890abcdef", "PL1234567890abcdef"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", None),
        ]
        for query, expected in cases:
            self.assertEqual(self.service.extract_playlist_id(query), expected)

    def test_clean_title(self):
        t1, a1 = self.service.clean_title("Rick Astley - Never Gonna Give You Up (Official Music Video)", "RickAstleyVEVO")
        self.assertEqual(t1, "Never Gonna Give You Up")
        self.assertEqual(a1, "Rick Astley")

        t2, a2 = self.service.clean_title("Queen - Bohemian Rhapsody [Remastered 2011]", "Queen Official")
        self.assertEqual(t2, "Bohemian Rhapsody")
        self.assertEqual(a2, "Queen")

        t3, a3 = self.service.clean_title("Get Lucky", "Daft Punk")
        self.assertEqual(t3, "Get Lucky")
        self.assertEqual(a3, "Daft Punk")

    @patch("src.youtube_service.requests.get")
    def test_get_video_details_by_id_oembed(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "title": "Michael Jackson - Billie Jean (Official Video)",
            "author_name": "Michael Jackson"
        }
        mock_get.return_value = mock_resp

        details = self.service.get_video_details_by_id("dQw4w9WgXcQ")
        self.assertIsNotNone(details)
        self.assertEqual(details["id"], "dQw4w9WgXcQ")
        self.assertEqual(details["name"], "Billie Jean")
        self.assertEqual(details["artist_str"], "Michael Jackson")
        self.assertEqual(details["album_art"], "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")

    @patch("src.youtube_service.requests.get")
    def test_add_song_request_and_queue(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "title": "Daft Punk - One More Time",
            "author_name": "Daft Punk"
        }
        mock_get.return_value = mock_resp

        # 1. Add first song
        ok, msg, track = self.service.add_song_request(
            query="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            requested_by="StreamerFan",
            prevent_duplicates=True
        )
        self.assertTrue(ok)
        self.assertIn("One More Time", msg)
        self.assertEqual(track["id"], "dQw4w9WgXcQ")

        # Currently playing should be this first song
        playing = self.service.get_currently_playing()
        self.assertIsNotNone(playing)
        self.assertEqual(playing["id"], "dQw4w9WgXcQ")
        self.assertEqual(playing["title"], "One More Time")
        self.assertEqual(playing["requested_by"], "StreamerFan")
        self.assertTrue(playing["is_playing"])

        # 2. Duplicate prevention
        ok_dup, msg_dup, _ = self.service.add_song_request(
            query="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            requested_by="AnotherUser",
            prevent_duplicates=True
        )
        self.assertFalse(ok_dup)
        self.assertIn("already in the queue", msg_dup)

        # 3. Add second song
        mock_resp.json.return_value = {
            "title": "M83 - Midnight City",
            "author_name": "M83"
        }
        ok2, msg2, track2 = self.service.add_song_request(
            query="https://www.youtube.com/watch?v=F2AitTPI5U0",
            requested_by="SynthwaveFan",
            prevent_duplicates=True
        )
        self.assertTrue(ok2)
        # Song 1 is currently playing, Song 2 is pending in queue
        self.assertEqual(self.service.get_currently_playing()["id"], "dQw4w9WgXcQ")
        self.assertEqual(len(self.service.get_queue()), 1)
        self.assertEqual(self.service.get_queue()[0]["id"], "F2AitTPI5U0")

        # 4. Advance to next track (pops Song 2 from pending queue)
        next_track = self.service.pop_next_track()
        self.assertEqual(next_track["id"], "F2AitTPI5U0")
        self.assertEqual(self.service.get_currently_playing()["id"], "F2AitTPI5U0")

        # 5. Queue is now empty, popping again returns None
        self.assertIsNone(self.service.pop_next_track())
        self.assertIsNone(self.service.get_currently_playing())

    @patch("src.youtube_service.requests.get")
    def test_duration_limit_rejection(self, mock_get):
        """Videos longer than max_duration_seconds must be rejected."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "title": "3 Hour Study Podcast - Ambient Talk",
            "author_name": "PodcastHost"
        }
        mock_resp.text = '{"lengthSeconds":"10800","category":"Education"}'
        mock_get.return_value = mock_resp

        service = YouTubeService(music_only=True, max_duration_seconds=600)
        ok, msg, track = service.add_song_request("https://www.youtube.com/watch?v=longpodcast0", requested_by="Viewer")
        self.assertFalse(ok)
        self.assertIn("too long", msg)

    @patch("src.youtube_service.requests.get")
    def test_non_music_rejection(self, mock_get):
        """Non-music videos (e.g. Gaming walkthrough) must be rejected when music_only=True."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "title": "Minecraft Hardcore Episode 1 - Survival Gameplay",
            "author_name": "ProGamer123"
        }
        mock_resp.text = '{"lengthSeconds":"300","category":"Gaming"}'
        mock_get.return_value = mock_resp

        service = YouTubeService(music_only=True, max_duration_seconds=600)
        ok, msg, track = service.add_song_request("https://www.youtube.com/watch?v=gamergame001", requested_by="Viewer")
        self.assertFalse(ok)
        self.assertIn("Only music", msg)

    @patch("src.youtube_service.requests.get")
    def test_music_video_accepted(self, mock_get):
        """Legitimate music tracks under 10 minutes must be accepted."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "title": "Coldplay - Viva La Vida",
            "author_name": "Coldplay - Topic"
        }
        mock_resp.text = '{"lengthSeconds":"242","category":"Music"}'
        mock_get.return_value = mock_resp

        service = YouTubeService(music_only=True, max_duration_seconds=600)
        ok, msg, track = service.add_song_request("https://www.youtube.com/watch?v=vivalavida00", requested_by="Viewer")
        self.assertTrue(ok)
        self.assertIn("Viva La Vida", msg)

    def test_controls(self):
        self.service.set_volume(75)
        self.assertEqual(self.service._volume, 75)

        self.service.set_volume(150)
        self.assertEqual(self.service._volume, 100)

        self.service.set_volume(-10)
        self.assertEqual(self.service._volume, 0)

        self.service._is_playing = True
        self.service.toggle_playback()
        self.assertFalse(self.service._is_playing)
        self.service.toggle_playback()
        self.assertTrue(self.service._is_playing)

        self.service._queue = [{"id": "1"}, {"id": "2"}]
        self.service.clear_playlist()
        self.assertEqual(len(self.service._queue), 0)

if __name__ == "__main__":
    unittest.main()
