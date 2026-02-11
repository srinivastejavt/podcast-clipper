// Podcast Clips Dashboard

let allClips = [];
let filteredClips = [];

// Load clips from JSON
async function loadClips() {
    try {
        const response = await fetch('clips.json');
        if (!response.ok) {
            throw new Error('Failed to load clips');
        }
        const data = await response.json();
        allClips = data.clips || [];

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
                <p>Clips will appear here after the first GitHub Actions run.</p>
            </div>
        `;
    }
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
    stats.textContent = `${metadata.total_clips} clips from ${metadata.channels?.length || 0} channels • Updated ${formatRelativeTime(date)}`;
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

// Filter and display clips
function filterAndDisplay() {
    const searchTerm = document.getElementById('search').value.toLowerCase();
    const channelFilter = document.getElementById('channel-filter').value;
    const sortOrder = document.getElementById('sort').value;

    // Filter
    filteredClips = allClips.filter(clip => {
        const matchesSearch = !searchTerm ||
            clip.quotable_line?.toLowerCase().includes(searchTerm) ||
            clip.transcript_text?.toLowerCase().includes(searchTerm) ||
            clip.channel_name?.toLowerCase().includes(searchTerm) ||
            clip.video_title?.toLowerCase().includes(searchTerm);

        const matchesChannel = !channelFilter || clip.channel_name === channelFilter;

        return matchesSearch && matchesChannel;
    });

    // Sort
    filteredClips.sort((a, b) => {
        const dateA = new Date(a.published_at || a.created_at);
        const dateB = new Date(b.published_at || b.created_at);
        return sortOrder === 'newest' ? dateB - dateA : dateA - dateB;
    });

    // Display
    displayClips(filteredClips);
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

// Create clip card HTML
function createClipCard(clip, index) {
    const date = new Date(clip.published_at || clip.created_at);
    const formattedDate = date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric'
    });

    const duration = Math.round(clip.end_time - clip.start_time);

    return `
        <article class="clip-card" data-index="${index}">
            <div class="clip-header">
                <div>
                    <div class="channel-name">${escapeHtml(clip.channel_name)}</div>
                    <div class="video-title">${escapeHtml(clip.video_title)}</div>
                </div>
                <div class="clip-meta">
                    <div>${formattedDate}</div>
                    <div>${duration}s clip</div>
                    ${clip.pattern ? `<span class="pattern-tag">${escapeHtml(clip.pattern)}</span>` : ''}
                </div>
            </div>

            <div class="quotable-line">"${escapeHtml(clip.quotable_line)}"</div>

            <div class="post-text">${escapeHtml(clip.full_post_text)}</div>

            <div class="clip-actions">
                <button class="btn btn-primary" onclick="copyPost(${index})">
                    Copy Post
                </button>
                <a href="${clip.youtube_url}" target="_blank" class="btn btn-secondary">
                    Watch Clip
                </a>
                <button class="btn btn-secondary" onclick="toggleTranscript(${index})">
                    Show Transcript
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
        btn.textContent = 'Copied!';
        btn.classList.add('copied');

        setTimeout(() => {
            btn.textContent = 'Copy Post';
            btn.classList.remove('copied');
        }, 2000);
    } catch (err) {
        console.error('Failed to copy:', err);
        alert('Failed to copy. Please select and copy manually.');
    }
}

// Toggle transcript visibility
function toggleTranscript(index) {
    const el = document.getElementById(`transcript-${index}`);
    el.classList.toggle('show');

    const btn = document.querySelector(`[data-index="${index}"] .transcript-toggle`).previousElementSibling.lastElementChild;
    btn.textContent = el.classList.contains('show') ? 'Hide Transcript' : 'Show Transcript';
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

// Load on page load
loadClips();
