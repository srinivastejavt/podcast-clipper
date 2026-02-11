#!/usr/bin/env python3
"""
Generate MP4 clips for all clips in clips.json.

This ensures download links work by creating MP4s with matching filenames.
Run locally (not in GitHub Actions) since it requires video downloads.
"""

import asyncio
import json
import sys
from pathlib import Path
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.clip_generator import clip_generator

DOCS_DIR = Path(__file__).parent.parent / "docs"
CLIPS_JSON = DOCS_DIR / "clips.json"
CLIPS_OUTPUT_DIR = DOCS_DIR / "clips"


async def generate_clip_for_entry(clip: dict) -> bool:
    """Generate MP4 for a single clip entry."""
    video_id = clip.get("video_id")
    start_time = clip.get("start_time", 0)
    end_time = clip.get("end_time", start_time + 45)

    if not video_id:
        return False

    # Generate filename matching what app.js expects
    filename = f"{video_id}_{int(start_time)}_{int(end_time)}"
    output_path = CLIPS_OUTPUT_DIR / f"{filename}.mp4"

    # Skip if already exists
    if output_path.exists():
        logger.info(f"Already exists: {filename}.mp4")
        return True

    # Generate the clip
    result = await clip_generator.generate_clip(
        video_id=video_id,
        start_time=start_time,
        end_time=end_time,
        output_name=filename
    )

    if result:
        # Move from data/video_clips to docs/clips
        source = Path(result)
        if source.exists() and source != output_path:
            CLIPS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            source.rename(output_path)
            logger.info(f"Moved to docs/clips: {filename}.mp4")
        return True

    return False


async def main():
    """Generate MP4s for all clips in clips.json."""
    logger.info("=== Generating MP4s for clips.json ===")

    if not CLIPS_JSON.exists():
        logger.error(f"clips.json not found at {CLIPS_JSON}")
        return

    with open(CLIPS_JSON) as f:
        data = json.load(f)

    clips = data.get("clips", [])
    logger.info(f"Found {len(clips)} clips in clips.json")

    # Create output directory
    CLIPS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Group clips by video_id to avoid re-downloading same video
    by_video = {}
    for clip in clips:
        vid = clip.get("video_id")
        if vid:
            if vid not in by_video:
                by_video[vid] = []
            by_video[vid].append(clip)

    logger.info(f"Clips from {len(by_video)} unique videos")

    success = 0
    failed = 0
    skipped = 0

    for video_id, video_clips in by_video.items():
        logger.info(f"\n--- Processing {video_id} ({len(video_clips)} clips) ---")

        for clip in video_clips:
            start = clip.get("start_time", 0)
            end = clip.get("end_time", start + 45)
            filename = f"{video_id}_{int(start)}_{int(end)}.mp4"

            # Check if already exists
            if (CLIPS_OUTPUT_DIR / filename).exists():
                logger.info(f"Skipping (exists): {filename}")
                skipped += 1
                continue

            try:
                result = await generate_clip_for_entry(clip)
                if result:
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Failed {filename}: {e}")
                failed += 1

            # Small delay between clips
            await asyncio.sleep(1)

        # Delay between videos to avoid rate limits
        await asyncio.sleep(2)

    logger.info(f"\n=== Done ===")
    logger.info(f"Success: {success}, Failed: {failed}, Skipped: {skipped}")
    logger.info(f"Total MP4s in docs/clips: {len(list(CLIPS_OUTPUT_DIR.glob('*.mp4')))}")


if __name__ == "__main__":
    asyncio.run(main())
