"""AUT4D API tests: bearer gate, immutable read-only evidence, tampering and scope."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from mio import autonomy_review_api as api

CAMPAIGN = "a" * 32
REVIEW_SHA = "b" * 64


def _report(show_diffs=False):
    cases = {}
    for key in api.CASE_IDS:
        cases[key] = {
            "model": "gpt-oss:20b", "changed_files": ["example.py"],
            "trusted_tests_passed": 9, "hidden_tests_passed": 6,
            "patch_sha256": "c" * 64,
            **({"patch": "--- a/example.py\n+++ b/example.py\n"} if show_diffs else {}),
        }
    return {
        "campaign": CAMPAIGN, "base_commit": "d" * 40,
        "review_sha256": REVIEW_SHA, "seal_verified": True,
        "owner_approved_apply": False, "source_applied": False,
        "status": "owner_review_required", "cases": cases,
    }


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    store = tmp_path / "autonomy"
    folder = store / "engineering-benchmarks" / CAMPAIGN
    folder.mkdir(parents=True, mode=0o700)
    store.chmod(0o700)
    folder.parent.chmod(0o700)
    (folder / api.SEAL_NAME).write_text("fixture")
    def verifier(path, campaign, *, show_diffs=False):
        assert path == store and campaign == CAMPAIGN
        return _report(show_diffs)
    monkeypatch.setattr(api, "verify_seal", verifier)
    app = FastAPI()
    def require_token(authorization: str | None = Header(default=None)):
        if authorization != "Bearer test-owner":
            raise HTTPException(status_code=401, detail="Unauthorized")
    api.register_autonomy_review_routes(app, require_token, store)
    return TestClient(app), store, folder


def _get(client, path, *, token=True):
    return client.get(path, headers={"Authorization": "Bearer test-owner"} if token else {})


def test_requires_owner_token(prepared):
    client, _, _ = prepared
    for path in ("/api/work/engineering/reviews",
                 "/api/work/engineering/reviews/" + CAMPAIGN,
                 "/api/work/engineering/reviews/" + CAMPAIGN + "/diff/invoice"):
        assert _get(client, path, token=False).status_code == 401


def test_inventory_does_not_disclose_patches(prepared):
    client, _, _ = prepared
    response = _get(client, "/api/work/engineering/reviews")
    assert response.status_code == 200
    body = response.json()
    assert body["permissions"] == {"apply": False, "approve": False}
    assert len(body["campaigns"]) == 1
    assert body["campaigns"][0]["review_sha256"] == REVIEW_SHA
    assert "patch" not in str(body)


def test_detail_summarizes_without_diff(prepared):
    client, _, _ = prepared
    response = _get(client, "/api/work/engineering/reviews/" + CAMPAIGN)
    assert response.status_code == 200
    assert response.json()["review_sha256"] == REVIEW_SHA
    assert "patch" not in response.json()["cases"]["invoice"]


def test_diff_explicit_and_read_only(prepared):
    client, _, _ = prepared
    response = _get(client, "/api/work/engineering/reviews/" + CAMPAIGN + "/diff/invoice")
    assert response.status_code == 200
    assert response.json()["patch"].startswith("--- a/")
    assert response.json()["owner_approved_apply"] is False
    assert response.json()["source_applied"] is False


@pytest.mark.parametrize("name", ["../etc", "invalid", "a" * 31, "b" * 33, "A" * 32])
def test_refuse_invalid_identifiers(prepared, name):
    client, _, _ = prepared
    response = _get(client, "/api/work/engineering/reviews/" + name)
    assert response.status_code in (404, 422)


def test_refuse_unknown_case(prepared):
    client, _, _ = prepared
    assert _get(client, "/api/work/engineering/reviews/" + CAMPAIGN + "/diff/nope").status_code == 404


def test_refuse_tampered_verification(prepared, monkeypatch):
    client, _, _ = prepared
    for tamper in ({"seal_verified": False}, {"owner_approved_apply": True},
                   {"source_applied": True}, {"cases": {}}):
        monkeypatch.setattr(api, "verify_seal", lambda *args, tamper=tamper, **kwargs: {**_report(), **tamper})
        assert _get(client, "/api/work/engineering/reviews/" + CAMPAIGN).status_code == 409


def test_refuse_untrusted_storage(prepared):
    client, _, folder = prepared
    folder.chmod(0o777)
    assert _get(client, "/api/work/engineering/reviews").status_code == 409


def test_never_exposes_mutation_methods(prepared):
    client, _, _ = prepared
    paths = ["/api/work/engineering/reviews", "/api/work/engineering/reviews/" + CAMPAIGN]
    for path in paths:
        response = client.post(path, headers={"Authorization": "Bearer test-owner"})
        assert response.status_code == 405
    paths = {route.path: route.methods for route in client.app.routes if hasattr(route, "methods")}
    for path, methods in paths.items():
        if path.startswith("/api/work/engineering/reviews"):
            assert methods == {"GET"}


def test_fullmatch_campaign_validation():
    assert api.CAMPAIGN_ID.fullmatch(CAMPAIGN)
    assert not api.CAMPAIGN_ID.fullmatch(CAMPAIGN + "/etc")
    assert re.fullmatch(r"[0-9a-f]{32}", CAMPAIGN)
