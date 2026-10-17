"""Offline storage snapshot safety, size budget, and integrity tests."""

import json
import os
import sqlite3

import pytest

from mio import durable_storage as ds


def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "filesystem_type", lambda path: "ext4")
    monkeypatch.setattr(ds, "TEMPORARY_PATHS", ())
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (runtime / "data").mkdir(mode=0o700)
    (runtime / "projects").mkdir(mode=0o700)
    db_path = runtime / "data" / "mioagent.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO records (value) VALUES ('test')")
    os.chmod(db_path, 0o600)
    project_dir = runtime / "projects" / "project-1"
    project_dir.mkdir(mode=0o700)
    (project_dir / "example.py").write_text("print('ok')\n", encoding="utf-8")
    target = tmp_path / "durable"
    target.mkdir(mode=0o700)
    return runtime, target


def test_snapshot_full_backup_and_verify(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    snap = ds.create_snapshot(runtime, target)
    assert snap.name.startswith("snapshot-")
    assert ds.verify_snapshot(snap)["verified_files"] == 2
    with sqlite3.connect(snap / "data" / "mioagent.db") as db:
        assert db.execute("SELECT value FROM records").fetchone() == ("test",)
    manifest = json.loads((snap / "manifest.json").read_text())
    assert manifest["excludes_credentials"] is True


def test_creating_snapshot_does_not_modify_source(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    before = (runtime / "projects" / "project-1" / "example.py").read_bytes()
    ds.create_snapshot(runtime, target)
    assert (runtime / "projects" / "project-1" / "example.py").read_bytes() == before


def test_excludes_credentials_and_runtime_flags(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    (runtime / "api-token").write_text("private-token")
    (runtime / "model.env").write_text("private-config")
    snap = ds.create_snapshot(runtime, target)
    assert not (snap / "api-token").exists()
    assert not (snap / "model.env").exists()
    assert "private-token" not in (snap / "manifest.json").read_text()


def test_reject_tampered_project_artifact(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    snap = ds.create_snapshot(runtime, target)
    (snap / "projects" / "project-1" / "example.py").write_text("tampered")
    with pytest.raises(ds.StorageError, match="checksum mismatch"):
        ds.verify_snapshot(snap)


def test_reject_tampered_database(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    snap = ds.create_snapshot(runtime, target)
    (snap / "data" / "mioagent.db").write_bytes(b"not sqlite")
    with pytest.raises(ds.StorageError, match="checksum mismatch"):
        ds.verify_snapshot(snap)


def test_reject_unexpected_file(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    snap = ds.create_snapshot(runtime, target)
    (snap / "surprise").write_text("unexpected")
    with pytest.raises(ds.StorageError, match="Unexpected"):
        ds.verify_snapshot(snap)


def test_reject_symlinked_source_artifact(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    (runtime / "projects" / "project-1" / "steal").symlink_to(
        runtime / "data" / "mioagent.db"
    )
    with pytest.raises(ds.StorageError, match="Unsafe artifact"):
        ds.create_snapshot(runtime, target)
    assert not list(target.iterdir())


def test_reject_symlinked_source_directory(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    (runtime / "projects" / "linked").symlink_to(runtime / "data", target_is_directory=True)
    with pytest.raises(ds.StorageError, match="unsafe directory"):
        ds.create_snapshot(runtime, target)


def test_reject_broad_permissions_on_target(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    target.chmod(0o755)
    with pytest.raises(ds.StorageError, match="0700"):
        ds.create_snapshot(runtime, target)


def test_reject_temp_path_even_on_ext4(tmp_path, monkeypatch):
    _, target = environment(tmp_path, monkeypatch)
    monkeypatch.setattr(ds, "TEMPORARY_PATHS", (tmp_path,))
    with pytest.raises(ds.StorageError, match="Temporary"):
        ds.validate_target(target)


def test_reject_non_native_fs(tmp_path, monkeypatch):
    _, target = environment(tmp_path, monkeypatch)
    monkeypatch.setattr(ds, "filesystem_type", lambda path: "fuseblk")
    with pytest.raises(ds.StorageError, match="native"):
        ds.validate_target(target)


def test_reject_limit_exceeded(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    (runtime / "projects" / "project-1" / "large.bin").write_bytes(b"x" * 1024 * 1024 * 2)
    with pytest.raises(ds.StorageError, match="budget"):
        ds.create_snapshot(runtime, target, max_mib=1)
    assert not list(target.iterdir())


def test_reject_invalid_limit(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    with pytest.raises(ds.StorageError, match="budget"):
        ds.create_snapshot(runtime, target, max_mib=0)


def test_private_directory_requires_owner_only(tmp_path):
    data = tmp_path / "data"
    data.mkdir(mode=0o755)
    with pytest.raises(ds.StorageError, match="0700"):
        ds._private_directory(data)


def test_reject_path_escape_in_manifest():
    with pytest.raises(ds.StorageError, match="Invalid"):
        ds._safe_relative("projects/../../secrets")
    with pytest.raises(ds.StorageError, match="Invalid"):
        ds._safe_relative("/etc/passwd")
    with pytest.raises(ds.StorageError, match="Invalid"):
        ds._safe_relative("data")


def test_init_target_and_recheck(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "TEMPORARY_PATHS", ())
    monkeypatch.setattr(ds, "filesystem_type", lambda path: "ext4")
    dest = tmp_path / "backups"
    assert ds.initialize_target(dest) == dest
    assert ds.initialize_target(dest) == dest
    assert dest.stat().st_mode & 0o777 == 0o700


def test_no_backup_under_source(tmp_path, monkeypatch):
    runtime, _ = environment(tmp_path, monkeypatch)
    nested = runtime / "backups"
    nested.mkdir(mode=0o700)
    with pytest.raises(ds.StorageError, match="contain"):
        ds.validate_target(nested, runtime)


def test_reject_symlink_in_snapshot_when_verifying(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    snap = ds.create_snapshot(runtime, target)
    original = snap / "projects" / "project-1" / "example.py"
    original.unlink()
    original.symlink_to(runtime / "data" / "mioagent.db")
    with pytest.raises(ds.StorageError, match="unsafe"):
        ds.verify_snapshot(snap)


def test_partial_copy_cleaned_up_on_failure(tmp_path, monkeypatch):
    runtime, target = environment(tmp_path, monkeypatch)
    def fail(*args):
        raise ds.StorageError("Simulated copy failure")
    monkeypatch.setattr(ds, "_copy_checked", fail)
    with pytest.raises(ds.StorageError, match="Simulated"):
        ds.create_snapshot(runtime, target)
    assert not list(target.iterdir())


def test_sqlite_0644_is_protected_by_private_parent(tmp_path, monkeypatch):
    runtime, _ = environment(tmp_path, monkeypatch)
    (runtime / "data" / "mioagent.db").chmod(0o644)
    assert ds.inventory(runtime)["project_files"] == 1


def test_reject_non_owner_writable_sqlite(tmp_path, monkeypatch):
    runtime, _ = environment(tmp_path, monkeypatch)
    (runtime / "data" / "mioagent.db").chmod(0o666)
    with pytest.raises(ds.StorageError, match="writable by other users"):
        ds.inventory(runtime)
