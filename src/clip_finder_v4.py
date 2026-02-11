"""
Clip Finder V4 - SIMPLE & FAST

One LLM call per video. No complex scoring. Just find quotable moments.
~3-5 min per video instead of 20+.
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
class SimpleClip:
    """A simple clip - just the essentials."""
    start_time: float
    end_time: float
    transcript_text: str
    quotable_line: str
    why_good: str
    pattern: str = ""
    speaker: Optional[str] = None


class ClipFinderV4:
    """
    V4 - Simple and fast.

    One LLM call to find the 3 best moments in the entire transcript.
    No chunking, no multi-stage scoring, no complex patterns.
    """

    def __init__(self):
        self.max_clips = 3

    async def find_clips(
        self,
        transcript: Transcript,
        video_title: str,
        channel_name: str,
        video_id: str = ""
    ) -> List[SimpleClip]:
        """Find the best clips in ONE LLM call."""

        logger.info(f"[V4] Finding clips in: {video_title}")

        # Store transcript for later extraction of real text
        self._current_transcript = transcript

        # Get transcript with timestamps (limit to ~15k chars for speed)
        timestamped_text = self._format_transcript(transcript, max_chars=15000)

        prompt = f"""Find the 3 BEST viral clip moments from this crypto podcast.

PODCAST: {channel_name} - "{video_title}"

TRANSCRIPT (with timestamps):
{timestamped_text}

WINNING PATTERNS (look for these):
1. CONTRAST: "Never been worse time for X... never been better for Y"
2. BOLD PREDICTION: "My thesis is..." "I think we'll see..."
3. HOT TAKE: "X is dead" "X is over" "Forget about X"
4. CONTRADICTION: "You can't have it both ways..."
5. REDEFINE: "X isn't about Y... it's actually about Z"
6. SPECIFIC NUMBERS: Concrete data that makes it real
7. SARCASM: "How dare this guy be successful..."

HARD REQUIREMENTS:
- Starts CLEAN (NOT with "But", "So", "And", "What we", "I mean")
- Takes a STANCE (opinion, not just description)
- Is QUOTABLE (something you'd screenshot and tweet)
- 30-90 seconds long (longer clips = more context)
- Complete thought (doesn't trail off)

MUST AVOID - These are NOT good clips:
- Sponsor reads or ads
- Subscribe/like reminders

⚠️ CRITICAL TIMESTAMP RULES:
- ONLY use timestamps that appear in the transcript above (look for [XXXs])
- Your start_time MUST be >= 30 (skip intro music)
- If you pick a timestamp that doesn't exist in the transcript, your clip will be REJECTED

Return JSON:
{{
    "clips": [
        {{
            "start_time": <seconds>,
            "end_time": <seconds>,
            "transcript": "<exact text of the clip>",
            "quotable_line": "<the single most tweetable line, 10-20 words>",
            "pattern": "<which pattern from above>",
            "why_good": "<why this would go viral, 10 words max>",
            "speaker": "<speaker name if known>"
        }}
    ]
}}

IMPORTANT: You MUST return at least 2 clips. Every podcast has quotable moments - find them.
Return 2-3 clips. Quality over quantity but always return something."""

        # Try up to 2 times
        for attempt in range(2):
            try:
                content = await llm.chat(prompt, json_mode=True)

                # Robust JSON extraction and fixing
                result = self._parse_json_response(content)
                if result is None:
                    raise json.JSONDecodeError("Failed to parse", content, 0)
                clips = []

                for c in result.get("clips", []):
                    # Basic validation
                    start = c.get("start_time", 0)
                    end = c.get("end_time", 0)

                    if isinstance(start, str):
                        start = float(start.replace("s", ""))
                    if isinstance(end, str):
                        end = float(end.replace("s", ""))

                    # Skip only the very first 30 seconds (usually just intro music)
                    if start < 30:
                        logger.debug(f"[V4] Skipping clip at {start}s - intro music")
                        continue

                    duration = end - start
                    if duration < 25 or duration > 120:  # Min 25 sec, max 2 min
                        continue

                    # Extract REAL transcript text from actual segments (don't trust LLM)
                    real_transcript = self._get_real_transcript(start, end)
                    if not real_transcript:
                        logger.warning(f"[V4] No transcript found for {start}s-{end}s, skipping")
                        continue

                    clips.append(SimpleClip(
                        start_time=start,
                        end_time=end,
                        transcript_text=real_transcript,  # Use REAL text, not LLM hallucination
                        quotable_line=c.get("quotable_line", ""),
                        why_good=c.get("why_good", ""),
                        pattern=c.get("pattern", ""),
                        speaker=c.get("speaker")
                    ))

                if clips:
                    logger.info(f"[V4] Found {len(clips)} clips")
                    return clips[:self.max_clips]

                # If no clips found, retry with simpler prompt
                if attempt == 0:
                    logger.warning("[V4] No clips found, retrying with simpler prompt...")
                    prompt = self._get_simple_prompt(timestamped_text, video_title, channel_name)
                    continue

            except json.JSONDecodeError as e:
                logger.warning(f"[V4] JSON parse error (attempt {attempt+1}): {e}")
                if attempt == 0:
                    prompt = self._get_simple_prompt(timestamped_text, video_title, channel_name)
                    continue
            except Exception as e:
                logger.error(f"[V4] Error: {e}")
                break

        logger.warning("[V4] Failed to find clips after retries")
        return []

    def _get_simple_prompt(self, transcript: str, title: str, channel: str) -> str:
        """Simpler fallback prompt."""
        return f"""Find 2 interesting quotes from this podcast.

PODCAST: {channel} - "{title}"

TRANSCRIPT:
{transcript[:10000]}

Return JSON with this exact format:
{{"clips": [
    {{"start_time": 100, "end_time": 130, "transcript": "the quote text", "quotable_line": "short catchy version", "pattern": "BOLD PREDICTION", "why_good": "interesting take", "speaker": "Guest"}},
    {{"start_time": 500, "end_time": 540, "transcript": "another quote", "quotable_line": "short version", "pattern": "HOT TAKE", "why_good": "controversial", "speaker": "Host"}}
]}}

Return exactly 2 clips. Pick any interesting moments."""

    def _parse_json_response(self, content: str) -> Optional[dict]:
        """Robustly parse JSON from LLM response, handling common issues."""
        content = content.strip()

        # Try direct parse first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Find the JSON object boundaries
        start_idx = content.find("{")
        if start_idx == -1:
            return None

        # Find matching closing brace
        brace_count = 0
        end_idx = -1
        for i, char in enumerate(content[start_idx:], start_idx):
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break

        if end_idx == -1:
            # No matching brace, try to fix by adding closing braces
            content = content[start_idx:] + "}]}"
        else:
            content = content[start_idx:end_idx]

        # Try parsing again
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Fix common issues: trailing commas, unescaped quotes in strings
        fixed = content
        # Remove trailing commas before ] or }
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
        # Fix unescaped newlines in strings (replace with space)
        fixed = re.sub(r'(?<!\\)\n', ' ', fixed)

        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Last resort: try to extract clips array using regex
        try:
            # Look for individual clip objects
            clip_pattern = r'\{\s*"start_time"\s*:\s*(\d+(?:\.\d+)?)\s*,\s*"end_time"\s*:\s*(\d+(?:\.\d+)?)\s*,\s*"transcript"\s*:\s*"([^"]*)"'
            matches = re.findall(clip_pattern, content)
            if matches:
                clips = []
                for start, end, transcript in matches:
                    clips.append({
                        "start_time": float(start),
                        "end_time": float(end),
                        "transcript": transcript,
                        "quotable_line": transcript[:100] if len(transcript) > 100 else transcript,
                        "pattern": "EXTRACTED",
                        "why_good": "Extracted from malformed response",
                        "speaker": None
                    })
                if clips:
                    logger.info(f"[V4] Extracted {len(clips)} clips using regex fallback")
                    return {"clips": clips}
        except Exception as e:
            logger.warning(f"[V4] Regex extraction failed: {e}")

        return None

    def _get_real_transcript(self, start_time: float, end_time: float) -> str:
        """Extract the REAL transcript text from segments for given time range."""
        if not hasattr(self, '_current_transcript') or not self._current_transcript:
            return ""

        # Get all segments that overlap with this time range
        relevant_segments = []
        for seg in self._current_transcript.segments:
            # Segment overlaps if it starts before end and ends after start
            if seg.start < end_time and seg.end > start_time:
                relevant_segments.append(seg.text)

        if not relevant_segments:
            # Try with a bit of buffer
            for seg in self._current_transcript.segments:
                if seg.start >= start_time - 5 and seg.end <= end_time + 5:
                    relevant_segments.append(seg.text)

        return " ".join(relevant_segments).strip()

    def _format_transcript(self, transcript: Transcript, max_chars: int = 25000) -> str:
        """Format transcript with timestamps."""
        # Skip only first 30 seconds (intro music)
        all_lines = [f"[{seg.start:.0f}s] {seg.text}" for seg in transcript.segments if seg.start >= 30]

        if not all_lines:
            # Fallback if video is short - use everything after 60s
            all_lines = [f"[{seg.start:.0f}s] {seg.text}" for seg in transcript.segments if seg.start >= 60]

        if not all_lines:
            return ""

        # If short enough, return all
        full_text = "\n".join(all_lines)
        if len(full_text) <= max_chars:
            return full_text

        # Sample from beginning (40%), middle (30%), end (30%)
        n = len(all_lines)
        begin_end = int(n * 0.4)
        mid_start = int(n * 0.35)
        mid_end = int(n * 0.65)
        end_start = int(n * 0.7)

        sampled = (
            all_lines[:begin_end] +
            ["\n... [MIDDLE OF PODCAST] ..."] +
            all_lines[mid_start:mid_end] +
            ["\n... [END OF PODCAST] ..."] +
            all_lines[end_start:]
        )

        result = "\n".join(sampled)

        # Truncate if still too long
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... [TRUNCATED]"

        return result


# Singleton
clip_finder_v4 = ClipFinderV4()
