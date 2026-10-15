import time

from fastapi.testclient import TestClient

from mio.api import create_app
from mio.config import Settings


def test_api_auth_and_worker(tmp_path):
    settings = Settings(
        mio_api_token="t" * 48,
        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        mio_workspace_root=tmp_path,
        mio_poll_seconds=0.1,
        mio_demo_step_seconds=0.01,
    )
    app = create_app(settings)
    headers = {"Authorization": "Bearer " + settings.mio_api_token}
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/status").status_code == 401
        assert client.get("/api/status", headers=headers).status_code == 200
        response = client.post("/api/tasks", headers=headers, json={"kind": "echo", "prompt": "hello"})
        assert response.status_code == 201, response.text
        task_id = response.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = client.get(f"/api/tasks/{task_id}", headers=headers).json()
            if task["status"] == "completed":
                break
            time.sleep(0.05)
        assert task["status"] == "completed"
        assert task["result"]["text"] == "hello"
        assert len(client.get("/api/tasks", headers=headers).json()["tasks"]) == 1
        assert client.post("/api/tasks", headers=headers, json={"kind": "shell"}).status_code == 422
