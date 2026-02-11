#!/usr/bin/env python3
"""
Run Pipeline Now

Runs the podcast clipping pipeline immediately (for testing/manual runs).
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from src.orchestrator import orchestrator


async def main():
    """Run the pipeline now."""
    logger.info("Initializing...")
    await orchestrator.init()

    logger.info("Running pipeline...")
    ranked_posts = await orchestrator.run_daily_pipeline(hours_back=48)

    if ranked_posts:
        logger.info(f"\n✅ Generated {len(ranked_posts)} candidates!")
        for rp in ranked_posts:
            logger.info(f"  #{rp.rank}: {rp.post.clip.video_title[:50]}... (score: {rp.final_score:.2f})")
    else:
        logger.info("No candidates generated. This could mean:")
        logger.info("  - No new podcasts in the last 48 hours")
        logger.info("  - Ollama is not running")
        logger.info("  - Transcription failed")


if __name__ == "__main__":
    asyncio.run(main())
