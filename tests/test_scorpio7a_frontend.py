"""SCORPIO7A source-level contracts; JavaScript behavior typechecked in dashboard."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOM = ROOT / "apps/dashboard/app/_mio/scorpio-control-room.tsx"
PANEL = ROOT / "apps/dashboard/app/_mio/scorpio-approval-panel.tsx"
CSS = ROOT / "apps/dashboard/app/_mio/scorpio.module.css"
SVG = ROOT / "apps/dashboard/public/scorpio-mark.svg"


def read(path):
    return path.read_text(encoding="utf-8")


def test_room_is_client():
    assert read(ROOM).startswith('"use client";')


def test_brand_is_spelled_correctly():
    assert "Scorpio Control Room" in read(ROOM)
    assert "Scorpo" not in read(ROOM)


def test_project_scoped_real_data():
    text = read(ROOM)
    assert 'mioApi<Overview>("work/overview")' in text
    assert '`work/projects/${projectId}`' in text
    assert '`work/runs/${runId}`' in text


def test_panel_uses_authenticated_proxy_only():
    text = read(PANEL)
    assert 'mioApi<{ id: string; mode: string }>' in text
    assert '`work/projects/${projectId}/runs`' in text
    assert "fetch(" not in text


def test_review_checkbox_is_required():
    text = read(PANEL)
    assert 'approved && feedback.trim().length >= 10' in text
    assert 'onClick={() => void submit()}' in text


def test_review_does_not_forge_permissions():
    text = read(PANEL)
    assert "host_shell" not in text
    assert "permissions:" not in text
    assert "task_type: choice, approved: true" in text


def test_review_does_not_silently_resume():
    text = read(PANEL)
    assert "NEW follow-up" in text
    assert "not an automatic resume" in text
    assert "/resume" not in text


def test_allowlist_restricted():
    text = read(PANEL)
    assert "paths.length > 8" in text
    assert "SAFE_PATH.test(path)" in text
    assert '".mioagent-private"' in text


def test_next_task_not_triggered_by_effect():
    text = read(PANEL)
    assert "void submit()" in text
    assert "useEffect" not in text


def test_failure_and_review_not_success():
    text = read(ROOM)
    assert '"needs_review", "failed", "interrupted"' in text
    assert 't.state === "answered"' in text


def test_active_tasks_not_review_approved():
    text = read(PANEL)
    assert 'const active = run.state === "queued" || run.state === "running"' in text
    assert "!active && approved" in text


def test_event_evidence_visible():
    text = read(ROOM)
    assert "run.events.map" in text
    assert "run.error" in text
    assert "run.result" in text


def test_brand_is_local_svg():
    text = read(SVG)
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in text
    assert "<script" not in text and "http://" not in text.replace('http://www.w3.org/2000/svg', '')


def test_dashboard_responsive():
    text = read(CSS)
    assert "max-width:740px" in text
    assert "prefers-reduced-motion" in text


def test_security_disclaimer():
    text = read(ROOM)
    assert "not a set of permission switches" in text
    assert "No silent or simulated resume" in text


def test_no_source_write_endpoints():
    text = read(ROOM) + read(PANEL)
    for marker in ('method: "DELETE"', '"PATCH"', '"PUT"', '/api/admin', 'start_service(', 'git push'):
        assert marker not in text
