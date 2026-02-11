#!/usr/bin/env python3
"""
Fetch Clips - Entry point for GitHub Actions

Uses RSS feeds (no quota limits!) to fetch videos, then processes for clips.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rss_monitor import rss_monitor
from src.orchestrator_web import orchestrator_web

# Output paths
DOCS_DIR = Path(__file__).parent.parent / "docs"
CLIPS_FILE = DOCS_DIR / "clips.json"
STATE_FILE = Path(__file__).parent.parent / "data" / "processed_videos.json"
POSTED_FILE = DOCS_DIR / "posted.json"


def load_processed_videos() -> set:
    """Load set of already processed video IDs."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            data = json.load(f)
            return set(data.get("video_ids", []))
    return set()


def save_processed_videos(video_ids: set):
    """Save processed video IDs."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump({"video_ids": list(video_ids), "updated_at": datetime.utcnow().isoformat()}, f)


def load_existing_clips() -> list:
    """Load existing clips from JSON."""
    if CLIPS_FILE.exists():
        with open(CLIPS_FILE) as f:
            data = json.load(f)
            return data.get("clips", [])
    return []


def load_posted_clips() -> set:
    """Load set of posted clip IDs."""
    if POSTED_FILE.exists():
        with open(POSTED_FILE) as f:
            data = json.load(f)
            return set(data.get("posted_ids", []))
    return set()


def save_clips(clips: list, posted_ids: set):
    """Save clips to JSON with posted status."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # Mark clips as posted
    for clip in clips:
        clip_id = f"{clip.get('video_id')}_{clip.get('start_time')}"
        clip['posted'] = clip_id in posted_ids

    # Sort by published date (newest first)
    clips.sort(key=lambda c: c.get("published_at", ""), reverse=True)

    # Keep only last 14 days of clips
    cutoff = (datetime.utcnow() - timedelta(days=14)).isoformat()
    clips = [c for c in clips if c.get("published_at", "") > cutoff or c.get("created_at", "") > cutoff]

    data = {
        "clips": clips,
        "metadata": {
            "total_clips": len(clips),
            "unposted_clips": len([c for c in clips if not c.get('posted')]),
            "generated_at": datetime.utcnow().isoformat(),
            "channels": list(set(c.get("channel_name", "") for c in clips))
        }
    }

    with open(CLIPS_FILE, "w") as f:
        json.dump(data, f, indent=2)

    logger.info(f"Saved {len(clips)} clips ({data['metadata']['unposted_clips']} unposted)")


async def main():
    """Main entry point."""
    logger.info("=== Podcast Clip Fetcher (RSS - No Quota!) ===")

    # Groq is optional - will fall back to Ollama if not set
    if not os.getenv("GROQ_API_KEY"):
        logger.info("GROQ_API_KEY not set - using local Ollama")

    # Load state
    processed_ids = load_processed_videos()
    existing_clips = load_existing_clips()
    posted_ids = load_posted_clips()
    logger.info(f"State: {len(processed_ids)} processed, {len(existing_clips)} clips, {len(posted_ids)} posted")

    # Fetch recent videos via RSS (no quota limits!)
    logger.info("Fetching via RSS feeds...")
    videos = await rss_monitor.check_all_channels(since_hours=48)

    # Filter to podcasts only
    podcasts = [v for v in videos if rss_monitor.is_likely_podcast(v)]
    logger.info(f"Found {len(podcasts)} podcasts")

    # Filter out already processed
    new_podcasts = [v for v in podcasts if v.video_id not in processed_ids]
    logger.info(f"New to process: {len(new_podcasts)}")

    if not new_podcasts:
        logger.info("No new podcasts to process")
        # Still save to update posted status
        save_clips(existing_clips, posted_ids)
        return

    # Process each video
    new_clips = []
    for video in new_podcasts:
        try:
            clips = await orchestrator_web.process_video(video)
            for clip in clips:
                clip_dict = clip.to_dict()
                clip_dict['thumbnail_url'] = video.thumbnail_url
                new_clips.append(clip_dict)
            processed_ids.add(video.video_id)
        except Exception as e:
            logger.error(f"Failed to process {video.video_id}: {e}")
            # Still mark as processed to avoid retrying broken videos
            processed_ids.add(video.video_id)

    logger.info(f"Found {len(new_clips)} new clips")

    # Merge with existing clips
    all_clips = existing_clips + new_clips

    # Remove duplicates (by video_id + start_time)
    seen = set()
    unique_clips = []
    for clip in all_clips:
        key = (clip.get("video_id"), clip.get("start_time"))
        if key not in seen:
            seen.add(key)
            unique_clips.append(clip)

    # Save results
    save_clips(unique_clips, posted_ids)
    save_processed_videos(processed_ids)

    logger.info(f"Done! Total clips: {len(unique_clips)}")


if __name__ == "__main__":
    asyncio.run(main())
