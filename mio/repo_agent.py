"""Bounded, auditable editing of EXISTING Python repositories.

User selects the repository, source allowlist and trusted acceptance tests.
A model may suggest file bytes only. Neither prompts nor model JSON grant tools.
All execution reuses MioAgent's existing Bubblewrap sandbox.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from mio.sandbox_verify import _bounded_run, sandbox_argv

MAX_TREE_FILES = 600
MAX_TREE_BYTES = 6_000_000
MAX_FILE_BYTES = 48_000
MAX_EDIT_BYTES = 32_000
MAX_EDITABLE = 4
MAX_TESTS = 6
MAX_LOG = 7_000
IGNORE_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                         ".mypy_cache", ".next", "dist", "build", ".mioagent-backups"})
ALLOW_SUFFIXES = frozenset({".py", ".json", ".toml", ".ini", ".txt", ".csv"})


class RepoStop(RuntimeError):
    """Fail closed without touching original repository files."""


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_path(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 180 or "\\" in name or "\x00" in name:
        raise RepoStop("Invalid relative source path")
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in (".", "..", "") for x in name.split("/")) or len(p.parts) > 9:
        raise RepoStop("Path escapes the approved repository")
    if any(x in IGNORE_DIRS or x.startswith(".") for x in p.parts):
        raise RepoStop("Hidden or generated paths are not permitted")
    return p.as_posix()


def safe_root(raw: str) -> Path:
    if not isinstance(raw, str) or not raw.startswith("/"):
        raise RepoStop("Repository root must be an absolute directory")
    p = Path(raw)
    if not p.is_dir() or p.is_symlink() or p.resolve() != p or p == Path("/"):
        raise RepoStop("Unsafe repository root")
    return p


@dataclass(frozen=True)
class RepoGoal:
    root: Path
    task: str
    editable: tuple[str, ...]
    tests: tuple[str, ...]
    max_attempts: int

    @classmethod
    def parse(cls, data: dict) -> RepoGoal:
        if not isinstance(data, dict) or set(data) != {
            "repository", "task", "editable_files", "acceptance_tests", "max_attempts"
        }:
            raise RepoStop("Goal requires exact repository, task, editable_files, acceptance_tests and max_attempts")
        root = safe_root(data["repository"])
        task = data["task"]
        if not isinstance(task, str) or not 12 <= len(task) <= 4_000:
            raise RepoStop("Task must be 12..4000 characters")
        editable = data["editable_files"]
        tests = data["acceptance_tests"]
        if (not isinstance(editable, list) or not 1 <= len(editable) <= MAX_EDITABLE
                or not isinstance(tests, list) or not 1 <= len(tests) <= MAX_TESTS):
            raise RepoStop("Allow 1..4 editable files and 1..6 acceptance tests")
        edit_paths = tuple(safe_path(x) for x in editable)
        test_paths = tuple(safe_path(x) for x in tests)
        if len(set(edit_paths + test_paths)) != len(edit_paths) + len(test_paths):
            raise RepoStop("Duplicate paths or attempted acceptance-test editing")
        if any(not p.endswith(".py") or Path(p).name.startswith("test_") for p in edit_paths):
            raise RepoStop("Only explicitly approved non-test Python sources may be edited")
        if any(not re.fullmatch(r"test_[a-zA-Z0-9_]+\.py", Path(p).name) for p in test_paths):
            raise RepoStop("Acceptance files must be test_*.py")
        attempts = data["max_attempts"]
        if type(attempts) is not int or not 1 <= attempts <= 3:
            raise RepoStop("max_attempts must be between 1 and 3")
        for name in edit_paths + test_paths:
            path = root / name
            if not path.is_file() or path.is_symlink() or path.resolve() != path:
                raise RepoStop("Approved source/test file missing or unsafe")
        return cls(root, task, edit_paths, test_paths, attempts)

    def digest(self) -> str:
        return sha(json.dumps({"repository": str(self.root), "task": self.task,
                               "editable_files": self.editable, "acceptance_tests": self.tests,
                               "max_attempts": self.max_attempts}, sort_keys=True).encode())


def index_tree(root: Path) -> dict[str, bytes]:
    """Never traverse symlinks, hidden trees, device files, or broad home directories."""
    result: dict[str, bytes] = {}
    total = 0
    for here, dirs, names in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")
                         and not (Path(here) / d).is_symlink())
        for filename in sorted(names):
            file = Path(here) / filename
            if filename.startswith(".") or file.suffix not in ALLOW_SUFFIXES or file.is_symlink():
                continue
            relative = file.relative_to(root).as_posix()
            safe_path(relative)
            if not file.is_file() or file.resolve() != file:
                raise RepoStop("Unsafe repository tree entry")
            if file.stat().st_size > MAX_FILE_BYTES:
                continue  # Huge files are not silently sent to a model.
            raw = file.read_bytes()
            if len(raw) > MAX_FILE_BYTES or b"\0" in raw:
                continue
            total += len(raw)
            if total > MAX_TREE_BYTES or len(result) >= MAX_TREE_FILES:
                raise RepoStop("Repository exceeds controlled snapshot budget")
            result[relative] = raw
    if not result:
        raise RepoStop("No eligible source files discovered")
    return result


def locked_snapshot(goal: RepoGoal) -> tuple[dict[str, bytes], dict[str, str]]:
    snapshot = index_tree(goal.root)
    approved = goal.editable + goal.tests
    for path in approved:
        if path not in snapshot:
            raise RepoStop("Approved source/test file exceeds snapshot rules")
    return snapshot, {p: sha(snapshot[p]) for p in approved}


def context(goal: RepoGoal, snapshot: dict[str, bytes], feedback: str = "") -> str:
    tree = "\n".join(f"- {p} ({len(blob)} bytes)" for p, blob in sorted(snapshot.items()))
    relevant = "\n\n".join(f"FILE {p}\n```python\n{snapshot[p].decode('utf-8')}\n```"
                              for p in goal.editable + goal.tests)
    joined = (f"USER TASK:\n{goal.task}\n\nTREE INDEX:\n{tree}\n\n"
              f"APPROVED SOURCE AND TRUSTED TESTS:\n{relevant}\n\nTEST FEEDBACK:\n{feedback[:MAX_LOG]}")
    if len(joined) > 40_000:
        raise RepoStop("Selected task context too large; narrow the editable/test allowlists")
    return joined


def parse_edits(text: str, goal: RepoGoal) -> dict[str, bytes]:
    stripped = text.strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
        stripped = stripped.removesuffix("```")
    if len(stripped) > 130_000:
        raise RepoStop("Model response exceeds edit JSON budget")
    try:
        value = json.loads(stripped.strip())
    except (ValueError, TypeError) as exc:
        raise RepoStop("Model did not return complete JSON edits") from exc
    if not isinstance(value, dict) or set(value) != {"edits"} or not isinstance(value["edits"], list):
        raise RepoStop("Model response must be exactly {edits:[{path,content}]}")
    if not 1 <= len(value["edits"]) <= len(goal.editable):
        raise RepoStop("No approved source changes proposed")
    changes: dict[str, bytes] = {}
    for item in value["edits"]:
        if not isinstance(item, dict) or set(item) != {"path", "content"}:
            raise RepoStop("Invalid model edit entry")
        path, content = item["path"], item["content"]
        if not isinstance(path, str) or path not in goal.editable or path in changes or not isinstance(content, str):
            raise RepoStop("Model attempted non-allowlisted or duplicate edit")
        raw = content.encode("utf-8")
        if not raw or len(raw) > MAX_EDIT_BYTES or b"\0" in raw:
            raise RepoStop("Generated file exceeds byte budget")
        try:
            ast.parse(content, filename=path)
        except SyntaxError as exc:
            raise RepoStop("Model-generated Python has invalid syntax") from exc
        changes[path] = raw
    return changes


def staged_snapshot(dest: Path, snap: dict[str, bytes]) -> None:
    if dest.exists() or dest.is_symlink():
        raise RepoStop("Staging directory must not exist")
    dest.mkdir(mode=0o700)
    for path, raw in snap.items():
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as stream:
            stream.write(raw)
        target.chmod(0o600)


# Selected test modules are imported by their precise owner-approved filenames.
# This closes the dangerous gap where an unrelated passing test might satisfy
# a total-tests>0 check while the requested acceptance tests were never run.
SELECTED_HARNESS = """
import importlib.util, os, resource, sys, unittest
resource.setrlimit(resource.RLIMIT_CPU, (12, 13))
resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
sys.path.insert(0, '/work')
suite = unittest.TestSuite()
for i, name in enumerate(__TEST_FILES__):
    spec = importlib.util.spec_from_file_location('mio_approved_test_' + str(i), '/work/' + name)
    if spec is None or spec.loader is None:
        print('MIO_SELECTED_TEST_IMPORT_FAILED', flush=True)
        sys.exit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    selected = unittest.defaultTestLoader.loadTestsFromModule(module)
    count = selected.countTestCases()
    print('MIO_SELECTED_FILE=' + str(i) + ':' + str(count), flush=True)
    if count < 1:
        sys.exit(1)
    suite.addTests(selected)
result = unittest.TextTestRunner(verbosity=1, stream=sys.stdout).run(suite)
print('MIO_VERIFIER_TESTS_RUN=' + str(result.testsRun), flush=True)
sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
""".strip()


def test_staged(root: Path, selected: tuple[str, ...], tests: dict[str, str]) -> dict:
    for p in selected:
        if sha((root / p).read_bytes()) != tests[p]:
            raise RepoStop("Trusted acceptance tests were altered")
    harness = SELECTED_HARNESS.replace("__TEST_FILES__", repr(selected))
    code, log, timed_out, overflow = _bounded_run(sandbox_argv(root, harness))
    match = re.findall(r"MIO_VERIFIER_TESTS_RUN=(\d+)", log)
    count = int(match[-1]) if match else 0
    counts = re.findall(r"MIO_SELECTED_FILE=(\d+):(\d+)", log)
    all_selected = len(counts) == len(selected) and all(
        int(idx) == i and int(n) >= 1 for i, (idx, n) in enumerate(counts)
    )
    for p in selected:
        if sha((root / p).read_bytes()) != tests[p]:
            raise RepoStop("Trusted acceptance test changed during execution")
    passed = code == 0 and all_selected and count >= len(selected) and not timed_out and not overflow
    return {"passed": passed, "tests_run": count, "selected_tests_run": all_selected,
            "return_code": code,
            "outcome": "timeout" if timed_out else "output_limit" if overflow else
            "passed" if passed else "failed", "log": log[:MAX_LOG],
            "isolation": "Bubblewrap read-only filesystem, no network or GPU"}


def diff(snapshot: dict[str, bytes], changes: dict[str, bytes]) -> str:
    sections = []
    for path, raw in sorted(changes.items()):
        old = snapshot[path].decode("utf-8").splitlines(keepends=True)
        new = raw.decode("utf-8").splitlines(keepends=True)
        sections.extend(difflib.unified_diff(old, new, fromfile="a/" + path, tofile="b/" + path))
    return "".join(sections)


def apply_verified(goal: RepoGoal, originals: dict[str, bytes], changed: dict[str, bytes],
                   private_run: Path) -> dict:
    """Explicit owner-authorized opt-in with backups and prewrite concurrency guard."""
    for path in goal.tests + tuple(changed):
        on_disk = goal.root / path
        if on_disk.is_symlink() or on_disk.resolve() != on_disk:
            raise RepoStop("A tracked source path changed into a symlink")
        if sha(on_disk.read_bytes()) != sha(originals[path]):
            raise RepoStop("Original repository changed during verification; refuse overwrite")
    backup = private_run / "original-source-backup"
    backup.mkdir(mode=0o700)
    for path in changed:
        target = backup / path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(originals[path])
        target.chmod(0o600)
    written = []
    try:
        for path, raw in changed.items():
            dest = goal.root / path
            old_mode = stat.S_IMODE(dest.stat().st_mode)
            fd, temp = tempfile.mkstemp(prefix=".mio-edit-", dir=dest.parent)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(raw)
                    f.flush()
                    os.fsync(f.fileno())
                os.chmod(temp, old_mode)
                os.replace(temp, dest)
                written.append(path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
    except OSError as exc:
        # Best effort rollback from independently saved bytes, preserving the backup.
        for path in written:
            (goal.root / path).write_bytes(originals[path])
        raise RepoStop("Apply failed; inspected source backup retained") from exc
    return {"applied": sorted(written), "private_backup": str(backup)}
