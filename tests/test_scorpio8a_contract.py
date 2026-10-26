"""Offline source contracts for unified Scorpio UI, not live-API tests."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/dashboard/app"

def read(path: str) -> str:
    return (APP / path).read_text(encoding="utf-8")

def test_persistent_layout_frame():
    code = read("layout.tsx")
    assert "ScorpioShell" in code and "<ScorpioShell>" in code

def test_shell_all_navigation_routes():
    code = read("_mio/scorpio8a-shell.tsx")
    for route in ("/chat", "/projects-space", "/work-mode", "/control-room",
                  "/approvals", "/tools-permissions", "/system-health", "/activity", "/settings"):
        assert route in code
    assert 'usePathname' in code and 'Link href=' in code

def test_shell_grounded_status():
    code = read("_mio/scorpio8a-shell.tsx")
    assert 'mioApi<{projects:WorkProject[]}>("work/overview")' in code
    assert 'Promise.allSettled' in code
    assert 'Work API unavailable' in code
    assert 'setInterval' in code

def test_brand_and_readable_layout():
    code = read("_mio/scorpio8a-shell.tsx")
    assert 'scorpio-mark.svg' in code and 'Scorpio' in code
    assert 'AI AGENT PLATFORM' in code
    css = read("_mio/scorpio8a.css")
    assert '@media(max-width:720px)' in css
    assert 'prefers-reduced-motion' in css

def test_chat_features_unmodified():
    code = read("chat/page.tsx")
    for marker in ("assistant/ask", "assistant/conversations", "omni/conversations", "studio/attachments", "sendImage", "imageIntent"):
        assert marker in code

def test_project_reuses_real_work_api():
    code = read("projects-space/page.tsx")
    for marker in ("work/overview", "work/projects", "studio/attachments", "approved:true", "OmniImageThread"):
        assert marker in code

def test_project_thread_creation_and_filter():
    code = read("projects-space/page.tsx")
    for marker in ("threadPrompt(", "inspectThread(", "ScorpioThreads", "crypto.randomUUID("):
        assert marker in code

def test_thread_contract_not_local_storage():
    code = read("_mio/scorpio8a-threads.tsx")
    assert "SCORPIO_THREAD_V1:" in code
    assert "[[SCORPIO_USER_MESSAGE]]" in code
    assert "history.slice(-3)" in code
    assert "localStorage" not in code

def test_work_assignment_capabilities_preserved():
    code = read("work-mode/page.tsx")
    for marker in ('engineeringGoal', 'unsupportedGoal', 'proposedType',
                   'Approve & start', 'Reject — do nothing', 'work/projects',
                   'work/runs/', 'run.events'):
        assert marker in code

def test_approval_uses_real_work_api_and_backend_controls():
    code = read("_mio/scorpio8a-panels.tsx")
    assert 'mioApi<WorkRun>(`work/runs/${selected}`)' in code
    assert 'ScorpioApprovalPanel' in code
    assert 'new bounded follow-up' in code
    assert 'setInterval' in code

def test_permission_page_read_only():
    code = read("_mio/scorpio8a-panels.tsx")
    assert "Backend capabilities" in code
    assert "does not display nonfunctional grant toggles" in code
    for forbidden in ('/api/admin', 'service/restart', 'grant-permission'):
        assert forbidden not in code

def test_no_fake_health_stats():
    code = read("_mio/scorpio8a-panels.tsx")
    assert 'assistant/status' in code and 'work/overview' in code
    assert 'No synthetic CPU, GPU or memory readings' in code

def test_logs_real_events():
    code = read("_mio/scorpio8a-panels.tsx")
    assert 'run.events.map(' in code

def test_contextual_chat_sidebar_and_primary_shell():
    code = read("_mio/ui-shell.tsx")
    assert 'sidebarContent' in code
    assert 'ScorpioShell' in code

def test_review_requires_active_owner():
    code = read("_mio/scorpio-approval-panel.tsx")
    assert 'onClick={() => void approve()}' in code
    assert 'onClick={() => setRejected(true)}' in code
    assert 'if (active) return' in code
    assert 'task_type: "engineering", approved: true' in code

def test_audit_and_no_host_actions():
    code = read("_mio/scorpio8a-panels.tsx")
    assert 'events' in code and 'mioApi' in code
    for forbidden in ('git push', 'stop_service(', 'MIO_API_TOKEN', 'os.kill('):
        assert forbidden not in code

def test_new_routes_registered():
    for route in ('approvals','tools-permissions','system-health','activity','settings'):
        assert (APP / route / 'page.tsx').is_file()

def test_dashboard_legacy_original_contract_survives():
    code = read("control-room/page.tsx")
    assert 'scorpio-control-room' in code

def test_documentation_disclaims_thread_isolation():
    text = (ROOT / "docs/SCORPIO8A_UNIFIED_DASHBOARD.md").read_text(encoding="utf-8")
    assert 'not a server-side thread namespace' in text
    assert 'separate' in text and 'approval' in text


def test_home_opens_scorpio_control_room():
    assert 'redirect("/control-room")' in read("page.tsx")
