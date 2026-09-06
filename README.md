# Voice Meeting Assistant

Upload a meeting recording and get back a transcript, an AI-generated summary, and a
structured list of action items you can check off — all through a small FastAPI backend
with a zero-build-step HTML/JS dashboard.

Speech-to-text runs **entirely locally and offline** (via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) /
CTranslate2 — no audio ever leaves your machine, no API key required for transcription).
Only the plain-text transcript is sent out, to the Claude API, for the summary and
action-item extraction step.

## Architecture

```
                 ┌──────────────────────┐
   audio file    │      FastAPI          │
  ───────────▶   │  POST /meetings       │──▶ saves file, inserts `meetings`
                 │  (returns immediately)│    row with status="processing"
                 └──────────┬───────────┘
                            │ BackgroundTasks
                            ▼
                 ┌──────────────────────┐
                 │  faster-whisper       │  local, offline, CPU-friendly
                 │  (transcription)      │  (downloads model on first run)
                 └──────────┬───────────┘
                            │ transcript (text)
                            ▼
                 ┌──────────────────────┐
                 │  Claude API           │  cloud call — text only, never audio
                 │  (summary + actions)  │  structured JSON output
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │      Postgres         │  meetings + action_items
                 └──────────────────────┘
                            ▲
                 ┌──────────┴───────────┐
                 │  Static dashboard     │  plain HTML/JS, no build step,
                 │  served at  /         │  polls GET /meetings while
                 └──────────────────────┘  processing
```

`POST /meetings` responds as soon as the file is saved and the DB row is created
(`status: "processing"`) — transcription and summarization happen afterwards in a FastAPI
`BackgroundTask`, and the dashboard polls the meeting until it flips to `done` (or `failed`).

### Why local transcription?

No per-minute transcription API costs, no audio uploaded to a third party, and it keeps
working if you're offline. The only network call in the whole pipeline is the (text-only)
summarization request to Claude.

## Stack

- **Backend:** FastAPI + Uvicorn
- **Database:** Postgres 16 (via Docker Compose), accessed with `psycopg` v3
- **Transcription:** `faster-whisper` (CTranslate2 + Whisper `base` model by default, runs on CPU)
- **Summarization / action items:** Anthropic Claude API (`claude-sonnet-5`), using
  [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
  so the response is guaranteed valid JSON — no fragile prompt-based parsing
- **Frontend:** a single static `index.html` with vanilla JS — no npm, no build step

## Endpoints

| Method | Path                     | Description                                                        |
|--------|--------------------------|----------------------------------------------------------------------|
| GET    | `/`                      | Serves the dashboard                                                |
| GET    | `/health`                | Liveness + DB connectivity check                                    |
| POST   | `/meetings`              | Multipart upload: `file` (audio) + optional `title`. Returns immediately with `status: "processing"`; transcription + summarization run in the background |
| GET    | `/meetings`              | List all meetings (id, title, created_at, status)                   |
| GET    | `/meetings/{id}`         | Full detail: transcript, summary, action items                      |
| PATCH  | `/action_items/{id}`     | Update `done` and/or `owner` on an action item                      |

## Setup

### 1. Start Postgres

```bash
docker compose up -d
```

This starts Postgres 16 on `localhost:5432` and automatically runs
`init-db/init.sql`, which creates the `meetings` and `action_items` tables.

> Port already taken? Override it: `POSTGRES_PORT=5433 docker compose up -d` and set
> `DATABASE_URL` accordingly in your `.env`.

### 2. Set up the Python environment

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Then edit `.env`:

- `ANTHROPIC_API_KEY` — get one at https://console.anthropic.com/settings/keys.
  Transcription works without it; without a key, uploads will still transcribe locally but
  the summarization step will fail and the meeting will be marked `status: "failed"` with a
  clear error message (rather than crashing the app).
- `DATABASE_URL` — defaults to the docker-compose Postgres above; change it if you're
  pointing at a different database.

### 4. Run the API

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000 for the dashboard, or http://localhost:8000/docs for the
interactive API docs (Swagger UI, generated automatically by FastAPI).

> **First run note:** the first time you upload a file, `faster-whisper` downloads the
> Whisper model weights (from Hugging Face, cached under `~/.cache/huggingface`) — this can
> take anywhere from a few seconds to a couple of minutes depending on your connection and
> the model size. Every upload after that is fast, since the model stays loaded in memory
> for the life of the process.

## Example: upload a meeting via curl

```bash
curl -X POST http://localhost:8000/meetings \
  -F "file=@/path/to/meeting.wav" \
  -F "title=Weekly sync"
```

```json
{"id": 1, "title": "Weekly sync", "status": "processing"}
```

Poll for the result:

```bash
curl http://localhost:8000/meetings/1
```

```json
{
  "id": 1,
  "title": "Weekly sync",
  "created_at": "2026-09-06T05:52:47Z",
  "status": "done",
  "audio_filename": "3981a9f3c9ff4fde8d3d786c679ce900.wav",
  "transcript": "Hi team, quick sync on the launch...",
  "summary": "The team discussed launch readiness...",
  "action_items": [
    {"id": 1, "meeting_id": 1, "description": "Finalize the pricing page", "owner": "Sarah", "done": false}
  ]
}
```

Mark an action item done:

```bash
curl -X PATCH http://localhost:8000/action_items/1 \
  -H "Content-Type: application/json" \
  -d '{"done": true}'
```

## Configuration reference

All settings live in `.env` (see `.env.example`):

| Variable              | Default                                                          | Notes                                              |
|-----------------------|-------------------------------------------------------------------|-----------------------------------------------------|
| `ANTHROPIC_API_KEY`   | *(empty)*                                                         | Required for summarization; transcription works without it |
| `DATABASE_URL`        | `postgresql://voiceapp:voiceapp@localhost:5432/voice_meeting_assistant` | |
| `WHISPER_MODEL_SIZE`  | `base`                                                            | `tiny`, `base`, `small`, `medium`, `large-v3` — bigger = more accurate, slower on CPU |
| `WHISPER_DEVICE`      | `cpu`                                                             | Set to `cuda` if you have a GPU + CUDA available     |
| `WHISPER_COMPUTE_TYPE`| `int8`                                                            | Quantization; `int8` is the fastest CPU-friendly option |
| `CLAUDE_MODEL`        | `claude-sonnet-5`                                              | |
| `UPLOAD_DIR`          | `uploads`                                                         | Where uploaded audio files are stored on disk        |
| `MAX_UPLOAD_BYTES`    | `209715200` (200 MB)                                              | |

## What was and wasn't tested end-to-end

This project was built and verified in a sandboxed dev environment:

- ✅ App imports cleanly and boots with `uvicorn` (no syntax/import errors).
- ✅ Postgres brought up via `docker compose up -d`; `init.sql` creates both tables correctly.
- ✅ Full pipeline tested with a **real audio file** (WAV generated via macOS `say`):
  upload → local faster-whisper transcription (including the on-first-run model download)
  → transcript stored in Postgres. The transcript came back accurate.
- ✅ `GET /meetings`, `GET /meetings/{id}`, `PATCH /action_items/{id}` (including the 404
  case) all verified against the live database.
- ✅ The Claude API request shape (model, `output_config` with a JSON schema, system +
  user messages) was verified to reach the API correctly (confirmed via a clean 401 with a
  dummy key, rather than a client-side error) — but the actual summarization response was
  **not** verified against a real Claude API key, since no `ANTHROPIC_API_KEY` was available
  in the build environment. With a valid key, this is a standard Messages API call and
  should work as shown; if the JSON schema or response parsing needs adjustment, look at
  `app/llm.py`.
- ⚠️ The dashboard's JS/HTML was reviewed carefully but not click-tested in an actual
  browser — no interactive browser was available in the build environment.

## Project layout

```
app/
  main.py            FastAPI app, endpoints, background processing job
  config.py          Environment-variable configuration
  database.py        Postgres connection pool (psycopg 3)
  schemas.py         Pydantic request/response models
  transcription.py   faster-whisper wrapper (local, offline)
  llm.py             Claude API call for summary + action items
static/
  index.html         Dashboard (vanilla HTML/JS, no build step)
init-db/
  init.sql           Schema: meetings, action_items
docker-compose.yml   Postgres 16
requirements.txt
.env.example
```
