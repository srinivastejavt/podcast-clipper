"""
Test Batch: V3 Tier Analysis

Tests the V3 channel tier system across different podcasts.
1. Fetches recent videos from YouTube (last 48 hours)
2. Groups by tier (A/B/C)
3. Shows content distribution
4. Scans cached transcripts for pattern matches
"""

import asyncio
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.youtube_monitor import youtube_monitor, VideoInfo
from src.clip_finder_v3 import clip_finder_v3, CLIP_PATTERNS
from src.transcriber import Transcript, TranscriptSegment
from src.database import database
from src.config import TRANSCRIPTS_DIR, DATA_DIR


async def load_cached_transcript(video_id: str):
    """Load a cached transcript if it exists."""
    transcript_path = TRANSCRIPTS_DIR / f"{video_id}_transcript.json"
    if not transcript_path.exists():
        return None

    with open(transcript_path, "r") as f:
        data = json.load(f)

    segments = [
        TranscriptSegment(start=s["start"], end=s["end"], text=s["text"])
        for s in data["segments"]
    ]

    return Transcript(
        video_id=video_id,
        segments=segments,
        full_text=data["full_text"],
        language=data.get("language", "en")
    )


def quick_pattern_scan(transcript: Transcript) -> dict:
    """
    Quick regex-based pattern scan without LLM.
    Returns estimated pattern matches per pattern type.
    """
    full_text = transcript.full_text.lower()
    pattern_counts = {}

    for pattern_id, pattern in CLIP_PATTERNS.items():
        count = 0
        matched_phrases = []
        for trigger in pattern["trigger_phrases"]:
            # Count occurrences
            matches = len(re.findall(re.escape(trigger.lower()), full_text))
            if matches > 0:
                count += matches
                matched_phrases.append(f"{trigger} ({matches}x)")

        if count > 0:
            pattern_counts[pattern_id] = {
                "name": pattern["name"],
                "count": count,
                "weight": pattern["weight"],
                "weighted_score": count * pattern["weight"],
                "matched_phrases": matched_phrases[:5]  # Top 5
            }

    return pattern_counts


async def main():
    print("=" * 70)
    print("V3 TIER ANALYSIS - TEST BATCH")
    print("=" * 70)
    print()

    # Initialize database
    await database.init()

    # Get channel configuration
    channels = clip_finder_v3.channel_config.get("channels", [])

    # Group channels by tier
    tier_channels = defaultdict(list)
    for ch in channels:
        tier = ch.get("tier", "B")
        tier_channels[tier].append(ch)

    print("CHANNEL CONFIGURATION:")
    print("-" * 40)
    for tier in ["A", "B", "C"]:
        settings = clip_finder_v3.get_tier_settings(tier)
        print(f"\nTier {tier}: {len(tier_channels[tier])} channels")
        print(f"  Max clips/video: {settings['max_clips_per_video']}")
        print(f"  Min score threshold: {settings['min_score_threshold']}")
        print(f"  Priority weight: {settings['priority_weight']}")
        for ch in tier_channels[tier]:
            print(f"  - {ch['name']} (@{ch['youtube_handle']})")

    print()
    print("=" * 70)
    print("FETCHING RECENT VIDEOS (Last 48 hours)")
    print("=" * 70)

    # Check all channels for recent videos
    all_videos = []
    videos_by_tier = {"A": [], "B": [], "C": []}

    for channel in channels:
        try:
            videos = await youtube_monitor.get_recent_videos(
                channel_handle=channel["youtube_handle"],
                channel_name=channel["name"],
                x_handle=channel.get("x_handle"),
                since_hours=48,
                max_results=5
            )

            # Filter for podcasts (not shorts)
            podcasts = [v for v in videos if youtube_monitor.is_likely_podcast(v)]

            if podcasts:
                tier = channel.get("tier", "B")
                print(f"[{tier}] {channel['name']}: {len(podcasts)} podcast(s)")
                for v in podcasts:
                    duration_min = (v.duration_seconds or 0) // 60
                    print(f"    - {v.title[:50]}... ({duration_min} min)")
                    videos_by_tier[tier].append(v)
                    all_videos.append(v)

            # Small delay to avoid rate limiting
            await asyncio.sleep(0.3)

        except Exception as e:
            print(f"Error checking {channel['name']}: {e}")

    print()
    print("=" * 70)
    print("VIDEO DISTRIBUTION BY TIER")
    print("=" * 70)

    for tier in ["A", "B", "C"]:
        count = len(videos_by_tier[tier])
        settings = clip_finder_v3.get_tier_settings(tier)
        max_potential_clips = count * settings["max_clips_per_video"]
        print(f"\nTier {tier}:")
        print(f"  Videos: {count}")
        print(f"  Max potential clips: {max_potential_clips}")
        if videos_by_tier[tier]:
            channels_active = list(set(v.channel_name for v in videos_by_tier[tier]))
            print(f"  Active channels: {', '.join(channels_active)}")

    total = len(all_videos)
    print(f"\nTOTAL: {total} videos in last 48 hours")

    # Check for cached transcripts
    print()
    print("=" * 70)
    print("CACHED TRANSCRIPT ANALYSIS")
    print("=" * 70)

    # Look for all cached transcripts
    transcript_files = list(TRANSCRIPTS_DIR.glob("*_transcript.json"))
    print(f"\nFound {len(transcript_files)} cached transcripts")

    if transcript_files:
        print("\nRunning quick pattern scan on cached transcripts...")
        print("-" * 40)

        transcript_analysis = []

        for tf in transcript_files[:10]:  # Limit to 10 for quick test
            video_id = tf.stem.replace("_transcript", "")
            transcript = await load_cached_transcript(video_id)

            if transcript:
                # Get video info from DB
                video_info = await database.get_video_info(video_id)
                channel_name = video_info["channel_name"] if video_info else "Unknown"
                tier = clip_finder_v3.get_channel_tier(channel_name)

                # Quick pattern scan
                patterns = quick_pattern_scan(transcript)

                total_weighted = sum(p["weighted_score"] for p in patterns.values())

                transcript_analysis.append({
                    "video_id": video_id,
                    "channel_name": channel_name,
                    "tier": tier,
                    "patterns": patterns,
                    "total_weighted_score": total_weighted,
                    "pattern_count": len(patterns)
                })

        # Sort by tier then score
        transcript_analysis.sort(key=lambda x: (x["tier"], -x["total_weighted_score"]))

        # Display results by tier
        for tier in ["A", "B", "C"]:
            tier_results = [t for t in transcript_analysis if t["tier"] == tier]
            if tier_results:
                tier_settings = clip_finder_v3.get_tier_settings(tier)
                print(f"\n[TIER {tier}] - Max {tier_settings['max_clips_per_video']} clips/video, min score {tier_settings['min_score_threshold']}")
                print("-" * 50)

                for result in tier_results:
                    print(f"\n{result['channel_name']} (video: {result['video_id'][:8]}...)")
                    print(f"  Pattern matches: {result['pattern_count']} types")
                    print(f"  Weighted score estimate: {result['total_weighted_score']:.1f}")

                    # Show top patterns
                    if result["patterns"]:
                        sorted_patterns = sorted(
                            result["patterns"].items(),
                            key=lambda x: x[1]["weighted_score"],
                            reverse=True
                        )[:3]
                        print("  Top patterns:")
                        for pid, pdata in sorted_patterns:
                            print(f"    - {pdata['name']}: {pdata['count']} matches (score: {pdata['weighted_score']:.1f})")
                            if pdata["matched_phrases"]:
                                print(f"      Triggers: {', '.join(pdata['matched_phrases'][:3])}")

        # Summary stats
        print()
        print("=" * 70)
        print("ESTIMATED CLIP YIELD BY TIER")
        print("=" * 70)

        for tier in ["A", "B", "C"]:
            tier_results = [t for t in transcript_analysis if t["tier"] == tier]
            tier_settings = clip_finder_v3.get_tier_settings(tier)

            if tier_results:
                avg_score = sum(t["total_weighted_score"] for t in tier_results) / len(tier_results)
                high_potential = sum(1 for t in tier_results if t["total_weighted_score"] >= 10)

                # Estimate clips based on patterns found
                estimated_clips = 0
                for t in tier_results:
                    if t["total_weighted_score"] >= tier_settings["min_score_threshold"] * 10:
                        estimated_clips += min(t["pattern_count"], tier_settings["max_clips_per_video"])

                print(f"\nTier {tier}:")
                print(f"  Transcripts analyzed: {len(tier_results)}")
                print(f"  Avg weighted score: {avg_score:.1f}")
                print(f"  High-potential transcripts: {high_potential}")
                print(f"  Estimated clip yield: ~{estimated_clips} clips")
            else:
                print(f"\nTier {tier}: No cached transcripts to analyze")

    print()
    print("=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)

    tier_a_count = len(videos_by_tier["A"])
    tier_b_count = len(videos_by_tier["B"])
    tier_c_count = len(videos_by_tier["C"])

    print()
    if tier_a_count > 0:
        print(f"1. PRIORITY: Process {tier_a_count} Tier A videos first (up to 3 clips each)")
    if tier_b_count > 0:
        print(f"2. STANDARD: Process {tier_b_count} Tier B videos (up to 2 clips each)")
    if tier_c_count > 0:
        print(f"3. SELECTIVE: Process {tier_c_count} Tier C videos only if score >= 2.0 (max 1 clip)")

    total_potential = (tier_a_count * 3) + (tier_b_count * 2) + (tier_c_count * 1)
    print(f"\nMax potential clips from this batch: {total_potential}")

    print()
    print("Test complete!")


if __name__ == "__main__":
    asyncio.run(main())
