from app import config
from app.platforms.base import Platform
from app.platforms.exophase import CONNECT_FIELDS, sync_environment


class EAPlatform(Platform):
    KEY = "ea"
    LABEL = "EA App"
    # EA has no reachable achievements API of its own — its unofficial GraphQL
    # backend has introspection disabled and rejects reconstructed queries
    # with no diagnostic detail, a dead end. Exophase has already done that
    # reverse engineering and exposes it through a public per-player API.
    # Each family member can supply their own Exophase login, or fall back
    # to the server's shared EXOPHASE_PLAYER_ID/EXOPHASE_ACCESS_TOKEN env vars.
    EXTERNAL_ID = "ea"
    CONNECT_FIELDS = CONNECT_FIELDS

    async def sync(self, account: dict, conn) -> None:
        player_id = self.cred(account, "exophase_player_id", config.EXOPHASE_PLAYER_ID)
        access_token = self.cred(account, "exophase_access_token", config.EXOPHASE_ACCESS_TOKEN)
        await sync_environment(self, conn, "ea", "origin", account, player_id, access_token)
