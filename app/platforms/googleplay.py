from app.platforms.base import Platform
from app.platforms.exophase import sync_environment


class GooglePlayPlatform(Platform):
    KEY = "googleplay"
    LABEL = "Google Play Games"
    # Google Play Games Services does have an official achievements API, but
    # it requires registering a Google Cloud OAuth client and a full consent
    # flow per user — heavier than this app's other unofficial-API platforms
    # need. Exophase already has this data (confirmed live against a real
    # account) through the same public per-player API used for EA/Ubisoft,
    # riding on the app's existing Exophase login
    # (EXOPHASE_PLAYER_ID/EXOPHASE_ACCESS_TOKEN) — no separate credential
    # needed here.
    EXTERNAL_ID = "googleplay"
    CONNECT_FIELDS: list[dict] = []

    async def sync(self, account: dict, conn) -> None:
        await sync_environment(self, conn, "googleplay", "android", account)
