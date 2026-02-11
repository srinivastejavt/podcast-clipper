"""
Orchestrator Web - Simplified for static web app

No video cutting, no database, no Telegram.
Just: Transcript → Clips → Posts → JSON output
"""

import asyncio
import time
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, asdict
from loguru import logger

from src.transcriber import transcriber
from src.clip_finder_v5 import clip_finder_v5, ClipCandidate
from src.llm import llm


@dataclass
class WebClip:
    """Clip formatted for web display."""
    video_id: str
    channel_name: str
    video_title: str
    published_at: str
    start_time: float
    end_time: float
    transcript_text: str
    quotable_line: str
    full_post_text: str
    pattern: str
    why_good: str
    speaker: Optional[str]
    youtube_url: str
    created_at: str
    score: float = 0.0
    thumbnail_url: Optional[str] = None
    clip_url: Optional[str] = None  # For video clips when generated

    def to_dict(self) -> dict:
        return asdict(self)


class OrchestratorWeb:
    """Simplified orchestrator for web app - no video files."""

    def __init__(self):
        self.max_retries = 2
        self.retry_delay = 5

    async def process_video(self, video: VideoInfo) -> List[WebClip]:
        """Process video and return web-ready clips."""
        start_time = time.time()
        logger.info(f"[Web] Processing: {video.title[:50]}...")

        try:
            # Step 1: Get transcript
            transcript = await self._get_transcript_with_retry(video.video_id)
            if not transcript:
                logger.error(f"[Web] Transcription failed for {video.video_id}")
                return []

            # Step 2: Find clips
            clips = await self._find_clips_with_retry(transcript, video)
            if not clips:
                logger.info(f"[Web] No clips found in {video.title[:40]}")
                return []

            # Step 3: Write posts in parallel
            logger.info(f"[Web] Writing {len(clips)} posts...")
            post_tasks = [self._write_post(clip, video) for clip in clips]
            post_texts = await asyncio.gather(*post_tasks, return_exceptions=True)

            # Build web clips
            web_clips = []
            for clip, post_text in zip(clips, post_texts):
                if isinstance(post_text, Exception) or not post_text:
                    post_text = self._fallback_post(clip, video)

                youtube_url = f"https://www.youtube.com/watch?v={video.video_id}&t={int(clip.start_time)}s"

                web_clips.append(WebClip(
                    video_id=video.video_id,
                    channel_name=video.channel_name,
                    video_title=video.title,
                    published_at=video.published_at.isoformat() if video.published_at else "",
                    start_time=clip.start_time,
                    end_time=clip.end_time,
                    transcript_text=clip.transcript_text,
                    quotable_line=clip.quotable_line,
                    full_post_text=post_text,
                    pattern=clip.pattern,
                    why_good=clip.why_good,
                    speaker=clip.speaker,
                    youtube_url=youtube_url,
                    created_at=datetime.utcnow().isoformat(),
                    score=getattr(clip, 'score', 0.0),
                    thumbnail_url=getattr(video, 'thumbnail_url', None)
                ))

            # Cleanup
            self._cleanup(video.video_id)

            elapsed = time.time() - start_time
            logger.info(f"[Web] Done! {len(web_clips)} clips in {elapsed:.0f}s")

            return web_clips

        except Exception as e:
            logger.error(f"[Web] Error processing {video.video_id}: {e}")
            self._cleanup(video.video_id)
            return []

    async def _get_transcript_with_retry(self, video_id: str):
        """Get transcript with retry logic."""
        for attempt in range(self.max_retries + 1):
            try:
                transcript = await transcriber.transcribe(video_id)
                if transcript:
                    return transcript
            except Exception as e:
                logger.warning(f"[Web] Transcript attempt {attempt + 1} failed: {e}")

            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)

        return None

    async def _find_clips_with_retry(self, transcript, video) -> List[ClipCandidate]:
        """Find clips with retry logic using V5 multi-pass."""
        for attempt in range(self.max_retries + 1):
            try:
                clips = await clip_finder_v5.find_clips(
                    transcript=transcript,
                    video_title=video.title,
                    channel_name=video.channel_name,
                    video_id=video.video_id
                )
                return clips
            except Exception as e:
                logger.warning(f"[Web] Clip finding attempt {attempt + 1} failed: {e}")

            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)

        return []

    async def _write_post(self, clip: ClipCandidate, video) -> Optional[str]:
        """Write a thoughtful post for a clip using LLM."""
        prompt = f"""Write a post about this podcast clip in a specific style.

PODCAST: {video.channel_name}
QUOTE: "{clip.quotable_line}"
FULL CONTEXT: {clip.transcript_text[:800]}

WRITE IN THIS EXACT STYLE (lowercase, thoughtful, analytical):

"{clip.quotable_line}"

here's what i understood + my take

[restate the quote in your own words] - [initial reaction, 1 sentence]. but let's dig deeper. [expand on what this means, 2-3 sentences about the implications].

i think [your interpretation of what this means for crypto/markets, 2-3 sentences]. [connect it to a broader trend or pattern you've observed].

but what most people miss is [a deeper insight or contrarian angle, 2-3 sentences]. [end with a thought-provoking statement, not a question].

STYLE RULES:
- ALL LOWERCASE (except for proper nouns like Bitcoin, Ethereum)
- conversational and thoughtful, like you're explaining to a friend
- NO questions at the end
- NO clickbait hooks like "unpopular opinion:" or "nobody's talking about this"
- NO emojis
- NO hashtags
- sound like a real person thinking through an idea, not a marketer
- be specific, reference the actual content
- ~400-600 characters total

Return ONLY the post text starting with the quote."""

        try:
            post = await llm.chat(prompt)
            post = post.strip()

            # Clean up LLM prefixes
            prefixes = ["Here's the post:", "Here is the post:", "Post:", "Tweet:"]
            for prefix in prefixes:
                if post.lower().startswith(prefix.lower()):
                    post = post[len(prefix):].strip()

            return post
        except Exception as e:
            logger.warning(f"[Web] Post writing failed: {e}")
            return None

    def _fallback_post(self, clip: ClipCandidate, video) -> str:
        """Fallback post if LLM fails."""
        return f'"{clip.quotable_line}"\n\nfrom {video.channel_name}'

    def _cleanup(self, video_id: str):
        """Clean up temporary files."""
        try:
            transcriber.cleanup_audio(video_id)
        except Exception:
            pass


# Singleton
orchestrator_web = OrchestratorWeb()
