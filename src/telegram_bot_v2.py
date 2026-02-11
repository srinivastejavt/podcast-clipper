"""
Telegram Bot V2 - Simplified

Only 5 core commands:
- /start - Welcome
- /clips - Get clips (does everything)
- /posted - Mark what you used
- /status - Check everything
- /help - Quick reference
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from loguru import logger
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from src.config import config
from src.database import database


class TelegramBotV2:
    """Simplified Telegram bot - just 5 commands."""

    def __init__(self):
        self.bot_token = config.TELEGRAM_BOT_TOKEN
        self.bot: Optional[Bot] = None
        self.app: Optional[Application] = None
        self.current_batch_clips: Dict[int, List[int]] = {}
        self._processing = False
        self._progress_message_id: Dict[int, int] = {}

    async def init(self):
        """Initialize the Telegram bot."""
        self.bot = Bot(token=self.bot_token)
        self.app = Application.builder().token(self.bot_token).build()

        # Core commands
        self.app.add_handler(CommandHandler("start", self._handle_start))
        self.app.add_handler(CommandHandler("clips", self._handle_clips))
        self.app.add_handler(CommandHandler("posted", self._handle_posted))
        self.app.add_handler(CommandHandler("status", self._handle_status))
        self.app.add_handler(CommandHandler("help", self._handle_help))

        # Debug commands
        self.app.add_handler(CommandHandler("debug", self._handle_debug))
        self.app.add_handler(CommandHandler("test", self._handle_test))
        self.app.add_handler(CommandHandler("logs", self._handle_logs))

        # Legacy aliases (hidden but work)
        self.app.add_handler(CommandHandler("run", self._handle_clips))
        self.app.add_handler(CommandHandler("commands", self._handle_help))

        logger.info("Telegram bot V2 initialized")

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Welcome message."""
        chat_id = update.effective_chat.id
        username = update.effective_user.username

        await database.add_telegram_user(chat_id, username)

        await update.message.reply_text(
            "👋 Welcome to Podcast Clipper!\n\n"
            "I monitor 26 crypto podcasts and send you the best clips with ready-to-post content.\n\n"
            "📌 Commands:\n"
            "/clips - Get 5 fresh clips now\n"
            "/posted 1,3 - Tell me what you used\n"
            "/status - Check progress & stats\n"
            "/debug - Troubleshoot issues\n\n"
            "⏰ Auto-delivery: 11am, 2pm, 6pm, 10pm IST\n\n"
            "Type /clips to get started!"
        )

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Quick help."""
        await update.message.reply_text(
            "📚 Podcast Clipper Commands\n\n"
            "=== Main ===\n"
            "/clips - Get 5 clips now\n"
            "/posted 1,3 - Mark clips you posted\n"
            "/status - See progress, quota, stats\n\n"
            "=== Troubleshooting ===\n"
            "/debug - System health & errors\n"
            "/test - Test clip finding pipeline\n"
            "/logs - View recent log entries\n\n"
            "⏰ Schedule: 11am, 2pm, 6pm, 10pm IST"
        )

    async def _handle_clips(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Main command - does everything to get clips."""
        chat_id = update.effective_chat.id

        if self._processing:
            await update.message.reply_text(
                "Already processing! Check /status for progress."
            )
            return

        self._processing = True
        start_time = datetime.now()

        try:
            # Step 1: Check for ready clips
            progress_msg = await update.message.reply_text(
                "Checking for clips..."
            )
            self._progress_message_id[chat_id] = progress_msg.message_id

            pending_clips = await database.get_pending_clips_for_batch(limit=50)  # Get ALL clips

            if pending_clips:
                await self._update_progress(chat_id, f"Sending {len(pending_clips)} clips...")
                await self._send_clips(chat_id, pending_clips)
                elapsed = (datetime.now() - start_time).seconds
                await self._update_progress(chat_id, f"Done! {len(pending_clips)} clips sent ({elapsed}s)")
                return

            # Step 2: Check for videos needing processing
            await self._update_progress(chat_id, "Looking for unprocessed videos...")
            videos = await database.get_videos_needing_processing()

            if videos:
                await self._update_progress(
                    chat_id,
                    f"Found {len(videos)} videos to process.\n"
                    f"This takes ~10-15 min per video.\n"
                    f"Processing first one now..."
                )

                from src.orchestrator_v4 import orchestrator_v4
                from src.youtube_monitor import VideoInfo
                from datetime import datetime as dt

                for i, v in enumerate(videos[:2]):  # Process max 2
                    video_start = datetime.now()
                    await self._update_progress(
                        chat_id,
                        f"[{i+1}/{min(2, len(videos))}] Processing: {v['title'][:40]}...\n"
                        f"~5 min (transcribe + find clips)"
                    )

                    video_info = VideoInfo(
                        video_id=v['video_id'],
                        channel_name=v['channel_name'],
                        channel_id="",
                        channel_x_handle="",
                        title=v['title'],
                        published_at=dt.now(),
                        description=v.get('description', '')
                    )
                    clips = await orchestrator_v4.process_video(video_info)

                    video_elapsed = (datetime.now() - video_start).seconds // 60
                    await self._update_progress(
                        chat_id,
                        f"[{i+1}/{min(2, len(videos))}] Found {len(clips)} clips ({video_elapsed} min)"
                    )

                # Get the clips we just made
                pending_clips = await database.get_pending_clips_for_batch(limit=50)

            # Step 3: If still no clips, try fetching new videos (uses API quota)
            if len(pending_clips) == 0:
                await self._update_progress(
                    chat_id,
                    "Checking YouTube for new podcasts...\n"
                    "(Uses API quota)"
                )

                from src.youtube_monitor import youtube_monitor
                try:
                    # Check quota first
                    usage = await database.get_api_usage_today("youtube")
                    if usage >= 9000:
                        await self._update_progress(
                            chat_id,
                            f"⚠️ YouTube quota nearly exhausted ({usage:,}/10,000)\n"
                            f"Resets ~1:30 PM IST. Using cached videos only."
                        )
                    else:
                        videos = await youtube_monitor.check_all_channels(since_hours=72)  # 72 hours
                        podcasts = [v for v in videos if youtube_monitor.is_likely_podcast(v)]

                        if podcasts:
                            # Show what we found
                            summary = f"Found {len(podcasts)} podcasts (last 72hrs):\n"
                            for i, v in enumerate(podcasts[:5], 1):
                                pub_date = v.published_at.strftime("%b %d") if v.published_at else "?"
                                duration = f"{v.duration_seconds//60}m" if v.duration_seconds else "?"
                                summary += f"  {i}. [{pub_date}] {v.channel_name}: {v.title[:30]}... ({duration})\n"
                            if len(podcasts) > 5:
                                summary += f"  ... and {len(podcasts)-5} more\n"
                            summary += f"\nProcessing top 2..."
                            await self._update_progress(chat_id, summary)

                            for v in podcasts[:2]:  # Process max 2
                                clips = await orchestrator_v4.process_video(v)
                                if clips:
                                    pending_clips.extend(clips)
                except Exception as e:
                    logger.error(f"Fetch error: {e}")

            # Step 4: Send whatever we have
            if pending_clips:
                await self._update_progress(chat_id, f"Sending {len(pending_clips)} clips...")
                await self._send_clips(chat_id, pending_clips)
                elapsed = (datetime.now() - start_time).seconds
                await self._update_progress(chat_id, f"Done! {len(pending_clips)} clips sent ({elapsed}s)")
            else:
                await self._update_progress(
                    chat_id,
                    "No clips available right now.\n\n"
                    "Possible reasons:\n"
                    "- YouTube API quota exhausted (resets ~1:30 PM IST)\n"
                    "- No new podcasts in last 48 hours\n\n"
                    "Try again later or wait for scheduled delivery."
                )

        except Exception as e:
            logger.error(f"Error in /clips: {e}")
            await self._update_progress(chat_id, f"Error: {str(e)[:100]}")

        finally:
            self._processing = False

    async def _update_progress(self, chat_id: int, text: str):
        """Update the progress message."""
        try:
            msg_id = self._progress_message_id.get(chat_id)
            if msg_id:
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text
                )
        except Exception:
            # If edit fails, send new message
            await self.bot.send_message(chat_id=chat_id, text=text)

    async def _handle_posted(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mark clips as posted."""
        chat_id = update.effective_chat.id

        if not context.args:
            await update.message.reply_text(
                "Usage: /posted 1,3,5\n"
                "Tell me which clip numbers you posted."
            )
            return

        try:
            input_text = " ".join(context.args)
            numbers = [int(n.strip()) for n in input_text.replace(",", " ").split()]

            batch_clips = self.current_batch_clips.get(chat_id, [])
            if not batch_clips:
                await update.message.reply_text("No recent clips to mark.")
                return

            marked = []
            for num in numbers:
                if 1 <= num <= len(batch_clips):
                    clip_id = batch_clips[num - 1]
                    await database.mark_clip_posted(clip_id)
                    marked.append(num)

            if marked:
                await update.message.reply_text(
                    f"Marked clips {', '.join(map(str, marked))} as posted!\n"
                    f"Thanks - this helps me learn what works."
                )

        except ValueError:
            await update.message.reply_text("Use: /posted 1,3,5")

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show everything: progress, quota, stats."""
        # Get various stats
        usage_today = await database.get_api_usage_today("youtube")
        videos_pending = await database.get_videos_needing_processing()
        pending_clips = await database.get_pending_clips_for_batch(limit=100)
        recent_videos = await database.get_recent_videos(hours=72)

        # Quota bar
        quota_percent = (usage_today / 10000) * 100
        quota_bar = "█" * int(quota_percent / 10) + "░" * (10 - int(quota_percent / 10))

        lines = [
            "=== Status ===\n",
            f"Processing: {'🔄 Yes' if self._processing else '💤 Idle'}",
            "\n=== YouTube Quota ===",
            f"{quota_bar} {usage_today:,}/10,000 ({quota_percent:.0f}%)",
        ]

        if quota_percent >= 90:
            lines.append("⚠️ Quota nearly exhausted! Resets ~1:30 PM IST")
        elif quota_percent >= 70:
            lines.append("⚡ Quota getting low")

        lines.extend([
            "\n=== Queue ===",
            f"📹 Videos to process: {len(videos_pending)}",
            f"🎬 Clips ready to send: {len(pending_clips)}",
        ])

        # Show recent processed videos
        if recent_videos:
            lines.append("\n=== Recent Videos (72hrs) ===")
            for v in recent_videos[:5]:
                try:
                    pub = v.get('published_at', '')
                    if pub:
                        from datetime import datetime as dt
                        if isinstance(pub, str):
                            pub = dt.fromisoformat(pub.replace('Z', '+00:00'))
                        pub_str = pub.strftime("%b %d %H:%M")
                    else:
                        pub_str = "?"
                    status = "✅" if v.get('clips_identified') else "⏳"
                    lines.append(f"{status} [{pub_str}] {v.get('channel_name', '')[:15]}: {v.get('title', '')[:25]}...")
                except:
                    pass

        # Show pending videos
        if videos_pending:
            lines.append("\n=== Pending Processing ===")
            for v in videos_pending[:3]:
                lines.append(f"⏳ {v.get('channel_name', '')[:15]}: {v.get('title', '')[:30]}...")
            if len(videos_pending) > 3:
                lines.append(f"   ... and {len(videos_pending)-3} more")

        lines.extend([
            "\n=== Schedule ===",
            "Auto-delivery: 11am, 2pm, 6pm, 10pm IST"
        ])

        await update.message.reply_text("\n".join(lines))

    async def _send_clips(self, chat_id: int, clips: List[dict]):
        """Send clips to user.

        For each clip, sends:
        1. Podcast summary (if available and first clip from that podcast)
        2. Video clip (mp4) with short caption
        3. Full transcript message
        4. Post text message
        """
        if not clips:
            return

        self.current_batch_clips[chat_id] = [c['id'] for c in clips]

        await self.bot.send_message(
            chat_id=chat_id,
            text=f"Here are {len(clips)} clips! Reply /posted 1,3 for ones you use."
        )

        # Track which videos we've sent summaries for
        sent_summaries = set()

        for i, clip in enumerate(clips, 1):
            try:
                video_id = clip.get('video_id', '')
                clip_path = Path(clip.get('clip_path', '')) if clip.get('clip_path') else None
                start_time = int(clip.get('start_time', 0))
                end_time = int(clip.get('end_time', 0))
                video_url = f"https://youtube.com/watch?v={video_id}&t={start_time}"

                # === 0. Send podcast summary (once per video) ===
                if video_id and video_id not in sent_summaries:
                    summary_msg = await self._get_podcast_summary(video_id, clip)
                    if summary_msg:
                        await self.bot.send_message(chat_id=chat_id, text=summary_msg)
                        sent_summaries.add(video_id)
                        await asyncio.sleep(0.5)

                # === 1. Send video clip with short caption ===
                # Get publish date from database
                video_info = await database.get_video_info(video_id)
                pub_date = ""
                if video_info and video_info.get('published_at'):
                    try:
                        from datetime import datetime as dt
                        pub = video_info['published_at']
                        if isinstance(pub, str):
                            pub = dt.fromisoformat(pub.replace('Z', '+00:00'))
                        pub_date = pub.strftime("%b %d")
                    except:
                        pub_date = ""

                short_caption = (
                    f"#{i} | {clip.get('channel_name', '')} - {clip.get('video_title', '')[:40]}...\n"
                    f"📅 Published: {pub_date} | ⏱ {start_time}s - {end_time}s ({end_time - start_time}s)\n"
                    f"🔗 {video_url}"
                )

                if clip_path and clip_path.exists():
                    with open(clip_path, 'rb') as video:
                        await self.bot.send_video(
                            chat_id=chat_id,
                            video=video,
                            caption=short_caption[:1024]
                        )
                else:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=f"#{i} ⚠️ Video not cut yet\n{video_url}"
                    )

                # === 2. Send full transcript ===
                transcript_text = clip.get("transcript_text", "")
                quotable = clip.get('quotable_line', '')
                patterns = ', '.join(clip.get('patterns_matched', [])) if clip.get('patterns_matched') else ''
                why = clip.get('why_selected', '')

                transcript_msg = f"📜 TRANSCRIPT #{i}:\n\n\"{transcript_text}\""
                if quotable:
                    transcript_msg += f"\n\n💬 Quotable: \"{quotable}\""
                if patterns:
                    transcript_msg += f"\n🎯 Pattern: {patterns}"
                if why:
                    transcript_msg += f"\n✨ Why: {why}"

                # Split if too long (Telegram limit 4096)
                if len(transcript_msg) > 4000:
                    await self.bot.send_message(chat_id=chat_id, text=transcript_msg[:4000] + "...")
                else:
                    await self.bot.send_message(chat_id=chat_id, text=transcript_msg)

                # === 3. Send post text ===
                post_text = clip.get('full_post_text', '')
                if post_text:
                    post_msg = f"✍️ YOUR POST #{i}:\n\n{post_text}"
                    if len(post_msg) > 4000:
                        await self.bot.send_message(chat_id=chat_id, text=post_msg[:4000])
                    else:
                        await self.bot.send_message(chat_id=chat_id, text=post_msg)

                await database.mark_clip_sent(clip['id'])

            except Exception as e:
                logger.error(f"Error sending clip {i}: {e}")
                # Fallback: send formatted message
                message = self._format_clip(i, clip)
                await self.bot.send_message(chat_id=chat_id, text=message[:4000])

            await asyncio.sleep(1.5)  # Slightly longer delay between clips

    async def _get_podcast_summary(self, video_id: str, clip: dict) -> Optional[str]:
        """Get podcast summary message for context."""
        try:
            # Try to get video map from database
            video_map = await database.get_video_map(video_id)

            if video_map:
                # Format the summary
                lines = [
                    f"📺 PODCAST SUMMARY",
                    f"━━━━━━━━━━━━━━━━━━━━━",
                    f"📍 {clip.get('channel_name', '')} - {clip.get('video_title', '')}",
                    ""
                ]

                if video_map.get('one_liner'):
                    lines.append(f"📝 {video_map['one_liner']}")

                if video_map.get('main_thesis'):
                    lines.append(f"🎯 Thesis: {video_map['main_thesis']}")

                if video_map.get('overall_sentiment'):
                    sentiment_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(
                        video_map['overall_sentiment'].lower(), "⚪"
                    )
                    lines.append(f"{sentiment_emoji} Sentiment: {video_map['overall_sentiment']}")

                # Add chapters summary
                chapters = video_map.get('chapters', [])
                if chapters:
                    lines.append("")
                    lines.append("📚 CHAPTERS:")
                    for j, ch in enumerate(chapters[:6], 1):  # Max 6 chapters
                        start_min = ch.get('start_time', 0) / 60
                        lines.append(f"  {j}. [{start_min:.0f}m] {ch.get('label', '')}")
                        if ch.get('summary'):
                            lines.append(f"      {ch['summary'][:80]}...")

                # Add speakers
                speakers = video_map.get('speakers', {})
                if speakers:
                    lines.append("")
                    lines.append("👥 SPEAKERS:")
                    for name, speaker in list(speakers.items())[:3]:  # Max 3 speakers
                        role = speaker.get('role', '')
                        stance = speaker.get('stance', '')
                        lines.append(f"  • {speaker.get('name', name)} ({role}) - {stance}")
                        if speaker.get('main_claims'):
                            claims = speaker['main_claims'][:2]
                            lines.append(f"    Claims: {'; '.join(claims)[:100]}")

                # Add key claims
                claims = video_map.get('claims', [])
                if claims:
                    lines.append("")
                    lines.append("💡 KEY CLAIMS:")
                    for claim in claims[:3]:  # Max 3 claims
                        lines.append(f"  • {claim.get('claim', '')[:100]}")

                lines.append("")
                lines.append("━━━━━━━━━━━━━━━━━━━━━")

                summary = "\n".join(lines)
                return summary[:4000]  # Telegram limit

            else:
                # No video map - return basic info
                return (
                    f"📺 PODCAST: {clip.get('channel_name', '')} - {clip.get('video_title', '')}\n"
                    f"(No detailed summary available)"
                )

        except Exception as e:
            logger.error(f"Error getting podcast summary: {e}")
            return None

    def _format_clip(self, rank: int, clip: dict) -> str:
        """Format a clip for sending."""
        video_url = f"https://youtube.com/watch?v={clip.get('video_id', '')}"
        start_time = int(clip.get('start_time', 0))
        end_time = int(clip.get('end_time', 0))

        # YouTube URL with timestamp
        timestamped_url = f"{video_url}&t={start_time}"

        # V3 pattern info if available
        pattern_info = ""
        if clip.get('quotable_line'):
            pattern_info = f"\n💬 QUOTABLE:\n\"{clip.get('quotable_line')}\"\n"
        if clip.get('patterns_matched'):
            patterns = ', '.join(clip.get('patterns_matched', []))
            pattern_info += f"\n🎯 Pattern: {patterns}"
        if clip.get('why_selected'):
            pattern_info += f"\n✨ Why: {clip.get('why_selected')}"

        # Get full transcript text (not truncated)
        transcript_text = clip.get("transcript_text", "")

        return (
            f"#{rank}\n\n"
            f"{clip.get('channel_name', '')} - {clip.get('video_title', '')[:50]}\n"
            f"🔗 {timestamped_url}\n"
            f"⏱ {start_time}s - {end_time}s ({end_time - start_time}s)\n"
            f"{pattern_info}\n"
            f"---\n"
            f"📜 FULL TRANSCRIPT:\n\n"
            f'"{transcript_text}"\n\n'
            f"---\n"
            f"✍️ YOUR POST:\n\n"
            f"{clip.get('full_post_text', '')}"
        )

    async def _handle_debug(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Deep troubleshooting info."""
        import os
        import sys
        from pathlib import Path

        lines = ["🔧 DEBUG INFO\n"]

        # 1. System health
        lines.append("=== System ===")
        try:
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            lines.append(f"CPU: {cpu}% | RAM: {mem}% | Disk: {disk}%")
        except:
            lines.append("(psutil not available)")

        # 2. Ollama status
        lines.append("\n=== Ollama (LLM) ===")
        try:
            import ollama
            models = ollama.list()
            model_names = [m.get('name', m.get('model', 'unknown')) for m in models.get('models', [])]
            lines.append(f"✅ Running | Models: {', '.join(model_names[:3])}")
        except Exception as e:
            lines.append(f"❌ Error: {str(e)[:50]}")

        # 3. Database stats
        lines.append("\n=== Database ===")
        try:
            videos = await database.get_recent_videos(hours=168)  # 7 days
            clips_pending = await database.get_pending_clips_for_batch(limit=100)
            lines.append(f"Videos (7d): {len(videos)}")
            lines.append(f"Clips pending: {len(clips_pending)}")

            # Last batch
            last_batch = await database.get_last_batch_time()
            if last_batch:
                lines.append(f"Last batch: {last_batch.strftime('%b %d %H:%M')}")
            else:
                lines.append("Last batch: Never")
        except Exception as e:
            lines.append(f"❌ DB Error: {e}")

        # 4. YouTube quota
        lines.append("\n=== YouTube API ===")
        try:
            usage = await database.get_api_usage_today("youtube")
            remaining = 10000 - usage
            lines.append(f"Used: {usage:,}/10,000 ({usage/100:.0f}%)")
            lines.append(f"Remaining: {remaining:,} units")
            if usage >= 9000:
                lines.append("⚠️ CRITICAL: Nearly exhausted!")
            elif usage >= 7000:
                lines.append("⚡ WARNING: Getting low")
        except Exception as e:
            lines.append(f"❌ Error: {e}")

        # 5. File paths
        lines.append("\n=== Paths ===")
        from src.config import DATA_DIR, CLIPS_DIR, TRANSCRIPTS_DIR
        lines.append(f"Data: {DATA_DIR}")
        clips_count = len(list(CLIPS_DIR.glob("*.mp4"))) if CLIPS_DIR.exists() else 0
        transcripts_count = len(list(TRANSCRIPTS_DIR.glob("*.json"))) if TRANSCRIPTS_DIR.exists() else 0
        lines.append(f"Clips: {clips_count} files")
        lines.append(f"Transcripts: {transcripts_count} cached")

        # 6. Recent errors from logs
        lines.append("\n=== Recent Errors ===")
        try:
            log_dir = DATA_DIR / "logs"
            if log_dir.exists():
                log_files = sorted(log_dir.glob("*.log"), reverse=True)
                if log_files:
                    with open(log_files[0], 'r') as f:
                        log_lines = f.readlines()[-50:]  # Last 50 lines
                    errors = [l.strip() for l in log_lines if 'ERROR' in l or 'WARNING' in l]
                    if errors:
                        for err in errors[-3:]:  # Last 3 errors
                            lines.append(f"• {err[:80]}...")
                    else:
                        lines.append("✅ No recent errors")
                else:
                    lines.append("No log files")
            else:
                lines.append("Log dir not found")
        except Exception as e:
            lines.append(f"Error reading logs: {e}")

        # 7. Commands to try
        lines.append("\n=== Troubleshooting ===")
        lines.append("/test - Test clip finding")
        lines.append("/logs - View recent logs")
        lines.append("/status - Check queue & quota")

        await update.message.reply_text("\n".join(lines))

    async def _handle_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Test the clip finding pipeline with a known video."""
        chat_id = update.effective_chat.id

        await update.message.reply_text(
            "🧪 Running pipeline test...\n\n"
            "This tests each component:\n"
            "1. Database connection\n"
            "2. Transcript loading\n"
            "3. LLM clip finding\n"
            "4. Results\n\n"
            "Please wait ~1-2 min..."
        )

        results = []

        # Test 1: Database
        results.append("1️⃣ Database:")
        try:
            await database.init()
            count = len(await database.get_recent_videos(hours=24))
            results.append(f"   ✅ Connected ({count} videos in 24h)")
        except Exception as e:
            results.append(f"   ❌ Error: {e}")
            await update.message.reply_text("\n".join(results))
            return

        # Test 2: Find a cached transcript
        results.append("\n2️⃣ Transcript:")
        try:
            from src.config import TRANSCRIPTS_DIR
            transcripts = list(TRANSCRIPTS_DIR.glob("*_transcript.json"))
            if transcripts:
                # Use most recent
                transcript_file = sorted(transcripts, key=lambda x: x.stat().st_mtime, reverse=True)[0]
                video_id = transcript_file.stem.replace("_transcript", "")
                results.append(f"   ✅ Found cached: {video_id}")

                from src.transcriber import transcriber
                transcript = await transcriber.transcribe(video_id)
                if transcript:
                    results.append(f"   ✅ Loaded: {len(transcript.segments)} segments")
                else:
                    results.append("   ❌ Failed to load")
                    await update.message.reply_text("\n".join(results))
                    return
            else:
                results.append("   ⚠️ No cached transcripts")
                results.append("   Run /clips first to process a video")
                await update.message.reply_text("\n".join(results))
                return
        except Exception as e:
            results.append(f"   ❌ Error: {e}")
            await update.message.reply_text("\n".join(results))
            return

        # Test 3: LLM clip finding
        results.append("\n3️⃣ LLM Clip Finding:")
        try:
            from src.clip_finder_v4 import clip_finder_v4
            import time

            start = time.time()
            clips = await clip_finder_v4.find_clips(
                transcript=transcript,
                video_title="Test Video",
                channel_name="Test Channel",
                video_id=video_id
            )
            elapsed = time.time() - start

            if clips:
                results.append(f"   ✅ Found {len(clips)} clips in {elapsed:.1f}s")
                for i, clip in enumerate(clips, 1):
                    results.append(f"   Clip {i}: {clip.start_time:.0f}s-{clip.end_time:.0f}s")
                    results.append(f"      \"{clip.quotable_line[:50]}...\"")
            else:
                results.append(f"   ⚠️ No clips found ({elapsed:.1f}s)")
                results.append("   This could mean:")
                results.append("   • Ollama not running")
                results.append("   • Model not loaded")
                results.append("   • JSON parsing failed")
        except Exception as e:
            results.append(f"   ❌ Error: {e}")

        # Summary
        results.append("\n" + "="*30)
        if "❌" in "\n".join(results):
            results.append("⚠️ Some tests failed - check errors above")
        else:
            results.append("✅ All tests passed!")

        await update.message.reply_text("\n".join(results))

    async def _handle_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show recent log entries."""
        from src.config import DATA_DIR

        lines = ["📋 RECENT LOGS\n"]

        try:
            log_dir = DATA_DIR / "logs"
            if not log_dir.exists():
                await update.message.reply_text("No logs directory found")
                return

            log_files = sorted(log_dir.glob("*.log"), reverse=True)
            if not log_files:
                await update.message.reply_text("No log files found")
                return

            # Read last 30 lines from most recent log
            with open(log_files[0], 'r') as f:
                all_lines = f.readlines()

            # Get last 20 entries
            recent = all_lines[-20:]

            for line in recent:
                line = line.strip()
                if not line:
                    continue

                # Shorten and add emoji
                if "ERROR" in line:
                    lines.append(f"❌ {line[:100]}")
                elif "WARNING" in line:
                    lines.append(f"⚠️ {line[:100]}")
                elif "INFO" in line:
                    lines.append(f"ℹ️ {line[:100]}")
                else:
                    lines.append(f"  {line[:100]}")

            lines.append(f"\n📁 Log file: {log_files[0].name}")

        except Exception as e:
            lines.append(f"Error reading logs: {e}")

        # Split if too long
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n... (truncated)"

        await update.message.reply_text(text)

    async def send_to_all_users(self, clips: List[dict], batch_type: str = "regular"):
        """Send clips to all subscribed users."""
        users = await database.get_active_telegram_users()

        for chat_id in users:
            try:
                await self._send_clips(chat_id, clips)
            except Exception as e:
                logger.error(f"Error sending to {chat_id}: {e}")

    async def send_notification(self, message: str):
        """Send notification to all users."""
        users = await database.get_active_telegram_users()
        for chat_id in users:
            try:
                await self.bot.send_message(chat_id=chat_id, text=message)
            except Exception:
                pass

    def run_polling(self):
        """Run bot."""
        logger.info("Starting Telegram bot V2...")
        self.app.run_polling()


# Singleton
telegram_bot = TelegramBotV2()
