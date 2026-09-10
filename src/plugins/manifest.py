"""Plugin manifest model — parsed from plugin.yaml (RFC 0010 §3)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class PluginEntryPoint:
    class_path: str = ""
    target_recipe: str = ""


@dataclass
class PluginPermissions:
    krm_permissions: List[str] = field(default_factory=list)
    rg_permissions: List[str] = field(default_factory=list)
    kg_permissions: List[str] = field(default_factory=list)
    allow_network: bool = False
    max_memory_mb: int = 512
    timeout_seconds: int = 300


@dataclass
class PluginManifest:
    id: str = ""
    name: str = ""
    version: str = "0.0.0"
    kae_core_version: str = ">=0.0.0"
    author: str = ""
    license: str = ""
    permissions: PluginPermissions = field(default_factory=PluginPermissions)
    entry_points: Dict[str, List[PluginEntryPoint]] = field(default_factory=dict)
    signature: str = ""
    pubkey_id: str = ""

    @classmethod
    def from_yaml(cls, yaml_text: str) -> "PluginManifest":
        data = yaml.safe_load(yaml_text) or {}
        perms_data = data.get("permissions", {})
        perms = PluginPermissions(
            krm_permissions=perms_data.get("krm_permissions", []),
            rg_permissions=perms_data.get("rg_permissions", []),
            kg_permissions=perms_data.get("kg_permissions", []),
            allow_network=perms_data.get("allow_network", False),
            max_memory_mb=perms_data.get("max_memory_mb", 512),
            timeout_seconds=perms_data.get("timeout_seconds", 300),
        )
        eps: Dict[str, List[PluginEntryPoint]] = {}
        for category, items in (data.get("entry_points") or {}).items():
            eps[category] = [
                PluginEntryPoint(
                    class_path=ep.get("class", ""),
                    target_recipe=ep.get("target_recipe", ""),
                )
                for ep in (items or [])
            ]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            version=data.get("version", "0.0.0"),
            kae_core_version=data.get("kae_core_version", ">=0.0.0"),
            author=data.get("author", ""),
            license=data.get("license", ""),
            permissions=perms,
            entry_points=eps,
            signature=data.get("signature", ""),
            pubkey_id=data.get("pubkey_id", ""),
        )
