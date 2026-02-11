"""
RSS Monitor - No API quota limits!

YouTube channels have RSS feeds at:
https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID

Free, unlimited, no API key needed.
"""

import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass
from loguru import logger

from src.config import config


@dataclass
class VideoInfo:
    """Video metadata from RSS."""
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
    """Monitor YouTube channels via RSS feeds - no quota limits!"""

    # Channel IDs (we need these, not handles)
    # Format: channel_name -> (channel_id, x_handle)
    CHANNEL_IDS = {
        "Bankless": ("UCAl9Ld79qaZxp9JzEOwd3aA", "@BanklessHQ"),
        "The Pomp Podcast": ("UCevXpeL8cNyAnww-NqJ4m2w", "@APompliano"),
        "Empire": ("UCL0J4MLEdLP0-UyLu0hCktg", "@theblockworksne"),
        "Bell Curve": ("UCNGk0aCr4xr8_qIlluOSA_w", "@BellCurvePod"),
        "What Bitcoin Did": ("UCE-V0b0VdL8WpMQhw2wf_Bw", "@WhatBitcoinDid"),
        "Up Only": ("UC1B03sc6xMvOblOBbBxoKzg", "@UpOnlyTV"),
        "The Chopping Block": ("UCL-0J3xHN8uZinKNr9ynElQ", "@ChoppingBlock"),
        "Real Vision Crypto": ("UC-pV5WshKug_JzV9tCIk7Rg", "@RealVision"),
        "Unchained": ("UCWiiMnsnw5Isc2PP1to9nNw", "@Unchained_pod"),
        "The Rollup": ("UC8Hh8kQ5X3gkxMxKu1g7_Bg", "@therollup"),
        "The Defiant Podcast": ("UChb3rwdvsKZLp_p8P9OKa6Q", "@DefiantNews"),
        "Solana Podcast": ("UCjsgQKPpR7ubPQhPqjf8kyA", "@SolanaPodcast"),
        "Coin Bureau Podcast": ("UCqK_GSMbpiV8spgD3ZGloSw", "@coinbureau"),
        "TFTC": ("UCtdbWsnfA08KhSUO4amVLaQ", "@TFTC21"),
        "Stephan Livera": ("UCDqPIrJSzHyyJpmH6wnxVxA", "@stephanlivera"),
    }

    def __init__(self):
        self.rss_base = "https://www.youtube.com/feeds/videos.xml?channel_id="

    async def get_channel_videos(
        self,
        channel_name: str,
        channel_id: str,
        x_handle: str = "",
        since_hours: int = 48
    ) -> List[VideoInfo]:
        """Fetch recent videos from a channel's RSS feed."""
        url = f"{self.rss_base}{channel_id}"
        cutoff = datetime.utcnow() - timedelta(hours=since_hours)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status != 200:
                        logger.warning(f"RSS fetch failed for {channel_name}: {response.status}")
                        return []

                    xml_content = await response.text()

            # Parse XML
            root = ET.fromstring(xml_content)
            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'yt': 'http://www.youtube.com/xml/schemas/2015',
                'media': 'http://search.yahoo.com/mrss/'
            }

            videos = []
            for entry in root.findall('atom:entry', ns):
                try:
                    video_id = entry.find('yt:videoId', ns).text
                    title = entry.find('atom:title', ns).text
                    published_str = entry.find('atom:published', ns).text

                    # Parse datetime
                    published = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
                    published_naive = published.replace(tzinfo=None)

                    # Skip old videos
                    if published_naive < cutoff:
                        continue

                    # Get description from media:group
                    description = ""
                    media_group = entry.find('media:group', ns)
                    if media_group is not None:
                        desc_elem = media_group.find('media:description', ns)
                        if desc_elem is not None and desc_elem.text:
                            description = desc_elem.text

                    # Get thumbnail
                    thumbnail = None
                    if media_group is not None:
                        thumb_elem = media_group.find('media:thumbnail', ns)
                        if thumb_elem is not None:
                            thumbnail = thumb_elem.get('url')

                    videos.append(VideoInfo(
                        video_id=video_id,
                        title=title,
                        channel_name=channel_name,
                        channel_id=channel_id,
                        description=description,
                        published_at=published,
                        thumbnail_url=thumbnail,
                        channel_x_handle=x_handle
                    ))

                except Exception as e:
                    logger.debug(f"Error parsing entry: {e}")
                    continue

            logger.info(f"[RSS] {channel_name}: {len(videos)} videos in last {since_hours}h")
            return videos

        except asyncio.TimeoutError:
            logger.warning(f"RSS timeout for {channel_name}")
            return []
        except Exception as e:
            logger.error(f"RSS error for {channel_name}: {e}")
            return []

    async def check_all_channels(self, since_hours: int = 48) -> List[VideoInfo]:
        """Check all configured channels via RSS."""
        logger.info(f"[RSS] Checking {len(self.CHANNEL_IDS)} channels...")

        # Create tasks for parallel fetching
        tasks = []
        for channel_name, (channel_id, x_handle) in self.CHANNEL_IDS.items():
            task = self.get_channel_videos(channel_name, channel_id, x_handle, since_hours)
            tasks.append(task)

        # Run all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all videos
        all_videos = []
        for result in results:
            if isinstance(result, list):
                all_videos.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Channel check failed: {result}")

        logger.info(f"[RSS] Total: {len(all_videos)} videos from all channels")
        return all_videos

    def is_likely_podcast(self, video: VideoInfo) -> bool:
        """Check if video is likely a podcast (not a short)."""
        title_lower = video.title.lower()

        # Skip obvious non-podcasts
        skip_keywords = ["shorts", "#shorts", "trailer", "teaser", "promo", "announcement", "clip"]
        if any(kw in title_lower for kw in skip_keywords):
            return False

        # We don't have duration from RSS, so we'll filter later during transcription
        return True


# Singleton
rss_monitor = RSSMonitor()
