// Podcast Clips Dashboard

let allClips = [];
let filteredClips = [];
let postedIds = new Set();
let activeIndex = -1;  // Currently selected clip for keyboard nav

// Generate embed URL from clip data
function getEmbedUrl(clip) {
    if (clip.embed_url) return clip.embed_url;
    // Generate from video_id and timestamps
    const start = Math.floor(clip.start_time || 0);
    const end = Math.floor(clip.end_time || start + 60);
    return `https://www.youtube.com/embed/${clip.video_id}?start=${start}&end=${end}&autoplay=0`;
}

// Estimate score for clips that don't have one
function estimateScore(clip) {
    if (clip.score && clip.score > 0) return clip.score;

    // Base score
    let score = 5.0;

    // Bonus for certain patterns
    const patternBonus = {
        'PREDICTION': 1.5,
        'HOT_TAKE': 1.5,
        'BOLD PREDICTION': 1.5,
        'INSIGHT': 1.0,
        'DATA': 1.0,
        'SPECIFIC NUMBERS': 1.0,
        'HUMOR': 0.5
    };
    score += patternBonus[clip.pattern] || 0;

    // Bonus for longer quotable lines (more substance)
    if (clip.quotable_line && clip.quotable_line.length > 30) score += 0.5;

    // Bonus for good clip duration (30-60s is ideal)
    const duration = (clip.end_time || 0) - (clip.start_time || 0);
    if (duration >= 30 && duration <= 60) score += 0.5;

    return Math.min(10, Math.max(1, score));
}

// Load clips and posted state
async function loadClips() {
    try {
        // Load clips
        const clipsRes = await fetch('clips.json');
        if (!clipsRes.ok) throw new Error('Failed to load clips');
        const data = await clipsRes.json();

        // Add estimated scores and embed URLs to clips that don't have them
        allClips = (data.clips || []).map(clip => ({
            ...clip,
            score: estimateScore(clip),
            embed_url: getEmbedUrl(clip)
        }));

        // Load posted state from localStorage
        const saved = localStorage.getItem('postedClips');
        if (saved) {
            postedIds = new Set(JSON.parse(saved));
        }

        // Populate channel filter
        populateChannelFilter(data.metadata?.channels || []);

        // Update stats
        updateStats(data.metadata);

        // Display clips
        filterAndDisplay();
    } catch (error) {
        console.error('Error loading clips:', error);
        document.getElementById('clips-container').innerHTML = `
            <div class="empty-state">
                <h2>No clips yet</h2>
                <p>Clips will appear here after the first run.</p>
            </div>
        `;
    }
}

// Get clip ID
function getClipId(clip) {
    return `${clip.video_id}_${clip.start_time}`;
}

// Populate channel dropdown
function populateChannelFilter(channels) {
    const select = document.getElementById('channel-filter');
    channels.sort().forEach(channel => {
        const option = document.createElement('option');
        option.value = channel;
        option.textContent = channel;
        select.appendChild(option);
    });
}

// Update stats display
function updateStats(metadata) {
    if (!metadata) return;
    const stats = document.getElementById('stats');
    const date = new Date(metadata.generated_at);
    const unposted = allClips.filter(c => !postedIds.has(getClipId(c))).length;
    stats.textContent = `${metadata.total_clips} clips (${unposted} unposted) • Updated ${formatRelativeTime(date)}`;
}

// Format relative time
function formatRelativeTime(date) {
    const now = new Date();
    const diff = now - date;
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor(diff / (1000 * 60));

    if (hours > 24) {
        return date.toLocaleDateString();
    } else if (hours > 0) {
        return `${hours}h ago`;
    } else if (minutes > 0) {
        return `${minutes}m ago`;
    } else {
        return 'just now';
    }
}

// Normalize pattern for filtering
function normalizePattern(pattern) {
    if (!pattern) return '';
    const p = pattern.toLowerCase().replace(/[^a-z]/g, '');
    if (p.includes('prediction') || p.includes('bold')) return 'prediction';
    if (p.includes('hot') || p.includes('take') || p.includes('truth')) return 'hot_take';
    if (p.includes('insight')) return 'insight';
    if (p.includes('data') || p.includes('number') || p.includes('specific')) return 'data';
    if (p.includes('humor') || p.includes('funny')) return 'humor';
    return p;
}

// Get clip duration category
function getDurationCategory(clip) {
    const duration = (clip.end_time || 0) - (clip.start_time || 0);
    if (duration < 45) return 'short';
    if (duration <= 75) return 'medium';
    return 'long';
}

// Filter and display clips
function filterAndDisplay() {
    const searchTerm = document.getElementById('search').value.toLowerCase();
    const channelFilter = document.getElementById('channel-filter').value;
    const patternFilter = document.getElementById('pattern-filter')?.value || '';
    const durationFilter = document.getElementById('duration-filter')?.value || '';
    const sortOrder = document.getElementById('sort').value;
    const hidePosted = document.getElementById('hide-posted')?.checked || false;
    const highScoreOnly = document.getElementById('high-score-only')?.checked || false;

    // Filter
    filteredClips = allClips.filter(clip => {
        const clipId = getClipId(clip);
        const isPosted = postedIds.has(clipId);

        if (hidePosted && isPosted) return false;
        if (highScoreOnly && (clip.score || 0) < 7) return false;

        const matchesSearch = !searchTerm ||
            clip.quotable_line?.toLowerCase().includes(searchTerm) ||
            clip.transcript_text?.toLowerCase().includes(searchTerm) ||
            clip.channel_name?.toLowerCase().includes(searchTerm) ||
            clip.video_title?.toLowerCase().includes(searchTerm);

        const matchesChannel = !channelFilter || clip.channel_name === channelFilter;
        const matchesPattern = !patternFilter || normalizePattern(clip.pattern) === patternFilter;
        const matchesDuration = !durationFilter || getDurationCategory(clip) === durationFilter;

        return matchesSearch && matchesChannel && matchesPattern && matchesDuration;
    });

    // Sort
    if (sortOrder === 'score') {
        filteredClips.sort((a, b) => (b.score || 0) - (a.score || 0));
    } else if (sortOrder === 'duration') {
        filteredClips.sort((a, b) => {
            const durA = (a.end_time || 0) - (a.start_time || 0);
            const durB = (b.end_time || 0) - (b.start_time || 0);
            return durA - durB;
        });
    } else {
        filteredClips.sort((a, b) => {
            const dateA = new Date(a.published_at || a.created_at);
            const dateB = new Date(b.published_at || b.created_at);
            return sortOrder === 'newest' ? dateB - dateA : dateA - dateB;
        });
    }

    // Display
    displayClips(filteredClips);
    updateQuickStats();
    activeIndex = -1;  // Reset selection on filter change
}

// Display clips
function displayClips(clips) {
    const container = document.getElementById('clips-container');

    if (clips.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <h2>No clips found</h2>
                <p>Try a different search or filter.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = clips.map((clip, index) => createClipCard(clip, index)).join('');
}

// Get local clip URL (for clips that have been generated)
function getLocalClipUrl(clip) {
    // Check if a local clip exists
    const clipFilename = `${clip.video_id}_${Math.floor(clip.start_time)}_${Math.floor(clip.end_time)}.mp4`;
    return `clips/${clipFilename}`;
}

// Create video player HTML
function createVideoPlayer(clip, index) {
    const embedUrl = getEmbedUrl(clip);
    const localClipUrl = getLocalClipUrl(clip);

    // Show video with fallback: try local clip first, then YouTube embed
    return `
        <div class="video-container" id="video-${index}">
            <video controls preload="metadata"
                poster="${clip.thumbnail_url || ''}"
                onerror="this.style.display='none'; document.getElementById('embed-${index}').style.display='block';">
                <source src="${localClipUrl}" type="video/mp4">
            </video>
            <iframe id="embed-${index}" style="display:none"
                src="${embedUrl}"
                title="Clip from ${escapeHtml(clip.channel_name)}"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowfullscreen
                loading="lazy">
            </iframe>
        </div>
        <div class="video-actions">
            <a href="${localClipUrl}" download="${clip.video_id}_clip.mp4" class="btn btn-secondary download-btn">
                ⬇ Download Clip
            </a>
        </div>
    `;
}

// Create clip card HTML
function createClipCard(clip, index) {
    const date = new Date(clip.published_at || clip.created_at);
    const formattedDate = date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric'
    });

    const duration = Math.round(clip.end_time - clip.start_time);
    const clipId = getClipId(clip);
    const isPosted = postedIds.has(clipId);
    const score = clip.score ? `${clip.score.toFixed(1)}/10` : '';

    return `
        <article class="clip-card ${isPosted ? 'posted' : ''}" data-index="${index}" data-clip-id="${clipId}">
            <div class="clip-header">
                <div>
                    <div class="channel-name">${escapeHtml(clip.channel_name)}</div>
                    <div class="video-title">${escapeHtml(clip.video_title)}</div>
                </div>
                <div class="clip-meta">
                    <div>${formattedDate}</div>
                    <div>${duration}s</div>
                    ${score ? `<span class="score-tag">${score}</span>` : ''}
                    ${clip.pattern ? `<span class="pattern-tag">${escapeHtml(clip.pattern)}</span>` : ''}
                    ${isPosted ? '<span class="posted-tag">Posted</span>' : ''}
                </div>
            </div>

            ${createVideoPlayer(clip, index)}

            <div class="quotable-line">"${escapeHtml(clip.quotable_line)}"</div>

            <div class="post-text">${escapeHtml(clip.full_post_text)}</div>

            <div class="clip-actions">
                <button class="btn btn-primary" onclick="copyPost(${index})">
                    Copy Post
                </button>
                <button class="btn ${isPosted ? 'btn-posted' : 'btn-secondary'}" onclick="togglePosted('${clipId}')">
                    ${isPosted ? 'Unmark Posted' : 'Mark Posted'}
                </button>
                <a href="${clip.youtube_url}" target="_blank" class="btn btn-secondary">
                    Watch
                </a>
                <button class="btn btn-secondary" onclick="toggleTranscript(${index})">
                    Transcript
                </button>
            </div>

            <div class="transcript-toggle">
                <div class="transcript-text" id="transcript-${index}">
                    ${escapeHtml(clip.transcript_text)}
                </div>
            </div>
        </article>
    `;
}

// Copy post to clipboard
async function copyPost(index) {
    const clip = filteredClips[index];
    try {
        await navigator.clipboard.writeText(clip.full_post_text);

        // Visual feedback
        const btn = document.querySelector(`[data-index="${index}"] .btn-primary`);
        if (btn) {
            btn.textContent = 'Copied!';
            btn.classList.add('copied');

            setTimeout(() => {
                btn.textContent = 'Copy Post';
                btn.classList.remove('copied');
            }, 2000);
        }

        showToast('Copied to clipboard!');
    } catch (err) {
        console.error('Failed to copy:', err);
        showToast('Failed to copy - try again');
    }
}

// Toggle posted state
function togglePosted(clipId) {
    if (postedIds.has(clipId)) {
        postedIds.delete(clipId);
    } else {
        postedIds.add(clipId);
    }

    // Save to localStorage
    localStorage.setItem('postedClips', JSON.stringify([...postedIds]));

    // Refresh display
    filterAndDisplay();
    updateStats({ total_clips: allClips.length, generated_at: new Date().toISOString() });
}

// Toggle transcript visibility
function toggleTranscript(index) {
    const el = document.getElementById(`transcript-${index}`);
    el.classList.toggle('show');
}

// Escape HTML
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Event listeners
document.getElementById('search').addEventListener('input', filterAndDisplay);
document.getElementById('channel-filter').addEventListener('change', filterAndDisplay);
document.getElementById('sort').addEventListener('change', filterAndDisplay);

// Pattern filter
const patternFilterEl = document.getElementById('pattern-filter');
if (patternFilterEl) {
    patternFilterEl.addEventListener('change', filterAndDisplay);
}

// Duration filter
const durationFilterEl = document.getElementById('duration-filter');
if (durationFilterEl) {
    durationFilterEl.addEventListener('change', filterAndDisplay);
}

// Hide posted checkbox
const hidePostedCheckbox = document.getElementById('hide-posted');
if (hidePostedCheckbox) {
    hidePostedCheckbox.addEventListener('change', filterAndDisplay);
}

// High score only checkbox
const highScoreCheckbox = document.getElementById('high-score-only');
if (highScoreCheckbox) {
    highScoreCheckbox.addEventListener('change', filterAndDisplay);
}

// Update quick stats
function updateQuickStats() {
    const total = allClips.length;
    const unposted = allClips.filter(c => !postedIds.has(getClipId(c))).length;
    const highScore = allClips.filter(c => (c.score || 0) >= 7).length;
    const showing = filteredClips.length;

    document.getElementById('stat-total').textContent = total;
    document.getElementById('stat-unposted').textContent = unposted;
    document.getElementById('stat-high').textContent = highScore;
    document.getElementById('stat-showing').textContent = showing;
}

// Show toast notification
function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2000);
}

// Set active clip (for keyboard navigation)
function setActiveClip(index) {
    // Remove previous active
    document.querySelectorAll('.clip-card.active').forEach(el => el.classList.remove('active'));

    if (index >= 0 && index < filteredClips.length) {
        activeIndex = index;
        const card = document.querySelector(`[data-index="${index}"]`);
        if (card) {
            card.classList.add('active');
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }
}

// Keyboard navigation
document.addEventListener('keydown', (e) => {
    // Ignore if typing in search
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

    switch (e.key.toLowerCase()) {
        case 'j':  // Next clip
            setActiveClip(Math.min(activeIndex + 1, filteredClips.length - 1));
            break;
        case 'k':  // Previous clip
            setActiveClip(Math.max(activeIndex - 1, 0));
            break;
        case 'c':  // Copy active clip
            if (activeIndex >= 0) {
                copyPost(activeIndex);
                showToast('Copied to clipboard!');
            }
            break;
        case 'p':  // Toggle posted
            if (activeIndex >= 0) {
                const clip = filteredClips[activeIndex];
                const clipId = getClipId(clip);
                togglePosted(clipId);
            }
            break;
        case '/':  // Focus search
            e.preventDefault();
            document.getElementById('search').focus();
            break;
    }
});

// Load on page load
loadClips();
