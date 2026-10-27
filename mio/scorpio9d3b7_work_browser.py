"""SCORPIO9D3B7: authenticated Work proposal -> single-use browser worker.

Proposals cannot execute. An authenticated owner decision issues a token for the
exact pre-staged public HTTPS URL. The worker atomically consumes its Work binding
before the existing B6 broker consumes the HTTPS grant and renders offline.
No LLM text, prompt, or ordinary Chat request can grant this capability.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, StrictBool

from mio.scorpio9d3b6_broker import ScopeDenied, _url, execute_granted, issue_one_use
from mio.work_core import WorkStop, _id, db, event, project_info, run_info, update
from mio.work_lifecycle import is_archived

MAX_GOAL = 6000


class BrowserProposalNew(BaseModel):
    prompt: str = Field(min_length=4, max_length=MAX_GOAL)
    url: str = Field(min_length=12, max_length=1500)


class BrowserDecisionNew(BaseModel):
    approve: StrictBool


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scorpio9d3b7_browser_proposals (
          run TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
          project TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          url TEXT NOT NULL,
          decision TEXT NOT NULL,
          token TEXT,
          consumed INTEGER NOT NULL DEFAULT 0,
          created INTEGER NOT NULL,
          decided INTEGER
        )
    """)


def broker_directory(root: Path) -> Path:
    # Work root's parent is already checked owner-private by work_core.db().
    return Path(root).parent / "scorpio9d3b7-browser-grants"


def propose(root: Path, *, project: str, goal: str, url: str) -> dict:
    """Stage a nonexecuting request. The URL must be explicit and immutable."""
    project = _id(project)
    if not isinstance(goal, str) or not 4 <= len(goal.strip()) <= MAX_GOAL:
        raise WorkStop("Browser task goal invalid")
    try:
        url = _url(url)
    except ScopeDenied as exc:
        raise WorkStop("Only an eligible public HTTPS URL may be proposed") from exc
    project_info(root, project)
    if is_archived(root, project):
        raise WorkStop("Archived projects cannot request browser access")
    now = int(time.time())
    run = uuid.uuid4().hex
    with db(root) as conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        busy = conn.execute("SELECT 1 FROM runs WHERE state IN ('queued','running') LIMIT 1").fetchone()
        if busy:
            raise WorkStop("One Work run at a time; wait for it to finish")
        conn.execute(
            "INSERT INTO runs(id,project,prompt,state,mode,created,updated,sources) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (run, project, goal.strip(), "needs_review", "browser_proposed", now, now, "[]"),
        )
        conn.execute(
            "INSERT INTO scorpio9d3b7_browser_proposals(run,project,url,decision,created) "
            "VALUES (?,?,?,?,?)", (run, project, url, "proposed", now),
        )
        conn.execute("INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                     (run, "browser.proposed", "Awaiting owner decision for exact public HTTPS URL", now))
    return proposal_info(root, run)


def proposal_info(root: Path, run: str) -> dict:
    run = _id(run)
    with db(root) as conn:
        _schema(conn)
        row = conn.execute(
            "SELECT b.run,b.project,b.url,b.decision,b.consumed,b.created,b.decided,"
            "r.prompt,r.state,r.mode FROM scorpio9d3b7_browser_proposals b "
            "JOIN runs r ON r.id=b.run AND r.project=b.project WHERE b.run=?", (run,),
        ).fetchone()
        if row is None:
            raise WorkStop("Browser proposal unavailable")
        return {key: row[key] for key in (
            "run", "project", "url", "decision", "consumed", "created", "decided", "prompt", "state", "mode"
        )}


def decide(root: Path, *, run: str, approve: bool) -> dict:
    """Trusted endpoint only: authorization must be verified before this call."""
    run = _id(run)
    if type(approve) is not bool:
        raise WorkStop("Owner decision must be explicit")
    pending = proposal_info(root, run)
    if (pending["decision"] != "proposed" or pending["mode"] != "browser_proposed"
            or pending["state"] != "needs_review"):
        raise WorkStop("This browser proposal was already decided")
    if is_archived(root, pending["project"]):
        raise WorkStop("Archived projects cannot authorize browser access")
    now = int(time.time())
    if not approve:
        with db(root) as conn:
            _schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                "UPDATE scorpio9d3b7_browser_proposals SET decision='rejected',decided=? "
                "WHERE run=? AND decision='proposed'", (now, run),
            ).rowcount
            if changed != 1:
                raise WorkStop("Browser proposal already decided")
            conn.execute(
                "UPDATE runs SET state='failed',mode='browser_denied',"
                "result='Owner rejected the proposed browser access.',updated=? "
                "WHERE id=? AND state='needs_review' AND mode='browser_proposed'", (now, run),
            )
            conn.execute("INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                         (run, "browser.rejected", "Owner rejected one URL; no grant issued", now))
        return proposal_info(root, run)
    with db(root) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM runs WHERE state IN ('queued','running') LIMIT 1").fetchone():
            raise WorkStop("Work queue busy; browser proposal remains unapproved")
    # B6 ledger is a separate private store. Issue before queueing. If the process
    # fails between ledgers, the unbound grant cannot be executed by the worker.
    try:
        token = issue_one_use(broker_directory(root), project=pending["project"],
                              run=run, url=pending["url"], owner_approved=True, ttl=180)
    except (ScopeDenied, OSError, sqlite3.Error) as exc:
        raise WorkStop("Could not issue a bounded browser grant") from exc
    with db(root) as conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM runs WHERE state IN ('queued','running') LIMIT 1").fetchone():
            raise WorkStop("Work became busy; issued grant left unusable")
        changed = conn.execute(
            "UPDATE scorpio9d3b7_browser_proposals SET decision='approved',token=?,decided=? "
            "WHERE run=? AND project=? AND url=? AND decision='proposed' AND consumed=0",
            (token, now, run, pending["project"], pending["url"]),
        ).rowcount
        if changed != 1:
            raise WorkStop("Browser proposal changed during approval")
        changed = conn.execute(
            "UPDATE runs SET state='queued',mode='browser_queued',result=NULL,updated=? "
            "WHERE id=? AND project=? AND state='needs_review' AND mode='browser_proposed'",
            (now, run, pending["project"]),
        ).rowcount
        if changed != 1:
            raise WorkStop("Browser Work run changed during approval")
        conn.execute("INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                     (run, "browser.approved", "Authenticated owner approved exact one-use HTTPS grant", now))
    return proposal_info(root, run)


def _claim_worker(root: Path, run: str) -> tuple[str, str, str]:
    """Atomically mark Work binding consumed and the matching run active."""
    with db(root) as conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT b.project,b.url,b.token,b.decision,b.consumed,r.state,r.mode "
            "FROM scorpio9d3b7_browser_proposals b JOIN runs r ON r.id=b.run "
            "AND r.project=b.project WHERE b.run=?", (run,),
        ).fetchone()
        if (row is None or row["state"] != "queued" or row["mode"] != "browser_queued"
                or row["decision"] != "approved" or row["consumed"] != 0
                or not isinstance(row["token"], str)):
            raise WorkStop("No exact unconsumed approved browser binding")
        changed = conn.execute(
            "UPDATE scorpio9d3b7_browser_proposals SET consumed=1,token=NULL "
            "WHERE run=? AND consumed=0 AND decision='approved'", (run,),
        ).rowcount
        if changed != 1:
            raise WorkStop("Browser Work binding already consumed")
        changed = conn.execute(
            "UPDATE runs SET state='running',mode='browser_running',updated=? "
            "WHERE id=? AND state='queued' AND mode='browser_queued'", (int(time.time()), run),
        ).rowcount
        if changed != 1:
            raise WorkStop("Browser Work run unavailable")
        conn.execute("INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                     (run, "browser.claimed", "Worker consumed exactly one approved URL binding", int(time.time())))
        return row["project"], row["url"], row["token"]


def maybe_execute_browser(root: Path, run: str, record: dict) -> dict | None:
    """Only browser_queued runs can execute. Others remain non-browser runs."""
    if record.get("mode") != "browser_queued":
        return None
    try:
        proposal = proposal_info(root, run)
        if is_archived(root, proposal["project"]):
            raise WorkStop("Browser project archived")
        project, url, token = _claim_worker(root, run)
        report = execute_granted(broker_directory(root), project=project, run=run,
                                 url=url, token=token)
        if (report.get("state") != "verified" or report.get("browser_network") != "disabled"
                or report.get("javascript_executed") is not True):
            raise WorkStop("Browser proof incomplete")
        evidence = (
            f"Verified one owner-approved public HTTPS document: {url}\n\n"
            f"Page SHA-256: {report['page_sha256']}\n"
            f"Offline browser result SHA-256: {report['rendered_sha256']}\n\n"
            "This is proof of retrieval and JavaScript rendering, not a verified "
            "answer about the document's factual contents. No browser network, "
            "downloads, installations, or host commands were granted."
        )
        event(root, run, "browser.verified", "One-use HTTPS evidence and offline rendering attested")
        update(root, run, "answered", mode="browser_verified", result=evidence,
               sources=[{"ref": "W1", "title": "Verified public HTTPS document", "url": url,
                         "page_verified": True, "page_sha256": report["page_sha256"]}])
    except (ScopeDenied, WorkStop, OSError, ValueError, RuntimeError, sqlite3.Error, KeyError):
        current = run_info(root, run)
        if current["state"] in {"queued", "running"}:
            event(root, run, "browser.denied", "Browser execution denied or failed; owner review required")
            update(root, run, "needs_review", mode="browser_denied",
                   error="Browser scope could not be verified. Owner must create a new proposal.")
    return run_info(root, run)


def register_browser_routes(app: FastAPI, require_token, root: Path) -> None:
    """Attach browser proposal/decision endpoints behind existing owner auth."""
    auth = [Depends(require_token)]

    @app.post("/api/work/projects/{project_id}/browser-proposals",
              dependencies=auth, status_code=201)
    def browser_proposal(project_id: str, payload: BrowserProposalNew):
        try:
            return propose(root, project=project_id, goal=payload.prompt, url=payload.url)
        except (WorkStop, OSError, ValueError) as exc:
            raise HTTPException(409, detail=str(exc)) from exc

    @app.get("/api/work/runs/{run_id}/browser-proposal", dependencies=auth)
    def read_browser_proposal(run_id: str):
        try:
            return proposal_info(root, run_id)
        except (WorkStop, OSError, ValueError) as exc:
            raise HTTPException(404, detail="Browser proposal unavailable") from exc

    @app.post("/api/work/runs/{run_id}/browser-decision", dependencies=auth)
    def browser_decision(run_id: str, payload: BrowserDecisionNew):
        try:
            return decide(root, run=run_id, approve=payload.approve)
        except (WorkStop, OSError, ValueError) as exc:
            raise HTTPException(409, detail=str(exc)) from exc
