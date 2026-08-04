import asyncio
import logging

import httpx
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import backup, config, db, hltb as hltb_names
from app.db import _fetch, _fetchrow
from app.platforms import PLATFORMS

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()
_scheduler = AsyncIOScheduler()

# In-memory sync progress tracker
_sync_progress: dict = {
    "running": False,
    "started_at": None,
    "platforms": {},  # platform -> {status, games_seen, achievements_synced, error}
}

# In-memory feed of newly-unlocked achievements, for the frontend to poll and
# toast. Capped ring buffer — losing old entries on restart is fine, this is
# just a live notification feed, not a record of truth (that's user_achievements).
_UNLOCK_EVENTS_MAX = 300
_unlock_events: list[dict] = []


def _record_unlock_events(rows: list[dict]) -> None:
    for r in rows:
        _unlock_events.append({
            "unlocked_at": r["unlocked_at"].isoformat(),
            "game_name": r["game_name"],
            "platform": r["platform"],
            "platform_game_id": r["platform_game_id"],
            "achievement_name": r["achievement_name"],
            "icon_url": r["icon_url"],
            "points": r["points"],
        })
    if len(_unlock_events) > _UNLOCK_EVENTS_MAX:
        del _unlock_events[: len(_unlock_events) - _UNLOCK_EVENTS_MAX]


async def _enrich_igdb(retry_failed: bool = False) -> None:
    """Fetch IGDB cover art for games that don't have it yet (parallel with semaphore)."""
    if not config.IGDB_CLIENT_ID or not config.IGDB_CLIENT_SECRET:
        return
    from app.igdb import search_cover
    pool = await db.get_pool()
    async with pool.connection() as conn:
        if retry_failed:
            rows = await _fetch(
                conn,
                "SELECT id, name, platform FROM platform_games WHERE (igdb_id IS NULL OR igdb_id = -1) AND total_achievements > 0",
            )
        else:
            rows = await _fetch(
                conn,
                "SELECT id, name, platform FROM platform_games WHERE igdb_id IS NULL AND total_achievements > 0",
            )
    log.info("IGDB enrichment: %d games to look up", len(rows))
    sem = asyncio.Semaphore(5)

    async def _lookup(row):
        async with sem:
            try:
                result = await search_cover(row["name"], row["platform"])
                if result:
                    igdb_id, cover_url = result
                    async with pool.connection() as conn:
                        await db.upsert_igdb_game(conn, igdb_id, row["name"], cover_url)
                        await db.set_igdb_id(conn, row["id"], igdb_id)
                    log.info("IGDB cover found for '%s'", row["name"])
                else:
                    async with pool.connection() as conn:
                        await conn.execute(
                            "UPDATE platform_games SET igdb_id = -1 WHERE id = %s", (row["id"],)
                        )
                await asyncio.sleep(config.REQUEST_DELAY_SECONDS)
            except Exception:
                log.exception("IGDB lookup failed for %s", row["name"])

    await asyncio.gather(*[_lookup(row) for row in rows])


async def _enrich_sgdb(retry_failed: bool = False, force: bool = False) -> None:
    """Fetch SteamGridDB landscape cover art for games that don't have it yet."""
    if not config.SGDB_API_KEY:
        return
    from app.sgdb import search_grid
    pool = await db.get_pool()
    async with pool.connection() as conn:
        if force:
            # Re-fetch everything, including games that already have a cover —
            # used once after switching the SGDB source from Grids to Heroes,
            # since existing covers won't otherwise be revisited.
            await conn.execute(
                "UPDATE platform_games SET sgdb_cover_url = NULL WHERE total_achievements > 0"
            )
            rows = await _fetch(
                conn,
                "SELECT id, name FROM platform_games WHERE total_achievements > 0",
            )
        elif retry_failed:
            rows = await _fetch(
                conn,
                "SELECT id, name FROM platform_games WHERE (sgdb_cover_url IS NULL OR sgdb_cover_url = '') AND total_achievements > 0",
            )
        else:
            rows = await _fetch(
                conn,
                "SELECT id, name FROM platform_games WHERE sgdb_cover_url IS NULL AND total_achievements > 0",
            )
    log.info("SGDB enrichment: %d games to look up", len(rows))
    sem = asyncio.Semaphore(3)

    async def _lookup(row):
        async with sem:
            try:
                url = await search_grid(row["name"])
                async with pool.connection() as conn:
                    await db.set_sgdb_cover(conn, row["id"], url or "")
                if url:
                    log.info("SGDB cover found for '%s'", row["name"])
                await asyncio.sleep(config.REQUEST_DELAY_SECONDS)
            except Exception:
                log.exception("SGDB lookup failed for %s", row["name"])

    await asyncio.gather(*[_lookup(row) for row in rows])


async def _enrich_hltb() -> None:
    """Fetch How Long To Beat times for games that don't have them yet (parallel with semaphore)."""
    try:
        from howlongtobeatpy import HowLongToBeat
    except ImportError:
        log.warning("howlongtobeatpy not installed; skipping HLTB enrichment")
        return

    pool = await db.get_pool()
    async with pool.connection() as conn:
        rows = await _fetch(
            conn,
            "SELECT id, name FROM platform_games WHERE hltb_main IS NULL AND total_achievements > 0",
        )

    log.info("HLTB enrichment: %d games to look up", len(rows))
    hltb = HowLongToBeat(0.0)
    sem = asyncio.Semaphore(3)

    async def _lookup(row):
        async with sem:
            try:
                query = hltb_names.clean_name(row["name"])
                results = await hltb.async_search(query)
                if not results:
                    log.info("HLTB no results for: %s (searched: %s)", row["name"], query)
                    async with pool.connection() as conn:
                        await db.update_hltb(conn, row["id"], -1, None, None)
                    return
                best = max(results, key=lambda r: r.similarity)
                log.info("HLTB best match for '%s': '%s' (sim=%.2f)", row["name"], best.game_name, best.similarity)
                main = float(best.main_story) if best.main_story and best.main_story > 0 else None
                extra = float(best.main_extra) if best.main_extra and best.main_extra > 0 else None
                complete = float(best.completionist) if best.completionist and best.completionist > 0 else None
                async with pool.connection() as conn:
                    await db.update_hltb(conn, row["id"], main or -1, extra, complete)
                await asyncio.sleep(config.REQUEST_DELAY_SECONDS)
            except Exception:
                log.exception("HLTB lookup failed for %s", row["name"])

    await asyncio.gather(*[_lookup(row) for row in rows])




# Manual slug aliases for games with abbreviated/different names in our DB vs Exophase
_EXOPHASE_TITLE_ALIASES: dict[str, str] = {
    "pgr-4": "project-gotham-racing-4",
    "pgr-3": "project-gotham-racing-3",
    "gta-iv": "grand-theft-auto-iv",
    "gta-iv-pc": "grand-theft-auto-iv",
    "modern-warfare": "call-of-duty-4-modern-warfare",
    "brothers-in-arms-hh": "brothers-in-arms-hells-highway",
    "nfs-undercover": "need-for-speed-undercover",
    "nfs-prostreet": "need-for-speed-prostreet",
    "guitar-hero-iii": "guitar-hero-iii-legends-of-rock",
    "medal-of-honor-airborne": "moh-airborne",
    "alone-in-the-dark": "alone-in-the-dark-2008",
    "kane-and-lynch-deadmen": "kane-lynch-dead-men",
}


async def _enrich_exophase_360_icons() -> None:
    """Fetch Xbox 360 achievement icons from Exophase (earned + locked via page scrape)."""
    if not config.EXOPHASE_PLAYER_ID:
        return

    from app.platforms.exophase import fetch_games_list, fetch_earned_icons, _to_slug

    access_token = config.EXOPHASE_ACCESS_TOKEN
    if not access_token:
        log.warning("Exophase: EXOPHASE_ACCESS_TOKEN not set; skipping enrichment")
        return

    pool = await db.get_pool()
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            exo_games = await fetch_games_list(client, config.EXOPHASE_PLAYER_ID, access_token)
        except Exception:
            log.exception("Exophase games list fetch failed")
            return

        # Build title→exo_game map for ALL games
        exo_by_title: dict[str, dict] = {}
        for g in exo_games:
            exo_by_title[_to_slug(g["title"])] = g

        if not exo_by_title:
            return

        # Find ALL Xbox achievements without icons (earned and locked)
        async with pool.connection() as conn:
            rows = await _fetch(
                conn,
                """
                SELECT a.id, a.name, pg.name AS game_name
                FROM achievements a
                JOIN platform_games pg ON pg.id = a.platform_game_id
                WHERE pg.platform = 'xbox' AND a.icon_url IS NULL
                """,
            )

        if not rows:
            log.info("Exophase enrichment: no Xbox achievements missing icons")
            return

        log.info("Exophase enrichment: %d Xbox achievements missing icons", len(rows))

        # Group achievements by game name
        by_game: dict[str, list[dict]] = {}
        for row in rows:
            by_game.setdefault(row["game_name"], []).append(row)

        updated = 0
        for game_name, achs in by_game.items():
            db_slug = _to_slug(game_name)
            exo_slug = _EXOPHASE_TITLE_ALIASES.get(db_slug, db_slug)
            exo_game = exo_by_title.get(exo_slug)
            if not exo_game:
                continue

            try:
                icons = await fetch_earned_icons(
                    exo_game["master_playerid"], exo_game["master_id"]
                )
            except Exception:
                log.exception("Exophase earned fetch failed for %s", game_name)
                continue

            if not icons:
                continue

            await asyncio.sleep(config.REQUEST_DELAY_SECONDS)

            async with pool.connection() as conn:
                for ach in achs:
                    slug = _to_slug(ach["name"])
                    icon_url = icons.get(slug)
                    if icon_url:
                        await conn.execute(
                            "UPDATE achievements SET icon_url = %s WHERE id = %s",
                            (icon_url, ach["id"]),
                        )
                        updated += 1

        log.info("Exophase enrichment: updated %d achievement icons", updated)


async def _sync_one_account(pool, account: dict) -> None:
    """Sync a single connected account, recording status + sync_run rows."""
    platform_cls = PLATFORMS.get(account["platform"])
    if not platform_cls:
        return
    plat = account["platform"]
    log.info("Syncing %s / %s", plat, account["external_id"])
    _sync_progress["platforms"][plat] = {
        "status": "running",
        "games_seen": 0,
        "achievements_synced": 0,
        "error": None,
    }
    async with pool.connection() as conn:
        run_row = await _fetchrow(
            conn,
            "INSERT INTO sync_runs (platform, linked_account_id, started_at, status) "
            "VALUES (%s, %s, now(), 'running') RETURNING id",
            plat, account.get("id"),
        )
        run_id = run_row["id"] if run_row else None
        try:
            worker = platform_cls()
            worker._progress = _sync_progress["platforms"][plat]
            await worker.sync(account, conn)
            if run_id:
                await conn.execute(
                    "UPDATE sync_runs SET finished_at = now(), status = 'ok' WHERE id = %s",
                    (run_id,),
                )
            # Only look for "new" unlocks if this account has synced
            # successfully before — on a brand-new account's first sync,
            # everything just synced in is historical backlog, not new.
            prev_synced_at = account.get("last_synced_at")
            if account.get("id") and prev_synced_at:
                try:
                    new_rows = await db.unlocks_since(conn, account["id"], prev_synced_at)
                    _record_unlock_events(new_rows)
                except Exception:
                    log.exception("Failed to collect new-unlock events for %s", plat)
            if account.get("id"):
                await db.set_account_status(conn, account["id"], "connected")
            _sync_progress["platforms"][plat]["status"] = "done"
            log.info("Sync done: %s", plat)
        except Exception as exc:
            log.exception("Sync failed: %s", plat)
            # Some exceptions (httpx timeouts/connect errors, bare asyncio.TimeoutError)
            # stringify to "" — fall back to the exception's type name so the UI
            # always shows *something* instead of a silent blank error.
            msg = str(exc) or type(exc).__name__
            _sync_progress["platforms"][plat]["status"] = "error"
            _sync_progress["platforms"][plat]["error"] = msg
            if account.get("id"):
                await db.set_account_status(conn, account["id"], "error", msg[:500])
            if run_id:
                await conn.execute(
                    "UPDATE sync_runs SET finished_at = now(), status = 'error', detail = %s WHERE id = %s",
                    (msg, run_id),
                )


async def run_sync(account_id: int | None = None) -> None:
    if _sync_lock.locked():
        log.info("Sync already running, skipping")
        return
    async with _sync_lock:
        from datetime import datetime, timezone
        _sync_progress["running"] = True
        _sync_progress["started_at"] = datetime.now(timezone.utc).isoformat()
        _sync_progress["platforms"] = {}

        pool = await db.get_pool()
        async with pool.connection() as conn:
            accounts = await db.list_accounts(conn)
        accounts = [a for a in accounts if a.get("enabled", True)]
        if account_id is not None:
            accounts = [a for a in accounts if a["id"] == account_id]

        for account in accounts:
            await _sync_one_account(pool, account)

        _sync_progress["running"] = False
        asyncio.create_task(_enrich_hltb())
        asyncio.create_task(_enrich_igdb())
        asyncio.create_task(_enrich_sgdb())
        asyncio.create_task(_enrich_exophase_360_icons())


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await db.get_pool()
    await db.apply_schema(pool)

    # One-time migration: seed DB-backed accounts from any legacy .env config.
    # Only fills in platforms that don't already have a connected account, so
    # credentials edited in the UI are never overwritten by stale env values.
    for seed in config.env_seed_accounts():
        async with pool.connection() as conn:
            if not await db.account_exists(conn, seed["platform"]):
                await db.upsert_account(
                    conn, seed["platform"], seed["external_id"],
                    seed["credentials"], seed.get("display_name"),
                )
                log.info("Seeded %s account from environment", seed["platform"])

    asyncio.create_task(run_sync())
    asyncio.create_task(_enrich_hltb())
    asyncio.create_task(_enrich_igdb())
    asyncio.create_task(_enrich_sgdb())

    _scheduler.add_job(run_sync, "interval", hours=config.SYNC_INTERVAL_HOURS)
    _scheduler.add_job(backup.create_backup_safe, "interval", hours=config.BACKUP_INTERVAL_HOURS)
    _scheduler.start()

    yield

    _scheduler.shutdown(wait=False)
    if db._pool:
        await db._pool.close()


app = FastAPI(title="Achievist", lifespan=lifespan)


@app.get("/api/profile")
async def get_profile():
    pool = await db.get_pool()
    async with pool.connection() as conn:
        return await db.get_profile(conn)


@app.put("/api/profile")
async def update_profile(payload: dict):
    display_name = (payload.get("display_name") or "").strip() or None
    avatar_url = (payload.get("avatar_url") or "").strip() or None
    pool = await db.get_pool()
    async with pool.connection() as conn:
        return await db.update_profile(conn, display_name, avatar_url)


@app.get("/api/summary")
async def summary():
    pool = await db.get_pool()
    async with pool.connection() as conn:
        row = await _fetchrow(
            conn,
            """
            SELECT
                COUNT(DISTINCT ug.platform_game_id)     AS total_games,
                SUM(ug.earned_achievements)              AS total_earned,
                SUM(ug.total_achievements)               AS total_possible,
                CASE WHEN SUM(ug.total_achievements) > 0
                     THEN ROUND(SUM(ug.earned_achievements)::numeric
                          / SUM(ug.total_achievements) * 100, 1)
                     ELSE 0 END                          AS overall_pct,
                COUNT(*) FILTER (WHERE ug.completion_pct = 100) AS perfect_games
            FROM user_games ug
            """,
        )
        by_platform = await _fetch(
            conn,
            """
            SELECT
                pg.platform,
                COUNT(*)                                 AS games,
                SUM(ug.earned_achievements)              AS earned,
                SUM(ug.total_achievements)               AS possible,
                CASE WHEN SUM(ug.total_achievements) > 0
                     THEN ROUND(SUM(ug.earned_achievements)::numeric
                          / SUM(ug.total_achievements) * 100, 1)
                     ELSE 0 END                          AS pct,
                SUM(ug.playtime_minutes)                 AS total_playtime_minutes
            FROM user_games ug
            JOIN platform_games pg ON pg.id = ug.platform_game_id
            GROUP BY pg.platform
            """,
        )
        last_synced = await _fetch(
            conn,
            """
            SELECT platform, MAX(finished_at) AS last_sync
            FROM sync_runs
            WHERE status = 'ok'
            GROUP BY platform
            """,
        )
    last_synced_map = {r["platform"]: r["last_sync"] for r in last_synced}
    platform_list = [
        {**dict(r), "last_sync": last_synced_map.get(r["platform"])}
        for r in by_platform
    ]
    max_playtime = max((p["total_playtime_minutes"] or 0 for p in platform_list), default=0)
    for p in platform_list:
        p["most_played"] = (p["total_playtime_minutes"] or 0) == max_playtime and max_playtime > 0
    return {
        "total_games": row["total_games"] or 0,
        "total_earned": int(row["total_earned"] or 0),
        "total_possible": int(row["total_possible"] or 0),
        "overall_pct": float(row["overall_pct"] or 0),
        "perfect_games": int(row["perfect_games"] or 0),
        "by_platform": platform_list,
    }


@app.get("/api/games")
async def games(
    sort: str = Query("recent", pattern="^(completion|recent|playtime|name)$"),
    platform: str | None = None,
    search: str | None = None,
    completion: str | None = Query(None, pattern="^(completed|in_progress|not_started)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    # Every ordering ends with pg.id as a tiebreaker so paginated results are
    # stable even when many rows share the same sort value (e.g. identical
    # last_played_at) — otherwise Postgres can return the same row on two
    # different pages, causing duplicates in infinite scroll.
    order = {
        "completion": "ug.completion_pct DESC, ug.earned_achievements DESC, pg.id",
        "recent": "ug.last_played_at DESC NULLS LAST, pg.id",
        "playtime": "ug.playtime_minutes DESC, pg.id",
        "name": "pg.name ASC, pg.id",
    }[sort]

    filters = ["ug.total_achievements > 0"]
    params: list = []

    if platform:
        filters.append("pg.platform = %s")
        params.append(platform)
    if search:
        filters.append("pg.name ILIKE %s")
        params.append(f"%{search}%")
    if completion == "completed":
        filters.append("ug.completion_pct >= 100")
    elif completion == "in_progress":
        filters.append("ug.earned_achievements > 0 AND ug.completion_pct < 100")
    elif completion == "not_started":
        filters.append("ug.earned_achievements = 0")

    where = "WHERE " + " AND ".join(filters)
    offset = (page - 1) * page_size

    pool = await db.get_pool()
    async with pool.connection() as conn:
        total_row = await _fetchrow(
            conn,
            f"""
            SELECT COUNT(*) AS cnt
            FROM user_games ug
            JOIN platform_games pg ON pg.id = ug.platform_game_id
            {where}
            """,
            *params,
        )
        rows = await _fetch(
            conn,
            f"""
            SELECT
                pg.id               AS platform_game_id,
                pg.platform,
                pg.platform_app_id,
                CASE WHEN pg.platform = 'ubisoft' THEN COALESCE(ig.name, pg.name) ELSE pg.name END AS name,
                pg.icon_url,
                pg.store_id,
                pg.sgdb_cover_url,
                ig.cover_url        AS igdb_cover_url,
                ug.playtime_minutes,
                ug.earned_achievements,
                ug.total_achievements,
                ug.completion_pct,
                ug.last_played_at
            FROM user_games ug
            JOIN platform_games pg ON pg.id = ug.platform_game_id
            LEFT JOIN igdb_games ig ON ig.id = pg.igdb_id AND pg.igdb_id > 0
            {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
            """,
            *params, page_size, offset,
        )

    return {
        "total": total_row["cnt"],
        "page": page,
        "page_size": page_size,
        "games": [dict(r) for r in rows],
    }


_RARITY_TIER_SQL = {
    "Legendary": "a.rarity_pct <= 1",
    "Epic": "a.rarity_pct > 1 AND a.rarity_pct <= 5",
    "Rare": "a.rarity_pct > 5 AND a.rarity_pct <= 20",
    "Uncommon": "a.rarity_pct > 20 AND a.rarity_pct <= 50",
    "Common": "a.rarity_pct > 50",
}


@app.get("/api/achievements/search")
async def achievements_search(
    q: str | None = None,
    rarity: str | None = Query(None, pattern="^(Legendary|Epic|Rare|Uncommon|Common)$"),
    platform: str | None = None,
    unlocked: str | None = Query(None, pattern="^(true|false)$"),
    sort: str = Query("rarity", pattern="^(rarity|name|points|unlocked_at)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=200),
):
    """Search achievements across the whole library, not just within one game."""
    order = {
        "rarity": "a.rarity_pct ASC NULLS LAST, a.id",
        "name": "a.name ASC, a.id",
        "points": "a.points DESC NULLS LAST, a.id",
        "unlocked_at": "ua.unlocked_at DESC NULLS LAST, a.id",
    }[sort]

    filters = []
    params: list = []

    if q:
        filters.append("(a.name ILIKE %s OR a.description ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if platform:
        filters.append("pg.platform = %s")
        params.append(platform)
    if unlocked == "true":
        filters.append("ua.unlocked = TRUE")
    elif unlocked == "false":
        filters.append("(ua.unlocked IS NULL OR ua.unlocked = FALSE)")
    if rarity:
        filters.append(_RARITY_TIER_SQL[rarity])

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    offset = (page - 1) * page_size

    pool = await db.get_pool()
    async with pool.connection() as conn:
        total_row = await _fetchrow(
            conn,
            f"""
            SELECT COUNT(*) AS cnt
            FROM achievements a
            JOIN platform_games pg ON pg.id = a.platform_game_id
            LEFT JOIN user_achievements ua ON ua.achievement_id = a.id
            {where}
            """,
            *params,
        )
        rows = await _fetch(
            conn,
            f"""
            SELECT
                a.platform_ach_id, a.name, a.description, a.icon_url, a.points, a.rarity_pct,
                ua.unlocked, ua.unlocked_at,
                pg.id AS platform_game_id, pg.name AS game_name, pg.platform,
                pg.sgdb_cover_url, pg.icon_url AS game_icon_url
            FROM achievements a
            JOIN platform_games pg ON pg.id = a.platform_game_id
            LEFT JOIN user_achievements ua ON ua.achievement_id = a.id
            {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
            """,
            *params, page_size, offset,
        )

    return {
        "total": total_row["cnt"],
        "page": page,
        "page_size": page_size,
        "achievements": [dict(r) for r in rows],
    }


@app.get("/api/games/{platform_game_id}")
async def game_detail(platform_game_id: int):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        row = await _fetchrow(
            conn,
            """
            SELECT
                pg.id               AS platform_game_id,
                pg.platform,
                pg.platform_app_id,
                CASE WHEN pg.platform = 'ubisoft' THEN COALESCE(ig.name, pg.name) ELSE pg.name END AS name,
                pg.icon_url,
                pg.store_id,
                pg.sgdb_cover_url,
                pg.hltb_main,
                pg.hltb_extra,
                pg.hltb_complete,
                ig.cover_url        AS igdb_cover_url,
                ug.playtime_minutes,
                ug.earned_achievements,
                ug.total_achievements,
                ug.completion_pct,
                ug.last_played_at
            FROM user_games ug
            JOIN platform_games pg ON pg.id = ug.platform_game_id
            LEFT JOIN igdb_games ig ON ig.id = pg.igdb_id AND pg.igdb_id > 0
            WHERE pg.id = %s
            """,
            platform_game_id,
        )
        rarity_summary = await _fetch(
            conn,
            """
            SELECT tier, COUNT(*) AS cnt FROM (
                SELECT CASE
                    WHEN a.rarity_pct <= 1  THEN 'Legendary'
                    WHEN a.rarity_pct <= 5  THEN 'Epic'
                    WHEN a.rarity_pct <= 20 THEN 'Rare'
                    WHEN a.rarity_pct <= 50 THEN 'Uncommon'
                    ELSE 'Common'
                END AS tier
                FROM user_achievements ua
                JOIN achievements a ON a.id = ua.achievement_id
                WHERE a.platform_game_id = %s AND ua.unlocked = true AND a.rarity_pct IS NOT NULL
            ) sub GROUP BY tier ORDER BY MIN(
                CASE tier
                    WHEN 'Legendary' THEN 1 WHEN 'Epic' THEN 2
                    WHEN 'Rare' THEN 3 WHEN 'Uncommon' THEN 4 ELSE 5
                END
            )
            """,
            platform_game_id,
        )
        points_row = await _fetchrow(
            conn,
            """
            SELECT SUM(a.points) AS total_points
            FROM user_achievements ua
            JOIN achievements a ON a.id = ua.achievement_id
            WHERE a.platform_game_id = %s AND ua.unlocked = true AND a.points IS NOT NULL
            """,
            platform_game_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Game not found")
    result = dict(row)
    result["rarity_summary"] = [dict(r) for r in rarity_summary]
    result["total_points"] = int(points_row["total_points"] or 0) if points_row else 0
    return result


@app.get("/api/statistics")
async def statistics():
    pool = await db.get_pool()
    try:
        async with pool.connection() as conn:
            general = await _fetchrow(
                conn,
                """
                SELECT
                    SUM(ug.earned_achievements)                                          AS unlocked,
                    SUM(ug.total_achievements - ug.earned_achievements)                  AS locked,
                    COUNT(*)                                                             AS games_total,
                    COUNT(*) FILTER (WHERE ug.completion_pct = 100)                     AS mastered,
                    COUNT(*) FILTER (WHERE ug.completion_pct >= 80 AND ug.completion_pct < 100) AS finished,
                    ROUND(AVG(ug.completion_pct), 1)                                    AS avg_completion,
                    ROUND(SUM(ug.earned_achievements)::numeric
                          / NULLIF(SUM(ug.total_achievements), 0) * 100, 2)             AS absolute_completion
                FROM user_games ug
                WHERE ug.total_achievements > 0
                """,
            )

            daily_max = await _fetchrow(
                conn,
                """
                SELECT COUNT(*) AS cnt
                FROM user_achievements
                WHERE unlocked = true AND unlocked_at IS NOT NULL
                GROUP BY unlocked_at::date
                ORDER BY cnt DESC LIMIT 1
                """,
            )

            monthly_max = await _fetchrow(
                conn,
                """
                SELECT COUNT(*) AS cnt
                FROM user_achievements
                WHERE unlocked = true AND unlocked_at IS NOT NULL
                GROUP BY DATE_TRUNC('month', unlocked_at)
                ORDER BY cnt DESC LIMIT 1
                """,
            )

            rarity_rows = await _fetch(
                conn,
                """
                SELECT tier, COUNT(*) AS cnt
                FROM (
                    SELECT
                        CASE
                            WHEN a.rarity_pct <= 1  THEN 'Legendary'
                            WHEN a.rarity_pct <= 5  THEN 'Epic'
                            WHEN a.rarity_pct <= 20 THEN 'Rare'
                            WHEN a.rarity_pct <= 50 THEN 'Uncommon'
                            ELSE 'Common'
                        END AS tier,
                        a.rarity_pct
                    FROM user_achievements ua
                    JOIN achievements a ON a.id = ua.achievement_id
                    WHERE ua.unlocked = true AND a.rarity_pct IS NOT NULL
                ) sub
                GROUP BY tier
                ORDER BY MIN(rarity_pct)
                """,
            )

            completion_dist = await _fetch(
                conn,
                """
                SELECT bracket, COUNT(*) AS cnt
                FROM (
                    SELECT
                        CASE
                            WHEN completion_pct = 0         THEN '0%%'
                            WHEN completion_pct <= 25       THEN '1-25%%'
                            WHEN completion_pct <= 50       THEN '25-50%%'
                            WHEN completion_pct <= 75       THEN '50-75%%'
                            WHEN completion_pct < 100       THEN '75-99%%'
                            ELSE '100%%'
                        END AS bracket
                    FROM user_games WHERE total_achievements > 0
                ) sub
                GROUP BY bracket
                """,
            )

            platform_rows = await _fetch(
                conn,
                """
                SELECT pg.platform, SUM(ug.earned_achievements) AS earned
                FROM user_games ug
                JOIN platform_games pg ON pg.id = ug.platform_game_id
                GROUP BY pg.platform
                """,
            )

            progression = await _fetch(
                conn,
                """
                SELECT DATE_TRUNC('month', unlocked_at)::date AS month, COUNT(*) AS cnt
                FROM user_achievements
                WHERE unlocked = true AND unlocked_at IS NOT NULL
                GROUP BY DATE_TRUNC('month', unlocked_at)::date
                ORDER BY DATE_TRUNC('month', unlocked_at)::date
                """,
            )

            best_day_row = await _fetchrow(
                conn,
                """
                SELECT unlocked_at::date AS day, COUNT(*) AS cnt
                FROM user_achievements
                WHERE unlocked = true AND unlocked_at IS NOT NULL
                GROUP BY unlocked_at::date
                ORDER BY cnt DESC LIMIT 1
                """,
            )

            best_month_row = await _fetchrow(
                conn,
                """
                SELECT DATE_TRUNC('month', unlocked_at)::date AS month, COUNT(*) AS cnt
                FROM user_achievements
                WHERE unlocked = true AND unlocked_at IS NOT NULL
                GROUP BY DATE_TRUNC('month', unlocked_at)::date
                ORDER BY cnt DESC LIMIT 1
                """,
            )

            streak_row = await _fetchrow(
                conn,
                """
                WITH daily AS (
                    SELECT DISTINCT unlocked_at::date AS day
                    FROM user_achievements
                    WHERE unlocked = true AND unlocked_at IS NOT NULL
                ),
                grouped AS (
                    SELECT day, day - (ROW_NUMBER() OVER (ORDER BY day))::int AS grp
                    FROM daily
                ),
                streaks AS (
                    SELECT MIN(day) AS start, MAX(day) AS finish,
                           COUNT(*) AS days
                    FROM grouped GROUP BY grp
                )
                SELECT start, finish, days FROM streaks ORDER BY days DESC LIMIT 1
                """,
            )

        cum, total = [], 0
        for r in progression:
            total += r["cnt"]
            cum.append({"month": r["month"].isoformat(), "total": total})

        bracket_order = ["0%", "1-25%", "25-50%", "50-75%", "75-99%", "100%"]
        dist_map = {r["bracket"]: r["cnt"] for r in completion_dist}

        return {
            "general": {
                "unlocked":           int(general["unlocked"] or 0),
                "locked":             int(general["locked"] or 0),
                "games_total":        int(general["games_total"] or 0),
                "mastered":           int(general["mastered"] or 0),
                "finished":           int(general["finished"] or 0),
                "avg_completion":     float(general["avg_completion"] or 0),
                "absolute_completion": float(general["absolute_completion"] or 0),
                "daily_max":          int(daily_max["cnt"]) if daily_max else 0,
                "monthly_max":        int(monthly_max["cnt"]) if monthly_max else 0,
                "best_day":           best_day_row["day"].isoformat() if best_day_row else None,
                "best_month":         best_month_row["month"].isoformat() if best_month_row else None,
                "best_month_cnt":     int(best_month_row["cnt"]) if best_month_row else 0,
                "best_streak_days":   int(streak_row["days"]) if streak_row else 0,
                "best_streak_start":  streak_row["start"].isoformat() if streak_row else None,
                "best_streak_end":    streak_row["finish"].isoformat() if streak_row else None,
            },
            "rarity": [{"tier": r["tier"], "cnt": r["cnt"]} for r in rarity_rows],
            "completion_dist": [{"bracket": b, "cnt": dist_map.get(b, 0)} for b in bracket_order],
            "platforms": [{"platform": r["platform"], "earned": int(r["earned"] or 0)} for r in platform_rows],
            "progression": cum,
        }
    except Exception:
        log.exception("statistics endpoint failed")
        raise


@app.get("/api/activity")
async def activity():
    """Unlock heatmap, streaks, total playtime, and a recent-activity feed."""
    from datetime import date, timedelta

    pool = await db.get_pool()
    async with pool.connection() as conn:
        heatmap_rows = await _fetch(
            conn,
            """
            SELECT unlocked_at::date AS day, COUNT(*) AS cnt
            FROM user_achievements
            WHERE unlocked = true AND unlocked_at IS NOT NULL
              AND unlocked_at >= now() - interval '53 weeks'
            GROUP BY unlocked_at::date
            ORDER BY day
            """,
        )
        playtime_row = await _fetchrow(
            conn, "SELECT COALESCE(SUM(playtime_minutes), 0) AS total FROM user_games"
        )
        feed_rows = await _fetch(
            conn,
            """
            SELECT pg.id AS platform_game_id, pg.name, pg.platform,
                   pg.icon_url, pg.sgdb_cover_url, ig.cover_url AS igdb_cover_url,
                   ua.unlocked_at::date AS day,
                   COUNT(*) AS cnt,
                   (array_remove(array_agg(a.icon_url ORDER BY ua.unlocked_at DESC), NULL))[1:6] AS icons
            FROM user_achievements ua
            JOIN achievements a ON a.id = ua.achievement_id
            JOIN platform_games pg ON pg.id = a.platform_game_id
            LEFT JOIN igdb_games ig ON ig.id = pg.igdb_id AND pg.igdb_id > 0
            WHERE ua.unlocked = true AND ua.unlocked_at IS NOT NULL
            GROUP BY pg.id, pg.name, pg.platform, pg.icon_url, pg.sgdb_cover_url,
                     ig.cover_url, ua.unlocked_at::date
            ORDER BY ua.unlocked_at::date DESC, cnt DESC
            LIMIT 40
            """,
        )

    # Streaks from distinct unlock days.
    days = sorted({r["day"] for r in heatmap_rows})
    day_set = set(days)
    longest = cur = 0
    prev = None
    for d in days:
        cur = cur + 1 if (prev and (d - prev).days == 1) else 1
        longest = max(longest, cur)
        prev = d
    # Current streak: consecutive days ending today or yesterday.
    current = 0
    probe = date.today()
    if probe not in day_set and (probe - timedelta(days=1)) in day_set:
        probe = probe - timedelta(days=1)
    while probe in day_set:
        current += 1
        probe -= timedelta(days=1)

    return {
        "heatmap": [{"day": r["day"].isoformat(), "count": r["cnt"]} for r in heatmap_rows],
        "current_streak": current,
        "longest_streak": longest,
        "total_playtime_minutes": int(playtime_row["total"] or 0),
        "feed": [
            {
                "platform_game_id": r["platform_game_id"],
                "name": r["name"],
                "platform": r["platform"],
                "cover_url": r["sgdb_cover_url"] or r["igdb_cover_url"] or r["icon_url"],
                "day": r["day"].isoformat(),
                "count": r["cnt"],
                "icons": r["icons"] or [],
            }
            for r in feed_rows
        ],
    }


@app.get("/api/statistics/platform/{platform}")
async def statistics_platform(platform: str):
    """Top games by completion for a platform, for the drilldown modal."""
    pool = await db.get_pool()
    async with pool.connection() as conn:
        rows = await _fetch(
            conn,
            """
            SELECT pg.id AS platform_game_id,
                   CASE WHEN pg.platform = 'ubisoft' THEN COALESCE(ig.name, pg.name) ELSE pg.name END AS name,
                   pg.icon_url,
                   ig.cover_url AS igdb_cover_url, pg.platform_app_id,
                   ug.earned_achievements, ug.total_achievements, ug.completion_pct
            FROM user_games ug
            JOIN platform_games pg ON pg.id = ug.platform_game_id
            LEFT JOIN igdb_games ig ON ig.id = pg.igdb_id AND pg.igdb_id > 0
            WHERE pg.platform = %s AND ug.total_achievements > 0
            ORDER BY ug.earned_achievements DESC
            LIMIT 50
            """,
            platform,
        )
    return [dict(r) for r in rows]


@app.get("/api/games/{platform_game_id}/achievements")
async def game_achievements(platform_game_id: int):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        rows = await _fetch(
            conn,
            """
            SELECT
                a.platform_ach_id,
                a.name,
                a.description,
                a.icon_url,
                a.points,
                a.rarity_pct,
                ua.unlocked,
                ua.unlocked_at
            FROM achievements a
            LEFT JOIN user_achievements ua ON ua.achievement_id = a.id
            WHERE a.platform_game_id = %s
            ORDER BY ua.unlocked DESC NULLS LAST, a.name
            """,
            platform_game_id,
        )
    return [dict(r) for r in rows]


@app.get("/api/hltb-test")
async def hltb_test(name: str = Query(...)):
    """Test HLTB search for a game name. Use to verify the library works."""
    try:
        from howlongtobeatpy import HowLongToBeat
    except ImportError:
        return {"error": "howlongtobeatpy not installed"}
    query = hltb_names.clean_name(name)
    try:
        results = await HowLongToBeat(0.0).async_search(query)
        if not results:
            return {"error": "no results", "name": name, "searched": query}
        best = max(results, key=lambda r: r.similarity)
        return {
            "name": name,
            "searched": query,
            "matched": best.game_name,
            "similarity": best.similarity,
            "main_story": best.main_story,
            "main_extra": best.main_extra,
            "completionist": best.completionist,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/exophase-origin-debug")
async def exophase_origin_debug(game_id: int | None = Query(None), player_id: int | None = Query(None)):
    """
    Temporary diagnostic: dumps Exophase's raw public API response for the
    "origin" (EA) environment, using the already-configured Exophase session
    (EXOPHASE_PLAYER_ID/EXOPHASE_ACCESS_TOKEN — the same ones the Xbox 360
    icon-enrichment feature uses). This is a much steadier foundation for EA
    achievement data than EA's own unofficial API: Exophase has already done
    that reverse-engineering, and exposes it through a public per-player API
    keyed by our own Exophase login rather than a fragile EA access token.

    With no params: dumps the raw games list for environment=origin.
    With ?game_id=&player_id=: dumps the raw "earned achievements" response
    for that game (player_id here is Exophase's per-game master_playerid,
    found in the games-list dump, not our own EXOPHASE_PLAYER_ID).
    """
    from app.platforms.exophase import _API, _BASE_HEADERS

    if not config.EXOPHASE_PLAYER_ID or not config.EXOPHASE_ACCESS_TOKEN:
        return {"error": "EXOPHASE_PLAYER_ID / EXOPHASE_ACCESS_TOKEN not configured."}

    headers = dict(_BASE_HEADERS)
    headers["Cookie"] = f"ACCESS_TOKEN={config.EXOPHASE_ACCESS_TOKEN}"

    async with httpx.AsyncClient(timeout=30) as client:
        if game_id and player_id:
            r = await client.get(
                f"{_API}/public/player/{player_id}/game/{game_id}/earned",
                params={"last": 9999999999999},
                headers=headers,
            )
        else:
            r = await client.get(
                f"{_API}/public/player/{config.EXOPHASE_PLAYER_ID}/games",
                params={"page": 1, "environment": "origin", "sort": 1, "showHidden": 0, "query": ""},
                headers=headers,
            )
        result = {"status_code": r.status_code}
        try:
            result["body"] = r.json()
        except Exception:
            result["body_text"] = r.text[:2000]
        return result


@app.post("/api/exophase-refresh", status_code=202)
async def exophase_refresh():
    """Clear all Exophase-sourced icons and re-enrich from scratch."""
    pool = await db.get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE achievements SET icon_url = NULL "
            "WHERE icon_url LIKE '%exophase%'"
        )
    asyncio.create_task(_enrich_exophase_360_icons())
    return {"status": "started"}


@app.post("/api/exophase-import-icons")
async def exophase_import_icons(payload: dict):
    """
    Accept a JSON body {game_name: str, icons: {achievement_name: icon_url}}
    and update matching achievements in the DB.
    """
    from app.platforms.exophase import _to_slug

    game_name = payload.get("game_name", "")
    icons: dict = payload.get("icons") or {}
    if not game_name or not icons:
        return {"error": "game_name and icons required"}

    pool = await db.get_pool()
    matched = None
    async with pool.connection() as conn:
        rows = await _fetch(
            conn,
            """
            SELECT a.id, a.name FROM achievements a
            JOIN platform_games pg ON pg.id = a.platform_game_id
            WHERE pg.platform = 'xbox' AND pg.name = %s
            """,
            game_name,
        )

    if not rows:
        # Try slug match, then prefix match (e.g. DB "Guitar Hero III" vs Exophase "Guitar Hero III: Legends of Rock")
        async with pool.connection() as conn:
            all_games = await _fetch(conn, "SELECT id, name FROM platform_games WHERE platform = 'xbox'")
        db_slug = _to_slug(game_name)
        matched = next((g for g in all_games if _to_slug(g["name"]) == db_slug), None)
        if not matched:
            matched = next((g for g in all_games if db_slug.startswith(_to_slug(g["name"]) + "-") or _to_slug(g["name"]).startswith(db_slug + "-")), None)
        if not matched:
            return {"error": f"No xbox game found matching '{game_name}'"}
        async with pool.connection() as conn:
            rows = await _fetch(
                conn,
                "SELECT a.id, a.name FROM achievements a WHERE a.platform_game_id = %s",
                matched["id"],
            )

    updated = 0
    created = 0
    slug_icons = {_to_slug(k): v for k, v in icons.items()}

    # Determine platform_game_id for potential inserts
    async with pool.connection() as conn:
        pg_row = await _fetchrow(
            conn,
            "SELECT id FROM platform_games WHERE platform = 'xbox' AND name = %s",
            game_name,
        )
        if not pg_row and matched:
            pg_id = matched["id"]
        elif pg_row:
            pg_id = pg_row["id"]
        else:
            pg_id = None

        # Get linked_account_id for xbox (to create user_achievement rows)
        la_row = await _fetchrow(
            conn,
            "SELECT id FROM linked_accounts WHERE platform = 'xbox' LIMIT 1",
        )
        linked_id = la_row["id"] if la_row else None

    async with pool.connection() as conn:
        existing_slugs = {_to_slug(ach["name"]) for ach in rows}
        for ach in rows:
            icon_url = slug_icons.get(_to_slug(ach["name"]))
            if icon_url:
                await conn.execute(
                    "UPDATE achievements SET icon_url = %s WHERE id = %s",
                    (icon_url, ach["id"]),
                )
                updated += 1

        # Create achievements that don't exist in DB yet
        if pg_id and linked_id:
            for name, icon_url in icons.items():
                slug = _to_slug(name)
                if slug not in existing_slugs:
                    synth_id = f"exo-{slug}"
                    ach_id = await db.upsert_achievement(
                        conn, pg_id, synth_id, name, None, icon_url, None, None
                    )
                    await db.upsert_user_achievement(conn, linked_id, ach_id, False, None)
                    created += 1

    return {"game_name": game_name, "achievements_found": len(rows), "icons_updated": updated, "achievements_created": created}


@app.post("/api/hltb-refresh", status_code=202)
async def hltb_refresh():
    """Reset all HLTB data and re-enrich from scratch."""
    pool = await db.get_pool()
    async with pool.connection() as conn:
        await conn.execute("UPDATE platform_games SET hltb_main=NULL, hltb_extra=NULL, hltb_complete=NULL")
    asyncio.create_task(_enrich_hltb())
    return {"status": "started"}


@app.post("/api/igdb-refresh", status_code=202)
async def igdb_refresh(platform: str | None = None):
    """Re-run IGDB enrichment including previously failed (-1) lookups.
    Pass ?platform=xbox to reset and retry only Xbox games."""
    pool = await db.get_pool()
    if platform:
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE platform_games SET igdb_id = NULL WHERE platform = %s AND igdb_id = -1",
                (platform,),
            )
        log.info("Reset failed IGDB lookups for platform=%s", platform)
    asyncio.create_task(_enrich_igdb(retry_failed=True))
    return {"status": "started"}


@app.post("/api/sgdb-refresh", status_code=202)
async def sgdb_refresh(force: bool = False):
    """
    Re-run SteamGridDB enrichment. By default only fills in games that don't
    have a cover yet; pass ?force=true to re-fetch every cover from scratch
    (e.g. after a change to which SGDB asset type is preferred).
    """
    asyncio.create_task(_enrich_sgdb(retry_failed=True, force=force))
    return {"status": "started"}


async def _sgdb_art_for(client, headers: dict, base: str, game_id: int) -> dict:
    """Fetch both Heroes (no logo, preferred) and Grids (may include a logo) for a game."""
    heroes: list[str] = []
    hr = await client.get(f"{base}/heroes/game/{game_id}", headers=headers, params={"limit": 8})
    if hr.status_code == 200 and hr.json().get("data"):
        heroes = [h["url"] for h in hr.json()["data"]]

    grids: list[str] = []
    for dims in ("460x215", "920x430"):
        gr = await client.get(
            f"{base}/grids/game/{game_id}",
            headers=headers,
            params={"dimensions": dims, "limit": 6},
        )
        if gr.status_code == 200 and gr.json().get("data"):
            grids.extend(g["url"] for g in gr.json()["data"])
    return {"heroes": heroes, "grids": grids}


@app.get("/api/sgdb-search")
async def sgdb_search(q: str):
    """
    Search SteamGridDB by name or numeric game ID. Returns both Heroes (wide
    banner art with no logo baked in — the best fit for our full-bleed cards)
    and Grids (may include the game's logo) so the user can pick either.
    """
    if not config.SGDB_API_KEY:
        return {"error": "SGDB not configured"}
    import httpx
    headers = {"Authorization": f"Bearer {config.SGDB_API_KEY}"}
    base = "https://www.steamgriddb.com/api/v2"
    async with httpx.AsyncClient(timeout=15) as client:
        # If query is a numeric ID, fetch art directly
        if q.strip().isdigit():
            game_id = int(q.strip())
            art = await _sgdb_art_for(client, headers, base, game_id)
            return {"games": [{"id": game_id, "name": f"Game ID {game_id}", **art}]}

        resp = await client.get(f"{base}/search/autocomplete/{q}", headers=headers)
        if resp.status_code != 200:
            return {"games": []}
        games = resp.json().get("data") or []
        results = []
        for game in games[:5]:
            art = await _sgdb_art_for(client, headers, base, game["id"])
            results.append({"id": game["id"], "name": game["name"], **art})
        return {"games": results}


@app.post("/api/sgdb-set")
async def sgdb_set(platform_game_id: int, url: str):
    """Manually set the SGDB cover URL for a game."""
    pool = await db.get_pool()
    async with pool.connection() as conn:
        await db.set_sgdb_cover(conn, platform_game_id, url)
    return {"status": "ok"}


@app.get("/api/sync/progress")
async def sync_progress():
    return _sync_progress


@app.get("/api/unlocks/recent")
async def recent_unlocks(since: str = ""):
    """
    Achievement-unlock events collected during syncs, for the frontend to
    poll and toast. Pass `since` back as the `unlocked_at` of the last event
    you've already shown; omit it to get the most recent handful.
    """
    events = _unlock_events
    if since:
        events = [e for e in events if e["unlocked_at"] > since]
    return {"events": events[-15:]}


@app.post("/api/sync", status_code=202)
async def trigger_sync():
    if _sync_lock.locked():
        raise HTTPException(status_code=409, detail="Sync already in progress")
    asyncio.create_task(run_sync())
    return {"status": "started"}


# ── Backups ───────────────────────────────────────────────────────────────────
# Everything Achievist knows — synced achievements and connected-account
# credentials alike — lives in Postgres, so a pg_dump backup covers all of it.

@app.get("/api/backups")
async def get_backups():
    return {
        "backups": backup.list_backups(),
        "keep_count": config.BACKUP_KEEP_COUNT,
        "interval_hours": config.BACKUP_INTERVAL_HOURS,
    }


@app.post("/api/backups", status_code=201)
async def create_backup_now():
    try:
        path = await backup.create_backup()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"filename": path.name}


@app.get("/api/backups/{filename}")
async def download_backup(filename: str):
    try:
        path = backup.resolve_backup_path(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@app.delete("/api/backups/{filename}", status_code=204)
async def remove_backup(filename: str):
    try:
        backup.delete_backup(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    return None


# ── Connected-account management ─────────────────────────────────────────────

def _redact_account(row: dict) -> dict:
    """Serialize an account for the UI, masking secret credential values."""
    platform_cls = PLATFORMS.get(row["platform"])
    secret_fields = set()
    if platform_cls:
        secret_fields = {f["name"] for f in platform_cls.CONNECT_FIELDS if f.get("secret")}
    creds = row.get("credentials") or {}
    safe_creds = {
        k: ("••••••" if k in secret_fields and v else v)
        for k, v in creds.items()
    }
    return {
        "id": row["id"],
        "platform": row["platform"],
        "external_id": row["external_id"],
        "display_name": row["display_name"],
        "enabled": row["enabled"],
        "status": row.get("status"),
        "last_error": row.get("last_error"),
        "last_synced_at": row.get("last_synced_at"),
        "credentials": safe_creds,
    }


@app.get("/api/platforms")
async def list_platforms():
    """Connection schemas for every supported platform (drives the Settings UI)."""
    return [cls.connect_schema() for cls in PLATFORMS.values()]


@app.get("/api/accounts")
async def list_accounts():
    pool = await db.get_pool()
    async with pool.connection() as conn:
        rows = await db.list_accounts(conn)
    return [_redact_account(r) for r in rows]


@app.post("/api/accounts", status_code=201)
async def connect_account(payload: dict):
    """
    Connect (or update) an account.
    Body: {"platform": "steam", "external_id": "...", "credentials": {...}}
    For fixed-identity platforms (gw2, xbox, ubisoft) external_id is optional.
    """
    platform = (payload.get("platform") or "").strip()
    platform_cls = PLATFORMS.get(platform)
    if not platform_cls:
        raise HTTPException(status_code=400, detail=f"Unknown platform '{platform}'")

    raw_creds = payload.get("credentials") or {}
    # Drop blanks and masked placeholders so an unchanged secret keeps its value.
    creds = {
        k: v for k, v in raw_creds.items()
        if isinstance(v, str) and v.strip() and v.strip() != "••••••"
    }
    # external_id comes from a dedicated field, the credentials, or a fixed default
    external_id = (
        payload.get("external_id")
        or creds.pop("external_id", None)
        or platform_cls.EXTERNAL_ID
        or creds.get("username")  # RA: default target user to the account username
    )
    if not external_id:
        raise HTTPException(status_code=400, detail="external_id is required for this platform")

    pool = await db.get_pool()
    async with pool.connection() as conn:
        # Merge with any existing credentials so editing one field doesn't wipe the rest.
        existing = await db.get_account_by_key(conn, platform, str(external_id))
        merged = {**(existing["credentials"] if existing else {}), **creds}

        # Validate required fields against the merged result (skip external_id).
        for field in platform_cls.CONNECT_FIELDS:
            if field["name"] == "external_id":
                continue
            if field.get("required") and not merged.get(field["name"]):
                raise HTTPException(status_code=400, detail=f"Missing required field: {field['label']}")

        await db.delete_other_accounts_for_platform(conn, platform, str(external_id))
        account_id = await db.upsert_account(conn, platform, str(external_id), merged)
    return {"id": account_id, "status": "connected"}


@app.delete("/api/accounts/{account_id}", status_code=204)
async def disconnect_account(account_id: int):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        acct = await db.get_account(conn, account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        await db.delete_account(conn, account_id)
    return None


@app.post("/api/accounts/{account_id}/sync", status_code=202)
async def sync_account(account_id: int):
    if _sync_lock.locked():
        raise HTTPException(status_code=409, detail="Sync already in progress")
    pool = await db.get_pool()
    async with pool.connection() as conn:
        acct = await db.get_account(conn, account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    asyncio.create_task(run_sync(account_id=account_id))
    return {"status": "started"}


@app.post("/api/xbox-dedup")
async def xbox_dedup():
    """
    Consolidate duplicate Xbox accounts: keep the linked account with the most
    stored games and delete the others (removes duplicate library entries).
    """
    pool = await db.get_pool()
    async with pool.connection() as conn:
        rows = await _fetch(
            conn,
            """
            SELECT la.id, la.external_id, COUNT(ug.id) AS games
            FROM linked_accounts la
            LEFT JOIN user_games ug ON ug.linked_account_id = la.id
            WHERE la.platform = 'xbox'
            GROUP BY la.id, la.external_id
            ORDER BY games DESC
            """,
        )
        if len(rows) <= 1:
            return {"status": "ok", "removed": 0, "kept": rows[0]["external_id"] if rows else None}
        keep = rows[0]
        removed = []
        for r in rows[1:]:
            await db.delete_account(conn, r["id"])
            removed.append(r["external_id"])
    return {"status": "ok", "kept": keep["external_id"], "kept_games": keep["games"], "removed": removed}


@app.post("/api/xbox-dedup-games")
async def xbox_dedup_games():
    """
    Merge duplicate Xbox games: Xbox's titleHistory returns a separate titleId
    per platform release of the same game (e.g. console vs PC/Game Pass), which
    show up as visual duplicates. For each set of platform_games sharing the
    same (lowercased) name, keep the one with the most achievements earned and
    delete the rest.
    """
    pool = await db.get_pool()
    merged = []
    async with pool.connection() as conn:
        groups = await _fetch(
            conn,
            """
            SELECT lower(pg.name) AS key, array_agg(pg.id) AS ids, array_agg(pg.name) AS names
            FROM platform_games pg
            WHERE pg.platform = 'xbox'
            GROUP BY lower(pg.name)
            HAVING COUNT(*) > 1
            """,
        )
        for g in groups:
            ids = g["ids"]
            rows = await _fetch(
                conn,
                """
                SELECT pg.id, COALESCE(MAX(ug.earned_achievements), 0) AS earned,
                       COALESCE(MAX(ug.total_achievements), 0) AS total
                FROM platform_games pg
                LEFT JOIN user_games ug ON ug.platform_game_id = pg.id
                WHERE pg.id = ANY(%s)
                GROUP BY pg.id
                ORDER BY earned DESC, total DESC
                """,
                ids,
            )
            keep_id = rows[0]["id"]
            remove_ids = [r["id"] for r in rows[1:]]
            if remove_ids:
                await conn.execute("DELETE FROM platform_games WHERE id = ANY(%s)", (remove_ids,))
            merged.append({"name": g["names"][0], "kept": keep_id, "removed": remove_ids})
    return {"status": "ok", "merged": merged}


@app.get("/api/psn-service-status")
async def psn_service_status():
    """Whether the backend PlayStation session is present and still valid."""
    from app.psn_auth import service_ticket_valid
    return {"signed_in": await service_ticket_valid()}


@app.post("/api/psn-service-ticket")
async def psn_service_ticket(payload: dict):
    """
    Store the backend PlayStation credential from an npsso token.
    Body: {"npsso": "<64-char token from ca.account.sony.com/api/v1/ssocookie>"}
    """
    from app.psn_auth import exchange_npsso
    npsso = (payload.get("npsso") or "").strip()
    if not npsso:
        raise HTTPException(status_code=400, detail="npsso is required")
    try:
        await exchange_npsso(npsso)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "message": "PlayStation session saved. You can now add accounts by Online ID."}


@app.get("/api/ubisoft-service-status")
async def ubisoft_service_status():
    """Whether the backend Ubisoft service ticket is present and still valid."""
    from app.ubisoft_auth import service_ticket_valid
    return {"signed_in": await service_ticket_valid()}


@app.post("/api/ubisoft-service-ticket")
async def ubisoft_service_ticket(payload: dict):
    """
    Store the backend Ubisoft service credential from a browser session ticket.
    Body: {"ticket": "<ewog… value from connect.ubisoft.com localStorage>"}
    """
    from app.ubisoft_auth import save_service_ticket
    ticket = (payload.get("ticket") or "").strip()
    if not ticket:
        raise HTTPException(status_code=400, detail="ticket is required")
    try:
        profile_id = await save_service_ticket(ticket)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "profile_id": profile_id,
            "message": "Ubisoft service session saved. You can now add accounts by username."}


@app.get("/api/xbox-service-status")
async def xbox_service_status():
    """Whether a backend Xbox sign-in exists (so gamertag lookups can work)."""
    from app.xbox_auth import load_refresh_token
    return {"signed_in": bool(config.XBOX_REFRESH_TOKEN or load_refresh_token())}


@app.get("/api/xbox-setup")
async def xbox_setup():
    """Start device code flow. Returns a user_code to enter at microsoft.com/devicelogin."""
    from app.xbox_auth import start_device_flow
    try:
        data = await start_device_flow()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "user_code": data.get("user_code"),
        "verification_uri": data.get("verification_uri"),
        "device_code": data.get("device_code"),
        "expires_in_seconds": data.get("expires_in"),
        "interval": data.get("interval", 5),
        "instructions": (
            f"Go to {data.get('verification_uri')} and enter code {data.get('user_code')}. "
            f"Then poll GET /api/xbox-setup-poll?device_code=<device_code> every {data.get('interval', 5)}s until status=done."
        ),
    }


@app.get("/api/xbox-setup-poll")
async def xbox_setup_poll(device_code: str):
    """Poll for device code flow completion. Call repeatedly until status=done."""
    from app.xbox_auth import poll_device_flow, get_tokens
    try:
        refresh_token = await poll_device_flow(device_code)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if refresh_token is None:
        return {"status": "pending"}
    try:
        tokens = await get_tokens(refresh_token)
        xuid = tokens.xuid
    except Exception as e:
        xuid = "unknown"
        log.warning("Could not fetch XUID after auth: %s", e)
    return {
        "status": "done",
        "xuid": xuid,
        "message": "Xbox authenticated successfully. The refresh token has been saved. Run a sync to import your games.",
        "env_hint": f"You can also set XBOX_REFRESH_TOKEN={refresh_token} in your .env for persistence across container recreations.",
    }


@app.get("/api/xbox-360-debug")
async def xbox_360_debug(game_id: int):
    """Return raw contract v1 achievement API responses for a 360 game (use the Achievist game_id from /game/<id> URL)."""
    from app.xbox_auth import get_tokens, load_refresh_token
    from app.platforms.xbox import _xbl_headers, _ACH
    # Look up the Xbox title_id from the DB
    pool = await db.get_pool()
    async with pool.connection() as conn:
        row = await _fetchrow(conn, "SELECT platform_app_id FROM platform_games WHERE id = %s", game_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Game {game_id} not found")
    title_id = row["platform_app_id"]
    refresh_token = config.XBOX_REFRESH_TOKEN or load_refresh_token()
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Xbox not configured")
    tokens = await get_tokens(refresh_token)
    xuid = tokens.xuid
    async with httpx.AsyncClient(timeout=30) as client:
        title_v1_resp = await client.get(
            f"{_ACH}/titles/{title_id}/achievements",
            params={"maxItems": 5},
            headers=_xbl_headers(tokens, contract="1"),
        )
        user_v1_resp = await client.get(
            f"{_ACH}/users/xuid({xuid})/achievements",
            params={"titleId": title_id, "maxItems": 5},
            headers=_xbl_headers(tokens, contract="1"),
        )
        user_v2_resp = await client.get(
            f"{_ACH}/users/xuid({xuid})/achievements",
            params={"titleId": title_id, "maxItems": 5},
            headers=_xbl_headers(tokens, contract="2"),
        )
        title_v2_resp = await client.get(
            f"{_ACH}/titles/{title_id}/achievements",
            params={"maxItems": 5},
            headers=_xbl_headers(tokens, contract="2"),
        )
    return {
        "game_id": game_id,
        "xbox_title_id": title_id,
        "title_v1_status": title_v1_resp.status_code,
        "title_v1_sample": title_v1_resp.json() if title_v1_resp.status_code == 200 else title_v1_resp.text,
        "user_v1_status": user_v1_resp.status_code,
        "user_v1_sample": user_v1_resp.json() if user_v1_resp.status_code == 200 else user_v1_resp.text,
        "user_v2_status": user_v2_resp.status_code,
        "user_v2_sample": user_v2_resp.json() if user_v2_resp.status_code == 200 else user_v2_resp.text,
        "title_v2_status": title_v2_resp.status_code,
        "title_v2_sample": title_v2_resp.json() if title_v2_resp.status_code == 200 else title_v2_resp.text,
    }


async def status():
    pool = await db.get_pool()
    async with pool.connection() as conn:
        accounts = await _fetch(
            conn,
            "SELECT id, platform, external_id, display_name, enabled, last_synced_at FROM linked_accounts",
        )
        runs = await _fetch(
            conn,
            "SELECT id, platform, started_at, finished_at, status, detail FROM sync_runs ORDER BY started_at DESC LIMIT 10",
        )
    return {
        "syncing": _sync_lock.locked(),
        "accounts": [dict(r) for r in accounts],
        "recent_runs": [dict(r) for r in runs],
    }



@app.get("/api/exophase-debug")
async def exophase_debug():
    """Debug Exophase integration: show games list fetch result and sample icon lookup."""
    from app.platforms.exophase import fetch_games_list, fetch_earned_icons, _to_slug

    if not config.EXOPHASE_PLAYER_ID:
        return {"error": "EXOPHASE_PLAYER_ID not configured"}

    access_token = config.EXOPHASE_ACCESS_TOKEN
    if not access_token:
        return {"error": "EXOPHASE_ACCESS_TOKEN not set — copy the ACCESS_TOKEN cookie from your browser on exophase.com"}

    pool = await db.get_pool()
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            exo_games = await fetch_games_list(client, config.EXOPHASE_PLAYER_ID, access_token)
        except Exception as e:
            return {"error": f"Games list fetch failed: {e}"}

    xbox_360_games = [g for g in exo_games if g["is_360"]]
    all_games_slugs = {_to_slug(g["title"]): g["master_id"] for g in exo_games}
    xbox_360_slugs = {_to_slug(g["title"]): g["master_id"] for g in xbox_360_games}

    # Get Xbox games in our DB that have achievements with no icons
    async with pool.connection() as conn:
        db_rows = await _fetch(
            conn,
            """
            SELECT DISTINCT pg.name, COUNT(a.id) FILTER (WHERE a.icon_url IS NULL) AS missing_icons
            FROM platform_games pg
            JOIN achievements a ON a.platform_game_id = pg.id
            WHERE pg.platform = 'xbox'
            GROUP BY pg.name
            ORDER BY missing_icons DESC
            """,
        )

    match_results = []
    for row in db_rows:
        db_slug = _to_slug(row["name"])
        exo_slug = _EXOPHASE_TITLE_ALIASES.get(db_slug, db_slug)
        aliased = exo_slug != db_slug
        match_results.append({
            "db_game": row["name"],
            "slug": db_slug,
            "exo_slug": exo_slug if aliased else None,
            "missing_icons": row["missing_icons"],
            "exophase_match": all_games_slugs.get(exo_slug),
            "is_360_match": xbox_360_slugs.get(exo_slug),
        })

    return {
        "exophase_total_games": len(exo_games),
        "exophase_360_games": len(xbox_360_games),
        "exophase_360_titles": [g["title"] for g in xbox_360_games],
        "db_xbox_games_with_missing_icons": match_results,
    }


import os

# Serve the built React SPA from app/webdist (produced by `vite build`).
# Falls back to the legacy static dir if the build output isn't present.
_WEB_DIR = os.path.abspath("app/webdist" if os.path.isdir("app/webdist") else "app/static")
_INDEX = os.path.join(_WEB_DIR, "index.html")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    # Serve real build assets (JS/CSS/images) directly; fall back to index.html
    # for client-side routes so the SPA can handle them.
    if full_path:
        candidate = os.path.normpath(os.path.join(_WEB_DIR, full_path))
        if candidate.startswith(_WEB_DIR) and os.path.isfile(candidate):
            return FileResponse(candidate)
    return FileResponse(_INDEX)
