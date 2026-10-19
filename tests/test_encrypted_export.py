"""Real GPG round-trip and safety tests; no network or credentials needed."""

import sqlite3
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mio.durable_storage import StorageError
from mio.encrypted_export import export_encrypted, verify_encrypted
from scripts import encrypted_backup

SECRET = "a long unique sample passphrase 2026"


@pytest.fixture
def fixture(tmp_path: Path):
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    (root / "data").mkdir(mode=0o700)
    (root / "projects").mkdir(mode=0o700)
    (root / "projects" / "test_calc.py").write_text("assert 1 + 1 == 2\n")
    with sqlite3.connect(root / "data" / "mioagent.db") as db:
        db.execute("CREATE TABLE tasks (id INTEGER)")
        db.execute("INSERT INTO tasks (id) VALUES (1)")
    return root, tmp_path / "backup.gpg"


def export(root, out, password=SECRET):
    with patch("mio.durable_storage.filesystem_type", return_value="ext4"):
        return export_encrypted(root, out, password, max_mib=2)


def test_real_gpg_round_trip(fixture):
    root, path = fixture
    generated = export(root, path)
    assert generated["encrypted_file"] == str(path)
    assert generated["encrypted_bytes"] > 150
    assert generated["artifact_files"] == 1
    assert b"assert 1 + 1" not in path.read_bytes()
    result = verify_encrypted(path, SECRET, max_mib=2)
    assert result["verified"] is True
    assert result["files"] == 2
    assert result["sqlite_integrity"] == "ok"


def test_reject_existing_ciphertext(fixture):
    root, path = fixture
    path.write_bytes(b"existing safe archive")
    with pytest.raises(StorageError, match="overwrite"):
        export(root, path)
    assert path.read_bytes() == b"existing safe archive"


def test_reject_existing_symlink(fixture):
    root, path = fixture
    destination = path.with_suffix(".txt")
    destination.write_text("leave untouched")
    path.symlink_to(destination)
    with pytest.raises(StorageError, match="overwrite"):
        export(root, path)
    assert destination.read_text() == "leave untouched"


def test_reject_short_password_before_creating_file(fixture):
    root, path = fixture
    with pytest.raises(StorageError, match="passphrase"):
        export(root, path, "short")
    assert not path.exists()


def test_reject_wrong_extension(fixture):
    root, path = fixture
    with pytest.raises(StorageError, match="end in .gpg"):
        export(root, path.with_suffix(".txt"))


def test_reject_symlinked_project_source(fixture):
    root, path = fixture
    (root / "projects" / "bad.py").symlink_to(root / "data" / "mioagent.db")
    with pytest.raises(StorageError, match="Unsafe artifact"):
        export(root, path)
    assert not path.exists()


def test_reject_large_budget(fixture):
    root, path = fixture
    with (
        patch("mio.durable_storage.filesystem_type", return_value="ext4"),
        pytest.raises(StorageError, match="budget"),
    ):
        export_encrypted(root, path, SECRET, max_mib=0)


def test_corrupt_ciphertext_fails_verification(fixture):
    root, path = fixture
    export(root, path)
    ciphertext = bytearray(path.read_bytes())
    ciphertext[-6] ^= 0xA7
    path.write_bytes(ciphertext)
    with pytest.raises((StorageError, OSError, ValueError, tarfile.TarError, EOFError)):
        verify_encrypted(path, SECRET, max_mib=2)


def test_wrong_passphrase_fails(fixture):
    root, path = fixture
    export(root, path)
    with pytest.raises((StorageError, tarfile.TarError, EOFError)):
        verify_encrypted(path, "long enough but incorrect passphrase", max_mib=2)


def test_offline_create_refuses_services_missing(monkeypatch, fixture):
    monkeypatch.setattr(encrypted_backup, "is_running", lambda role: role == "api")
    with pytest.raises(StorageError, match="both managed services"):
        encrypted_backup.create(fixture[1], 2)


def test_offline_create_refuses_active_jobs(monkeypatch, fixture):
    monkeypatch.setattr(encrypted_backup, "is_running", lambda _: True)
    monkeypatch.setattr(encrypted_backup, "_no_active_jobs", lambda: (_ for _ in ()).throw(
        StorageError("1 active or queued tasks")
    ))
    with pytest.raises(StorageError, match="active"):
        encrypted_backup.create(fixture[1], 2)


def test_no_plaintext_or_model_secrets_in_archive(fixture):
    root, path = fixture
    (root / "api-token").write_text("SUPPOSED_SECRET_API_TOKEN")
    (root / "model.env").write_text("SUPPOSED_SECRET_MODEL_CONFIG")
    export(root, path)
    encrypted = path.read_bytes()
    assert b"SUPPOSED_SECRET_API_TOKEN" not in encrypted
    assert b"SUPPOSED_SECRET_MODEL_CONFIG" not in encrypted
    assert b"SQLite format 3" not in encrypted
