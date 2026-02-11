"""
Orchestrator V4 - FAST & PRODUCTION-READY

Process a video in ~1-2 minutes:
1. Get transcript (YouTube captions = instant, Whisper fallback = 1-2 min)
2. Find clips - ONE LLM call (30 sec)
3. Write posts - PARALLEL LLM calls (30 sec total)
4. Cut video clips (30 sec)

Features:
- YouTube captions first (instant)
- Retry logic for failures
- Parallel processing where possible
- Proper cleanup on errors
"""

import asyncio
import time
from datetime import datetime
from typing import List, Optional, Tuple
from loguru import logger

from src.database import database
from src.transcriber import transcriber
from src.clip_finder_v4 import clip_finder_v4, SimpleClip
from src.video_cutter import video_cutter
from src.youtube_monitor import VideoInfo
from src.config import config
import ollama


class OrchestratorV4:
    """Fast, production-ready video processing."""

    def __init__(self):
        self.max_retries = 2
        self.retry_delay = 5  # seconds

    async def process_video(self, video: VideoInfo) -> List[dict]:
        """Process a video with retry logic and proper error handling."""
        start_time = time.time()

        logger.info(f"[V4] 🎬 Processing: {video.title[:50]}...")

        # Skip if already done
        if await database.video_exists(video.video_id):
            logger.info(f"[V4] ⏭️  Already processed: {video.video_id}")
            return []

        try:
            # Add to database first
            await database.add_video(
                video_id=video.video_id,
                channel_name=video.channel_name,
                title=video.title,
                published_at=video.published_at,
                description=video.description or ""
            )

            # Step 1: Get transcript (YouTube captions or Whisper)
            transcript = await self._get_transcript_with_retry(video.video_id)
            if not transcript:
                logger.error(f"[V4] ❌ Transcription failed for {video.video_id}")
                return []

            await database.mark_video_transcribed(video.video_id)

            # Step 2: Find clips
            clips = await self._find_clips_with_retry(transcript, video)
            if not clips:
                logger.info(f"[V4] ⚠️  No clips found in {video.title[:40]}")
                self._cleanup(video.video_id)
                return []

            await database.mark_video_clips_identified(video.video_id)

            # Step 3 & 4: Write posts (parallel) and download video (parallel)
            processed = await self._process_clips(clips, video)

            # Cleanup
            self._cleanup(video.video_id)

            elapsed = time.time() - start_time
            logger.info(f"[V4] ✅ Done! {len(processed)} clips in {elapsed:.0f}s from {video.title[:40]}")

            return processed

        except Exception as e:
            logger.error(f"[V4] ❌ Error processing {video.video_id}: {e}")
            self._cleanup(video.video_id)
            return []

    async def _get_transcript_with_retry(self, video_id: str):
        """Get transcript with retry logic."""
        for attempt in range(self.max_retries + 1):
            try:
                logger.info(f"[V4] 📝 Step 1/4: Getting transcript...")
                transcript = await transcriber.transcribe(video_id)
                if transcript:
                    return transcript
            except Exception as e:
                logger.warning(f"[V4] Transcript attempt {attempt + 1} failed: {e}")

            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)

        return None

    async def _find_clips_with_retry(self, transcript, video: VideoInfo) -> List[SimpleClip]:
        """Find clips with retry logic."""
        for attempt in range(self.max_retries + 1):
            try:
                logger.info(f"[V4] 🎯 Step 2/4: Finding clips...")
                clips = await clip_finder_v4.find_clips(
                    transcript=transcript,
                    video_title=video.title,
                    channel_name=video.channel_name,
                    video_id=video.video_id
                )
                return clips
            except Exception as e:
                logger.warning(f"[V4] Clip finding attempt {attempt + 1} failed: {e}")

            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)

        return []

    async def _process_clips(self, clips: List[SimpleClip], video: VideoInfo) -> List[dict]:
        """Process clips: write posts and cut video in parallel."""
        logger.info(f"[V4] ✍️  Step 3/4: Writing {len(clips)} posts...")

        # Start post writing and video download in parallel
        post_tasks = [self._write_post(clip, video) for clip in clips]
        download_task = video_cutter.download_video(video.video_id)

        # Wait for both
        results = await asyncio.gather(
            asyncio.gather(*post_tasks),
            download_task,
            return_exceptions=True
        )

        post_texts = results[0] if not isinstance(results[0], Exception) else [None] * len(clips)
        video_path = results[1] if not isinstance(results[1], Exception) else None

        if not video_path:
            logger.error(f"[V4] ❌ Video download failed")
            # Still save clips without video paths
            video_path = None

        # Step 4: Cut clips
        logger.info(f"[V4] ✂️  Step 4/4: Cutting {len(clips)} clips...")

        processed = []
        from src.clip_identifier import IdentifiedClip

        for clip, post_text in zip(clips, post_texts):
            if not post_text:
                post_text = f'"{clip.quotable_line}"\n\n🎥 {video.channel_name}'

            clip_path = None
            if video_path:
                try:
                    identified = IdentifiedClip(
                        start_time=clip.start_time,
                        end_time=clip.end_time,
                        transcript_text=clip.transcript_text,
                        speaker_name=clip.speaker,
                        clip_type="quote",
                        value_reason=clip.why_good,
                        score=1.0,
                        video_id=video.video_id,
                        channel_name=video.channel_name,
                        video_title=video.title
                    )
                    clip_path = await video_cutter.create_clip_for_identified(identified, video_path)
                except Exception as e:
                    logger.warning(f"[V4] Clip cutting failed: {e}")

            # Save to DB
            try:
                clip_id = await database.save_clip(
                    video_id=video.video_id,
                    start_time=clip.start_time,
                    end_time=clip.end_time,
                    transcript_text=clip.transcript_text,
                    speaker_name=clip.speaker,
                    speaker_x_handle=None,
                    clip_type="quote",
                    score=1.0,
                    clip_path=str(clip_path) if clip_path else None,
                    opinion_text=clip.why_good,
                    full_post_text=post_text
                )

                processed.append({
                    'id': clip_id,
                    'video_id': video.video_id,
                    'channel_name': video.channel_name,
                    'video_title': video.title,
                    'start_time': clip.start_time,
                    'end_time': clip.end_time,
                    'transcript_text': clip.transcript_text,
                    'quotable_line': clip.quotable_line,
                    'full_post_text': post_text,
                    'clip_path': str(clip_path) if clip_path else None
                })
            except Exception as e:
                logger.error(f"[V4] Failed to save clip: {e}")

        return processed

    async def _write_post(self, clip: SimpleClip, video: VideoInfo) -> Optional[str]:
        """Write a thoughtful, analytical post for a clip."""
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
            response = await asyncio.to_thread(
                ollama.chat,
                model=config.OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}]
            )
            post = response["message"]["content"].strip()

            # Clean up any meta text the LLM might add
            if post.startswith('"') and post.endswith('"'):
                post = post[1:-1]

            # Remove common LLM prefixes
            prefixes_to_remove = ["Here's the post:", "Here is the post:", "Post:", "Tweet:"]
            for prefix in prefixes_to_remove:
                if post.lower().startswith(prefix.lower()):
                    post = post[len(prefix):].strip()

            return post
        except Exception as e:
            logger.warning(f"[V4] Post writing failed: {e}")
            # Better fallback
            return (
                f"🎙️ Heard something interesting on {video.channel_name}:\n\n"
                f'"{clip.quotable_line}"\n\n'
                f"What do you think? 👇"
            )

    def _cleanup(self, video_id: str):
        """Clean up temporary files."""
        try:
            transcriber.cleanup_audio(video_id)
            video_cutter.cleanup_temp_videos(video_id)
        except Exception as e:
            logger.debug(f"[V4] Cleanup warning: {e}")


# Singleton
orchestrator_v4 = OrchestratorV4()
