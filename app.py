import os
import random
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

def get_spotify_metadata(track_url, token):
    try:
        if "spotify.com/track/" not in track_url:
            return None
            
        track_id = track_url.split("track/")[1].split("?")[0]
        
        url = "https://api.spotidownloader.com/metadata"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Origin': 'https://spotidownloader.com',
            'Referer': 'https://spotidownloader.com/'
        }
        payload = {'type': 'track', 'id': track_id}
        
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                meta = data['metadata']
                return {
                    'title': meta['title'],
                    'uploader': meta['artists'],
                    'thumbnail': meta['cover'],
                    'is_spotify': True,
                    'download_link': data['link'],
                    'platform': 'spotify'
                }
            else:
                raise Exception(f"API Error: {data.get('message', 'Unknown error')}")
        elif response.status_code == 403: # Token expired or invalid
             raise Exception("Token Invalid or Expired (403)")
        elif response.status_code == 400:
             raise Exception("Bad Request (400) - Verify Token")
             
    except Exception as e:
        raise Exception(f"Spotify Error: {str(e)}")
    return None


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        video_url = request.form.get('url')
        if not video_url:
            return render_template('index.html', error="Please enter a URL", platforms=PLATFORMS)
        
        try:
            platform_id, platform_config = detect_platform(video_url)
            
            if platform_id == 'spotify':
                token = request.form.get('spotify_token')
                if not token:
                    raise Exception("Spotify Token is required! Please paste it in the input field.")
                info = get_spotify_metadata(video_url, token)
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
