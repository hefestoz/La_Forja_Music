import os
import asyncio
import logging
from aiohttp import web
from src.spotify_service import SpotifyService

logger = logging.getLogger("OverlayServer")

class OverlayServer:
    """
    Lightweight local web server serving the OBS Browser Source overlay
    and JSON APIs for playback status.
    """

    def __init__(self, spotify_service: SpotifyService, host: str = "127.0.0.1", port: int = 5000):
        self.spotify = spotify_service
        self.host = host
        self.port = port
        self.app = web.Application()
        self._runner: web.AppRunner = None
        self._site: web.TCPSite = None
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_overlay)
        self.app.router.add_get("/overlay", self.handle_overlay)
        self.app.router.add_get("/api/now-playing", self.handle_now_playing)
        self.app.router.add_get("/api/queue", self.handle_queue)
        self.app.router.add_get("/api/health", self.handle_health)

    async def handle_overlay(self, request: web.Request) -> web.Response:
        template_path = os.path.join(os.path.dirname(__file__), "templates", "overlay.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read()
            return web.Response(text=content, content_type="text/html")
        except Exception as e:
            logger.error(f"Failed to read overlay template: {e}")
            return web.Response(text=f"Error loading overlay: {e}", status=500)

    async def handle_now_playing(self, request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        # Spotify API call is synchronous requests, run in executor
        track_info = await loop.run_in_executor(None, self.spotify.get_currently_playing)
        return web.json_response(track_info or {})

    async def handle_queue(self, request: web.Request) -> web.Response:
        queue = self.spotify.get_recent_requests()
        return web.json_response({"queue": queue})

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def start(self):
        """Starts the aiohttp web server."""
        logger.info(f"Starting OBS Overlay server on http://{self.host}:{self.port}/overlay")
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info(f"[OK] OBS Overlay available at: http://{self.host}:{self.port}/overlay")

    async def stop(self):
        """Stops the overlay server."""
        if self._runner:
            logger.info("Stopping OBS Overlay server...")
            await self._runner.cleanup()
