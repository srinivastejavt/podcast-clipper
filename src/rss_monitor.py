"""
YouTube Channel Monitor - Uses yt-dlp for scraping (no API quota!)

Since YouTube disabled RSS feeds, we use yt-dlp to scrape channel pages.
This is free and has no quota limits.
"""

import asyncio
import sys
import json
from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class VideoInfo:
    """Video metadata."""
    video_id: str
    title: str
    channel_name: str
    channel_id: str
    description: str
    published_at: datetime
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    channel_x_handle: Optional[str] = None


class RSSMonitor:
    """Monitor YouTube channels using yt-dlp (no quota limits!)"""

    # Channel handles and X handles
    # Format: channel_name -> (youtube_handle, x_handle)
    CHANNEL_IDS = {
        "Bankless": ("@Bankless", "@BanklessHQ"),
        "The Pomp Podcast": ("@AnthonyPompliano", "@APompliano"),
        "Empire": ("@Blockworks", "@theblockworksne"),
        "Bell Curve": ("@BellCurvePodcast", "@BellCurvePod"),
        "What Bitcoin Did": ("@WhatBitcoinDid", "@WhatBitcoinDid"),
        "Up Only": ("@UpOnly", "@UpOnlyTV"),
        "The Chopping Block": ("@ChoppingBlockPod", "@ChoppingBlock"),
        "Real Vision": ("@RealVisionFinance", "@RealVision"),
        "Unchained": ("@unchaborada", "@Unchained_pod"),
        "The Rollup": ("@therollupco", "@therollup"),
        "Coin Bureau": ("@CoinBureau", "@coinbureau"),
    }

    def __init__(self):
        pass

    async def get_channel_videos(
        self,
        channel_name: str,
        youtube_handle: str,
        x_handle: str = "",
        since_hours: int = 48
    ) -> List[VideoInfo]:
        """Fetch recent videos from a channel using yt-dlp."""
        cutoff = datetime.utcnow() - timedelta(hours=since_hours)

        try:
            # Use yt-dlp to get channel videos (limited to recent)
            channel_url = f"https://www.youtube.com/{youtube_handle}/videos"

            cmd = [
                sys.executable, "-m", "yt_dlp",
                "--flat-playlist",
                "--playlist-end", "10",  # Only last 10 videos
                "-J",  # JSON output
                channel_url
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=60
            )

            if process.returncode != 0:
                logger.warning(f"yt-dlp failed for {channel_name}: {stderr.decode()[:200]}")
                return []

            data = json.loads(stdout.decode())
            entries = data.get("entries", [])

            videos = []
            for entry in entries:
                try:
                    video_id = entry.get("id")
                    title = entry.get("title", "")

                    # Skip shorts and non-podcast content
                    if not video_id or len(title) < 10:
                        continue

                    # Get upload date if available
                    upload_date = entry.get("upload_date")
                    if upload_date:
                        published = datetime.strptime(upload_date, "%Y%m%d")
                    else:
                        published = datetime.utcnow()

                    # Skip old videos
                    if published < cutoff:
                        continue

                    thumbnail = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
                    duration = entry.get("duration")

                    videos.append(VideoInfo(
                        video_id=video_id,
                        title=title,
                        channel_name=channel_name,
                        channel_id=youtube_handle,
                        description=entry.get("description", ""),
                        published_at=published,
                        thumbnail_url=thumbnail,
                        duration_seconds=duration,
                        channel_x_handle=x_handle
                    ))

                except Exception as e:
                    logger.debug(f"Failed to parse entry: {e}")
                    continue

            logger.info(f"[yt-dlp] {channel_name}: {len(videos)} recent videos")
            return videos

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching {channel_name}")
            return []
        except Exception as e:
            logger.warning(f"Failed to fetch {channel_name}: {e}")
            return []

    def is_likely_podcast(self, video: VideoInfo) -> bool:
        """Check if a video is likely a podcast episode."""
        title_lower = video.title.lower()

        # Duration check (podcasts are usually > 20 min)
        if video.duration_seconds and video.duration_seconds < 1200:
            return False

        # Podcast keywords
        podcast_keywords = [
            "podcast", "episode", "ep.", "ep ", "interview",
            "conversation", "talk", "chat", "discussion",
            "ft.", "feat.", "with", "|", "—", "-"
        ]

        # Check if title contains podcast indicators
        has_keyword = any(kw in title_lower for kw in podcast_keywords)

        # Skip obvious non-podcasts
        skip_keywords = ["shorts", "#shorts", "trailer", "teaser", "announcement"]
        is_skip = any(kw in title_lower for kw in skip_keywords)

        return has_keyword and not is_skip

    async def check_all_channels(self, since_hours: int = 48) -> List[VideoInfo]:
        """Check all configured channels for new videos."""
        logger.info(f"[yt-dlp] Checking {len(self.CHANNEL_IDS)} channels...")

        all_videos = []

        # Process channels sequentially to avoid rate limiting
        for channel_name, (youtube_handle, x_handle) in self.CHANNEL_IDS.items():
            videos = await self.get_channel_videos(
                channel_name, youtube_handle, x_handle, since_hours
            )
            all_videos.extend(videos)
            # Small delay between channels
            await asyncio.sleep(1)

        logger.info(f"[yt-dlp] Total: {len(all_videos)} videos from all channels")
        return all_videos


# Singleton
rss_monitor = RSSMonitor()
