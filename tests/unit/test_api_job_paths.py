"""A job id names one directory under KAE_SSD_PATH, never a path out of it.

Starlette decodes the path before it matches a route, so %2E%2E reaches the
handlers as job_id "..": DELETE /api/v1/jobs/%2E%2E removed the data root's
parent, every job and whatever lay beside it, and the downloads served files
from there. The assemble request's target_lang names the output file, and
"x/../../elsewhere/planted" wrote the book outside the job's directory.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from src.api.app import create_app

JOB = "3f1c2a9e-5b7d-4e8a-9c0f-1a2b3c4d5e6f"
OTHER = "7a8b9c0d-1e2f-4a3b-8c5d-6e7f8a9b0c1d"


@pytest.fixture()
def data(tmp_path, monkeypatch):
    root = tmp_path / "data"
    ssd = root / "ssd"
    for job in (JOB, OTHER):
        (ssd / job).mkdir(parents=True)
        (ssd / job / "book.pdf").write_bytes(b"%PDF-1.4")
    (root / "keep.txt").write_text("beside the data root")
    monkeypatch.setenv("KAE_SSD_PATH", str(ssd))
    monkeypatch.setenv("KAE_DATA_DIR", str(root / "kae"))
    with TestClient(create_app()) as client:
        yield client, root, ssd


@pytest.mark.parametrize("job_id", ["%2E%2E", "%2E"])
def test_delete_leaves_everything_outside_the_job_alone(data, job_id):
    client, root, ssd = data
    res = client.delete(f"/api/v1/jobs/{job_id}")
    assert (root / "keep.txt").read_text() == "beside the data root"
    assert (ssd / JOB / "book.pdf").is_file()
    assert (ssd / OTHER / "book.pdf").is_file()
    assert res.status_code == 404


def test_delete_removes_the_job_and_only_it(data):
    client, root, ssd = data
    res = client.delete(f"/api/v1/jobs/{JOB}")
    assert res.status_code == 200
    assert res.json() == {"status": "deleted", "job_id": JOB}
    assert not (ssd / JOB).exists()
    assert (ssd / OTHER / "book.pdf").is_file()
    assert (root / "keep.txt").is_file()


@pytest.mark.parametrize("what, planted", [
    ("preview", "preview_pages.pdf"),
    ("translated", "translated_russian.pdf"),
])
def test_downloads_serve_nothing_from_outside_the_job(data, what, planted):
    client, root, ssd = data
    (root / planted).write_bytes(b"%PDF-1.4 not a job's")
    (ssd / planted).write_bytes(b"%PDF-1.4 not a job's")
    for job_id in ("%2E%2E", "%2E"):
        assert client.get(f"/api/v1/jobs/{job_id}/download/{what}").status_code == 404


def test_the_translated_book_of_a_job_is_served(data):
    client, _root, ssd = data
    (ssd / JOB / "translated_russian.pdf").write_bytes(b"%PDF-1.4 book")
    res = client.get(f"/api/v1/jobs/{JOB}/download/translated")
    assert res.status_code == 200
    assert res.content == b"%PDF-1.4 book"


@pytest.mark.parametrize("lang", [
    "x/../../planted", "x\\..\\..\\planted", "Rus\x00sian", "",
])
def test_the_target_language_names_no_path(data, lang):
    client, root, _ssd = data
    res = client.post(f"/api/v1/jobs/{JOB}/assemble", json={"target_lang": lang})
    assert res.status_code == 422
    assert not list(root.rglob("planted*"))


@pytest.mark.parametrize("uri", [
    "file:///etc/hosts", "FILE:///srv/book.pdf", "upload://../../keep.pdf",
    "sep://nvme-local/../keep.pdf", "/etc/hosts", "\\\\server\\share\\book.pdf",
])
def test_a_text_payload_names_no_file_on_the_server(data, uri):
    """The analyzers read a document's source by its uri; a text payload's
    uri is only a label, and one naming a server file had them read it."""
    client, _root, _ssd = data
    before = client.get("/api/v1/documents").json()
    res = client.post("/api/v1/documents/upload",
                      json={"source_uri": uri, "content": "some text"})
    assert res.status_code == 422
    assert client.get("/api/v1/documents").json() == before


@pytest.mark.parametrize("uri", ["workspace://document_ch4.txt", "s3://bucket/doc.pdf"])
def test_a_text_payload_keeps_its_label(data, uri):
    client, _root, _ssd = data
    res = client.post("/api/v1/documents/upload",
                      json={"source_uri": uri, "content": "some text"})
    assert res.status_code == 201
    assert res.json()["source_uri"] == uri


def test_an_upload_is_named_by_its_base_name(data):
    client, root, ssd = data
    res = client.post("/api/v1/documents/upload",
                      files={"file": ("../../keep.txt", b"text of the upload", "text/plain")})
    assert res.status_code == 201
    assert res.json()["source_uri"] == "upload://keep.txt"
    assert (root / "keep.txt").read_text() == "beside the data root"
