"""Every unit test keeps its data to itself.

The app factory (src.api.app.create_app) registers the host's book store
as a provider where KAE_SSD_PATH names a directory that exists, and keeps
documents and its audit log under KAE_DATA_DIR. In the deployed container
both name the real store: a test listing "its one provider" found the
RPi5's NVMe beside it, and every run left its "s3://bucket/doc123.pdf"
among the real documents. Here each test is given directories of its own
- the book store's not made, so nothing is registered - as on a machine
with no store at all. A test that needs one sets it itself.
"""

import pytest


@pytest.fixture(autouse=True)
def _own_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KAE_DATA_DIR", str(tmp_path / "kae-data"))
    monkeypatch.setenv("KAE_SSD_PATH", str(tmp_path / "kae-ssd"))
