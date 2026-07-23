-- Deep Clip Search — schema (master doc C2)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

CREATE TABLE IF NOT EXISTS videos (
  id              TEXT PRIMARY KEY,       -- yt video id / ig shortcode
  source          TEXT NOT NULL,          -- 'youtube'|'youtube_shorts'|'instagram'|'tiktok'
  title           TEXT,
  channel_id      TEXT,
  channel_name    TEXT,
  duration_s      INT,
  published_at    TIMESTAMPTZ,
  view_count      BIGINT,
  like_count      BIGINT,
  transcript_kind TEXT,                   -- 'manual'|'auto'|'whisper'|NULL
  lang            TEXT,
  credibility     REAL DEFAULT 0.5,       -- channel-level (Learn Mode)
  ingested_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS videos_channel_idx ON videos (channel_id);
CREATE INDEX IF NOT EXISTS videos_source_idx  ON videos (source);

CREATE TABLE IF NOT EXISTS segments (
  id        BIGSERIAL PRIMARY KEY,
  video_id  TEXT REFERENCES videos(id) ON DELETE CASCADE,
  t_start   REAL NOT NULL,
  t_end     REAL NOT NULL,
  text      TEXT NOT NULL,
  embedding VECTOR(1024),
  vis_tags  JSONB,                        -- {'archival':0.9,...} (post-MVP, stage 8)
  quality   REAL,                         -- explanation-quality 0-1 (Learn)
  intensity REAL                          -- moment-intensity 0-1 (Entertain)
);
CREATE INDEX IF NOT EXISTS segments_embedding_idx
  ON segments USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS segments_video_idx ON segments (video_id);

CREATE TABLE IF NOT EXISTS deep_pages (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  query_norm     TEXT UNIQUE,
  mode           TEXT NOT NULL DEFAULT 'learn',   -- 'learn'|'entertain'
  outline        JSONB,
  page           JSONB,
  status         TEXT,                            -- 'building'|'ready'|'failed'
  built_at       TIMESTAMPTZ,
  build_cost_usd REAL
);

CREATE TABLE IF NOT EXISTS learning_paths (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seed_url      TEXT,
  seed_analysis JSONB,                    -- topic/subtopic/depth or vibe
  page          JSONB,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- quota protection (C2 / stage 2 mitigation b)
CREATE TABLE IF NOT EXISTS hint_cache (
  hint       TEXT PRIMARY KEY,
  video_ids  TEXT[],
  fetched_at TIMESTAMPTZ DEFAULT now()
);

-- Analytics (master doc D4/D8): the go/no-go metric is "do users finish pages
-- and come back?". None of that is answerable without recording it. Append-only
-- event log. anon_id is a client-generated UUID stored in localStorage, never a
-- real identity -- no login is required to measure completion and return.
CREATE TABLE IF NOT EXISTS events (
  id          BIGSERIAL PRIMARY KEY,
  anon_id     TEXT NOT NULL,
  session_id  TEXT NOT NULL,
  kind        TEXT NOT NULL,
  slug        TEXT,
  mode        TEXT,
  video_id    TEXT,
  position    INT,
  value       REAL,
  meta        JSONB,
  created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_slug_idx ON events (slug, created_at);
CREATE INDEX IF NOT EXISTS events_kind_idx ON events (kind, created_at);
CREATE INDEX IF NOT EXISTS events_anon_idx ON events (anon_id, created_at);

-- Saved pages (master doc D3, Pro tier). Keyed by anon_id (localStorage UUID),
-- so saving works with no login -- accounts can attach to an anon_id later
-- without migrating data. A user cannot save the same page twice (PK).
CREATE TABLE IF NOT EXISTS saved_pages (
  anon_id   TEXT NOT NULL,
  slug      TEXT NOT NULL,
  mode      TEXT,
  title     TEXT,
  saved_at  TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (anon_id, slug)
);
CREATE INDEX IF NOT EXISTS saved_pages_anon_idx ON saved_pages (anon_id, saved_at DESC);

-- Perspective streams (research/perspective-streams.md). A user-authored,
-- ordered collection of real clips expressing a viewpoint, shareable by link.
-- Always attributed as a personal perspective in the UI -- never objective truth.
CREATE TABLE IF NOT EXISTS streams (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  anon_id    TEXT NOT NULL,
  title      TEXT NOT NULL,
  stance     TEXT,
  is_public  BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS streams_anon_idx ON streams (anon_id, created_at DESC);

CREATE TABLE IF NOT EXISTS stream_clips (
  stream_id    UUID REFERENCES streams(id) ON DELETE CASCADE,
  position     INT NOT NULL,
  video_id     TEXT NOT NULL,
  t_start      REAL NOT NULL,
  t_end        REAL NOT NULL,
  note         TEXT,
  channel      TEXT,
  video_title  TEXT,
  PRIMARY KEY (stream_id, position)
);
