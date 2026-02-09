import os
import random
import subprocess
import tempfile
import json
from flask import Flask, render_template, request, redirect, url_for, send_file

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

# Platform detection
PLATFORMS = {
    'spotify': {
        'domains': ['open.spotify.com', 'spotify.com'],
        'name': 'Spotify',
        'icon': '🎵',
        'color': '#1DB954'
    },
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

def get_random_proxy():
    proxy = random.choice(PROXIES)
    return f"http://{proxy}"

def extract_video_info(video_url):
    """Try all proxies until one succeeds (for yt-dlp supported platforms)."""
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

def get_spotify_info(spotify_url):
    """Get Spotify track/playlist info using spotdl."""
    try:
        # Use spotdl to get metadata
        result = subprocess.run(
            ['spotdl', 'meta', spotify_url, '--output', '-'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            # Fallback: just return basic info from URL
            return {
                'title': 'Spotify Track',
                'uploader': 'Spotify',
                'thumbnail': 'https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png',
                'duration_string': '--:--',
                'platform': 'spotify',
                'url': spotify_url,
                'is_spotify': True
            }
        
        # Parse the metadata if available
        try:
            metadata = json.loads(result.stdout)
            if isinstance(metadata, list) and len(metadata) > 0:
                track = metadata[0]
                return {
                    'title': track.get('name', 'Spotify Track'),
                    'uploader': ', '.join(track.get('artists', ['Spotify'])),
                    'thumbnail': track.get('cover_url', 'https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png'),
                    'duration_string': f"{track.get('duration', 0) // 60}:{track.get('duration', 0) % 60:02d}",
                    'platform': 'spotify',
                    'url': spotify_url,
                    'is_spotify': True
                }
        except json.JSONDecodeError:
            pass
        
        return {
            'title': 'Spotify Track',
            'uploader': 'Spotify',
            'thumbnail': 'https://storage.googleapis.com/pr-newsroom-wp/1/2018/11/Spotify_Logo_RGB_Green.png',
            'duration_string': '--:--',
            'platform': 'spotify',
            'url': spotify_url,
            'is_spotify': True
        }
        
    except subprocess.TimeoutExpired:
        raise Exception("Spotify request timed out")
    except FileNotFoundError:
        raise Exception("spotdl is not installed. Please run: pip install spotdl")
    except Exception as e:
        raise Exception(f"Spotify error: {str(e)}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        video_url = request.form.get('url')
        if not video_url:
            return render_template('index.html', error="Please enter a URL", platforms=PLATFORMS)
        
        try:
            platform_id, platform_config = detect_platform(video_url)
            
            if platform_id == 'spotify':
                # Use spotdl for Spotify
                info = get_spotify_info(video_url)
            else:
                # Use yt-dlp for everything else
                info = extract_video_info(video_url)
                info['platform'] = platform_id
                info['is_spotify'] = False
            
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
    is_spotify = request.args.get('spotify', 'false') == 'true'
    
    if not video_url:
        return redirect(url_for('index'))

    try:
        if is_spotify:
            # Download Spotify track using spotdl
            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    ['spotdl', video_url, '--output', tmpdir],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                # Find the downloaded file
                files = os.listdir(tmpdir)
                if files:
                    filepath = os.path.join(tmpdir, files[0])
                    return send_file(filepath, as_attachment=True, download_name=files[0])
                else:
                    return "Download failed: No file was created", 500
        else:
            # Use yt-dlp for video platforms
            info = extract_video_info(video_url)
            return redirect(info['url'])
    except subprocess.TimeoutExpired:
        return "Download timed out", 500
    except Exception as e:
        return f"Error: {e}", 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
