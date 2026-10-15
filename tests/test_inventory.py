from mio.workers import inventory_workspace


def test_inventory_does_not_include_dotenv_or_symlinks(tmp_path):
    (tmp_path / "file.py").write_text("print('hi')")
    (tmp_path / ".env").write_text("SECRET=never show")
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "passwords.txt").write_text("nope")
    (tmp_path / "link.py").symlink_to(tmp_path / "file.py")
    report = inventory_workspace(tmp_path)
    assert report["visible_file_count"] == 1
    assert report["sample_files"] == ["file.py"]
