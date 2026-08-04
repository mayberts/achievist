from app.platforms.base import Platform
from app.platforms.exophase import sync_environment


class UbisoftPlatform(Platform):
    KEY = "ubisoft"
    LABEL = "Ubisoft Connect"
    # Ubisoft's own public club-actions API mostly returns generic XP-granting
    # "actions" rather than curated trophy-style achievements — low-value data
    # even though the API itself works. Exophase already normalizes Ubisoft
    # achievement data the same way it does EA's, through a public per-player
    # API riding on the app's existing Exophase login
    # (EXOPHASE_PLAYER_ID/EXOPHASE_ACCESS_TOKEN) — no separate per-account
    # credential (and no more expiring session ticket) needed here.
    EXTERNAL_ID = "ubisoft"
    CONNECT_FIELDS: list[dict] = []

    async def sync(self, account: dict, conn) -> None:
        await sync_environment(self, conn, "ubisoft", "uplay", account)
