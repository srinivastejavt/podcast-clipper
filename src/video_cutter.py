"""
Video Cutter Module

Downloads and cuts video clips from YouTube using yt-dlp and ffmpeg.
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional
from loguru import logger

from src.config import CLIPS_DIR, DATA_DIR
from src.clip_identifier import IdentifiedClip


class VideoCutter:
    """Downloads and cuts video clips from YouTube."""

    def __init__(self):
        self.clips_dir = CLIPS_DIR
        self.temp_dir = DATA_DIR / "temp_videos"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def download_video(self, video_id: str) -> Optional[Path]:
        """Download video from YouTube (720p for speed, good enough for clips)."""
        output_path = self.temp_dir / f"{video_id}.mp4"

        if output_path.exists():
            logger.info(f"Video already downloaded: {output_path}")
            return output_path

        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            # Use 720p for faster download (clips don't need 1080p)
            cmd = [
                "yt-dlp",
                "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
                "--merge-output-format", "mp4",
                "-o", str(output_path),
                "--no-playlist",
                "--concurrent-fragments", "4",  # Parallel download
                url
            ]

            logger.info(f"Downloading video {video_id} (720p)...")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"yt-dlp error: {stderr.decode()}")
                return None

            logger.info(f"Video downloaded: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error downloading video: {e}")
            return None

    async def cut_clip(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        output_name: str,
        padding_before: float = 0.5,
        padding_after: float = 0.5
    ) -> Optional[Path]:
        """Cut a clip from the video using ffmpeg."""
        output_path = self.clips_dir / f"{output_name}.mp4"

        if output_path.exists():
            logger.info(f"Clip already exists: {output_path}")
            return output_path

        try:
            # Add padding but don't go negative
            actual_start = max(0, start_time - padding_before)
            duration = (end_time + padding_after) - actual_start

            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-ss", str(actual_start),  # Start time
                "-i", str(video_path),  # Input file
                "-t", str(duration),  # Duration
                "-c:v", "libx264",  # Video codec
                "-c:a", "aac",  # Audio codec
                "-preset", "fast",  # Encoding speed
                "-crf", "23",  # Quality (lower = better, 23 is default)
                "-movflags", "+faststart",  # Web optimization
                str(output_path)
            ]

            logger.info(f"Cutting clip: {start_time:.1f}s - {end_time:.1f}s")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"ffmpeg error: {stderr.decode()}")
                return None

            logger.info(f"Clip saved: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error cutting clip: {e}")
            return None

    async def create_clip_for_identified(
        self,
        clip: IdentifiedClip,
        video_path: Optional[Path] = None
    ) -> Optional[Path]:
        """Create a video clip for an identified moment."""
        # Download video if not provided
        if video_path is None:
            video_path = await self.download_video(clip.video_id)
            if video_path is None:
                return None

        # Generate unique output name
        output_name = f"{clip.video_id}_{int(clip.start_time)}_{int(clip.end_time)}"

        return await self.cut_clip(
            video_path=video_path,
            start_time=clip.start_time,
            end_time=clip.end_time,
            output_name=output_name
        )

    async def create_clips_batch(
        self,
        clips: list[IdentifiedClip]
    ) -> dict[str, Optional[Path]]:
        """Create clips for multiple identified moments."""
        results = {}

        # Group clips by video_id to avoid re-downloading
        clips_by_video = {}
        for clip in clips:
            if clip.video_id not in clips_by_video:
                clips_by_video[clip.video_id] = []
            clips_by_video[clip.video_id].append(clip)

        for video_id, video_clips in clips_by_video.items():
            logger.info(f"Processing {len(video_clips)} clips from video {video_id}")

            # Download video once
            video_path = await self.download_video(video_id)
            if video_path is None:
                for clip in video_clips:
                    results[f"{clip.video_id}_{clip.start_time}"] = None
                continue

            # Cut all clips from this video
            for clip in video_clips:
                clip_path = await self.create_clip_for_identified(clip, video_path)
                results[f"{clip.video_id}_{clip.start_time}"] = clip_path

        return results

    def cleanup_temp_videos(self, video_id: Optional[str] = None):
        """Clean up temporary video files."""
        if video_id:
            video_path = self.temp_dir / f"{video_id}.mp4"
            if video_path.exists():
                video_path.unlink()
                logger.info(f"Cleaned up temp video: {video_path}")
        else:
            # Clean all temp videos
            for video_file in self.temp_dir.glob("*.mp4"):
                video_file.unlink()
                logger.info(f"Cleaned up temp video: {video_file}")

    def get_clip_path(self, clip: IdentifiedClip) -> Optional[Path]:
        """Get the path to an existing clip file."""
        output_name = f"{clip.video_id}_{int(clip.start_time)}_{int(clip.end_time)}.mp4"
        clip_path = self.clips_dir / output_name
        return clip_path if clip_path.exists() else None


# Singleton instance
video_cutter = VideoCutter()
