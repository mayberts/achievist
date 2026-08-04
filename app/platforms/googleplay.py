from app import config
from app.platforms.base import Platform
from app.platforms.exophase import CONNECT_FIELDS, sync_environment


class GooglePlayPlatform(Platform):
    KEY = "googleplay"
    LABEL = "Google Play Games"
    # Google Play Games Services does have an official achievements API, but
    # it requires registering a Google Cloud OAuth client and a full consent
    # flow per user — heavier than this app's other unofficial-API platforms
    # need. Exophase already has this data (confirmed live against a real
    # account) through the same public per-player API used for EA/Ubisoft.
    # Each family member can supply their own Exophase login, or fall back
    # to the server's shared EXOPHASE_PLAYER_ID/EXOPHASE_ACCESS_TOKEN.
    EXTERNAL_ID = "googleplay"
    CONNECT_FIELDS = CONNECT_FIELDS

    async def sync(self, account: dict, conn) -> None:
        player_id = self.cred(account, "exophase_player_id", config.EXOPHASE_PLAYER_ID)
        access_token = self.cred(account, "exophase_access_token", config.EXOPHASE_ACCESS_TOKEN)
        await sync_environment(self, conn, "googleplay", "android", account, player_id, access_token)
