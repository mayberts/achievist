import asyncio
import logging
from datetime import datetime

import httpx

from app import config, db
from app.platforms.base import Platform
from app.platforms.exophase import fetch_environment_games, fetch_earned, fetch_game_page_icons

log = logging.getLogger(__name__)


def _humanize(slug: str) -> str:
    return slug.replace("-", " ").title()


def _parse_ts(ts) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts))
    except Exception:
        return None


class EAPlatform(Platform):
    KEY = "ea"
    LABEL = "EA App"
    # EA has no reachable achievements API of its own — its unofficial GraphQL
    # backend has introspection disabled and rejects reconstructed queries
    # with no diagnostic detail, a dead end. Exophase has already done that
    # reverse engineering and exposes it through a public per-player API,
    # riding on the same Exophase login already configured for Xbox 360 icon
    # enrichment (EXOPHASE_PLAYER_ID/EXOPHASE_ACCESS_TOKEN) — no separate
    # per-account credential needed here.
    EXTERNAL_ID = "ea"
    # No per-account credential needed: this rides on the app's existing
    # Exophase login (EXOPHASE_PLAYER_ID / EXOPHASE_ACCESS_TOKEN env vars,
    # the same ones already powering Xbox 360 icon enrichment) to read
    # linked EA/Origin games from Exophase's public per-player API.
    CONNECT_FIELDS: list[dict] = []

    async def sync(self, account: dict, conn) -> None:
        if not config.EXOPHASE_PLAYER_ID or not config.EXOPHASE_ACCESS_TOKEN:
            raise RuntimeError(
                "EXOPHASE_PLAYER_ID / EXOPHASE_ACCESS_TOKEN not configured — EA sync rides on "
                "the app's Exophase login, same as Xbox 360 icon enrichment."
            )
        delay = config.REQUEST_DELAY_SECONDS

        linked_id = await db.upsert_linked_account(conn, "ea", account["external_id"])
        earned_cache = await db.get_earned_counts(conn, linked_id)

        async with httpx.AsyncClient(timeout=30) as client:
            games = await fetch_environment_games(
                client, config.EXOPHASE_PLAYER_ID, config.EXOPHASE_ACCESS_TOKEN, "origin",
            )
        log.info("EA (via Exophase): %d games", len(games))

        for g in games:
            total = g["total_awards"]
            if not total:
                continue
            exo_slug = g["exo_slug"]

            self._inc("games_seen")
            pg_id = await db.upsert_platform_game(conn, "ea", exo_slug, g["title"], g["cover"], total)
            await db.upsert_user_game(conn, linked_id, pg_id, 0, g["earned_awards"], total, None)

            cached = earned_cache.get(exo_slug)
            if cached and cached["earned"] == g["earned_awards"] and cached["stored"] >= total > 0:
                continue

            await asyncio.sleep(delay)
            icons = await fetch_game_page_icons(exo_slug)  # {name_slug: icon_url}, locked + unlocked
            await asyncio.sleep(delay)
            earned = await fetch_earned(g["master_playerid"], g["master_id"])  # {slug: {timestamp, icon}}

            # Union both slug sets: the page scrape may miss secret/hidden
            # achievements that only appear once earned, and vice versa the
            # earned feed's own slug is Exophase's canonical one (may differ
            # slightly from our re-slugified tooltip name).
            all_slugs = set(icons) | set(earned)
            if not all_slugs:
                continue

            for slug in all_slugs:
                self._inc("achievements_synced")
                earned_info = earned.get(slug)
                is_unlocked = earned_info is not None
                icon = (earned_info or {}).get("icon") or icons.get(slug)
                db_ach_id = await db.upsert_achievement(
                    conn, pg_id, slug, _humanize(slug), None, icon, None, None,
                )
                await db.upsert_user_achievement(
                    conn, linked_id, db_ach_id, is_unlocked,
                    _parse_ts((earned_info or {}).get("timestamp")),
                )
