"""Live no-sudo Phase 2 integration smoke test (uses a real configured local model).

Run: python3 scripts/phase2_smoke.py
This creates one harmless conversation and makes two inference calls. It does not
execute system tools or connect to cloud providers.
"""

from __future__ import annotations

import time

from native_runtime import API_URL, get_token, load_json


def main():
    token = get_token()
    status = load_json(f"{API_URL}/api/assistant/status", token)
    print("Model configuration:", status)
    if not status.get("local_reachable"):
        raise SystemExit("Local model service is not reachable. Start Ollama first.")
    if status.get("cloud_enabled"):
        raise SystemExit("Smoke test requires local-only configuration to avoid paid calls.")
    job = load_json(f"{API_URL}/api/assistant/ask", token, {
        "prompt": "In two sentences, explain why a task queue is useful in an AI assistant."
    })
    task_id = job["task_id"]
    print("Model request queued:", task_id)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        task = load_json(f"{API_URL}/api/tasks/{task_id}", token)
        if task["status"] == "completed":
            result = task["result"]
            if not result.get("answer") or not result.get("plan"):
                raise SystemExit("AI response lacked an answer or plan")
            print("MODEL:", result.get("model"))
            print("PROVIDER:", result.get("provider"))
            print("PLAN:", result.get("plan"))
            print("ANSWER:", result["answer"][:1000])
            print("PASS: real model inference, persisted result, AI supervisor")
            return
        if task["status"] in ("canceled", "failed"):
            raise SystemExit(f"AI task {task['status']}: {task.get('error')}")
        time.sleep(2)
    raise SystemExit("Timed out waiting for local model. Check logs and GPU utilization.")


if __name__ == "__main__":
    main()
