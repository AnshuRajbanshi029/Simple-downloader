import os
import random
import time
import base64
import re
from flask import Flask, render_template, request, redirect, url_for, Response, stream_with_context

import requests
from bs4 import BeautifulSoup
import yt_dlp

app = Flask(__name__)

# Residential Proxies - rotates randomly for each request
PROXIES = [
    "sckfugob:2j5x61bsrvu0@31.59.20.176:6754",
    "sckfugob:2j5x61bsrvu0@23.95.150.145:6114",
    "sckfugob:2j5x61bsrvu0@198.23.239.134:6540",
    "sckfugob:2j5x61bsrvu0@45.38.107.97:6014",
    "sckfugob:2j5x61bsrvu0@107.172.163.27:6543",
    "sckfugob:2j5x61bsrvu0@198.105.121.200:6462",
    "sckfugob:2j5x61bsrvu0@64.137.96.74:6641",
    "sckfugob:2j5x61bsrvu0@216.10.27.159:6837",
    "sckfugob:2j5x61bsrvu0@23.26.71.145:5628",
    "sckfugob:2j5x61bsrvu0@23.229.19.94:8689",
]

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


def extract_video_info(video_url):
    """Try all proxies until one succeeds."""
    shuffled_proxies = PROXIES.copy()
    random.shuffle(shuffled_proxies)
    
    last_error = None
    for proxy in shuffled_proxies:
        try:
            ydl_opts = {
                'format': 'best',
                'proxy': f"http://{proxy}",
                'quiet': True,
                'no_warnings': True,
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
            continue  # Try next proxy
    
    # All proxies failed
    raise last_error if last_error else Exception("All proxies failed")

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
    
    # Extract track ID
    track_id_match = re.search(r'track/([a-zA-Z0-9]+)', track_url)
    if not track_id_match:
        return result
    track_id = track_id_match.group(1)
    
    artist_id = None  # Will extract from track data
    
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
    
    return result


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        video_url = request.form.get('url')
        if not video_url:
            return render_template('index.html', error="Please enter a URL", platforms=PLATFORMS)
        
        try:
            platform_id, platform_config = detect_platform(video_url)
            
            if platform_id == 'spotify':
                info = get_spotify_metadata(video_url)
            else:
                info = extract_video_info(video_url)
                
            info['platform'] = platform_id
            
            return render_template('index.html', 
                                   video_info=info, 
                                   url=video_url, 
                                   platform=platform_config,
                                   platform_id=platform_id,
                                   platforms=PLATFORMS)
        except Exception as e:
            return render_template('index.html', error=str(e), platforms=PLATFORMS)
            
    return render_template('index.html', platforms=PLATFORMS)

@app.route('/download')
def download():
    video_url = request.args.get('url')
    quality = request.args.get('quality', 'best')
    
    if not video_url:
        return redirect(url_for('index'))

    try:
        shuffled_proxies = PROXIES.copy()
        random.shuffle(shuffled_proxies)
        
        if quality == 'worst':
            format_str = 'worst[ext=mp4]/worst'
        else:
            format_str = 'best[ext=mp4]/best'
        
        for proxy in shuffled_proxies:
            try:
                ydl_opts = {
                    'format': format_str,
                    'proxy': f"http://{proxy}",
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                    stream_url = info['url']
                    title = info.get('title', 'video')
                    
                    # Stream the file with proper headers
                    def generate():
                        with requests.get(stream_url, stream=True, timeout=30) as r:
                            r.raise_for_status()
                            for chunk in r.iter_content(chunk_size=8192):
                                if chunk:
                                    yield chunk
                    
                    safe_filename = re.sub(r'[^\w\-_.]', '_', title)[:100] + '.mp4'
                    
                    return Response(
                        stream_with_context(generate()),
                        headers={
                            'Content-Disposition': f'attachment; filename="{safe_filename}"',
                            'Content-Type': 'video/mp4',
                        }
                    )
            except Exception:
                continue
        
        return "Error: All proxies failed", 500
    except Exception as e:
        return f"Error: {e}", 500


@app.route('/download_audio')
def download_audio():
    video_url = request.args.get('url')
    audio_format = request.args.get('format', 'mp3')
    
    if not video_url:
        return redirect(url_for('index'))

    try:
        shuffled_proxies = PROXIES.copy()
        random.shuffle(shuffled_proxies)
        
        for proxy in shuffled_proxies:
            try:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'proxy': f"http://{proxy}",
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                    stream_url = info['url']
                    title = info.get('title', 'audio')
                    ext = audio_format.lower()
                    
                    def generate():
                        with requests.get(stream_url, stream=True, timeout=30) as r:
                            r.raise_for_status()
                            for chunk in r.iter_content(chunk_size=8192):
                                if chunk:
                                    yield chunk
                    
                    safe_filename = re.sub(r'[^\w\-_.]', '_', title)[:100] + f'.{ext}'
                    mime_type = 'audio/mpeg' if ext == 'mp3' else 'audio/wav'
                    
                    return Response(
                        stream_with_context(generate()),
                        headers={
                            'Content-Disposition': f'attachment; filename="{safe_filename}"',
                            'Content-Type': mime_type,
                        }
                    )
            except Exception:
                continue
        
        return "Error: All proxies failed", 500
    except Exception as e:
        return f"Error: {e}", 500


@app.route('/get_formats')
def get_formats():
    """Get available video formats for a URL"""
    video_url = request.args.get('url')
    
    if not video_url:
        return {'error': 'No URL provided'}, 400

    try:
        shuffled_proxies = PROXIES.copy()
        random.shuffle(shuffled_proxies)
        
        for proxy in shuffled_proxies:
            try:
                ydl_opts = {
                    'proxy': f"http://{proxy}",
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                    formats = info.get('formats', [])
                    
                    # Find best and worst video resolutions
                    video_formats = [f for f in formats if f.get('height') and f.get('vcodec') != 'none']
                    if video_formats:
                        best = max(video_formats, key=lambda x: x.get('height', 0))
                        worst = min(video_formats, key=lambda x: x.get('height', 0))
                        
                        return {
                            'best_quality': f"{best.get('height', '?')}p",
                            'worst_quality': f"{worst.get('height', '?')}p",
                        }
                    
                    return {'best_quality': 'HD', 'worst_quality': 'SD'}
            except Exception:
                continue
        
        return {'best_quality': 'HD', 'worst_quality': 'SD'}
    except Exception:
        return {'best_quality': 'HD', 'worst_quality': 'SD'}


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

