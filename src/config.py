import os
import json
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional

# Load environment variables
load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
CLIPS_DIR = DATA_DIR / "clips"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
DB_PATH = DATA_DIR / "podcast_clipper.db"

# Create directories if they don't exist
for dir_path in [DATA_DIR, CLIPS_DIR, TRANSCRIPTS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # YouTube
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")

    # Ollama
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    # App settings
    CHECK_INTERVAL_HOURS: int = int(os.getenv("CHECK_INTERVAL_HOURS", "1"))
    DAILY_REPORT_TIME: str = os.getenv("DAILY_REPORT_TIME", "09:00")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")
    MAX_CLIP_DURATION_SECONDS: int = int(os.getenv("MAX_CLIP_DURATION_SECONDS", "120"))
    CANDIDATES_PER_DAY: int = int(os.getenv("CANDIDATES_PER_DAY", "10"))

    # Batch delivery settings
    CANDIDATES_PER_BATCH: int = int(os.getenv("CANDIDATES_PER_BATCH", "5"))
    BATCHES_PER_DAY: int = int(os.getenv("BATCHES_PER_DAY", "4"))
    BATCH_TIMES: str = os.getenv("BATCH_TIMES", "09:00,13:00,17:00,21:00")
    WEEKLY_BACKUP_COUNT: int = int(os.getenv("WEEKLY_BACKUP_COUNT", "10"))

    @classmethod
    def load_channels(cls) -> list[dict]:
        """Load channel configuration from JSON file."""
        channels_file = CONFIG_DIR / "channels.json"
        with open(channels_file, "r") as f:
            data = json.load(f)
        return data["channels"]

    @classmethod
    def load_voice_profile(cls) -> dict:
        """Load voice profile configuration from JSON file."""
        voice_file = CONFIG_DIR / "voice_profile.json"
        with open(voice_file, "r") as f:
            return json.load(f)


config = Config()
