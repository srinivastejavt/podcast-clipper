"""
Clip Finder V3 - Pattern-Based Selection

Finds clips that match proven viral patterns from Bankless, clipsofcrypto, etc.
Uses 10 winning patterns + hard rejection filters.

This replaces the generic "find valuable moments" approach with
specific pattern matching that works on crypto Twitter.

Channel Tiers:
- Tier A: Clip goldmines (Bankless, Pomp, etc) - prioritize, up to 3 clips
- Tier B: Good content, occasional gems - normal processing, up to 2 clips
- Tier C: Technical/educational - skip unless exceptional score, max 1 clip
"""

import asyncio
import json
import re
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger
import ollama

from src.config import config, Config, DATA_DIR
from src.transcriber import Transcript, TranscriptSegment


# Load channel config with tiers
def _load_channel_config() -> Dict[str, Any]:
    """Load channel configuration with tier info."""
    config_path = Path(__file__).parent.parent / "config" / "channels.json"
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load channel config: {e}")
        return {"channels": [], "tier_config": {}}


CHANNEL_CONFIG = _load_channel_config()


# ============================================================================
# WINNING PATTERNS - Based on analysis of viral Bankless/clipsofcrypto posts
# ============================================================================

CLIP_PATTERNS = {
    "contrast": {
        "name": "Contrast/Paradox",
        "description": "Two opposing ideas that create tension",
        "examples": [
            "There's never been a worse time to be X... and never been a better time to be Y",
            "X isn't about Y... it's actually about Z",
            "Everyone thinks X but the reality is Y"
        ],
        "trigger_phrases": [
            "never been worse", "never been better",
            "isn't about", "it's actually",
            "on one hand", "on the other",
            "the opposite is true",
            "but here's the thing"
        ],
        "weight": 1.3  # High viral potential
    },
    "bold_prediction": {
        "name": "Bold Prediction",
        "description": "Clear prediction with conviction",
        "examples": [
            "My thesis is we'll see Bitcoin over $1 million",
            "I think X will happen within Y timeframe",
            "This is going to be the biggest Z we've ever seen"
        ],
        "trigger_phrases": [
            "my thesis is", "i think we'll see",
            "i predict", "i expect",
            "going to happen", "will be worth",
            "by 2025", "by 2026", "by end of year",
            "this cycle", "next cycle"
        ],
        "weight": 1.4  # Very high - people love predictions
    },
    "contradiction_callout": {
        "name": "Contradiction Callout",
        "description": "Pointing out logical inconsistency",
        "examples": [
            "You can't really have it both ways",
            "The problem with that logic is...",
            "That doesn't make sense because..."
        ],
        "trigger_phrases": [
            "can't have it both ways",
            "doesn't make sense",
            "the problem with",
            "contradiction",
            "but wait",
            "that's not how it works"
        ],
        "weight": 1.2
    },
    "consequence_chain": {
        "name": "If-Then Consequence",
        "description": "Logical chain showing surprising outcomes",
        "examples": [
            "If we see a real shock... the fallout doesn't stop at portfolios",
            "When X happens, it leads to Y, which causes Z"
        ],
        "trigger_phrases": [
            "if we see", "if this happens",
            "when this", "the fallout",
            "leads to", "which means",
            "the second order effect",
            "what people don't realize"
        ],
        "weight": 1.2
    },
    "hot_take": {
        "name": "Hot Take/Death Declaration",
        "description": "Declaring something dead, over, or the past",
        "examples": [
            "Tribal wars are just like the thing of the past",
            "X is dead", "X is over",
            "We're done with X"
        ],
        "trigger_phrases": [
            "is dead", "is over", "is done",
            "thing of the past",
            "nobody cares about",
            "doesn't matter anymore",
            "forget about"
        ],
        "weight": 1.3
    },
    "meme_analogy": {
        "name": "Meme/Cultural Reference",
        "description": "Using meme or pop culture to explain concept",
        "examples": [
            "There's that meme of like Japanese man still fighting world war 2",
            "It's like that scene in X where...",
            "You know how people say..."
        ],
        "trigger_phrases": [
            "that meme", "like the meme",
            "reminds me of", "it's like when",
            "you know how", "remember when",
            "there's this joke"
        ],
        "weight": 1.25  # Very shareable
    },
    "sarcastic_mock": {
        "name": "Sarcastic Devil's Advocate",
        "description": "Mocking a bad take through exaggeration",
        "examples": [
            "How dare this guy be successful... What a disgusting human being",
            "Oh no, someone made money, call the police"
        ],
        "trigger_phrases": [
            "how dare", "what a crime",
            "oh no", "god forbid",
            "imagine thinking",
            "the audacity"
        ],
        "weight": 1.2
    },
    "specific_numbers": {
        "name": "Specific Numbers/Data",
        "description": "Concrete numbers that make it real",
        "examples": [
            "10% drop in stocks",
            "Bitcoin over $1 million",
            "fraction of a fraction of a cent"
        ],
        "trigger_phrases": [
            "percent", "%",
            "million", "billion",
            "hundred", "thousand",
            "2x", "3x", "10x", "100x"
        ],
        "weight": 1.1
    },
    "walkthrough": {
        "name": "Step-by-Step Walkthrough",
        "description": "Explaining process that builds to punchline",
        "examples": [
            "You hit an API → get 402 error → bot sends USDC → happens at lightspeed",
            "First you do X, then Y happens, and suddenly Z"
        ],
        "trigger_phrases": [
            "first you", "then you",
            "step one", "step two",
            "here's how it works",
            "the process is",
            "and then", "and suddenly"
        ],
        "weight": 1.15
    },
    "redefine": {
        "name": "Redefining a Term",
        "description": "Giving new meaning to something familiar",
        "examples": [
            "x402 isn't 'a payment protocol'... It's pay-per-API for the agent economy",
            "DeFi isn't about removing banks, it's about..."
        ],
        "trigger_phrases": [
            "isn't really", "isn't just",
            "it's actually", "what it really means",
            "the real meaning", "think of it as",
            "better way to think about"
        ],
        "weight": 1.3
    }
}


# ============================================================================
# HARD REJECTION FILTERS - Instant kill signals
# ============================================================================

BAD_OPENERS = [
    "but ", "so ", "and ", "or ",
    "what we ", "what i ",
    "i mean ", "you know ",
    "like i said", "as i mentioned",
    "going back to", "to your point",
    "um ", "uh ", "yeah ",
    "right so", "okay so"
]

JARGON_TERMS = [
    "term structure", "yield curve", "liquidity provision",
    "collateralization ratio", "utilization rate",
    "impermanent loss", "slippage tolerance",
    "rebalancing mechanism", "arbitrage opportunity",
    "cross-margining", "delta neutral"
]


@dataclass
class PatternMatch:
    """A clip candidate that matches a winning pattern."""
    pattern_id: str
    pattern_name: str
    start_time: float
    end_time: float
    transcript_text: str
    speaker_name: Optional[str]
    trigger_found: str  # Which trigger phrase matched
    score: float
    quotable_line: str  # The most quotable single line
    why_good: str  # Explanation for human review


@dataclass
class V3ClipCandidate:
    """Final scored candidate from V3 pipeline."""
    start_time: float
    end_time: float
    transcript_text: str
    speaker_name: Optional[str]
    patterns_matched: List[PatternMatch]
    total_score: float
    primary_pattern: str
    quotable_line: str
    why_selected: str
    rejection_reasons: List[str] = field(default_factory=list)
    passed_filters: bool = True


class ClipFinderV3:
    """
    V3 Clip Finder - Pattern-based selection.

    Instead of generic "find valuable moments", we specifically hunt for
    the 10 patterns that work on crypto Twitter.

    Uses channel tiers to filter at podcast level:
    - Tier A: Best podcasts, up to 3 clips, no min score
    - Tier B: Good podcasts, up to 2 clips, no min score
    - Tier C: Technical podcasts, max 1 clip, requires score >= 2.0
    """

    def __init__(self):
        self.patterns = CLIP_PATTERNS
        self.bad_openers = [x.lower() for x in BAD_OPENERS]
        self.jargon_terms = [x.lower() for x in JARGON_TERMS]
        self.min_duration = 15  # seconds
        self.max_duration = 90  # seconds - shorter is better for Twitter

        # Load tier config
        self.channel_config = CHANNEL_CONFIG
        self.tier_config = self.channel_config.get("tier_config", {})

        # Build channel->tier lookup
        self.channel_tiers = {}
        for ch in self.channel_config.get("channels", []):
            self.channel_tiers[ch["name"].lower()] = ch.get("tier", "B")
            # Also index by handle
            if ch.get("youtube_handle"):
                handle = ch["youtube_handle"].lstrip("@").lower()
                self.channel_tiers[handle] = ch.get("tier", "B")

    def get_channel_tier(self, channel_name: str) -> str:
        """Get tier for a channel (A, B, or C). Defaults to B."""
        name_lower = channel_name.lower()
        # Try exact match first
        if name_lower in self.channel_tiers:
            return self.channel_tiers[name_lower]
        # Try partial match
        for key, tier in self.channel_tiers.items():
            if key in name_lower or name_lower in key:
                return tier
        return "B"  # Default

    def get_tier_settings(self, tier: str) -> Dict[str, Any]:
        """Get settings for a tier."""
        defaults = {
            "A": {"max_clips_per_video": 3, "min_score_threshold": 0, "priority_weight": 1.5},
            "B": {"max_clips_per_video": 2, "min_score_threshold": 0, "priority_weight": 1.0},
            "C": {"max_clips_per_video": 1, "min_score_threshold": 2.0, "priority_weight": 0.5}
        }
        config = self.tier_config.get(tier, {})
        return {**defaults.get(tier, defaults["B"]), **config}

    def should_process_channel(self, channel_name: str) -> Tuple[bool, str]:
        """
        Check if we should process this channel at all.

        Returns (should_process, reason)
        For now, we process all channels but apply different standards.
        This could be extended to skip channels entirely.
        """
        tier = self.get_channel_tier(channel_name)

        if tier == "A":
            return True, f"Tier A: High-priority channel for clip mining"
        elif tier == "B":
            return True, f"Tier B: Standard processing"
        elif tier == "C":
            return True, f"Tier C: Technical content - only exceptional clips will pass"
        else:
            return True, f"Unknown tier, defaulting to B"

    def get_channel_notes(self, channel_name: str) -> Optional[str]:
        """Get notes about a channel (why it's in its tier)."""
        for ch in self.channel_config.get("channels", []):
            if ch["name"].lower() == channel_name.lower():
                return ch.get("notes")
            if ch.get("youtube_handle", "").lstrip("@").lower() == channel_name.lower():
                return ch.get("notes")
        return None

    async def find_clips(
        self,
        transcript: Transcript,
        video_title: str,
        channel_name: str,
        video_id: str = ""
    ) -> List[V3ClipCandidate]:
        """
        Find clips matching winning patterns.

        Returns candidates sorted by score, already filtered.
        Respects channel tier settings for clip limits and score thresholds.
        """
        # Get channel tier settings
        tier = self.get_channel_tier(channel_name)
        tier_settings = self.get_tier_settings(tier)
        max_clips = tier_settings["max_clips_per_video"]
        min_score = tier_settings["min_score_threshold"]

        logger.info(f"[V3] Finding pattern-matched clips in: {video_title}")
        logger.info(f"[V3] Channel tier: {tier} (max {max_clips} clips, min score {min_score})")

        # Step 1: Scan transcript for pattern matches
        raw_matches = await self._scan_for_patterns(transcript, video_title, channel_name)
        logger.info(f"[V3] Found {len(raw_matches)} raw pattern matches")

        if not raw_matches:
            if tier == "C":
                logger.info(f"[V3] Tier C channel with no matches - skipping (expected for technical content)")
            return []

        # Step 2: Apply hard filters
        filtered_matches = self._apply_hard_filters(raw_matches)
        logger.info(f"[V3] {len(filtered_matches)} passed hard filters")

        if not filtered_matches:
            return []

        # Step 3: Group overlapping matches and create candidates
        candidates = self._create_candidates(filtered_matches)
        logger.info(f"[V3] Created {len(candidates)} candidates")

        # Step 4: Score and rank
        scored = self._score_candidates(candidates)

        # Step 5: Apply tier-based score threshold
        if min_score > 0:
            before_count = len(scored)
            scored = [c for c in scored if c.total_score >= min_score]
            if len(scored) < before_count:
                logger.info(f"[V3] Tier {tier}: Removed {before_count - len(scored)} clips below min score {min_score}")

        # Step 6: Apply diversity (respecting tier max clips)
        final = self._apply_diversity_constraints(scored, max_clips=max_clips)
        logger.info(f"[V3] Final selection: {len(final)} clips (tier {tier})")

        return final

    async def _scan_for_patterns(
        self,
        transcript: Transcript,
        video_title: str,
        channel_name: str
    ) -> List[PatternMatch]:
        """Scan transcript for all pattern matches using LLM."""

        # Create chunks for scanning (2 minute windows)
        chunks = self._create_scan_chunks(transcript, chunk_seconds=120)
        all_matches = []

        for i, chunk in enumerate(chunks):
            logger.debug(f"[V3] Scanning chunk {i+1}/{len(chunks)}")

            matches = await self._scan_chunk_for_patterns(
                chunk, video_title, channel_name
            )
            all_matches.extend(matches)

            await asyncio.sleep(0.2)

        return all_matches

    def _create_scan_chunks(
        self,
        transcript: Transcript,
        chunk_seconds: float = 120
    ) -> List[dict]:
        """Create overlapping chunks for pattern scanning."""
        chunks = []
        segments = transcript.segments

        if not segments:
            return []

        chunk_start_time = segments[0].start
        chunk_segments = []

        for segment in segments:
            if segment.start - chunk_start_time > chunk_seconds and chunk_segments:
                # Save chunk
                chunks.append({
                    'start_time': chunk_start_time,
                    'end_time': chunk_segments[-1].end,
                    'text': '\n'.join([
                        f"[{s.start:.1f}s] {s.text}"
                        for s in chunk_segments
                    ]),
                    'segments': chunk_segments.copy()
                })
                # Start new chunk (with 30s overlap)
                overlap_start = segment.start - 30
                chunk_segments = [s for s in chunk_segments if s.start >= overlap_start]
                chunk_start_time = chunk_segments[0].start if chunk_segments else segment.start

            chunk_segments.append(segment)

        # Don't forget last chunk
        if chunk_segments:
            chunks.append({
                'start_time': chunk_start_time,
                'end_time': chunk_segments[-1].end,
                'text': '\n'.join([
                    f"[{s.start:.1f}s] {s.text}"
                    for s in chunk_segments
                ]),
                'segments': chunk_segments
            })

        return chunks

    async def _scan_chunk_for_patterns(
        self,
        chunk: dict,
        video_title: str,
        channel_name: str
    ) -> List[PatternMatch]:
        """Use LLM to find pattern matches in a chunk."""

        patterns_desc = "\n".join([
            f"{i+1}. {p['name']}: {p['description']}\n   Examples: {p['examples'][0]}"
            for i, (pid, p) in enumerate(self.patterns.items())
        ])

        prompt = f"""You are hunting for VIRAL CLIP MOMENTS in a crypto podcast.

PODCAST: {channel_name} - "{video_title}"
CHUNK: {chunk['start_time']:.0f}s - {chunk['end_time']:.0f}s

TRANSCRIPT:
{chunk['text'][:4000]}

PATTERNS THAT GO VIRAL (find these):
{patterns_desc}

FIND MOMENTS that match these patterns. Look for:
- Bold claims or predictions
- Contrasts ("never been worse... never been better")
- Hot takes ("X is dead", "X is over")
- Sarcastic mockery
- Meme references
- Step-by-step explanations with punchlines
- Specific numbers that make it concrete

CRITICAL: The clip must:
- Start CLEAN (not with "But", "So", "And")
- Be a COMPLETE thought (not trail off)
- Be QUOTABLE (something you'd screenshot)
- Take a STANCE (not just describe)

Return JSON:
{{
    "matches": [
        {{
            "pattern": "<pattern name from list above>",
            "start_time": <exact timestamp from [XXX.Xs] markers>,
            "end_time": <timestamp where thought completes>,
            "transcript": "<exact verbatim text>",
            "speaker": "<name if mentioned>",
            "trigger_phrase": "<which phrase triggered the match>",
            "quotable_line": "<the single most tweetable line from this>",
            "why_good": "<1 sentence: why this would work on Twitter>"
        }}
    ]
}}

If no good matches in this chunk, return: {{"matches": []}}
Quality over quantity - only return genuinely good moments."""

        try:
            response = await asyncio.to_thread(
                ollama.chat,
                model=config.OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format="json"
            )

            result = json.loads(response["message"]["content"])
            matches = []

            for m in result.get("matches", []):
                # Map pattern name to ID
                pattern_id = self._get_pattern_id(m.get("pattern", ""))
                if not pattern_id:
                    continue

                # Validate duration
                duration = m.get("end_time", 0) - m.get("start_time", 0)
                if duration < self.min_duration or duration > self.max_duration:
                    continue

                matches.append(PatternMatch(
                    pattern_id=pattern_id,
                    pattern_name=self.patterns[pattern_id]["name"],
                    start_time=m.get("start_time", 0),
                    end_time=m.get("end_time", 0),
                    transcript_text=m.get("transcript", ""),
                    speaker_name=m.get("speaker"),
                    trigger_found=m.get("trigger_phrase", ""),
                    score=self.patterns[pattern_id]["weight"],
                    quotable_line=m.get("quotable_line", ""),
                    why_good=m.get("why_good", "")
                ))

            return matches

        except Exception as e:
            logger.error(f"[V3] Error scanning chunk: {e}")
            return []

    def _get_pattern_id(self, pattern_name: str) -> Optional[str]:
        """Map pattern name to ID."""
        name_lower = pattern_name.lower()
        for pid, p in self.patterns.items():
            if pid in name_lower or p["name"].lower() in name_lower:
                return pid
        # Try partial match
        for pid, p in self.patterns.items():
            if any(word in name_lower for word in pid.split("_")):
                return pid
        return None

    def _apply_hard_filters(self, matches: List[PatternMatch]) -> List[PatternMatch]:
        """Apply hard rejection filters."""
        filtered = []

        for match in matches:
            rejection_reasons = []
            text_lower = match.transcript_text.lower().strip()

            # Check bad openers
            for bad in self.bad_openers:
                if text_lower.startswith(bad):
                    rejection_reasons.append(f"Bad opener: starts with '{bad}'")
                    break

            # Check jargon density (3+ jargon terms in first 50 words)
            first_50_words = ' '.join(text_lower.split()[:50])
            jargon_count = sum(1 for j in self.jargon_terms if j in first_50_words)
            if jargon_count >= 3:
                rejection_reasons.append(f"Too much jargon: {jargon_count} technical terms")

            # Check if thought completes (doesn't end with "...")
            if match.transcript_text.strip().endswith("..."):
                rejection_reasons.append("Incomplete thought: trails off")

            # Check minimum quotable content
            if len(match.quotable_line) < 20:
                rejection_reasons.append("No quotable line found")

            if not rejection_reasons:
                filtered.append(match)
            else:
                logger.debug(f"[V3] Rejected: {rejection_reasons[0]}")

        return filtered

    def _create_candidates(self, matches: List[PatternMatch]) -> List[V3ClipCandidate]:
        """Group overlapping matches into candidates."""
        if not matches:
            return []

        # Sort by start time
        sorted_matches = sorted(matches, key=lambda m: m.start_time)

        candidates = []
        current_group = [sorted_matches[0]]

        for match in sorted_matches[1:]:
            # Check if overlapping with current group (within 30 seconds)
            if match.start_time - current_group[-1].end_time < 30:
                current_group.append(match)
            else:
                # Create candidate from group
                candidates.append(self._group_to_candidate(current_group))
                current_group = [match]

        # Don't forget last group
        if current_group:
            candidates.append(self._group_to_candidate(current_group))

        return candidates

    def _group_to_candidate(self, matches: List[PatternMatch]) -> V3ClipCandidate:
        """Convert a group of overlapping matches to a single candidate."""
        # Use the highest-scoring match as primary
        best_match = max(matches, key=lambda m: m.score)

        # Combine all pattern info
        all_patterns = list(set(m.pattern_id for m in matches))

        return V3ClipCandidate(
            start_time=min(m.start_time for m in matches),
            end_time=max(m.end_time for m in matches),
            transcript_text=best_match.transcript_text,
            speaker_name=best_match.speaker_name,
            patterns_matched=matches,
            total_score=sum(m.score for m in matches),
            primary_pattern=best_match.pattern_name,
            quotable_line=best_match.quotable_line,
            why_selected=best_match.why_good,
            passed_filters=True
        )

    def _score_candidates(self, candidates: List[V3ClipCandidate]) -> List[V3ClipCandidate]:
        """Score and sort candidates."""
        for candidate in candidates:
            # Bonus for multiple pattern matches
            if len(candidate.patterns_matched) > 1:
                candidate.total_score *= 1.2

            # Bonus for shorter clips (more shareable)
            duration = candidate.end_time - candidate.start_time
            if duration <= 45:
                candidate.total_score *= 1.1
            elif duration <= 30:
                candidate.total_score *= 1.2

            # Bonus for having specific numbers
            if any(c.isdigit() for c in candidate.transcript_text):
                candidate.total_score *= 1.05

        # Sort by score
        candidates.sort(key=lambda c: c.total_score, reverse=True)
        return candidates

    def _apply_diversity_constraints(
        self,
        candidates: List[V3ClipCandidate],
        min_gap_seconds: float = 300,  # 5 minutes apart
        max_clips: int = 2
    ) -> List[V3ClipCandidate]:
        """Select final clips with diversity constraints."""
        if not candidates:
            return []

        selected = []

        for candidate in candidates:
            if len(selected) >= max_clips:
                break

            # Check time gap from already selected
            too_close = any(
                abs(candidate.start_time - s.start_time) < min_gap_seconds
                for s in selected
            )

            # Check pattern diversity (prefer different patterns)
            same_pattern = any(
                candidate.primary_pattern == s.primary_pattern
                for s in selected
            )

            if not too_close and not same_pattern:
                selected.append(candidate)
            elif not too_close and len(selected) < max_clips:
                # Accept same pattern if we need clips and it's far enough
                selected.append(candidate)

        return selected

    def format_candidate_for_review(self, candidate: V3ClipCandidate) -> str:
        """Format a candidate for human review in Telegram."""
        duration = candidate.end_time - candidate.start_time

        lines = [
            f"⭐ Score: {candidate.total_score:.1f}",
            f"🎯 Pattern: {candidate.primary_pattern}",
            f"⏱ {candidate.start_time:.0f}s - {candidate.end_time:.0f}s ({duration:.0f}s)",
            f"",
            f"💬 Quotable:",
            f'"{candidate.quotable_line}"',
            f"",
            f"📝 Why good: {candidate.why_selected}",
        ]

        if len(candidate.patterns_matched) > 1:
            patterns = [m.pattern_name for m in candidate.patterns_matched]
            lines.append(f"🔥 Multiple patterns: {', '.join(patterns)}")

        return "\n".join(lines)


# Singleton instance
clip_finder_v3 = ClipFinderV3()
