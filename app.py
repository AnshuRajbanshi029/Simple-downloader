import os
import random
from flask import Flask, render_template, request, redirect, url_for, Response, stream_with_context
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

def get_random_proxy():
    proxy = random.choice(PROXIES)
    return f"http://{proxy}"

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        video_url = request.form.get('url')
        if not video_url:
            return render_template('index.html', error="Please enter a URL")
        
        try:
            # We'll just stream it directly to the user
            # Getting info first to get the title and direct URL
            ydl_opts = {
                'format': 'best',
                'proxy': get_random_proxy(),
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                return render_template('index.html', video_info=info, url=video_url)
        except Exception as e:
            return render_template('index.html', error=str(e))
            
    return render_template('index.html')

@app.route('/download')
def download():
    video_url = request.args.get('url')
    if not video_url:
        return redirect(url_for('index'))

    try:
        # Stream the download
        def generate():
            ydl_opts = {
                'format': 'best',
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                download_url = info['url']
                title = info.get('title', 'video')
                ext = info.get('ext', 'mp4')
                
                # We can redirect to the direct URL if it's accessible (often faster)
                # But sometimes it's IP locked. Let's try redirecting first for speed.
                # If that fails, we'd need a proxy solution which is complex.
                # Direct redirect is the "fastest" valid approach for a simple tool.
                return redirect(download_url)
                
        # Actually, for a robust "hosting" solution, we might want to proxy it if redirect fails.
        # But for "simple" and "fast" in Python, let's stick to getting the direct URL and redirecting.
        # It puts the bandwidth on the client, not the server.
        
        ydl_opts = {
            'format': 'best',
            'proxy': get_random_proxy(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return redirect(info['url'])
            
    except Exception as e:
        return f"Error: {e}"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
