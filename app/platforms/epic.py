import asyncio
import logging
from datetime import datetime

import httpx

from app import config, db
from app.platforms.base import Platform

log = logging.getLogger(__name__)

_GRAPHQL = "https://store.epicgames.com/graphql"

# Apollo persisted-query hashes captured from the Epic Store profile page.
_HASH_PROFILE_PRIVATE = "47d0391fa5ec42d829e4a03f399cb586a29cf3cebd940cc4747aed0192c61114"
_HASH_ACHIEVEMENT = "9284d2fe200e351d1496feda728db23bb52bfd379b236fc3ceca746c1f1b33f2"
_HASH_PLAYER_ACH = "70ff714976f88a85aafa3cb5abb9909d52e12a3ff585d7b49550d2493a528fb0"

_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://store.epicgames.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}


def _cover(key_images: list) -> str | None:
    if not isinstance(key_images, list):
        return None
    by_type = {i.get("type"): i.get("url") for i in key_images if isinstance(i, dict)}
    return by_type.get("OfferImageWide") or by_type.get("OfferImageTall") or by_type.get("Thumbnail")


def _parse_date(val):
    if not val or val == "N/A":
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None


class EpicPlatform(Platform):
    KEY = "epic"
    LABEL = "Epic Games"
    CONNECT_FIELDS = [
        {"name": "external_id", "label": "Epic Account ID", "type": "text", "required": True,
         "help": "The ID from your profile URL: store.epicgames.com/u/<THIS>. "
                 "Your profile and achievements must be set to public."},
    ]

    async def _gql(self, client, account_id, headers, op, variables, sha):
        body = {
            "operationName": op,
            "variables": variables,
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}},
        }
        r = await client.post(_GRAPHQL, json=body, headers=headers)
        r.raise_for_status()
        return r.json().get("data") or {}

    async def sync(self, account: dict, conn) -> None:
        account_id = account["external_id"]
        delay = config.REQUEST_DELAY_SECONDS
        headers = {**_HEADERS, "Referer": f"https://store.epicgames.com/u/{account_id}"}

        linked_id = await db.upsert_linked_account(conn, account["user_id"], "epic", account_id)
        earned_cache = await db.get_earned_counts(conn, linked_id)

        async with httpx.AsyncClient(timeout=30) as client:
            # 1) Enumerate the player's games (paginated).
            games: list[dict] = []
            for page in range(1, 40):
                await asyncio.sleep(delay)
                data = await self._gql(
                    client, account_id, headers, "playerProfilePrivate",
                    {"epicAccountId": account_id, "locale": "en-US", "page": page, "accountId": account_id},
                    _HASH_PROFILE_PRIVATE,
                )
                summ = (((data.get("PlayerProfile") or {}).get("playerProfile") or {})
                        .get("achievementsSummaries") or {})
                items = summ.get("data") or []
                if not items:
                    break
                games.extend(items)
                if len(items) < 10:  # last page
                    break

            log.info("Epic: %d games for %s", len(games), account_id)

            for g in games:
                sandbox_id = g.get("sandboxId")
                product = g.get("product") or {}
                name = product.get("name") or sandbox_id
                slug = product.get("slug")
                total = int((g.get("productAchievements") or {}).get("totalAchievements") or 0)
                earned = int(g.get("totalUnlocked") or 0)
                cover = _cover((g.get("baseOfferForSandbox") or {}).get("keyImages") or [])
                if not sandbox_id or total == 0:
                    continue

                self._inc("games_seen")
                pg_id = await db.upsert_platform_game(conn, "epic", sandbox_id, name, cover, total, slug)
                await db.upsert_user_game(conn, linked_id, pg_id, 0, earned, total, None)

                cached = earned_cache.get(sandbox_id)
                if cached and cached["earned"] == earned and cached["stored"] >= total > 0:
                    continue

                # 2) Definitions for this sandbox (names, icons, rarity, XP) + productId.
                await asyncio.sleep(delay)
                defs = await self._gql(
                    client, account_id, headers, "Achievement",
                    {"sandboxId": sandbox_id, "locale": "en-US"}, _HASH_ACHIEVEMENT,
                )
                record = ((defs.get("Achievement") or {}).get("productAchievementsRecordBySandbox") or {})
                product_id = record.get("productId")
                definitions = record.get("achievements") or []
                if not definitions or not product_id:
                    continue

                # 3) Player's unlock status for this product.
                await asyncio.sleep(delay)
                pdata = await self._gql(
                    client, account_id, headers, "playerProfileAchievementsByProductId",
                    {"epicAccountId": account_id, "productId": product_id}, _HASH_PLAYER_ACH,
                )
                pach = ((((pdata.get("PlayerProfile") or {}).get("playerProfile") or {})
                         .get("productAchievements") or {}).get("data") or {})
                unlocked: dict[str, str] = {}
                for entry in pach.get("playerAchievements") or []:
                    pa = entry.get("playerAchievement") or {}
                    if pa.get("unlocked"):
                        unlocked[pa.get("achievementName")] = pa.get("unlockDate")

                for d in definitions:
                    ach = d.get("achievement") or {}
                    ach_name = ach.get("name")
                    if not ach_name:
                        continue
                    self._inc("achievements_synced")
                    is_unlocked = ach_name in unlocked
                    icon = ach.get("unlockedIconLink") if is_unlocked else ach.get("lockedIconLink")
                    rarity = (ach.get("rarity") or {}).get("percent")
                    db_ach_id = await db.upsert_achievement(
                        conn,
                        pg_id,
                        ach_name,
                        ach.get("unlockedDisplayName") or ach_name,
                        ach.get("unlockedDescription") or ach.get("lockedDescription"),
                        (icon or "").replace("http://", "https://") or None,
                        ach.get("XP"),
                        rarity,
                    )
                    await db.upsert_user_achievement(
                        conn, linked_id, db_ach_id, is_unlocked, _parse_date(unlocked.get(ach_name)),
                    )
