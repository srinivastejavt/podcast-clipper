"""
Audio Transcription Module

Uses YouTube captions first (instant), falls back to Whisper if unavailable.
MLX Whisper optimized for Apple Silicon.
"""

import asyncio
import subprocess
import tempfile
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from loguru import logger

from src.config import TRANSCRIPTS_DIR


@dataclass
class TranscriptSegment:
    """A segment of transcribed audio."""
    start: float  # Start time in seconds
    end: float    # End time in seconds
    text: str     # Transcribed text


@dataclass
class Transcript:
    """Full transcript with segments."""
    video_id: str
    segments: list[TranscriptSegment]
    full_text: str
    language: str = "en"

    def get_text_at_time(self, start: float, end: float) -> str:
        """Get transcript text between two timestamps."""
        relevant_segments = [
            seg for seg in self.segments
            if seg.start >= start and seg.end <= end
        ]
        return " ".join(seg.text for seg in relevant_segments)

    def save(self, path: Optional[Path] = None) -> Path:
        """Save transcript to file."""
        if path is None:
            path = TRANSCRIPTS_DIR / f"{self.video_id}.txt"

        with open(path, "w") as f:
            for seg in self.segments:
                f.write(f"[{seg.start:.2f} - {seg.end:.2f}] {seg.text}\n")

        return path


class Transcriber:
    """Transcribes audio using Whisper."""

    def __init__(self, model_size: str = "base"):
        """
        Initialize transcriber.

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large)
                       For M4 Air, 'base' or 'small' recommended for speed/quality balance
        """
        self.model_size = model_size
        self._model = None

    async def download_audio(self, video_id: str) -> Optional[Path]:
        """Download audio from YouTube video using yt-dlp."""
        output_path = TRANSCRIPTS_DIR / f"{video_id}.mp3"

        if output_path.exists():
            logger.info(f"Audio already downloaded: {output_path}")
            return output_path

        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            cmd = [
                "yt-dlp",
                "-x",  # Extract audio
                "--audio-format", "mp3",
                "--audio-quality", "0",  # Best quality
                "-o", str(output_path),
                "--no-playlist",
                url
            ]

            logger.info(f"Downloading audio for {video_id}...")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"yt-dlp error: {stderr.decode()}")
                return None

            logger.info(f"Audio downloaded: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error downloading audio: {e}")
            return None

    async def transcribe(self, video_id: str, audio_path: Optional[Path] = None) -> Optional[Transcript]:
        """
        Transcribe video - tries YouTube captions first (instant), falls back to Whisper.
        """
        # Check if transcript already exists
        transcript_path = TRANSCRIPTS_DIR / f"{video_id}_transcript.json"
        if transcript_path.exists():
            logger.info(f"Using cached transcript for {video_id}")
            return await self._load_transcript(video_id, transcript_path)

        # Try YouTube captions first (instant, no audio download needed)
        logger.info(f"Trying YouTube captions for {video_id}...")
        transcript = await self._get_youtube_captions(video_id)
        if transcript:
            await self._save_transcript(transcript, transcript_path)
            logger.info(f"Got YouTube captions for {video_id} (instant)")
            return transcript

        # Fallback to Whisper
        logger.info(f"No YouTube captions, using Whisper for {video_id}...")

        # Download audio if not provided
        if audio_path is None:
            audio_path = await self.download_audio(video_id)
            if audio_path is None:
                return None

        try:
            logger.info(f"Transcribing {video_id} with Whisper ({self.model_size})...")
            result = await self._run_whisper(audio_path)

            if result is None:
                return None

            segments = [
                TranscriptSegment(
                    start=seg["start"],
                    end=seg["end"],
                    text=seg["text"].strip()
                )
                for seg in result["segments"]
            ]

            transcript = Transcript(
                video_id=video_id,
                segments=segments,
                full_text=result["text"],
                language=result.get("language", "en")
            )

            await self._save_transcript(transcript, transcript_path)
            logger.info(f"Transcription complete for {video_id}")
            return transcript

        except Exception as e:
            logger.error(f"Error transcribing {video_id}: {e}")
            return None

    async def _get_youtube_captions(self, video_id: str) -> Optional[Transcript]:
        """Get captions directly from YouTube (instant, no audio needed)."""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            cmd = [
                "yt-dlp",
                "--write-auto-sub",
                "--sub-lang", "en",
                "--skip-download",
                "--sub-format", "json3",
                "-o", str(TRANSCRIPTS_DIR / f"{video_id}_caption"),
                url
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            # Look for the caption file
            caption_file = TRANSCRIPTS_DIR / f"{video_id}_caption.en.json3"
            if not caption_file.exists():
                # Try auto-generated
                for f in TRANSCRIPTS_DIR.glob(f"{video_id}_caption*.json3"):
                    caption_file = f
                    break

            if not caption_file.exists():
                return None

            # Parse json3 format
            with open(caption_file, 'r') as f:
                data = json.load(f)

            segments = []
            full_text_parts = []

            for event in data.get('events', []):
                if 'segs' not in event:
                    continue

                start_ms = event.get('tStartMs', 0)
                duration_ms = event.get('dDurationMs', 0)

                text_parts = []
                for seg in event['segs']:
                    if 'utf8' in seg:
                        text_parts.append(seg['utf8'])

                text = ''.join(text_parts).strip()
                if text and text != '\n':
                    segments.append(TranscriptSegment(
                        start=start_ms / 1000,
                        end=(start_ms + duration_ms) / 1000,
                        text=text
                    ))
                    full_text_parts.append(text)

            # Cleanup caption file
            caption_file.unlink()

            if not segments:
                return None

            return Transcript(
                video_id=video_id,
                segments=segments,
                full_text=' '.join(full_text_parts),
                language="en"
            )

        except Exception as e:
            logger.debug(f"YouTube captions not available: {e}")
            return None

    async def _run_whisper(self, audio_path: Path) -> Optional[dict]:
        """Run Whisper transcription."""
        try:
            # Try mlx-whisper first (optimized for Apple Silicon)
            import mlx_whisper

            # Map model size to MLX community repo
            model_repos = {
                "tiny": "mlx-community/whisper-tiny-mlx",
                "base": "mlx-community/whisper-base-mlx",
                "small": "mlx-community/whisper-small-mlx",
                "medium": "mlx-community/whisper-medium-mlx",
                "large-v3": "mlx-community/whisper-large-v3-mlx",
                "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
            }
            repo = model_repos.get(self.model_size, f"mlx-community/whisper-{self.model_size}-mlx")

            logger.info(f"Using MLX Whisper model: {repo}")
            result = await asyncio.to_thread(
                mlx_whisper.transcribe,
                str(audio_path),
                path_or_hf_repo=repo
            )
            return result
        except ImportError:
            logger.info("mlx-whisper not available, falling back to standard whisper")

        try:
            # Fallback to standard whisper
            import whisper
            if self._model is None:
                self._model = await asyncio.to_thread(whisper.load_model, self.model_size)

            result = await asyncio.to_thread(
                self._model.transcribe,
                str(audio_path),
                verbose=False
            )
            return result
        except ImportError:
            logger.error("Neither mlx-whisper nor whisper is installed")
            return None

    async def _save_transcript(self, transcript: Transcript, path: Path):
        """Save transcript to JSON file."""
        import json

        data = {
            "video_id": transcript.video_id,
            "full_text": transcript.full_text,
            "language": transcript.language,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in transcript.segments
            ]
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    async def _load_transcript(self, video_id: str, path: Path) -> Transcript:
        """Load transcript from JSON file."""
        import json

        with open(path, "r") as f:
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

    def cleanup_audio(self, video_id: str):
        """Remove downloaded audio file to save space."""
        audio_path = TRANSCRIPTS_DIR / f"{video_id}.mp3"
        if audio_path.exists():
            audio_path.unlink()
            logger.info(f"Cleaned up audio file: {audio_path}")


# Singleton instance
# Using "small" for fast transcription (~1 min vs 3-4 min for large)
# Quality is good enough for clip finding. Options: tiny, base, small, medium, large-v3, large-v3-turbo
transcriber = Transcriber(model_size="small")
