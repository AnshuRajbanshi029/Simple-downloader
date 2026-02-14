// Update this with your actual Render backend URL before deploying to Netlify
// e.g. 'https://your-app-name.onrender.com'
const API_BASE_URL = 'https://ayoo-a9it.onrender.com';

// Spotify Scraper API — used for Spotify metadata + downloads
const SPOTIFY_API_BASE = 'https://spotify-scraper.replit.app';

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

        console.log('[DEBUG] resolving URL:', url);

        // Route Spotify URLs to the dedicated Scraper API
        const isSpotify = /spotify\.com/i.test(url) || /open\.spotify/i.test(url);

        if (isSpotify) {
            resolveSpotify(url)
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
                    console.error('[DEBUG] Spotify API error:', err);
                    loader.classList.remove('active');
                    submitBtn.disabled = false;
                    showError('Failed to fetch Spotify info. Please try again.');
                });
        } else {
            // Non-Spotify: use Render backend
            fetch(`${API_BASE_URL}/api/resolve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            })
                .then(response => response.json())
                .then(data => {
                    console.log('[DEBUG] resolve response:', data);
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
                    console.error('[DEBUG] Fetch error:', err);
                    loader.classList.remove('active');
                    submitBtn.disabled = false;
                    showError('Network error or server unavailable.');
                });
        }
    });
});

/* -------- Spotify Scraper API -------- */

function resolveSpotify(spotifyUrl) {
    const endpoint = `${SPOTIFY_API_BASE}/api/scrape?url=${encodeURIComponent(spotifyUrl)}`;
    return fetch(endpoint)
        .then(r => {
            if (!r.ok) throw new Error('Spotify API returned ' + r.status);
            return r.json();
        })
        .then(raw => {
            console.log('[DEBUG] Spotify scraper raw:', raw);
            // Normalise into the shape renderVideoCard() expects
            const track = (raw.tracks && raw.tracks[0]) || {};
            const artistName = (track.artists && track.artists[0] && track.artists[0].name) || raw.preview?.artist || 'Unknown';
            const artistId = track.artists && track.artists[0] && track.artists[0].id;
            const artistImg = (artistId && raw.artistImages && raw.artistImages[artistId]) || (track.artists && track.artists[0] && track.artists[0].image) || '';
            const albumImages = (track.album && track.album.images) || [];
            const bigAlbumArt = albumImages.reduce((best, img) => (img.width > (best.width || 0) ? img : best), {});

            // Format duration
            const durationMs = track.duration_ms || 0;
            const totalSec = Math.floor(durationMs / 1000);
            const mins = Math.floor(totalSec / 60);
            const secs = totalSec % 60;
            const durationDisplay = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

            return {
                title: track.name || raw.preview?.title || 'Unknown Track',
                uploader: artistName,
                channel: artistName,
                thumbnail: bigAlbumArt.url || raw.preview?.image || '',
                artist_image: artistImg,
                duration_display: durationDisplay,
                duration_ms: durationMs,
                is_spotify: true,
                platform: 'spotify',
                platform_config: { name: 'Spotify', color: '#1DB954', icon: '🎵' },
                // Store the download URLs from the API for direct streaming
                spotify_download_url: track.download_url || '',
                spotify_download_url_wav: track.download_url_wav || '',
                // Preview URL as fallback
                spotify_preview_url: track.preview_url || raw.preview?.audio || '',
            };
        });
}

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
        .catch(() => { });
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
        // Store download URLs in globals so the button handler can access them
        window._spotifyDownloadUrl = info.spotify_download_url || '';
        window._spotifyDownloadUrlWav = info.spotify_download_url_wav || '';
        window._spotifyTrackTitle = info.title || '';
        window._spotifyTrackArtist = info.uploader || '';
        window._spotifyDurationMs = info.duration_ms || 0;

        downloadOptionsHtml = `
        <div class="download-options" id="spotifyDownloadOptions"
             data-download-url="${escapeHtml(info.spotify_download_url || '')}"
             data-download-url-wav="${escapeHtml(info.spotify_download_url_wav || '')}"
             data-title="${escapeHtml(info.title || '')}"
             data-artist="${escapeHtml(info.uploader || '')}" 
             data-duration-ms="${info.duration_ms || 0}">
            <div class="download-section" style="grid-column: 1 / -1;">
                <div class="download-section-title">🎵 Spotify Audio Download</div>
                <div class="download-btn-group">
                    <a href="#" onclick="startSpotifyDownload('mp3'); return false;" class="btn-small btn-audio"
                        style="background: linear-gradient(135deg, #1DB954, #1ed760); color: white;">
                        Download MP3
                        <span class="quality-label">.mp3</span>
                    </a>
                    <a href="#" onclick="startSpotifyDownload('wav'); return false;"
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

function startSpotifyDownload(fmt) {
    var title = window._spotifyTrackTitle || '';
    var artist = window._spotifyTrackArtist || '';
    var durationMs = window._spotifyDurationMs || 0;

    if (!title || !artist) {
        showError('No track info available for download.');
        return;
    }

    var format = fmt || 'mp3';
    console.log('[DEBUG] Spotify POST download:', { title: title, artist: artist, durationMs: durationMs, format: format });

    // Show progress overlay
    showProgressOverlay('audio', format, true);
    var bar = document.getElementById('dlBar');
    var percent = document.getElementById('dlPercent');
    var msg = document.getElementById('dlMsg');
    var stepDl = document.getElementById('stepDownload');
    var stepMrg = document.getElementById('stepMerge');
    var stepDone = document.getElementById('stepDone');
    var overlay = document.getElementById('dlProgressOverlay');

    // ── Realistic progress simulation (~10s total) ──
    var currentPct = 0;
    var fetchDone = false;
    var blobResult = null;
    var fetchError = null;

    // Dynamic status messages for each phase
    var connectMsgs = ['Connecting to server…', 'Establishing connection…', 'Reaching Spotify servers…'];
    var dlMsgs = ['Downloading audio…', 'Fetching audio stream…', 'Receiving data…', 'Buffering audio…'];
    var convertMsgs = ['Converting to .' + format + '…', 'Processing audio…', 'Encoding ' + format.toUpperCase() + '…'];

    function setProgress(pct, message) {
        currentPct = Math.min(pct, 100);
        bar.style.width = currentPct + '%';
        percent.textContent = Math.round(currentPct) + '%';
        if (message) msg.textContent = message;
    }

    function pickRandom(arr) {
        return arr[Math.floor(Math.random() * arr.length)];
    }

    setProgress(0, pickRandom(connectMsgs));

    // Phase-based tick interval (~300ms per tick)
    var tickInterval = 300;
    var tickCount = 0;

    var progressTimer = setInterval(function () {
        tickCount++;

        if (fetchError) {
            clearInterval(progressTimer);
            return;
        }

        // If fetch completed, rush to finish
        if (fetchDone && blobResult) {
            clearInterval(progressTimer);
            finishDownload(blobResult);
            return;
        }

        // Phase 1: Connecting (0% – 15%, first ~2s = ~7 ticks)
        if (currentPct < 15) {
            var inc = 1.5 + Math.random() * 1.2;
            setProgress(currentPct + inc);
            if (tickCount === 3) {
                msg.textContent = pickRandom(connectMsgs);
            }
        }
        // Phase 2: Downloading (15% – 70%, ~5s = ~17 ticks)
        else if (currentPct < 70) {
            if (currentPct < 16) {
                // Transition to download phase
                stepDl.className = 'dl-step active';
                msg.textContent = pickRandom(dlMsgs);
            }
            // Natural-feeling increments: faster in the middle, slower near edges
            var distFromCenter = Math.abs(currentPct - 42) / 28;
            var base = 2.8 * (1 - distFromCenter * 0.5);
            var jitter = (Math.random() - 0.3) * 1.5;
            var increment = Math.max(0.3, base + jitter);
            setProgress(currentPct + increment);

            // Cycle download messages occasionally
            if (tickCount % 5 === 0) {
                msg.textContent = pickRandom(dlMsgs);
            }
        }
        // Phase 3: Converting (70% – 88%, ~3s = ~10 ticks)
        else if (currentPct < 88) {
            if (currentPct < 71) {
                // Transition to converting phase
                stepDl.className = 'dl-step completed';
                stepMrg.className = 'dl-step active';
                msg.textContent = pickRandom(convertMsgs);
            }
            // Slower, more deliberate increments
            var inc3 = 1.0 + Math.random() * 1.2;
            setProgress(currentPct + inc3);

            if (tickCount % 6 === 0) {
                msg.textContent = pickRandom(convertMsgs);
            }
        }
        // Phase 4: Waiting for fetch (88% – 92%, crawl)
        else if (currentPct < 92) {
            var crawl = 0.1 + Math.random() * 0.3;
            setProgress(currentPct + crawl, 'Finalizing…');
        }
        // Cap at 92% until fetch resolves — bar stalls here naturally
    }, tickInterval);

    // ── Actual fetch (runs in parallel with animation) ──
    fetch(SPOTIFY_API_BASE + '/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            trackName: title,
            artistName: artist,
            durationMs: durationMs,
            format: format
        })
    })
        .then(function (response) {
            if (!response.ok) {
                return response.text().then(function (t) { throw new Error(t || 'Download failed'); });
            }
            return response.blob();
        })
        .then(function (blob) {
            blobResult = blob;
            fetchDone = true;
            // If the timer already crawled past 92%, finish immediately
            if (currentPct >= 92) {
                clearInterval(progressTimer);
                finishDownload(blob);
            }
        })
        .catch(function (err) {
            fetchError = err;
            clearInterval(progressTimer);
            console.error('[DEBUG] Spotify download error:', err);
            msg.textContent = 'Download failed — ' + (err.message || 'please try again.');
            msg.classList.add('dl-progress-error');
            setTimeout(function () { overlay.classList.remove('active'); }, 4000);
        });

    // ── Finish: animate 92% → 100% and trigger file save ──
    function finishDownload(blob) {
        // Quick rush to 95%
        setProgress(95, 'Preparing your file…');
        stepDl.className = 'dl-step completed';
        stepMrg.className = 'dl-step completed';

        setTimeout(function () {
            setProgress(98);
        }, 300);

        setTimeout(function () {
            // Trigger the actual file download via blob URL
            var blobUrl = URL.createObjectURL(blob);
            var a = document.createElement('a');
            var safeTitle = (title + ' - ' + artist).replace(/[^a-zA-Z0-9 \-_]/g, '');
            a.href = blobUrl;
            a.download = safeTitle + '.' + format;
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(blobUrl);

            setProgress(100, 'Download complete!');
            stepDone.className = 'dl-step active';

            setTimeout(function () { overlay.classList.remove('active'); }, 2500);
        }, 600);
    }
}

function showProgressOverlay(type, fmt, isSpotify) {
    isSpotify = isSpotify || false;
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
