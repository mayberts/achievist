import asyncio
from pathlib import Path

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import config

_pool: AsyncConnectionPool | None = None


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            config.DATABASE_URL,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        await _pool.open()
    return _pool


async def apply_schema(pool: AsyncConnectionPool) -> None:
    schema = Path("schema.sql").read_text()
    async with pool.connection() as conn:
        await conn.execute(schema)


async def migrate_single_user_to_admin(pool: AsyncConnectionPool) -> str | None:
    """
    One-time migration for deployments that predate multi-user support: if
    there's pre-existing linked_accounts/profile data but no users yet,
    create an admin user, attach all existing data to it, and return the
    freshly generated password (only non-None the run this actually
    happens) so it can be surfaced to the operator via logs. A fresh install
    with no prior data returns None — first-run setup handles that case via
    the /api/setup endpoint instead.
    """
    from app.auth import hash_password
    import secrets

    async with pool.connection() as conn:
        existing = await _fetchrow(conn, "SELECT COUNT(*) AS n FROM users")
        if existing["n"] > 0:
            return None

        has_data = await _fetchrow(
            conn,
            "SELECT (EXISTS (SELECT 1 FROM linked_accounts) OR "
            "EXISTS (SELECT 1 FROM profile WHERE display_name IS NOT NULL OR avatar_url IS NOT NULL)) AS has_data"
        )
        if not has_data["has_data"]:
            return None

        profile_row = await _fetchrow(conn, "SELECT display_name, avatar_url FROM profile WHERE id = 1")
        password = secrets.token_urlsafe(12)
        user = await _fetchrow(
            conn,
            "INSERT INTO users (username, password_hash, display_name, avatar_url, is_admin) "
            "VALUES ('admin', %s, %s, %s, TRUE) RETURNING id",
            hash_password(password),
            profile_row["display_name"] if profile_row else None,
            profile_row["avatar_url"] if profile_row else None,
        )
        await conn.execute("UPDATE linked_accounts SET user_id = %s WHERE user_id IS NULL", (user["id"],))
        return password


# ── Users & sessions ──────────────────────────────────────────────────────

async def count_users(conn) -> int:
    row = await _fetchrow(conn, "SELECT COUNT(*) AS n FROM users")
    return row["n"]


async def create_user(
    conn, username: str, password_hash: str, display_name: str | None = None,
    avatar_url: str | None = None, is_admin: bool = False,
) -> dict:
    return await _fetchrow(
        conn,
        "INSERT INTO users (username, password_hash, display_name, avatar_url, is_admin) "
        "VALUES (%s, %s, %s, %s, %s) "
        "RETURNING id, username, display_name, avatar_url, is_admin, created_at",
        username, password_hash, display_name, avatar_url, is_admin,
    )


async def get_user_by_username(conn, username: str) -> dict | None:
    return await _fetchrow(conn, "SELECT * FROM users WHERE username = %s", username)


async def get_user_by_id(conn, user_id: int) -> dict | None:
    return await _fetchrow(conn, "SELECT * FROM users WHERE id = %s", user_id)


async def list_users(conn) -> list[dict]:
    return await _fetch(
        conn,
        "SELECT id, username, display_name, avatar_url, is_admin, share_stats, created_at FROM users ORDER BY id",
    )


async def update_user_profile(
    conn, user_id: int, display_name: str | None, avatar_url: str | None, share_stats: bool,
    background_url: str | None = None,
) -> None:
    await conn.execute(
        "UPDATE users SET display_name = %s, avatar_url = %s, share_stats = %s, background_url = %s WHERE id = %s",
        (display_name, avatar_url, share_stats, background_url, user_id),
    )


async def update_user_password(conn, user_id: int, password_hash: str) -> None:
    await conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))


async def delete_user(conn, user_id: int) -> None:
    await conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


# Points-per-rarity-tier for "Achievist Points" — a platform-agnostic score
# so the leaderboard isn't just whoever plays the platform with the
# biggest native point scale (Gamerscore vs. RA points vs. none at all for
# Steam). Tier boundaries mirror frontend/src/lib/rarity.ts exactly.
async def get_leaderboard(conn, requesting_user_id: int) -> list[dict]:
    """
    Achievist Points + raw stats per user who has opted in via
    users.share_stats — plus the requesting user themself even if they
    haven't opted in, so they can always see their own row.
    """
    return await _fetch(
        conn,
        """
        WITH ach_stats AS (
            SELECT
                la.user_id,
                COUNT(*) AS achievements_unlocked,
                SUM(
                    CASE
                        WHEN a.rarity_pct IS NULL  THEN 15
                        WHEN a.rarity_pct <= 1     THEN 200
                        WHEN a.rarity_pct <= 5     THEN 100
                        WHEN a.rarity_pct <= 20    THEN 50
                        WHEN a.rarity_pct <= 50    THEN 25
                        ELSE 10
                    END
                ) AS achievist_points
            FROM user_achievements ua
            JOIN linked_accounts la ON la.id = ua.linked_account_id
            JOIN achievements a ON a.id = ua.achievement_id
            WHERE ua.unlocked = true
            GROUP BY la.user_id
        ),
        game_stats AS (
            SELECT
                la.user_id,
                COUNT(DISTINCT ug.platform_game_id) AS games_played,
                COUNT(DISTINCT ug.platform_game_id) FILTER (
                    WHERE ug.total_achievements > 0 AND ug.completion_pct >= 100
                ) AS games_completed
            FROM user_games ug
            JOIN linked_accounts la ON la.id = ug.linked_account_id
            GROUP BY la.user_id
        )
        SELECT
            u.id AS user_id,
            u.username,
            u.display_name,
            u.avatar_url,
            COALESCE(ach.achievist_points, 0) AS achievist_points,
            COALESCE(ach.achievements_unlocked, 0) AS achievements_unlocked,
            COALESCE(g.games_played, 0) AS games_played,
            COALESCE(g.games_completed, 0) AS games_completed
        FROM users u
        LEFT JOIN ach_stats ach ON ach.user_id = u.id
        LEFT JOIN game_stats g ON g.user_id = u.id
        WHERE u.share_stats = true OR u.id = %s
        ORDER BY achievist_points DESC
        """,
        requesting_user_id,
    )


async def get_shared_games(conn, requesting_user_id: int) -> list[dict]:
    """
    Games owned by two or more "visible" users (opted-in via share_stats,
    plus the requester themself), each with every visible owner's progress
    on it — for a family "who's ahead on this one" comparison. Matched by
    platform_game_id (same platform + same app id), not igdb_id, since
    igdb_id isn't populated for every game and an exact platform-game match
    is unambiguous; cross-platform copies of the same game (e.g. Steam vs.
    Xbox) show as separate rows.
    """
    return await _fetch(
        conn,
        """
        WITH visible AS (
            SELECT id FROM users WHERE share_stats = true OR id = %s
        ),
        per_user_game AS (
            SELECT
                ug.platform_game_id,
                la.user_id,
                u.username,
                u.display_name,
                u.avatar_url,
                ug.earned_achievements,
                ug.total_achievements,
                ug.completion_pct
            FROM user_games ug
            JOIN linked_accounts la ON la.id = ug.linked_account_id
            JOIN visible v ON v.id = la.user_id
            JOIN users u ON u.id = la.user_id
        )
        SELECT
            pg.id AS platform_game_id,
            pg.platform,
            pg.name,
            pg.icon_url,
            pg.sgdb_cover_url,
            json_agg(
                json_build_object(
                    'user_id', pug.user_id,
                    'username', pug.username,
                    'display_name', pug.display_name,
                    'avatar_url', pug.avatar_url,
                    'earned', pug.earned_achievements,
                    'total', pug.total_achievements,
                    'completion_pct', pug.completion_pct
                ) ORDER BY pug.completion_pct DESC NULLS LAST
            ) AS players
        FROM per_user_game pug
        JOIN platform_games pg ON pg.id = pug.platform_game_id
        GROUP BY pg.id, pg.platform, pg.name, pg.icon_url, pg.sgdb_cover_url
        HAVING COUNT(DISTINCT pug.user_id) >= 2
        ORDER BY pg.name
        """,
        requesting_user_id,
    )


async def get_game_comparison(conn, requesting_user_id: int, platform_game_id: int) -> dict | None:
    """
    Achievement-by-achievement comparison for one game, across every
    "visible" user (opted-in via share_stats, plus the requester) who owns
    it. Returns None if the requester themself doesn't own this game — a
    comparison of a game you don't have makes no sense, and doubles as an
    access check so a user_id can't be used to snoop on games they've never
    touched.
    """
    game = await _fetchrow(
        conn,
        "SELECT id, platform, name, icon_url, sgdb_cover_url, guide_url FROM platform_games WHERE id = %s",
        platform_game_id,
    )
    if not game:
        return None

    owners = await _fetch(
        conn,
        """
        SELECT DISTINCT la.user_id, u.username, u.display_name, u.avatar_url
        FROM user_games ug
        JOIN linked_accounts la ON la.id = ug.linked_account_id
        JOIN users u ON u.id = la.user_id
        WHERE ug.platform_game_id = %s AND (u.share_stats = true OR u.id = %s)
        ORDER BY la.user_id
        """,
        platform_game_id, requesting_user_id,
    )
    if not any(o["user_id"] == requesting_user_id for o in owners):
        return None

    achievements = await _fetch(
        conn,
        """
        SELECT
            a.id, a.platform_ach_id, a.name, a.description, a.icon_url,
            a.points, a.rarity_pct, a.guide_url,
            json_agg(
                json_build_object(
                    'user_id', o.user_id,
                    'unlocked', COALESCE(ua.unlocked, false),
                    'unlocked_at', ua.unlocked_at
                ) ORDER BY o.user_id
            ) AS per_user
        FROM achievements a
        -- linked_account_id (not just user_id) here so a user with accounts
        -- on multiple platforms only matches their account *for this game's
        -- platform*, not any unlock rows from an unrelated platform account.
        CROSS JOIN (
            SELECT DISTINCT la.user_id, la.id AS linked_account_id
            FROM user_games ug
            JOIN linked_accounts la ON la.id = ug.linked_account_id
            JOIN users u ON u.id = la.user_id
            WHERE ug.platform_game_id = %s AND (u.share_stats = true OR u.id = %s)
        ) o
        LEFT JOIN user_achievements ua ON ua.achievement_id = a.id AND ua.linked_account_id = o.linked_account_id
        WHERE a.platform_game_id = %s
        GROUP BY a.id, a.platform_ach_id, a.name, a.description, a.icon_url, a.points, a.rarity_pct, a.guide_url
        ORDER BY a.rarity_pct ASC NULLS LAST, a.name
        """,
        platform_game_id, requesting_user_id, platform_game_id,
    )
    return {"game": game, "owners": owners, "achievements": achievements}


async def get_user_export(conn, user_id: int) -> dict:
    """
    Everything one user would want in a personal backup — their connected
    accounts (excluding credentials, which have no business leaving the
    server), games, and unlocked achievements. Deliberately not a restorable
    dump: re-importing would mean re-creating rows in the shared
    platform_games/achievements catalog, which is out of scope for a
    self-service export. Full restore already exists at the admin level via
    pg_dump/pg_restore (see app/backup.py).
    """
    accounts = await _fetch(
        conn,
        """
        SELECT platform, external_id, display_name, status, last_synced_at, created_at
        FROM linked_accounts WHERE user_id = %s ORDER BY platform
        """,
        user_id,
    )
    games = await _fetch(
        conn,
        """
        SELECT pg.platform, pg.name, ug.playtime_minutes, ug.earned_achievements,
               ug.total_achievements, ug.completion_pct, ug.last_played_at
        FROM user_games ug
        JOIN linked_accounts la ON la.id = ug.linked_account_id
        JOIN platform_games pg ON pg.id = ug.platform_game_id
        WHERE la.user_id = %s
        ORDER BY pg.platform, pg.name
        """,
        user_id,
    )
    achievements = await _fetch(
        conn,
        """
        SELECT pg.platform, pg.name AS game_name, a.name AS achievement_name,
               a.points, a.rarity_pct, ua.unlocked_at
        FROM user_achievements ua
        JOIN achievements a ON a.id = ua.achievement_id
        JOIN platform_games pg ON pg.id = a.platform_game_id
        JOIN linked_accounts la ON la.id = ua.linked_account_id
        WHERE la.user_id = %s AND ua.unlocked = true
        ORDER BY ua.unlocked_at DESC NULLS LAST
        """,
        user_id,
    )
    return {"accounts": accounts, "games": games, "achievements": achievements}


async def create_session(conn, token: str, user_id: int, expires_at) -> None:
    await conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (%s, %s, %s)",
        (token, user_id, expires_at),
    )


async def get_session_user(conn, token: str) -> dict | None:
    return await _fetchrow(
        conn,
        "SELECT u.id, u.username, u.display_name, u.avatar_url, u.background_url, u.is_admin, u.share_stats "
        "FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = %s AND s.expires_at > now()",
        token,
    )


async def delete_session(conn, token: str) -> None:
    await conn.execute("DELETE FROM sessions WHERE token = %s", (token,))


async def _fetchrow(conn, query: str, *args):
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, args)
        return await cur.fetchone()


async def _fetch(conn, query: str, *args):
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, args)
        return await cur.fetchall()


async def upsert_linked_account(conn, user_id: int, platform: str, external_id: str) -> int:
    row = await _fetchrow(
        conn,
        """
        INSERT INTO linked_accounts (user_id, platform, external_id, display_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, platform, external_id) DO UPDATE SET enabled = TRUE
        RETURNING id
        """,
        user_id, platform, external_id, external_id,
    )
    return row["id"]


# ── Connected-account management ─────────────────────────────────────────────

async def list_accounts(conn, user_id: int) -> list[dict]:
    """Return this user's connected accounts with their credentials and status."""
    return await _fetch(
        conn,
        """
        SELECT id, platform, external_id, display_name, enabled,
               credentials, status, last_error, last_synced_at, created_at
        FROM linked_accounts
        WHERE user_id = %s
        ORDER BY platform, id
        """,
        user_id,
    )


async def list_all_accounts(conn) -> list[dict]:
    """
    Every connected account across every user, including which user owns
    it — used only by the background sync job (scheduled + "sync all"),
    never by a request handler acting on behalf of one logged-in user.
    """
    return await _fetch(
        conn,
        """
        SELECT id, user_id, platform, external_id, display_name, enabled,
               credentials, status, last_error, last_synced_at, created_at
        FROM linked_accounts
        ORDER BY platform, id
        """,
    )


async def get_account(conn, account_id: int, user_id: int) -> dict | None:
    """user_id is required so one user can't fetch/act on another's account by guessing its id."""
    return await _fetchrow(
        conn,
        """
        SELECT id, platform, external_id, display_name, enabled,
               credentials, status, last_error, last_synced_at, created_at
        FROM linked_accounts WHERE id = %s AND user_id = %s
        """,
        account_id, user_id,
    )


async def get_account_by_key(conn, user_id: int, platform: str, external_id: str) -> dict | None:
    return await _fetchrow(
        conn,
        "SELECT id, platform, external_id, credentials FROM linked_accounts "
        "WHERE user_id = %s AND platform = %s AND external_id = %s",
        user_id, platform, external_id,
    )


async def upsert_account(conn, user_id: int, platform: str, external_id: str,
                         credentials: dict, display_name: str | None = None) -> int:
    """Create or update a connected account, storing credentials as JSONB."""
    row = await _fetchrow(
        conn,
        """
        INSERT INTO linked_accounts (user_id, platform, external_id, display_name, credentials, enabled, status)
        VALUES (%s, %s, %s, %s, %s, TRUE, 'connected')
        ON CONFLICT (user_id, platform, external_id) DO UPDATE
            SET display_name = COALESCE(EXCLUDED.display_name, linked_accounts.display_name),
                credentials  = EXCLUDED.credentials,
                enabled      = TRUE,
                status       = 'connected',
                last_error   = NULL
        RETURNING id
        """,
        user_id, platform, external_id, display_name or external_id, Jsonb(credentials),
    )
    return row["id"]


async def set_account_status(conn, account_id: int, status: str,
                             last_error: str | None = None) -> None:
    await conn.execute(
        """
        UPDATE linked_accounts
           SET status = %s, last_error = %s,
               last_synced_at = CASE WHEN %s = 'connected' THEN now() ELSE last_synced_at END
         WHERE id = %s
        """,
        (status, last_error, status, account_id),
    )


async def delete_other_accounts_for_platform(conn, user_id: int, platform: str, keep_external_id: str) -> None:
    """
    This app supports one account per platform per user. If a reconnect
    resolves to a different external_id than before (e.g. Ubisoft/PSN
    re-resolving a username to a different profile id), drop the other
    row(s) for this platform instead of leaving them as invisible,
    error-counted orphans. Scoped to user_id so this can't touch another
    user's account for the same platform.
    """
    await conn.execute(
        "DELETE FROM linked_accounts WHERE user_id = %s AND platform = %s AND external_id != %s",
        (user_id, platform, keep_external_id),
    )


async def delete_account(conn, account_id: int, user_id: int) -> None:
    """Remove a connected account and its synced data (FK cascade handles children)."""
    await conn.execute("DELETE FROM linked_accounts WHERE id = %s AND user_id = %s", (account_id, user_id))


async def account_exists(conn, user_id: int, platform: str) -> bool:
    row = await _fetchrow(
        conn, "SELECT 1 AS x FROM linked_accounts WHERE user_id = %s AND platform = %s LIMIT 1",
        user_id, platform,
    )
    return row is not None


async def upsert_platform_game(conn, platform: str, platform_app_id: str, name: str,
                                icon_url: str | None, total_achievements: int,
                                store_id: str | None = None,
                                xbox_pfn: str | None = None) -> int:
    row = await _fetchrow(
        conn,
        """
        INSERT INTO platform_games (platform, platform_app_id, name, icon_url, total_achievements, store_id, xbox_pfn)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (platform, platform_app_id) DO UPDATE
            SET name = EXCLUDED.name,
                icon_url = EXCLUDED.icon_url,
                total_achievements = EXCLUDED.total_achievements,
                store_id = COALESCE(platform_games.store_id, EXCLUDED.store_id),
                xbox_pfn = COALESCE(platform_games.xbox_pfn, EXCLUDED.xbox_pfn)
        RETURNING id
        """,
        platform, platform_app_id, name, icon_url, total_achievements, store_id, xbox_pfn,
    )
    return row["id"]


async def upsert_user_game(conn, linked_account_id: int, platform_game_id: int,
                            playtime_minutes: int, earned: int, total: int,
                            last_played_at=None) -> None:
    pct = round(earned / total * 100, 1) if total else 0
    await conn.execute(
        """
        INSERT INTO user_games
            (linked_account_id, platform_game_id, playtime_minutes,
             earned_achievements, total_achievements, completion_pct, last_played_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (linked_account_id, platform_game_id) DO UPDATE
            SET playtime_minutes      = EXCLUDED.playtime_minutes,
                earned_achievements   = EXCLUDED.earned_achievements,
                total_achievements    = EXCLUDED.total_achievements,
                completion_pct        = EXCLUDED.completion_pct,
                last_played_at        = EXCLUDED.last_played_at
        """,
        (linked_account_id, platform_game_id, playtime_minutes, earned, total, pct, last_played_at),
    )


async def upsert_achievement(conn, platform_game_id: int, platform_ach_id: str,
                              name: str, description: str | None,
                              icon_url: str | None, points: int | None,
                              rarity_pct: float | None) -> int:
    row = await _fetchrow(
        conn,
        """
        INSERT INTO achievements
            (platform_game_id, platform_ach_id, name, description, icon_url, points, rarity_pct)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (platform_game_id, platform_ach_id) DO UPDATE
            SET name        = EXCLUDED.name,
                description = EXCLUDED.description,
                icon_url    = EXCLUDED.icon_url,
                points      = EXCLUDED.points,
                rarity_pct  = EXCLUDED.rarity_pct
        RETURNING id
        """,
        platform_game_id, platform_ach_id, name, description, icon_url, points, rarity_pct,
    )
    return row["id"]


# ── TrueAchievements/TrueSteamAchievements guide links ──────────────────────

_GUIDE_REFRESH_INTERVAL = "30 days"


async def guide_links_need_refresh(conn, platform_game_id: int) -> bool:
    row = await _fetchrow(
        conn,
        "SELECT platform, guide_links_fetched_at FROM platform_games WHERE id = %s",
        platform_game_id,
    )
    if not row or row["platform"] not in ("steam", "xbox"):
        return False
    if row["guide_links_fetched_at"] is None:
        return True
    stale = await _fetchrow(
        conn,
        f"SELECT (guide_links_fetched_at < now() - interval '{_GUIDE_REFRESH_INTERVAL}') AS stale "
        "FROM platform_games WHERE id = %s",
        platform_game_id,
    )
    return bool(stale and stale["stale"])


async def list_achievement_names(conn, platform_game_id: int) -> list[dict]:
    return await _fetch(
        conn,
        "SELECT id, name FROM achievements WHERE platform_game_id = %s AND name IS NOT NULL",
        platform_game_id,
    )


async def list_unmatched_achievement_names(conn, platform_game_id: int, limit: int) -> list[dict]:
    """Achievements still missing a guide_url, oldest/lowest-id first, capped for quota-bounded lookups."""
    return await _fetch(
        conn,
        "SELECT id, name FROM achievements "
        "WHERE platform_game_id = %s AND name IS NOT NULL AND guide_url IS NULL "
        "ORDER BY id LIMIT %s",
        platform_game_id, limit,
    )


async def has_unmatched_achievements(conn, platform_game_id: int) -> bool:
    row = await _fetchrow(
        conn,
        "SELECT EXISTS (SELECT 1 FROM achievements WHERE platform_game_id = %s AND guide_url IS NULL) AS has_any",
        platform_game_id,
    )
    return bool(row and row["has_any"])


async def set_achievement_guide_urls(conn, mapping: dict[int, str]) -> None:
    for achievement_id, url in mapping.items():
        await conn.execute(
            "UPDATE achievements SET guide_url = %s WHERE id = %s", (url, achievement_id),
        )


async def mark_guide_links_fetched(conn, platform_game_id: int) -> None:
    await conn.execute(
        "UPDATE platform_games SET guide_links_fetched_at = now() WHERE id = %s",
        (platform_game_id,),
    )


async def clear_guide_links(conn, platform_game_id: int) -> None:
    """
    Force the next view to re-scrape immediately instead of waiting out the
    30-day cache — for when a slug override/fix ships after a game was
    already (wrongly) marked checked, or TSA/TA's page has visibly changed.
    """
    await conn.execute(
        "UPDATE platform_games SET guide_links_fetched_at = NULL, guide_url = NULL WHERE id = %s",
        (platform_game_id,),
    )
    await conn.execute(
        "UPDATE achievements SET guide_url = NULL WHERE platform_game_id = %s",
        (platform_game_id,),
    )


async def set_platform_game_guide_url(conn, platform_game_id: int, url: str) -> None:
    """
    Only call this once the scraper has confirmed the URL actually resolves
    to real achievement links — an unconfirmed slug guess is wrong often
    enough (edition/subtitle abbreviations) that it isn't safe to hand to
    the frontend as a fallback link.
    """
    await conn.execute(
        "UPDATE platform_games SET guide_url = %s WHERE id = %s", (url, platform_game_id),
    )


async def get_earned_counts(conn, linked_account_id: int) -> dict[str, dict]:
    """Return {platform_app_id: {earned, stored}} only for games that have achievement records stored."""
    rows = await _fetch(
        conn,
        """
        SELECT pg.platform_app_id, ug.earned_achievements,
               COUNT(a.id) AS stored_achievements
        FROM user_games ug
        JOIN platform_games pg ON pg.id = ug.platform_game_id
        JOIN achievements a ON a.platform_game_id = pg.id
        WHERE ug.linked_account_id = %s
        GROUP BY pg.platform_app_id, ug.earned_achievements
        """,
        linked_account_id,
    )
    return {r["platform_app_id"]: {"earned": r["earned_achievements"], "stored": r["stored_achievements"]} for r in rows}


async def upsert_igdb_game(conn, igdb_id: int, name: str, cover_url: str) -> None:
    await conn.execute(
        """
        INSERT INTO igdb_games (id, name, cover_url)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, cover_url = EXCLUDED.cover_url
        """,
        (igdb_id, name, cover_url),
    )


async def set_igdb_id(conn, platform_game_id: int, igdb_id: int) -> None:
    await conn.execute(
        "UPDATE platform_games SET igdb_id = %s WHERE id = %s",
        (igdb_id, platform_game_id),
    )


async def set_sgdb_cover(conn, platform_game_id: int, cover_url: str) -> None:
    await conn.execute(
        "UPDATE platform_games SET sgdb_cover_url = %s WHERE id = %s",
        (cover_url, platform_game_id),
    )


async def set_store_id(conn, platform_game_id: int, store_id: str) -> None:
    await conn.execute(
        "UPDATE platform_games SET store_id = %s WHERE id = %s",
        (store_id, platform_game_id),
    )


async def update_hltb(conn, platform_game_id: int, main: float | None, extra: float | None, complete: float | None) -> None:
    await conn.execute(
        "UPDATE platform_games SET hltb_main=%s, hltb_extra=%s, hltb_complete=%s WHERE id=%s",
        (main, extra, complete, platform_game_id),
    )


async def remove_user_game(conn, linked_account_id: int, platform: str, platform_app_id: str) -> None:
    await conn.execute(
        """
        DELETE FROM user_games ug
        USING platform_games pg
        WHERE ug.platform_game_id = pg.id
          AND ug.linked_account_id = %s
          AND pg.platform = %s
          AND pg.platform_app_id = %s
        """,
        (linked_account_id, platform, platform_app_id),
    )


async def unlocks_since(conn, linked_account_id: int, since) -> list[dict]:
    """
    Achievements for this account whose platform-reported unlock time is
    after `since`. Used right after a sync to detect genuinely new unlocks —
    callers should pass the account's *previous* last_synced_at (and skip the
    call entirely if that's None, i.e. this is the account's first-ever
    sync, to avoid treating a whole synced-in backlog as "new").
    """
    return await _fetch(
        conn,
        """
        SELECT a.name AS achievement_name, a.icon_url, a.points,
               pg.name AS game_name, pg.platform, pg.id AS platform_game_id,
               ua.unlocked_at
        FROM user_achievements ua
        JOIN achievements a ON a.id = ua.achievement_id
        JOIN platform_games pg ON pg.id = a.platform_game_id
        WHERE ua.linked_account_id = %s AND ua.unlocked = TRUE AND ua.unlocked_at > %s
        ORDER BY ua.unlocked_at ASC
        """,
        linked_account_id, since,
    )


async def upsert_user_achievement(conn, linked_account_id: int, achievement_id: int,
                                   unlocked: bool, unlocked_at=None) -> None:
    await conn.execute(
        """
        INSERT INTO user_achievements (linked_account_id, achievement_id, unlocked, unlocked_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (linked_account_id, achievement_id) DO UPDATE
            SET unlocked    = EXCLUDED.unlocked,
                unlocked_at = EXCLUDED.unlocked_at
        """,
        (linked_account_id, achievement_id, unlocked, unlocked_at),
    )


async def get_profile(conn) -> dict:
    row = await _fetchrow(conn, "SELECT display_name, avatar_url FROM profile WHERE id = 1")
    return dict(row) if row else {"display_name": None, "avatar_url": None}


async def update_profile(conn, display_name: str | None, avatar_url: str | None) -> dict:
    """Overwrites both fields (not a partial patch) — pass None to clear a field
    back to its default, since the caller always submits the whole form."""
    row = await _fetchrow(
        conn,
        """
        UPDATE profile SET display_name = %s, avatar_url = %s
        WHERE id = 1
        RETURNING display_name, avatar_url
        """,
        display_name, avatar_url,
    )
    return dict(row)
