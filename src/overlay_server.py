import os
import socket
import asyncio
import logging
from aiohttp import web
from src.spotify_service import SpotifyService

logger = logging.getLogger("OverlayServer")

def get_local_lan_ip() -> str:
    """Detects active local IPv4 address for remote / Dual-PC OBS browser sources."""
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"

@web.middleware
async def cors_middleware(request, handler):
    """Ensures OBS Browser Source or remote widgets never get blocked by CORS."""
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

class OverlayServer:
    """
    Lightweight local web server serving the OBS Browser Source overlay
    and JSON APIs for playback status.
    Listens on 0.0.0.0 to accept connections from localhost (127.0.0.1),
    local LAN IP (for dual-PC setups), and virtual network adapters.
    """

    def __init__(self, spotify_service: SpotifyService, host: str = "0.0.0.0", port: int = 5000):
        self.spotify = spotify_service
        self.host = host
        self.port = port
        self.lan_ip = get_local_lan_ip()
        self.app = web.Application(middlewares=[cors_middleware])
        self._runner: web.AppRunner = None
        self._site: web.TCPSite = None
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_overlay)
        self.app.router.add_get("/overlay", self.handle_overlay)
        self.app.router.add_get("/player", self.handle_player)
        self.app.router.add_get("/api/now-playing", self.handle_now_playing)
        self.app.router.add_get("/api/queue", self.handle_queue)
        self.app.router.add_get("/api/health", self.handle_health)
        self.app.router.add_post("/api/player/ended", self.handle_player_ended)
        self.app.router.add_post("/api/player/progress", self.handle_player_progress)

    async def handle_overlay(self, request: web.Request) -> web.Response:
        template_path = os.path.join(os.path.dirname(__file__), "templates", "overlay.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read()
            return web.Response(text=content, content_type="text/html")
        except Exception as e:
            logger.error(f"Failed to read overlay template: {e}")
            return web.Response(text=f"Error loading overlay: {e}", status=500)

    async def handle_player(self, request: web.Request) -> web.Response:
        template_path = os.path.join(os.path.dirname(__file__), "templates", "player.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read()
            token = request.query.get("token", "default")
            content = content.replace("{{TOKEN}}", token)
            return web.Response(text=content, content_type="text/html")
        except Exception as e:
            logger.error(f"Failed to read player template: {e}")
            return web.Response(text=f"Error loading player: {e}", status=500)

    async def handle_player_ended(self, request: web.Request) -> web.Response:
        next_track = self.spotify.next_track()
        curr = self.spotify.get_currently_playing()
        return web.json_response({"advanced": bool(next_track), "current_track": curr})

    async def handle_player_progress(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            p_ms = data.get("progress_ms", 0)
            d_ms = data.get("duration_ms")
            if hasattr(self.spotify, "update_progress"):
                self.spotify.update_progress(p_ms, d_ms)
        except Exception:
            pass
        return web.json_response({"status": "ok"})

    async def handle_now_playing(self, request: web.Request) -> web.Response:
        track_info = self.spotify.get_currently_playing()
        return web.json_response(track_info or {})

    async def handle_queue(self, request: web.Request) -> web.Response:
        queue = self.spotify.get_recent_requests()
        return web.json_response({"queue": queue})

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def start(self):
        """Starts the aiohttp web server with automatic port-conflict recovery."""
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()

        started = False
        initial_port = self.port
        for offset in range(5):
            attempt_port = initial_port + offset
            try:
                self._site = web.TCPSite(self._runner, self.host, attempt_port)
                await self._site.start()
                self.port = attempt_port
                started = True
                break
            except OSError as e:
                logger.warning(f"Port {attempt_port} occupied or unavailable ({e}). Retrying on {attempt_port + 1}...")

        if not started:
            logger.error(f"Could not bind OverlayServer on ports {initial_port} - {initial_port + 4}.")
            return

        lan_str = f" | LAN: http://{self.lan_ip}:{self.port}/overlay" if self.lan_ip != "127.0.0.1" else ""
        logger.info(f"[OK] OBS Overlay available at: http://localhost:{self.port}/overlay (or http://127.0.0.1:{self.port}/overlay{lan_str})")

    async def stop(self):
        """Stops the overlay server."""
        if self._runner:
            logger.info("Stopping OBS Overlay server...")
            await self._runner.cleanup()
