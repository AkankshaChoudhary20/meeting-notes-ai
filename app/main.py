"""Voice Meeting Assistant — FastAPI backend.

Pipeline for POST /meetings:
  1. Save the uploaded audio file to disk and insert a `meetings` row with
     status="processing". Respond immediately with the new meeting id.
  2. In a FastAPI BackgroundTask: transcribe the audio locally with
     faster-whisper (no network call), then send the transcript to the
     Claude API for a summary + structured action items, then write the
     transcript/summary/action_items/status back to Postgres.

This keeps the upload request fast while still doing the (slower) whisper +
Claude work outside the request/response cycle.
"""
import logging
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import ANTHROPIC_API_KEY, BASE_DIR, MAX_UPLOAD_BYTES, UPLOAD_DIR
from app.database import check_connection, dict_cursor, get_conn, init_pool
from app.llm import analyze_transcript
from app.schemas import (
    ActionItemOut,
    ActionItemUpdate,
    HealthResponse,
    MeetingCreateResponse,
    MeetingDetail,
    MeetingListItem,
)
from app.transcription import transcribe_audio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Voice Meeting Assistant",
    description=(
        "Upload a meeting recording, get a local transcript, an AI-generated "
        "summary, and structured action items."
    ),
    version="0.1.0",
)

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".mpeg", ".mpga"}


@app.on_event("startup")
def on_startup() -> None:
    try:
        init_pool()
    except Exception as exc:  # noqa: BLE001
        # Don't crash the app if Postgres isn't up yet — /health will report
        # it, and requests that need the DB will fail with a clear 503.
        logger.warning("Could not initialize the database pool at startup: %s", exc)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    db_ok = check_connection()
    return HealthResponse(status="ok", database="connected" if db_ok else "unreachable")


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------


def _process_meeting(meeting_id: int, file_path: str) -> None:
    """Background job: transcribe locally, then summarize via Claude."""
    try:
        logger.info("Meeting %s: starting transcription of %s", meeting_id, file_path)
        transcript = transcribe_audio(file_path)
        logger.info("Meeting %s: transcription complete (%d chars)", meeting_id, len(transcript))

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE meetings SET transcript = %s WHERE id = %s",
                    (transcript, meeting_id),
                )

        analysis = analyze_transcript(transcript)
        logger.info("Meeting %s: analysis complete", meeting_id)

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE meetings SET summary = %s, status = 'done' WHERE id = %s",
                    (analysis["summary"], meeting_id),
                )
                for item in analysis["action_items"]:
                    cur.execute(
                        "INSERT INTO action_items (meeting_id, description, owner) "
                        "VALUES (%s, %s, %s)",
                        (meeting_id, item["description"], item.get("owner")),
                    )
    except Exception as exc:  # noqa: BLE001 - background job must never crash the process
        logger.exception("Meeting %s: processing failed", meeting_id)
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE meetings SET status = 'failed', "
                        "summary = %s WHERE id = %s",
                        (f"Processing failed: {exc}", meeting_id),
                    )
        except Exception:  # noqa: BLE001
            logger.exception("Meeting %s: also failed to record the failure", meeting_id)


@app.post("/meetings", response_model=MeetingCreateResponse, status_code=201)
async def create_meeting(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Meeting audio file"),
    title: Optional[str] = Form(None),
) -> MeetingCreateResponse:
    if not ANTHROPIC_API_KEY:
        logger.warning(
            "ANTHROPIC_API_KEY is not set — transcription will still work, but "
            "summarization will fail and the meeting will be marked 'failed'."
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )

    safe_ext = ext if ext else ".wav"
    stored_filename = f"{uuid.uuid4().hex}{safe_ext}"
    dest_path = UPLOAD_DIR / stored_filename
    dest_path.write_bytes(contents)

    meeting_title = (title or "").strip() or (file.filename or "Untitled meeting")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO meetings (title, audio_filename, status) "
                    "VALUES (%s, %s, 'processing') RETURNING id",
                    (meeting_title, stored_filename),
                )
                meeting_id = cur.fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to remove unregistered meeting upload %s", dest_path)
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    background_tasks.add_task(_process_meeting, meeting_id, str(dest_path))

    return MeetingCreateResponse(id=meeting_id, title=meeting_title, status="processing")


@app.get("/meetings", response_model=List[MeetingListItem])
def list_meetings() -> List[MeetingListItem]:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                "SELECT id, title, created_at, status, audio_filename "
                "FROM meetings ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
    return [MeetingListItem(**row) for row in rows]


@app.get("/meetings/{meeting_id}", response_model=MeetingDetail)
def get_meeting(meeting_id: int) -> MeetingDetail:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                "SELECT id, title, created_at, status, audio_filename, transcript, summary "
                "FROM meetings WHERE id = %s",
                (meeting_id,),
            )
            meeting = cur.fetchone()
            if meeting is None:
                raise HTTPException(status_code=404, detail="Meeting not found")

            cur.execute(
                "SELECT id, meeting_id, description, owner, done "
                "FROM action_items WHERE meeting_id = %s ORDER BY id",
                (meeting_id,),
            )
            action_items = cur.fetchall()

    return MeetingDetail(
        **meeting,
        action_items=[ActionItemOut(**item) for item in action_items],
    )


# ---------------------------------------------------------------------------
# Action items
# ---------------------------------------------------------------------------


@app.patch("/action_items/{item_id}", response_model=ActionItemOut)
def update_action_item(item_id: int, update: ActionItemUpdate) -> ActionItemOut:
    fields = update.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{col} = %s" for col in fields)
    values = list(fields.values()) + [item_id]

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                f"UPDATE action_items SET {set_clause} WHERE id = %s "
                f"RETURNING id, meeting_id, description, owner, done",
                values,
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Action item not found")

    return ActionItemOut(**row)


# ---------------------------------------------------------------------------
# Static dashboard
# ---------------------------------------------------------------------------

STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_dashboard() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))
