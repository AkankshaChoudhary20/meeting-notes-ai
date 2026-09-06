"""Application configuration, loaded from environment variables / .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root if present. Real env vars always win.
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://voiceapp:voiceapp@localhost:5432/voice_meeting_assistant",
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# faster-whisper model size. "base" is a good CPU-friendly default; "small"
# is more accurate but slower on CPU. Downloaded automatically on first use.
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# Where uploaded audio files are stored on disk.
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Claude model used to generate the summary + action items.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))  # 200 MB
