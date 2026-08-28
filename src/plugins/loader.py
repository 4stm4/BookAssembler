"""Plugin loader — discover, verify, and load plugins (RFC 0010 §4)."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from src.plugins.manifest import PluginManifest
from src.plugins.signing import verify_plugin_with_trusted_key

log = logging.getLogger(__name__)


class PluginLoadError(Exception):
    pass


class PluginRegistry:
    """Discovers and verifies plugins from a directory."""

    def __init__(self, plugins_dir: Path, trusted_keys_dir: Optional[Path] = None) -> None:
        self._plugins_dir = plugins_dir
        self._trusted_keys_dir = trusted_keys_dir or (plugins_dir / "trusted_keys")
        self._manifests: Dict[str, PluginManifest] = {}

    def discover(self) -> List[PluginManifest]:
        if not self._plugins_dir.exists():
            return []
        manifests: List[PluginManifest] = []
        for entry in sorted(self._plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "plugin.yaml"
            if not manifest_path.exists():
                log.warning("Plugin dir %s has no plugin.yaml, skipping", entry.name)
                continue
            try:
                manifest = PluginManifest.from_yaml(manifest_path.read_text())
            except Exception as e:
                log.warning("Failed to parse %s: %s", manifest_path, e)
                continue
            manifests.append(manifest)
        return manifests

    def verify_and_register(self, manifest: PluginManifest, plugin_bytes: bytes) -> bool:
        if not manifest.signature or not manifest.pubkey_id:
            log.warning("Plugin %s has no signature, rejecting", manifest.id)
            return False
        ok = verify_plugin_with_trusted_key(
            plugin_bytes,
            manifest.signature,
            manifest.pubkey_id,
            self._trusted_keys_dir,
        )
        if not ok:
            log.warning("Plugin %s signature verification failed", manifest.id)
            return False
        self._manifests[manifest.id] = manifest
        log.info("Plugin %s v%s registered", manifest.id, manifest.version)
        return True

    def get_manifest(self, plugin_id: str) -> Optional[PluginManifest]:
        return self._manifests.get(plugin_id)

    @property
    def registered_plugins(self) -> Dict[str, PluginManifest]:
        return dict(self._manifests)
