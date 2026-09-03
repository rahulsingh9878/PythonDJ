// --- Global DOM refs ---
const queryInput = document.getElementById('queryInput');
const clearBtn = document.getElementById('clearBtn');
const searchBox = document.getElementById('searchBox');

// --- Global state variables ---
let isPlaying = false;
let isMuted = (typeof CONFIG !== 'undefined' ? CONFIG.isMuted : false);
let djMode = localStorage.getItem('djMode') !== 'false'; // on by default

// --- Sync Tracking ---
// --- Sync Tracking ---
let hasTriggeredAutoNext = false; // flag to prevent multiple triggers for same song


// --- Image error fallback ---
function handleImageError(img, videoId) {
    const fallbacks = [
        `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`,
        `https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`
    ];
    let idx = fallbacks.indexOf(img.src);
    if (idx < fallbacks.length - 1) img.src = fallbacks[idx + 1];
    else img.onerror = null;
}

// --- DJ Mode ---
let peakMode = localStorage.getItem('peakMode') || 'best'; // 'best' | 'first'

function toggleDJMode() {
    djMode = !djMode;
    localStorage.setItem('djMode', djMode);
    const btn = document.getElementById('djToggleBtn');
    if (btn) btn.classList.toggle('active', djMode);
    _syncPeakModeBtn();
}

function togglePeakMode() {
    peakMode = peakMode === 'best' ? 'first' : 'best';
    localStorage.setItem('peakMode', peakMode);
    _syncPeakModeBtn();
}

function _syncPeakModeBtn() {
    const btn = document.getElementById('peakModeBtn');
    const label = document.getElementById('peakModeLabel');
    if (!btn || !label) return;
    btn.style.display = djMode ? 'flex' : 'none';
    label.textContent = peakMode === 'first' ? 'First' : 'Best';
}

function initDJToggle() {
    const btn = document.getElementById('djToggleBtn');
    if (btn) btn.classList.toggle('active', djMode);
    _syncPeakModeBtn();
}

window.addEventListener('DOMContentLoaded', initDJToggle);

// --- Clear button ---
function toggleClearBtn() {
    if (clearBtn && queryInput)
        clearBtn.style.display = queryInput.value.length > 0 ? 'block' : 'none';
}
if (queryInput && clearBtn) {
    queryInput.addEventListener('input', toggleClearBtn);
    clearBtn.addEventListener('click', () => { queryInput.value = ''; toggleClearBtn(); queryInput.focus(); });
    toggleClearBtn();
}

// --- Search box auto-hide timer ---
let searchHideTimer = null;
function resetSearchTimer() {
    if (searchHideTimer) clearTimeout(searchHideTimer);
    searchHideTimer = setTimeout(() => {
        if (document.activeElement !== queryInput && searchBox) {
            searchBox.classList.remove('visible');
        } else if (searchBox && searchBox.classList.contains('visible')) {
            resetSearchTimer();
        }
    }, 5000);
}
if (queryInput && searchBox) {
    queryInput.addEventListener('input', () => { toggleClearBtn(); resetSearchTimer(); });
    queryInput.addEventListener('focus', resetSearchTimer);
    searchBox.addEventListener('mousedown', resetSearchTimer);
    searchBox.addEventListener('touchstart', resetSearchTimer);
}

function toggleSearch() {
    if (!searchBox) return;
    const wledView = document.getElementById('wledView');
    if (wledView && wledView.style.display !== 'none') showHomeTab();
    if (!searchBox.classList.contains('visible')) {
        if (queryInput) { queryInput.value = ''; toggleClearBtn(); }
    }
    searchBox.classList.toggle('visible');
    if (searchBox.classList.contains('visible')) {
        if (queryInput) queryInput.focus();
        window.scrollTo({ top: 0, behavior: 'smooth' });
        resetSearchTimer();
    }
}

// ===================== Track Rendering =====================
const renderTrackItem = (t, i) => `
    <div class="track-item" data-title="${t.title}" data-videoid="${t.videoId}" data-thumb="${t.thumbnail}" data-artist="${t.artist}">
        <div class="track-index">${i}</div>
        <div class="track-thumb-box">
            <img src="${t.thumbnail}" alt="${t.title}" class="track-thumbnail" onerror="handleImageError(this, '${t.videoId}')">
        </div>
        <div class="track-info">
            <div class="track-title">${t.title}</div>
            <div class="track-artist-row">
                <span>${t.artist}</span>
                ${(t.labels || []).map(l => `<span class="badge ${l === 'Official' ? 'badge-official' : l === 'Remix' ? 'badge-remix' : l === 'Dance' ? 'badge-dance' : l === 'Slowed' ? 'badge-slowed' : ''}">${l}</span>`).join('')}
            </div>
        </div>
        <div class="track-actions">
            <button class="radio-btn" onclick="event.stopPropagation(); startRadio('${t.videoId}')" title="Start Radio">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M20 6H8.3l8.26-3.82a1 1 0 0 0-1.25-1.07l-9 4.14A2 2 0 0 0 5 6H4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2zm-3.5 10a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5zm-9 0a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z"/></svg>
            </button>
            <button class="menu-btn" onclick="event.stopPropagation()">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 16c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2zm0-6c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2zm0-6c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2z"/></svg>
            </button>
        </div>
    </div>`;

function updateContainers(videoList, songList, isCharts = false) {
    const noVideo = isCharts ? '' : '<div class="empty-state" style="padding:40px;text-align:center;color:var(--text-muted);"><p>No videos found</p></div>';
    const noSong = isCharts ? '' : '<div class="empty-state" style="padding:40px;text-align:center;color:var(--text-muted);"><p>No songs found</p></div>';
    document.getElementById('videosContainer').innerHTML = videoList.length ? videoList.map((t, i) => renderTrackItem(t, i + 1)).join('') : noVideo;
    document.getElementById('songsContainer').innerHTML = songList.length ? songList.map((t, i) => renderTrackItem(t, i + 1)).join('') : noSong;
}

// ===================== setType / Tab =====================
function setType(type) {
    document.getElementById('musicTypeInput').value = type;
    document.querySelectorAll('.type-option').forEach(opt => opt.classList.toggle('active', opt.dataset.type === type));
    document.getElementById('videosContainer').style.display = type === 'videos' ? 'block' : 'none';
    document.getElementById('songsContainer').style.display = type === 'songs' ? 'block' : 'none';
    try { localStorage.setItem('preferredMusicType', type); } catch (e) { }
    const container = document.getElementById(type + 'Container');
    if (container) {
        const count = container.querySelectorAll('.track-item').length;
        document.querySelector('.results-meta span').textContent = `${count} results • ${count} results`;
    }
}

window.addEventListener('DOMContentLoaded', () => {
    try {
        const saved = localStorage.getItem('preferredMusicType');
        if (saved === 'videos' || saved === 'songs') setType(saved);
    } catch (e) { }
});


// ===================== Search =====================
async function submitSearch(e, isRefresh = false) {
    if (e) e.preventDefault();
    const query = queryInput.value.trim();
    if (!query && !isRefresh) return;

    document.body.classList.add('searching');
    syncClient.send('search', {
        query: query,
        limit: 30,
        refresh: isRefresh,
        music_type: document.getElementById('musicTypeInput').value || 'videos'
    });
}

const trackForm = document.getElementById('trackForm');
if (trackForm) trackForm.addEventListener('submit', submitSearch);

window.addEventListener('load', () => {
    if (sessionStorage.getItem('searchPerformed') === 'true') {
        const sb = document.getElementById('searchBox');
        if (sb) sb.classList.add('visible');
        sessionStorage.removeItem('searchPerformed');
        resetSearchTimer();
    }
});

// ===================== Radio =====================
async function startRadio(videoId) {
    document.body.classList.add('searching');
    syncClient.send('radio', { videoId: videoId, limit: 50 });
}

// ===================== Charts =====================
async function fetchCharts() {
    const wledView = document.getElementById('wledView');
    if (wledView && wledView.style.display !== 'none') showHomeTab();
    document.body.classList.add('searching');
    try {
        const res = await fetch('/charts/?country=IN');
        if (!res.ok) throw new Error('Charts fetch failed');
        const data = await res.json();
        updateContainers(data.top_videos, data.top_songs, true);
        document.getElementById('songsContainer').style.display = 'block';
        document.getElementById('videosContainer').style.display = 'block';
        document.querySelector('.results-meta span').textContent = 'Trending • Top 20';
        setType('songs');
        queryInput.value = '';
    } catch (err) { console.error(err); alert('Failed to load charts'); }
    finally { document.body.classList.remove('searching'); }
}

// ===================== Unified Sync Client =====================
class DJSyncClient {
    constructor(role = 'controller') {
        this.role = role;
        this.roomId = null;
        this._changingRoom = false;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectDelay = 30000;
        this.baseDelay = 3000;
        this.pingInterval = null;
        this.connect();
    }
    connect() {
        const isLocal = !window.location.hostname ||
            ['localhost', '127.0.0.1'].includes(window.location.hostname) ||
            window.location.hostname.startsWith('192.168.') ||
            window.location.hostname.startsWith('10.') ||
            window.location.hostname.startsWith('172.');
        const WBase = 'wss://unappendaged-aretha-unwaning.ngrok-free.dev';
        const roomSuffix = this.roomId ? `&room_id=${this.roomId}` : '';
        const url = isLocal
            ? `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.hostname}:8045/ws/sync?role=${this.role}${roomSuffix}`
            : `${WBase}/ws/sync?role=${this.role}${roomSuffix}`;
        console.log(`[Sync] Connecting to ${url}...`);
        this.ws = new WebSocket(url);
        this.ws.onopen = () => {
            console.log('[Sync] ✅ Connected');
            this.reconnectAttempts = 0;
            this.startHeartbeat();
            const logoSvg = document.querySelector('#header-logo svg');
            if (logoSvg) logoSvg.style.color = '#0fff02';
        };
        this.ws.onmessage = (e) => {
            try { this.handleMessage(JSON.parse(e.data)); }
            catch (err) { console.error('[Sync] Parse error:', err); }
        };
        this.ws.onclose = (event) => {
            console.log('[Sync] 🔌 Disconnected', event.code);
            this.stopHeartbeat();
            const logoSvg = document.querySelector('#header-logo svg');
            if (logoSvg) logoSvg.style.color = '#ff0202';
            if (this._changingRoom) return;
            if (event.code === 4001) {
                // Room no longer exists; drop back to idle
                this.roomId = null;
                if (typeof roomClient !== 'undefined') {
                    roomClient.state = 'IDLE';
                    roomClient.currentRoom = null;
                    roomClient._showIdleView();
                    roomClient._updateHeaderBtn();
                    showToast('Room no longer available');
                }
                return;
            }
            this.retry();
        };
        this.ws.onerror = (err) => { console.error('[Sync] ❌ Error:', err); };
    }
    startHeartbeat() {
        this.pingInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) this.send('ping', { ts: Date.now() });
        }, 5000);
    }
    stopHeartbeat() { if (this.pingInterval) clearInterval(this.pingInterval); }
    retry() {
        if (this._changingRoom) return;
        const delay = Math.min(this.baseDelay * Math.pow(2, this.reconnectAttempts), this.maxReconnectDelay);
        console.log(`[Sync] Retrying in ${delay / 1000}s...`);
        setTimeout(() => { this.reconnectAttempts++; this.connect(); }, delay);
    }

    setRoom(room_id) {
        this._changingRoom = true;
        this.stopHeartbeat();
        this.roomId = room_id;
        this.reconnectAttempts = 0;
        if (this.ws) { try { this.ws.close(); } catch (_) {} }
        setTimeout(() => { this._changingRoom = false; this.connect(); }, 150);
    }
    send(type, data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type, data }));
        else console.warn(`[Sync] Cannot send ${type}, socket not open`);
    }
    handleMessage(msg) {
        const { type, data } = msg;

        // Logging handled for specific messages
        if (type !== 'pong' && type !== 'ping') {
            console.log(`[Sync Controller] Received message: ${type}`, data);
        }

        switch (type) {
            case 'pong': break;
            case 'player_status':
                if (data && data.currentTime !== undefined) {
                    console.log(`[Sync] Player Status - Video: ${data.videoId} | Time: ${data.currentTime.toFixed(2)}s / ${data.duration ? data.duration.toFixed(2) : 0}s | State: ${data.state} | Player: ${data.player_id || '?'}`);

                    const duration = parseInt(data.duration || 0);
                    const currentTime = parseInt(data.currentTime || 0);

                    updateSeekBar(currentTime, duration);
                    if (data.state === 1) startSeekTick(); else stopSeekTick();

                    const playerLabel = document.getElementById('activePlayerLabel');
                    if (playerLabel && data.player_id) {
                        playerLabel.textContent = data.player_id;
                        playerLabel.style.display = 'inline';
                    }

                    // Trigger next automatically if < 22s left
                    if (duration > 0 && data.state === 1) { // 1 = Playing
                        const remaining = duration - currentTime;
                        console.log(`[AutoAdvance] ⏭ Only ${remaining}s left, auto-advancing...`);
                        if (remaining < 50 && remaining > 5) {
                            console.log(`[AutoAdvance Pressed] ⏭ Only ${remaining}s left, auto-advancing...`);
                            sendPlayerControl('next', 5);
                        }
                    }
                }
                break;
            case 'play':
                console.log(`[Sync] Play - Video: ${data.videoId}`);
                updateSeekBar(0, 0);
                startSeekTick();
                if (data.videoid) {
                    const mp = document.getElementById('miniPlayer');
                    if (mp) mp.classList.add('active');
                    if (data.title) document.getElementById('nowPlayingTitle').textContent = data.title;
                    if (data.videoid) document.getElementById('nowPlayingVideoID').textContent = data.videoid;
                    isPlaying = true;
                    hasTriggeredAutoNext = false; // Reset skip flag for new song
                    const pp = document.getElementById('playPausePath');
                    if (pp) pp.setAttribute('d', 'M6 19h4V5H6v14zm8-14v14h4V5h-4z');
                }
                break;
            case 'vol':
                const v = parseInt(data.volume);
                if (!isNaN(v)) syncVolumeUI(v);
                break;
            case 'mute':
                if (data && 'isMuted' in data) {
                    isMuted = data.isMuted;
                    updateMuteUI();
                }
                break;
            case 'heatmap':
                renderHeatmap(data.values, data.step, data.peaks);
                break;
            case 'power_state':
                if (data && 'on' in data) {
                    const t = document.getElementById('wledPowerToggle');
                    if (t) t.checked = data.on;
                }
                break;
            case 'brightness_state':
                if (data && 'value' in data) {
                    const s = document.getElementById('wledBrightnessSlider');
                    if (s) s.value = data.value;
                }
                break;
            case 'color_state':
                if (data && data.hex) {
                    const slot = data.slot || 0;
                    colorSlotValues[slot] = data.hex;
                    if (slot === selectedColorSlot) {
                        const c = document.getElementById('wledColorPicker');
                        if (c) c.value = data.hex;
                    }
                    regenerateMarkerSwatches();
                }
                break;
            case 'sync_state':
                if (data && 'on' in data) {
                    const t = document.getElementById('wledClubSyncToggle');
                    if (t) t.checked = data.on;
                }
                break;
            case 'peakfx_state':
                if (data && 'on' in data) {
                    const t = document.getElementById('wledPeakFxToggle');
                    if (t) t.checked = data.on;
                }
                break;
            case 'palette_state':
                if (data && data.palette) setActivePaletteUI(data.palette);
                break;
            case 'effect_state':
                if (data && data.effect) setActiveEffectUI(data.effect);
                break;
            case 'control':
                this.handleControl(data);
                break;
            case 'qr':
                if (data.img) {
                    const qrImg = document.getElementById('qrImage');
                    const qrUrl = document.getElementById('qrUrl');
                    const qrMod = document.getElementById('qrModal');
                    if (qrImg) qrImg.src = `data:image/png;base64,${data.img.replace(/^"|"$/g, '')}`;
                    if (qrUrl) qrUrl.textContent = data.url || window.location.origin;
                    if (qrMod) qrMod.classList.add('active');
                }
                break;
            case 'suggestions':
                renderSuggestions(data.suggestions);
                break;
            case 'radio_result':
            case 'search_result':
                document.body.classList.remove('searching');
                if (data) {
                    if (data.query) queryInput.value = data.query;
                    updateContainers(data.video_tracks, data.song_tracks);

                    if (type === 'search_result') {
                        setType(data.music_type || 'videos');
                        sessionStorage.setItem('searchPerformed', 'true');
                        resetSearchTimer();
                        const np = document.getElementById('nextPlay');
                        if (np) np.checked = false;
                    } else {
                        document.querySelector('.results-meta span').textContent = 'Radio Mix • Dual Playlist';
                        queryInput.value = '';
                    }
                }
                break;
        }
    }
    handleControl(data) {
        console.log("[Sync Controller] handleControl called:", data);
        if (data.action === 'toggle' || data.action === 'stateChange') {
            if (data.state) {
                const playerLabel = document.getElementById('activePlayerLabel');
                const activePlayer = playerLabel ? playerLabel.textContent.trim() : null;
                const fromPlayer = data.player || null;

                // Only update icon if the event is from the currently active player
                if (fromPlayer && activePlayer && fromPlayer !== activePlayer) {
                    console.log(`[Sync Controller] Ignoring stateChange from ${fromPlayer}, active player is ${activePlayer}`);
                    return;
                }

                isPlaying = (data.state === 'playing');
                const pp2 = document.getElementById('playPausePath');
                if (pp2) pp2.setAttribute('d', isPlaying ? 'M6 19h4V5H6v14zm8-14v14h4V5h-4z' : 'M8 5v14l11-7z');
                if (isPlaying) startSeekTick(); else stopSeekTick();
            }
        }
    }
}

// ===================== Suggestions =====================
const suggestionsBox = document.getElementById('suggestionsBox');
let debounceTimer;

if (queryInput && suggestionsBox) {
    queryInput.addEventListener('input', (e) => {
        const val = e.target.value.trim();
        if (val.length > 0) {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => syncClient.send('suggest', { query: val }), 1000);
        } else {
            suggestionsBox.classList.remove('active');
        }
    });
    document.addEventListener('click', (e) => {
        if (!queryInput.contains(e.target) && !suggestionsBox.contains(e.target))
            suggestionsBox.classList.remove('active');
    });
    queryInput.addEventListener('focus', () => {
        if (queryInput.value.trim().length > 0)
            syncClient.send('suggest', { query: queryInput.value.trim() });
    });
}

function renderSuggestions(list) {
    if (!list || list.length === 0) { suggestionsBox.classList.remove('active'); return; }
    suggestionsBox.innerHTML = list.map(s => `
        <div class="suggestion-item" onclick="selectSuggestion('${s.replace(/'/g, "\\'")}')">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
            <span>${s}</span>
        </div>`).join('');
    suggestionsBox.classList.add('active');
}

function selectSuggestion(val) {
    queryInput.value = val;
    suggestionsBox.classList.remove('active');
    submitSearch();
}

// Initialize sync client
const syncClient = new DJSyncClient('controller');


const navVolSlider = document.getElementById('navVolSlider');
const navVolProgress = document.getElementById('navVolProgress');
const navVolLabel = document.getElementById('navVolLabel');
const qrModal = document.getElementById('qrModal');

// ===================== Seek Bar =====================
const seekProgress = document.getElementById('seekProgress');
const seekCurrentTimeEl = document.getElementById('seekCurrentTime');
const seekRemainingTimeEl = document.getElementById('seekRemainingTime');

let seekCurrentTime = 0;
let seekDuration = 0;
let seekTickInterval = null;

function formatTime(s) {
    const sec = Math.max(0, Math.floor(s));
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

function updateSeekBar(ct, dur) {
    seekCurrentTime = ct;
    seekDuration = dur;
    const pct = dur > 0 ? Math.min(100, (ct / dur) * 100) : 0;
    if (seekProgress) seekProgress.style.width = pct + '%';
    if (seekCurrentTimeEl) seekCurrentTimeEl.textContent = formatTime(ct);
    if (seekRemainingTimeEl) seekRemainingTimeEl.textContent = '-' + formatTime(dur - ct);
}

function startSeekTick() {
    stopSeekTick();
    seekTickInterval = setInterval(() => {
        if (seekDuration > 0 && seekCurrentTime < seekDuration) {
            updateSeekBar(seekCurrentTime + 1, seekDuration);
        }
    }, 1000);
}

function stopSeekTick() {
    if (seekTickInterval) { clearInterval(seekTickInterval); seekTickInterval = null; }
}

// ===================== Heatmap =====================
// Compact format from backend: { values: [0..1, ...], step: seconds, peaks: [midpoint, ...] }
function renderHeatmap(values, step, peakTimes) {
    const wrapper = document.getElementById('heatmapWrapper');
    const canvas = document.getElementById('heatmapCanvas');
    if (!wrapper || !canvas || !values || values.length === 0) return;

    wrapper.classList.add('visible');

    const dpr = window.devicePixelRatio || 1;
    const W = wrapper.offsetWidth;
    const H = wrapper.offsetHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    // Background
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, W, H);

    const totalDuration = values.length * step;
    const segW = Math.max(1, W / values.length);

    // Draw each segment as a vertical bar — height proportional to engagement value
    values.forEach((v, i) => {
        const x = (i / values.length) * W;
        const barH = v * H;
        const alpha = 0.25 + v * 0.75;
        ctx.fillStyle = `rgba(255, 30, 30, ${alpha.toFixed(2)})`;
        ctx.fillRect(x, H - barH, segW + 0.5, barH);
    });

    // Gradient fade at bottom — blends into the seek bar below
    const fadeGrad = ctx.createLinearGradient(0, 0, 0, H);
    fadeGrad.addColorStop(0, 'rgba(10,10,10,0)');
    fadeGrad.addColorStop(1, 'rgba(10,10,10,0.5)');
    ctx.fillStyle = fadeGrad;
    ctx.fillRect(0, 0, W, H);

    // Peak markers — thin white ticks at each detected hot-spot
    if (peakTimes && peakTimes.length) {
        ctx.fillStyle = 'rgba(255,255,255,0.75)';
        peakTimes.forEach(midpoint => {
            const x = Math.round((midpoint / totalDuration) * W);
            ctx.fillRect(x - 1, 0, 2, H);
        });
    }
}

// ===================== Seek Interaction =====================
const seekBarWrapper = document.querySelector('.seek-bar-wrapper');
let _isSeeking = false;
let _seekFlushTimer = null;

function _getSeekFraction(clientX) {
    const rect = seekBarWrapper.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
}

// Update UI instantly; send WS at most every 150ms during drag, always on release.
function _doSeek(fraction, final = false) {
    if (!seekBarWrapper || seekDuration <= 0) return;
    const seekTo = Math.round(fraction * seekDuration);
    updateSeekBar(seekTo, seekDuration);

    if (final) {
        if (_seekFlushTimer) { clearTimeout(_seekFlushTimer); _seekFlushTimer = null; }
        syncClient.send('control', { action: 'seek', seekTo });
    } else if (!_seekFlushTimer) {
        _seekFlushTimer = setTimeout(() => {
            _seekFlushTimer = null;
            syncClient.send('control', { action: 'seek', seekTo });
        }, 150);
    }
}

if (seekBarWrapper) {
    // --- Mouse ---
    seekBarWrapper.addEventListener('mousedown', (e) => {
        e.preventDefault();
        _isSeeking = true;
        seekBarWrapper.classList.add('seeking');
        stopSeekTick();
        _doSeek(_getSeekFraction(e.clientX));
    });

    document.addEventListener('mousemove', (e) => {
        if (!_isSeeking) return;
        _doSeek(_getSeekFraction(e.clientX));
    });

    document.addEventListener('mouseup', (e) => {
        if (!_isSeeking) return;
        _isSeeking = false;
        seekBarWrapper.classList.remove('seeking');
        _doSeek(_getSeekFraction(e.clientX), true);
        if (seekDuration > 0) startSeekTick();
    });

    // --- Touch ---
    seekBarWrapper.addEventListener('touchstart', (e) => {
        _isSeeking = true;
        seekBarWrapper.classList.add('seeking');
        stopSeekTick();
        _doSeek(_getSeekFraction(e.touches[0].clientX));
    }, { passive: true });

    document.addEventListener('touchmove', (e) => {
        if (!_isSeeking) return;
        _doSeek(_getSeekFraction(e.touches[0].clientX));
    }, { passive: true });

    document.addEventListener('touchend', () => {
        if (!_isSeeking) return;
        _isSeeking = false;
        seekBarWrapper.classList.remove('seeking');
        // Send final position (already set by last touchmove)
        if (_seekFlushTimer) { clearTimeout(_seekFlushTimer); _seekFlushTimer = null; }
        syncClient.send('control', { action: 'seek', seekTo: seekCurrentTime });
        if (seekDuration > 0) startSeekTick();
    });
}

// ===================== QR =====================
function toggleQR(e) {
    if (e) e.stopPropagation();
    if (qrModal && qrModal.classList.contains('active')) return hideQR();
    syncClient.send('qr', { url: window.location.origin });
}
function hideQR() { if (qrModal) qrModal.classList.remove('active'); }

// ===================== Player Controls =====================
function sendPlayerControl(action, delay = 1) {
    if (action === 'next' || action === 'prev') {
        const results = Array.from(document.querySelectorAll('.track-item'));
        if (results.length > 0) {
            const currentVideoID = document.getElementById('nowPlayingVideoID').textContent;
            const currentIndex = results.findIndex(item => item.dataset.videoid === currentVideoID);
            const targetIndex = action === 'next'
                ? (currentIndex + delay) % results.length
                : (currentIndex - 1 + results.length) % results.length;
            playTrackFromItem(results[targetIndex]);
            return;
        }
    }
    let msgData = { action, timestamp: Date.now() };
    if (action === 'toggle') {
        isPlaying = !isPlaying;
        const pp = document.getElementById('playPausePath');
        if (pp) pp.setAttribute('d', isPlaying ? 'M6 19h4V5H6v14zm8-14v14h4V5h-4z' : 'M8 5v14l11-7z');
        msgData.state = isPlaying ? 'playing' : 'paused';
    }
    syncClient.send('control', msgData);
}

function playTrackFromItem(item) {
    console.log(`[PlayTrack] Playing ${item.dataset}...`);
    const title = item.dataset.title;
    const vid = item.dataset.videoid;
    const artist = item.dataset.artist;
    const mp = document.getElementById('miniPlayer');
    if (mp) mp.classList.add('active');
    document.getElementById('nowPlayingTitle').textContent = title;
    document.getElementById('nowPlayingVideoID').textContent = vid;
    document.getElementById('nowPlayingArtist').textContent = artist;
    isPlaying = true;
    const pp = document.getElementById('playPausePath');
    if (pp) pp.setAttribute('d', 'M6 19h4V5H6v14zm8-14v14h4V5h-4z');

    let defaultVol = (typeof CONFIG !== 'undefined' ? CONFIG.maxVol : 100);
    const val = navVolSlider ? navVolSlider.value : (volSlider ? volSlider.value : defaultVol);

    document.body.classList.add('searching');
    syncClient.send('play', {
        videoId: vid,
        query: title,
        limit: 50,
        maxVol: parseInt(val),
        music_type: document.getElementById('musicTypeInput').value || 'videos',
        nextPlay: true,
        refresh: false,
        dj_mode: djMode,
        peak_mode: peakMode
    });

    if (queryInput) queryInput.value = title;
    const vi = document.getElementById('videoIdInput');
    const np = document.getElementById('nextPlay');
    const mv = document.getElementById('maxVol');
    if (vi) vi.value = vid;
    if (np) np.checked = true;
    if (mv) mv.value = val;
}

const tracksList = document.getElementById('tracksList');
if (tracksList) {
    tracksList.addEventListener('click', (e) => {
        const item = e.target.closest('.track-item');
        if (item && !e.target.closest('.menu-btn') && !e.target.closest('.radio-btn')) {
            playTrackFromItem(item);
        }
    });
}

// ===================== Volume =====================
function syncVolumeUI(v) {
    if (navVolSlider) navVolSlider.value = v;
    if (navVolProgress) navVolProgress.style.height = v + '%';
    if (navVolLabel) navVolLabel.textContent = v + '%';
    updateMuteUI();
}

function updateAllVolume(v) {
    const vol = parseInt(v);
    if (isNaN(vol)) return;
    syncVolumeUI(vol);
    syncClient.send('vol', { volume: vol });
}

function toggleMute() {
    isMuted = !isMuted;
    syncClient.send('mute', { isMuted: isMuted });
    updateMuteUI();
}

function updateMuteUI() {
    const muteIcon = document.getElementById('muteIcon');
    if (!muteIcon) return;

    const vol = navVolSlider ? parseInt(navVolSlider.value) : 100;
    const effectivelyMuted = isMuted || vol === 0;

    if (effectivelyMuted) {
        muteIcon.innerHTML = '<path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>';
        muteIcon.style.color = 'var(--primary)';
    } else {
        muteIcon.innerHTML = '<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>';
        muteIcon.style.color = 'var(--text-dim)';
    }
}

window.addEventListener('load', updateMuteUI);


let volumeHideTimer = null;
function resetVolumeTimer() {
    if (volumeHideTimer) clearTimeout(volumeHideTimer);
    const vp = document.getElementById('navVolumePopover');
    if (vp) volumeHideTimer = setTimeout(() => vp.classList.remove('active'), 3000);
}

if (navVolSlider) {
    function handleVertSlide(e) {
        const wrapper = document.querySelector('.vert-slider-wrapper');
        if (!wrapper) return;
        const rect = wrapper.getBoundingClientRect();
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        let pct = 1 - (clientY - rect.top) / rect.height;
        pct = Math.max(0, Math.min(100, Math.round(pct * 100)));
        updateAllVolume(pct);
        resetVolumeTimer();
        if (e.cancelable) e.preventDefault();
    }
    const hInput = document.getElementById('navVolSlider');
    hInput.addEventListener('mousedown', (e) => {
        handleVertSlide(e);
        const move = (me) => handleVertSlide(me);
        const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
    });
    hInput.addEventListener('touchstart', (e) => {
        handleVertSlide(e);
        const tmove = (te) => handleVertSlide(te);
        const tend = () => { document.removeEventListener('touchmove', tmove); document.removeEventListener('touchend', tend); };
        document.addEventListener('touchmove', tmove, { passive: false });
        document.addEventListener('touchend', tend);
    }, { passive: false });
    hInput.addEventListener('input', (e) => { updateAllVolume(e.target.value); resetVolumeTimer(); });
}

function toggleVolumePopover(e) {
    if (e) e.stopPropagation();
    const popover = document.getElementById('navVolumePopover');
    if (!popover) return;
    popover.classList.toggle('active');
    if (popover.classList.contains('active')) resetVolumeTimer();
}
document.addEventListener('click', () => {
    const vp = document.getElementById('navVolumePopover');
    if (vp) vp.classList.remove('active');
    if (volumeHideTimer) clearTimeout(volumeHideTimer);
});

// ===================== Sort =====================
let currentSort = 'official';
function cycleSort() {
    const modes = ['official', 'remix', 'lyrical', 'slowed', 'relevance'];
    currentSort = modes[(modes.indexOf(currentSort) + 1) % modes.length];
    const sl = document.getElementById('sortLabel');
    if (sl) sl.textContent = currentSort.charAt(0).toUpperCase() + currentSort.slice(1) + ' >';
    sortResults(currentSort);
}

function sortResults(criteria) {
    ['songsContainer', 'videosContainer'].forEach(id => {
        const container = document.getElementById(id);
        if (!container) return;
        const items = Array.from(container.querySelectorAll('.track-item'));
        items.sort((a, b) => {
            const getLabels = (el) => Array.from(el.querySelectorAll('.badge')).map(b => b.textContent.toLowerCase());
            const la = getLabels(a), lb = getLabels(b);
            if (criteria === 'official') return lb.includes('official') - la.includes('official');
            if (criteria === 'remix') return lb.includes('remix') - la.includes('remix');
            if (criteria === 'lyrical') return lb.includes('lyrical') - la.includes('lyrical');
            if (criteria === 'slowed') return lb.includes('slowed') - la.includes('slowed');
            return 0;
        });
        items.forEach(el => container.appendChild(el));
    });
}

window.addEventListener('load', () => { if (queryInput && !queryInput.value) queryInput.focus(); });

// ===================== Toast =====================
let toastTimer = null;
function showToast(msg) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
}

// ===================== Room Panel =====================
function openRoomPanel() {
    document.getElementById('roomPanel').classList.add('active');
    document.getElementById('roomPanelOverlay').classList.add('active');
    roomClient.refreshRooms();
}

function closeRoomPanel() {
    document.getElementById('roomPanel').classList.remove('active');
    document.getElementById('roomPanelOverlay').classList.remove('active');
}

// ===================== WLED Tab =====================
function showWledTab() {
    document.querySelector('.search-section').style.display = 'none';
    document.querySelector('.results-meta').style.display = 'none';
    document.getElementById('tracksList').style.display = 'none';
    document.getElementById('wledView').style.display = 'block';
    document.querySelectorAll('.nav-item').forEach((n) => n.classList.remove('active'));
    document.getElementById('wledNavBtn').classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showHomeTab() {
    document.querySelector('.search-section').style.display = '';
    document.querySelector('.results-meta').style.display = '';
    document.getElementById('tracksList').style.display = '';
    document.getElementById('wledView').style.display = 'none';
    document.querySelectorAll('.nav-item').forEach((n) => n.classList.remove('active'));
    const homeNav = document.querySelector('.nav-item[href="/"]');
    if (homeNav) homeNav.classList.add('active');
}

const wledPowerToggle = document.getElementById('wledPowerToggle');
if (wledPowerToggle) {
    wledPowerToggle.addEventListener('change', () => {
        const on = wledPowerToggle.checked;
        syncClient.send('power', { on });
        showToast(on ? 'WLED: On' : 'WLED: Off');
    });
}

const wledBrightnessSlider = document.getElementById('wledBrightnessSlider');
if (wledBrightnessSlider) {
    let brightnessDebounce = null;
    wledBrightnessSlider.addEventListener('input', () => {
        const value = parseInt(wledBrightnessSlider.value, 10);
        clearTimeout(brightnessDebounce);
        brightnessDebounce = setTimeout(() => {
            syncClient.send('brightness', { value });
        }, 150);
    });
}

const wledColorPicker = document.getElementById('wledColorPicker');
let selectedColorSlot = 0;
const colorSlotValues = { 0: '#ff0000', 1: '#000000', 2: '#000000' };

// "Structural" palettes (Random Cycle, Color 1, Colors 1&2, Color Gradient,
// Colors Only) render from the segment's own colors, not a fixed gradient —
// rebuild their swatch preview from whatever's currently picked, same as
// WLED's own UI does (its redrawPalPrev()).
const RAINBOW_GRADIENT = 'linear-gradient(to right, red, orange, #ff0, green, #00f, purple)';
const COLOR_SLOT_FOR_MARKER = { c1: 0, c2: 1, c3: 2 };

function regenerateMarkerSwatches() {
    document.querySelectorAll('.palette-chip[data-markers]').forEach((chip) => {
        let markers;
        try { markers = JSON.parse(chip.dataset.markers); } catch (e) { return; }
        const swatch = chip.querySelector('.palette-swatch');
        if (!swatch || !markers || !markers.length) return;

        if (markers[0] === 'r') {
            swatch.style.background = RAINBOW_GRADIENT;
            return;
        }
        const colors = markers.map((m) => colorSlotValues[COLOR_SLOT_FOR_MARKER[m]] || '#000000');
        if (colors.length === 1) {
            swatch.style.background = colors[0];
            return;
        }
        const stops = colors.map((c, i) => `${c} ${Math.round((i / (colors.length - 1)) * 100)}%`);
        swatch.style.background = `linear-gradient(to right, ${stops.join(', ')})`;
    });
}
regenerateMarkerSwatches();

function selectColorSlot(slot) {
    selectedColorSlot = slot;
    document.querySelectorAll('.color-slot-option').forEach((btn) => {
        btn.classList.toggle('active', Number(btn.dataset.slot) === slot);
    });
    if (wledColorPicker) wledColorPicker.value = colorSlotValues[slot];
}

if (wledColorPicker) {
    let colorDebounce = null;
    wledColorPicker.addEventListener('input', () => {
        const hex = wledColorPicker.value;
        colorSlotValues[selectedColorSlot] = hex;
        regenerateMarkerSwatches();
        clearTimeout(colorDebounce);
        colorDebounce = setTimeout(() => {
            syncClient.send('color', { hex, slot: selectedColorSlot });
        }, 150);
    });
}

// ===================== Club Sync =====================
const wledClubSyncToggle = document.getElementById('wledClubSyncToggle');
if (wledClubSyncToggle) {
    wledClubSyncToggle.addEventListener('change', () => {
        const on = wledClubSyncToggle.checked;
        syncClient.send('sync', { on });
        showToast(on ? 'Club Sync: On' : 'Club Sync: Off');
    });
}

const wledPeakFxToggle = document.getElementById('wledPeakFxToggle');
if (wledPeakFxToggle) {
    wledPeakFxToggle.addEventListener('change', () => {
        const on = wledPeakFxToggle.checked;
        syncClient.send('peakfx', { on });
        showToast(on ? 'Peak FX: On' : 'Peak FX: Off');
    });
}

async function resumeAutoSync() {
    try {
        const res = await fetch('/wled/sync/resume', { method: 'POST' });
        if (res.ok) showToast('Auto sync resumed');
    } catch (err) { console.error('[ClubSync] Resume failed:', err); }
}

// ===================== Palette Picker =====================
function setActivePaletteUI(paletteName) {
    document.querySelectorAll('.palette-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.palette === paletteName);
    });
}

function triggerPalette(name, chipEl) {
    setActivePaletteUI(name);
    syncClient.send('palette', { name });
    if (chipEl) showToast(`Palette: ${name}`);
}

const paletteGrid = document.getElementById('paletteGrid');
if (paletteGrid) {
    paletteGrid.addEventListener('click', (e) => {
        const chip = e.target.closest('.palette-chip');
        if (chip) triggerPalette(chip.dataset.palette, chip);
    });
}

// ===================== Effect Picker =====================
function setActiveEffectUI(effectName) {
    document.querySelectorAll('.effect-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.effect === effectName);
    });
}

function triggerEffect(name, chipEl) {
    setActiveEffectUI(name);
    syncClient.send('effect', { name });
    if (chipEl) showToast(`Effect: ${name}`);
    loadEffectControls(name);
}

const effectGrid = document.getElementById('effectGrid');
if (effectGrid) {
    effectGrid.addEventListener('click', (e) => {
        const chip = e.target.closest('.effect-chip');
        if (chip) triggerEffect(chip.dataset.effect, chip);
    });
}

// ===================== Effect Search / Sort =====================
const effectSearchInput = document.getElementById('effectSearchInput');
if (effectSearchInput && effectGrid) {
    effectSearchInput.addEventListener('input', () => {
        const q = effectSearchInput.value.trim().toLowerCase();
        effectGrid.querySelectorAll('.effect-chip').forEach((chip) => {
            const match = chip.dataset.effect.toLowerCase().includes(q);
            chip.style.display = match ? '' : 'none';
        });
    });
}

let effectSortMode = 'name';
function setEffectSort(mode) {
    if (!effectGrid) return;
    effectSortMode = mode;
    document.querySelectorAll('.effect-sort-option').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.sort === mode);
    });

    const chips = Array.from(effectGrid.querySelectorAll('.effect-chip'));
    chips.sort((a, b) => {
        if (mode === 'audio') {
            const audioDiff = Number(b.dataset.audio) - Number(a.dataset.audio);
            if (audioDiff !== 0) return audioDiff;
        }
        return a.dataset.effect.localeCompare(b.dataset.effect);
    });
    chips.forEach((chip) => effectGrid.appendChild(chip));
}

// ===================== Effect Controls (sx/ix/c1/c2/c3) =====================
const PARAM_KEYS = ['sx', 'ix', 'c1', 'c2', 'c3'];

async function loadEffectControls(name) {
    const empty = document.getElementById('effectControlsEmpty');
    const body = document.getElementById('effectControlsBody');
    if (!empty || !body) return;
    try {
        const res = await fetch(`/wled/effect/${encodeURIComponent(name)}/controls`);
        if (!res.ok) return;
        const { labels, defaults } = await res.json();

        let anyShown = false;
        PARAM_KEYS.forEach((key) => {
            const row = body.querySelector(`.ec-row[data-param-row="${key}"]`);
            if (!row) return;
            const label = labels[key];
            if (label) {
                anyShown = true;
                row.style.display = '';
                row.querySelector('label').textContent = label;
                const slider = row.querySelector('input[type="range"]');
                slider.value = (defaults && defaults[key] !== undefined) ? defaults[key] : 128;
            } else {
                row.style.display = 'none';
            }
        });

        empty.style.display = anyShown ? 'none' : '';
        body.style.display = anyShown ? '' : 'none';
    } catch (err) {
        console.error('[EffectControls] load failed:', err);
    }
}

const effectControlsBody = document.getElementById('effectControlsBody');
if (effectControlsBody) {
    const debounceTimers = {};
    effectControlsBody.addEventListener('input', (e) => {
        const slider = e.target.closest('input[type="range"]');
        if (!slider) return;
        const param = slider.dataset.param;
        const value = parseInt(slider.value, 10);
        clearTimeout(debounceTimers[param]);
        debounceTimers[param] = setTimeout(() => {
            syncClient.send('params', { [param]: value });
        }, 150);
    });
}

// ===================== RoomClient =====================
class RoomClient {
    constructor() {
        this.ws = null;
        this.state = 'IDLE'; // IDLE | HOST | MEMBER
        this.currentRoom = null;
        this._reconnectTimer = null;
        this._pingInterval = null;
        this._reconnectDelay = 3000;
        this.connect();
    }

    connect() {
        const isLocal = ['localhost', '127.0.0.1'].includes(location.hostname)
            || location.hostname.startsWith('192.168.')
            || location.hostname.startsWith('10.')
            || location.hostname.startsWith('172.');
        const WBase = 'wss://unappendaged-aretha-unwaning.ngrok-free.dev';
        const url = isLocal
            ? `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.hostname}:8045/ws/room`
            : `${WBase}/ws/room`;

        this.ws = new WebSocket(url);
        this.ws.onopen = () => {
            console.log('[Room] Connected');
            this._reconnectDelay = 3000;
            this._startHeartbeat();
        };
        this.ws.onmessage = (e) => {
            try { this._handle(JSON.parse(e.data)); } catch (err) { console.error('[Room] Parse error', err); }
        };
        this.ws.onclose = () => {
            console.log('[Room] Disconnected');
            this._stopHeartbeat();
            this._reconnectTimer = setTimeout(() => {
                this._reconnectDelay = Math.min(this._reconnectDelay * 2, 30000);
                this.connect();
            }, this._reconnectDelay);
        };
        this.ws.onerror = () => {};
    }

    _startHeartbeat() {
        this._pingInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) this._send('ping', {});
        }, 30000);
    }

    _stopHeartbeat() { clearInterval(this._pingInterval); }

    _send(type, data = {}) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, data }));
        }
    }

    _handle(msg) {
        const { type, data } = msg;
        switch (type) {
            case 'rooms_list':
                this._renderList(data.rooms || []);
                break;
            case 'room_created':
                this.state = 'HOST';
                this.currentRoom = data;
                this._showHostView(data);
                this._updateHeaderBtn();
                showToast('Room created — share the code!');
                syncClient.setRoom(data.id);
                break;
            case 'room_joined':
                this.state = 'MEMBER';
                this.currentRoom = data;
                this._showMemberView(data);
                this._updateHeaderBtn();
                syncClient.setRoom(data.id);
                break;
            case 'member_joined':
            case 'member_left':
                this._updateMemberCount(data.member_count);
                break;
            case 'room_closed':
                this.state = 'IDLE';
                this.currentRoom = null;
                this._showIdleView();
                this._updateHeaderBtn();
                showToast('Room was closed by the host');
                syncClient.setRoom(null);
                break;
            case 'error':
                showToast(this._errorMsg(data.code, data.message));
                break;
            case 'pong':
                break;
        }
    }

    _errorMsg(code) {
        const map = {
            ROOM_NOT_FOUND: 'Room not found — check the code',
            ROOM_FULL: 'Room is full',
            ALREADY_IN_ROOM: 'Leave your current room first',
            NAME_REQUIRED: 'Enter a room name or code',
        };
        return map[code] || 'Something went wrong';
    }

    // ── Public actions ──────────────────────────────────────────────

    createRoom() {
        const input = document.getElementById('roomNameInput');
        const name = (input ? input.value : '').trim();
        if (!name) { showToast('Enter a room name'); return; }
        this._send('create_room', { name, max_members: 20 });
        if (input) input.value = '';
    }

    joinRoom(roomId) {
        this._send('join_room', { room_id: roomId });
    }

    leaveRoom() {
        this._send('leave_room', {});
        this.state = 'IDLE';
        this.currentRoom = null;
        this._showIdleView();
        this._updateHeaderBtn();
        this.refreshRooms();
        syncClient.setRoom(null);
    }

    refreshRooms() {
        this._send('list_rooms', {});
    }

    copyCode() {
        if (!this.currentRoom) return;
        const code = this.currentRoom.id || '';
        navigator.clipboard.writeText(code).then(
            () => showToast(`Copied ${code}`),
            () => showToast('Could not copy — code: ' + code)
        );
    }

    // ── View rendering ──────────────────────────────────────────────

    _showIdleView() {
        document.getElementById('roomIdleView').style.display = '';
        document.getElementById('roomHostView').style.display = 'none';
        document.getElementById('roomMemberView').style.display = 'none';
    }

    _showHostView(data) {
        document.getElementById('roomIdleView').style.display = 'none';
        document.getElementById('roomHostView').style.display = '';
        document.getElementById('roomMemberView').style.display = 'none';
        document.getElementById('hostRoomCode').textContent = data.id || '——';
        document.getElementById('hostRoomName').textContent = data.name || '';
        document.getElementById('hostMemberCount').textContent = this._memberLabel(data.member_count);
    }

    _showMemberView(data) {
        document.getElementById('roomIdleView').style.display = 'none';
        document.getElementById('roomHostView').style.display = 'none';
        document.getElementById('roomMemberView').style.display = '';
        document.getElementById('memberRoomCode').textContent = data.id || '——';
        document.getElementById('memberRoomName').textContent = data.name || '';
        document.getElementById('memberCount').textContent = this._memberLabel(data.member_count);
    }

    _updateMemberCount(count) {
        const label = this._memberLabel(count);
        const hEl = document.getElementById('hostMemberCount');
        const mEl = document.getElementById('memberCount');
        if (hEl) hEl.textContent = label;
        if (mEl) mEl.textContent = label;
        if (this.currentRoom) this.currentRoom.member_count = count;
    }

    _renderList(rooms) {
        const container = document.getElementById('roomsList');
        if (!container) return;

        if (!rooms.length) {
            container.innerHTML = `
                <div class="room-empty-state">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" style="color:var(--text-muted);margin-bottom:10px">
                        <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>
                    </svg>
                    <p>No rooms yet</p>
                    <span>Create one above to get started</span>
                </div>`;
            return;
        }

        const inRoom = this.state !== 'IDLE';
        container.innerHTML = rooms.map(r => {
            const full = r.member_count >= r.max_members;
            const disabled = inRoom || full;
            const meta = `${r.member_count}/${r.max_members} members${full ? ' · Full' : ''}`;
            return `
            <div class="room-card">
                <div class="room-card-info">
                    <div class="room-card-name">${this._esc(r.name)}</div>
                    <div class="room-card-meta">${meta} · <span style="font-family:monospace;letter-spacing:.05em">${r.id}</span></div>
                </div>
                <button class="room-join-btn" onclick="roomClient.joinRoom('${r.id}')" ${disabled ? 'disabled' : ''}>
                    Join
                </button>
            </div>`;
        }).join('');
    }

    _memberLabel(n) { return n === 1 ? '1 member' : `${n} members`; }

    _esc(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    _updateHeaderBtn() {
        const btn = document.getElementById('roomHeaderBtn');
        if (!btn) return;
        btn.classList.toggle('room-active', this.state !== 'IDLE');
    }
}

const roomClient = new RoomClient();
