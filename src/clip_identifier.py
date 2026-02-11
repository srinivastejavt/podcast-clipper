"""
Clip Identifier Module

Uses Ollama (Llama 3.1) to identify valuable moments in podcast transcripts.
"""

import asyncio
import json
from typing import Optional
from dataclasses import dataclass
from loguru import logger
import ollama

from src.config import config, Config
from src.transcriber import Transcript, TranscriptSegment


@dataclass
class IdentifiedClip:
    """A valuable moment identified in the transcript."""
    start_time: float
    end_time: float
    transcript_text: str
    speaker_name: Optional[str]
    clip_type: str  # insider_info, macro_thesis, market_psychology, etc.
    value_reason: str  # Why this clip is valuable
    score: float  # 0-10 score for ranking
    video_id: str
    channel_name: str
    channel_x_handle: Optional[str] = None
    video_title: str = ""
    published_at: Optional[str] = None  # When the video was published
    video_url: Optional[str] = None  # YouTube URL


class ClipIdentifier:
    """Identifies valuable moments in podcast transcripts using LLM."""

    def __init__(self):
        self.voice_profile = Config.load_voice_profile()
        self.clip_criteria = self.voice_profile["clip_value_criteria"]

    def _build_identification_prompt(self, transcript_chunk: str, video_title: str, channel_name: str) -> str:
        """Build the prompt for identifying valuable clips."""
        criteria_text = "\n".join([
            f"- {c['type']}: {c['description']} (example: {c['example']})"
            for c in self.clip_criteria
        ])

        return f"""You are analyzing a crypto/finance podcast transcript to find the most valuable, quotable moments.

PODCAST: {channel_name} - "{video_title}"

TRANSCRIPT CHUNK (format: [timestamp in seconds] text):
{transcript_chunk}

CRITERIA FOR VALUABLE CLIPS:
{criteria_text}

YOUR TASK:
1. Identify 0-3 valuable moments in this transcript chunk that match the criteria above.
2. Use the EXACT timestamps shown in brackets [XXX.Xs] - these are precise timestamps from the audio.
3. Score each clip from 1-10 based on how valuable/shareable it is.

Focus on moments that are:
- Insightful, not surface-level observations
- Specific and actionable, not vague
- Novel or contrarian (but not controversial)
- Quotable - something people would want to share
- COMPLETE thoughts - must start and end at natural speech boundaries

CRITICAL TIMESTAMP RULES:
- Use the EXACT start timestamp from the first [XXX.Xs] marker of the quote
- Use the EXACT end timestamp from the last segment of the quote
- The transcript_text must match EXACTLY what appears between those timestamps
- Clips should be 15-90 seconds ideally (max 120 seconds)

Respond in JSON format:
{{
    "clips": [
        {{
            "start_time": <float - exact timestamp from transcript>,
            "end_time": <float - exact timestamp from transcript>,
            "transcript_text": "<EXACT verbatim text between those timestamps>",
            "speaker_name": "<name if mentioned, otherwise null>",
            "clip_type": "<type from criteria>",
            "value_reason": "<1-2 sentence explanation of why this is valuable>",
            "score": <1-10>
        }}
    ]
}}

If no valuable clips found in this chunk, return: {{"clips": []}}
"""

    async def identify_clips(
        self,
        transcript: Transcript,
        video_title: str,
        channel_name: str,
        channel_x_handle: Optional[str] = None,
        chunk_size: int = 5000,  # Characters per chunk
        chunk_overlap: int = 500
    ) -> list[IdentifiedClip]:
        """Identify valuable clips in a transcript."""
        all_clips = []

        # Split transcript into overlapping chunks for processing
        chunks = self._split_transcript_into_chunks(
            transcript, chunk_size, chunk_overlap
        )

        logger.info(f"Processing {len(chunks)} transcript chunks for {video_title}")

        for i, (chunk_text, chunk_start_time) in enumerate(chunks):
            logger.debug(f"Processing chunk {i+1}/{len(chunks)}")

            clips = await self._process_chunk(
                chunk_text=chunk_text,
                chunk_start_time=chunk_start_time,
                video_title=video_title,
                channel_name=channel_name,
                video_id=transcript.video_id,
                channel_x_handle=channel_x_handle
            )
            all_clips.extend(clips)

            # Small delay to avoid overwhelming Ollama
            await asyncio.sleep(0.5)

        # Deduplicate overlapping clips
        all_clips = self._deduplicate_clips(all_clips)

        # Sort by score
        all_clips.sort(key=lambda c: c.score, reverse=True)

        logger.info(f"Identified {len(all_clips)} valuable clips in {video_title}")
        return all_clips

    def _split_transcript_into_chunks(
        self,
        transcript: Transcript,
        chunk_size: int,
        overlap: int
    ) -> list[tuple[str, float]]:
        """Split transcript into chunks with timestamps."""
        chunks = []
        current_chunk = ""
        chunk_start_time = 0.0

        for segment in transcript.segments:
            segment_text = f"[{segment.start:.1f}s] {segment.text}\n"

            if len(current_chunk) + len(segment_text) > chunk_size:
                # Save current chunk
                if current_chunk:
                    chunks.append((current_chunk, chunk_start_time))

                # Start new chunk with overlap
                # Find segments that fit in overlap
                overlap_text = ""
                for prev_seg in transcript.segments:
                    if prev_seg.start >= segment.start - 30:  # ~30 seconds overlap
                        break
                    overlap_text = f"[{prev_seg.start:.1f}s] {prev_seg.text}\n"

                current_chunk = overlap_text + segment_text
                chunk_start_time = segment.start
            else:
                if not current_chunk:
                    chunk_start_time = segment.start
                current_chunk += segment_text

        # Don't forget the last chunk
        if current_chunk:
            chunks.append((current_chunk, chunk_start_time))

        return chunks

    async def _process_chunk(
        self,
        chunk_text: str,
        chunk_start_time: float,
        video_title: str,
        channel_name: str,
        video_id: str,
        channel_x_handle: Optional[str]
    ) -> list[IdentifiedClip]:
        """Process a single transcript chunk to identify clips."""
        prompt = self._build_identification_prompt(chunk_text, video_title, channel_name)

        try:
            response = await asyncio.to_thread(
                ollama.chat,
                model=config.OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format="json"
            )

            result_text = response["message"]["content"]
            result = json.loads(result_text)

            clips = []
            for clip_data in result.get("clips", []):
                # Validate clip duration (max 2 minutes)
                duration = clip_data["end_time"] - clip_data["start_time"]
                if duration > config.MAX_CLIP_DURATION_SECONDS:
                    continue

                clips.append(IdentifiedClip(
                    start_time=clip_data["start_time"],
                    end_time=clip_data["end_time"],
                    transcript_text=clip_data["transcript_text"],
                    speaker_name=clip_data.get("speaker_name"),
                    clip_type=clip_data["clip_type"],
                    value_reason=clip_data["value_reason"],
                    score=clip_data["score"],
                    video_id=video_id,
                    channel_name=channel_name,
                    channel_x_handle=channel_x_handle,
                    video_title=video_title
                ))

            return clips

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error processing chunk: {e}")
            return []

    def _deduplicate_clips(self, clips: list[IdentifiedClip]) -> list[IdentifiedClip]:
        """Remove duplicate/overlapping clips, keeping higher scored ones."""
        if not clips:
            return []

        # Sort by score descending
        sorted_clips = sorted(clips, key=lambda c: c.score, reverse=True)

        unique_clips = []
        for clip in sorted_clips:
            # Check if this clip overlaps significantly with any already selected
            is_duplicate = False
            for unique in unique_clips:
                if clip.video_id != unique.video_id:
                    continue

                # Check time overlap
                overlap_start = max(clip.start_time, unique.start_time)
                overlap_end = min(clip.end_time, unique.end_time)

                if overlap_end > overlap_start:
                    overlap_duration = overlap_end - overlap_start
                    clip_duration = clip.end_time - clip.start_time

                    if overlap_duration / clip_duration > 0.5:  # >50% overlap
                        is_duplicate = True
                        break

            if not is_duplicate:
                unique_clips.append(clip)

        return unique_clips


# Singleton instance
clip_identifier = ClipIdentifier()
