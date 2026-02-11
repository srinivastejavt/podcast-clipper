"""
Clip Finder V5 - Multi-pass for better quality

Pass 1: Find candidate moments (fast, broad)
Pass 2: Score and rank candidates (focused, quality)
Pass 3: Generate optimized quotable lines (polish)
"""

import asyncio
import json
import re
from typing import List, Optional
from dataclasses import dataclass
from loguru import logger

from src.llm import llm
from src.transcriber import Transcript


@dataclass
class ClipCandidate:
    """A clip candidate with scoring."""
    start_time: float
    end_time: float
    transcript_text: str
    quotable_line: str
    pattern: str
    why_good: str
    speaker: Optional[str] = None
    score: float = 0.0
    viral_potential: str = ""


class ClipFinderV5:
    """
    V5 - Multi-pass for better quality.

    Pass 1: Scan full transcript for 5-7 candidate moments
    Pass 2: Score each candidate on virality criteria
    Pass 3: Polish the top 3 quotable lines
    """

    def __init__(self):
        self.max_clips = 5  # Return more clips for user choice

    async def find_clips(
        self,
        transcript: Transcript,
        video_title: str,
        channel_name: str,
        video_id: str = ""
    ) -> List[ClipCandidate]:
        """Find clips using multi-pass approach."""

        logger.info(f"[V5] Finding clips in: {video_title}")
        self._current_transcript = transcript

        # Pass 1: Find candidates
        candidates = await self._find_candidates(transcript, video_title, channel_name)
        if not candidates:
            logger.warning("[V5] No candidates found in pass 1")
            return []

        logger.info(f"[V5] Pass 1: Found {len(candidates)} candidates")

        # Pass 2: Score candidates (parallel)
        scored = await self._score_candidates(candidates, channel_name)
        if not scored:
            logger.warning("[V5] Scoring failed, using raw candidates")
            scored = candidates

        # Sort by score
        scored.sort(key=lambda c: c.score, reverse=True)
        top_clips = scored[:self.max_clips]

        logger.info(f"[V5] Pass 2: Scored and ranked, top {len(top_clips)} selected")

        # Pass 3: Polish quotable lines (parallel)
        polished = await self._polish_quotes(top_clips, channel_name)

        logger.info(f"[V5] Pass 3: Polished {len(polished)} clips")
        return polished

    async def _find_candidates(
        self,
        transcript: Transcript,
        video_title: str,
        channel_name: str
    ) -> List[ClipCandidate]:
        """Pass 1: Find 5-7 candidate moments."""

        # Ollama has no limits - use more transcript for better context
        timestamped_text = self._format_transcript(transcript, max_chars=40000)

        prompt = f"""Find 5-7 potential viral clip moments from this crypto podcast.

PODCAST: {channel_name} - "{video_title}"

TRANSCRIPT:
{timestamped_text}

Look for moments that have:
- Strong opinions or predictions
- Surprising insights or contrarian takes
- Specific numbers or data
- Memorable phrases or quotable lines
- Emotional or passionate delivery
- Humor or sarcasm

Return JSON with 5-7 candidates:
{{
    "candidates": [
        {{
            "start_time": <seconds>,
            "end_time": <seconds>,
            "transcript": "<exact text>",
            "quotable_line": "<most tweetable phrase>",
            "pattern": "<PREDICTION/HOT_TAKE/INSIGHT/DATA/HUMOR>",
            "why_good": "<why this could go viral>",
            "speaker": "<speaker name if known>"
        }}
    ]
}}

Rules:
- Each clip should be 30-90 seconds
- start_time must be >= 30 (skip intro)
- Use ONLY timestamps from the transcript
- Cast a wide net - we'll filter later"""

        try:
            content = await llm.chat(prompt, json_mode=True)
            result = self._parse_json(content)

            candidates = []
            for c in result.get("candidates", []):
                start = float(str(c.get("start_time", 0) or 0).replace("s", ""))
                end = c.get("end_time")

                # If end_time is null or missing, default to start + 45 seconds
                if end is None or end == 0:
                    end = start + 45
                else:
                    end = float(str(end).replace("s", ""))

                if start < 30:
                    continue

                # Ensure reasonable clip duration
                duration = end - start
                if duration < 25:
                    end = start + 45  # Default 45 second clip
                elif duration > 120:
                    end = start + 60  # Cap at 60 seconds

                real_text = self._get_real_transcript(start, end)
                if not real_text:
                    continue

                candidates.append(ClipCandidate(
                    start_time=start,
                    end_time=end,
                    transcript_text=real_text,
                    quotable_line=c.get("quotable_line", ""),
                    pattern=c.get("pattern", ""),
                    why_good=c.get("why_good", ""),
                    speaker=c.get("speaker")
                ))

            return candidates

        except Exception as e:
            logger.error(f"[V5] Pass 1 error: {e}")
            return []

    async def _score_candidates(
        self,
        candidates: List[ClipCandidate],
        channel_name: str
    ) -> List[ClipCandidate]:
        """Pass 2: Score each candidate on virality criteria."""

        if not candidates:
            return []

        # Score all candidates in parallel
        tasks = [self._score_single(c, channel_name) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored = []
        for candidate, result in zip(candidates, results):
            if isinstance(result, Exception):
                candidate.score = 5.0  # Default mid-score
            else:
                candidate.score = result.get("score", 5.0)
                candidate.viral_potential = result.get("analysis", "")
            scored.append(candidate)

        return scored

    async def _score_single(self, candidate: ClipCandidate, channel_name: str) -> dict:
        """Score a single candidate."""
        prompt = f"""Rate this podcast clip for viral potential on Twitter/X.

CHANNEL: {channel_name}
CLIP: "{candidate.transcript_text[:500]}"
QUOTABLE: "{candidate.quotable_line}"

Score 1-10 on each criterion:
1. HOOK: Does it grab attention immediately?
2. OPINION: Does it take a strong stance?
3. SHAREABILITY: Would people quote-tweet this?
4. CLARITY: Is the point clear in 60 seconds?
5. UNIQUENESS: Is this a fresh take?

Return JSON:
{{
    "hook": <1-10>,
    "opinion": <1-10>,
    "shareability": <1-10>,
    "clarity": <1-10>,
    "uniqueness": <1-10>,
    "score": <average>,
    "analysis": "<one sentence on viral potential>"
}}"""

        try:
            content = await llm.chat(prompt, json_mode=True)
            return self._parse_json(content)
        except:
            return {"score": 5.0}

    async def _polish_quotes(
        self,
        clips: List[ClipCandidate],
        channel_name: str
    ) -> List[ClipCandidate]:
        """Pass 3: Polish quotable lines for maximum impact."""

        if not clips:
            return []

        # Polish all in parallel
        tasks = [self._polish_single(c, channel_name) for c in clips]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for clip, result in zip(clips, results):
            if isinstance(result, str) and result:
                clip.quotable_line = result

        return clips

    async def _polish_single(self, clip: ClipCandidate, channel_name: str) -> str:
        """Polish a single quotable line."""
        prompt = f"""Improve this quotable line for Twitter/X.

ORIGINAL: "{clip.quotable_line}"
CONTEXT: {clip.transcript_text[:300]}

Make it:
- Punchy and memorable
- 10-20 words max
- Standalone (makes sense without context)
- Lowercase (except proper nouns)

Return ONLY the improved quote, nothing else."""

        try:
            result = await llm.chat(prompt)
            # Clean up
            result = result.strip().strip('"').strip("'")
            if len(result) < 100:  # Sanity check
                return result
        except:
            pass

        return clip.quotable_line

    def _format_transcript(self, transcript: Transcript, max_chars: int) -> str:
        """Format transcript with timestamps."""
        lines = [f"[{seg.start:.0f}s] {seg.text}" for seg in transcript.segments if seg.start >= 30]

        text = "\n".join(lines)
        if len(text) > max_chars:
            # Sample from beginning, middle, end
            n = len(lines)
            sampled = lines[:int(n*0.4)] + ["..."] + lines[int(n*0.3):int(n*0.7)] + ["..."] + lines[int(n*0.7):]
            text = "\n".join(sampled)[:max_chars]

        return text

    def _get_real_transcript(self, start: float, end: float) -> str:
        """Extract actual transcript text for time range."""
        if not hasattr(self, '_current_transcript'):
            return ""

        segments = [
            seg.text for seg in self._current_transcript.segments
            if seg.start < end and seg.end > start
        ]
        return " ".join(segments).strip()

    def _parse_json(self, content: str) -> dict:
        """Parse JSON from LLM response."""
        content = content.strip()
        try:
            return json.loads(content)
        except:
            pass

        # Find JSON object
        start = content.find("{")
        if start == -1:
            return {}

        brace_count = 0
        end = -1
        for i, c in enumerate(content[start:], start):
            if c == "{":
                brace_count += 1
            elif c == "}":
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break

        if end > start:
            try:
                return json.loads(content[start:end])
            except:
                pass

        return {}


# Singleton
clip_finder_v5 = ClipFinderV5()
