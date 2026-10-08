import sys
import argparse
from dotenv import load_dotenv
from src.spotify_service import SpotifyService

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="Test Spotify Service Integration")
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        default="Bohemian Rhapsody Queen",
        help="Song name or Spotify track link to search/add (default: 'Bohemian Rhapsody Queen')"
    )
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="Only search and display track metadata without modifying the playlist"
    )
    parser.add_argument(
        "--user",
        "-u",
        type=str,
        default="Tester",
        help="Username of requester (default: 'Tester')"
    )

    args = parser.parse_args()

    print("========================================")
    print(" Spotify Service Test")
    print("========================================")

    try:
        service = SpotifyService(open_browser=False)
        if not service.is_authorized():
            print("\n[ATTENTION] Spotify authorization required before first use!")
            print("Please run:")
            print("   .\\.venv\\Scripts\\python authorize_spotify.py\n")
            sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Failed to initialize SpotifyService: {e}")
        print("Please check your .env file credentials.")
        sys.exit(1)

    try:
        playlist_name = service.get_playlist_name()
        print(f"[OK] Connected to Playlist: '{playlist_name}' (ID: {service.playlist_id})\n")
    except Exception as e:
        print(f"[WARNING] Could not fetch playlist name: {e}\n")

    if args.search_only:
        print(f"Searching for: '{args.query}'...")
        track = service.search_track(args.query)
        if track:
            print("[OK] Track Found:")
            print(f"   Title:    {track['name']}")
            print(f"   Artist:   {track['artist_str']}")
            print(f"   URI:      {track['uri']}")
            print(f"   Duration: {track['duration_ms'] // 1000}s")
            print(f"   Link:     {track['external_url']}")
        else:
            print(f"[FAIL] No results found for query: '{args.query}'")
    else:
        print(f"Simulating song request for: '{args.query}' from '{args.user}'...")
        success, message, track = service.add_song_request(
            query=args.query,
            requested_by=args.user,
            prevent_duplicates=True
        )
        if success:
            print(f"\n[SUCCESS] {message}")
            if track:
                print(f"   Link: {track['external_url']}")
        else:
            print(f"\n[RESULT] {message}")

if __name__ == "__main__":
    main()
