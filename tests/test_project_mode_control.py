import os

import pytest

from scripts import project_mode_control as pmc


def test_optin_marker_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(pmc, "MARKER", tmp_path / "project-mode-enabled")
    monkeypatch.setattr(pmc, "setup_runtime", lambda: None)
    assert not pmc.enabled()
    pmc.set_enabled(True)
    assert pmc.enabled()
    assert os.stat(pmc.MARKER).st_mode & 0o077 == 0
    pmc.set_enabled(False)
    assert not pmc.enabled()


def test_bad_marker_permissions(tmp_path, monkeypatch):
    marker = tmp_path / "project-mode-enabled"
    marker.write_text("enabled\n", encoding="utf-8")
    marker.chmod(0o644)
    monkeypatch.setattr(pmc, "MARKER", marker)
    with pytest.raises(RuntimeError, match="owner-private"):
        pmc.enabled()
