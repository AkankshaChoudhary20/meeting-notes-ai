"""Local, offline speech-to-text using faster-whisper.

No API key and no network call is needed for transcription — everything
runs on-device with CTranslate2. The model weights are downloaded once (from
Hugging Face) the first time transcribe() is called and then cached under
~/.cache/huggingface, so the very first transcription in a fresh environment
will take longer while the model downloads.
"""
import logging
import threading
from typing import Optional

from faster_whisper import WhisperModel

from app.config import WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL_SIZE

logger = logging.getLogger(__name__)

_model: Optional[WhisperModel] = None
_model_lock = threading.Lock()


def get_model() -> WhisperModel:
    """Lazily load (and cache) the whisper model, once per process."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                logger.info(
                    "Loading faster-whisper model '%s' (device=%s, compute_type=%s) "
                    "— this downloads the model on first run and may take a while.",
                    WHISPER_MODEL_SIZE,
                    WHISPER_DEVICE,
                    WHISPER_COMPUTE_TYPE,
                )
                _model = WhisperModel(
                    WHISPER_MODEL_SIZE,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                )
                logger.info("faster-whisper model loaded")
    return _model


def transcribe_audio(file_path: str) -> str:
    """Transcribe an audio file on disk and return the full text transcript."""
    model = get_model()
    segments, info = model.transcribe(file_path, beam_size=5, vad_filter=True)
    logger.info(
        "Transcribing %s: detected language=%s (p=%.2f)",
        file_path,
        info.language,
        info.language_probability,
    )
    text_parts = [segment.text.strip() for segment in segments]
    transcript = " ".join(part for part in text_parts if part)
    return transcript.strip()
