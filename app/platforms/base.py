from abc import ABC, abstractmethod


class Platform(ABC):
    # ── Connection metadata (drives the Settings UI) ─────────────────────────
    # Subclasses override these so the frontend can render connect forms and
    # the backend knows how to validate/store credentials.
    KEY: str = ""            # platform key, e.g. "steam"
    LABEL: str = ""          # display name, e.g. "Steam"
    AUTH_TYPE: str = "form"  # "form" (field inputs) or "oauth" (device flow, e.g. Xbox)
    # Field schema for form-based platforms. Each entry:
    #   {"name", "label", "type": "text"|"password", "required", "help"?, "secret"?}
    # The field named "external_id" (if present) becomes the account's unique id;
    # otherwise a fixed EXTERNAL_ID is used.
    CONNECT_FIELDS: list[dict] = []
    EXTERNAL_ID: str | None = None  # fixed id for single-identity platforms (gw2, xbox, ubisoft)

    def __init__(self):
        self._progress: dict | None = None

    def _inc(self, key: str, amount: int = 1) -> None:
        if self._progress is not None:
            self._progress[key] = self._progress.get(key, 0) + amount

    @staticmethod
    def cred(account: dict, key: str, default=None):
        """Read a credential from the account's stored credentials JSON."""
        creds = account.get("credentials") or {}
        val = creds.get(key)
        return val if val not in (None, "") else default

    @classmethod
    def connect_schema(cls) -> dict:
        """Serializable description of how to connect this platform (for the UI)."""
        return {
            "key": cls.KEY,
            "label": cls.LABEL,
            "auth_type": cls.AUTH_TYPE,
            "fields": cls.CONNECT_FIELDS,
        }

    @abstractmethod
    async def sync(self, account: dict, conn) -> None:
        """Pull data for `account` and upsert into DB via `conn`."""
