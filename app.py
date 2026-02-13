import os
import random
import time
import base64
import re
import json
import unicodedata
from difflib import SequenceMatcher
import tempfile
import shutil
import threading
import uuid
from flask import Flask, render_template, request, redirect, url_for, Response, stream_with_context, jsonify, send_file

import requests
from bs4 import BeautifulSoup
import yt_dlp

# Check if ffmpeg is available for merging separate audio+video streams
HAS_FFMPEG = shutil.which('ffmpeg') is not None

app = Flask(__name__)
from flask_cors import CORS
CORS(app)

# ── In-memory task tracker for download progress ──────────────────────────
download_tasks = {}  # task_id -> task dict
TASK_TTL = 3600      # seconds to keep completed tasks before cleanup


def _make_task():
    """Create a fresh task dict and register it."""
    task_id = uuid.uuid4().hex[:12]
    task = {
        'id': task_id,
        'status': 'starting',     # starting | downloading | merging | done | error
        'progress': 0,            # 0-100
        'message': 'Preparing…',
        'filename': None,
        'filepath': None,
        'tmpdir': None,
        'mime_type': None,
        'filesize': 0,
        'error': None,
        'created_at': time.time(),
        'last_activity': time.time(),
    }
    download_tasks[task_id] = task
    # Prune old tasks — never kill a still-running download
    now = time.time()
    for tid in list(download_tasks):
        t = download_tasks.get(tid)
        if not t:
            continue
        if t['status'] in ('starting', 'downloading', 'merging'):
            continue
        age = now - t.get('last_activity', t['created_at'])
        if age > TASK_TTL:
            _cleanup_task(tid)
    return task


def _cleanup_task(task_id):
    """Remove task and its temp files."""
    task = download_tasks.pop(task_id, None)
    if task and task.get('tmpdir'):
        shutil.rmtree(task['tmpdir'], ignore_errors=True)


# ── Global download limiter (100 per 24 h across all platforms) ───────────
DAILY_DOWNLOAD_LIMIT = 100
_DL_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.download_log.json')
_dl_log_lock = threading.Lock()


def _load_download_log():
    """Load timestamps from disk. Caller must hold _dl_log_lock."""
    try:
        with open(_DL_LOG_FILE, 'r') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _save_download_log(log):
    """Persist timestamps to disk atomically. Caller must hold _dl_log_lock."""
    tmp = _DL_LOG_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(log, f)
        # Atomic rename (as atomic as the OS allows)
        if os.path.exists(_DL_LOG_FILE):
            os.replace(tmp, _DL_LOG_FILE)
        else:
            os.rename(tmp, _DL_LOG_FILE)
    except OSError:
        pass


def _prune_log(log):
    """Remove timestamps older than 24h. Returns new sorted list."""
    now = time.time()
    cutoff = now - 86400
    if isinstance(log, dict): return [] # Reset if format mismatch
    return sorted([t for t in log if t > cutoff])


def downloads_remaining():
    """How many downloads are still allowed in the current 24-h window."""
    with _dl_log_lock:
        log = _prune_log(_load_download_log())
        return max(DAILY_DOWNLOAD_LIMIT - len(log), 0)


def try_reserve_download():
    """Atomically check limit AND record a download. Returns True if allowed."""
    with _dl_log_lock:
        log = _prune_log(_load_download_log())
        if len(log) >= DAILY_DOWNLOAD_LIMIT:
            return False
        log.append(time.time())
        _save_download_log(log)
        return True


def unreserve_download():
    """Remove the most recent entry (e.g. if download actually failed)."""
    with _dl_log_lock:
        log = _prune_log(_load_download_log())
        if log:
            log.pop()
            _save_download_log(log)


# ── Proxy Rotation Logic (for 402 Payment Required errors) ──────────────────
PROXY_FILES = [".txt1", ".txt2", ".txt3", ".txt4"]
_proxy_file_lock = threading.Lock()
_current_proxy_index = 0

def _load_proxies_from_file(file_name):
    """Load proxy strings from a text file in the app directory."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, file_name)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"Error loading {file_name}: {e}")
    return []

def get_all_proxies():
    """Returns a combined list of all proxies from all .txtN files."""
    all_proxies = []
    for file_name in PROXY_FILES:
        all_proxies.extend(_load_proxies_from_file(file_name))
    return all_proxies

# Initial proxy list for global use (backwards compatibility)
PROXIES = get_all_proxies()

# Platform detection (video platforms only)
PLATFORMS = {
    'tiktok': {
        'domains': ['tiktok.com', 'vm.tiktok.com'],
        'name': 'TikTok',
        'icon': '🎵',
        'color': '#000000'
    },
    'facebook': {
        'domains': ['facebook.com', 'fb.watch', 'fb.com'],
        'name': 'Facebook',
        'icon': '📘',
        'color': '#1877F2'
    },
    'instagram': {
        'domains': ['instagram.com', 'instagr.am'],
        'name': 'Instagram',
        'icon': '📷',
        'color': '#E4405F'
    },
    'youtube': {
        'domains': ['youtube.com', 'youtu.be', 'youtube.com/shorts'],
        'name': 'YouTube',
        'icon': '▶️',
        'color': '#FF0000'
    },
    'spotify': {
        'domains': ['spotify.com', 'open.spotify.com'],
        'name': 'Spotify',
        'icon': '🎵',
        'color': '#1DB954'
    }
}

def detect_platform(url):
    """Detect which platform the URL belongs to."""
    url_lower = url.lower()
    for platform_id, config in PLATFORMS.items():
        for domain in config['domains']:
            if domain in url_lower:
                return platform_id, config
    return 'youtube', PLATFORMS['youtube']  # Default to YouTube

def get_youtube_channel_avatar(channel_id):
    """Fetch YouTube channel avatar from channel page."""
    if not channel_id:
        return None
    
    try:
        # Fetch channel page
        channel_url = f"https://www.youtube.com/channel/{channel_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(channel_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            html = response.text
            # Look for avatar URL in various patterns
            import re
            
            # Pattern 1: og:image meta tag (often the channel avatar)
            og_match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            if og_match:
                avatar_url = og_match.group(1)
                # Convert to higher resolution
                avatar_url = re.sub(r'=s\d+-', '=s176-', avatar_url)
                return avatar_url
            
            # Pattern 2: Look for avatar in JSON data
            avatar_match = re.search(r'"avatar":\s*\{\s*"thumbnails":\s*\[\s*\{\s*"url":\s*"([^"]+)"', html)
            if avatar_match:
                return avatar_match.group(1)
            
            # Pattern 3: Channel thumbnail URL pattern
            thumb_match = re.search(r'(https://yt3\.ggpht\.com/[^"\\]+)', html)
            if thumb_match:
                return thumb_match.group(1)
    except Exception as e:
        print(f"Error fetching channel avatar: {e}")
    
    return None


def _fetch_html_with_proxies(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }
    
    # Try all available proxies from all groups
    all_proxies = get_all_proxies()
    random.shuffle(all_proxies)

    for proxy in all_proxies:
        try:
            proxy_url = f"http://{proxy}"
            response = requests.get(
                url,
                headers=headers,
                proxies={'http': proxy_url, 'https': proxy_url},
                timeout=15
            )
            if response.status_code == 200:
                return response.text
        except Exception:
            continue
            
    return None


def _clean_tiktok_url(url):
    if not url:
        return None
    return (url
            .replace('\\u002F', '/')
            .replace('\\/', '/')
            .replace('\\u003D', '=')
            .replace('\\u0026', '&'))


def get_tiktok_profile_avatar(profile_url):
    if not profile_url:
        return None

    html = _fetch_html_with_proxies(profile_url) or _fetch_html(profile_url)
    if not html:
        return None

    patterns = [
        r'"avatarLarger"\s*:\s*"([^"]+)"',
        r'"avatarMedium"\s*:\s*"([^"]+)"',
        r'"avatarThumb"\s*:\s*"([^"]+)"',
        r'"avatar"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return _clean_tiktok_url(match.group(1))

    return None


def _clean_instagram_url(url):
    if not url:
        return None
    return (url
            .replace('\\u002F', '/')
            .replace('\\/', '/')
            .replace('\\u003D', '=')
            .replace('\\u0026', '&'))


def _clean_image_url(url):
    if not url:
        return None
    return (url
            .replace('&amp;', '&')
            .replace('\\u002F', '/')
            .replace('\\/', '/')
            .replace('\\u003D', '=')
            .replace('\\u0026', '&'))


def _pick_best_thumbnail(thumbnails):
    if not thumbnails:
        return None

    def score(t):
        width = t.get('width') or 0
        height = t.get('height') or 0
        return (width * height, width, height)

    best = max(thumbnails, key=score)
    return best.get('url') or best.get('src')


def get_instagram_user_avatar(user_id):
    """Fetch an Instagram user's profile picture via the internal mobile API, rotating on 402."""
    if not user_id:
        return None

    api_url = f"https://i.instagram.com/api/v1/users/{user_id}/info/"
    ig_headers = {
        "User-Agent": (
            "Instagram 275.0.0.27.98 Android "
            "(33/13; 420dpi; 1080x2400; samsung; SM-G991B; "
            "o1s; exynos2100; en_US; 458229237)"
        ),
        "X-IG-App-ID": "936619743392459",
    }

    for attempt in range(1):
        shuffled = get_all_proxies()
        random.shuffle(shuffled)
        all_402 = True

        for proxy in shuffled[:4]:                       # try up to 4 proxies
            try:
                proxy_url = f"http://{proxy}"
                resp = requests.get(
                    api_url,
                    headers=ig_headers,
                    proxies={"http": proxy_url, "https": proxy_url},
                    timeout=10,
                )
                if resp.status_code == 200:
                    user = resp.json().get("user", {})
                    # Prefer HD, fall back to standard
                    hd = user.get("hd_profile_pic_url_info", {})
                    pic = (
                        hd.get("url")
                        or user.get("profile_pic_url_hd")
                        or user.get("profile_pic_url")
                    )
                    if pic:
                        return pic
                
                if resp.status_code != 402:
                    all_402 = False
            except Exception as e:
                if "402" not in str(e):
                    all_402 = False
                continue
        
        break

    return None


def _resolve_fb_numeric_id_to_slug(numeric_id):
    """Convert a Facebook numeric user/page ID to its username slug.

    A HEAD request to ``facebook.com/{numeric_id}`` with the
    ``facebookexternalhit`` user-agent follows a redirect straight to
    ``facebook.com/{slug}``.  Works for both Pages and personal profiles
    without authentication.
    """
    if not numeric_id or not str(numeric_id).isdigit():
        return None

    try:
        r = requests.head(
            f"https://www.facebook.com/{numeric_id}",
            headers={
                "User-Agent": "facebookexternalhit/1.1",
                "Accept": "text/html",
            },
            timeout=15,
            allow_redirects=True,
        )
        m = re.search(
            r'facebook\.com/([A-Za-z0-9._-]+)/?(?:\?.*)?$', r.url
        )
        if m:
            slug = m.group(1)
            # Make sure we actually got a redirect (slug != original ID)
            if slug != str(numeric_id):
                return slug
    except Exception:
        pass
    return None


def get_facebook_avatar_via_graph_api(uploader_id=None, webpage_url=None):
    """Fetch a Facebook Page's profile picture via the public Graph API.

    Strategy
    ────────
    1. Try to extract the page slug directly from ``webpage_url``
       (e.g. ``facebook.com/isakhantravel/videos/…`` → ``isakhantravel``).
    2. If that fails, resolve the numeric ``uploader_id`` to a slug via the
       login-wall redirect trick.
    3. Query ``graph.facebook.com/{slug}/picture?type=large&redirect=false``
       and return the image URL only if ``is_silhouette`` is ``false``.

    Returns the avatar URL string, or ``None``.
    """
    slug = None

    # ── Phase A: extract slug from webpage_url ──
    SKIP_SEGMENTS = {
        'watch', 'reel', 'story.php', 'video.php', 'videos',
        'groups', 'events', 'plugins', 'posts', 'reels',
        'photo.php', 'permalink.php', 'ads', 'live',
    }
    if webpage_url:
        m = re.search(r'facebook\.com/([A-Za-z0-9._-]+)(?:/|$)', webpage_url)
        if m and m.group(1) not in SKIP_SEGMENTS:
            slug = m.group(1)

    # ── Phase B: resolve numeric ID → slug ──
    if not slug and uploader_id:
        slug = _resolve_fb_numeric_id_to_slug(uploader_id)

    if not slug:
        return None

    # ── Phase C: query Graph API ──
    graph_url = (
        f"https://graph.facebook.com/{slug}/picture"
        f"?type=large&redirect=false"
    )
    try:
        resp = requests.get(graph_url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json().get('data', {})
        if data.get('is_silhouette'):
            return None
        pic_url = data.get('url')
        if pic_url:
            return _clean_image_url(pic_url)
    except Exception:
        pass
    return None


def _is_fb_default_avatar(url):
    """Return True if ``url`` looks like Facebook's generic default avatar.

    Default/placeholder profile pictures live under the ``t1.30497-1`` CDN
    bucket.  Real user photos use buckets like ``t39.30808-1``, etc.
    """
    return '/t1.30497-1/' in (url or '')


def get_facebook_profile_avatar(video_page_url):
    """Extract the *poster's* profile picture from a Facebook video/post page.

    Strategy order
    ──────────────
    1. Find ALL ``profile_picture.uri`` entries in the page's embedded JSON and
       return the first one that is NOT a default/silhouette avatar.
    2. Find ``profilePicLarge`` / ``profilePicMedium`` / ``profilePic`` keys.
    3. Look for ``profile_url`` in the JSON, fetch that profile page, and
       repeat the search there.
    4. Legacy meta-tag / og:image fallback.
    """
    if not video_page_url:
        return None

    html = _fetch_html_with_proxies(video_page_url) or _fetch_html(video_page_url)
    if not html:
        return None

    # ── 1. Collect ALL profile_picture.uri entries; skip default avatars ──
    all_pics = re.findall(
        r'"profile_picture"\s*:\s*\{[^\}]*"uri"\s*:\s*"([^"]+)"', html
    )
    for raw in all_pics:
        pic = _clean_image_url(raw.replace('\\/', '/'))
        if not _is_fb_default_avatar(pic):
            return pic

    # ── 2. Try profilePicLarge / profilePicMedium / profilePic ──
    for key in ('profilePicLarge', 'profilePicMedium', 'profilePic'):
        m = re.search(
            rf'"{key}"\s*:\s*\{{[^\}}]*"uri"\s*:\s*"([^"]+)"', html
        )
        if m:
            pic = _clean_image_url(m.group(1).replace('\\/', '/'))
            if not _is_fb_default_avatar(pic):
                return pic

    # ── 3. Discover the author's profile URL from JSON and fetch that page ──
    m2 = re.search(
        r'"profile_url"\s*:\s*"(https?:\\/\\/www\.facebook\.com[^"]+)"', html
    )
    if m2:
        author_url = m2.group(1).replace('\\/', '/')
        profile_html = (
            _fetch_html_with_proxies(author_url) or _fetch_html(author_url)
        )
        if profile_html:
            pp = re.findall(
                r'"profile_picture"\s*:\s*\{[^\}]*"uri"\s*:\s*"([^"]+)"',
                profile_html,
            )
            for raw in pp:
                pic = _clean_image_url(raw.replace('\\/', '/'))
                if not _is_fb_default_avatar(pic):
                    return pic
            for key in ('profilePicLarge', 'profilePicMedium', 'profilePic'):
                mp = re.search(
                    rf'"{key}"\s*:\s*\{{[^\}}]*"uri"\s*:\s*"([^"]+)"',
                    profile_html,
                )
                if mp:
                    pic = _clean_image_url(mp.group(1).replace('\\/', '/'))
                    if not _is_fb_default_avatar(pic):
                        return pic

    # ── 4. Legacy: meta tags on whatever page we last fetched ──
    for pat in (
        r'<link[^>]+rel="image_src"[^>]+href="([^"]+)"',
        r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
        r'"profilePicUrl"\s*:\s*"([^"]+)"',
        r'"profile_pic_url"\s*:\s*"([^"]+)"',
    ):
        m = re.search(pat, html)
        if m:
            pic = _clean_image_url(m.group(1))
            if not _is_fb_default_avatar(pic):
                return pic

    return None


def _should_proxy_image(url):
    if not url:
        return False
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ''
    return host.endswith('.cdninstagram.com') or host.endswith('.fbcdn.net')


def extract_video_info(video_url):
    """Try all proxies across all available groups until one succeeds."""
    last_error = None
    
    # Get all 40 proxies (10 per file x 4 files)
    all_proxies = get_all_proxies()
    random.shuffle(all_proxies)
    
    print(f"Attempting to extract video info using {len(all_proxies)} available proxies...")
    
    for proxy in all_proxies:
        try:
            ydl_opts = {
                'format': 'best',
                'proxy': f"http://{proxy}",
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'socket_timeout': 20,
                'extractor_args': {'youtube': {'player_client': ['ios,web']}},
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                # Try to get channel avatar for YouTube videos
                channel_id = info.get('channel_id')
                if channel_id and not info.get('artist_image'):
                    avatar = get_youtube_channel_avatar(channel_id)
                    if avatar:
                        info['artist_image'] = avatar
                
                return info  # Success!
        except Exception as e:
            last_error = e
            # Log the error and move to next proxy regardless of error type
            print(f"Proxy {proxy} failed: {str(e).splitlines()[0] if str(e) else 'Unknown error'}")
            continue
    
    # All 40 proxies failed
    raise last_error if last_error else Exception("All 40 proxies failed to extract video info")

spotify_token_cache = {
    'access_token': None,
    'expires_at': 0
}


def _extract_spotify_track_id(track_url):
    """Support open.spotify.com/track/<id> and spotify:track:<id>."""
    if "spotify.com/track/" in track_url:
        return track_url.split("track/")[1].split("?")[0].split("/")[0]
    if track_url.startswith("spotify:track:"):
        return track_url.split("spotify:track:")[1].strip()
    return None


def _extract_spotify_item(track_url):
    """Return (kind, id) for track/artist/album/playlist URLs or URIs."""
    match = re.search(r"spotify\.com/(track|artist|album|playlist)/([a-zA-Z0-9]+)", track_url)
    if match:
        return match.group(1), match.group(2)
    if track_url.startswith("spotify:"):
        parts = track_url.split(":")
        if len(parts) >= 3 and parts[1] in ("track", "artist", "album", "playlist"):
            return parts[1], parts[2]
    return None, None


def get_spotify_app_token():
    """Get and cache Spotify app token using Client Credentials flow."""
    now = int(time.time())
    if spotify_token_cache['access_token'] and spotify_token_cache['expires_at'] > now + 30:
        return spotify_token_cache['access_token']

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise Exception("Missing SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET on server.")

    basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = {"grant_type": "client_credentials"}

    response = requests.post(
        "https://accounts.spotify.com/api/token",
        headers=headers,
        data=payload,
        timeout=15
    )
    if response.status_code != 200:
        raise Exception(f"Spotify token request failed ({response.status_code})")

    data = response.json()
    access_token = data.get("access_token")
    expires_in = int(data.get("expires_in", 3600))
    if not access_token:
        raise Exception("Spotify token response missing access_token.")

    spotify_token_cache['access_token'] = access_token
    spotify_token_cache['expires_at'] = now + expires_in
    return access_token


def spotify_api_get(path):
    """GET against Spotify API with one retry on 401."""
    token = get_spotify_app_token()
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"https://api.spotify.com{path}", headers=headers, timeout=15)

    if response.status_code == 401:
        spotify_token_cache['access_token'] = None
        spotify_token_cache['expires_at'] = 0
        token = get_spotify_app_token()
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"https://api.spotify.com{path}", headers=headers, timeout=15)

    return response


def _fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None
        return response.text
    except:
        return None


from bs4 import BeautifulSoup

def _extract_meta_content(html, property_name):
    if not html:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    
    # Try property attribute (Standard OG tags)
    meta = soup.find('meta', property=property_name)
    if meta and meta.get('content'):
        return meta['content']
        
    # Try name attribute (Twitter tags, etc.)
    meta = soup.find('meta', attrs={'name': property_name})
    if meta and meta.get('content'):
        return meta['content']
        
    # Try itemprop (Schema.org)
    meta = soup.find('meta', itemprop=property_name)
    if meta and meta.get('content'):
        return meta['content']
        
    # Try link tags (music:musician is often a link)
    link = soup.find('link', rel=property_name)
    if link and link.get('href'):
        return link['href']
        
    return None


# ScrapingBee API Configuration
SCRAPINGBEE_API_KEY = "2H8R75KT5UR5TWQHOPS2MVBS0C61PVVCOPMC2Y9HGDT55LQ1SMAX5O5ZN6BONP74KJSTM06JF7WK1DVL"
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1"


def _format_duration(ms):
    """Convert milliseconds to readable format (3:30)"""
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _is_direct_video_format(fmt):
    """True when the format has a direct URL and contains video."""
    return (
        bool(fmt.get('url'))
        and fmt.get('vcodec') != 'none'
        and fmt.get('height')
    )


def _select_direct_video_format(formats, quality='best'):
    """Select best/worst direct video format for streaming."""
    candidates = [f for f in formats if _is_direct_video_format(f)]
    if not candidates:
        return None

    # Prioritize resolution first; prefer tracks with audio when quality is tied.
    def has_audio(fmt):
        return 1 if fmt.get('acodec') and fmt.get('acodec') != 'none' else 0

    if quality == 'worst':
        return min(
            candidates,
            key=lambda fmt: (
                fmt.get('height') or 0,
                fmt.get('tbr') or 0,
                fmt.get('fps') or 0,
                0 if has_audio(fmt) else 1,
            ),
        )

    return max(
        candidates,
        key=lambda fmt: (
            fmt.get('height') or 0,
            fmt.get('tbr') or 0,
            fmt.get('fps') or 0,
            has_audio(fmt),
        ),
    )


def _get_quality_labels(formats):
    """Return best/worst quality labels like 2160p and 144p."""
    video_fmts = [
        f for f in formats
        if f.get('vcodec') != 'none' and f.get('height')
    ]
    if not video_fmts:
        return 'HD', 'SD'

    best_height = max(f.get('height', 0) for f in video_fmts)
    worst_height = min(f.get('height', 0) for f in video_fmts)
    best_label = f"{best_height}p" if best_height else 'Best'
    worst_label = f"{worst_height}p" if worst_height else 'Low'
    return best_label, worst_label


def _video_mime_from_ext(ext):
    ext = (ext or '').lower()
    if ext == 'webm':
        return 'video/webm'
    if ext == 'mkv':
        return 'video/x-matroska'
    if ext == 'm4v':
        return 'video/x-m4v'
    if ext == 'mov':
        return 'video/quicktime'
    return 'video/mp4'


def _format_duration_seconds(seconds):
    """Format seconds as mm:ss with leading zeros (e.g., 00:07)."""
    if seconds is None:
        return None
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return None
    minutes = total // 60
    secs = total % 60
    return f"{minutes:02d}:{secs:02d}"


def _upgrade_spotify_image(url):
    """Try to upgrade Spotify image URL to a higher-res variant."""
    if not url:
        return url
    return re.sub(r"(ab67616d0000)[0-9a-f]{4}", r"\1b273", url)


# ── Spotify song-matching helpers (ported from spotify_multiplatform_downloader.py) ──

EXCLUDED_HINTS = {
    "karaoke", "instrumental", "live", "remix", "cover",
    "nightcore", "8d", "slowed", "sped up", "reverb", "edit", "version",
}


def _normalize_text(value):
    """Unicode-normalize, strip brackets/feat, lowercase for comparison."""
    value = value or ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"\([^)]*\)|\[[^\]]*]|\{[^}]*}", " ", value)
    value = re.sub(r"\b(ft|feat|featuring)\.?\b", " ", value)
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _contains_excluded_hint(text):
    norm = _normalize_text(text)
    for hint in EXCLUDED_HINTS:
        pattern = r"(?:^|\s)" + re.escape(hint) + r"(?:\s|$)"
        if re.search(pattern, norm):
            return True
    return False


def _contains_phrase(haystack_norm, phrase_norm):
    if not haystack_norm or not phrase_norm:
        return False
    pattern = r"(?:^|\s)" + re.escape(phrase_norm) + r"(?:\s|$)"
    return re.search(pattern, haystack_norm) is not None


def _artist_coverage(artists, haystack):
    """Fraction of artists found (word-boundary) in the candidate text."""
    if not artists:
        return 0.0
    hay = _normalize_text(haystack)
    hits = 0
    for artist in artists:
        token = _normalize_text(artist)
        if _contains_phrase(hay, token):
            hits += 1
    return hits / len(artists)


def _score_spotify_candidate(track_title, track_artists, target_dur_s, candidate, tolerance=5):
    """Score a yt-dlp search result against the Spotify track.

    Returns (score, duration_diff) or None if the candidate is rejected.
    """
    title = (candidate.get("title") or "").strip()
    uploader = (candidate.get("uploader") or candidate.get("channel") or "").strip()
    duration = candidate.get("duration")
    url = candidate.get("webpage_url") or candidate.get("url")

    if not title or not url:
        return None
    
    # If duration is missing slightly risky but allow it if titles match well
    if duration is None:
        duration = target_dur_s
        
    duration = int(duration)
    duration_diff = abs(duration - target_dur_s)
    if duration_diff > tolerance:
        return None

    combined_text = f"{title} {uploader}"
    if _contains_excluded_hint(combined_text):
        return None

    norm_target = _normalize_text(track_title)
    norm_candidate = _normalize_text(title)
    title_similarity = SequenceMatcher(None, norm_target, norm_candidate).ratio()

    # Handle list or string for artists
    if isinstance(track_artists, str):
        artist_list = [a.strip() for a in track_artists.split(",")]
    else:
        artist_list = list(track_artists)
        
    artist_cov = _artist_coverage(artist_list, combined_text)

    # RELAXED THRESHOLDS:
    # Was 0.50 -> Now 0.35 (sometimes artist name is just "The Weeknd" vs "Weeknd" etc)
    if artist_cov < 0.35:
        # Special case: if title is exceptionally similar (>0.9), allow low artist coverage
        if title_similarity < 0.9:
            return None
            
    # Was 0.70 -> Now 0.55
    if title_similarity < 0.55:
        return None

    duration_score = 1.0 - (duration_diff / max(tolerance, 1))
    extractor = (candidate.get("extractor") or "").lower()
    source_bonus = 0.03  # youtube default
    if "music" in extractor or "ytmusic" in extractor:
        source_bonus = 0.05
    elif "soundcloud" in extractor:
        source_bonus = 0.02

    score = (title_similarity * 0.60) + (artist_cov * 0.30) + (duration_score * 0.10) + source_bonus
    
    print(f"[DEBUG] Candidate: '{title}' | Score: {score:.2f} | TitleSim: {title_similarity:.2f} | ArtistCov: {artist_cov:.2f} | DurDiff: {duration_diff}s")
    
    return score, duration_diff


def get_spotify_metadata(track_url):
    """
    Get Spotify track metadata using ScrapingBee + oEmbed.
    Returns: song_name, artist_name, image_url, duration, artist_image
    """
    result = {
        "title": None,
        "uploader": None,
        "thumbnail": None,
        "artist_image": None,  # Artist profile picture
        "duration": None,
        "duration_ms": None,
        "is_spotify": True,
        "spotify_url": track_url,
        "platform": "spotify"
    }
    
    # Extract item kind + ID
    kind, item_id = _extract_spotify_item(track_url)
    if not kind or not item_id:
        return result

    result["spotify_type"] = kind

    # Non-track items: use oEmbed for reliable metadata
    if kind != "track":
        try:
            oembed_url = f"https://open.spotify.com/oembed?url={track_url}"
            resp = requests.get(oembed_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                result["thumbnail"] = data.get("thumbnail_url")
                title = data.get("title", "")
                author = data.get("author_name", "")
                if kind == "artist":
                    result["title"] = title or author or "Unknown Artist"
                    result["uploader"] = result["title"]
                else:
                    result["title"] = title or "Unknown"
                    result["uploader"] = author or "Unknown Artist"
                result["artist_image"] = result["thumbnail"]
        except Exception as e:
            print(f"Spotify oEmbed Error: {e}")

        # Ensure defaults for non-track items
        result["title"] = result["title"] or "Unknown"
        result["uploader"] = result["uploader"] or "Unknown"
        result["artist_image"] = result["artist_image"] or result["thumbnail"]
        result["thumbnail"] = _upgrade_spotify_image(result["thumbnail"])
        result["artist_image"] = _upgrade_spotify_image(result["artist_image"])
        return result

    track_id = item_id
    artist_id = None  # Will extract from track data
    
    # APPROACH 0: Spotify Web API (most reliable when credentials are available)
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if client_id and client_secret:
        try:
            api_resp = spotify_api_get(f"/v1/tracks/{track_id}")
            if api_resp.status_code == 200:
                api_data = api_resp.json()
                result["title"] = api_data.get("name") or result["title"]
                api_artists = [a.get("name", "").strip() for a in api_data.get("artists", []) if a.get("name")]
                if api_artists:
                    result["uploader"] = ", ".join(api_artists)
                result["duration_ms"] = int(api_data.get("duration_ms") or 0) or result["duration_ms"]
                if result["duration_ms"]:
                    result["duration"] = _format_duration(result["duration_ms"])
                album_images = (api_data.get("album") or {}).get("images") or []
                if album_images:
                    result["thumbnail"] = album_images[0]["url"]
                # Fetch artist image
                if api_data.get("artists"):
                    first_artist = api_data["artists"][0]
                    artist_id = first_artist.get("id")
                    if artist_id:
                        try:
                            artist_resp = spotify_api_get(f"/v1/artists/{artist_id}")
                            if artist_resp.status_code == 200:
                                a_images = artist_resp.json().get("images") or []
                                if a_images:
                                    result["artist_image"] = a_images[0]["url"]
                        except Exception:
                            pass
        except Exception as e:
            print(f"Spotify API Error: {e}")

    # APPROACH 1: Scrape embed page via ScrapingBee (has all metadata including duration)
    embed_url = f"https://open.spotify.com/embed/track/{track_id}"
    
    try:
        params = {
            "api_key": SCRAPINGBEE_API_KEY,
            "url": embed_url,
            "render_js": "true",
            "wait": "2000",
        }
        
        resp = requests.get(SCRAPINGBEE_URL, params=params, timeout=45)
        
        if resp.status_code == 200:
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            
            for script in soup.find_all("script"):
                content = script.string or ""
                
                # Look for track data in scripts
                if '"duration":' in content or '"type":"track"' in content:
                    # Extract song name
                    name_match = re.search(r'"name"\s*:\s*"([^"]+)"', content)
                    if name_match:
                        result["title"] = name_match.group(1)
                    
                    # Extract duration (can be "duration_ms" or just "duration")
                    dur_match = re.search(r'"duration(?:_ms)?"\s*:\s*(\d+)', content)
                    if dur_match:
                        result["duration_ms"] = int(dur_match.group(1))
                        result["duration"] = _format_duration(result["duration_ms"])
                    
                    # Extract artist(s) and artist ID
                    artist_matches = re.findall(r'"artists"\s*:\s*\[(.*?)\]', content, re.DOTALL)
                    if artist_matches:
                        artist_names = re.findall(r'"name"\s*:\s*"([^"]+)"', artist_matches[0])
                        if artist_names:
                            result["uploader"] = ", ".join(artist_names)
                        
                        # Extract first artist ID for fetching artist image
                        artist_id_match = re.search(r'spotify:artist:([a-zA-Z0-9]+)', artist_matches[0])
                        if artist_id_match:
                            artist_id = artist_id_match.group(1)
                    
                    # Extract album/track image (will use as fallback for artist image)
                    img_match = re.search(r'"url"\s*:\s*"(https://[^"]*spotify[^"]*\.(?:jpg|png|jpeg)[^"]*)"', content)
                    if img_match:
                        result["thumbnail"] = img_match.group(1)
                    
                    break
            
            # Fallback for image from meta tag
            if not result["thumbnail"]:
                og_img = soup.find("meta", property="og:image")
                if og_img:
                    result["thumbnail"] = og_img.get("content")
                    
    except Exception as e:
        print(f"ScrapingBee Error: {e}")
    
    # APPROACH 2: Get artist image from artist embed page (if we have artist ID)
    if artist_id and not result["artist_image"]:
        try:
            artist_embed_url = f"https://open.spotify.com/embed/artist/{artist_id}"
            params = {
                "api_key": SCRAPINGBEE_API_KEY,
                "url": artist_embed_url,
                "render_js": "true",
                "wait": "2000",
            }
            
            resp = requests.get(SCRAPINGBEE_URL, params=params, timeout=30)
            
            if resp.status_code == 200:
                artist_html = resp.text
                
                # Look for artist image in the response
                artist_img_match = re.search(r'"image"\s*:\s*\[?\s*\{?\s*"url"\s*:\s*"(https://[^"]+)"', artist_html)
                if artist_img_match:
                    result["artist_image"] = artist_img_match.group(1)
                else:
                    # Try og:image meta tag
                    artist_soup = BeautifulSoup(artist_html, "html.parser")
                    og_artist_img = artist_soup.find("meta", property="og:image")
                    if og_artist_img:
                        result["artist_image"] = og_artist_img.get("content")
                        
        except Exception as e:
            print(f"Artist image fetch error: {e}")
    
    # APPROACH 3: oEmbed fallback for missing fields (FREE, no credits)
    if not result["thumbnail"] or not result["title"] or not result["uploader"]:
        try:
            oembed_url = f"https://open.spotify.com/oembed?url={track_url}"
            resp = requests.get(oembed_url, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                
                if not result["thumbnail"]:
                    result["thumbnail"] = data.get("thumbnail_url")
                
                # Parse title for song name and artist
                title = data.get("title", "")
                if title:
                    if " - song and lyrics by " in title:
                        parts = title.split(" - song and lyrics by ")
                        if not result["title"]:
                            result["title"] = parts[0].strip()
                        if not result["uploader"] and len(parts) > 1:
                            result["uploader"] = parts[1].strip()
                    elif " by " in title:
                        idx = title.rfind(" by ")
                        if not result["title"]:
                            result["title"] = title[:idx].strip()
                        if not result["uploader"]:
                            result["uploader"] = title[idx+4:].strip()
                    else:
                        if not result["title"]:
                            result["title"] = title
                            
        except Exception as e:
            print(f"oEmbed Error: {e}")
    
    # Set defaults for any missing fields
    result["title"] = result["title"] or "Unknown Track"
    result["uploader"] = result["uploader"] or "Unknown Artist"
    
    # Use album art as fallback for artist image
    if not result["artist_image"]:
        result["artist_image"] = result["thumbnail"]

    result["thumbnail"] = _upgrade_spotify_image(result["thumbnail"])
    result["artist_image"] = _upgrade_spotify_image(result["artist_image"])
    
    return result


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html', platforms=PLATFORMS, downloads_remaining=downloads_remaining())

@app.route('/api/resolve', methods=['POST'])
def api_resolve():
    data = request.get_json(force=True)
    video_url = data.get('url')
    if not video_url:
        return jsonify({'error': "Please enter a URL"}), 400
    
    try:
        platform_id, platform_config = detect_platform(video_url)
        
        if platform_id == 'spotify':
            info = get_spotify_metadata(video_url)
        else:
            info = extract_video_info(video_url)
            
        info['platform'] = platform_id
        # Pass config back so frontend knows color/name
        info['platform_config'] = platform_config

        if platform_id == 'tiktok' and not info.get('artist_image'):
            avatar = (
                info.get('uploader_avatar')
                or info.get('uploader_avatar_url')
                or info.get('uploader_thumbnail')
                or info.get('avatar')
            )
            if not avatar:
                profile_url = info.get('uploader_url')
                if not profile_url:
                    uploader_id = info.get('uploader_id') or info.get('uploader')
                    if uploader_id:
                        profile_url = f"https://www.tiktok.com/@{uploader_id}"
                if not profile_url:
                    webpage_url = info.get('webpage_url')
                    if webpage_url:
                        match = re.search(r'tiktok\.com/@([^/?]+)', webpage_url)
                        if match:
                            profile_url = f"https://www.tiktok.com/@{match.group(1)}"
                avatar = get_tiktok_profile_avatar(profile_url)

            if avatar:
                info['artist_image'] = avatar

        if platform_id == 'tiktok':
            duration_display = _format_duration_seconds(info.get('duration'))
            if duration_display:
                info['duration_display'] = duration_display

        if platform_id == 'facebook':
            if not info.get('artist_image'):
                avatar = (
                    info.get('uploader_avatar')
                    or info.get('uploader_avatar_url')
                    or info.get('uploader_thumbnail')
                    or info.get('avatar')
                )
                if not avatar:
                    # ── PRIMARY: Graph API (fast & reliable for Pages) ──
                    avatar = get_facebook_avatar_via_graph_api(
                        uploader_id=info.get('uploader_id'),
                        webpage_url=info.get('webpage_url'),
                    )
                if not avatar:
                    # ── FALLBACK: HTML-scrape the video page ──
                    video_page = info.get('webpage_url') or info.get('url')
                    avatar = get_facebook_profile_avatar(video_page)

                if avatar:
                    info['artist_image'] = avatar

            duration_display = _format_duration_seconds(info.get('duration'))
            if duration_display:
                info['duration_display'] = duration_display

            if info.get('artist_image') and _should_proxy_image(info['artist_image']):
                from urllib.parse import quote as _url_quote
                info['artist_image'] = (
                    '/proxy_image?url=' + _url_quote(info['artist_image'], safe='')
                )

        if platform_id == 'instagram':
            if not info.get('thumbnail'):
                info['thumbnail'] = _pick_best_thumbnail(info.get('thumbnails', []))

            # ── Avatar: fetch via Instagram's internal user API ──
            if not info.get('artist_image'):
                avatar = (
                    info.get('uploader_avatar')
                    or info.get('uploader_avatar_url')
                    or info.get('uploader_thumbnail')
                    or info.get('avatar')
                )
                if not avatar:
                    # yt_dlp's uploader_id is the numeric user ID
                    avatar = get_instagram_user_avatar(
                        info.get('uploader_id')
                    )

                if avatar:
                    info['artist_image'] = avatar

            # ── Proxy Instagram CDN images through our server ──
            # Instagram CDN URLs can be geo-blocked or expire for
            # direct browser requests, so we proxy them to be safe.
            from urllib.parse import quote as _url_quote
            if info.get('artist_image') and _should_proxy_image(info['artist_image']):
                info['artist_image'] = (
                    '/proxy_image?url=' + _url_quote(info['artist_image'], safe='')
                )
            if info.get('thumbnail') and _should_proxy_image(info['thumbnail']):
                info['thumbnail'] = (
                    '/proxy_image?url=' + _url_quote(info['thumbnail'], safe='')
                )

            duration_display = _format_duration_seconds(info.get('duration'))
            if duration_display:
                info['duration_display'] = duration_display

        if platform_id != 'spotify':
            best_label, worst_label = _get_quality_labels(info.get('formats', []))
            info['best_quality_label'] = best_label
            info['worst_quality_label'] = worst_label

            # Ensure every non-Spotify platform has a formatted duration (mm:ss)
            if not info.get('duration_display'):
                duration_display = _format_duration_seconds(info.get('duration'))
                if duration_display:
                    info['duration_display'] = duration_display
        
        return jsonify(info)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Background download worker ───────────────────────────────────────────
def _run_video_download(task, video_url, quality, proxies=None):
    """Download video (+ merge audio) in a background thread, rotating on 402."""
    last_error = None
    
    # Try all 40 proxies
    shuffled = get_all_proxies()
    random.shuffle(shuffled)

    for proxy in shuffled:
        tmpdir = tempfile.mkdtemp()
        task['tmpdir'] = tmpdir
        try:
            if quality == 'worst':
                if HAS_FFMPEG:
                    fmt = ('worstvideo[ext=mp4][vcodec^=avc]+worstaudio[ext=m4a]'
                           '/worstvideo[ext=mp4]+worstaudio[ext=m4a]'
                           '/worstvideo+worstaudio'
                           '/worst[ext=mp4]/worst')
                else:
                    fmt = 'worst[ext=mp4][vcodec^=avc]/worst[ext=mp4]/worst'
            else:
                if HAS_FFMPEG:
                    fmt = ('bestvideo[ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]'
                           '/bestvideo[ext=mp4]+bestaudio[ext=m4a]'
                           '/bestvideo+bestaudio'
                           '/best[ext=mp4]/best')
                else:
                    fmt = 'best[ext=mp4][vcodec^=avc]/best[ext=mp4]/best'

            output_template = os.path.join(tmpdir, '%(id)s.%(ext)s')

            # Track multi-stream progress
            _dl_state = {'streams_done': 0}

            def _progress_hook(d):
                task['last_activity'] = time.time()
                if d.get('status') == 'downloading':
                    task['status'] = 'downloading'
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        raw_pct = downloaded / total
                        if _dl_state['streams_done'] == 0:
                            task['progress'] = min(int(raw_pct * 85), 85)
                        else:
                            task['progress'] = min(85 + int(raw_pct * 10), 95)
                    if _dl_state['streams_done'] == 0:
                        task['message'] = 'Downloading video…'
                    else:
                        task['message'] = 'Downloading audio…'
                elif d.get('status') == 'finished':
                    _dl_state['streams_done'] += 1
                    if _dl_state['streams_done'] == 1:
                        task['progress'] = 85
                        task['message'] = 'Video downloaded, fetching audio…'
                    else:
                        task['progress'] = 95
                        task['message'] = 'Download complete, processing…'

            def _postprocessor_hook(d):
                task['last_activity'] = time.time()
                if d.get('status') == 'started':
                    task['status'] = 'merging'
                    task['progress'] = 96
                    task['message'] = 'Merging streams…'
                elif d.get('status') == 'finished':
                    task['progress'] = 99
                    task['message'] = 'Merge complete!'

            ydl_opts = {
                'format': fmt,
                'proxy': f"http://{proxy}",
                'quiet': True,
                'no_warnings': True,
                'outtmpl': output_template,
                'restrictfilenames': True,
                'noplaylist': True,
                'socket_timeout': 30,
                'concurrent_fragment_downloads': 8,
                'extractor_args': {'youtube': {'player_client': ['ios,web']}},
                'progress_hooks': [_progress_hook],
                'postprocessor_hooks': [_postprocessor_hook],
            }
            if HAS_FFMPEG:
                ydl_opts['merge_output_format'] = 'mp4'

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                title = info.get('title', 'video')

                downloaded_files = [
                    f for f in os.listdir(tmpdir)
                    if not f.endswith('.part') and not f.endswith('.ytdl')
                ]
                if not downloaded_files:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                    continue

                filepath = os.path.join(tmpdir, downloaded_files[0])
                ext = os.path.splitext(downloaded_files[0])[1].lstrip('.') or 'mp4'
                safe_filename = re.sub(r'[^\w\-_.]', '_', title)[:100] + f'.{ext}'

                task['filepath'] = filepath
                task['filename'] = safe_filename
                task['filesize'] = os.path.getsize(filepath)
                task['mime_type'] = _video_mime_from_ext(ext)
                task['status'] = 'done'
                task['progress'] = 100
                task['message'] = 'Ready to download!'
                return
        except Exception as e:
            last_error = e
            shutil.rmtree(tmpdir, ignore_errors=True)
            continue
            
    task['status'] = 'error'
    task['error'] = str(last_error) if last_error else 'All proxies failed'
    task['message'] = 'Download failed — please try again.'
    unreserve_download()


def _run_audio_download(task, video_url, audio_format, proxies=None):
    """Download + convert audio in a background thread, rotating on 402."""
    last_error = None
    
    # Try all 40 proxies
    shuffled = get_all_proxies()
    random.shuffle(shuffled)

    for proxy in shuffled:
        tmpdir = tempfile.mkdtemp()
        task['tmpdir'] = tmpdir
        try:
            ext = audio_format.lower()
            output_template = os.path.join(tmpdir, '%(id)s.%(ext)s')

            def _progress_hook(d):
                task['last_activity'] = time.time()
                if d.get('status') == 'downloading':
                    task['status'] = 'downloading'
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        task['progress'] = min(int(downloaded / total * 95), 95)
                    task['message'] = 'Downloading audio…'
                elif d.get('status') == 'finished':
                    task['progress'] = 95
                    task['message'] = 'Download complete, converting…'

            def _postprocessor_hook(d):
                task['last_activity'] = time.time()
                if d.get('status') == 'started':
                    task['status'] = 'merging'
                    task['progress'] = 96
                    task['message'] = f'Converting to .{ext}…'
                elif d.get('status') == 'finished':
                    task['progress'] = 99
                    task['message'] = 'Conversion complete!'

            ydl_opts = {
                'format': 'bestaudio/best',
                'proxy': f"http://{proxy}",
                'quiet': True,
                'no_warnings': True,
                'outtmpl': output_template,
                'restrictfilenames': True,
                'noplaylist': True,
                'socket_timeout': 30,
                'concurrent_fragment_downloads': 8,
                'extractor_args': {'youtube': {'player_client': ['ios,web']}},
                'progress_hooks': [_progress_hook],
                'postprocessor_hooks': [_postprocessor_hook],
            }
            if HAS_FFMPEG:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': ext,
                    'preferredquality': '192',
                }]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                title = info.get('title', 'audio')

                downloaded_files = [
                    f for f in os.listdir(tmpdir)
                    if not f.endswith('.part') and not f.endswith('.ytdl')
                ]
                if not downloaded_files:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                    continue

                filepath = os.path.join(tmpdir, downloaded_files[0])
                actual_ext = os.path.splitext(downloaded_files[0])[1].lstrip('.') or ext
                safe_filename = re.sub(r'[^\w\-_.]', '_', title)[:100] + f'.{actual_ext}'

                mime_map = {
                    'mp3': 'audio/mpeg',
                    'wav': 'audio/wav',
                    'm4a': 'audio/mp4',
                    'opus': 'audio/opus',
                    'webm': 'audio/webm',
                    'ogg': 'audio/ogg',
                }
                task['filename'] = safe_filename
                task['filesize'] = os.path.getsize(filepath)
                task['mime_type'] = mime_map.get(actual_ext, f'audio/{actual_ext}')
                task['status'] = 'done'
                task['progress'] = 100
                task['message'] = 'Ready to download!'
                return
        except Exception as e:
            last_error = e
            shutil.rmtree(tmpdir, ignore_errors=True)
            continue

    task['status'] = 'error'
    task['error'] = str(last_error) if last_error else 'All proxies failed'
    task['message'] = 'Download failed — please try again.'
    unreserve_download()


def _run_spotify_download(task, track_title, track_artist, duration_ms, audio_format, proxies=None):
    """Search YouTube for a Spotify track match and download it as audio, rotating on 402."""
    last_error = None
    
    # Try all 40 proxies
    shuffled = get_all_proxies()
    random.shuffle(shuffled)

    for proxy in shuffled:
        tmpdir = tempfile.mkdtemp()
        task['tmpdir'] = tmpdir
        try:
            ext = audio_format.lower()
            target_dur_s = duration_ms / 1000.0

            # Search Strategies
            best_match = None
            strategies = [
                (f"ytsearch10:{track_artist} - {track_title} audio", "Resolving high-fidelity audio stream…", 2),
                (f"ytsearch10:{track_artist} - {track_title} lyrics", "Decrypting secure audio segment…", 4),
                (f"scsearch5:{track_artist} - {track_title}", "Remastering audio buffer…", 5)
            ]
            
            for query, msg, tol in strategies:
                task['message'] = msg
                ydl_opts_search = {
                    'proxy': f"http://{proxy}",
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': True,
                    'socket_timeout': 15,
                }
                try:
                    with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
                        results = ydl.extract_info(query, download=False)
                        entries = results.get('entries', [])
                        candidates = []
                        for entry in entries:
                            res = _score_spotify_candidate(track_title, [track_artist], target_dur_s, entry, tolerance=tol)
                            if res:
                                candidates.append((res[0], entry['url']))
                        if candidates:
                            best_match = sorted(candidates, key=lambda x: x[0], reverse=True)[0]
                            break
                except Exception:
                    continue

            if not best_match:
                raise Exception("No suitable candidates found")

            # Download actual match
            video_url = best_match[1]
            output_template = os.path.join(tmpdir, '%(id)s.%(ext)s')

            # Hooks
            def _progress_hook(d):
                task['last_activity'] = time.time()
                if d.get('status') == 'downloading':
                    task['status'] = 'downloading'
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        task['progress'] = min(int(downloaded / total * 95), 95)
                    task['message'] = 'Downloading audio…'
                elif d.get('status') == 'finished':
                    task['progress'] = 95

            def _postprocessor_hook(d):
                task['last_activity'] = time.time()
                if d.get('status') == 'started':
                    task['status'] = 'merging'
                    task['message'] = f'Converting to {audio_format}…'
                elif d.get('status') == 'finished':
                    task['progress'] = 99

            ydl_opts = {
                'format': 'bestaudio/best',
                'proxy': f"http://{proxy}",
                'quiet': True,
                'no_warnings': True,
                'outtmpl': output_template,
                'restrictfilenames': True,
                'socket_timeout': 30,
                'progress_hooks': [_progress_hook],
                'postprocessor_hooks': [_postprocessor_hook],
            }
            if HAS_FFMPEG:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': ext,
                    'preferredquality': '192',
                }]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(video_url, download=True)
                downloaded_files = [f for f in os.listdir(tmpdir) if not f.endswith('.part') and not f.endswith('.ytdl')]
                if not downloaded_files:
                    continue

                filepath = os.path.join(tmpdir, downloaded_files[0])
                task['filepath'] = filepath
                task['filename'] = re.sub(r'[^\w\-_.]', '_', track_title)[:100] + f'.{ext}'
                task['filesize'] = os.path.getsize(filepath)
                task['mime_type'] = f'audio/{ext}'
                task['status'] = 'done'
                task['progress'] = 100
                task['message'] = 'Ready!'
                return
        except Exception as e:
            last_error = e
            shutil.rmtree(tmpdir, ignore_errors=True)
            continue

    task['status'] = 'error'
    task['error'] = str(last_error) if last_error else 'All proxies failed during download'
    task['message'] = 'Download failed — please try again.'
    unreserve_download()


# ── API routes for task-based downloads ────────────────────────────────────

@app.route('/download_start', methods=['POST'])
def download_start():
    """Kick off a download in the background and return a task ID."""
    data = request.get_json(force=True)
    video_url = data.get('url')
    dl_type = data.get('type', 'video')        # 'video', 'audio', or 'spotify'
    quality = data.get('quality', 'best')       # 'best' or 'worst'
    audio_format = data.get('format', 'mp3')    # 'mp3' or 'wav'

    if not video_url:
        return jsonify({'error': 'No URL provided'}), 400

    # Atomic check+reserve — no race condition possible
    if not try_reserve_download():
        return jsonify({'error': 'Daily download limit reached (100/day). Try again later.'}), 429

    task = _make_task()

    if dl_type == 'spotify':
        # Spotify download: use metadata from request body
        track_title = data.get('track_title', '')
        track_artist = data.get('track_artist', '')
        duration_ms = int(data.get('duration_ms', 0))

        if not track_title or not track_artist or duration_ms <= 0:
            # Fallback: fetch metadata server-side
            try:
                sp_meta = get_spotify_metadata(video_url)
                track_title = track_title or sp_meta.get('title', 'Unknown Track')
                track_artist = track_artist or sp_meta.get('uploader', 'Unknown Artist')
                duration_ms = duration_ms or sp_meta.get('duration_ms', 0)
            except Exception:
                pass

        if not track_title or not track_artist or duration_ms <= 0:
            unreserve_download()
            return jsonify({'error': 'Could not determine track metadata for Spotify download.'}), 400

        t = threading.Thread(
            target=_run_spotify_download,
            args=(task, track_title, track_artist, duration_ms, audio_format, PROXIES),
            daemon=True,
        )
    elif dl_type == 'audio':
        t = threading.Thread(
            target=_run_audio_download,
            args=(task, video_url, audio_format, PROXIES),
            daemon=True,
        )
    else:
        t = threading.Thread(
            target=_run_video_download,
            args=(task, video_url, quality, PROXIES),
            daemon=True,
        )
    t.start()

    return jsonify({'task_id': task['id']})


@app.route('/downloads_remaining')
def api_downloads_remaining():
    """Return how many downloads are left in the 24-h window."""
    return jsonify({'remaining': downloads_remaining(), 'limit': DAILY_DOWNLOAD_LIMIT})


@app.route('/download_progress/<task_id>')
def download_progress(task_id):
    """Poll this to get live progress of a download task."""
    task = download_tasks.get(task_id)
    if not task:
        return jsonify({'status': 'error', 'message': 'Task not found'}), 404
    return jsonify({
        'status': task['status'],
        'progress': task['progress'],
        'message': task['message'],
    })


@app.route('/download_file/<task_id>')
def download_file(task_id):
    """Serve the finished file.  Temp dir is cleaned later by TTL."""
    task = download_tasks.get(task_id)
    if not task or task['status'] not in ('done', 'served'):
        return 'File not ready', 404

    filepath = task.get('filepath')
    if not filepath or not os.path.isfile(filepath):
        return 'File no longer available', 410

    # Cap re-serves at 3 to prevent abuse of a single task ID
    serve_count = task.get('_serve_count', 0)
    if serve_count >= 3:
        return 'Download link expired', 410

    task['status'] = 'served'
    task['last_activity'] = time.time()
    task['_serve_count'] = serve_count + 1

    return send_file(
        filepath,
        mimetype=task['mime_type'],
        as_attachment=True,
        download_name=task['filename'],
    )


# ── Image proxy  (Instagram CDN returns 403 to bare browser requests) ─────

@app.route('/proxy_image')
def proxy_image():
    """Proxy an external image through this server, rotating on failure."""
    from urllib.parse import urlparse

    img_url = request.args.get('url', '')
    if not img_url:
        return '', 204

    host = urlparse(img_url).hostname or ''
    allowed = host.endswith('.cdninstagram.com') or host.endswith('.fbcdn.net')
    if not allowed:
        return '', 403

    for attempt in range(2):
        shuffled = PROXIES.copy()
        random.shuffle(shuffled)
        all_402 = True

        for proxy_str in shuffled[:4]: # Try up to 4 proxies from current group
            try:
                proxy_url = f"http://{proxy_str}"
                resp = requests.get(
                    img_url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                                      'Chrome/120.0.0.0 Safari/537.36',
                        'Referer': 'https://www.instagram.com/',
                        'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
                    },
                    proxies={'http': proxy_url, 'https': proxy_url},
                    timeout=10,
                )
                if resp.status_code == 200:
                    ct = resp.headers.get('Content-Type', 'image/jpeg')
                    return Response(
                        resp.content,
                        content_type=ct,
                        headers={'Cache-Control': 'public, max-age=86400'},
                    )
                if resp.status_code != 402:
                    all_402 = False
            except Exception as e:
                if "402" not in str(e):
                    all_402 = False
                continue
        
        break

    # Final fallback without proxy
    try:
        resp = requests.get(
            img_url,
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://www.instagram.com/',
                'Accept': 'image/*,*/*;q=0.8',
            },
            timeout=10,
        )
        if resp.status_code == 200:
            ct = resp.headers.get('Content-Type', 'image/jpeg')
            return Response(resp.content, content_type=ct)
    except:
        pass

    return '', 502


# Legacy direct-download routes (kept as fallbacks) ────────────────────────

@app.route('/download')
def download():
    video_url = request.args.get('url')
    quality = request.args.get('quality', 'best')
    if not video_url:
        return redirect(url_for('index'))
    # Redirect to index so JS flow is used instead
    return redirect(url_for('index'))


@app.route('/download_audio')
def download_audio():
    video_url = request.args.get('url')
    if not video_url:
        return redirect(url_for('index'))
    return redirect(url_for('index'))


@app.route('/get_formats')
def get_formats():
    """Get available video formats for a URL, rotating on failure."""
    video_url = request.args.get('url')
    if not video_url:
        return {'error': 'No URL provided'}, 400

    last_error = None
    for attempt in range(2):
        shuffled = PROXIES.copy()
        random.shuffle(shuffled)
        all_402 = True

        for proxy in shuffled:
            try:
                ydl_opts = {
                    'proxy': f"http://{proxy}",
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                    formats = info.get('formats', [])
                    video_fmts = [f for f in formats if f.get('vcodec') != 'none' and f.get('height')]
                    
                    if video_fmts:
                        best_height = max(f.get('height', 0) for f in video_fmts)
                        worst_height = min(f.get('height', 0) for f in video_fmts)
                        return {
                            'best_quality': f"{best_height}p" if best_height else 'Best',
                            'worst_quality': f"{worst_height}p" if worst_height else 'Low',
                        }
                    return {'best_quality': 'HD', 'worst_quality': 'SD'}
            except Exception as e:
                last_error = e
                if "402" not in str(e):
                    all_402 = False
                continue
        
        break
            
    return {'best_quality': 'HD', 'worst_quality': 'SD'}


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
