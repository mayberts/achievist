import asyncio
import logging

import httpx

from app import config, db
from app.platforms.base import Platform
from app.ubisoft_auth import (
    get_service_ticket,
    resolve_username,
    session_headers,
    club_headers,
    CLUB_BASE,
)

log = logging.getLogger(__name__)

_BASE = "https://public-ubiservices.ubi.com"
_CDN = "https://static8.cdn.ubi.com/u/Uplay"


def _icon(images: list) -> str | None:
    """Pick a thumbnail image URL from a club action's images list."""
    if not isinstance(images, list):
        return None
    by_type = {i.get("type"): i.get("url") for i in images if isinstance(i, dict)}
    url = by_type.get("thumbnail") or by_type.get("background") or next(iter(by_type.values()), None)
    if not url:
        return None
    if url.startswith("http"):
        return url.replace("http://", "https://")
    return f"{_CDN}{url}"


class UbisoftPlatform(Platform):
    KEY = "ubisoft"
    LABEL = "Ubisoft Connect"
    CONNECT_FIELDS = [
        {"name": "external_id", "label": "Ubisoft Username", "type": "text", "required": True,
         "help": "Your Ubisoft Connect username. Your profile must be set to public for achievements to sync."},
    ]

    async def sync(self, account: dict, conn) -> None:
        delay = config.REQUEST_DELAY_SECONDS
        username = account["external_id"]

        ticket = await get_service_ticket()
        base_h = session_headers(ticket)   # public host: profiles, spaces metadata
        club_h = club_headers(ticket)      # msr host: achievements ("actions")

        linked_id = await db.upsert_linked_account(conn, "ubisoft", username)
        earned_cache = await db.get_earned_counts(conn, linked_id)

        async with httpx.AsyncClient(timeout=30) as client:
            profile_id = await resolve_username(client, base_h, username)

            await asyncio.sleep(delay)
            gp = await client.get(
                f"{_BASE}/v1/profiles/{profile_id}/gamesplayed",
                params={"spaceIds": "", "spacePlatformTypes": "", "applicationPlatformTypes": ""},
                headers=base_h,
            )
            if gp.status_code != 200:
                raise RuntimeError(f"Ubisoft gamesplayed failed: {gp.status_code} — {gp.text[:200]}")
            games = gp.json().get("gamesPlayed") or []
            log.info("Ubisoft: %d games for %s", len(games), username)

            space_name_cache: dict[str, dict] = {}

            async def space_info(sid: str) -> dict:
                if sid in space_name_cache:
                    return space_name_cache[sid]
                await asyncio.sleep(delay)
                r = await client.get(f"{_BASE}/v1/spaces/{sid}", headers=base_h)
                info = r.json() if r.status_code == 200 else {}
                space_name_cache[sid] = info
                return info

            async def club_actions(host_path: str) -> list:
                """
                Fetch all club actions for a path, paging through results.
                The endpoint returns a limited page (~10); walk offset until no
                new action ids appear (also safe if the API ignores paging).
                """
                sep = "&" if "?" in host_path else "?"
                all_actions: list = []
                seen: set[str] = set()
                offset = 0
                for _ in range(40):  # safety cap (~4000 actions)
                    await asyncio.sleep(delay)
                    r = await client.get(
                        f"{CLUB_BASE}{host_path}{sep}limit=100&offset={offset}",
                        headers=club_h,
                    )
                    if r.status_code != 200:
                        break
                    page = r.json().get("actions") or []
                    new = [a for a in page if str(a.get("id")) not in seen]
                    if not new:
                        break
                    for a in new:
                        seen.add(str(a.get("id")))
                    all_actions.extend(new)
                    offset += len(page)
                return all_actions

            for game in games:
                sid = game.get("spaceId")
                if not sid:
                    continue

                info = await space_info(sid)
                parent_id = info.get("parentSpaceId")

                # Achievement definitions live on the space itself, or its parent
                # (e.g. crossplay variants). Try both.
                ach_space = sid
                defs = await club_actions(f"/v1/spaces/{sid}/club/actions")
                if not defs and parent_id:
                    defs = await club_actions(f"/v1/spaces/{parent_id}/club/actions")
                    if defs:
                        ach_space = parent_id
                if not defs:
                    continue  # no achievements for this game

                # Player's unlocked actions for that space (activationDate set = unlocked)
                unlocked_raw = await club_actions(
                    f"/v1/profiles/{profile_id}/club/actions?spaceId={ach_space}"
                )
                unlocked: dict[str, str] = {
                    str(a.get("id")): a.get("activationDate")
                    for a in unlocked_raw
                    if a.get("activationDate")
                }

                total = len(defs)
                earned = len(unlocked)
                name = info.get("parentSpaceName") or info.get("spaceName") or ach_space
                log.info("Ubisoft %s: earned=%d total=%d", name, earned, total)

                self._inc("games_seen")
                pg_id = await db.upsert_platform_game(conn, "ubisoft", ach_space, name, None, total)
                await db.upsert_user_game(conn, linked_id, pg_id, 0, earned, total, None)

                cached = earned_cache.get(ach_space)
                if cached and cached["earned"] == earned and cached["stored"] >= total > 0:
                    continue

                for a in defs:
                    aid = str(a.get("id"))
                    if not aid:
                        continue
                    self._inc("achievements_synced")
                    db_ach_id = await db.upsert_achievement(
                        conn,
                        pg_id,
                        aid,
                        a.get("name") or aid,
                        a.get("description"),
                        _icon(a.get("images")),
                        a.get("xp") or None,
                        None,
                    )
                    await db.upsert_user_achievement(
                        conn, linked_id, db_ach_id, aid in unlocked, unlocked.get(aid),
                    )
