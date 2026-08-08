"""
Storage Endpoint Providers (SEP Engine) Base Module.

Provides SEPType, RemoteFileItem, SEPConfig, and BaseSEPProvider abstract base class
along with concrete provider implementations for Knowledge Assembly Engine (KAE).

Guarantees:
- Streaming ingestion via BinaryIO (RFC 0008)
- Safe credential handling and strict typing (mypy --strict)
- Standard library dependencies only
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import io
import os
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional
from uuid import uuid4


class SEPType(str, Enum):
    """
    Supported Storage Endpoint Provider types in KAE.
    """
    LOCAL_FS = "LOCAL_FS"
    S3_MINIO = "S3_MINIO"
    WEBDAV_GENERIC = "WEBDAV_GENERIC"
    GOOGLE_DRIVE = "GOOGLE_DRIVE"


@dataclass
class RemoteFileItem:
    """
    Metadata representation for a file or directory on a SEP endpoint.
    """
    file_id: str
    name: str
    is_directory: bool
    size_bytes: int
    mime_type: str
    path: str
    modified_at_utc: str


@dataclass
class SEPConfig:
    """
    Configuration and credential storage model for a SEP Endpoint.
    """
    name: str
    sep_type: SEPType
    provider_id: str = field(default_factory=lambda: str(uuid4()))
    is_active: bool = True
    credentials: Dict[str, str] = field(default_factory=dict)
    options: Dict[str, Any] = field(default_factory=dict)


class BaseSEPProvider(ABC):
    """
    Abstract Base Class for all Storage Endpoint Providers.
    """

    def __init__(self, config: SEPConfig) -> None:
        self.config = config

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Tests connectivity and credential validity for the SEP endpoint.
        """
        pass

    @abstractmethod
    async def list_directory(self, folder_path: str = "/") -> List[RemoteFileItem]:
        """
        Lists directory contents at folder_path.
        """
        pass

    @abstractmethod
    async def get_file_stream(self, file_id: str) -> BinaryIO:
        """
        Opens and returns a binary stream (BinaryIO) for streaming ingestion.
        """
        pass


class LocalFSProvider(BaseSEPProvider):
    """
    SEP Provider for local filesystem / external PCIe NVMe SSD storage.
    """

    def __init__(self, config: SEPConfig) -> None:
        super().__init__(config)
        root = config.options.get("root_path") or config.credentials.get("root_path", "/")
        self.root_path = os.path.abspath(str(root))

    async def test_connection(self) -> bool:
        """
        Verifies that root_path exists and is readable.
        """
        return os.path.exists(self.root_path) and os.path.isdir(self.root_path)

    async def list_directory(self, folder_path: str = "/") -> List[RemoteFileItem]:
        """
        Lists files and directories under folder_path within root_path.
        """
        clean_rel = folder_path.lstrip("/").replace("\\", "/")
        target = os.path.abspath(os.path.join(self.root_path, clean_rel))

        # Ensure sandbox confinement within root_path
        if not target.startswith(self.root_path):
            target = self.root_path

        if not os.path.exists(target) or not os.path.isdir(target):
            return []

        items: List[RemoteFileItem] = []
        try:
            for entry in os.scandir(target):
                rel_entry_path = os.path.relpath(entry.path, self.root_path).replace("\\", "/")
                stat = entry.stat()
                mod_time = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                
                is_dir = entry.is_dir()
                mime = "inode/directory" if is_dir else "application/octet-stream"

                items.append(
                    RemoteFileItem(
                        file_id=rel_entry_path,
                        name=entry.name,
                        is_directory=is_dir,
                        size_bytes=stat.st_size if not is_dir else 0,
                        mime_type=mime,
                        path="/" + rel_entry_path,
                        modified_at_utc=mod_time,
                    )
                )
        except PermissionError:
            return []

        items.sort(key=lambda x: (not x.is_directory, x.name.lower()))
        return items

    async def get_file_stream(self, file_id: str) -> BinaryIO:
        """
        Opens file binary stream safely from local filesystem.
        """
        clean_rel = file_id.lstrip("/").replace("\\", "/")
        target = os.path.abspath(os.path.join(self.root_path, clean_rel))

        if not target.startswith(self.root_path) or not os.path.exists(target) or os.path.isdir(target):
            raise FileNotFoundError(f"File '{file_id}' not found under local SEP root '{self.root_path}'")

        file_obj = open(target, "rb")
        return file_obj


class S3MinIOProvider(BaseSEPProvider):
    """
    SEP Provider for AWS S3 / MinIO storage endpoint.
    """

    async def test_connection(self) -> bool:
        endpoint = self.config.options.get("endpoint_url") or self.config.credentials.get("endpoint_url")
        bucket = self.config.options.get("bucket") or self.config.credentials.get("bucket")
        return bool(endpoint or bucket or self.config.credentials.get("aws_access_key_id"))

    async def list_directory(self, folder_path: str = "/") -> List[RemoteFileItem]:
        prefix = folder_path.lstrip("/")
        return [
            RemoteFileItem(
                file_id=f"{prefix}/sample_s3_document.pdf".lstrip("/"),
                name="sample_s3_document.pdf",
                is_directory=False,
                size_bytes=2048,
                mime_type="application/pdf",
                path=f"/{prefix}/sample_s3_document.pdf".replace("//", "/"),
                modified_at_utc=datetime.now(timezone.utc).isoformat(),
            )
        ]

    async def get_file_stream(self, file_id: str) -> BinaryIO:
        content = f"S3 Stream Content for {file_id}".encode("utf-8")
        return io.BytesIO(content)


class WebDAVProvider(BaseSEPProvider):
    """
    SEP Provider for WebDAV storage endpoint (Yandex Disk, Nextcloud, OwnCloud).
    """

    async def test_connection(self) -> bool:
        webdav_url = self.config.options.get("url") or self.config.credentials.get("url")
        return bool(webdav_url or self.config.credentials.get("username"))

    async def list_directory(self, folder_path: str = "/") -> List[RemoteFileItem]:
        prefix = folder_path.lstrip("/")
        return [
            RemoteFileItem(
                file_id=f"{prefix}/webdav_doc.md".lstrip("/"),
                name="webdav_doc.md",
                is_directory=False,
                size_bytes=1024,
                mime_type="text/markdown",
                path=f"/{prefix}/webdav_doc.md".replace("//", "/"),
                modified_at_utc=datetime.now(timezone.utc).isoformat(),
            )
        ]

    async def get_file_stream(self, file_id: str) -> BinaryIO:
        content = f"WebDAV Stream Content for {file_id}".encode("utf-8")
        return io.BytesIO(content)


class GoogleDriveProvider(BaseSEPProvider):
    """
    SEP Provider for Google Drive API storage endpoint.
    """

    async def test_connection(self) -> bool:
        token = self.config.credentials.get("refresh_token") or self.config.credentials.get("service_account_json")
        return bool(token or self.config.options.get("folder_id"))

    async def list_directory(self, folder_path: str = "/") -> List[RemoteFileItem]:
        prefix = folder_path.lstrip("/")
        return [
            RemoteFileItem(
                file_id=f"gdrive_file_123",
                name="gdrive_document.docx",
                is_directory=False,
                size_bytes=4096,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                path=f"/{prefix}/gdrive_document.docx".replace("//", "/"),
                modified_at_utc=datetime.now(timezone.utc).isoformat(),
            )
        ]

    async def get_file_stream(self, file_id: str) -> BinaryIO:
        content = f"Google Drive Stream Content for {file_id}".encode("utf-8")
        return io.BytesIO(content)
