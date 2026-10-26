"""A job's document is served once its import is over, and whole.

The import put the parsed document in the store before the pipeline ran
over it. The editor reads /result, and while that answers an error it
polls the job's progress and loads the result when the job completes; a
200 it takes for the finished document. So a book opened during its import
showed the adapter's blocks - every one an UnknownBlock - as the result,
and kept showing them. The serializer had no branch for UnknownBlock
either: "UnknownBlock", no text, confidence NaN%; and saved so, the text
was gone. The adapter's output is saved before the pipeline runs, and a
server restarted mid-import brought it back as a completed job.
"""

import json
import threading
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from src.analyzers.pipeline import PipelineRunner  # noqa: E402
from src.api.app import create_app  # noqa: E402

FIXTURE = "tests/fixtures/z80_decimal_binary_table.pdf"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    ssd = tmp_path / "ssd"
    ssd.mkdir()
    monkeypatch.setenv("KAE_SSD_PATH", str(ssd))
    monkeypatch.setenv("KAE_DATA_DIR", str(tmp_path / "kae"))
    return tmp_path


def _progress(client, job_id):
    return client.get(f"/api/v1/jobs/{job_id}/progress").json()


def _wait(client, job_id, until, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = _progress(client, job_id)
        if until(p):
            return p
        time.sleep(0.05)
    pytest.fail(f"job never reached the state: {_progress(client, job_id)}")


def _nodes(tree):
    for node in tree:
        yield node
        yield from _nodes(node.get("children") or [])


def test_the_document_waits_for_its_import(env, monkeypatch):
    gate, entered = threading.Event(), threading.Event()
    execute = PipelineRunner.execute

    def held(self, *args, **kwargs):
        entered.set()
        assert gate.wait(30), "the test never let the pipeline run"
        return execute(self, *args, **kwargs)

    monkeypatch.setattr(PipelineRunner, "execute", held)
    with TestClient(create_app()) as client:
        with open(FIXTURE, "rb") as fh:
            job_id = client.post("/api/v1/documents/upload",
                                 files={"file": ("table.pdf", fh, "application/pdf")}).json()["job_id"]
        try:
            assert entered.wait(30), "the pipeline never started"
            # The parsed document is in the store; the analyzers have not run.
            assert _progress(client, job_id)["status"] == "RUNNING"
            assert client.get(f"/api/v1/jobs/{job_id}/result").status_code == 409
            assert client.post(f"/api/v1/jobs/{job_id}/assemble",
                               json={"target_lang": "Russian"}).status_code == 409
        finally:
            gate.set()
        _wait(client, job_id, lambda p: p["status"] == "COMPLETED")
        result = client.get(f"/api/v1/jobs/{job_id}/result")
        assert result.status_code == 200
        types = {n["type"] for n in _nodes(result.json()["containers"])}
        assert "UnknownBlock" not in types


def test_an_unclaimed_block_keeps_its_text(env):
    """An UnknownBlock read back from disk is served with its text and
    confidence, not as a bare type."""
    docs = env / "kae" / "docs"
    docs.mkdir(parents=True)
    block = {"id": "u-1", "type": "UnknownBlock", "text": "Switching waveforms of the regulator",
             "page_index": 6, "bbox": [0.1, 0.2, 0.9, 0.25], "confidence_score": 0.7}
    (docs / "job-u.json").write_text(json.dumps({
        "title": "book", "_source_uri": "upload://book.pdf", "_source_type": "pdf",
        "containers": [{"id": "root", "type": "ContainerUnit", "title": "book", "level": 1,
                        "children": [block]}],
    }))
    with TestClient(create_app()) as client:
        [node] = client.get("/api/v1/jobs/job-u/result").json()["containers"][0]["children"]
    assert node["type"] == "UnknownBlock"
    assert node["text"] == "Switching waveforms of the regulator"
    assert node["confidence_score"] == 0.7


def test_an_import_cut_short_by_a_restart_is_not_completed(env):
    docs = env / "kae" / "docs"
    docs.mkdir(parents=True)
    (docs / "job-cut.json").write_text(json.dumps({
        "title": "book", "_source_uri": "upload://book.pdf", "_source_type": "pdf",
        "_analyzed": False,
        "containers": [{"id": "root", "type": "ContainerUnit", "title": "book", "level": 1,
                        "children": [{"id": "u-1", "type": "UnknownBlock", "text": "raw"}]}],
    }))
    with TestClient(create_app()) as client:
        progress = _progress(client, "job-cut")
        assert progress["status"] == "FAILED"
        assert "прервана" in progress["error"]
        assert client.get("/api/v1/jobs/job-cut/result").status_code == 409
        listed = {d["job_id"]: d["status"] for d in client.get("/api/v1/documents").json()}
        assert listed["job-cut"] == "FAILED"
        assert client.delete("/api/v1/jobs/job-cut").status_code == 200
