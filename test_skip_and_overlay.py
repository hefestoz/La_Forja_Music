import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock
from src.request_limiter import RequestLimiter
from src.twitch_service import TwitchBot
from src.tiktok_service import TikTokListener
from src.overlay_server import OverlayServer, get_local_lan_ip

def run_async(coro):
    stack = [coro]
    val = None
    while stack:
        try:
            nxt = stack[-1].send(val)
            val = None
            if hasattr(nxt, "__await__"):
                stack.append(nxt.__await__())
            elif hasattr(nxt, "send"):
                stack.append(nxt)
        except StopIteration as e:
            stack.pop()
            val = e.value
    return val

class TestSkipCommandAndOverlay(unittest.TestCase):

    def test_twitch_skip_by_requester(self):
        async def scenario():
            mock_spotify = MagicMock()
            mock_spotify.get_currently_playing.return_value = {
                "title": "Bohemian Rhapsody",
                "artist_str": "Queen",
                "requested_by": "alice"
            }
            mock_spotify.next_track.return_value = True

            limiter = RequestLimiter(broadcaster_username="streamer_boss")
            bot = TwitchBot(
                spotify_service=mock_spotify,
                request_limiter=limiter,
                channel="streamer_boss",
                token="oauth:fake",
                nick="streamer_boss"
            )
            bot.send_chat_message = AsyncMock()

            # 1. Non-requester bob tries to skip alice's song -> DENIED
            await bot.handle_skip_request("bob")
            mock_spotify.next_track.assert_not_called()
            bot.send_chat_message.assert_called_with("@bob Only @alice (the requester) can skip this song.")

            # 2. Requester alice skips her song -> APPROVED
            await bot.handle_skip_request("alice")
            mock_spotify.next_track.assert_called_once()
            self.assertIn("Skipped your song", bot.send_chat_message.call_args[0][0])
            self.assertIn("Bohemian Rhapsody", bot.send_chat_message.call_args[0][0])

        run_async(scenario())

    def test_twitch_skip_by_broadcaster(self):
        async def scenario():
            mock_spotify = MagicMock()
            mock_spotify.get_currently_playing.return_value = {
                "title": "Sandstorm",
                "artist_str": "Darude",
                "requested_by": "random_viewer"
            }
            mock_spotify.next_track.return_value = True

            limiter = RequestLimiter(broadcaster_username="streamer_boss")
            bot = TwitchBot(
                spotify_service=mock_spotify,
                request_limiter=limiter,
                channel="streamer_boss",
                token="oauth:fake",
                nick="streamer_boss"
            )
            bot.send_chat_message = AsyncMock()

            # Broadcaster can skip any song
            await bot.handle_skip_request("streamer_boss")
            mock_spotify.next_track.assert_called_once()
            self.assertIn("Broadcaster skipped", bot.send_chat_message.call_args[0][0])
            self.assertIn("@random_viewer", bot.send_chat_message.call_args[0][0])

        run_async(scenario())

    def test_twitch_skip_no_track_playing(self):
        async def scenario():
            mock_spotify = MagicMock()
            mock_spotify.get_currently_playing.return_value = None

            limiter = RequestLimiter(broadcaster_username="streamer_boss")
            bot = TwitchBot(
                spotify_service=mock_spotify,
                request_limiter=limiter,
                channel="streamer_boss",
                token="oauth:fake",
                nick="streamer_boss"
            )
            bot.send_chat_message = AsyncMock()

            await bot.handle_skip_request("alice")
            mock_spotify.next_track.assert_not_called()
            bot.send_chat_message.assert_called_with("@alice No song is currently playing.")

        run_async(scenario())

    def test_tiktok_skip_by_requester_and_denied_for_others(self):
        async def scenario():
            mock_spotify = MagicMock()
            mock_spotify.get_currently_playing.return_value = {
                "title": "Shape of You",
                "artist_str": "Ed Sheeran",
                "requested_by": "TikTok/dance_queen"
            }
            mock_spotify.next_track.return_value = True

            limiter = RequestLimiter(broadcaster_username="host_streamer")
            listener = TikTokListener(
                spotify_service=mock_spotify,
                request_limiter=limiter,
                unique_id="host_streamer"
            )

            # 1. Other user tries !skip -> DENIED
            await listener.handle_comment("other_user", "!skip", "Other User")
            mock_spotify.next_track.assert_not_called()

            # 2. Requester tries !skip -> APPROVED
            await listener.handle_comment("dance_queen", "!skip", "dance_queen")
            mock_spotify.next_track.assert_called_once()

        run_async(scenario())

    def test_overlay_server_handlers_and_lan_ip(self):
        async def scenario():
            mock_spotify = MagicMock()
            mock_spotify.get_currently_playing.return_value = {
                "title": "Test Song",
                "artist_str": "Test Artist",
                "is_playing": True
            }
            mock_spotify.get_recent_requests.return_value = []

            server = OverlayServer(spotify_service=mock_spotify, host="0.0.0.0", port=5000)
            self.assertEqual(server.host, "0.0.0.0")

            lan = get_local_lan_ip()
            self.assertTrue(isinstance(lan, str))
            self.assertTrue(len(lan) > 0)

            # Test overlay template handler
            req = MagicMock()
            resp = await server.handle_overlay(req)
            self.assertEqual(resp.status, 200)
            self.assertIn("OBS Now Playing Overlay", resp.text)

            # Test now-playing API handler
            np_resp = await server.handle_now_playing(req)
            self.assertEqual(np_resp.status, 200)
            data = json.loads(np_resp.text)
            self.assertEqual(data.get("title"), "Test Song")

        run_async(scenario())

if __name__ == "__main__":
    unittest.main()
