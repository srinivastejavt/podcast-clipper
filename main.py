#!/usr/bin/env python3
"""
Podcast Clipper - PRODUCTION VERSION

Schedule: 11am, 2pm, 6pm, 10pm IST
"""

import asyncio
import sys
import os
import fcntl
import signal
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import config, DATA_DIR
from src.database import database
from src.telegram_bot_v2 import telegram_bot


# === SINGLE INSTANCE LOCK ===
LOCK_FILE = DATA_DIR / "bot.lock"
lock_fd = None

def acquire_lock():
    """Ensure only one bot instance runs."""
    global lock_fd
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_fd = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        logger.info(f"Lock acquired - PID {os.getpid()}")
        return True
    except IOError:
        logger.error("Another bot instance is running!")
        print("ERROR: Another bot instance is already running!")
        print("Run: pkill -f 'python.*main.py'")
        sys.exit(1)

def release_lock():
    """Release the lock on shutdown."""
    global lock_fd
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            LOCK_FILE.unlink(missing_ok=True)
        except:
            pass


# === LOGGING ===
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "logs").mkdir(exist_ok=True)

logger.add(
    DATA_DIR / "logs" / "bot_{time}.log",
    rotation="1 day",
    retention="3 days",
    level="INFO"
)


# === BATCH DELIVERY ===
async def run_batch_delivery():
    """Scheduled batch delivery with error handling."""
    logger.info("=== BATCH DELIVERY STARTED ===")
    try:
        from src.youtube_monitor import youtube_monitor
        from src.orchestrator_v4 import orchestrator_v4

        # Check quota first
        usage = await database.get_api_usage_today("youtube")
        if usage >= 9000:
            logger.warning(f"YouTube quota low ({usage}/10000), skipping fetch")
        else:
            # Get recent videos
            videos = await youtube_monitor.check_all_channels(since_hours=72)
            podcasts = [v for v in videos if youtube_monitor.is_likely_podcast(v)]
            logger.info(f"Found {len(podcasts)} podcasts")

            # Process up to 3 videos
            for video in podcasts[:3]:
                if await database.video_exists(video.video_id):
                    continue
                try:
                    clips = await orchestrator_v4.process_video(video)
                    if clips:
                        logger.info(f"Processed {len(clips)} clips from {video.title[:30]}")
                except Exception as e:
                    logger.error(f"Failed to process {video.video_id}: {e}")

        # Send ALL pending clips
        pending = await database.get_pending_clips_for_batch(limit=50)
        if pending:
            logger.info(f"Sending {len(pending)} clips to users")
            await telegram_bot.send_to_all_users(pending)
            await database.log_batch("scheduled", len(pending))
        else:
            logger.info("No pending clips to send")

    except Exception as e:
        logger.error(f"Batch delivery error: {e}")

    logger.info("=== BATCH DELIVERY COMPLETE ===")


# === STARTUP CHECK ===
async def startup_notification():
    """Send startup notification with status."""
    import pytz

    tz = pytz.timezone(config.TIMEZONE)
    now = datetime.now(tz)

    # Scheduled hours
    scheduled_hours = [11, 14, 18, 22]

    # Find next batch time
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_hour = None
    next_time = None

    for hour in sorted(scheduled_hours):
        scheduled_time = today.replace(hour=hour)
        if scheduled_time > now:
            next_hour = hour
            next_time = scheduled_time
            break

    if next_hour is None:
        tomorrow = today + timedelta(days=1)
        next_hour = scheduled_hours[0]
        next_time = tomorrow.replace(hour=next_hour)

    # Time until next batch
    time_until = next_time - now
    hours_until = time_until.total_seconds() / 3600
    if hours_until < 1:
        time_str = f"{int(time_until.total_seconds() / 60)} minutes"
    else:
        time_str = f"{hours_until:.1f} hours"

    # Get stats
    pending = await database.get_pending_clips_for_batch(limit=100)
    usage = await database.get_api_usage_today("youtube")
    quota_pct = int(usage / 100)

    # Build message
    msg = (
        f"🟢 Bot is online!\n\n"
        f"📬 Clips ready: {len(pending)}\n"
        f"⏰ Next batch: {next_hour}:00 IST (in {time_str})\n"
        f"📊 YouTube Quota: {usage:,}/10,000 ({quota_pct}%)\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 COMMANDS\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"/clips → Get clips now\n"
        f"/status → See queue & stats\n"
        f"/debug → System health\n"
        f"/posted 1,3 → Mark clips used\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    await telegram_bot.send_notification(msg)


# === MAIN ===
def main():
    # Acquire lock first
    acquire_lock()

    # Handle graceful shutdown
    def shutdown_handler(signum, frame):
        logger.info("Shutdown signal received")
        release_lock()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    import nest_asyncio
    nest_asyncio.apply()

    async def setup():
        logger.info("=== STARTING PODCAST CLIPPER ===")

        # Initialize
        await database.init()
        await telegram_bot.init()

        # Send startup notification
        try:
            await startup_notification()
        except Exception as e:
            logger.error(f"Startup notification failed: {e}")

        # Setup scheduler
        scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

        # Schedule batches: 11am, 2pm, 6pm, 10pm IST
        for hour in [11, 14, 18, 22]:
            scheduler.add_job(
                run_batch_delivery,
                CronTrigger(hour=hour, minute=0),
                id=f"batch_{hour}",
                replace_existing=True,
                misfire_grace_time=3600  # Allow 1 hour grace for missed jobs
            )
            logger.info(f"Scheduled batch at {hour}:00 IST")

        scheduler.start()
        logger.info("Scheduler started")

    try:
        asyncio.run(setup())
        logger.info("Starting Telegram bot polling...")

        # Run polling with error handling for network issues
        while True:
            try:
                telegram_bot.app.run_polling(
                    drop_pending_updates=True,
                    allowed_updates=["message"],
                    close_loop=False
                )
                break  # Clean exit
            except Exception as poll_error:
                error_str = str(poll_error).lower()

                # Network-related errors - wait and retry
                if any(x in error_str for x in [
                    "nodename nor servname",
                    "network is unreachable",
                    "connection reset",
                    "timed out",
                    "temporary failure",
                    "getaddrinfo failed"
                ]):
                    logger.warning(f"Network error: {poll_error}")
                    logger.info("Waiting 60s before retry...")
                    import time
                    time.sleep(60)
                    continue

                # Conflict error - another instance took over
                elif "conflict" in error_str or "terminated by other" in error_str:
                    logger.error("Another bot instance detected, exiting...")
                    break

                # Unknown error - re-raise
                else:
                    raise

    except Exception as e:
        logger.error(f"Bot crashed: {e}")
    finally:
        release_lock()


if __name__ == "__main__":
    main()
