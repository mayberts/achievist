"""
Failed-login throttling.

/api/auth/login previously did a PBKDF2 check and returned 401 with nothing
counting failures — no delay, no cap, no lockout. Password guessing ran as
fast as the server could hash, which for a self-hosted app that may be
reachable from the internet is the whole ballgame.

State is in memory. This app runs a single uvicorn process (see Dockerfile),
so there is nothing to share it with, and losing the counters on restart is
an acceptable trade for having no new dependency and no write per failed
attempt. If it ever runs multiple workers, this must move to Postgres —
otherwise each worker enforces its own limit and the real one multiplies.

Two keys are tracked, with deliberately different limits:

  * Per username, tightly. This is what actually stops a guessing run, since
    it holds however many addresses the attacker rotates through.
  * Per client IP, loosely. Behind a reverse proxy every request arrives from
    one address, so a tight limit here would let one attacker lock out the
    whole family. It is a backstop against someone spraying many usernames,
    not the primary defence.

Both cut the other way too: any per-username lockout lets someone deny one
person access by guessing badly on purpose. The lockout is deliberately
short so that is an annoyance rather than damage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Per username: generous enough to survive a genuinely forgotten password,
# small enough that guessing is hopeless.
USER_MAX_ATTEMPTS = 8
USER_WINDOW_SECONDS = 15 * 60
USER_LOCKOUT_SECONDS = 10 * 60

# Per IP: loose, because a reverse proxy makes this one address for everyone.
IP_MAX_ATTEMPTS = 30
IP_WINDOW_SECONDS = 15 * 60
IP_LOCKOUT_SECONDS = 10 * 60

# Stop a spray across thousands of made-up usernames from growing the table
# without bound. Well above any real family's key count.
MAX_TRACKED_KEYS = 10_000


@dataclass
class _Entry:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class LoginLimiter:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def _prune(self, now: float, window: float) -> None:
        stale = [
            k
            for k, e in self._entries.items()
            if e.locked_until < now and (not e.failures or e.failures[-1] < now - window)
        ]
        for k in stale:
            del self._entries[k]

    def retry_after(self, key: str, *, now: float | None = None) -> int:
        """Seconds the caller must wait, or 0 if it may proceed."""
        now = time.monotonic() if now is None else now
        entry = self._entries.get(key)
        if entry is None or entry.locked_until <= now:
            return 0
        # Always at least 1: a caller that is locked must never be told 0.
        return max(1, int(entry.locked_until - now))

    def record_failure(
        self, key: str, *, max_attempts: int, window: float, lockout: float, now: float | None = None
    ) -> None:
        now = time.monotonic() if now is None else now
        if len(self._entries) >= MAX_TRACKED_KEYS:
            self._prune(now, max(USER_WINDOW_SECONDS, IP_WINDOW_SECONDS))

        entry = self._entries.setdefault(key, _Entry())
        entry.failures = [t for t in entry.failures if t > now - window]
        entry.failures.append(now)
        if len(entry.failures) >= max_attempts:
            entry.locked_until = now + lockout
            # Start the next window clean, so one more failure after the
            # lockout expires does not immediately re-lock the account.
            entry.failures.clear()

    def reset(self, key: str) -> None:
        """Called on a successful login, so a good password clears the slate."""
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()


limiter = LoginLimiter()


def user_key(username: str) -> str:
    # Usernames are matched case-sensitively at the database, but the limiter
    # folds case so "Dad" and "dad" cannot be used as two separate budgets.
    return f"user:{username.strip().lower()}"


def ip_key(ip: str) -> str:
    return f"ip:{ip}"
