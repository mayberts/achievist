"""
Database backups.

Uses `pg_dump` (custom format) against DATABASE_URL, since Pantheon's entire
state — synced games/achievements *and* connected-account credentials — lives
in Postgres. Backups land in /backups (a persistent volume) with a retention
policy that keeps the most recent N.

Restore on the host:
    docker compose exec -T db pg_restore -U pantheon -d pantheon --clean --if-exists < backup.dump
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from app import config

log = logging.getLogger(__name__)

BACKUP_DIR = Path("/backups")
_FILENAME_RE = re.compile(r"^pantheon-\d{8}-\d{6}\.dump$")


def resolve_backup_path(filename: str) -> Path:
    """
    Resolve a backup filename to a path inside BACKUP_DIR, rejecting anything
    that isn't an exact match for our own naming scheme (blocks path
    traversal like '../../etc/passwd').
    """
    if not _FILENAME_RE.match(filename):
        raise ValueError(f"Invalid backup filename: {filename!r}")
    return BACKUP_DIR / filename


def select_backups_to_remove(names_with_mtime: list[tuple[str, float]], keep: int) -> list[str]:
    """
    Pure retention logic: given (filename, mtime) pairs, return the names that
    fall outside the most recent `keep`. Split out from the filesystem calls
    in enforce_retention() so it's trivially testable.
    """
    ordered = sorted(names_with_mtime, key=lambda x: x[1], reverse=True)
    return [name for name, _ in ordered[keep:]]


def _existing_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("pantheon-*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)


def enforce_retention(keep: int | None = None) -> list[str]:
    keep = config.BACKUP_KEEP_COUNT if keep is None else keep
    files = _existing_backups()
    to_remove = select_backups_to_remove([(f.name, f.stat().st_mtime) for f in files], keep)
    by_name = {f.name: f for f in files}
    for name in to_remove:
        by_name[name].unlink(missing_ok=True)
        log.info("Removed old backup: %s", name)
    return to_remove


async def create_backup() -> Path:
    """Run pg_dump and write a timestamped .dump file, then prune old ones."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"pantheon-{stamp}.dump"

    proc = await asyncio.create_subprocess_exec(
        "pg_dump", config.DATABASE_URL, "-Fc", "-f", str(dest),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed: {stderr.decode(errors='replace')[:500]}")

    log.info("Backup created: %s (%d bytes)", dest.name, dest.stat().st_size)
    enforce_retention()
    return dest


async def create_backup_safe() -> None:
    """Scheduler-safe wrapper — logs failures instead of crashing the job loop."""
    try:
        await create_backup()
    except Exception:
        log.exception("Scheduled backup failed")


def list_backups() -> list[dict]:
    return [
        {
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
        for f in _existing_backups()
    ]


def delete_backup(filename: str) -> None:
    resolve_backup_path(filename).unlink(missing_ok=True)
