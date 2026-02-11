#!/usr/bin/env python3
"""
Process cached transcripts - fast clip generation from existing transcripts.
"""

import asyncio
import json
import sys
import os
from datetime import datetime
from pathlib import Path
from loguru import logger

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.clip_finder_v5 import clip_finder_v5, ClipCandidate
from src.transcriber import Transcript, TranscriptSegment
from src.orchestrator_web import WebClip
from src.llm import llm

TRANSCRIPTS_DIR = Path(__file__).parent.parent / "data" / "transcripts"
DOCS_DIR = Path(__file__).parent.parent / "docs"
CLIPS_FILE = DOCS_DIR / "clips.json"


def load_transcript(video_id: str):
    """Load a cached transcript."""
    path = TRANSCRIPTS_DIR / f"{video_id}_transcript.json"
    if not path.exists():
        return None

    with open(path) as f:
        data = json.load(f)

    segments = [
        TranscriptSegment(start=s["start"], end=s["end"], text=s["text"])
        for s in data.get("segments", [])
    ]

    return Transcript(
        video_id=video_id,
        segments=segments,
        full_text=data.get("full_text", ""),
        language=data.get("language", "en")
    )


def get_video_ids() -> list:
    """Get list of video IDs with cached transcripts."""
    ids = []
    for f in TRANSCRIPTS_DIR.glob("*_transcript.json"):
        video_id = f.stem.replace("_transcript", "")
        ids.append(video_id)
    return ids


async def write_post(clip: ClipCandidate, channel_name: str) -> str:
    """Generate a Twitter post for a clip."""
    prompt = f"""Write a Twitter/X post (max 250 chars) for this crypto podcast clip.

QUOTE: "{clip.quotable_line}"
CONTEXT: {clip.transcript_text[:500]}
PATTERN: {clip.pattern}
CHANNEL: {channel_name}

Write a short, engaging post that:
- Starts with the quotable line in lowercase
- Adds 1-2 lines of your take
- Uses crypto Twitter style (no emojis)
- Is under 250 characters total

Just return the post text, nothing else."""

    try:
        return await llm.chat(prompt)
    except:
        return f'"{clip.quotable_line.lower()}"\n\n{clip.why_good}'


async def process_video(video_id: str, channel_name: str = "Unknown") -> list:
    """Process a single video from cached transcript."""
    transcript = load_transcript(video_id)
    if not transcript:
        logger.warning(f"No transcript for {video_id}")
        return []

    logger.info(f"Processing {video_id} ({len(transcript.segments)} segments)...")

    # Find clips
    clips = await clip_finder_v5.find_clips(
        transcript=transcript,
        video_title=f"Video {video_id}",
        channel_name=channel_name,
        video_id=video_id
    )

    if not clips:
        logger.info(f"No clips found in {video_id}")
        return []

    logger.info(f"Found {len(clips)} clips in {video_id}")

    # Generate posts
    results = []
    for clip in clips:
        post = await write_post(clip, channel_name)

        youtube_url = f"https://www.youtube.com/watch?v={video_id}&t={int(clip.start_time)}s"
        embed_url = f"https://www.youtube.com/embed/{video_id}?start={int(clip.start_time)}&end={int(clip.end_time)}"

        results.append({
            "video_id": video_id,
            "channel_name": channel_name,
            "video_title": f"Video {video_id}",
            "published_at": datetime.utcnow().isoformat(),
            "start_time": clip.start_time,
            "end_time": clip.end_time,
            "transcript_text": clip.transcript_text,
            "quotable_line": clip.quotable_line,
            "full_post_text": post,
            "pattern": clip.pattern,
            "why_good": clip.why_good,
            "speaker": clip.speaker or "",
            "youtube_url": youtube_url,
            "embed_url": embed_url,
            "created_at": datetime.utcnow().isoformat(),
            "score": clip.score,
            "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
        })

    return results


async def main():
    """Process all cached transcripts."""
    logger.info("=== Processing Cached Transcripts ===")

    video_ids = get_video_ids()
    logger.info(f"Found {len(video_ids)} cached transcripts")

    # Load existing clips
    existing_clips = []
    if CLIPS_FILE.exists():
        with open(CLIPS_FILE) as f:
            existing_clips = json.load(f).get("clips", [])

    # Get already processed video IDs
    processed = set(c.get("video_id") for c in existing_clips)

    # Process new videos only
    new_ids = [vid for vid in video_ids if vid not in processed]
    logger.info(f"New to process: {len(new_ids)}")

    all_clips = existing_clips.copy()

    for video_id in new_ids[:10]:  # Limit to 10 at a time
        try:
            clips = await process_video(video_id)
            all_clips.extend(clips)
            # Small delay to avoid rate limits
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Failed {video_id}: {e}")

    # Save
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CLIPS_FILE, "w") as f:
        json.dump({
            "clips": all_clips,
            "metadata": {
                "total_clips": len(all_clips),
                "generated_at": datetime.utcnow().isoformat()
            }
        }, f, indent=2)

    logger.info(f"Done! Total clips: {len(all_clips)}")


if __name__ == "__main__":
    asyncio.run(main())
