// Update this with your actual Render backend URL before deploying to Netlify
// e.g. 'https://your-app-name.onrender.com'
const API_BASE_URL = 'https://ayoo-a9it.onrender.com';

document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('fetchForm');
    const loader = document.getElementById('loaderOverlay');
    const submitBtn = document.getElementById('submitBtn');
    const urlInput = document.getElementById('urlInput');
    const errorBox = document.getElementById('errorBox');
    const resultContainer = document.getElementById('resultContainer');

    // Initial load: fetch remaining downloads
    updateDlCounter();

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        
        const url = urlInput.value.trim();
        if (!url) return;

        loader.classList.add('active');
        submitBtn.disabled = true;
        errorBox.style.display = 'none';
        errorBox.textContent = '';
        resultContainer.innerHTML = ''; // Clear previous results

        fetch(`${API_BASE_URL}/api/resolve`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url: url })
        })
        .then(response => response.json())
        .then(data => {
            loader.classList.remove('active');
            submitBtn.disabled = false;

            if (data.error) {
                showError(data.error);
            } else {
                playSuccessTone();
                renderVideoCard(data, url);
            }
        })
        .catch(err => {
            loader.classList.remove('active');
            submitBtn.disabled = false;
            showError('Network error or server unavailable.');
            console.error(err);
        });
    });
});

function showError(msg) {
    const errorBox = document.getElementById('errorBox');
    errorBox.textContent = msg;
    errorBox.style.display = 'block';
}

function updateDlCounter() {
    fetch(`${API_BASE_URL}/downloads_remaining`)
        .then(r => r.json())
        .then(d => {
            const el = document.getElementById('dlCount');
            const wrap = document.getElementById('dlRemaining');
            if (!el) return;
            el.textContent = d.remaining;
            wrap.classList.remove('low', 'depleted');
            if (d.remaining <= 0) wrap.classList.add('depleted');
            else if (d.remaining <= 20) wrap.classList.add('low');
        })
        .catch(() => {});
}

function playSuccessTone() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = 523.25; // C5
        gain.gain.value = 0.05;
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.18);
        osc.onended = function () {
            ctx.close();
        };
    } catch (e) {
        // Ignore audio errors
    }
}

function renderVideoCard(info, originalUrl) {
    const container = document.getElementById('resultContainer');
    
    // Determine platform specific details
    let platformIcon = '';
    let platformName = '';
    
    // Simple platform mapping based on icon content from original - dynamic icons are hard to pass directly
    // Ideally the API returns icon SVG or URL, for now we can infer or pass simple names
    // info.platform has the ID (youtube, tiktok, etc)
    
    const platformId = info.platform || 'youtube';
    const platformConfig = info.platform_config || {}; 
    const platformColor = platformConfig.color || '#FF0000';
    
    // Helper to generate download buttons HTML
    let downloadOptionsHtml = '';
    
    if (info.is_spotify) {
        downloadOptionsHtml = `
        <div class="download-options" id="spotifyDownloadOptions" 
             data-title="${escapeHtml(info.title || '')}"
             data-artist="${escapeHtml(info.uploader || '')}" 
             data-duration-ms="${info.duration_ms || 0}">
            <div class="download-section" style="grid-column: 1 / -1;">
                <div class="download-section-title">🎵 Spotify Audio Download</div>
                <div class="download-btn-group">
                    <a href="#" onclick="startSpotifyDownload('${originalUrl}', 'mp3'); return false;" class="btn-small btn-audio"
                        style="background: linear-gradient(135deg, #1DB954, #1ed760); color: white;">
                        Download MP3
                        <span class="quality-label">.mp3</span>
                    </a>
                    <a href="#" onclick="startSpotifyDownload('${originalUrl}', 'wav'); return false;"
                        class="btn-small btn-audio">
                        Download WAV
                        <span class="quality-label">.wav</span>
                    </a>
                </div>
            </div>
        </div>`;
    } else {
        downloadOptionsHtml = `
        <div class="download-options">
            <div class="download-section">
                <div class="download-section-title">📹 Video Download</div>
                <div class="download-btn-group">
                    <a href="#" onclick="startDownload('${originalUrl}', 'video','best'); return false;"
                        class="btn-small btn-video">
                        Highest Quality
                        <span class="quality-label">${info.best_quality_label || 'HD'}</span>
                    </a>
                    <a href="#" onclick="startDownload('${originalUrl}', 'video','worst'); return false;"
                        class="btn-small btn-video">
                        Lowest Quality
                        <span class="quality-label">${info.worst_quality_label || 'SD'}</span>
                    </a>
                </div>
            </div>
            <div class="download-section">
                <div class="download-section-title">🎵 Audio Download</div>
                <div class="download-btn-group">
                    <a href="#" onclick="startDownload('${originalUrl}', 'audio','best','mp3'); return false;"
                        class="btn-small btn-audio">
                        MP3 Format
                        <span class="quality-label">.mp3</span>
                    </a>
                    <a href="#" onclick="startDownload('${originalUrl}', 'audio','best','wav'); return false;"
                        class="btn-small btn-audio">
                        WAV Format
                        <span class="quality-label">.wav</span>
                    </a>
                </div>
            </div>
        </div>`;
    }

    // Proxy images logic
    // If the image url is relative (starts with /proxy_image), prepend API_BASE_URL
    let thumbnail = info.thumbnail;
    let artistImage = info.artist_image;
    
    if (thumbnail && thumbnail.startsWith('/proxy_image')) {
        thumbnail = API_BASE_URL + thumbnail;
    }
    if (artistImage && artistImage.startsWith('/proxy_image')) {
        artistImage = API_BASE_URL + artistImage;
    }
    
    const cardHtml = `
    <div class="video-card">
        <div class="thumbnail-container ${['tiktok', 'instagram'].includes(platformId) ? 'portrait' : ''} ${platformId === 'spotify' ? 'spotify' : ''}">
            <img src="${thumbnail || ''}" alt="Thumbnail" loading="eager" onerror="this.style.display='none'">
            ${(info.duration_display || info.duration) ? `<span class="duration-badge">${info.duration_display || info.duration}</span>` : ''}
        </div>
        <div class="video-info">
            <span class="platform-badge ${platformId}">
                ${platformConfig.name || 'Video'}
            </span>

            <h2 class="video-title">${escapeHtml(info.title || 'Unknown Title')}</h2>

            <div class="channel-info">
                <div class="channel-avatar">
                    ${artistImage ? `<img src="${artistImage}" alt="Avatar" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">` : ''}
                    <span style="${artistImage ? 'display:none;' : ''}">${(info.uploader || info.channel || '?').substring(0, 1).toUpperCase()}</span>
                </div>
                <div class="channel-details">
                    <div class="channel-name">${escapeHtml(info.uploader || info.channel || 'Unknown')}</div>
                    ${info.view_count ? `<div class="video-meta">${parseInt(info.view_count).toLocaleString()} views</div>` : ''}
                </div>
            </div>

            ${downloadOptionsHtml}
        </div>
    </div>`;

    container.innerHTML = cardHtml;
}

function escapeHtml(text) {
    if (!text) return '';
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


/* -------- Download Progress System -------- */

function startDownload(url, type, quality, fmt) {
    showProgressOverlay(type, fmt);

    // Start the download task
    const body = { url: url, type: type, quality: quality || 'best' };
    if (fmt) body.format = fmt;

    fetch(`${API_BASE_URL}/download_start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            handleDownloadError(data.error);
            updateDlCounter();
            return;
        }
        updateDlCounter();
        pollProgress(data.task_id);
    })
    .catch(err => {
        handleDownloadError('Failed to start download.');
    });
}

function startSpotifyDownload(url, fmt) {
    const optsEl = document.getElementById('spotifyDownloadOptions');
    if (!optsEl) return;

    const trackTitle = optsEl.getAttribute('data-title') || '';
    const trackArtist = optsEl.getAttribute('data-artist') || '';
    const durationMs = parseInt(optsEl.getAttribute('data-duration-ms') || '0', 10);

    showProgressOverlay('audio', fmt, true);

    const body = {
        url: url,
        type: 'spotify',
        format: fmt || 'mp3',
        track_title: trackTitle,
        track_artist: trackArtist,
        duration_ms: durationMs
    };

    fetch(`${API_BASE_URL}/download_start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            handleDownloadError(data.error);
            updateDlCounter();
            return;
        }
        updateDlCounter();
        pollProgress(data.task_id);
    })
    .catch(err => {
        handleDownloadError('Failed to start Spotify download.');
    });
}

function showProgressOverlay(type, fmt, isSpotify = false) {
    const overlay = document.getElementById('dlProgressOverlay');
    const title = document.getElementById('dlTitle');
    const stepDlSub = document.getElementById('stepDownloadSub');
    const stepMrg = document.getElementById('stepMerge');
    const stepMrgSub = document.getElementById('stepMergeSub');
    const bar = document.getElementById('dlBar');
    const percent = document.getElementById('dlPercent');
    const msg = document.getElementById('dlMsg');
    
    // Reset state
    bar.style.width = '0%';
    percent.textContent = '0%';
    msg.textContent = isSpotify ? 'Starting download…' : 'Preparing…';
    msg.classList.remove('dl-progress-error');
    document.getElementById('stepDownload').className = 'dl-step active';
    document.getElementById('stepMerge').className = 'dl-step';
    document.getElementById('stepDone').className = 'dl-step';

    if (isSpotify) {
        title.textContent = 'Downloading from Spotify';
        stepDlSub.textContent = 'Downloading audio…';
        stepMrg.querySelector('.dl-step-label').textContent = 'Converting Format';
        stepMrgSub.textContent = 'Converting to .' + (fmt || 'mp3');
    } else if (type === 'audio') {
        title.textContent = 'Downloading Audio';
        stepDlSub.textContent = 'Fetching audio from server…';
        stepMrg.querySelector('.dl-step-label').textContent = 'Converting Format';
        stepMrgSub.textContent = 'Converting to .' + (fmt || 'mp3');
    } else {
        title.textContent = 'Processing your request';
        stepDlSub.textContent = 'Fetching video from server…';
        stepMrg.querySelector('.dl-step-label').textContent = 'Merging Audio & Video';
        stepMrgSub.textContent = 'Combining streams into .mp4';
    }

    overlay.classList.add('active');
}

function handleDownloadError(message) {
    const msg = document.getElementById('dlMsg');
    const overlay = document.getElementById('dlProgressOverlay');
    msg.textContent = message;
    msg.classList.add('dl-progress-error');
    setTimeout(function () { overlay.classList.remove('active'); }, 3000);
}

function pollProgress(taskId) {
    const overlay = document.getElementById('dlProgressOverlay');
    const bar = document.getElementById('dlBar');
    const percent = document.getElementById('dlPercent');
    const msg = document.getElementById('dlMsg');
    const stepDl = document.getElementById('stepDownload');
    const stepMrg = document.getElementById('stepMerge');
    const stepDone = document.getElementById('stepDone');

    const timer = setInterval(function () {
        fetch(`${API_BASE_URL}/download_progress/${taskId}`)
            .then(r => r.json())
            .then(data => {
                const pct = data.progress || 0;
                bar.style.width = pct + '%';
                percent.textContent = pct + '%';
                msg.textContent = data.message || '';

                if (data.status === 'downloading') {
                    stepDl.className = 'dl-step active';
                    stepMrg.className = 'dl-step';
                    stepDone.className = 'dl-step';
                } else if (data.status === 'merging') {
                    stepDl.className = 'dl-step completed';
                    stepMrg.className = 'dl-step active';
                    stepDone.className = 'dl-step';
                } else if (data.status === 'done' || data.status === 'served') {
                    clearInterval(timer);
                    bar.style.width = '100%';
                    percent.textContent = '100%';
                    stepDl.className = 'dl-step completed';
                    stepMrg.className = 'dl-step completed';
                    stepDone.className = 'dl-step active';
                    msg.textContent = 'Ready!';

                    // Use a hidden link for reliable large-file downloads
                    setTimeout(function () {
                        // For the download link, we also need to point to the backend
                        const downloadUrl = `${API_BASE_URL}/download_file/${taskId}`;
                        
                        // Create invisible iframe or link to trigger download
                        const a = document.createElement('a');
                        a.href = downloadUrl;
                        a.style.display = 'none';
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        
                        setTimeout(function () {
                            overlay.classList.remove('active');
                        }, 2000);
                    }, 800);
                } else if (data.status === 'error') {
                    clearInterval(timer);
                    msg.textContent = data.message || 'Download failed.';
                    msg.classList.add('dl-progress-error');
                    setTimeout(function () { overlay.classList.remove('active'); }, 4000);
                }
            })
            .catch(function () {
                // network hiccup, keep polling
            });
    }, 600);
}
