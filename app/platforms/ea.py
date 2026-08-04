import asyncio
import logging
from datetime import datetime

import httpx

from app import config, db
from app.platforms.base import Platform

log = logging.getLogger(__name__)

_GRAPHQL = "https://service-aggregation-layer.juno.ea.com/graphql"

_IDENTITY_QUERY = "query GetIdentity { me { player { pd psd displayName } } }"

_OWNED_GAMES_QUERY = """
query GetOwnedGameProducts($locale: Locale!) {
  me {
    ownedGameProducts(
      storefronts: [EA]
      type: [DIGITAL_FULL_GAME, DIGITAL_EXPANSION]
      platforms: [PC]
      limit: 9999
      locale: $locale
    ) {
      items {
        originOfferId
        product { id name gameSlug baseItem { gameType } }
      }
    }
  }
}
"""

_ACHIEVEMENTS_QUERY = """
query GetAchievements($offerId: String!, $playerPsd: String!, $locale: Locale!) {
  achievements(offerId: $offerId, playerPsd: $playerPsd, locale: $locale) {
    id
    achievements { id name description awardCount date }
  }
}
"""


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%dT%H:%M:%S.%fZ")
    except Exception:
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None


class EAPlatform(Platform):
    KEY = "ea"
    LABEL = "EA App"
    EXTERNAL_ID = "ea"  # single-identity: the real player id only becomes known from the token itself
    CONNECT_FIELDS = [
        {"name": "access_token", "label": "EA Access Token", "type": "password", "required": True, "secret": True,
         "help": "While logged into EA in your browser, open "
                 "https://accounts.ea.com/connect/auth?client_id=ORIGIN_JS_SDK&response_type=token"
                 "&redirect_uri=nucleus:rest&prompt=none — copy the access_token value from the "
                 "redirected URL. This is unofficial and the token expires periodically, so you'll "
                 "need to repeat this and reconnect when sync starts failing."},
    ]

    async def _gql(self, client, headers, query, variables):
        r = await client.post(_GRAPHQL, json={"query": query, "variables": variables}, headers=headers)
        if r.status_code == 401:
            raise RuntimeError("EA access token expired or invalid — reconnect with a fresh token.")
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(f"EA GraphQL error: {data['errors']}")
        return data.get("data") or {}

    async def sync(self, account: dict, conn) -> None:
        token = self.cred(account, "access_token")
        if not token:
            raise RuntimeError("Missing EA access token.")
        delay = config.REQUEST_DELAY_SECONDS
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30) as client:
            identity = await self._gql(client, headers, _IDENTITY_QUERY, {})
            player = ((identity.get("me") or {}).get("player") or {})
            player_psd = player.get("psd")
            if not player_psd:
                raise RuntimeError("Could not resolve EA player identity from this token.")

            external_id = player.get("pd") or player_psd
            linked_id = await db.upsert_linked_account(conn, "ea", str(external_id))
            earned_cache = await db.get_earned_counts(conn, linked_id)

            await asyncio.sleep(delay)
            owned = await self._gql(client, headers, _OWNED_GAMES_QUERY, {"locale": "en_US"})
            games = ((owned.get("me") or {}).get("ownedGameProducts") or {}).get("items") or []
            log.info("EA: %d owned games for %s", len(games), external_id)

            for g in games:
                offer_id = g.get("originOfferId")
                product = g.get("product") or {}
                name = product.get("name")
                if not offer_id or not name:
                    continue

                await asyncio.sleep(delay)
                try:
                    adata = await self._gql(
                        client, headers, _ACHIEVEMENTS_QUERY,
                        {"offerId": offer_id, "playerPsd": player_psd, "locale": "en_US"},
                    )
                except RuntimeError:
                    continue  # not every EA product has an achievement set

                sets = adata.get("achievements") or {}
                definitions = sets.get("achievements") or []
                if not definitions:
                    continue

                total = len(definitions)
                earned = sum(1 for a in definitions if (a.get("awardCount") or 0) > 0)

                self._inc("games_seen")
                pg_id = await db.upsert_platform_game(conn, "ea", offer_id, name, None, total)
                await db.upsert_user_game(conn, linked_id, pg_id, 0, earned, total, None)

                cached = earned_cache.get(offer_id)
                if cached and cached["earned"] == earned and cached["stored"] >= total > 0:
                    continue

                for a in definitions:
                    aid = str(a.get("id") or "")
                    ach_name = a.get("name") or aid
                    if not aid:
                        continue
                    self._inc("achievements_synced")
                    is_unlocked = (a.get("awardCount") or 0) > 0
                    db_ach_id = await db.upsert_achievement(
                        conn, pg_id, aid, ach_name, a.get("description"), None, None, None,
                    )
                    await db.upsert_user_achievement(
                        conn, linked_id, db_ach_id, is_unlocked, _parse_date(a.get("date")) if is_unlocked else None,
                    )
