import sys
import os
import argparse
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from src.spotify_service import SpotifyService

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="Authorize Spotify Application for Song Requests")
    parser.add_argument(
        "--url",
        type=str,
        help="Paste the full callback URL you were redirected to (e.g. http://127.0.0.1:8888/callback?code=...)"
    )
    args = parser.parse_args()

    service = SpotifyService(open_browser=False)
    auth_manager = service.auth_manager

    # Check if we already have a cached token that is valid
    token_info = auth_manager.get_cached_token()
    if token_info and not auth_manager.is_token_expired(token_info):
        print("\n[OK] Spotify is ALREADY authorized!")
        print(f"Token is valid. Connected to playlist: '{service.get_playlist_name()}'")
        return

    if args.url:
        parsed = urlparse(args.url)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if not code:
            print("[ERROR] Could not find 'code' parameter in the provided URL.")
            sys.exit(1)
        print(f"Exchanging code for token...")
        token = auth_manager.get_access_token(code=code, as_dict=False)
        if token:
            print("[SUCCESS] Spotify authorization successful! Token saved to .cache-spotify.")
            print(f"Connected to playlist: '{service.get_playlist_name()}'")
        else:
            print("[ERROR] Failed to obtain token from the provided code.")
        return

    auth_url = auth_manager.get_authorize_url()
    print("\n=======================================================")
    print(" Spotify One-Time Authorization Required")
    print("=======================================================")
    print("\n1. Make sure you added this Redirect URI to your Spotify App Dashboard:")
    print(f"   --> {service.redirect_uri}")
    print("\n2. Open this link in your web browser:")
    print(f"\n{auth_url}\n")
    print("3. Click 'Agree'.")
    print("4. Copy the entire URL you are redirected to (even if the browser shows an empty or error page),")
    print("   and run:")
    print('   .\\.venv\\Scripts\\python authorize_spotify.py --url "<PASTED_REDIRECT_URL>"')
    print("=======================================================\n")

if __name__ == "__main__":
    main()
