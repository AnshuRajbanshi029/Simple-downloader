import os
import random
import time
import base64
import re
from flask import Flask, render_template, request, redirect, url_for

import requests
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


def get_spotify_metadata_public(track_url):
    """No-credential fallback using Spotify public pages/oEmbed/YouTube Search."""
    oembed_res = requests.get(
        "https://open.spotify.com/oembed",
        params={"url": track_url},
        timeout=15
    )
    
    oembed = oembed_res.json() if oembed_res.status_code == 200 else {}
    title = oembed.get("title") or "Unknown"
    artist_names = oembed.get("author_name") or "Unknown"
    cover = oembed.get("thumbnail_url")

    # Scrape track page for more precise info
    track_html = _fetch_html(track_url)
    if track_html:
        # Improved Title/Artist extraction from OG tags
        og_title = _extract_meta_content(track_html, "og:title")
        if og_title and " - Song by " in og_title:
             artist_names = og_title.split(" - Song by ")[1]
             if not title or title == "Unknown":
                 title = og_title.split(" - Song by ")[0]
        
        og_desc = _extract_meta_content(track_html, "og:description")
        if og_desc and " · " in og_desc:
            parts = og_desc.split(" · ")
            if len(parts) >= 2:
                 artist_names = parts[1]

    # YouTube Fallback for Artist Name/Image if Spotify fails
    artist_image = None
    if artist_names == "Unknown" or not artist_names:
        try:
            # Search YouTube for the track title
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'max_downloads': 1,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_results = ydl.extract_info(f"ytsearch1:{title} song", download=False)
                if search_results.get('entries'):
                    entry = search_results['entries'][0]
                    artist_names = entry.get('uploader') or artist_names
                    # Try to get channel thumbnail? yt-dlp might not have it in flat search
                    # But uploader is better than "Unknown"
        except:
            pass

    # Profile Image Fallback (use album cover if artist image missing)
    if not artist_image:
        artist_image = cover

    return {
        "title": title,
        "uploader": artist_names,
        "thumbnail": cover,
        "artist_image": artist_image,
        "is_spotify": True,
        "spotify_url": track_url,
        "platform": "spotify"
    }


def get_spotify_metadata(track_url):
    try:
        track_id = _extract_spotify_track_id(track_url)
        if not track_id:
            raise Exception("Please provide a valid Spotify track URL.")

        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            return get_spotify_metadata_public(track_url)

        track_res = spotify_api_get(f"/v1/tracks/{track_id}")
        if track_res.status_code != 200:
            raise Exception(f"Track fetch failed ({track_res.status_code})")
        track = track_res.json()

        artists = track.get("artists", [])
        artist_names = ", ".join([a.get("name", "") for a in artists if a.get("name")]) or "Unknown"
        primary_artist_id = artists[0].get("id") if artists else None

        artist_image = None
        if primary_artist_id:
            artist_res = spotify_api_get(f"/v1/artists/{primary_artist_id}")
            if artist_res.status_code == 200:
                artist_data = artist_res.json()
                artist_images = artist_data.get("images", [])
                if artist_images:
                    artist_image = artist_images[0].get("url")

        album = track.get("album", {})
        album_images = album.get("images", [])
        cover = album_images[0].get("url") if album_images else None

        return {
            "title": track.get("name", "Unknown"),
            "uploader": artist_names,
            "thumbnail": cover,
            "artist_image": artist_image,
            "is_spotify": True,
            "spotify_url": (track.get("external_urls") or {}).get("spotify", track_url),
            "platform": "spotify"
        }
    except Exception as e:
        raise Exception(f"Spotify Error: {str(e)}")


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
    
    if not video_url:
        return redirect(url_for('index'))

    try:
        info = extract_video_info(video_url)
        return redirect(info['url'])
    except Exception as e:
        return f"Error: {e}", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
