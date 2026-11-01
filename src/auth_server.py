import os
import json
import threading
import logging
from typing import Optional, Callable, Any
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger("AuthServer")

SUCCESS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Connected - La Forja Music</title>
  <style>
    body {
      background: #0f1015;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #FFFFFF;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100vh;
      margin: 0;
    }
    .card {
      background: #181a22;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 18px;
      padding: 36px 44px;
      text-align: center;
      box-shadow: 0 12px 36px rgba(0,0,0,0.6);
      max-width: 440px;
    }
    .icon {
      font-size: 48px;
      margin-bottom: 12px;
    }
    h2 {
      margin: 0 0 10px 0;
      color: #1DB954;
      font-size: 22px;
    }
    p {
      color: #9499AD;
      font-size: 14px;
      line-height: 1.5;
      margin: 0 0 16px 0;
    }
    .hint {
      display: inline-block;
      background: rgba(29, 185, 84, 0.15);
      color: #1DB954;
      font-weight: 600;
      font-size: 12px;
      padding: 6px 14px;
      border-radius: 8px;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon" id="card-icon">🎧</div>
    <h2 id="title-msg">Account Connected!</h2>
    <p id="status-msg">Your authentication with <strong>La Forja Music</strong> was successful.</p>
    <div class="hint" id="close-hint">You can safely close this browser window and return to the app.</div>
  </div>

  <script>
    (function() {
      // Check if access_token is present in the URL hash (Twitch Implicit Grant)
      if (window.location.hash && window.location.hash.length > 1) {
        const hash = window.location.hash.substring(1);
        const params = new URLSearchParams(hash);
        const access_token = params.get('access_token');
        if (access_token) {
          const status_elem = document.getElementById('status-msg');
          const title_elem = document.getElementById('title-msg');
          const icon_elem = document.getElementById('card-icon');
          if (status_elem) status_elem.innerText = "Transmitting Twitch credentials to La Forja Music...";

          fetch('/callback/twitch?token=' + encodeURIComponent(access_token))
            .then(res => res.json())
            .then(data => {
              if (data && data.status === 'ok') {
                if (icon_elem) icon_elem.innerText = "🟣";
                if (title_elem) {
                  title_elem.innerText = "Twitch Connected!";
                  title_elem.style.color = "#9146FF";
                }
                if (status_elem) {
                  status_elem.innerHTML = "Linked Twitch channel: <strong>@" + (data.login || 'streamer') + "</strong>.<br>You can safely close this window.";
                }
              }
            })
            .catch(err => {
              console.error("Failed to forward Twitch token:", err);
            });
        }
      }
    })();
  </script>
</body>
</html>
"""

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles incoming OAuth redirects from browser."""

    server_instance: Any = None

    def log_message(self, format, *args):
        # Suppress noisy standard server access logs
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        # 1. Handle Twitch hash redirect token
        if parsed.path.startswith("/callback/twitch"):
            token = qs.get("token", [None])[0]
            login_detected = None
            if token and self.server_instance and self.server_instance.on_twitch_token_callback:
                logger.info("Twitch access token received via hash loopback handler.")
                threading.Thread(target=self.server_instance.on_twitch_token_callback, args=(token,), daemon=True).start()
                try:
                    from src.twitch_service import validate_twitch_token
                    _, login_detected, _, _ = validate_twitch_token(token)
                except Exception:
                    pass

            response_data = {"status": "ok", "login": login_detected or ""}
            body = json.dumps(response_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 2. Handle Spotify or code grant redirect
        code = qs.get("code", [None])[0]
        if code and self.server_instance and self.server_instance.on_code_callback:
            logger.info("OAuth code received via loopback server.")
            threading.Thread(target=self.server_instance.on_code_callback, args=(code,), daemon=True).start()

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        body = SUCCESS_HTML.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

class OAuthServer:
    """
    Ephemeral loopback web server for capturing OAuth redirects.
    Runs on a dedicated background daemon thread.
    """

    def __init__(
        self,
        port: int = 8888,
        on_code_callback: Optional[Callable[[str], None]] = None,
        on_twitch_token_callback: Optional[Callable[[str], None]] = None
    ):
        self.port = port
        self.on_code_callback = on_code_callback
        self.on_twitch_token_callback = on_twitch_token_callback
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._is_running = False

    def set_on_code_callback(self, cb: Optional[Callable[[str], None]]) -> None:
        self.on_code_callback = cb

    def set_on_twitch_token_callback(self, cb: Optional[Callable[[str], None]]) -> None:
        self.on_twitch_token_callback = cb

    def start(self) -> bool:
        """Starts the loopback server on a background thread."""
        if self._is_running:
            return True

        try:
            handler_class = OAuthCallbackHandler
            handler_class.server_instance = self
            self._server = HTTPServer(("127.0.0.1", self.port), handler_class)
            self._is_running = True

            def serve():
                logger.info(f"OAuth Loopback server listening on http://127.0.0.1:{self.port}/callback")
                while self._is_running and self._server:
                    try:
                        self._server.handle_request()
                    except Exception:
                        pass

            self._thread = threading.Thread(target=serve, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            logger.error(f"Failed to start OAuth loopback server on port {self.port}: {e}")
            return False

    def stop(self) -> None:
        """Stops and cleans up the loopback server."""
        self._is_running = False
        if self._server:
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        logger.info("OAuth Loopback server stopped.")
