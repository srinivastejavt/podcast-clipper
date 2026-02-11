#!/usr/bin/env python3
"""
Stress Test - Test the full pipeline with timing
"""

import asyncio
import time
from datetime import datetime
from loguru import logger

# Setup path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import database
from src.youtube_monitor import youtube_monitor, VideoInfo
from src.orchestrator_v4 import orchestrator_v4
from src.transcriber import transcriber


async def test_full_pipeline():
    """Test the complete pipeline with a real video."""

    print("\n" + "="*60)
    print("🧪 STRESS TEST - Full Pipeline")
    print("="*60 + "\n")

    # Initialize
    await database.init()

    # Test 1: Find a recent video
    print("📺 Step 1: Finding recent videos...")
    start = time.time()

    videos = await youtube_monitor.check_all_channels(since_hours=72)
    print(f"   Found {len(videos)} videos in {time.time()-start:.1f}s")

    if not videos:
        print("❌ No videos found! Check your channels config.")
        return

    # Filter for podcasts (>10 min)
    podcasts = [v for v in videos if v.duration_seconds and v.duration_seconds > 600]
    print(f"   {len(podcasts)} are podcasts (>10 min)")

    if not podcasts:
        print("❌ No podcasts found!")
        return

    # Pick first unprocessed one
    video = None
    for v in podcasts:
        if not await database.video_exists(v.video_id):
            video = v
            break

    if not video:
        # Use first one even if processed (for testing)
        video = podcasts[0]
        print(f"⚠️  All videos processed, testing with: {video.title[:50]}")
        # Delete from DB to re-test
        import aiosqlite
        async with aiosqlite.connect(database.db_path) as db:
            await db.execute("DELETE FROM videos WHERE video_id = ?", (video.video_id,))
            await db.execute("DELETE FROM clips WHERE video_id = ?", (video.video_id,))
            await db.commit()

    print(f"\n📼 Testing with: {video.title[:60]}...")
    print(f"   Channel: {video.channel_name}")
    print(f"   Duration: {video.duration_seconds//60} min")
    print(f"   Video ID: {video.video_id}")

    # Test 2: Full processing
    print("\n⏱️  Step 2: Processing video (timing each stage)...")

    total_start = time.time()

    # Track individual stages
    stages = {}

    # Stage 1: Transcribe
    print("\n   📝 Transcribing...")
    stage_start = time.time()
    transcript = await transcriber.transcribe(video.video_id)
    stages['transcribe'] = time.time() - stage_start
    print(f"      Done in {stages['transcribe']:.1f}s")

    if not transcript:
        print("❌ Transcription failed!")
        return

    print(f"      Segments: {len(transcript.segments)}")
    print(f"      Total chars: {len(transcript.full_text)}")

    # Stage 2: Find clips
    print("\n   🎯 Finding clips...")
    stage_start = time.time()
    from src.clip_finder_v4 import clip_finder_v4
    clips = await clip_finder_v4.find_clips(
        transcript=transcript,
        video_title=video.title,
        channel_name=video.channel_name,
        video_id=video.video_id
    )
    stages['find_clips'] = time.time() - stage_start
    print(f"      Done in {stages['find_clips']:.1f}s")
    print(f"      Found: {len(clips)} clips")

    if clips:
        for i, clip in enumerate(clips, 1):
            print(f"\n      Clip {i}:")
            print(f"         Time: {clip.start_time:.0f}s - {clip.end_time:.0f}s ({clip.end_time-clip.start_time:.0f}s)")
            print(f"         Pattern: {clip.pattern}")
            print(f"         Quote: \"{clip.quotable_line[:60]}...\"")

    # Stage 3: Write posts (parallel)
    print("\n   ✍️  Writing posts (parallel)...")
    stage_start = time.time()
    from src.orchestrator_v4 import orchestrator_v4
    post_tasks = [orchestrator_v4._write_post(clip, video) for clip in clips]
    posts = await asyncio.gather(*post_tasks)
    stages['write_posts'] = time.time() - stage_start
    print(f"      Done in {stages['write_posts']:.1f}s")
    print(f"      Posts: {len([p for p in posts if p])}")

    # Stage 4: Cut clips
    print("\n   ✂️  Cutting video clips...")
    stage_start = time.time()
    from src.video_cutter import video_cutter
    video_path = await video_cutter.download_video(video.video_id)
    stages['download'] = time.time() - stage_start
    print(f"      Download: {stages['download']:.1f}s")

    if video_path:
        stage_start = time.time()
        for clip in clips:
            output_name = f"{video.video_id}_{int(clip.start_time)}_{int(clip.end_time)}"
            await video_cutter.cut_clip(
                video_path=video_path,
                start_time=clip.start_time,
                end_time=clip.end_time,
                output_name=output_name
            )
        stages['cut_clips'] = time.time() - stage_start
        print(f"      Cutting: {stages['cut_clips']:.1f}s")

    total_time = time.time() - total_start

    # Summary
    print("\n" + "="*60)
    print("📊 TIMING RESULTS")
    print("="*60)
    print(f"\n   {'Stage':<20} {'Time':>10}")
    print(f"   {'-'*30}")
    for stage, t in stages.items():
        print(f"   {stage:<20} {t:>8.1f}s")
    print(f"   {'-'*30}")
    print(f"   {'TOTAL':<20} {total_time:>8.1f}s")

    # Target check
    print(f"\n   Target: < 120s (2 min)")
    if total_time < 120:
        print(f"   ✅ PASSED! ({total_time:.1f}s)")
    else:
        print(f"   ❌ FAILED ({total_time:.1f}s > 120s)")
        print(f"\n   Bottleneck: {max(stages, key=stages.get)} ({stages[max(stages, key=stages.get)]:.1f}s)")

    # Cleanup
    print("\n🧹 Cleaning up...")
    transcriber.cleanup_audio(video.video_id)
    video_cutter.cleanup_temp_videos(video.video_id)

    print("\n✅ Stress test complete!\n")


if __name__ == "__main__":
    asyncio.run(test_full_pipeline())
