import asyncio
import logging
from datetime import datetime

import httpx

from app import config, db
from app.xbox_auth import XboxTokens
from app.platforms.base import Platform

log = logging.getLogger(__name__)

_TITLEHUB = "https://titlehub.xboxlive.com"
_ACH = "https://achievements.xboxlive.com"


def _xbl_headers(tokens: XboxTokens, contract: str = "2") -> dict:
    return {
        "Authorization": tokens.auth_header,
        "x-xbl-contract-version": contract,
        "Accept": "application/json",
        "Accept-Language": "en-US",
    }


class XboxPlatform(Platform):
    KEY = "xbox"
    LABEL = "Xbox"
    AUTH_TYPE = "oauth"
    EXTERNAL_ID = "xbox"
    CONNECT_FIELDS = [
        {"name": "external_id", "label": "Xbox Gamertag", "type": "text", "required": False,
         "help": "Your Xbox profile and achievement history must be set to public."},
    ]

    async def sync(self, account: dict, conn) -> None:
        from app.xbox_auth import get_tokens, load_refresh_token, resolve_gamertag

        # One backend Xbox sign-in authorizes all lookups (like Ubisoft's service
        # session). Individual accounts can then be added by gamertag.
        refresh_token = config.XBOX_REFRESH_TOKEN or load_refresh_token()
        if not refresh_token:
            raise RuntimeError("Xbox not signed in — use 'Sign in with Xbox' to connect the backend account.")

        tokens = await get_tokens(refresh_token)
        delay = config.REQUEST_DELAY_SECONDS

        target = (account.get("external_id") or "").strip()
        if not target or target.lower() == "xbox":
            xuid = tokens.xuid                                # the signed-in account itself
        elif target.isdigit():
            xuid = target                                     # already an XUID
        else:
            xuid = await resolve_gamertag(tokens, target)     # gamertag → XUID

        # Always key data by XUID so the same person added via sign-in and/or a
        # gamertag collapses into one account instead of duplicating the library.
        linked_id = await db.upsert_linked_account(conn, account["user_id"], "xbox", xuid)
        earned_cache = await db.get_earned_counts(conn, linked_id)

        async with httpx.AsyncClient(timeout=30) as client:
            # Fetch all titles the player has played with achievement decoration
            resp = await client.get(
                f"{_TITLEHUB}/users/xuid({xuid})/titles/titleHistory/decoration/Achievement,Image",
                headers=_xbl_headers(tokens),
            )
            resp.raise_for_status()
            data = resp.json()
            titles = data.get("titles") or []

            # Xbox's titleHistory returns a separate titleId per platform release of
            # the same game (e.g. console vs PC/Game Pass), which otherwise show up
            # as visual duplicates. Keep only the "best" entry per name: the one
            # with the most achievements earned, tie-broken by total achievements
            # then most recent play.
            def _sort_key(t: dict) -> tuple:
                ach = t.get("achievement") or {}
                hist = t.get("titleHistory") or {}
                return (
                    int(ach.get("currentAchievements") or 0),
                    int(ach.get("totalAchievements") or 0),
                    hist.get("lastTimePlayed") or "",
                )

            best_by_name: dict[str, dict] = {}
            for t in titles:
                name = (t.get("name") or "").strip().lower()
                if not name:
                    continue
                if name not in best_by_name or _sort_key(t) > _sort_key(best_by_name[name]):
                    best_by_name[name] = t
            titles = list(best_by_name.values())

            for title in titles:
                self._inc("games_seen")
                title_id = str(title.get("titleId", ""))
                name = title.get("name", f"Title {title_id}")

                ach_info = title.get("achievement") or {}
                total = int(ach_info.get("totalAchievements") or 0)
                earned = int(ach_info.get("currentAchievements") or 0)
                total_gamerscore = int(ach_info.get("totalGamerscore") or 0)
                is_360 = ach_info.get("sourceVersion") == 1

                if total == 0 and total_gamerscore == 0:
                    continue

                # Best icon: prefer tile image from Image decoration
                icon_url = None
                for img in title.get("images") or []:
                    if img.get("type") in ("Icon", "Tile", "BrandedKeyArt"):
                        icon_url = img.get("url")
                        break
                if not icon_url:
                    icon_url = title.get("displayImage")

                # pfn and store_id directly from the API
                pfn = title.get("pfn") or None
                store_id = title.get("storeId") or None

                title_history = title.get("titleHistory") or {}
                playtime_minutes = int(title_history.get("minutesPlayed") or 0)

                last_played_at = None
                last_played_str = title_history.get("lastTimePlayed")
                if last_played_str:
                    try:
                        last_played_at = datetime.fromisoformat(
                            last_played_str.replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                pg_id = await db.upsert_platform_game(
                    conn, "xbox", title_id, name, icon_url, total,
                    store_id=store_id, xbox_pfn=pfn, is_360=is_360,
                )
                await db.upsert_user_game(
                    conn, linked_id, pg_id, playtime_minutes, earned, total, last_played_at
                )

                # Both shortcuts below trust Xbox's titleHistory achievement
                # summary (total/currentAchievements) to decide whether
                # anything's worth re-checking. For legacy 360 titles that
                # summary can be simply wrong — most dangerously, a
                # too-low totalAchievements that never corrects itself. Once
                # what we've locally stored reaches that (wrong) total, the
                # "nothing changed" shortcut has no other signal telling it
                # there's more to find, and would keep skipping forever even
                # as real new unlocks come in — which looks exactly like "it
                # synced once, and unlocks since then never show up." 360
                # titles skip both shortcuts entirely and always ask the
                # achievements endpoint directly; it's one bounded, paginated
                # call, so the extra cost is small and paid only for the 360
                # titles in the library.
                if not is_360:
                    if earned == 0 and total > 0:
                        continue

                    # Skip if earned count unchanged and all achievements already stored
                    cached = earned_cache.get(title_id)
                    if cached and cached["earned"] == earned and cached["stored"] >= total > 0:
                        continue

                await asyncio.sleep(delay)

                if is_360:
                    # Fetch earned achievements (v1 API only returns earned, not locked)
                    earned_achievements = []
                    continuation = None
                    while True:
                        params = {"titleId": title_id, "maxItems": 1000}
                        if continuation:
                            params["continuationToken"] = continuation
                        ach_resp = await client.get(
                            f"{_ACH}/users/xuid({xuid})/achievements",
                            params=params,
                            headers=_xbl_headers(tokens, contract="1"),
                        )
                        if ach_resp.status_code == 429:
                            log.warning("Xbox Live rate limit hit")
                            raise RuntimeError("Xbox Live rate limit — try again later")
                        if ach_resp.status_code != 200:
                            # This used to fail silently: no log line, and
                            # whatever had been paged in so far (possibly
                            # nothing at all) was then used below as though
                            # it were the complete, correct list. A newly
                            # unlocked 360 achievement that hadn't been paged
                            # in yet would just never appear, with nothing
                            # anywhere to explain why. Logging it, and
                            # abandoning this title's update for this sync
                            # rather than writing a partial or empty result,
                            # matches how the non-360 branch below already
                            # handles a failed fetch.
                            log.warning(
                                "360 achievements fetch failed for %s: HTTP %d",
                                name, ach_resp.status_code,
                            )
                            earned_achievements = None
                            break
                        data = ach_resp.json()
                        earned_achievements.extend(data.get("achievements") or [])
                        continuation = (data.get("pagingInfo") or {}).get("continuationToken")
                        if not continuation:
                            break

                    if earned_achievements is None:
                        continue

                    earned_map = {
                        str(a.get("id")): a.get("timeUnlocked")
                        for a in earned_achievements
                    }
                    achievements = earned_achievements
                else:
                    ach_resp = await client.get(
                        f"{_ACH}/users/xuid({xuid})/achievements",
                        params={"titleId": title_id, "maxItems": 1000},
                        headers=_xbl_headers(tokens, contract="2"),
                    )
                    if ach_resp.status_code == 429:
                        log.warning("Xbox Live rate limit hit")
                        raise RuntimeError("Xbox Live rate limit — try again later")
                    if ach_resp.status_code != 200:
                        log.warning("Achievements fetch failed for %s: HTTP %d", name, ach_resp.status_code)
                        continue
                    achievements = ach_resp.json().get("achievements") or []
                    earned_map = {}

                if total == 0 and achievements:
                    total = len(achievements)
                    await db.upsert_platform_game(
                        conn, "xbox", title_id, name, icon_url, total,
                        store_id=store_id, xbox_pfn=pfn, is_360=is_360,
                    )
                    await db.upsert_user_game(conn, linked_id, pg_id, 0, earned, total, last_played_at)

                for ach in achievements:
                    self._inc("achievements_synced")
                    ach_id = str(ach.get("id", ""))
                    ach_name = ach.get("name", "")
                    description = ach.get("description") or ach.get("lockedDescription")

                    icon = None
                    if not is_360:
                        for media in ach.get("mediaAssets") or []:
                            if media.get("type") == "Icon":
                                icon = media.get("url")
                                break

                    points = None
                    for reward in ach.get("rewards") or []:
                        if reward.get("type") == "Gamerscore":
                            try:
                                points = int(reward.get("value", 0))
                            except (TypeError, ValueError):
                                pass
                            break
                    # v1 (360): gamerscore is a top-level field
                    if points is None and ach.get("gamerscore") is not None:
                        try:
                            points = int(ach["gamerscore"])
                        except (TypeError, ValueError):
                            pass

                    rarity_pct = None
                    rarity = ach.get("rarity") or {}
                    if rarity.get("currentPercentage") is not None:
                        try:
                            rarity_pct = float(rarity["currentPercentage"])
                        except (TypeError, ValueError):
                            pass

                    if is_360:
                        time_str = earned_map.get(ach_id)
                        unlocked = time_str is not None
                        unlocked_at = None
                        if time_str and time_str not in ("", "0001-01-01T00:00:00.0000000Z", "0001-01-01T00:00:00Z"):
                            try:
                                unlocked_at = datetime.fromisoformat(
                                    time_str.replace("Z", "+00:00")
                                )
                            except ValueError:
                                pass
                    else:
                        unlocked = ach.get("progressState") == "Achieved"
                        unlocked_at = None
                        if unlocked:
                            time_str = (ach.get("progression") or {}).get("timeUnlocked")
                            if time_str and time_str not in ("", "0001-01-01T00:00:00.0000000Z", "0001-01-01T00:00:00Z"):
                                try:
                                    unlocked_at = datetime.fromisoformat(
                                        time_str.replace("Z", "+00:00")
                                    )
                                except ValueError:
                                    pass

                    db_ach_id = await db.upsert_achievement(
                        conn, pg_id, ach_id, ach_name, description, icon, points, rarity_pct
                    )
                    await db.upsert_user_achievement(
                        conn, linked_id, db_ach_id, unlocked, unlocked_at
                    )
