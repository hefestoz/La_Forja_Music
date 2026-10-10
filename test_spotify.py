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

    parser.add_argument(
        "--suite",
        action="store_true",
        help="Run comprehensive search test suite on edge cases and common queries"
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

    if args.suite:
        print("Running Search Integrity Test Suite...\n")
        test_cases = [
            ("International Link", "https://open.spotify.com/intl-es/track/7d1CFwrBmH34gmS0Hkbfbt?si=abcdef123456", "Replay", "Zendaya"),
            ("Direct URI", "spotify:track:4cOdK2wGLETKBW3PvgPWqT", "Never Gonna Give You Up", "Rick Astley"),
            ("Hyphenated Artist - Song", "Michael Jackson - Billie Jean", "Billie Jean", "Michael Jackson"),
            ("Hyphenated Song - Artist", "Bohemian Rhapsody - Queen", "Bohemian Rhapsody", "Queen"),
            ("Hyphen with Band Dash", "AC/DC - Back in Black", "Back In Black", "AC/DC"),
            ("Word Delimiter 'by'", "Can't Stop by Red Hot Chili Peppers", "Can't Stop", "Red Hot Chili Peppers"),
            ("Ambiguous Title 'in my head'", "Jason Derulo - In My Head", "In My Head", "Jason Derulo"),
            ("Single Word Pop Query", "replay iyaz", "Replay", "Iyaz")
        ]

        passed = 0
        for label, q, expected_title, expected_artist in test_cases:
            res = service.search_track(q)
            if not res:
                print(f"[FAIL] {label}: '{q}' -> No track found!")
                continue
            
            title_ok = expected_title.lower() in res["name"].lower()
            artist_ok = any(expected_artist.lower() in a.lower() for a in res["artists"])

            if title_ok and artist_ok:
                print(f"[PASS] {label}: '{q}' -> \"{res['name']}\" by {res['artist_str']}")
                passed += 1
            else:
                print(f"[FAIL] {label}: '{q}'")
                print(f"       Got: \"{res['name']}\" by {res['artist_str']}")
                print(f"       Expected: \"{expected_title}\" by {expected_artist}")

        print(f"\nResults: {passed}/{len(test_cases)} tests passed.")
        sys.exit(0 if passed == len(test_cases) else 1)

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
