-- Achievist schema. Multi-user, cross-platform achievement aggregator.
-- Idempotent: safe to run on every startup.

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    display_name    TEXT,
    avatar_url      TEXT,
    is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS linked_accounts (
    id              SERIAL PRIMARY KEY,
    platform        TEXT NOT NULL,
    external_id     TEXT NOT NULL,          -- steamid64, RA username, psn account id, etc.
    display_name    TEXT,
    enabled         BOOLEAN DEFAULT TRUE,
    credentials     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- per-account secrets/config (api keys, tokens, region)
    status          TEXT DEFAULT 'connected',            -- connected | error
    last_error      TEXT,
    last_synced_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (platform, external_id)
);
-- safe migrations for existing deployments
ALTER TABLE linked_accounts ADD COLUMN IF NOT EXISTS credentials JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE linked_accounts ADD COLUMN IF NOT EXISTS status      TEXT DEFAULT 'connected';
ALTER TABLE linked_accounts ADD COLUMN IF NOT EXISTS last_error  TEXT;

-- Multi-user (in progress — see app/main.py's Auth section docstring):
-- each linked account will belong to exactly one user rather than being
-- shared globally. The column is added now, nullable and unused by any
-- query yet, so this migration is safe to ship independently. The
-- (platform, external_id) unique constraint above is deliberately left
-- alone for now: swapping it to (user_id, platform, external_id) has to
-- land together with the db.py call-site changes that supply a real
-- user_id (upsert_linked_account/upsert_account's ON CONFLICT targets),
-- not before — doing it here would break every existing "connect account"
-- call immediately, since ON CONFLICT must match a real constraint.
ALTER TABLE linked_accounts ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE CASCADE;

-- This app supports one account per platform, but the (platform, external_id)
-- unique constraint above didn't prevent orphaned duplicates from piling up
-- when a reconnect resolved to a different external_id. Keep only the most
-- recently created row per platform.
DELETE FROM linked_accounts a
USING linked_accounts b
WHERE a.platform = b.platform AND a.id < b.id;

CREATE TABLE IF NOT EXISTS igdb_games (
    id                  BIGINT PRIMARY KEY,  -- IGDB id
    name                TEXT NOT NULL,
    slug                TEXT,
    cover_url           TEXT,
    first_release_date  DATE
);

CREATE TABLE IF NOT EXISTS platform_games (
    id                  SERIAL PRIMARY KEY,
    platform            TEXT NOT NULL,
    platform_app_id     TEXT NOT NULL,       -- steam appid, RA game id, np comm id
    name                TEXT NOT NULL,
    icon_url            TEXT,
    igdb_id             BIGINT REFERENCES igdb_games(id),
    total_achievements  INT DEFAULT 0,
    hltb_main           NUMERIC,             -- How Long To Beat: main story hours
    hltb_extra          NUMERIC,             -- main + extras hours
    hltb_complete       NUMERIC,             -- completionist hours
    UNIQUE (platform, platform_app_id)
);
-- safe migrations for existing deployments
ALTER TABLE platform_games ADD COLUMN IF NOT EXISTS hltb_main     NUMERIC;
ALTER TABLE platform_games ADD COLUMN IF NOT EXISTS hltb_extra    NUMERIC;
ALTER TABLE platform_games ADD COLUMN IF NOT EXISTS hltb_complete NUMERIC;
ALTER TABLE platform_games ADD COLUMN IF NOT EXISTS igdb_id       BIGINT REFERENCES igdb_games(id);
ALTER TABLE platform_games ADD COLUMN IF NOT EXISTS store_id      TEXT;
ALTER TABLE platform_games ADD COLUMN IF NOT EXISTS xbox_pfn      TEXT;
ALTER TABLE platform_games ADD COLUMN IF NOT EXISTS sgdb_cover_url TEXT;
-- Clear previously stored store_ids so the improved title-match check re-validates them
UPDATE platform_games SET store_id = NULL WHERE platform = 'xbox' AND store_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS achievements (
    id                  SERIAL PRIMARY KEY,
    platform_game_id    INT NOT NULL REFERENCES platform_games(id) ON DELETE CASCADE,
    platform_ach_id     TEXT NOT NULL,       -- steam apiname, RA achievement id
    name                TEXT,
    description         TEXT,
    icon_url            TEXT,
    points              INT,                 -- gamerscore / RA points / trophy weight
    rarity_pct          NUMERIC,             -- global unlock percentage
    UNIQUE (platform_game_id, platform_ach_id)
);

CREATE TABLE IF NOT EXISTS user_achievements (
    id                  SERIAL PRIMARY KEY,
    linked_account_id   INT NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    achievement_id      INT NOT NULL REFERENCES achievements(id) ON DELETE CASCADE,
    unlocked            BOOLEAN DEFAULT FALSE,
    unlocked_at         TIMESTAMPTZ,
    UNIQUE (linked_account_id, achievement_id)
);

CREATE TABLE IF NOT EXISTS user_games (
    id                  SERIAL PRIMARY KEY,
    linked_account_id   INT NOT NULL REFERENCES linked_accounts(id) ON DELETE CASCADE,
    platform_game_id    INT NOT NULL REFERENCES platform_games(id) ON DELETE CASCADE,
    playtime_minutes    INT,
    earned_achievements INT DEFAULT 0,
    total_achievements  INT DEFAULT 0,
    completion_pct      NUMERIC DEFAULT 0,
    last_played_at      TIMESTAMPTZ,
    UNIQUE (linked_account_id, platform_game_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id                  SERIAL PRIMARY KEY,
    platform            TEXT,
    linked_account_id   INT REFERENCES linked_accounts(id) ON DELETE SET NULL,
    started_at          TIMESTAMPTZ DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    status              TEXT,
    detail              TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_games_account ON user_games(linked_account_id);
CREATE INDEX IF NOT EXISTS idx_user_ach_account ON user_achievements(linked_account_id);
CREATE INDEX IF NOT EXISTS idx_platform_games_igdb ON platform_games(igdb_id);

-- Legacy single-row profile from before multi-user support. No longer
-- written to by the app (display_name/avatar_url now live on users) — kept
-- only so app.db.migrate_single_user_to_admin() can read this deployment's
-- pre-existing profile into the new admin user it creates on first boot.
CREATE TABLE IF NOT EXISTS profile (
    id              INT PRIMARY KEY DEFAULT 1,
    display_name    TEXT,
    avatar_url      TEXT,
    CHECK (id = 1)
);
INSERT INTO profile (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
