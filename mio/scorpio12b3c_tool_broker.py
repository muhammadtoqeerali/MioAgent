"""Scorpio S12B3C: offline, owner-scoped, staged Python tool broker.

Reusable control-plane primitive only.  NOT wired to API/Work, not an LLM
agent, not a grant system, and does not apply edits to an existing repository.
Actor input is untrusted; it can list/read/grep one pinned repository snapshot,
propose strictly allowlisted Python edits, and request exactly one selected-test
Bubblewrap run per attempt.  The owner, not the actor, supplies the RepoGoal.

Audit contains bounded metadata only.  Its hash chain detects alteration only
when the final head hash is independently preserved/trusted (not signatures).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

from mio.repo_agent import (
    RepoGoal,
    RepoStop,
    locked_snapshot,
    parse_edits,
    safe_path,
    staged_snapshot,
    test_staged,
)

ACTION_BUDGET = 14
READ_LIMIT = 5000
FEEDBACK_LIMIT = 1600
AUDIT_RECORD_LIMIT = 1800
MAX_EVENTS = 128
HASH = re.compile(r"[0-9a-f]{64}\Z")
ALLOWED_TOOLS = frozenset({"repo.list", "repo.read", "repo.grep", "edit.propose", "tests.run"})


class BrokerStop(RuntimeError):
    """Action rejected or safety invariant not met. No production apply."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


class AuditChain:
    """In-memory metadata journal; caller must independently pin final head."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._head = "0" * 64

    @property
    def head(self) -> str:
        return self._head

    @property
    def rows(self) -> tuple[dict[str, Any], ...]:
        # Deep copies prevent outside callers from mutating the active journal.
        return tuple(json.loads(json.dumps(row)) for row in self._rows)

    def record(self, event: str, *, attempt: int, info: dict[str, Any] | None = None) -> None:
        if not isinstance(event, str) or not re.fullmatch(r"[a-z_.]{1,48}", event):
            raise BrokerStop("Invalid audit event category")
        if type(attempt) is not int or not 0 <= attempt <= 3:
            raise BrokerStop("Invalid audit attempt")
        if len(self._rows) >= MAX_EVENTS:
            raise BrokerStop("Audit event budget exhausted")
        detail = {} if info is None else info
        if not isinstance(detail, dict) or not all(isinstance(k, str) for k in detail):
            raise BrokerStop("Invalid audit metadata")
        row = {"index": len(self._rows) + 1, "previous": self._head,
               "event": event, "attempt": attempt, "info": detail}
        raw = _canonical(row)
        if len(raw) > AUDIT_RECORD_LIMIT:
            raise BrokerStop("Audit metadata too large")
        row["sha256"] = _sha(raw)
        self._rows.append(row)
        self._head = row["sha256"]

    @staticmethod
    def verify(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...], head: str) -> bool:
        if not isinstance(head, str) or not HASH.fullmatch(head) or not rows:
            return False
        prior = "0" * 64
        try:
            for index, row in enumerate(rows, 1):
                if not isinstance(row, dict) or set(row) != {
                        "index", "previous", "event", "attempt", "info", "sha256"}:
                    return False
                if row["index"] != index or row["previous"] != prior:
                    return False
                core = {key: value for key, value in row.items() if key != "sha256"}
                expected = _sha(_canonical(core))
                if row["sha256"] != expected:
                    return False
                prior = expected
            return prior == head
        except (TypeError, ValueError, OverflowError):
            return False


def _private_scratch(root: Path) -> Path:
    """Use only an existing owner-private native runtime subdirectory."""
    base = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
    if root.is_symlink() or not root.is_absolute() or not root.is_dir() or root != root.resolve():
        raise BrokerStop("Scratch directory must already exist and be real")
    if base.is_symlink() or not base.is_dir() or not root.resolve().is_relative_to(base.resolve()):
        raise BrokerStop("Scratch directory must be inside owner native runtime")
    if root.resolve() == base.resolve():
        raise BrokerStop("Refuse native runtime root directly as scratch")
    for target in (base, root):
        info = target.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise BrokerStop("Scratch path ownership/mode is not private")
    # Reuse the existing filesystem-type guard (no NTFS/CIFS for untrusted code).
    from mio.project_mode import ALLOWED_MOUNTS, _mount_type
    if _mount_type(root.resolve()) not in ALLOWED_MOUNTS:
        raise BrokerStop("Scratch must live on approved native Linux filesystem")
    return root


class ToolBroker:
    """One owner-pinned goal, at most its approved bounded attempt count.

    This object never writes source under ``goal.root``.  File modifications live
    only in temporary staging copied from a fixed snapshot and are removed after
    tests.  All tests are executed by MioAgent's selected-file bwrap verifier.
    """

    def __init__(self, goal: RepoGoal, *, scratch: Path, budget: int = ACTION_BUDGET) -> None:
        if not isinstance(goal, RepoGoal):
            raise BrokerStop("Owner must supply an approved RepoGoal")
        if type(budget) is not int or not 1 <= budget <= ACTION_BUDGET:
            raise BrokerStop("Invalid tool-action budget")
        self.scratch = _private_scratch(scratch)
        # Validate even a preconstructed dataclass: it is not itself a grant.
        try:
            validated = RepoGoal.parse({
                "repository": str(goal.root), "task": goal.task,
                "editable_files": list(goal.editable),
                "acceptance_tests": list(goal.tests),
                "max_attempts": goal.max_attempts,
            })
        except (RepoStop, ValueError, TypeError) as exc:
            raise BrokerStop("Owner goal failed RepoGoal policy") from exc
        if validated != goal:
            raise BrokerStop("Owner goal changed during validation")
        self.goal = validated
        self.snapshot, self.test_pins = locked_snapshot(goal)
        self.original_hashes = {path: _sha(raw) for path, raw in self.snapshot.items()}
        self.budget = budget
        self.audit = AuditChain()
        self.attempt = 0
        self.sequence = 1
        self.used_actions = 0
        self.denied_actions = 0
        self.pending: dict[str, bytes] | None = None
        self.tested = False
        self.cancelled = False
        self.done = False
        self.last_public_pass: bool | None = None
        self.audit.record("controller.created", attempt=0,
                          info={"sources": len(self.snapshot), "approved_edits": len(goal.editable),
                                "selected_tests": len(goal.tests), "goal_hash": goal.digest()})

    def start_attempt(self) -> int:
        if self.cancelled or self.done or self.attempt >= self.goal.max_attempts:
            raise BrokerStop("Attempt budget finished or controller closed")
        if self.attempt and self.last_public_pass is not False:
            raise BrokerStop("Cannot retry without a recorded failed public test")
        if not self.verified_original_unchanged():
            raise BrokerStop("Owner repository changed after snapshot; refuse trial")
        self.attempt += 1
        self.sequence = 1
        self.used_actions = 0
        self.pending = None
        self.tested = False
        self.last_public_pass = None
        self.audit.record("controller.attempt", attempt=self.attempt)
        return self.attempt

    def cancel(self) -> None:
        if not self.cancelled:
            self.cancelled = True
            self.audit.record("controller.cancel", attempt=self.attempt)

    def _deny(self, category: str) -> None:
        self.denied_actions += 1
        self.audit.record("broker.denied", attempt=self.attempt,
                          info={"category": category})
        raise BrokerStop("Action denied: " + category)

    def dispatch(self, envelope: Any) -> dict[str, Any]:
        if self.attempt == 0 or self.cancelled or self.done:
            self._deny("not_active")
        # Count ALL attempts including malformed/denied calls: no infinite denial loop.
        if self.used_actions >= self.budget:
            self._deny("action_budget")
        self.used_actions += 1
        if not isinstance(envelope, dict) or set(envelope) != {"seq", "tool", "args"}:
            self._deny("envelope_schema")
        seq, tool, args = envelope["seq"], envelope["tool"], envelope["args"]
        if type(seq) is not int or seq != self.sequence:
            self._deny("sequence")
        self.sequence += 1
        if not isinstance(tool, str) or tool not in ALLOWED_TOOLS or not isinstance(args, dict):
            self._deny("tool_or_arguments_not_allowed")
        try:
            if tool == "repo.list":
                if args:
                    self._deny("tool_arguments")
                result = {"paths": sorted(self.snapshot)}
                meta = {"count": len(self.snapshot)}
            elif tool == "repo.read":
                if set(args) != {"path"}:
                    self._deny("tool_arguments")
                path = safe_path(args["path"])
                if path not in self.snapshot:
                    self._deny("read_scope")
                text = self.snapshot[path].decode("utf-8")
                if len(text) > READ_LIMIT:
                    self._deny("read_limit")
                result = {"content": text}
                meta = {"path": path, "sha256": _sha(self.snapshot[path])}
            elif tool == "repo.grep":
                if set(args) != {"path", "literal"}:
                    self._deny("tool_arguments")
                path = safe_path(args["path"])
                literal = args["literal"]
                if path not in self.snapshot or not isinstance(literal, str) or not 1 <= len(literal) <= 64:
                    self._deny("grep_scope")
                matches = [(idx, line[:160]) for idx, line in enumerate(
                    self.snapshot[path].decode("utf-8").splitlines(), 1) if literal in line][:10]
                result = {"matches": matches}
                meta = {"path": path, "matches": len(matches)}
            elif tool == "edit.propose":
                if set(args) != {"edits"}:
                    self._deny("tool_arguments")
                if self.pending is not None or self.tested:
                    self._deny("repeat_edit")
                changes = parse_edits(json.dumps({"edits": args["edits"]}), self.goal)
                if not any(self.snapshot[path] != value for path, value in changes.items()):
                    self._deny("unchanged_edit")
                self.pending = changes  # no filesystem writes until selected-test execution
                result = {"accepted_paths": sorted(changes)}
                meta = {"paths": sorted(changes),
                        "hashes": {p: _sha(v) for p, v in sorted(changes.items())}}
            elif tool == "tests.run":
                if args != {"suite": "public"}:
                    self._deny("test_scope")
                if self.pending is None or self.tested:
                    self._deny("test_order")
                if not self.verified_original_unchanged():
                    raise BrokerStop("Owner repository changed before testing")
                # Fresh synthetic-private staging; never run code in original repo.
                with tempfile.TemporaryDirectory(prefix="s12b3c-trial-", dir=self.scratch) as name:
                    stage = Path(name)
                    os.chmod(stage, 0o700)
                    # stage_snapshot requires nonexisting target, create a child.
                    candidate = stage / "snapshot"
                    staged_snapshot(candidate, self.snapshot)
                    for path, raw in self.pending.items():
                        target = candidate / path
                        if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(candidate):
                            raise BrokerStop("Unsafe synthetic staging target")
                        target.write_bytes(raw)
                    outcome = test_staged(candidate, self.goal.tests, self.test_pins)
                if not self.verified_original_unchanged():
                    raise BrokerStop("Owner repository changed during testing")
                self.tested = True
                self.last_public_pass = bool(outcome["passed"] and outcome["selected_tests_run"])
                if self.last_public_pass:
                    self.done = True
                result = {"passed": self.last_public_pass,
                          "selected_tests_run": bool(outcome["selected_tests_run"]),
                          "tests_run": int(outcome["tests_run"]),
                          "feedback": str(outcome["log"])[-FEEDBACK_LIMIT:]}
                meta = {"passed": self.last_public_pass, "tests_run": result["tests_run"],
                        "selected_tests_run": result["selected_tests_run"]}
            else:
                self._deny("tool_or_arguments_not_allowed")
        except BrokerStop:
            raise
        except (RepoStop, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._deny("repo_policy_" + type(exc).__name__)
        self.audit.record("broker.accepted", attempt=self.attempt, info={"tool": tool, **meta})
        return result

    def verified_original_unchanged(self) -> bool:
        """Compare ALL original snapshot bytes; missing or changed paths fail."""
        for path, prior in self.original_hashes.items():
            current = self.goal.root / path
            if current.is_symlink() or not current.is_file() or _sha(current.read_bytes()) != prior:
                return False
        return True

    def result(self) -> dict[str, Any]:
        return {"goal_sha256": self.goal.digest(), "attempts": self.attempt,
                "public_pass": self.last_public_pass, "done": self.done,
                "denied": self.denied_actions, "events": len(self.audit.rows),
                "audit_sha256": self.audit.head,
                "original_unchanged": self.verified_original_unchanged()}
