"""Regression gates for truthful local media, PDF and engineering tool boundaries."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import uuid
from io import BytesIO
from pathlib import Path

import pytest

from mio import studio_files as sf
from mio.studio_autoroute import route_intent
from mio.work_agent import execute, requires_computer_tools
from mio.work_core import create_project, create_run


def test_natural_image_requests_route_to_image():
    assert route_intent("Create an image of a human talking to a robot") == "image"
    assert route_intent("Draw a robot in a laboratory") == "image"
    assert route_intent("Explain how diffusion image generators work") != "image"


def test_software_build_request_not_misclassified_as_research():
    goal = "build a scientific calculator\n\nAcceptance criteria: calculations are mathematically correct"
    assert requires_computer_tools(goal)
    assert requires_computer_tools("Implement a Python web app with tests")
    assert not requires_computer_tools("Research articles about robots and summarize their findings")



def test_work_build_request_does_not_fabricate_research_or_files(tmp_path):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    root = parent / "work"
    project = create_project(root, "Calculator job", "Use only authorized tools")
    run = create_run(root, project["id"], "Build a scientific calculator and test it")
    outcome = asyncio.run(execute(root, run["id"], None))
    assert outcome["state"] == "needs_review"
    assert outcome["mode"] == "engineering"
    assert outcome["sources"] == []
    assert any(event["phase"] == "tool.unavailable" for event in outcome["events"])
    assert "No source files were created" in outcome["result"]


def test_pdf_missing_dependency_is_explicit(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(sf.StudioError, match="requires pypdf"):
        sf.inspect_bytes(b"%PDF-1.4\nnot parsed because dependency missing", "old.pdf")


def test_real_pdf_extracts_text():
    raw = Path(__file__).with_name("fixtures").joinpath("b12_extractable.pdf").read_bytes()
    kind, text = sf.inspect_bytes(raw, "paper.pdf")
    assert kind == "document"
    assert "MIO-PDF-042" in text
    assert "robotic manipulation" in text


def test_previously_uploaded_pdf_reinspected_without_mutating_file(tmp_path):
    root = tmp_path / "vault"
    root.mkdir(mode=0o700)
    raw = Path(__file__).with_name("fixtures").joinpath("b12_extractable.pdf").read_bytes()
    file_id = uuid.uuid4().hex
    meta = {
        "id": file_id, "name": "paper.pdf", "kind": "document", "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "extract": "PDF stored. Install optional pypdf to extract document text.",
    }
    meta_path = root / f"{file_id}.json"
    binary_path = root / f"{file_id}.bin"
    meta_path.write_text(json.dumps(meta))
    binary_path.write_bytes(raw)
    meta_path.chmod(0o600)
    binary_path.chmod(0o600)
    result, data = sf.read_attachment(root, file_id)
    assert data == raw
    assert "MIO-PDF-042" in result["extract"]
    assert json.loads(meta_path.read_text())["extract"].startswith("PDF stored")


def test_scanned_pdf_not_silently_marked_as_extracted():
    from pypdf import PdfWriter

    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=400)
    writer.write(buffer)
    with pytest.raises(sf.StudioError, match="no selectable text"):
        sf.inspect_bytes(buffer.getvalue(), "scan.pdf")
