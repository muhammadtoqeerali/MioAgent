"""B9R2: general web-evidence fallback across Chat and Work research."""

import asyncio

from mio.web_evidence import EvidenceError, enrich_sources


def results(n=6):
    return [
        {"ref": f"W{i}", "url": f"https://example.org/page{i}",
         "title": f"Research result {i}", "snippet": "Topic evidence"}
        for i in range(1, n + 1)
    ]


def test_skips_three_inaccessible_pages_then_retrieves_later_page():
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith(("page1", "page2", "page3")):
            raise EvidenceError("Blocked, large, or unusable page")
        return {"page_verified": True, "page_excerpt": "Verified public text " * 4}

    entries = results()
    output = asyncio.run(enrich_sources(entries, fetch))
    assert len(calls) == 6
    assert [v["ref"] for v in output if v["page_verified"]] == ["W4", "W5", "W6"]
    assert all(not item["page_verified"] for item in output[:3])
    assert all("snippet only" in item["evidence_scope"] for item in output[:3])
    assert all("page_verified" not in row for row in entries)


def test_three_successes_stop_additional_network_requests():
    calls = []

    def fetch(url):
        calls.append(url)
        return {"page_verified": True, "page_excerpt": "Verified public text " * 4}

    output = asyncio.run(enrich_sources(results(), fetch))
    assert len(calls) == 3
    assert len([row for row in output if row["page_verified"]]) == 3
    assert all(row["page_verified"] is False for row in output[3:])


def test_batch_never_expands_past_six_sources():
    calls = []

    def failing_fetch(url):
        calls.append(url)
        raise EvidenceError("Not available")

    output = asyncio.run(enrich_sources(results(8), failing_fetch))
    assert len(calls) == 6
    assert len(output) == 6
    assert not any(row["page_verified"] for row in output)


def test_untrusted_search_metadata_cannot_forge_page_verification():
    source = results(1)
    source[0]["page_verified"] = True
    source[0]["page_excerpt"] = "FAKE search-index declaration"

    def failing_fetch(_url):
        raise EvidenceError("Not available")

    output = asyncio.run(enrich_sources(source, failing_fetch))
    assert output[0]["page_verified"] is False
    assert "snippet only" in output[0]["evidence_scope"]


def test_transport_failure_does_not_discard_later_sources():
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith("page1"):
            raise OSError("Network unavailable")
        return {"page_verified": True, "page_excerpt": "Verified public text " * 4}

    output = asyncio.run(enrich_sources(results(6), fetch))
    assert len(calls) == 4
    assert [row["ref"] for row in output if row["page_verified"]] == ["W2", "W3", "W4"]
