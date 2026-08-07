import asyncio
import logging

import httpx
from contextlib import asynccontextmanager

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import auth, backup, config, db, hltb as hltb_names
from app.db import _fetch, _fetchrow
from app.platforms import PLATFORMS
from app.platforms import trueachievements

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


def _record_unlock_events(rows: list[dict], user_id: int) -> None:
    for r in rows:
        _unlock_events.append({
            "user_id": user_id,
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
                    _record_unlock_events(new_rows, account["user_id"])
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


async def run_sync(account_id: int | None = None, user_id: int | None = None) -> None:
    """
    Syncs every enabled account by default (the scheduled background job).
    Pass user_id to scope a run to one logged-in user's own accounts (the
    manual "Sync" button), or account_id for a single account.
    """
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
            accounts = await db.list_all_accounts(conn)
        accounts = [a for a in accounts if a.get("enabled", True)]
        if user_id is not None:
            accounts = [a for a in accounts if a["user_id"] == user_id]
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

    # One-time migration: deployments that predate multi-user support get
    # their existing data attached to a freshly created admin account.
    generated_password = await db.migrate_single_user_to_admin(pool)
    if generated_password:
        log.warning("=" * 60)
        log.warning("Migrated existing data to a new admin account.")
        log.warning("  username: admin")
        log.warning("  password: %s", generated_password)
        log.warning("Log in and change this password from Account Settings.")
        log.warning("=" * 60)

    # One-time migration: seed DB-backed accounts from any legacy .env config.
    # Only fills in platforms that don't already have a connected account, so
    # credentials edited in the UI are never overwritten by stale env values.
    # Env vars are server-level config (the operator's own credentials), so
    # these attach to the first admin account — skipped entirely if no admin
    # exists yet (a brand new install where first-run setup hasn't happened).
    env_seeds = config.env_seed_accounts()
    if env_seeds:
        async with pool.connection() as conn:
            admin = await _fetchrow(conn, "SELECT id FROM users WHERE is_admin ORDER BY id LIMIT 1")
        if admin:
            for seed in env_seeds:
                async with pool.connection() as conn:
                    if not await db.account_exists(conn, admin["id"], seed["platform"]):
                        await db.upsert_account(
                            conn, admin["id"], seed["platform"], seed["external_id"],
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


# ── Auth ──────────────────────────────────────────────────────────────────
# Phase 1 of multi-user support: users/sessions exist and login works, but
# most endpoints below this point don't filter by the logged-in user yet
# (that's a separate, larger follow-up). get_current_user/require_user are
# in place now so that work can build on them incrementally.

async def get_current_user(achievist_session: str | None = Cookie(None)) -> dict | None:
    if not achievist_session:
        return None
    pool = await db.get_pool()
    async with pool.connection() as conn:
        return await db.get_session_user(conn, achievist_session)


async def require_user(user: dict | None = Depends(get_current_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


async def require_admin(user: dict = Depends(require_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@app.get("/api/auth/status")
async def auth_status(user: dict | None = Depends(get_current_user)):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        needs_setup = (await db.count_users(conn)) == 0
    return {"logged_in": user is not None, "user": user, "needs_setup": needs_setup}


@app.post("/api/auth/setup")
async def auth_setup(payload: dict, response: Response):
    """Create the first (admin) account. Only allowed while no users exist."""
    pool = await db.get_pool()
    async with pool.connection() as conn:
        if (await db.count_users(conn)) > 0:
            raise HTTPException(status_code=400, detail="Setup already completed")
        username = (payload.get("username") or "").strip()
        password = payload.get("password") or ""
        if not username or len(password) < 8:
            raise HTTPException(status_code=400, detail="Username required; password must be 8+ characters")
        user = await db.create_user(conn, username, auth.hash_password(password), is_admin=True)
        await _start_session(conn, response, user["id"])
        return {"id": user["id"], "username": user["username"], "is_admin": True}


@app.post("/api/auth/login")
async def auth_login(payload: dict, response: Response):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    pool = await db.get_pool()
    async with pool.connection() as conn:
        user = await db.get_user_by_username(conn, username)
        if not user or not auth.verify_password(password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        await _start_session(conn, response, user["id"])
        return {
            "id": user["id"], "username": user["username"],
            "display_name": user["display_name"], "avatar_url": user["avatar_url"],
            "is_admin": user["is_admin"],
        }


@app.post("/api/auth/logout")
async def auth_logout(response: Response, achievist_session: str | None = Cookie(None)):
    if achievist_session:
        pool = await db.get_pool()
        async with pool.connection() as conn:
            await db.delete_session(conn, achievist_session)
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"status": "ok"}


async def _start_session(conn, response: Response, user_id: int) -> None:
    token = auth.new_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=auth.SESSION_TTL_DAYS)
    await db.create_session(conn, token, user_id, expires_at)
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        max_age=auth.SESSION_TTL_DAYS * 24 * 3600,
        httponly=True, samesite="lax",
    )


@app.get("/api/users")
async def list_users(admin: dict = Depends(require_admin)):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        return await db.list_users(conn)


@app.post("/api/users")
async def create_user_account(payload: dict, admin: dict = Depends(require_admin)):
    """Admin-only: create an account for a family member (e.g. a child)."""
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or len(password) < 8:
        raise HTTPException(status_code=400, detail="Username required; password must be 8+ characters")
    pool = await db.get_pool()
    async with pool.connection() as conn:
        if await db.get_user_by_username(conn, username):
            raise HTTPException(status_code=400, detail="That username is already taken")
        user = await db.create_user(
            conn, username, auth.hash_password(password),
            display_name=payload.get("display_name"), is_admin=bool(payload.get("is_admin")),
        )
        return user


@app.delete("/api/users/{user_id}")
async def delete_user_account(user_id: int, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Can't delete your own account while logged in as it")
    pool = await db.get_pool()
    async with pool.connection() as conn:
        await db.delete_user(conn, user_id)
    return {"status": "ok"}


@app.get("/api/profile")
async def get_profile(user: dict = Depends(require_user)):
    return {
        "display_name": user["display_name"],
        "avatar_url": user["avatar_url"],
        "background_url": user["background_url"],
        "share_stats": user["share_stats"],
    }


@app.put("/api/profile")
async def update_profile(payload: dict, user: dict = Depends(require_user)):
    display_name = (payload.get("display_name") or "").strip() or None
    avatar_url = (payload.get("avatar_url") or "").strip() or None
    background_url = (payload.get("background_url") or "").strip() or None
    share_stats = bool(payload.get("share_stats"))
    pool = await db.get_pool()
    async with pool.connection() as conn:
        await db.update_user_profile(conn, user["id"], display_name, avatar_url, share_stats, background_url)
    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "background_url": background_url,
        "share_stats": share_stats,
    }


@app.get("/api/leaderboard")
async def leaderboard(user: dict = Depends(require_user)):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        rows = await db.get_leaderboard(conn, user["id"])
    return {"entries": rows, "you_share": user["share_stats"]}


@app.get("/api/leaderboard/games")
async def leaderboard_games(user: dict = Depends(require_user)):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        rows = await db.get_shared_games(conn, user["id"])
    return {"games": rows, "you_share": user["share_stats"]}


@app.get("/api/leaderboard/games/{platform_game_id}/compare")
async def compare_game_achievements(platform_game_id: int, user: dict = Depends(require_user)):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        await _maybe_schedule_guide_refresh(conn, platform_game_id)
        result = await db.get_game_comparison(conn, user["id"], platform_game_id)
    if not result:
        raise HTTPException(status_code=404, detail="Game not found in your library")
    return result


@app.get("/api/summary")
async def summary(user: dict = Depends(require_user)):
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
            JOIN linked_accounts la ON la.id = ug.linked_account_id
            WHERE la.user_id = %s
            """,
            user["id"],
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
            JOIN linked_accounts la ON la.id = ug.linked_account_id
            WHERE la.user_id = %s
            GROUP BY pg.platform
            """,
            user["id"],
        )
        last_synced = await _fetch(
            conn,
            """
            SELECT sr.platform, MAX(sr.finished_at) AS last_sync
            FROM sync_runs sr
            JOIN linked_accounts la ON la.id = sr.linked_account_id
            WHERE sr.status = 'ok' AND la.user_id = %s
            GROUP BY sr.platform
            """,
            user["id"],
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
    user: dict = Depends(require_user),
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

    filters = ["ug.total_achievements > 0", "la.user_id = %s"]
    params: list = [user["id"]]

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
            JOIN linked_accounts la ON la.id = ug.linked_account_id
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
            JOIN linked_accounts la ON la.id = ug.linked_account_id
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
    user: dict = Depends(require_user),
):
    """Search achievements across the whole library, not just within one game."""
    order = {
        "rarity": "a.rarity_pct ASC NULLS LAST, a.id",
        "name": "a.name ASC, a.id",
        "points": "a.points DESC NULLS LAST, a.id",
        "unlocked_at": "ua.unlocked_at DESC NULLS LAST, a.id",
    }[sort]

    # Both the JOIN's "la.user_id = %s" and any filter placeholders below are
    # interpolated into the same query string, so this param must come first
    # to match its position in the SQL text (right after the games-I-own
    # join, before the WHERE filters).
    filters = []
    params: list = [user["id"]]

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
            JOIN user_games ug ON ug.platform_game_id = pg.id
            JOIN linked_accounts la ON la.id = ug.linked_account_id AND la.user_id = %s
            LEFT JOIN user_achievements ua ON ua.achievement_id = a.id AND ua.linked_account_id = la.id
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
            JOIN user_games ug ON ug.platform_game_id = pg.id
            JOIN linked_accounts la ON la.id = ug.linked_account_id AND la.user_id = %s
            LEFT JOIN user_achievements ua ON ua.achievement_id = a.id AND ua.linked_account_id = la.id
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
async def game_detail(platform_game_id: int, user: dict = Depends(require_user)):
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
                ug.linked_account_id,
                ug.playtime_minutes,
                ug.earned_achievements,
                ug.total_achievements,
                ug.completion_pct,
                ug.last_played_at
            FROM user_games ug
            JOIN platform_games pg ON pg.id = ug.platform_game_id
            JOIN linked_accounts la ON la.id = ug.linked_account_id AND la.user_id = %s
            LEFT JOIN igdb_games ig ON ig.id = pg.igdb_id AND pg.igdb_id > 0
            WHERE pg.id = %s
            """,
            user["id"], platform_game_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Game not found")
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
                WHERE a.platform_game_id = %s AND ua.linked_account_id = %s
                  AND ua.unlocked = true AND a.rarity_pct IS NOT NULL
            ) sub GROUP BY tier ORDER BY MIN(
                CASE tier
                    WHEN 'Legendary' THEN 1 WHEN 'Epic' THEN 2
                    WHEN 'Rare' THEN 3 WHEN 'Uncommon' THEN 4 ELSE 5
                END
            )
            """,
            platform_game_id, row["linked_account_id"],
        )
        points_row = await _fetchrow(
            conn,
            """
            SELECT SUM(a.points) AS total_points
            FROM user_achievements ua
            JOIN achievements a ON a.id = ua.achievement_id
            WHERE a.platform_game_id = %s AND ua.linked_account_id = %s
              AND ua.unlocked = true AND a.points IS NOT NULL
            """,
            platform_game_id, row["linked_account_id"],
        )
    if not row:
        raise HTTPException(status_code=404, detail="Game not found")
    result = dict(row)
    result["rarity_summary"] = [dict(r) for r in rarity_summary]
    result["total_points"] = int(points_row["total_points"] or 0) if points_row else 0
    return result


@app.get("/api/statistics")
async def statistics(user: dict = Depends(require_user)):
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
                JOIN linked_accounts la ON la.id = ug.linked_account_id AND la.user_id = %s
                WHERE ug.total_achievements > 0
                """,
                user["id"],
            )

            daily_max = await _fetchrow(
                conn,
                """
                SELECT COUNT(*) AS cnt
                FROM user_achievements ua
                JOIN linked_accounts la ON la.id = ua.linked_account_id AND la.user_id = %s
                WHERE ua.unlocked = true AND ua.unlocked_at IS NOT NULL
                GROUP BY ua.unlocked_at::date
                ORDER BY cnt DESC LIMIT 1
                """,
                user["id"],
            )

            monthly_max = await _fetchrow(
                conn,
                """
                SELECT COUNT(*) AS cnt
                FROM user_achievements ua
                JOIN linked_accounts la ON la.id = ua.linked_account_id AND la.user_id = %s
                WHERE ua.unlocked = true AND ua.unlocked_at IS NOT NULL
                GROUP BY DATE_TRUNC('month', ua.unlocked_at)
                ORDER BY cnt DESC LIMIT 1
                """,
                user["id"],
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
                    JOIN linked_accounts la ON la.id = ua.linked_account_id AND la.user_id = %s
                    WHERE ua.unlocked = true AND a.rarity_pct IS NOT NULL
                ) sub
                GROUP BY tier
                ORDER BY MIN(rarity_pct)
                """,
                user["id"],
            )

            completion_dist = await _fetch(
                conn,
                """
                SELECT bracket, COUNT(*) AS cnt
                FROM (
                    SELECT
                        CASE
                            WHEN ug.completion_pct = 0         THEN '0%%'
                            WHEN ug.completion_pct <= 25       THEN '1-25%%'
                            WHEN ug.completion_pct <= 50       THEN '25-50%%'
                            WHEN ug.completion_pct <= 75       THEN '50-75%%'
                            WHEN ug.completion_pct < 100       THEN '75-99%%'
                            ELSE '100%%'
                        END AS bracket
                    FROM user_games ug
                    JOIN linked_accounts la ON la.id = ug.linked_account_id AND la.user_id = %s
                    WHERE ug.total_achievements > 0
                ) sub
                GROUP BY bracket
                """,
                user["id"],
            )

            platform_rows = await _fetch(
                conn,
                """
                SELECT pg.platform, SUM(ug.earned_achievements) AS earned
                FROM user_games ug
                JOIN platform_games pg ON pg.id = ug.platform_game_id
                JOIN linked_accounts la ON la.id = ug.linked_account_id AND la.user_id = %s
                GROUP BY pg.platform
                """,
                user["id"],
            )

            progression = await _fetch(
                conn,
                """
                SELECT DATE_TRUNC('month', ua.unlocked_at)::date AS month, COUNT(*) AS cnt
                FROM user_achievements ua
                JOIN linked_accounts la ON la.id = ua.linked_account_id AND la.user_id = %s
                WHERE ua.unlocked = true AND ua.unlocked_at IS NOT NULL
                GROUP BY DATE_TRUNC('month', ua.unlocked_at)::date
                ORDER BY DATE_TRUNC('month', ua.unlocked_at)::date
                """,
                user["id"],
            )

            best_day_row = await _fetchrow(
                conn,
                """
                SELECT ua.unlocked_at::date AS day, COUNT(*) AS cnt
                FROM user_achievements ua
                JOIN linked_accounts la ON la.id = ua.linked_account_id AND la.user_id = %s
                WHERE ua.unlocked = true AND ua.unlocked_at IS NOT NULL
                GROUP BY ua.unlocked_at::date
                ORDER BY cnt DESC LIMIT 1
                """,
                user["id"],
            )

            best_month_row = await _fetchrow(
                conn,
                """
                SELECT DATE_TRUNC('month', ua.unlocked_at)::date AS month, COUNT(*) AS cnt
                FROM user_achievements ua
                JOIN linked_accounts la ON la.id = ua.linked_account_id AND la.user_id = %s
                WHERE ua.unlocked = true AND ua.unlocked_at IS NOT NULL
                GROUP BY DATE_TRUNC('month', ua.unlocked_at)::date
                ORDER BY cnt DESC LIMIT 1
                """,
                user["id"],
            )

            streak_row = await _fetchrow(
                conn,
                """
                WITH daily AS (
                    SELECT DISTINCT ua.unlocked_at::date AS day
                    FROM user_achievements ua
                    JOIN linked_accounts la ON la.id = ua.linked_account_id AND la.user_id = %s
                    WHERE ua.unlocked = true AND ua.unlocked_at IS NOT NULL
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
                user["id"],
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
async def activity(user: dict = Depends(require_user)):
    """Unlock heatmap, streaks, total playtime, and a recent-activity feed."""
    from datetime import date, timedelta

    pool = await db.get_pool()
    async with pool.connection() as conn:
        heatmap_rows = await _fetch(
            conn,
            """
            SELECT ua.unlocked_at::date AS day, COUNT(*) AS cnt
            FROM user_achievements ua
            JOIN linked_accounts la ON la.id = ua.linked_account_id AND la.user_id = %s
            WHERE ua.unlocked = true AND ua.unlocked_at IS NOT NULL
              AND ua.unlocked_at >= now() - interval '53 weeks'
            GROUP BY ua.unlocked_at::date
            ORDER BY day
            """,
            user["id"],
        )
        playtime_row = await _fetchrow(
            conn,
            "SELECT COALESCE(SUM(ug.playtime_minutes), 0) AS total FROM user_games ug "
            "JOIN linked_accounts la ON la.id = ug.linked_account_id AND la.user_id = %s",
            user["id"],
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
            JOIN linked_accounts la ON la.id = ua.linked_account_id AND la.user_id = %s
            LEFT JOIN igdb_games ig ON ig.id = pg.igdb_id AND pg.igdb_id > 0
            WHERE ua.unlocked = true AND ua.unlocked_at IS NOT NULL
            GROUP BY pg.id, pg.name, pg.platform, pg.icon_url, pg.sgdb_cover_url,
                     ig.cover_url, ua.unlocked_at::date
            ORDER BY ua.unlocked_at::date DESC, cnt DESC
            LIMIT 40
            """,
            user["id"],
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
async def statistics_platform(platform: str, user: dict = Depends(require_user)):
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
            JOIN linked_accounts la ON la.id = ug.linked_account_id AND la.user_id = %s
            LEFT JOIN igdb_games ig ON ig.id = pg.igdb_id AND pg.igdb_id > 0
            WHERE pg.platform = %s AND ug.total_achievements > 0
            ORDER BY ug.earned_achievements DESC
            LIMIT 50
            """,
            user["id"], platform,
        )
    return [dict(r) for r in rows]


async def _refresh_guide_links(platform_game_id: int) -> None:
    """
    Scrapes TrueSteamAchievements/TrueAchievements for this game's
    per-achievement links, matching by normalized name, and caches the
    result on the achievements themselves. Runs detached (asyncio.create_task,
    same pattern as the enrichment jobs below) rather than blocking the
    request that triggered it — scraping an external site is slow and
    best-effort by nature (see app/platforms/trueachievements.py), so
    requests always serve whatever guide_url is already cached (possibly
    none, on a game's very first load) instead of waiting on it.
    """
    pool = await db.get_pool()
    async with pool.connection() as conn:
        game = await _fetchrow(conn, "SELECT platform, name FROM platform_games WHERE id = %s", platform_game_id)
        if not game:
            return
        links = await trueachievements.fetch_achievement_links(game["platform"], game["name"])
        if links:
            achievements = await db.list_achievement_names(conn, platform_game_id)
            mapping = {
                a["id"]: links[trueachievements.normalize_name(a["name"])]
                for a in achievements
                if trueachievements.normalize_name(a["name"]) in links
            }
            if mapping:
                await db.set_achievement_guide_urls(conn, mapping)
        await db.mark_guide_links_fetched(conn, platform_game_id)


async def _maybe_schedule_guide_refresh(conn, platform_game_id: int) -> None:
    if await db.guide_links_need_refresh(conn, platform_game_id):
        asyncio.create_task(_refresh_guide_links(platform_game_id))


@app.get("/api/games/{platform_game_id}/achievements")
async def game_achievements(platform_game_id: int, user: dict = Depends(require_user)):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        await _maybe_schedule_guide_refresh(conn, platform_game_id)
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
                a.guide_url,
                ua.unlocked,
                ua.unlocked_at
            FROM achievements a
            JOIN user_games ug ON ug.platform_game_id = a.platform_game_id
            JOIN linked_accounts la ON la.id = ug.linked_account_id AND la.user_id = %s
            LEFT JOIN user_achievements ua ON ua.achievement_id = a.id AND ua.linked_account_id = la.id
            WHERE a.platform_game_id = %s
            ORDER BY ua.unlocked DESC NULLS LAST, a.name
            """,
            user["id"], platform_game_id,
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
async def exophase_origin_debug(
    game_id: int | None = Query(None),
    player_id: int | None = Query(None),
    environment: str = Query("origin"),
):
    """
    Temporary diagnostic: dumps Exophase's raw public API response for a
    given environment (e.g. "origin" for EA, "uplay" for Ubisoft), using the
    already-configured Exophase session (EXOPHASE_PLAYER_ID/EXOPHASE_ACCESS_TOKEN
    — the same ones the Xbox 360 icon-enrichment feature uses).

    With no game_id/player_id: dumps the raw games list for `environment`.
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
                params={"page": 1, "environment": environment, "sort": 1, "showHidden": 0, "query": ""},
                headers=headers,
            )
        result = {"status_code": r.status_code}
        try:
            result["body"] = r.json()
        except Exception:
            result["body_text"] = r.text[:2000]
        return result


@app.get("/api/exophase-match-debug")
async def exophase_match_debug(
    exo_slug: str = Query(...),
    page_type: str = Query("achievements"),
    master_playerid: int = Query(...),
    master_id: int = Query(...),
):
    """
    Temporary diagnostic: some unlocked achievements aren't showing as
    unlocked after the HTML-parser rewrite, meaning the earned-feed's slug
    doesn't always line up with the achievements page's href-derived slug.
    This reports both slug sets and exactly which earned slugs have no
    matching page award, so the mismatch pattern can be seen directly
    instead of guessed at.
    """
    from app.platforms.exophase import fetch_game_page_awards, fetch_earned

    awards = await fetch_game_page_awards(exo_slug, page_type)
    earned = await fetch_earned(master_playerid, master_id)

    page_slugs = {a["slug"] for a in awards if a.get("slug")}
    earned_slugs = set(earned)

    return {
        "page_award_count": len(awards),
        "earned_count": len(earned),
        "earned_not_matched_in_page": sorted(earned_slugs - page_slugs),
        "page_slugs_sample": sorted(page_slugs)[:15],
        "earned_slugs_sample": sorted(earned_slugs)[:15],
    }


@app.get("/api/exophase-page-debug")
async def exophase_page_debug(exo_slug: str = Query(...), page_type: str = Query("achievements")):
    """
    Temporary diagnostic: fetches an Exophase game achievements/challenges
    page and reports what the real scraper (fetch_game_page_awards, the
    HTML-parser-based one actually used by sync) finds, plus a raw HTML
    snippet — to check whether the page renders the achievement grid as
    static HTML at all for a given environment/game.
    """
    from app.platforms.exophase import fetch_game_page_awards, _PAGE_HEADERS

    awards = await fetch_game_page_awards(exo_slug, page_type)

    url = f"https://www.exophase.com/game/{exo_slug}/{page_type}/"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(url, headers=_PAGE_HEADERS)

    text = r.text
    # Find where the achievement grid actually starts, whatever its real
    # class names turn out to be, instead of guessing blind again.
    idx = text.lower().find("award-image")
    if idx == -1:
        idx = text.lower().find("data-tippy-content")
    if idx == -1:
        idx = text.lower().find("achievement")
    context = text[max(0, idx - 200):idx + 2000] if idx != -1 else None

    return {
        "url": url,
        "status_code": r.status_code,
        "awards_found": len(awards),
        "sample_awards": awards[:5],
        "html_length": len(text),
        "found_marker_at": idx if idx != -1 else None,
        "context_around_marker": context,
        "head_snippet": text[:1500] if idx == -1 else None,
    }


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
async def sync_progress(user: dict = Depends(require_user)):
    # Not scoped per-user: this reflects whatever background sync is
    # currently running (which could be another family member's, or the
    # scheduled all-accounts job), not just this user's. Acceptable for
    # now — it only exposes platform names and progress counts, not
    # account data — but a genuinely per-user progress view would need its
    # own tracking structure rather than this single global dict.
    return _sync_progress


@app.get("/api/unlocks/recent")
async def recent_unlocks(since: str = "", user: dict = Depends(require_user)):
    """
    Achievement-unlock events collected during syncs, for the frontend to
    poll and toast. Pass `since` back as the `unlocked_at` of the last event
    you've already shown; omit it to get the most recent handful.
    """
    events = [e for e in _unlock_events if e["user_id"] == user["id"]]
    if since:
        events = [e for e in events if e["unlocked_at"] > since]
    return {"events": events[-15:]}


@app.post("/api/sync", status_code=202)
async def trigger_sync(user: dict = Depends(require_user)):
    if _sync_lock.locked():
        raise HTTPException(status_code=409, detail="Sync already in progress")
    asyncio.create_task(run_sync(user_id=user["id"]))
    return {"status": "started"}


# ── Backups ───────────────────────────────────────────────────────────────────
# Everything Achievist knows — synced achievements and connected-account
# credentials alike — lives in Postgres, so a pg_dump backup covers all of it.

@app.get("/api/backups")
async def get_backups(admin: dict = Depends(require_admin)):
    return {
        "backups": backup.list_backups(),
        "keep_count": config.BACKUP_KEEP_COUNT,
        "interval_hours": config.BACKUP_INTERVAL_HOURS,
    }


@app.post("/api/backups", status_code=201)
async def create_backup_now(admin: dict = Depends(require_admin)):
    try:
        path = await backup.create_backup()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"filename": path.name}


@app.get("/api/backups/{filename}")
async def download_backup(filename: str, admin: dict = Depends(require_admin)):
    try:
        path = backup.resolve_backup_path(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@app.delete("/api/backups/{filename}", status_code=204)
async def remove_backup(filename: str, admin: dict = Depends(require_admin)):
    try:
        backup.delete_backup(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    return None


# ── Personal data export ─────────────────────────────────────────────────────
# Self-service, per-user export — anyone can download their own library and
# unlocked achievements as JSON, no admin needed. Not a restorable dump
# (credentials are excluded, and re-importing into the shared game catalog is
# out of scope) — full restore is the admin-level pg_dump/pg_restore above.

@app.get("/api/export")
async def export_my_data(user: dict = Depends(require_user)):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        data = await db.get_user_export(conn, user["id"])
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "username": user["username"],
        "display_name": user["display_name"],
        **data,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"achievist-export-{user['username']}-{stamp}.json"
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
async def list_accounts(user: dict = Depends(require_user)):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        rows = await db.list_accounts(conn, user["id"])
    return [_redact_account(r) for r in rows]


@app.post("/api/accounts", status_code=201)
async def connect_account(payload: dict, user: dict = Depends(require_user)):
    """
    Connect (or update) an account for the logged-in user.
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
        existing = await db.get_account_by_key(conn, user["id"], platform, str(external_id))
        merged = {**(existing["credentials"] if existing else {}), **creds}

        # Validate required fields against the merged result (skip external_id).
        for field in platform_cls.CONNECT_FIELDS:
            if field["name"] == "external_id":
                continue
            if field.get("required") and not merged.get(field["name"]):
                raise HTTPException(status_code=400, detail=f"Missing required field: {field['label']}")

        await db.delete_other_accounts_for_platform(conn, user["id"], platform, str(external_id))
        account_id = await db.upsert_account(conn, user["id"], platform, str(external_id), merged)
    return {"id": account_id, "status": "connected"}


@app.delete("/api/accounts/{account_id}", status_code=204)
async def disconnect_account(account_id: int, user: dict = Depends(require_user)):
    pool = await db.get_pool()
    async with pool.connection() as conn:
        acct = await db.get_account(conn, account_id, user["id"])
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        await db.delete_account(conn, account_id, user["id"])
    return None


@app.post("/api/accounts/{account_id}/sync", status_code=202)
async def sync_account(account_id: int, user: dict = Depends(require_user)):
    if _sync_lock.locked():
        raise HTTPException(status_code=409, detail="Sync already in progress")
    pool = await db.get_pool()
    async with pool.connection() as conn:
        acct = await db.get_account(conn, account_id, user["id"])
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    asyncio.create_task(run_sync(account_id=account_id))
    return {"status": "started"}


@app.post("/api/xbox-dedup")
async def xbox_dedup(user: dict = Depends(require_user)):
    """
    Consolidate this user's duplicate Xbox accounts: keep the linked account
    with the most stored games and delete the others (removes duplicate
    library entries).
    """
    pool = await db.get_pool()
    async with pool.connection() as conn:
        rows = await _fetch(
            conn,
            """
            SELECT la.id, la.external_id, COUNT(ug.id) AS games
            FROM linked_accounts la
            LEFT JOIN user_games ug ON ug.linked_account_id = la.id
            WHERE la.platform = 'xbox' AND la.user_id = %s
            GROUP BY la.id, la.external_id
            ORDER BY games DESC
            """,
            user["id"],
        )
        if len(rows) <= 1:
            return {"status": "ok", "removed": 0, "kept": rows[0]["external_id"] if rows else None}
        keep = rows[0]
        removed = []
        for r in rows[1:]:
            await db.delete_account(conn, r["id"], user["id"])
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
