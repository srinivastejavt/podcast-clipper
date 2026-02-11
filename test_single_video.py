#!/usr/bin/env python3
"""
Test Single Video

Process a single YouTube video URL through the pipeline (for testing).
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from src.orchestrator import orchestrator
from src.telegram_bot import telegram_bot
from src.video_cutter import video_cutter


async def test_video(video_url: str, send_telegram: bool = False):
    """Test the pipeline with a single video."""
    logger.info(f"Testing with video: {video_url}")

    await orchestrator.init()

    ranked_posts = await orchestrator.run_single_video(video_url)

    if not ranked_posts:
        logger.warning("No clips generated from this video")
        return

    logger.info(f"\n✅ Generated {len(ranked_posts)} candidates:\n")

    for rp in ranked_posts:
        post = rp.post
        clip = post.clip

        print("=" * 60)
        print(f"RANK #{rp.rank} (score: {rp.final_score:.2f})")
        print(f"Type: {clip.clip_type}")
        print(f"Speaker: {clip.speaker_name or 'Unknown'}")
        print(f"Time: {clip.start_time:.0f}s - {clip.end_time:.0f}s")
        print("-" * 60)
        print("TRANSCRIPT:")
        print(f'"{clip.transcript_text}"')
        print("-" * 60)
        print("YOUR POST:")
        print(post.full_post_text)
        print("=" * 60)
        print()

        # Check if clip was created
        clip_path = video_cutter.get_clip_path(clip)
        if clip_path:
            print(f"📹 Video clip saved: {clip_path}")
        print()

    if send_telegram:
        # Build clip paths
        paths_dict = {}
        for rp in ranked_posts:
            clip = rp.post.clip
            clip_key = f"{clip.video_id}_{clip.start_time}"
            path = video_cutter.get_clip_path(clip)
            if path:
                paths_dict[clip_key] = path

        await telegram_bot.send_daily_candidates(ranked_posts, paths_dict)
        logger.info("Sent to Telegram!")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_single_video.py <youtube_url> [--telegram]")
        print("Example: python test_single_video.py https://www.youtube.com/watch?v=xxxxx")
        sys.exit(1)

    video_url = sys.argv[1]
    send_telegram = "--telegram" in sys.argv

    asyncio.run(test_video(video_url, send_telegram))
