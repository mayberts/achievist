"""
Pure-function tests for app/backup.py — filename validation and retention
selection. Both are exercised without touching the filesystem or Postgres.
"""

import pytest

from app import backup


class TestResolveBackupPath:
    def test_accepts_valid_filename(self):
        path = backup.resolve_backup_path("pantheon-20260802-120000.dump")
        assert path == backup.BACKUP_DIR / "pantheon-20260802-120000.dump"

    @pytest.mark.parametrize("name", [
        "../../etc/passwd",
        "pantheon-20260802-120000.dump/../../etc/passwd",
        "pantheon-2026080-120000.dump",
        "pantheon-20260802-1200000.dump",
        "pantheon-20260802-120000.tar",
        "not-a-backup.dump",
        "",
        "pantheon-20260802-120000.dump.exe",
    ])
    def test_rejects_invalid_filename(self, name):
        with pytest.raises(ValueError):
            backup.resolve_backup_path(name)


class TestSelectBackupsToRemove:
    def test_keeps_most_recent_n(self):
        names_with_mtime = [
            ("a", 1.0),
            ("b", 3.0),
            ("c", 2.0),
        ]
        assert backup.select_backups_to_remove(names_with_mtime, keep=2) == ["a"]

    def test_keeps_all_when_under_limit(self):
        names_with_mtime = [("a", 1.0), ("b", 2.0)]
        assert backup.select_backups_to_remove(names_with_mtime, keep=5) == []

    def test_empty_list(self):
        assert backup.select_backups_to_remove([], keep=14) == []

    def test_keep_zero_removes_everything(self):
        names_with_mtime = [("a", 1.0), ("b", 2.0)]
        assert set(backup.select_backups_to_remove(names_with_mtime, keep=0)) == {"a", "b"}
