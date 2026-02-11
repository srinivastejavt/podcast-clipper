"""
YouTube Channel Monitor

Monitors configured YouTube channels for new videos and retrieves video metadata.
Uses caching and quota tracking to minimize API usage.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger
from pydantic import BaseModel

from src.config import config, Config
from src.database import database


class VideoInfo(BaseModel):
    """Video information model."""
    video_id: str
    title: str
    description: str
    channel_name: str
    channel_id: str
    published_at: datetime
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None
    channel_x_handle: Optional[str] = None


class YouTubeMonitor:
    """Monitors YouTube channels for new podcast episodes."""

    def __init__(self):
        self.youtube = build("youtube", "v3", developerKey=config.YOUTUBE_API_KEY)
        self.channels = Config.load_channels()
        self._channel_id_cache: dict[str, str] = {}

    async def get_channel_id(self, channel_handle: str, channel_name: str = "") -> Optional[str]:
        """Get channel ID from handle/username. Uses DB cache first."""
        # Check memory cache
        if channel_handle in self._channel_id_cache:
            return self._channel_id_cache[channel_handle]

        # Check database cache
        cached_id = await database.get_cached_channel_id(channel_handle)
        if cached_id:
            self._channel_id_cache[channel_handle] = cached_id
            logger.debug(f"Using cached channel ID for {channel_handle}")
            return cached_id

        try:
            # Try searching by handle (e.g., @Bankless)
            handle = channel_handle.lstrip("@")

            # First try the forHandle parameter (1 unit)
            request = self.youtube.channels().list(
                part="id",
                forHandle=handle
            )
            response = await asyncio.to_thread(request.execute)
            await database.log_api_usage("youtube", "channels.list", 1)

            if response.get("items"):
                channel_id = response["items"][0]["id"]
                self._channel_id_cache[channel_handle] = channel_id
                # Cache in database
                await database.cache_channel_id(channel_handle, channel_id, channel_name)
                return channel_id

            # Fallback to search (100 units!)
            request = self.youtube.search().list(
                part="snippet",
                q=handle,
                type="channel",
                maxResults=1
            )
            response = await asyncio.to_thread(request.execute)
            await database.log_api_usage("youtube", "search.list", 100)

            if response.get("items"):
                channel_id = response["items"][0]["snippet"]["channelId"]
                self._channel_id_cache[channel_handle] = channel_id
                # Cache in database
                await database.cache_channel_id(channel_handle, channel_id, channel_name)
                return channel_id

            logger.warning(f"Could not find channel ID for {channel_handle}")
            return None

        except HttpError as e:
            logger.error(f"YouTube API error getting channel ID for {channel_handle}: {e}")
            return None

    async def get_recent_videos(
        self,
        channel_handle: str,
        channel_name: str,
        x_handle: Optional[str] = None,
        since_hours: int = 48,
        max_results: int = 10
    ) -> list[VideoInfo]:
        """Get recent videos from a channel."""
        channel_id = await self.get_channel_id(channel_handle, channel_name)
        if not channel_id:
            return []

        try:
            # Calculate the date threshold
            published_after = (datetime.utcnow() - timedelta(hours=since_hours)).isoformat() + "Z"

            # Search for videos (100 units per call!)
            request = self.youtube.search().list(
                part="snippet",
                channelId=channel_id,
                type="video",
                order="date",
                publishedAfter=published_after,
                maxResults=max_results
            )
            response = await asyncio.to_thread(request.execute)
            await database.log_api_usage("youtube", "search.list", 100)

            videos = []
            video_ids = []

            for item in response.get("items", []):
                video_ids.append(item["id"]["videoId"])
                videos.append({
                    "video_id": item["id"]["videoId"],
                    "title": item["snippet"]["title"],
                    "description": item["snippet"]["description"],
                    "channel_name": channel_name,
                    "channel_id": channel_id,
                    "published_at": datetime.fromisoformat(
                        item["snippet"]["publishedAt"].replace("Z", "+00:00")
                    ),
                    "thumbnail_url": item["snippet"]["thumbnails"].get("high", {}).get("url"),
                    "channel_x_handle": x_handle
                })

            # Get video durations
            if video_ids:
                duration_map = await self._get_video_durations(video_ids)
                for video in videos:
                    video["duration_seconds"] = duration_map.get(video["video_id"])

            return [VideoInfo(**v) for v in videos]

        except HttpError as e:
            logger.error(f"YouTube API error getting videos for {channel_name}: {e}")
            return []

    async def _get_video_durations(self, video_ids: list[str]) -> dict[str, int]:
        """Get durations for multiple videos."""
        try:
            request = self.youtube.videos().list(
                part="contentDetails",
                id=",".join(video_ids)
            )
            response = await asyncio.to_thread(request.execute)
            await database.log_api_usage("youtube", "videos.list", 1)

            duration_map = {}
            for item in response.get("items", []):
                duration_str = item["contentDetails"]["duration"]
                duration_seconds = self._parse_duration(duration_str)
                duration_map[item["id"]] = duration_seconds

            return duration_map

        except HttpError as e:
            logger.error(f"YouTube API error getting durations: {e}")
            return {}

    def _parse_duration(self, duration_str: str) -> int:
        """Parse ISO 8601 duration string to seconds."""
        import re
        pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
        match = re.match(pattern, duration_str)
        if not match:
            return 0

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)

        return hours * 3600 + minutes * 60 + seconds

    async def check_all_channels(self, since_hours: int = 48) -> list[VideoInfo]:
        """Check all configured channels for new videos."""
        all_videos = []

        # Check quota before starting
        usage_today = await database.get_api_usage_today("youtube")
        logger.info(f"YouTube API usage today: {usage_today} units (limit: 10,000)")

        if usage_today >= 9000:
            logger.warning("Approaching YouTube quota limit! Skipping channel checks.")
            return []

        for channel in self.channels:
            # Check quota mid-run
            usage_today = await database.get_api_usage_today("youtube")
            if usage_today >= 9500:
                logger.warning(f"YouTube quota nearly exhausted ({usage_today}/10000). Stopping.")
                break

            logger.info(f"Checking channel: {channel['name']}")
            videos = await self.get_recent_videos(
                channel_handle=channel["youtube_handle"],
                channel_name=channel["name"],
                x_handle=channel.get("x_handle"),
                since_hours=since_hours
            )
            all_videos.extend(videos)
            logger.info(f"Found {len(videos)} new videos from {channel['name']}")

            # Log fetch history
            await database.log_fetch(channel['name'], len(videos))

            # Small delay to avoid rate limiting
            await asyncio.sleep(0.5)

        # Sort by published date (newest first)
        all_videos.sort(key=lambda v: v.published_at, reverse=True)

        return all_videos

    def is_likely_podcast(self, video: VideoInfo) -> bool:
        """Check if a video is likely a podcast episode (not a short clip)."""
        # Filter out shorts and very short videos
        if video.duration_seconds and video.duration_seconds < 600:  # Less than 10 min
            return False

        # Filter out obvious non-podcast content by title
        skip_keywords = ["shorts", "#shorts", "trailer", "teaser", "promo", "announcement"]
        title_lower = video.title.lower()
        if any(kw in title_lower for kw in skip_keywords):
            return False

        return True


# Singleton instance
youtube_monitor = YouTubeMonitor()
