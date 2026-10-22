"""Owner-token protected, read-only Work endpoints for sealed engineering reviews.

All dossier content is reconstructed against authenticated immutable evidence.
There are deliberately no mutation, approval, shell or patch-application routes.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

from mio.autonomy_benchmarks import CAMPAIGN_ID, CASE_IDS
from mio.autonomy_reviews import SEAL_NAME, verify_seal
from scripts.native_runtime import RUNTIME

MAX_LIST = 64


def _store_is_private(root: Path) -> bool:
    try:
        info = root.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISDIR(info.st_mode) or root.is_symlink()
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise RuntimeError("Private engineering review storage is unsafe")
    return True


def _authenticated(store: Path, campaign: str, *, show_diffs: bool = False) -> dict:
    if not CAMPAIGN_ID.fullmatch(campaign):
        raise HTTPException(status_code=404, detail="Review campaign unavailable")
    try:
        result = verify_seal(store, campaign, show_diffs=show_diffs)
        if (result.get("seal_verified") is not True
                or result.get("owner_approved_apply") is not False
                or result.get("source_applied") is not False
                or result.get("status") != "owner_review_required"
                or set(result.get("cases", {})) != set(CASE_IDS)):
            raise RuntimeError("Review failed authenticated safety checks")
        return result
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=409, detail="Sealed review evidence unavailable or invalid") from exc


def register_autonomy_review_routes(
    app: FastAPI,
    require_token: Callable,
    store: Path = RUNTIME / "autonomy",
) -> None:
    """Register only GET routes, inheriting the existing MioAgent owner bearer check."""
    auth = [Depends(require_token)]

    @app.get("/api/work/engineering/reviews", dependencies=auth)
    def reviews():
        parent = store / "engineering-benchmarks"
        try:
            if not _store_is_private(store) or not _store_is_private(parent):
                return {"campaigns": [], "permissions": {"apply": False, "approve": False}}
            entries = []
            for child in sorted(parent.iterdir(), key=lambda item: item.name):
                if not CAMPAIGN_ID.fullmatch(child.name):
                    continue
                if not _store_is_private(child):
                    raise RuntimeError("Campaign directory missing or unsafe")
                seal = child / SEAL_NAME
                if not seal.exists() and not seal.is_symlink():
                    continue
                if len(entries) >= MAX_LIST:
                    raise RuntimeError("Too many sealed reviews to list")
                report = _authenticated(store, child.name)
                entries.append({
                    "campaign": child.name,
                    "base_commit": report["base_commit"],
                    "review_sha256": report["review_sha256"],
                    "cases": {
                        name: {"model": data["model"],
                               "changed_files": data["changed_files"],
                               "trusted_tests": data["trusted_tests_passed"],
                               "hidden_tests": data["hidden_tests_passed"]}
                        for name, data in report["cases"].items()
                    },
                    "seal_verified": True,
                })
            return {"campaigns": entries, "permissions": {"apply": False, "approve": False}}
        except HTTPException:
            raise
        except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="Private review inventory invalid") from exc

    @app.get("/api/work/engineering/reviews/{campaign}", dependencies=auth)
    def review(campaign: str):
        return _authenticated(store, campaign)

    @app.get("/api/work/engineering/reviews/{campaign}/diff/{case}", dependencies=auth)
    def case_diff(campaign: str, case: str):
        if case not in CASE_IDS:
            raise HTTPException(status_code=404, detail="Engineering case unavailable")
        report = _authenticated(store, campaign, show_diffs=True)
        item = report["cases"][case]
        return {
            "campaign": campaign,
            "case": case,
            "review_sha256": report["review_sha256"],
            "model": item["model"],
            "changed_files": item["changed_files"],
            "patch": item["patch"],
            "patch_sha256": item["patch_sha256"],
            "trusted_tests": item["trusted_tests_passed"],
            "hidden_tests": item["hidden_tests_passed"],
            "seal_verified": True,
            "owner_approved_apply": False,
            "source_applied": False,
        }
