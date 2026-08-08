"""
SEP Manager Module for Knowledge Assembly Engine (KAE).

Manages registration, configuration, browsing, and document ingestion from
Storage Endpoint Providers (SEP) into KAE JobManager.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only
"""

from typing import Dict, List, Optional

from src.adapters.providers.base import (
    BaseSEPProvider,
    GoogleDriveProvider,
    LocalFSProvider,
    S3MinIOProvider,
    SEPConfig,
    SEPType,
    WebDAVProvider,
)
from src.jobs.manager import JobManager, JobRecord


class SEPManager:
    """
    Registry and orchestration manager for Storage Endpoint Providers.
    """

    def __init__(self) -> None:
        self._configs: Dict[str, SEPConfig] = {}
        self._providers: Dict[str, BaseSEPProvider] = {}

    def register_provider(self, config: SEPConfig) -> BaseSEPProvider:
        """
        Registers a new SEP provider configuration and instantiates its driver.
        """
        provider_class: type[BaseSEPProvider]

        if config.sep_type == SEPType.LOCAL_FS:
            provider_class = LocalFSProvider
        elif config.sep_type == SEPType.S3_MINIO:
            provider_class = S3MinIOProvider
        elif config.sep_type == SEPType.WEBDAV_GENERIC:
            provider_class = WebDAVProvider
        elif config.sep_type == SEPType.GOOGLE_DRIVE:
            provider_class = GoogleDriveProvider
        else:
            raise ValueError(f"Unsupported SEPType '{config.sep_type}'")

        provider = provider_class(config)
        self._configs[config.provider_id] = config
        self._providers[config.provider_id] = provider
        return provider

    def list_configured_providers(self) -> List[SEPConfig]:
        """
        Returns list of all configured SEP provider settings.
        """
        return list(self._configs.values())

    def get_provider(self, provider_id: str) -> BaseSEPProvider:
        """
        Retrieves active SEP provider instance by provider_id.
        """
        provider = self._providers.get(provider_id)
        if provider is None:
            raise KeyError(f"SEP Provider with ID '{provider_id}' not found")
        return provider

    async def import_file_to_kae(
        self,
        provider_id: str,
        file_id: str,
        job_manager: JobManager,
    ) -> JobRecord:
        """
        Streams file from provider and initializes processing Job in JobManager.
        """
        provider = self.get_provider(provider_id)
        
        # Verify file stream capability (raises error if missing/unreachable)
        _stream = await provider.get_file_stream(file_id)

        source_uri = f"sep://{provider_id}/{file_id.lstrip('/')}"
        job = job_manager.create_job(source_uri=source_uri)
        return job
