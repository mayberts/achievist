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


def request_is_https(request) -> bool:
    """
    Whether this request reached the user over https.

    X-Forwarded-Proto is checked first and on purpose. uvicorn runs without
    --proxy-headers here, so behind a TLS-terminating reverse proxy the app
    only ever sees http on the socket and request.url.scheme would always say
    "http" — auto-detection would then never enable Secure on exactly the
    deployments that need it.

    The header is client-controllable in principle, but the only thing it can
    influence is whether a cookie gets a stricter flag, and a proxy that
    terminates TLS overwrites it anyway.
    """
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        # A chain of proxies appends, e.g. "https, http" — the first entry is
        # the one the browser actually spoke.
        return forwarded.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def cookie_secure(request) -> bool:
    """Resolve config.COOKIE_SECURE against this request."""
    from app import config

    if config.COOKIE_SECURE == "true":
        return True
    if config.COOKIE_SECURE == "false":
        return False
    return request_is_https(request)
