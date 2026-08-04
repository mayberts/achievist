from app import config
from app.platforms.base import Platform
from app.platforms.exophase import CONNECT_FIELDS, sync_environment


class GOGPlatform(Platform):
    KEY = "gog"
    LABEL = "GOG"
    # GOG doesn't expose a usable public achievements API of its own for
    # third-party sync (ruled out earlier in this app's history). Exophase
    # already has this data (confirmed live against a real account,
    # environment slug "gog") through the same public per-player API used
    # for EA/Ubisoft/Google Play. Each family member can supply their own
    # Exophase login, or fall back to the server's shared
    # EXOPHASE_PLAYER_ID/EXOPHASE_ACCESS_TOKEN.
    EXTERNAL_ID = "gog"
    CONNECT_FIELDS = CONNECT_FIELDS

    async def sync(self, account: dict, conn) -> None:
        player_id = self.cred(account, "exophase_player_id", config.EXOPHASE_PLAYER_ID)
        access_token = self.cred(account, "exophase_access_token", config.EXOPHASE_ACCESS_TOKEN)
        await sync_environment(self, conn, "gog", "gog", account, player_id, access_token)
