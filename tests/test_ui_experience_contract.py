"""Offline source contracts for UX2, no workstation/runtime mutation."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("MIO_UX2_RELEASE_ROOT", Path(__file__).resolve().parents[1]))
APP = ROOT / "apps" / "dashboard" / "app"

def load(name: str) -> str:
    return (APP / name).read_text(encoding="utf-8")

def test_simplified_navigation_and_default_route():
    shell = load("_mio/ui-shell.tsx")
    assert all(p in shell for p in ('/chat', '/projects-space', '/work-mode', '/control-room'))
    assert all(f'href="{old}"' not in shell for old in ('/studio','/assistant','/work','/intelligence','/projects'))
    assert 'redirect("/control-room")' in load("page.tsx")
    assert 'redirect("/chat")' in load("workspace/page.tsx")

def test_chat_uses_persistent_conversations_and_real_image_api():
    code = load("chat/page.tsx")
    for required in ('assistant/conversations', 'assistant/ask', 'tasks/${pending}', '/api/studio', 'studio/images/', 'New chat'):
        assert required in code
    assert "setTimeout(() => set" not in code

def test_projects_use_real_file_memory_and_run_endpoints():
    code = load("projects-space/page.tsx")
    for required in ('work/projects', 'studio/attachments', '/files', '/memory', '/runs', 'approved:true'):
        assert required in code
    assert 'independent server-side thread isolation is not yet implemented' in code

def test_work_has_enforced_ability_boundary_and_real_run_events():
    code = load("work-mode/page.tsx")
    for required in ('kind==="supported"', 'kind==="computer"', 'setAck', 'work/projects', 'work/runs/', 'run.events'):
        assert required in code
    assert 'independent Ubuntu Work worker' in code
    assert 'during API restarts' in code
    assert 'Task is active in the API process' not in code
    assert 'unrestricted terminal' not in code.lower()

def test_control_room_uses_recorded_events_and_links_back():
    code = load("control-room/page.tsx")
    if code.strip() == 'export { default } from "../_mio/scorpio-control-room";':
        # Scorpio7A extracts the real implementation into a client component.
        # Preserve the evidence-backed contract across that refactor.
        implementation = load("_mio/scorpio-control-room.tsx")
        actions = load("_mio/scorpio-approval-panel.tsx")
        for required in (
            'mioApi<WorkRun>', 'work/runs/${runId}', 'run.events.map',
            'statusKind(run)', 'needs_review', 'ScorpioApprovalPanel',
            '/work-mode',
        ):
            assert required in implementation
        for required in ('task_type', 'approved: true', 'onSubmitted'):
            assert required in actions
    else:
        assert 'phaseSeen(' in code
        assert 'model.review_unavailable' in code
        assert '/work-mode' in code


def test_markdown_fenced_code_tracks_state_in_normal_loop():
    source = load("_mio/rich-text.tsx")
    assert "for (const [i, line] of lines.entries())" in source
    assert "lines.forEach(" not in source
    assert 'if(code) blocks.push(<pre key="unfinished-code"' in source
