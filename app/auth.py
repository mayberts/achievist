import hashlib
import hmac
import secrets

# Stdlib PBKDF2 rather than adding bcrypt/argon2 as a new dependency — this
# is a self-hosted single-family app, not a public-facing service handling
# large numbers of accounts, so the extra dependency isn't worth it.
_ITERATIONS = 260_000
_ALGO = "sha256"

SESSION_COOKIE = "achievist_session"
SESSION_TTL_DAYS = 30


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(_ALGO, password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac(_ALGO, password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return hmac.compare_digest(expected.hex(), digest_hex)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


# A real hash of a value nobody can log in with, so a login attempt for an
# unknown username can still pay the same PBKDF2 cost as a real one. Without
# it, "no such user" returns in microseconds while a wrong password takes
# ~100ms, which tells an attacker exactly which accounts exist.
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))
