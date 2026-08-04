from app.platforms.base import Platform
from app.platforms.exophase import sync_environment


class EAPlatform(Platform):
    KEY = "ea"
    LABEL = "EA App"
    # EA has no reachable achievements API of its own — its unofficial GraphQL
    # backend has introspection disabled and rejects reconstructed queries
    # with no diagnostic detail, a dead end. Exophase has already done that
    # reverse engineering and exposes it through a public per-player API,
    # riding on the same Exophase login already configured for Xbox 360 icon
    # enrichment (EXOPHASE_PLAYER_ID/EXOPHASE_ACCESS_TOKEN) — no separate
    # per-account credential needed here.
    EXTERNAL_ID = "ea"
    CONNECT_FIELDS: list[dict] = []

    async def sync(self, account: dict, conn) -> None:
        await sync_environment(self, conn, "ea", "origin", account)
