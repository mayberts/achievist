import asyncio
import logging
from datetime import datetime

import httpx

from app import config, db
from app.platforms.base import Platform
from app.psn_auth import get_access_token, auth_headers

log = logging.getLogger(__name__)

# Profile API
_BASE = "https://us-prof.np.community.playstation.net"

# Trophy API
_TROPHY_BASE = "https://m.np.playstation.com/api/trophy/v1"

# Rough point weighting per trophy tier (PSN has no built-in points system).
_TROPHY_POINTS = {"bronze": 15, "silver": 30, "gold": 90, "platinum": 300}


class PSNPlatform(Platform):
    KEY = "psn"
    LABEL = "PlayStation"
    CONNECT_FIELDS = [
        {
            "name": "external_id",
            "label": "PSN Online ID",
            "type": "text",
            "required": True,
            "help": "Your PSN username. Trophy privacy must be set to 'Anyone' for this to sync.",
        },
    ]

    async def sync(self, account: dict, conn) -> None:
        online_id = account["external_id"]
        delay = config.REQUEST_DELAY_SECONDS

        access_token = await get_access_token()
        headers = auth_headers(access_token)

        linked_id = await db.upsert_linked_account(
            conn, account["user_id"], "psn", online_id
        )
        earned_cache = await db.get_earned_counts(conn, linked_id)

        async with httpx.AsyncClient(timeout=30) as client:
            # Resolve PSN Online ID to accountId.
            profile = await client.get(
                f"{_BASE}/userProfile/v1/users/{online_id}/profile2",
                headers=headers,
                params={"fields": "accountId"},
            )

            if profile.status_code == 404:
                raise RuntimeError(
                    f"No PlayStation profile found for '{online_id}'."
                )

            profile.raise_for_status()
            profile_data = profile.json()
            account_id = (
                (profile_data.get("profile") or {}).get("accountId")
                or profile_data.get("accountId")
            )

            if not account_id:
                raise RuntimeError(
                    f"Could not resolve accountId for '{online_id}'."
                )

            # Fetch the user's trophy titles.
            titles: list[dict] = []
            offset = 0

            while True:
                await asyncio.sleep(delay)

                resp = await client.get(
                    f"{_TROPHY_BASE}/users/{account_id}/trophyTitles",
                    headers=headers,
                    params={"limit": 100, "offset": offset},
                )

                if resp.status_code == 403:
                    log.error(
                        "PSN trophyTitles returned 403. URL=%s Response=%s",
                        resp.url,
                        resp.text[:1000],
                    )
                    raise RuntimeError(
                        f"PlayStation API returned 403 while fetching trophies "
                        f"for '{online_id}'."
                    )

                resp.raise_for_status()
                data = resp.json()
                page = data.get("trophyTitles") or []
                titles.extend(page)

                total_count = data.get("totalItemCount") or len(titles)
                offset += len(page)

                if not page or offset >= total_count:
                    break

            log.info("PSN: %d titles for %s", len(titles), online_id)

            for title in titles:
                np_comm_id = title.get("npCommunicationId")
                name = title.get("trophyTitleName") or np_comm_id
                icon = title.get("trophyTitleIconUrl")
                defined = title.get("definedTrophies") or {}
                earned = title.get("earnedTrophies") or {}

                total = sum(
                    int(defined.get(t, 0) or 0) for t in _TROPHY_POINTS
                )
                earned_total = sum(
                    int(earned.get(t, 0) or 0) for t in _TROPHY_POINTS
                )

                if not np_comm_id or total == 0:
                    continue

                is_ps5 = "PS5" in (
                    title.get("trophyTitlePlatform") or ""
                )
                service_name = "trophy2" if is_ps5 else "trophy"

                self._inc("games_seen")
                pg_id = await db.upsert_platform_game(
                    conn, "psn", np_comm_id, name, icon, total
                )
                await db.upsert_user_game(
                    conn, linked_id, pg_id, 0, earned_total, total, None
                )

                cached = earned_cache.get(np_comm_id)
                if (
                    cached
                    and cached["earned"] == earned_total
                    and cached["stored"] >= total > 0
                ):
                    continue

                await asyncio.sleep(delay)

                tr_resp = await client.get(
                    f"{_TROPHY_BASE}/users/{account_id}/"
                    f"npCommunicationIds/{np_comm_id}/"
                    "trophyGroups/all/trophies",
                    headers=headers,
                    params={
                        "npServiceName": service_name,
                        "fields": (
                            "@default,trophyRare,"
                            "trophyEarnedRate,trophyType"
                        ),
                    },
                )

                if tr_resp.status_code != 200:
                    log.warning(
                        "PSN trophies fetch failed for %s: HTTP %s — %s",
                        name,
                        tr_resp.status_code,
                        tr_resp.text[:500],
                    )
                    continue

                for t in tr_resp.json().get("trophies") or []:
                    trophy_id = t.get("trophyId")

                    if trophy_id is None:
                        continue

                    self._inc("achievements_synced")
                    trophy_type = t.get("trophyType") or "bronze"
                    rarity = t.get("trophyEarnedRate")

                    db_ach_id = await db.upsert_achievement(
                        conn,
                        pg_id,
                        str(trophy_id),
                        t.get("trophyName") or f"Trophy {trophy_id}",
                        t.get("trophyDetail"),
                        t.get("trophyIconUrl"),
                        _TROPHY_POINTS.get(trophy_type),
                        float(rarity) if rarity is not None else None,
                    )

                    unlocked = bool(t.get("earned"))
                    unlocked_at = None

                    if unlocked and t.get("earnedDateTime"):
                        try:
                            unlocked_at = datetime.fromisoformat(
                                t["earnedDateTime"].replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass

                    await db.upsert_user_achievement(
                        conn,
                        linked_id,
                        db_ach_id,
                        unlocked,
                        unlocked_at,
                    )
