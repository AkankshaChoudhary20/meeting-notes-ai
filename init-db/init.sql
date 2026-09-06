-- Voice Meeting Assistant — database schema
-- Applied automatically by the postgres container on first startup
-- (mounted into /docker-entrypoint-initdb.d/ via docker-compose.yml)

CREATE TABLE IF NOT EXISTS meetings (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT 'Untitled meeting',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    audio_filename  TEXT,
    transcript      TEXT,
    summary         TEXT,
    status          TEXT NOT NULL DEFAULT 'processing'
                        CHECK (status IN ('processing', 'done', 'failed'))
);

CREATE TABLE IF NOT EXISTS action_items (
    id              SERIAL PRIMARY KEY,
    meeting_id      INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    description     TEXT NOT NULL,
    owner           TEXT,
    done            BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_action_items_meeting_id ON action_items(meeting_id);
CREATE INDEX IF NOT EXISTS idx_meetings_created_at ON meetings(created_at DESC);
