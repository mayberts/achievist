from app.platforms.base import Platform
from app.platforms.exophase import sync_environment


class GOGPlatform(Platform):
    KEY = "gog"
    LABEL = "GOG"
    # GOG doesn't expose a usable public achievements API of its own for
    # third-party sync (ruled out earlier in this app's history). Exophase
    # already has this data (confirmed live against a real account,
    # environment slug "gog") through the same public per-player API used
    # for EA/Ubisoft/Google Play, riding on the app's existing Exophase
    # login — no separate credential needed here.
    EXTERNAL_ID = "gog"
    CONNECT_FIELDS: list[dict] = []

    async def sync(self, account: dict, conn) -> None:
        await sync_environment(self, conn, "gog", "gog", account)
