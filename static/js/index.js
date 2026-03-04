// --- Global DOM refs ---
const queryInput = document.getElementById('queryInput');
const clearBtn = document.getElementById('clearBtn');
const searchBox = document.getElementById('searchBox');

// --- Global state variables ---
let isPlaying = false;
let isMuted = (typeof CONFIG !== 'undefined' ? CONFIG.isMuted : false);

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
        const url = isLocal
            ? `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.hostname}:8045/ws/sync?role=${this.role}`
            : `${WBase}/ws/sync?role=${this.role}`;
        console.log(`[Sync] Connecting to ${url}...`);
        this.ws = new WebSocket(url);
        this.ws.onopen = () => {
            console.log('[Sync] ✅ Connected');
            this.reconnectAttempts = 0;
            this.startHeartbeat();
        };
        this.ws.onmessage = (e) => {
            try { this.handleMessage(JSON.parse(e.data)); }
            catch (err) { console.error('[Sync] Parse error:', err); }
        };
        this.ws.onclose = () => { console.log('[Sync] 🔌 Disconnected'); this.stopHeartbeat(); this.retry(); };
        this.ws.onerror = (err) => { console.error('[Sync] ❌ Error:', err); };
    }
    startHeartbeat() {
        this.pingInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) this.send('ping', { ts: Date.now() });
        }, 10000);
    }
    stopHeartbeat() { if (this.pingInterval) clearInterval(this.pingInterval); }
    retry() {
        const delay = Math.min(this.baseDelay * Math.pow(2, this.reconnectAttempts), this.maxReconnectDelay);
        console.log(`[Sync] Retrying in ${delay / 1000}s...`);
        setTimeout(() => { this.reconnectAttempts++; this.connect(); }, delay);
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
                    console.log(`[Sync] Player Status - Video: ${data.videoId} | Time: ${data.currentTime.toFixed(2)}s / ${data.duration ? data.duration.toFixed(2) : 0}s | State: ${data.state}`);

                    const duration = parseInt(data.duration || 0);
                    const currentTime = parseInt(data.currentTime || 0);

                    // Trigger next automatically if < 22s left
                    if (duration > 0 && data.state === 1) { // 1 = Playing
                        const remaining = duration - currentTime;
                        if (remaining < 100 && remaining > 5) {
                            console.log(`[AutoAdvance] ⏭ Only ${remaining}s left, auto-advancing...`);
                            sendPlayerControl('next');
                        }
                    }
                }
                break;
            case 'play':
                if (data.videoId) {
                    const mp = document.getElementById('miniPlayer');
                    if (mp) mp.classList.add('active');
                    if (data.title) document.getElementById('nowPlayingTitle').textContent = data.title;
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
                isPlaying = (data.state === 'playing');
                const pp2 = document.getElementById('playPausePath');
                if (pp2) pp2.setAttribute('d', isPlaying ? 'M6 19h4V5H6v14zm8-14v14h4V5h-4z' : 'M8 5v14l11-7z');
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


const volSlider = document.getElementById('volumeSlider');
const volProgress = document.getElementById('volProgress');
const navVolSlider = document.getElementById('navVolSlider');
const navVolProgress = document.getElementById('navVolProgress');
const navVolLabel = document.getElementById('navVolLabel');
const qrModal = document.getElementById('qrModal');

// ===================== QR =====================
function toggleQR(e) {
    if (e) e.stopPropagation();
    if (qrModal && qrModal.classList.contains('active')) return hideQR();
    syncClient.send('qr', { url: window.location.origin });
}
function hideQR() { if (qrModal) qrModal.classList.remove('active'); }

// ===================== Player Controls =====================
function sendPlayerControl(action) {
    if (action === 'next' || action === 'prev') {
        const results = Array.from(document.querySelectorAll('.track-item'));
        if (results.length > 0) {
            const currentTitle = document.getElementById('nowPlayingTitle').textContent;
            const currentIndex = results.findIndex(item => item.dataset.title === currentTitle);
            const targetIndex = action === 'next'
                ? (currentIndex + 1) % results.length
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
    const title = item.dataset.title;
    const vid = item.dataset.videoid;
    const artist = item.dataset.artist;
    const mp = document.getElementById('miniPlayer');
    if (mp) mp.classList.add('active');
    document.getElementById('nowPlayingTitle').textContent = title;
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
        refresh: false
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
    if (volSlider) volSlider.value = v;
    if (volProgress) volProgress.style.width = v + '%';
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

    const vol = volSlider ? parseInt(volSlider.value) : 100;
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

if (volSlider) volSlider.addEventListener('input', (e) => updateAllVolume(e.target.value));

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
