-- Permanent case records.
-- Safe to run more than once: nothing is created twice and nothing is deleted.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per child.
CREATE TABLE IF NOT EXISTS cases (
    id              TEXT PRIMARY KEY,             -- case_uuid, report_id, or upload_id#row
    channel         TEXT NOT NULL CHECK (channel IN ('field', 'helpline', 'upload')),
    source_id       TEXT,                         -- the submission, call or upload it came from
    region          TEXT,
    district        TEXT,
    community       TEXT,
    child_name      TEXT,                         -- kept for follow-up visits only; never sent to the model
    status          TEXT NOT NULL,                -- assessed, not_scored_..., human_review, could_not_assess, needs_transcription
    score           INTEGER,
    band            TEXT CHECK (band IN ('No risk', 'Low', 'Moderate', 'High')),
    alert           BOOLEAN NOT NULL DEFAULT FALSE,
    urgent_reasons  TEXT[] NOT NULL DEFAULT '{}',
    flags           TEXT[] NOT NULL DEFAULT '{}',
    summary         TEXT,                         -- written by the model, for officers; never used for scoring
    masked_text     TEXT,                         -- the text the model read, with names and phones masked
    original_key    TEXT,                         -- where the untouched original is kept (MinIO)
    received_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cases_region_band ON cases (region, band);

-- One row per indicator found: the evidence behind the band.
CREATE TABLE IF NOT EXISTS indicators (
    id          SERIAL PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    indicator   INTEGER NOT NULL CHECK (indicator BETWEEN 1 AND 10),
    subtype     TEXT CHECK (subtype IN ('a', 'b')),
    source      TEXT NOT NULL,                    -- answers, report, both, ...
    quote       TEXT,
    observed    BOOLEAN NOT NULL DEFAULT FALSE    -- found but not scored (refused interview, human review)
);
CREATE INDEX IF NOT EXISTS indicators_case ON indicators (case_id);

-- Pieces of masked text with their vectors, searched in Stage 7.
CREATE TABLE IF NOT EXISTS chunks (
    id           SERIAL PRIMARY KEY,
    case_id      TEXT REFERENCES cases (id) ON DELETE CASCADE,   -- NULL for policy documents
    source_type  TEXT NOT NULL CHECK (source_type IN ('case', 'policy')),
    document     TEXT NOT NULL,
    section      TEXT,
    region       TEXT,
    text         TEXT NOT NULL,
    embedding    vector(768)
);
CREATE INDEX IF NOT EXISTS chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);

-- One row per alert. It stays open until a person confirms it (Stage 6).
CREATE TABLE IF NOT EXISTS alerts (
    id                SERIAL PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    reasons           TEXT[] NOT NULL,
    status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'confirmed')),
    escalation_level  INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_by      TEXT,
    confirmed_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS alerts_open ON alerts (status) WHERE status = 'open';
