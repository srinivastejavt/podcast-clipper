"""
Database Module

SQLite database for tracking processed videos, clips, and posting history.
"""

import aiosqlite
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from loguru import logger

from src.config import DB_PATH


class Database:
    """SQLite database for tracking state."""

    def __init__(self):
        self.db_path = DB_PATH

    async def init(self):
        """Initialize database tables."""
        async with aiosqlite.connect(self.db_path) as db:
            # Videos table - tracks which videos we've processed
            await db.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    channel_name TEXT,
                    title TEXT,
                    description TEXT,
                    published_at TIMESTAMP,
                    processed_at TIMESTAMP,
                    transcribed BOOLEAN DEFAULT FALSE,
                    clips_identified BOOLEAN DEFAULT FALSE
                )
            """)

            # Clips table - tracks identified clips
            await db.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT,
                    start_time REAL,
                    end_time REAL,
                    transcript_text TEXT,
                    speaker_name TEXT,
                    speaker_x_handle TEXT,
                    clip_type TEXT,
                    score REAL,
                    clip_path TEXT,
                    opinion_text TEXT,
                    full_post_text TEXT,
                    sent_to_user BOOLEAN DEFAULT FALSE,
                    user_posted BOOLEAN DEFAULT FALSE,
                    posted_at TIMESTAMP,
                    is_backup BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_id) REFERENCES videos(video_id)
                )
            """)

            # Speakers table - track speakers and their insights
            await db.execute("""
                CREATE TABLE IF NOT EXISTS speakers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    x_handle TEXT,
                    company TEXT,
                    role TEXT,
                    topics TEXT,
                    clip_count INTEGER DEFAULT 0,
                    last_seen TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Speaker insights - what each speaker is bullish on
            await db.execute("""
                CREATE TABLE IF NOT EXISTS speaker_insights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    speaker_id INTEGER,
                    topic TEXT,
                    stance TEXT,
                    summary TEXT,
                    clip_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (speaker_id) REFERENCES speakers(id),
                    FOREIGN KEY (clip_id) REFERENCES clips(id)
                )
            """)

            # Telegram users - who should receive updates
            await db.execute("""
                CREATE TABLE IF NOT EXISTS telegram_users (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT,
                    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)

            # Batch history - track sent batches
            await db.execute("""
                CREATE TABLE IF NOT EXISTS batch_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_type TEXT,
                    clip_count INTEGER,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Opinion variations - store multiple opinions per clip
            await db.execute("""
                CREATE TABLE IF NOT EXISTS opinion_variations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clip_id INTEGER,
                    variation_index INTEGER,
                    variation_style TEXT,
                    opinion_text TEXT,
                    full_post_text TEXT,
                    selected BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (clip_id) REFERENCES clips(id)
                )
            """)

            # Clip previews - for preview before full processing
            await db.execute("""
                CREATE TABLE IF NOT EXISTS clip_previews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT,
                    start_time REAL,
                    end_time REAL,
                    transcript_preview TEXT,
                    clip_type TEXT,
                    estimated_score REAL,
                    approved BOOLEAN DEFAULT NULL,
                    processed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_id) REFERENCES videos(video_id)
                )
            """)

            # Episode summaries - cached episode context
            await db.execute("""
                CREATE TABLE IF NOT EXISTS episode_summaries (
                    video_id TEXT PRIMARY KEY,
                    main_topics TEXT,
                    key_points TEXT,
                    speakers_mentioned TEXT,
                    overall_sentiment TEXT,
                    one_liner TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_id) REFERENCES videos(video_id)
                )
            """)

            # API usage tracking
            await db.execute("""
                CREATE TABLE IF NOT EXISTS api_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    api_name TEXT,
                    endpoint TEXT,
                    units_used INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Channel ID cache - avoid repeated lookups
            await db.execute("""
                CREATE TABLE IF NOT EXISTS channel_cache (
                    youtube_handle TEXT PRIMARY KEY,
                    channel_id TEXT,
                    channel_name TEXT,
                    last_checked TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Fetch history - track when we last fetched each channel
            await db.execute("""
                CREATE TABLE IF NOT EXISTS fetch_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_name TEXT,
                    videos_found INTEGER,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Video maps - full podcast summaries
            await db.execute("""
                CREATE TABLE IF NOT EXISTS video_maps (
                    video_id TEXT PRIMARY KEY,
                    video_map TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.commit()
            logger.info("Database initialized")

    async def video_exists(self, video_id: str) -> bool:
        """Check if a video has been processed."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM videos WHERE video_id = ?",
                (video_id,)
            )
            return await cursor.fetchone() is not None

    async def add_video(
        self,
        video_id: str,
        channel_name: str,
        title: str,
        published_at: datetime,
        description: str = ""
    ):
        """Add a video to the database."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO videos
                (video_id, channel_name, title, description, published_at, processed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (video_id, channel_name, title, description, published_at, datetime.utcnow()))
            await db.commit()

    async def mark_video_transcribed(self, video_id: str):
        """Mark a video as transcribed."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE videos SET transcribed = TRUE WHERE video_id = ?",
                (video_id,)
            )
            await db.commit()

    async def mark_video_clips_identified(self, video_id: str):
        """Mark a video as having clips identified."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE videos SET clips_identified = TRUE WHERE video_id = ?",
                (video_id,)
            )
            await db.commit()

    async def save_clip(
        self,
        video_id: str,
        start_time: float,
        end_time: float,
        transcript_text: str,
        speaker_name: Optional[str],
        speaker_x_handle: Optional[str],
        clip_type: str,
        score: float,
        clip_path: Optional[str] = None,
        opinion_text: Optional[str] = None,
        full_post_text: Optional[str] = None,
        score_breakdown: Optional[dict] = None
    ) -> int:
        """Save a clip to the database and return its ID."""
        import json
        async with aiosqlite.connect(self.db_path) as db:
            # Check if score_breakdown column exists, add if not
            try:
                await db.execute("SELECT score_breakdown FROM clips LIMIT 1")
            except:
                await db.execute("ALTER TABLE clips ADD COLUMN score_breakdown TEXT")
                await db.commit()

            score_breakdown_json = json.dumps(score_breakdown) if score_breakdown else None

            cursor = await db.execute("""
                INSERT INTO clips
                (video_id, start_time, end_time, transcript_text, speaker_name,
                 speaker_x_handle, clip_type, score, clip_path, opinion_text, full_post_text, score_breakdown)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (video_id, start_time, end_time, transcript_text, speaker_name,
                  speaker_x_handle, clip_type, score, clip_path, opinion_text, full_post_text, score_breakdown_json))
            await db.commit()
            return cursor.lastrowid

    async def mark_clip_sent(self, clip_id: int):
        """Mark a clip as sent to user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE clips SET sent_to_user = TRUE WHERE id = ?",
                (clip_id,)
            )
            await db.commit()

    async def mark_clip_posted(self, clip_id: int):
        """Mark a clip as posted by user to X."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE clips SET user_posted = TRUE, posted_at = ? WHERE id = ?",
                (datetime.utcnow(), clip_id)
            )
            await db.commit()

    async def mark_clip_as_backup(self, clip_id: int):
        """Mark a clip as backup for low-content days."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE clips SET is_backup = TRUE WHERE id = ?",
                (clip_id,)
            )
            await db.commit()

    async def get_unposted_clips(self, limit: int = 10) -> list[dict]:
        """Get clips that were sent but not posted (for backup)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT c.*, v.title as video_title, v.channel_name, v.published_at
                FROM clips c
                JOIN videos v ON c.video_id = v.video_id
                WHERE c.sent_to_user = TRUE
                AND c.user_posted = FALSE
                AND c.created_at > datetime('now', '-7 days')
                ORDER BY c.score DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_weekly_backup_clips(self, limit: int = 5) -> list[dict]:
        """Get top unposted clips from the week for backup."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT c.*, v.title as video_title, v.channel_name, v.published_at
                FROM clips c
                JOIN videos v ON c.video_id = v.video_id
                WHERE c.sent_to_user = TRUE
                AND c.user_posted = FALSE
                AND c.created_at > datetime('now', '-7 days')
                ORDER BY c.score DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_pending_clips_for_batch(self, limit: int = 5) -> list[dict]:
        """Get clips that haven't been sent yet for a new batch."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT c.*, v.title as video_title, v.channel_name, v.published_at
                FROM clips c
                JOIN videos v ON c.video_id = v.video_id
                WHERE c.sent_to_user = FALSE
                AND c.clip_path IS NOT NULL
                ORDER BY c.created_at DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def add_telegram_user(self, chat_id: int, username: Optional[str] = None):
        """Add or update a Telegram user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO telegram_users (chat_id, username, is_active)
                VALUES (?, ?, TRUE)
            """, (chat_id, username))
            await db.commit()

    async def get_active_telegram_users(self) -> list[int]:
        """Get all active Telegram user chat IDs."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT chat_id FROM telegram_users WHERE is_active = TRUE"
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_recent_videos(self, hours: int = 48) -> list[dict]:
        """Get recently processed videos."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM videos
                WHERE processed_at > datetime('now', ? || ' hours')
                ORDER BY processed_at DESC
            """, (f"-{hours}",))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def add_or_update_speaker(
        self,
        name: str,
        x_handle: Optional[str] = None,
        company: Optional[str] = None,
        role: Optional[str] = None
    ) -> int:
        """Add or update a speaker and return their ID."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if speaker exists
            cursor = await db.execute(
                "SELECT id FROM speakers WHERE LOWER(name) = LOWER(?)",
                (name,)
            )
            row = await cursor.fetchone()

            if row:
                speaker_id = row[0]
                # Update existing speaker
                await db.execute("""
                    UPDATE speakers
                    SET x_handle = COALESCE(?, x_handle),
                        company = COALESCE(?, company),
                        role = COALESCE(?, role),
                        clip_count = clip_count + 1,
                        last_seen = ?
                    WHERE id = ?
                """, (x_handle, company, role, datetime.utcnow(), speaker_id))
            else:
                # Insert new speaker
                cursor = await db.execute("""
                    INSERT INTO speakers (name, x_handle, company, role, clip_count, last_seen)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (name, x_handle, company, role, datetime.utcnow()))
                speaker_id = cursor.lastrowid

            await db.commit()
            return speaker_id

    async def add_speaker_insight(
        self,
        speaker_id: int,
        topic: str,
        stance: str,
        summary: str,
        clip_id: int
    ):
        """Add an insight for a speaker."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO speaker_insights (speaker_id, topic, stance, summary, clip_id)
                VALUES (?, ?, ?, ?, ?)
            """, (speaker_id, topic, stance, summary, clip_id))
            await db.commit()

    async def get_speaker_summary(self, speaker_name: str) -> dict:
        """Get a summary of what a speaker is bullish/bearish on."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Get speaker info
            cursor = await db.execute(
                "SELECT * FROM speakers WHERE LOWER(name) = LOWER(?)",
                (speaker_name,)
            )
            speaker = await cursor.fetchone()

            if not speaker:
                return None

            # Get their insights
            cursor = await db.execute("""
                SELECT topic, stance, summary FROM speaker_insights
                WHERE speaker_id = ?
                ORDER BY created_at DESC
            """, (speaker['id'],))
            insights = await cursor.fetchall()

            return {
                'speaker': dict(speaker),
                'insights': [dict(i) for i in insights]
            }

    async def log_batch(self, batch_type: str, clip_count: int):
        """Log a sent batch."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO batch_history (batch_type, clip_count)
                VALUES (?, ?)
            """, (batch_type, clip_count))
            await db.commit()

    async def get_last_batch_time(self) -> Optional[datetime]:
        """Get the time of the last sent batch."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT sent_at FROM batch_history
                ORDER BY sent_at DESC LIMIT 1
            """)
            row = await cursor.fetchone()
            if row and row[0]:
                try:
                    return datetime.fromisoformat(row[0].replace('Z', '+00:00'))
                except:
                    return None
            return None

    async def get_clip_by_id(self, clip_id: int) -> Optional[dict]:
        """Get a clip by its ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM clips WHERE id = ?",
                (clip_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    # =========== OPINION VARIATIONS ===========

    async def save_opinion_variation(
        self,
        clip_id: int,
        variation_index: int,
        variation_style: str,
        opinion_text: str,
        full_post_text: str
    ) -> int:
        """Save an opinion variation for a clip."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO opinion_variations
                (clip_id, variation_index, variation_style, opinion_text, full_post_text)
                VALUES (?, ?, ?, ?, ?)
            """, (clip_id, variation_index, variation_style, opinion_text, full_post_text))
            await db.commit()
            return cursor.lastrowid

    async def get_opinion_variations(self, clip_id: int) -> list[dict]:
        """Get all opinion variations for a clip."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM opinion_variations
                WHERE clip_id = ?
                ORDER BY variation_index
            """, (clip_id,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def select_opinion_variation(self, clip_id: int, variation_index: int):
        """Mark a variation as selected and update the main clip."""
        async with aiosqlite.connect(self.db_path) as db:
            # Get the selected variation
            cursor = await db.execute("""
                SELECT opinion_text, full_post_text FROM opinion_variations
                WHERE clip_id = ? AND variation_index = ?
            """, (clip_id, variation_index))
            row = await cursor.fetchone()

            if row:
                # Update main clip
                await db.execute("""
                    UPDATE clips
                    SET opinion_text = ?, full_post_text = ?
                    WHERE id = ?
                """, (row[0], row[1], clip_id))

                # Mark variation as selected
                await db.execute("""
                    UPDATE opinion_variations
                    SET selected = TRUE
                    WHERE clip_id = ? AND variation_index = ?
                """, (clip_id, variation_index))

            await db.commit()

    # =========== CLIP PREVIEWS ===========

    async def save_clip_preview(
        self,
        video_id: str,
        start_time: float,
        end_time: float,
        transcript_preview: str,
        clip_type: str,
        estimated_score: float
    ) -> int:
        """Save a clip preview for approval before full processing."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO clip_previews
                (video_id, start_time, end_time, transcript_preview, clip_type, estimated_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (video_id, start_time, end_time, transcript_preview, clip_type, estimated_score))
            await db.commit()
            return cursor.lastrowid

    async def get_pending_previews(self, video_id: Optional[str] = None) -> list[dict]:
        """Get clip previews waiting for approval."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if video_id:
                cursor = await db.execute("""
                    SELECT p.*, v.title as video_title, v.channel_name
                    FROM clip_previews p
                    JOIN videos v ON p.video_id = v.video_id
                    WHERE p.approved IS NULL AND p.video_id = ?
                    ORDER BY p.estimated_score DESC
                """, (video_id,))
            else:
                cursor = await db.execute("""
                    SELECT p.*, v.title as video_title, v.channel_name
                    FROM clip_previews p
                    JOIN videos v ON p.video_id = v.video_id
                    WHERE p.approved IS NULL
                    ORDER BY p.estimated_score DESC
                """)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def approve_preview(self, preview_id: int, approved: bool):
        """Approve or reject a clip preview."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE clip_previews
                SET approved = ?
                WHERE id = ?
            """, (approved, preview_id))
            await db.commit()

    async def mark_preview_processed(self, preview_id: int):
        """Mark a preview as processed (clip has been cut)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE clip_previews
                SET processed = TRUE
                WHERE id = ?
            """, (preview_id,))
            await db.commit()

    async def get_approved_previews(self, limit: int = 10) -> list[dict]:
        """Get approved previews that haven't been processed yet."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT p.*, v.title as video_title, v.channel_name
                FROM clip_previews p
                JOIN videos v ON p.video_id = v.video_id
                WHERE p.approved = TRUE AND p.processed = FALSE
                ORDER BY p.estimated_score DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # =========== EPISODE SUMMARIES ===========

    async def save_episode_summary(
        self,
        video_id: str,
        main_topics: list[str],
        key_points: list[str],
        speakers_mentioned: list[str],
        overall_sentiment: str,
        one_liner: str
    ):
        """Save an episode summary."""
        import json
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO episode_summaries
                (video_id, main_topics, key_points, speakers_mentioned, overall_sentiment, one_liner)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                video_id,
                json.dumps(main_topics),
                json.dumps(key_points),
                json.dumps(speakers_mentioned),
                overall_sentiment,
                one_liner
            ))
            await db.commit()

    async def save_video_map(
        self,
        video_id: str,
        video_map_json: dict
    ):
        """Save a full video map (speaker-grounded notes) to the database."""
        import json
        async with aiosqlite.connect(self.db_path) as db:
            # Create table if not exists
            await db.execute("""
                CREATE TABLE IF NOT EXISTS video_maps (
                    video_id TEXT PRIMARY KEY,
                    video_map TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_id) REFERENCES videos(video_id)
                )
            """)

            await db.execute("""
                INSERT OR REPLACE INTO video_maps (video_id, video_map)
                VALUES (?, ?)
            """, (video_id, json.dumps(video_map_json)))
            await db.commit()

    async def get_video_map(self, video_id: str) -> Optional[dict]:
        """Get the video map for a video."""
        import json
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT video_map FROM video_maps WHERE video_id = ?",
                (video_id,)
            )
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

    async def get_episode_summary(self, video_id: str) -> Optional[dict]:
        """Get an episode summary."""
        import json
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM episode_summaries WHERE video_id = ?",
                (video_id,)
            )
            row = await cursor.fetchone()
            if row:
                data = dict(row)
                data['main_topics'] = json.loads(data['main_topics'])
                data['key_points'] = json.loads(data['key_points'])
                data['speakers_mentioned'] = json.loads(data['speakers_mentioned'])
                return data
            return None

    async def get_videos_needing_processing(self) -> list[dict]:
        """Get videos that are in the database but don't have clips yet."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT v.video_id, v.channel_name, v.title, v.description, v.published_at
                FROM videos v
                LEFT JOIN clips c ON v.video_id = c.video_id
                WHERE c.id IS NULL
                ORDER BY v.published_at DESC
            """)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_video_info(self, video_id: str) -> Optional[dict]:
        """Get video info from database."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM videos WHERE video_id = ?",
                (video_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    # === API Usage Tracking ===

    async def log_api_usage(self, api_name: str, endpoint: str, units: int = 1):
        """Log API usage for quota tracking."""
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO api_usage (date, api_name, endpoint, units_used) VALUES (?, ?, ?, ?)",
                (today, api_name, endpoint, units)
            )
            await db.commit()

    async def get_api_usage_today(self, api_name: str = "youtube") -> int:
        """Get total API units used today."""
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT SUM(units_used) FROM api_usage WHERE date = ? AND api_name = ?",
                (today, api_name)
            )
            result = await cursor.fetchone()
            return result[0] or 0

    async def get_api_usage_history(self, days: int = 7) -> list[dict]:
        """Get API usage history for the past N days."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT date, api_name, SUM(units_used) as total_units
                FROM api_usage
                WHERE date >= date('now', ?)
                GROUP BY date, api_name
                ORDER BY date DESC
            """, (f'-{days} days',))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # === Channel ID Cache ===

    async def get_cached_channel_id(self, youtube_handle: str) -> Optional[str]:
        """Get cached channel ID to avoid API calls."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT channel_id FROM channel_cache WHERE youtube_handle = ?",
                (youtube_handle,)
            )
            result = await cursor.fetchone()
            return result[0] if result else None

    async def cache_channel_id(self, youtube_handle: str, channel_id: str, channel_name: str):
        """Cache a channel ID for future use."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO channel_cache (youtube_handle, channel_id, channel_name, last_checked)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (youtube_handle, channel_id, channel_name))
            await db.commit()

    async def get_all_cached_channels(self) -> list[dict]:
        """Get all cached channel IDs."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM channel_cache")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # === Fetch History ===

    async def log_fetch(self, channel_name: str, videos_found: int):
        """Log a channel fetch for history."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO fetch_history (channel_name, videos_found) VALUES (?, ?)",
                (channel_name, videos_found)
            )
            await db.commit()

    async def get_fetch_history(self, limit: int = 50) -> list[dict]:
        """Get recent fetch history."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT channel_name, videos_found, fetched_at
                FROM fetch_history
                ORDER BY fetched_at DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# Singleton instance
database = Database()
