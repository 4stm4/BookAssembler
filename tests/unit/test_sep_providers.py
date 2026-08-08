"""
Unit tests for Storage Endpoint Providers (SEP Engine) & FastAPI SEP endpoints.

Tests:
1. LocalFSProvider connection test, directory listing, and binary stream reading.
2. SEPManager registration, listing, retrieval, and job import.
3. FastAPI endpoints: POST /providers, GET /providers, GET /{id}/browse, POST /{id}/import.
"""

import asyncio
import os
import tempfile
from typing import BinaryIO

from fastapi.testclient import TestClient

from src.adapters.providers import (
    LocalFSProvider,
    RemoteFileItem,
    SEPConfig,
    SEPManager,
    SEPType,
)
from src.api.app import create_app
from src.jobs.manager import JobManager


def test_local_fs_provider_lifecycle() -> None:
    """
    Tests LocalFSProvider: connection check, directory listing, and binary file streaming.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create test subfolder and files
        sub_dir = os.path.join(tmp_dir, "documents")
        os.makedirs(sub_dir, exist_ok=True)

        file1_path = os.path.join(sub_dir, "report.txt")
        file_content = b"Knowledge Assembly Engine SEP Content Test"
        with open(file1_path, "wb") as f:
            f.write(file_content)

        config = SEPConfig(
            name="Local SSD /mnt/nvme",
            sep_type=SEPType.LOCAL_FS,
            options={"root_path": tmp_dir},
        )

        provider = LocalFSProvider(config)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 1. Test Connection
        connected = loop.run_until_complete(provider.test_connection())
        assert connected is True

        # 2. Test List Directory Root
        root_items = loop.run_until_complete(provider.list_directory("/"))
        assert len(root_items) == 1
        assert root_items[0].name == "documents"
        assert root_items[0].is_directory is True

        # 3. Test List Directory Subfolder
        sub_items = loop.run_until_complete(provider.list_directory("/documents"))
        assert len(sub_items) == 1
        assert sub_items[0].name == "report.txt"
        assert sub_items[0].is_directory is False
        assert sub_items[0].size_bytes == len(file_content)

        # 4. Test Get File Stream
        stream: BinaryIO = loop.run_until_complete(provider.get_file_stream("/documents/report.txt"))
        read_bytes = stream.read()
        stream.close()
        assert read_bytes == file_content

        loop.close()


def test_sep_manager_operations() -> None:
    """
    Tests SEPManager registration, listing, and import into JobManager.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "data.pdf")
        with open(test_file, "wb") as f:
            f.write(b"PDF Binary Data")

        manager = SEPManager()
        job_manager = JobManager()

        config = SEPConfig(
            name="Backup Local FS",
            sep_type=SEPType.LOCAL_FS,
            credentials={"root_path": tmp_dir},
        )

        # 1. Register
        provider = manager.register_provider(config)
        assert provider.config.provider_id == config.provider_id

        # 2. List Configured
        all_configs = manager.list_configured_providers()
        assert len(all_configs) == 1
        assert all_configs[0].name == "Backup Local FS"

        # 3. Get Provider
        retrieved = manager.get_provider(config.provider_id)
        assert retrieved == provider

        # 4. Import File to KAE
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        job = loop.run_until_complete(
            manager.import_file_to_kae(
                provider_id=config.provider_id,
                file_id="data.pdf",
                job_manager=job_manager,
            )
        )
        loop.close()

        assert job.job_id is not None
        assert job.source_uri == f"sep://{config.provider_id}/data.pdf"
        assert job.status.value == "QUEUED"


def test_fastapi_sep_endpoints() -> None:
    """
    Tests FastAPI REST API SEP endpoints: create provider, list, browse, import.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.makedirs(os.path.join(tmp_dir, "books"), exist_ok=True)
        book_file = os.path.join(tmp_dir, "books", "chapter1.txt")
        with open(book_file, "w", encoding="utf-8") as f:
            f.write("Chapter 1: The Foundations of Knowledge")

        app = create_app()
        client = TestClient(app)

        # 1. POST /api/v1/sep/providers (Create Provider)
        create_resp = client.post(
            "/api/v1/sep/providers",
            json={
                "name": "Local Book Depot",
                "sep_type": "LOCAL_FS",
                "options": {"root_path": tmp_dir},
            },
        )
        assert create_resp.status_code == 201
        created_data = create_resp.json()
        provider_id = created_data["provider_id"]
        assert created_data["name"] == "Local Book Depot"
        assert created_data["sep_type"] == "LOCAL_FS"

        # 2. GET /api/v1/sep/providers (List Providers)
        list_resp = client.get("/api/v1/sep/providers")
        assert list_resp.status_code == 200
        providers = list_resp.json()
        assert len(providers) == 1
        assert providers[0]["provider_id"] == provider_id

        # 3. GET /api/v1/sep/providers/{provider_id}/browse (Browse Directory)
        browse_resp = client.get(f"/api/v1/sep/providers/{provider_id}/browse?folder_path=/books")
        assert browse_resp.status_code == 200
        items = browse_resp.json()
        assert len(items) == 1
        assert items[0]["name"] == "chapter1.txt"
        assert items[0]["is_directory"] is False

        # 4. POST /api/v1/sep/providers/{provider_id}/import (Import File)
        import_resp = client.post(
            f"/api/v1/sep/providers/{provider_id}/import",
            json={"file_id": "/books/chapter1.txt"},
        )
        assert import_resp.status_code == 201
        import_data = import_resp.json()
        job_id = import_data["job_id"]
        assert import_data["status"] == "QUEUED"
        assert f"sep://{provider_id}/books/chapter1.txt" in import_data["source_uri"]

        # 5. GET /api/v1/jobs/{job_id}/status (Verify Job Created)
        status_resp = client.get(f"/api/v1/jobs/{job_id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["job_id"] == job_id


if __name__ == "__main__":
    test_local_fs_provider_lifecycle()
    test_sep_manager_operations()
    test_fastapi_sep_endpoints()
    print("ALL SEP PROVIDER TESTS PASSED PERFECTLY!")
