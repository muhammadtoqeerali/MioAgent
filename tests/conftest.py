"""Make the entire Python test suite independent of active workstation models.

All real-fleet acceptance tests pass their own explicit policy or monkeypatch it.
Unrelated API/worker tests use mock model IDs and must not read an operator's
private /var/tmp/mioagent-native-<uid>/model-fleet.json. The active policy is
never read, renamed, disabled, or modified by these tests.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_live_fleet_policy(tmp_path, monkeypatch):
    """Give each test its own absent, owner-private fleet policy path."""
    private = tmp_path / "isolated-fleet"
    private.mkdir(mode=0o700)
    monkeypatch.setattr(
        "mio.model_fleet.policy_path", lambda: private / "model-fleet.json"
    )
