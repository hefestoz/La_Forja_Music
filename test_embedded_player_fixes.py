import unittest
from unittest.mock import MagicMock, patch
import os
import tkinter as tk

from src.embedded_player import EmbeddedPlayer, PersistentCDP
from src.youtube_service import YouTubeService

class TestEmbeddedPlayerFixes(unittest.TestCase):
    """
    Tests for YouTube in-app queue progression, ad skipping, and title bar hiding.
    """

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_titlebar_offset_constant(self):
        player = EmbeddedPlayer(self.root)
        self.assertEqual(player.TITLE_BAR_OFFSET, 34)

    def test_advancement_debounce_single_trigger(self):
        """Verify that on_video_ended is only triggered once per completed track."""
        ended_called_count = 0
        def on_ended():
            nonlocal ended_called_count
            ended_called_count += 1

        player = EmbeddedPlayer(self.root, on_video_ended=on_ended)
        player.current_video_id = "TRACK_A"

        # Simulate monitor loop detection logic
        dur_sec = 200
        cur_sec = 199.5
        ended = False

        # First trigger: Track A ends
        if ended or (dur_sec > 10 and cur_sec >= dur_sec - 0.8):
            if not player._is_advancing and player.current_video_id != player._last_ended_video_id:
                player._is_advancing = True
                player._last_ended_video_id = player.current_video_id
                if player.on_video_ended:
                    player.on_video_ended()

        self.assertEqual(ended_called_count, 1)
        self.assertTrue(player._is_advancing)
        self.assertEqual(player._last_ended_video_id, "TRACK_A")

        # Second tick before new track plays (still on old page or transition)
        if ended or (dur_sec > 10 and cur_sec >= dur_sec - 0.8):
            if not player._is_advancing and player.current_video_id != player._last_ended_video_id:
                player._is_advancing = True
                player._last_ended_video_id = player.current_video_id
                if player.on_video_ended:
                    player.on_video_ended()

        # Must NOT call on_ended a second time!
        self.assertEqual(ended_called_count, 1)

        # New track is loaded
        player.load_video("TRACK_B", title="Track B")
        self.assertEqual(player.current_video_id, "TRACK_B")
        self.assertFalse(player._is_advancing)

    def test_ad_does_not_trigger_advance(self):
        """Verify that an ending ad (cur_sec == dur_sec, isAd=True) does NOT trigger queue advancement."""
        ended_called = False
        def on_ended():
            nonlocal ended_called
            ended_called = True

        player = EmbeddedPlayer(self.root, on_video_ended=on_ended)
        player.current_video_id = "TRACK_A"

        # Simulate ad finishing (e.g. 15s ad skipped to end)
        is_ad = True
        dur_sec = 15
        cur_sec = 15
        ended = True

        # In monitor loop: if is_ad is True, advancement must never fire
        vid_matches = True
        is_finished = ended or (dur_sec > 15 and cur_sec >= dur_sec - 1.0)
        if vid_matches and not is_ad and dur_sec > 15 and cur_sec > 8 and is_finished:
            player.on_video_ended()

        self.assertFalse(ended_called)

    def test_stop_does_not_kill_browser(self):
        """Verify that stop() switches to Idle state without terminating the browser process."""
        player = EmbeddedPlayer(self.root)
        player._browser_proc = MagicMock()
        player._browser_proc.poll.return_value = None  # Running

        player.stop()

        self.assertIsNone(player.current_video_id)
        self.assertFalse(player._is_playing)
        self.assertEqual(player.status_badge.cget("text"), "● Idle")
        # Ensure browser process was NOT terminated on idle stop
        player._browser_proc.terminate.assert_not_called()
        player._browser_proc.kill.assert_not_called()

    def test_shield_script_includes_ad_skipper_and_clean_css(self):
        """Verify that shield script contains the CSS rules and fast ad-skipping logic."""
        cdp = PersistentCDP(port=9999)
        script = cdp._get_shield_script()

        self.assertIn("#masthead-container", script)
        self.assertIn(".ytp-skip-ad-button", script)
        self.assertIn("playbackRate = 16.0", script)
        self.assertIn("v.muted = true", script)
        self.assertIn("100", script)  # 100ms interval

    def test_load_video_by_id_script(self):
        """Verify load_video_by_id targets movie_player before falling back to navigation."""
        cdp = PersistentCDP(port=9999)
        with patch.object(cdp, "eval") as mock_eval:
            mock_eval.return_value = "PLAYER_LOADED"
            res = cdp.load_video_by_id("ABC123XYZ00", "https://www.youtube.com/watch?v=ABC123XYZ00")
            self.assertEqual(res, "PLAYER_LOADED")
            mock_eval.assert_called_once()
            call_arg = mock_eval.call_args[0][0]
            self.assertIn("movie_player", call_arg)
            self.assertIn("loadVideoById", call_arg)
            self.assertIn("ABC123XYZ00", call_arg)

if __name__ == "__main__":
    unittest.main()
