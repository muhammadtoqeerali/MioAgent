"""Real HTTP integration against a tiny local OpenAI-compatible stub server.

It verifies the router, planner, worker, database and API wiring without
claiming real LLM weights have been loaded on the test host.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

from mio.api import create_app
from mio.config import Settings


class StubModel(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/v1/models":
            body = b'{"data":[{"id":"stub"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        is_plan = "task planner" in request["messages"][0]["content"]
        answer = '{"steps":["Read question","Answer carefully"]}' if is_plan else "Local stub answer"
        payload = json.dumps({"choices": [{"message": {"content": answer}}],
                              "usage": {"prompt_tokens": 6, "completion_tokens": 4}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def test_gateway_http_and_persistent_supervisor(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubModel)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(
            mio_api_token="m" * 48,
            mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'messages.db'}",
            mio_local_base_url=f"http://127.0.0.1:{server.server_port}/v1",
            mio_local_model="stub",
            mio_poll_seconds=0.1,
        )
        headers = {"Authorization": "Bearer " + settings.mio_api_token}
        with TestClient(create_app(settings)) as client:
            info = client.get("/api/assistant/status", headers=headers).json()
            assert info["local_reachable"] is True
            submission = client.post("/api/assistant/ask", headers=headers,
                                     json={"prompt": "Write a short answer"})
            assert submission.status_code == 202
            job_id = submission.json()["task_id"]
            end = time.monotonic() + 8
            while time.monotonic() < end:
                job = client.get(f"/api/tasks/{job_id}", headers=headers).json()
                if job["status"] == "completed":
                    break
                time.sleep(0.1)
            assert job["status"] == "completed", job
            assert job["result"]["answer"] == "Local stub answer"
            assert job["result"]["input_tokens"] == 12
            assert job["result"]["output_tokens"] == 8
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
