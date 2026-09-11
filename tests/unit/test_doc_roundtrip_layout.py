"""A document read back from disk keeps its page layout (RFC 0021 §5.4).

Documents leave the in-memory store (restart, LRU eviction) and are rebuilt
from their persisted JSON. A paragraph used to come back as one line holding
all its text, its per-line boxes dropped — and the editor, which lays a
scanned page's lines over the scan, drew every paragraph of every restored
job as one wrapped block beside the lines it should have covered
("Programming the Z80", page 17). Page sizes were not persisted at all.

This goes through the real path: a persisted file, the API's own DocStore
and rebuild, the endpoints the editor calls.
"""
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


LINES = [
    {"text": "X is true, then take action A, else B. Instead of presenting a formal",
     "bbox": [0.157, 0.072, 0.924, 0.092],
     "style": {"font_family": "serif", "font_size_pt": 11.1, "is_bold": False,
               "is_italic": False, "is_monospace": False, "text_color_rgb": [0, 0, 0]}},
    {"text": "definition of flowcharts at this point, we will introduce and discuss",
     "bbox": [0.157, 0.093, 0.924, 0.113]},
    {"text": "flowcharts later on in the book when we present programs.",
     "bbox": [0.157, 0.114, 0.790, 0.134]},
]


def _persisted(job_id: str) -> dict:
    para = {
        "id": "p-1", "type": "ParagraphBlock", "text": " ".join(l["text"] for l in LINES),
        "page_index": 15, "bbox": [0.157, 0.072, 0.924, 0.134], "lines": LINES,
        "style": LINES[0]["style"], "confidence_score": 0.9,
    }
    title = {
        "id": "t-1", "type": "TitlePageBlock", "page_role": "title", "text": "PROGRAMMING THE Z80",
        "page_index": 0, "bbox": [0.2, 0.1, 0.8, 0.3],
        "lines": [{"text": "PROGRAMMING", "bbox": [0.3, 0.1, 0.7, 0.18]},
                  {"text": "THE Z80", "bbox": [0.35, 0.2, 0.65, 0.3]}],
        "confidence_score": 0.9,
    }
    return {
        "title": "zaks", "_source_uri": f"upload://{job_id}.pdf", "_source_type": "pdf",
        "page_count": 16, "page_sizes_pt": [[403.0, 612.0]] * 16,
        "containers": [{"id": "root", "type": "ContainerUnit", "title": "zaks", "level": 1,
                        "children": [title, para]}],
    }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KAE_DATA_DIR", str(tmp_path))
    from src.api.app import create_app
    job_id = "roundtrip-job"
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / f"{job_id}.json").write_text(json.dumps(_persisted(job_id)))
    return TestClient(create_app()), job_id


def _find(node, node_id):
    if node.get("id") == node_id:
        return node
    for c in node.get("children") or []:
        hit = _find(c, node_id)
        if hit:
            return hit
    return None


def test_a_paragraph_keeps_its_lines_through_the_disk(client):
    tc, job_id = client
    res = tc.get(f"/api/v1/jobs/{job_id}/result")
    assert res.status_code == 200
    para = _find(res.json()["containers"][0], "p-1")
    assert [l["text"] for l in para["lines"]] == [l["text"] for l in LINES]
    for got, want in zip(para["lines"], LINES):
        assert got["bbox"] == pytest.approx(want["bbox"])


def test_a_title_page_keeps_its_lines_through_the_disk(client):
    tc, job_id = client
    title = _find(tc.get(f"/api/v1/jobs/{job_id}/result").json()["containers"][0], "t-1")
    assert [l["text"] for l in title["lines"]] == ["PROGRAMMING", "THE Z80"]


def test_page_sizes_survive_the_disk(client):
    tc, job_id = client
    pages = tc.get(f"/api/v1/jobs/{job_id}/pages").json()["pages"]
    page = next(p for p in pages if p["page_index"] == 15)
    assert (page["width_pt"], page["height_pt"]) == (403.0, 612.0)
