"""
Clip Generator - Creates actual video clips (30-60s MP4s)

Downloads video, extracts clip, uploads to cloud storage.
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional
from loguru import logger
import aiohttp
import os

CLIPS_DIR = Path(__file__).parent.parent / "data" / "video_clips"


class ClipGenerator:
    """Generate video clips from YouTube videos."""

    def __init__(self):
        CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    async def generate_clip(
        self,
        video_id: str,
        start_time: float,
        end_time: float,
        output_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate a video clip.

        Returns: Path to clip file or None if failed
        """
        if output_name is None:
            output_name = f"{video_id}_{int(start_time)}_{int(end_time)}"

        output_path = CLIPS_DIR / f"{output_name}.mp4"

        # Skip if already exists
        if output_path.exists():
            logger.info(f"Clip already exists: {output_path}")
            return str(output_path)

        url = f"https://www.youtube.com/watch?v={video_id}"
        duration = end_time - start_time

        try:
            # Use yt-dlp + ffmpeg to download just the clip segment
            # This is more efficient than downloading the whole video
            cmd = [
                "yt-dlp",
                "--quiet",
                "--no-warnings",
                "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
                "--download-sections", f"*{start_time}-{end_time}",
                "--force-keyframes-at-cuts",
                "-o", str(output_path),
                "--merge-output-format", "mp4",
                url
            ]

            logger.info(f"Generating clip: {video_id} [{start_time}s - {end_time}s]")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=300  # 5 min timeout
            )

            if process.returncode != 0:
                logger.error(f"yt-dlp error: {stderr.decode()}")
                return None

            if output_path.exists():
                logger.info(f"Clip generated: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
                return str(output_path)
            else:
                logger.error("Clip file not created")
                return None

        except asyncio.TimeoutError:
            logger.error(f"Clip generation timed out for {video_id}")
            return None
        except Exception as e:
            logger.error(f"Clip generation error: {e}")
            return None

    async def upload_to_cloudflare_r2(
        self,
        file_path: str,
        bucket_name: str = "podcast-clips"
    ) -> Optional[str]:
        """
        Upload clip to Cloudflare R2 (S3-compatible, free tier: 10GB).

        Requires env vars: R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY
        Returns: Public URL or None
        """
        # This is a placeholder - implement when you set up R2
        # For now, clips are stored locally/in the repo
        pass

    def cleanup_old_clips(self, max_age_days: int = 7):
        """Remove clips older than max_age_days."""
        import time
        cutoff = time.time() - (max_age_days * 24 * 60 * 60)

        for clip_file in CLIPS_DIR.glob("*.mp4"):
            if clip_file.stat().st_mtime < cutoff:
                clip_file.unlink()
                logger.info(f"Deleted old clip: {clip_file}")


# Singleton
clip_generator = ClipGenerator()
