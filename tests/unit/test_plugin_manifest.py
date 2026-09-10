"""Tests for PluginManifest parsing."""
import pytest

from src.plugins.manifest import PluginManifest


_SAMPLE_YAML = """\
id: "plugin.org.chem_extractor"
name: "Chemistry Extractor"
version: "1.2.0"
kae_core_version: ">=2.0.0"
author: "ChemAI Lab"
license: "MIT"
permissions:
  krm_permissions: ["READ", "INSERT"]
  rg_permissions: ["READ"]
  kg_permissions: ["READ", "MUTATE_ENTITIES"]
  allow_network: false
  max_memory_mb: 1024
  timeout_seconds: 300
entry_points:
  analyzers:
    - class: "src.chem.ChemAnalyzer"
      target_recipe: "recipe.chemistry"
signature: "abc123"
pubkey_id: "chemai"
"""


class TestManifestParsing:
    def test_basic_fields(self):
        m = PluginManifest.from_yaml(_SAMPLE_YAML)
        assert m.id == "plugin.org.chem_extractor"
        assert m.version == "1.2.0"
        assert m.author == "ChemAI Lab"

    def test_permissions(self):
        m = PluginManifest.from_yaml(_SAMPLE_YAML)
        assert "READ" in m.permissions.krm_permissions
        assert m.permissions.max_memory_mb == 1024
        assert not m.permissions.allow_network

    def test_entry_points(self):
        m = PluginManifest.from_yaml(_SAMPLE_YAML)
        assert "analyzers" in m.entry_points
        assert m.entry_points["analyzers"][0].class_path == "src.chem.ChemAnalyzer"

    def test_signature_fields(self):
        m = PluginManifest.from_yaml(_SAMPLE_YAML)
        assert m.signature == "abc123"
        assert m.pubkey_id == "chemai"

    def test_empty_yaml(self):
        m = PluginManifest.from_yaml("")
        assert m.id == ""
        assert m.version == "0.0.0"
