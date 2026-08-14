import asyncio
import logging
from datetime import datetime

import httpx

from app import config, db
from app.platforms.base import Platform

log = logging.getLogger(__name__)

_USERS = "https://users.roblox.com/v1"
_BADGES = "https://badges.roblox.com/v1"
_THUMBS = "https://thumbnails.roblox.com/v1"


class RobloxPlatform(Platform):
    KEY = "roblox"
    LABEL = "Roblox"
    # Roblox's badge API is fully public — no login/API key needed, just a
    # username. Games are Roblox "universes"; badges are its achievements.
    # There's no "games I've played" endpoint, so only games the user has
    # earned at least one badge in ever show up here — a 0%-complete game
    # with no earned badges is invisible to this API, same limitation as
    # every other unofficial-scrape platform in this app.
    CONNECT_FIELDS = [
        {"name": "external_id", "label": "Roblox Username", "type": "text", "required": True,
         "help": "Your Roblox username. Badges are public, no login needed."},
    ]

    async def sync(self, account: dict, conn) -> None:
        username = account["external_id"]
        delay = config.REQUEST_DELAY_SECONDS

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_USERS}/usernames/users",
                json={"usernames": [username], "excludeBannedUsers": True},
            )
            resp.raise_for_status()
            matches = resp.json().get("data") or []
            if not matches:
                raise RuntimeError(f"Roblox username not found: {username}")
            user_id = matches[0]["id"]

            linked_id = await db.upsert_linked_account(conn, account["user_id"], "roblox", username)
            earned_cache = await db.get_earned_counts(conn, linked_id)

            earned_badges = await self._fetch_all(
                client, f"{_BADGES}/users/{user_id}/badges", {"limit": 100, "sortOrder": "Desc"}, delay,
            )
            if not earned_badges:
                return

            awarded_at = await self._fetch_awarded_dates(client, user_id, [b["id"] for b in earned_badges], delay)

            by_universe: dict[int, dict] = {}
            for b in earned_badges:
                uni = b.get("awardingUniverse") or {}
                uni_id = uni.get("id")
                if not uni_id:
                    continue
                by_universe.setdefault(
                    uni_id, {"name": uni.get("name") or f"Game {uni_id}", "place_id": uni.get("rootPlaceId"), "badges": []}
                )
                by_universe[uni_id]["badges"].append(b)

            for uni_id, game in by_universe.items():
                self._inc("games_seen")
                uni_key = str(uni_id)
                earned_ids = {b["id"] for b in game["badges"]}
                earned_count = len(earned_ids)

                # Full badge roster (locked + unlocked) for the game — a
                # separate per-universe listing, not tied to any user.
                all_badges = await self._fetch_all(
                    client, f"{_BADGES}/universes/{uni_id}/badges", {"limit": 100}, delay,
                )
                badge_pool = all_badges or game["badges"]
                total = len(badge_pool)

                place_id = str(game["place_id"]) if game.get("place_id") else None
                pg_id = await db.upsert_platform_game(conn, "roblox", uni_key, game["name"], None, total, place_id)
                await db.upsert_user_game(conn, linked_id, pg_id, 0, earned_count, total, None)

                cached = earned_cache.get(uni_key)
                if cached and cached["earned"] == earned_count and cached["stored"] >= total > 0:
                    continue

                icon_by_id = await self._fetch_icons(client, [b["id"] for b in badge_pool], delay)

                for b in badge_pool:
                    self._inc("achievements_synced")
                    bid = b["id"]
                    is_unlocked = bid in earned_ids
                    unlocked_at = None
                    ts = awarded_at.get(bid)
                    if ts:
                        try:
                            unlocked_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except ValueError:
                            pass
                    db_ach_id = await db.upsert_achievement(
                        conn, pg_id, str(bid), b.get("name") or f"Badge {bid}",
                        b.get("description"), icon_by_id.get(bid), None, None,
                    )
                    await db.upsert_user_achievement(conn, linked_id, db_ach_id, is_unlocked, unlocked_at)

    @staticmethod
    async def _fetch_all(client: httpx.AsyncClient, url: str, params: dict, delay: float) -> list[dict]:
        items: list[dict] = []
        cursor = ""
        while True:
            p = dict(params)
            if cursor:
                p["cursor"] = cursor
            resp = await client.get(url, params=p)
            if resp.status_code != 200:
                log.warning("Roblox GET %s HTTP %d", url, resp.status_code)
                break
            data = resp.json()
            items.extend(data.get("data") or [])
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
            await asyncio.sleep(delay)
        return items

    @staticmethod
    async def _fetch_awarded_dates(
        client: httpx.AsyncClient, user_id: int, badge_ids: list[int], delay: float
    ) -> dict[int, str]:
        awarded_at: dict[int, str] = {}
        for i in range(0, len(badge_ids), 100):
            chunk = badge_ids[i:i + 100]
            resp = await client.get(
                f"{_BADGES}/users/{user_id}/badges/awarded-dates",
                params={"badgeIds": ",".join(str(x) for x in chunk)},
            )
            if resp.status_code == 200:
                for row in resp.json().get("data") or []:
                    awarded_at[row["badgeId"]] = row.get("awardedDate")
            else:
                log.warning("Roblox awarded-dates HTTP %d", resp.status_code)
            await asyncio.sleep(delay)
        return awarded_at

    @staticmethod
    async def _fetch_icons(client: httpx.AsyncClient, badge_ids: list[int], delay: float) -> dict[int, str]:
        icons: dict[int, str] = {}
        for i in range(0, len(badge_ids), 100):
            chunk = badge_ids[i:i + 100]
            resp = await client.get(
                f"{_THUMBS}/badges/icons",
                params={"badgeIds": ",".join(str(x) for x in chunk), "size": "150x150", "format": "Png"},
            )
            if resp.status_code == 200:
                for row in resp.json().get("data") or []:
                    if row.get("imageUrl"):
                        icons[row["targetId"]] = row["imageUrl"]
            else:
                log.warning("Roblox badge icons HTTP %d", resp.status_code)
            await asyncio.sleep(delay)
        return icons
