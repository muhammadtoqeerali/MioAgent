"""SCORPIO9D3B8 UI-source contract; TypeScript is checked by project tsc."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "apps/dashboard/app/_mio/scorpio-browser-evidence.tsx"
WORK = ROOT / "apps/dashboard/app/work-mode/page.tsx"
APPROVAL = ROOT / "apps/dashboard/app/_mio/scorpio-approval-panel.tsx"


def test_panel_stays_client_only():
    text = PANEL.read_text()
    assert text.startswith('"use client";')
    assert "mioApi" in text and "postJson" in text
    assert "localStorage" not in text and "sessionStorage" not in text


def test_propose_not_grant():
    text = PANEL.read_text()
    assert "work/projects/${projectId}/browser-proposals" in text
    assert 'created.decision !== "proposed"' in text
    assert "Approve or Reject" in text


def test_decision_explicit():
    text = PANEL.read_text()
    assert "async function decide(approve: boolean)" in text
    assert "onClick={() => void decide(true)}" in text
    assert "onClick={() => void decide(false)}" in text
    assert "postJson({ approve })" in text
    assert "useEffect(() =>" in text
    assert "decide(true)" not in text.split("useEffect(() =>", 1)[1].split("}, [", 1)[0]


def test_render_server_proposal_not_text_authority():
    text = PANEL.read_text()
    assert "work/runs/${run.id}/browser-proposal" in text
    assert "created.project !== projectId" in text
    assert "changed.project !== projectId" in text
    assert "proposal.url" in text
    assert "dangerouslySetInnerHTML" not in text


def test_no_host_operations_or_direct_network_fetch():
    text = PANEL.read_text()
    assert "window.open" not in text
    assert "fetch(" not in text
    assert "exec(" not in text
    assert "child_process" not in text


def test_work_page_includes_panel_once():
    text = WORK.read_text()
    assert text.count('import ScorpioBrowserEvidence from "../_mio/scorpio-browser-evidence";') == 1
    assert text.count("<ScorpioBrowserEvidence key={selected} projectId={selected} run={run}/>") == 1


def test_original_retry_panel_does_not_compete_with_browser_grant():
    text = APPROVAL.read_text()
    assert 'if (run.mode.startsWith("browser_")) return null;' in text
