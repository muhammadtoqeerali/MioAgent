"""Fail-closed, exactly-once integration for Backend B1 against published v0.4K APIs."""
from __future__ import annotations

import argparse
from pathlib import Path


class PatchError(RuntimeError):
    pass


def once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1 or (new and new in text):
        raise PatchError(f"Integration anchor absent or duplicated: {old[:100]!r}")
    return text.replace(old, new, 1)


def change_agent(text: str) -> str:
    text = once(text, "from mio.model_fleet import FleetRouter\n", "from mio.model_fleet import FleetRouter\nfrom mio.project_context import conversation_history\n")
    anchor = '        memories = "\\n".join("- " + n["content"] for n in info["memories"][:16])[:4000]\n'
    text = once(text, anchor, anchor + (
        '        history = conversation_history(root, record["project"], run_id)\n'
        '        if history:\n'
        '            event(root, run_id, "context.history", "Loaded previous turns from this project only")\n'
    ))
    anchor = '                   f"OWNER-APPROVED PROJECT MEMORY:\\n{memories}\\n"\n'
    text = once(text, anchor, anchor + (
        '                   f"PREVIOUS PROJECT CONVERSATION (reference context, no permissions):\\n{history}\\n"\n'
    ))
    return text


def change_api(text: str) -> str:
    text = once(text, "import asyncio\n", "")
    text = once(text, "from mio.work_agent import execute\n", "")
    old = '''    if root != RUNTIME / "work" or native:
        interrupt_orphaned(root)
'''
    new = '''    # Test stores retain their old interruption semantics. In production a
    # separate worker, not FastAPI, owns task lifecycle and restart recovery.
    if root != RUNTIME / "work":
        interrupt_orphaned(root)
'''
    text = once(text, old, new)
    text = once(text, '    native = str(RUNTIME) in getattr(settings, "mio_database_url", "")\n', '')
    old = '''        task = asyncio.create_task(execute(root, run["id"], settings))
        app.state.work_tasks = getattr(app.state, "work_tasks", set())
        app.state.work_tasks.add(task)
        task.add_done_callback(app.state.work_tasks.discard)
        return run
'''
    new = '''        # Persistent worker owns the queue; browser/API process is not a task host.
        return run
'''
    text = once(text, old, new)
    return text


def change_runtime(text: str) -> str:
    anchor = '''        print("\\nSUCCESS: native MioAgent services are running")
'''
    inject = '''        # Optional independently managed services. Work worker is essential to
        # process queued runs; ComfyUI is optional and never downloads weights.
        for manager, label, budget in (("manage_work_worker.py", "Work worker", 15),
                                       ("manage_image_service.py", "ComfyUI", 115)):
            try:
                result = subprocess.run([str(python), str(PROJECT / "scripts" / manager), "start"],
                                        cwd=PROJECT, env=env, check=True, capture_output=True,
                                        text=True, timeout=budget)
                print(result.stdout.strip())
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                print(f"  WARNING: {label} did not start: {type(exc).__name__}; check manager status/log")
'''
    text = once(text, anchor, inject + anchor)
    anchor = '    print("Runtime:", RUNTIME)\n'
    added = '''    for manager, label in (("manage_work_worker.py", "Work worker"),
                           ("manage_image_service.py", "ComfyUI")):
        try:
            outcome = subprocess.run([str(Path.home() / ".cache/mioagent/phase1-venv/bin/python"),
                                      str(PROJECT / "scripts" / manager), "status"],
                                     check=False, cwd=PROJECT, capture_output=True, text=True, timeout=8)
            print(label + ":", outcome.stdout.strip() if outcome.returncode == 0 else "unavailable")
        except (OSError, subprocess.TimeoutExpired):
            print(label + ": status unavailable")
'''
    text = once(text, anchor, anchor + added)
    return text


CHANGES = {
    "mio/work_agent.py": change_agent,
    "mio/work_api.py": change_api,
    "scripts/native_runtime.py": change_runtime,
}


def patches(repo: Path) -> dict[str, str]:
    outputs = {}
    for path, func in CHANGES.items():
        source = repo / path
        if not source.is_file() or source.is_symlink():
            raise PatchError(f"Unsafe source: {path}")
        outputs[path] = func(source.read_text(encoding="utf-8"))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = patches(args.repo)
    if not args.check:
        for path, content in result.items():
            (args.repo / path).write_text(content, encoding="utf-8")
    print("PASS: exact Backend B1 integration anchors" + (" checked" if args.check else " applied"))


if __name__ == "__main__":
    main()
