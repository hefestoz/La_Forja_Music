# La Forja Music Engine

> **A high-concurrency, cross-platform interactive audio streaming bot bridging Twitch IRC and TikTok Live to Spotify playback, featuring an intelligent 4-tier track resolution engine, sliding-window rate limiting, a broadcast-ready OBS overlay, and a native multi-threaded desktop control surface.**

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. System Architecture](#2-system-architecture)
- [3. Core Technical Engineering](#3-core-technical-engineering)
  - [3.1. 4-Tier Heuristic Track Resolution Engine](#31-4-tier-heuristic-track-resolution-engine)
  - [3.2. Real-Time Chat Ingestion & Protocol Adapters](#32-real-time-chat-ingestion--protocol-adapters)
  - [3.3. Concurrency & Hybrid Threading Architecture](#33-concurrency--hybrid-threading-architecture)
  - [3.4. Dual-Mode Sliding-Window Quota Limiter](#34-dual-mode-sliding-window-quota-limiter)
  - [3.5. OBS Micro-Overlay Service & Visual Telemetry](#35-obs-micro-overlay-service--visual-telemetry)
  - [3.6. CustomTkinter Desktop Controller](#36-customtkinter-desktop-controller)
- [4. Repository Structure](#4-repository-structure)
- [5. Configuration & Environment Variables](#5-configuration--environment-variables)
- [6. Installation & Execution](#6-installation--execution)
- [7. Automated Verification & Testing Suite](#7-automated-verification--testing-suite)
- [8. Security & Resilience Considerations](#8-security--resilience-considerations)

---

## 1. Executive Summary

**La Forja Music** is an enterprise-grade live production integration service engineered for broadcast streaming setups (OBS Studio, Streamlabs, TikTok Live Studio). In interactive streaming environments, audience engagement relies heavily on song requests (`!sr`). However, standard implementations suffer from severe failure modes:
1. **Search Pollution**: Obscure covers, tribute recordings, karaoke tracks, and Lucene search syntax quirks cause wrong tracks to be queued.
2. **Platform Fragmentation**: Viewers on Twitch and TikTok operate in isolated chat ecosystems with distinct protocol overheads.
3. **Streamer Fatigue**: Streamers must frequently Alt-Tab out of full-screen games or software to manage queues, skip troll tracks, or adjust levels.

This project resolves these challenges through an asynchronous, event-driven Python pipeline that ingests chat events across disparate protocols, deduplicates and ranks track candidates against Spotify's Web API using natural language scoring heuristics, enforces per-stream sliding quotas, and exposes both a glassmorphism OBS browser overlay and a secondary-screen hardware-accelerated GUI controller.

---

## 2. System Architecture

The following diagram illustrates the decoupled, event-driven data flow and execution threads across the ingestion, business logic, persistence, and presentation layers:

```
                  ┌──────────────────────┐         ┌──────────────────────┐
                  │      Twitch IRC      │         │     TikTok Live      │
                  │   WebSocket (RFC)    │         │ Protobuf Event Stream│
                  └──────────┬───────────┘         └──────────┬───────────┘
                             │                                │
                             │ [Chat Message Event]           │ [Comment Event]
                             ▼                                ▼
                  ┌───────────────────────────────────────────────────────┐
                  │                 Protocol Ingestion Layer              │
                  │  - TwitchBot (RFC 1459 parser, ping-pong heartbeat)   │
                  │  - TikTokListener (Defensive backoff & error handler) │
                  └──────────────────────────┬────────────────────────────┘
                                             │
                                             │ User & Command Validation
                                             ▼
                               ┌───────────────────────────┐
                               │   RequestLimiter Module   │
                               │ - Sliding-Window Quota    │
                               │ - Broadcaster Privilege   │
                               └─────────────┬─────────────┘
                                             │ (Allowed)
                                             ▼
                               ┌───────────────────────────┐
                               │  Spotify Track Resolver   │
                               │ ───────────────────────── │
                               │ Tier 1: URL/URI Regex     │
                               │ Tier 2: Delimiter Split   │
                               │ Tier 3: Lucene Sanitizer  │
                               │ Tier 4: Heuristic Scorer  │
                               └─────────────┬─────────────┘
                                             │
                        ┌────────────────────┴────────────────────┐
                        ▼                                         ▼
         ┌─────────────────────────────┐           ┌─────────────────────────────┐
         │     Spotify Web API         │           │   In-Memory Audit Trail     │
         │ - Playlist Mutation (POST)  │           │ - Recent Request Queue      │
         │ - Playback Telemetry (GET)  │           │ - User Attribution Metadata │
         │ - Playback Control (PUT)    │           │ - Deduplication Registry    │
         └──────────────┬──────────────┘           └──────────────┬──────────────┘
                        │                                         │
                        │ Polling / Telemetry Feed                │
                        ▼                                         ▼
         ┌─────────────────────────────┐           ┌─────────────────────────────┐
         │     Overlay Server (aiohttp)│           │   Native Desktop Mini-App   │
         │  http://127.0.0.1:5000      │           │    (CustomTkinter GUI)      │
         │ ─────────────────────────── │           │ ─────────────────────────── │
         │ • /overlay (HTML/CSS/JS)    │           │ • Hardware-accelerated GUI  │
         │ • /api/now-playing (JSON)   │           │ • Always-on-top Pinning     │
         │ • /api/queue (JSON)         │           │ • Live Transport Controls   │
         │                             │           │ • Quota & Queue Moderation  │
         └──────────────┬──────────────┘           └─────────────────────────────┘
                        │
                        ▼
         ┌─────────────────────────────┐
         │     OBS Studio / Studio     │
         │    Browser Source Widget    │
         └─────────────────────────────┘
```

---

## 3. Core Technical Engineering

### 3.1. 4-Tier Heuristic Track Resolution Engine

Standard song request implementations blindly execute `sp.search(q=query, type='track', limit=1)` and select `items[0]`. In production environments, this leads to three catastrophic failure modes:

1. **Lucene Hyphen Negation Operator**: In the Spotify Web API search grammar, a hyphen `-` denotes a Boolean `NOT`. If a chatter types `Michael Jackson - Billie Jean`, Spotify interprets the query as `Michael Jackson NOT Billie NOT Jean`, actively excluding the desired hit.
2. **International Localized URLs**: Modern mobile applications and non-US browsers export localized URLs (e.g., `https://open.spotify.com/intl-es/track/7d1CFwr...`). Hardcoded regexes targeting `/track/<id>` fail, resulting in raw URL strings being fed into free-text search.
3. **Index-0 Noise (Karaoke & Cover Pollution)**: High-frequency titles (e.g., `Replay`, `Creep`) often return low-budget karaoke recordings or tribute bands ahead of original master recordings.

To solve this, [`src/spotify_service.py`](file:///c:/Users/User/Documents/Programmer/La_Forja_Music/src/spotify_service.py) implements a **4-Tier Hierarchical Track Resolver**:

```
[Raw User Query]
       │
       ├─► [Tier 1: Canonical Identifier Extraction]
       │     Matches: Base62 22-char ID, spotify:track:ID, open.spotify.com/(intl-[a-z]{2}/)?track/ID
       │     Bypasses search engine entirely; fetches exact track entity via sp.track(id).
       │
       ├─► [Tier 2: Delimiter-Based Structured Query Synthesis]
       │     Detects delimiters: ' - ', ' – ', ' — ', ' by ', ' // '
       │     Decomposes query into (partA, partB).
       │     Executes bi-directional Spotify field filters:
       │       • track:"{partB}" artist:"{partA}"
       │       • track:"{partA}" artist:"{partB}"
       │
       ├─► [Tier 3: Lucene Operator Sanitization]
       │     If no delimiter matches, sanitizes hyphens and dashes into whitespace delimiters:
       │       re.sub(r"[-–—]", " ", query)
       │     Fetches top 10 search candidates across Spotify catalog.
       │
       └─► [Tier 4: Composite Heuristic Candidate Scorer]
             Deduplicates candidates and scores each track against user intent.
```

#### Candidate Scoring Function

The composite scoring algorithm evaluates candidate tracks using the following formulation:

$$\text{Score} = S_{\text{rank}} + S_{\text{similarity}} + S_{\text{token}} + S_{\text{exact}} + S_{\text{artist}} + S_{\text{pop}} - P_{\text{junk}}$$

Where:
- **Baseline Rank Offset ($S_{\text{rank}}$)**: Preserves Spotify's native algorithmic relevance:
  $$S_{\text{rank}} = 10.0 - (0.9 \times \text{candidate\_index})$$
- **Levenshtein String Similarity ($S_{\text{similarity}}$)**: Evaluates normalized character edit distance via `difflib.SequenceMatcher`:
  $$S_{\text{similarity}} = 35.0 \times \max\left(\text{ratio}(Q, \text{Title}), \text{ratio}(Q, \text{Title} \parallel \text{Artist})\right)$$
- **Token Set Overlap ($S_{\text{token}}$)**: Ensures multi-word queries match title/artist token sets:
  $$S_{\text{token}} = 35.0 \times \frac{|T_Q \cap T_C|}{|T_Q|}$$
- **Exact Matches ($S_{\text{exact}}, S_{\text{artist}}$)**:
  - $+20.0$ if $\text{Title} \equiv Q$
  - $+15.0$ if user query contains or matches candidate artist name
- **Popularity Term ($S_{\text{pop}}$)**: Up to $+20.0$ when Spotify returns popularity telemetry.
- **Junk/Noise Penalty Matrix ($P_{\text{junk}}$)**:
  - **Karaoke**: $-70.0$ penalty if candidate contains `"karaoke"` (unless requested).
  - **Tribute / Cover**: $-60.0$ penalty if candidate contains `"originally performed"`, `"tribute to"`, `"tribute band"`.
  - **Generic Cover**: $-40.0$ penalty if candidate contains `"cover"`.
  - **Instrumental**: $-45.0$ penalty if candidate contains `"instrumental"`.
  - **Unsolicited Live Recording**: $-15.0$ penalty for live album versions.

---

### 3.2. Real-Time Chat Ingestion & Protocol Adapters

The bot connects to two independent streaming platforms without requiring third-party bot aggregators:

#### Twitch IRC Client (`src/twitch_service.py`)
- **Transport**: Secure WebSocket (`wss://irc-ws.chat.twitch.tv:443`) implementing raw RFC 1459 IRC framing.
- **Protocol Loop**: Parses incoming raw lines using regex:
  `^:(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #(\w+) :(.+)$`
- **Resilience**: Auto-responds to Twitch `PING :tmi.twitch.tv` with `PONG :tmi.twitch.tv`. If the socket disconnects, an exponential backoff loop ($2\text{s} \to 4\text{s} \to \dots \to 60\text{s}$) maintains persistent connectivity.
- **Command Dispatcher**: Detects `!sr`, `!songrequest`, `!myrequests`, and broadcaster-restricted `!resetrequests`.

#### TikTok Live Protobuf Streamer (`src/tiktok_service.py`)
- **Transport**: Reverse-engineered WebSocket stream leveraging `TikTokLive`, decoding live server-sent protobuf events.
- **Event Handling**: Registers non-blocking handlers on `CommentEvent`, `ConnectEvent`, and `DisconnectEvent`.
- **Fault-Tolerant State Machine**: If the streamer is offline (`UserOfflineError`), the service enters an idle poll loop every 30 seconds rather than terminating the process.

---

### 3.3. Concurrency & Hybrid Threading Architecture

Python desktop applications encounter a fundamental concurrency challenge:
- **Tkinter/CustomTkinter GUI**: Must execute on the **Main Thread** and run a blocking native OS event loop (`app.mainloop()`).
- **Asynchronous Web/Network I/O**: `aiohttp` (Overlay server), `websockets` (Twitch), and `TikTokLive` require an active `asyncio` event loop.

#### Threading Model Implementation

[`main.py`](file:///c:/Users/User/Documents/Programmer/La_Forja_Music/main.py) implements a clean separation of concerns:

```
┌────────────────────────────────────────────────────────┐
│                      MAIN PROCESS                      │
│                                                        │
│  ┌────────────────────────┐  ┌──────────────────────┐  │
│  │      Main Thread       │  │ Daemon Worker Thread │  │
│  │ ────────────────────── │  │ ──────────────────── │  │
│  │ CustomTkinter GUI Loop │  │ asyncio Event Loop   │  │
│  │ - 1000ms UI Poller     │  │ - TwitchBot Task     │  │
│  │ - User Click Events    │  │ - TikTokListener Task│  │
│  │ - Volume Slider Events │  │ - aiohttp Web Server │  │
│  └───────────┬────────────┘  └──────────┬───────────┘  │
│              │                          │              │
│              │ Thread-Safe Dispatches   │              │
│              └────────► Queue / State ◄─┘              │
│                         (Spotipy API)                  │
└────────────────────────────────────────────────────────┘
```

1. **Background Async Loop**: `BotManager.start_background()` spawns a daemon thread hosting a dedicated `asyncio.new_event_loop()`. All coroutines are gathered under `asyncio.gather()`.
2. **Non-Blocking I/O Handoff**: Spotipy Web API network calls (blocking HTTP requests) invoked inside async coroutines are dispatched to the thread pool via `loop.run_in_executor(None, fn, *args)` to prevent event-loop starvation.
3. **Graceful Shutdown**: Intercepting window destruction (`WM_DELETE_WINDOW`) or terminal `SIGINT` signals triggers synchronous teardown across both threads, unbinding web ports and closing active WebSocket sessions cleanly.

---

### 3.4. Dual-Mode Sliding-Window Quota Limiter

To eliminate spam and ensure fair access, [`src/request_limiter.py`](file:///c:/Users/User/Documents/Programmer/La_Forja_Music/src/request_limiter.py) provides a high-efficiency rate-limiting engine:

- **Identity Partitioning**: Users are keyed by `platform:username` (e.g., `twitch:viewer1`, `tiktok:viewer2`), preventing username collisions across platforms.
- **Configurable Modes**:
  - **Session Mode (`USER_LIMIT_WINDOW_MINUTES = 0`)**: Fixed quota per stream session. Counts accumulate until manually cleared or restarted.
  - **Sliding-Window Mode (`USER_LIMIT_WINDOW_MINUTES > 0`)**: Evaluates timestamps dynamically:
    $$\text{Valid Timestamps} = \{ t \in T_{\text{user}} \mid t > (t_{\text{now}} - \Delta t_{\text{window}}) \}$$
    Old timestamps are pruned in $\mathcal{O}(N)$ where $N \le \text{max\_songs}$.
- **Fair-Use Guarantee**: Unsuccessful searches, network timeouts, or duplicate track rejections never increment the chatter's quota.
- **Role-Based Privilege Escalation**: Broadcasters (configured via `TWITCH_CHANNEL` / `TIKTOK_USERNAME`) automatically bypass limits.

---

### 3.5. OBS Micro-Overlay Service & Visual Telemetry

The overlay stack consists of:
- **Asynchronous Web Server (`src/overlay_server.py`)**: Built on `aiohttp.web`, serving static assets and REST JSON endpoints:
  - `GET /overlay`: Renders the self-contained transparent glassmorphism widget.
  - `GET /api/now-playing`: Returns active track title, artist, album art URL, millisecond progress, duration, playback status, and requester badge.
  - `GET /api/queue`: Exposes the last 30 requests.
- **Widget Frontend (`src/templates/overlay.html`)**:
  - **CSS Glassmorphism**: `backdrop-filter: blur(16px)` with semi-transparent rgba alpha layers and rounded 16px geometry.
  - **Hardware-Accelerated Transitions**: CSS 3D transforms (`translateY`) with cubic-bezier timing functions for smooth track transitions.
  - **Animated Equalizer**: Pure CSS-animated audio bars responding to `is_playing` state flags (active bouncing when playing, frozen opacity drop when paused).
  - **Platform-Specific Attribution**: Displays requester badges with branded Twitch Purple (`#9146FF`) or TikTok Coral (`#FE2C55`).

---

### 3.6. CustomTkinter Desktop Controller

The desktop mini-app ([`src/mini_app.py`](file:///c:/Users/User/Documents/Programmer/La_Forja_Music/src/mini_app.py)) provides an operational dashboard for the streamer:

- **Hardware Pinning**: One-click Always-On-Top toggle (`self.attributes("-topmost", True)`) prevents the window from being hidden behind full-screen games or production software.
- **Full Transport Controls**:
  - Next Track (`[⏭ Skip]`)
  - Previous Track (`[⏮ Prev]`)
  - Play / Pause Toggle (`[⏯]`)
  - Real-Time Volume Slider (`[0% - 100%]`) with debounce logic
- **Moderator Controls**:
  - `[🔄 Reset Chatter Limits]`: Flushes limiter history in real time.
  - `[🗑 Clear Playlist]`: Flushes queued tracks in Spotify.
- **Asynchronous Image Loading**: Album artwork is fetched off the UI thread via `urllib.request` and cached in memory using Pillow (`PIL.ImageTk`), eliminating UI freezing.

---

## 4. Repository Structure

```
La_Forja_Music/
├── .env.example             # Documented template for required environment secrets
├── .gitignore               # Ignores .venv, .env, OAuth caches, and bytecode
├── authorize_spotify.py     # Headless OAuth code-exchange utility for initial setup
├── main.py                  # Unified entry point; orchestrates concurrency and services
├── requirements.txt         # Pinned dependency manifest
├── README.md                # Technical system documentation and engineering specification
│
├── src/                     # Core system modules
│   ├── __init__.py          # Package initializer
│   ├── mini_app.py          # CustomTkinter secondary-screen GUI controller
│   ├── overlay_server.py    # aiohttp micro-web server for OBS overlays & REST APIs
│   ├── request_limiter.py   # Sliding-window rate limiter & quota enforcement engine
│   ├── spotify_service.py   # Spotify Web API client, auth refresher & 4-tier track resolver
│   ├── tiktok_service.py    # TikTok Live event consumer with reconnect backoff
│   ├── twitch_service.py    # Twitch IRC WebSocket client (RFC 1459)
│   └── templates/
│       └── overlay.html     # Broadcast overlay widget (HTML5 / CSS3 / ES6)
│
└── tests/                   # Verification & test harnesses
    ├── test_limiter.py      # Unit tests for sliding-window & per-stream limiter logic
    ├── test_spotify.py      # 8-point regression test suite for track search integrity
    ├── test_tiktok.py       # Simulation harness for TikTok Live chat comments
    └── test_twitch.py       # Isolated test runner for Twitch WebSocket connectivity
```

---

## 5. Configuration & Environment Variables

Create a `.env` file in the project root:

```ini
# ==============================================================================
# SPOTIFY DEVELOPER CONFIGURATION
# https://developer.spotify.com/dashboard
# ==============================================================================
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
SPOTIFY_PLAYLIST_ID=your_target_playlist_id

# ==============================================================================
# TWITCH IRC CONFIGURATION
# Generate token: https://twitchapps.com/tmi/
# ==============================================================================
TWITCH_TOKEN=oauth:your_twitch_oauth_token
TWITCH_NICK=your_bot_or_user_name
TWITCH_CHANNEL=your_channel_name

# ==============================================================================
# TIKTOK LIVE CONFIGURATION
# ==============================================================================
TIKTOK_USERNAME=your_tiktok_username

# ==============================================================================
# SONG REQUEST QUOTA CONFIGURATION
# ==============================================================================
# Maximum songs allowed per user (0 = unlimited)
MAX_SONGS_PER_USER=3

# Limit duration:
# 0 = Per-stream session (resets on bot restart or via !resetrequests)
# >0 = Rolling sliding-window in minutes (e.g., 60 = max 3 songs every 60 mins)
USER_LIMIT_WINDOW_MINUTES=0
```

---

## 6. Installation & Execution

### 1. Prerequisites
- Python 3.11 or 3.12 installed.
- Spotify Premium account (required by Spotify Web API for playback control).
- Spotify Developer Application created with Redirect URI `http://127.0.0.1:8888/callback`.

### 2. Environment Setup
```powershell
# Clone the repository
git clone https://github.com/hefestoz/La_Forja_Music.git
cd La_Forja_Music

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. One-Time Spotify Authorization
```powershell
python authorize_spotify.py
```
*Follow the terminal instructions to authorize via your browser. Tokens will be cached in `.cache-spotify` and automatically refreshed indefinitely.*

### 4. Running the Bot

**Production Mode (Native GUI Controller + OBS Overlay + Background Listeners):**
```powershell
python main.py
```

**Headless Mode (Server / Command-Line Only):**
```powershell
python main.py --no-gui
```

### 5. Configuring OBS Studio / TikTok Live Studio
1. In OBS Studio, add a **Browser Source**.
2. **URL**: `http://localhost:5000/overlay`
3. **Width**: `600` | **Height**: `160`
4. Check **Shutdown source when not visible** (recommended).

---

## 7. Automated Verification & Testing Suite

The repository contains isolated test suites to validate logic without running live streams:

### 1. Track Search & Resolver Regression Suite
```powershell
python test_spotify.py --suite
```
Runs an 8-point regression matrix against the live Spotify Web API:
- International localized URL parsing (`open.spotify.com/intl-es/...`)
- Canonical URI handling (`spotify:track:...`)
- Hyphenated query negation bypass (`Michael Jackson - Billie Jean`)
- Inverted query syntax (`Bohemian Rhapsody - Queen`)
- Band names containing punctuation (`AC/DC - Back in Black`)
- Natural language delimiters (`Can't Stop by Red Hot Chili Peppers`)
- Ambiguous multi-artist titles (`In My Head` -> Jason Derulo)
- Mainstream candidate scoring (`replay iyaz` -> Iyaz)

### 2. Rate Limiter Unit Tests
```powershell
python test_limiter.py
```
Validates:
- Per-stream hard stops ($N \ge \text{max\_songs}$)
- Broadcaster privilege bypass
- Sliding-window timestamp expiration and quota recovery
- Global and targeted cache flushes

### 3. Platform Simulation Harnesses
```powershell
# Test TikTok comment ingestion without a live stream
python test_tiktok.py --simulate

# Test isolated Twitch chat connection
python test_twitch.py
```

---

## 8. Security & Resilience Considerations

- **Zero Secret Leakage**: Secrets reside exclusively in `.env` (gitignored). OAuth tokens stored in `.cache-spotify` are restricted to local read permissions.
- **Defensive API Rate Limiting**: Chat command throttling prevents chat floods from triggering HTTP 429 errors against Spotify's Web API.
- **Fault-Tolerant Reconnections**: Network partitions, socket timeouts, or offline live rooms are handled via non-blocking retry loops with exponential backoff.
- **Non-Interactive Execution**: All service instances configure `open_browser=False` in spotipy OAuth handlers to prevent child processes from hanging in headless environments.

---

## License

Distributed under the MIT License. See `LICENSE` for more information.
