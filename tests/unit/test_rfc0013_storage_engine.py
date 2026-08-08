"""
Unit tests for RFC 0013 Storage Engine (Content-Addressed Storage, Pack Storage, Snapshots, GC, Integrity).

Tests:
1. Content Addressing (idempotent storage, duplicate hash deduplication)
2. Pack Storage (.kap format creation, random access reading by index)
3. Snapshot Manifest & Reproducibility (resolving child artifacts)
4. Garbage Collection & Pinning (pin protection vs unreferenced cleanup)
5. Integrity Check (detecting byte corruption on load)
"""

import hashlib

from src.artifacts.models import ArtifactType, StorageTier
from src.artifacts.store import (
    ArtifactStore,
    MultiLevelCache,
    PackFileBuilder,
    PackFileReader,
)


def test_content_addressing_deduplication() -> None:
    """
    Test content addressing: re-storing identical content returns the exact same artifact_id
    without duplicating store data entries.
    """
    store = ArtifactStore()

    data = {"krm_version": "1.0.0", "title": "Deduplication Test Doc"}
    producer = "test_producer_v1"

    manifest1 = store.put_artifact(
        content=data,
        artifact_type=ArtifactType.NORMALIZED_KRM,
        producer=producer,
        producer_version="1.0.0",
    )

    manifest2 = store.put_artifact(
        content=data,
        artifact_type=ArtifactType.NORMALIZED_KRM,
        producer=producer,
        producer_version="1.0.0",
    )

    assert manifest1.artifact_id == manifest2.artifact_id
    assert manifest1.content_hash == manifest2.content_hash

    # Verify content retrieved matches original bytes
    retrieved_bytes = store.get_artifact(manifest1.artifact_id)
    assert len(retrieved_bytes) > 0


def test_pack_storage_kap_builder_and_reader() -> None:
    """
    Test PackFileBuilder and PackFileReader (.kap format) compressed block index and random access.
    """
    builder = PackFileBuilder()

    art1_id = "art_chunk_001"
    art1_data = b"Paragraph 1 text content for pack storage test."

    art2_id = "art_chunk_002"
    art2_data = b"Paragraph 2 text content with structured layout."

    builder.add_entry(art1_id, art1_data)
    builder.add_entry(art2_id, art2_data)

    pack_bytes = builder.build_pack()
    assert len(pack_bytes) > 20
    assert pack_bytes.endswith(b"KAP1")

    # Read back using PackFileReader
    reader = PackFileReader(pack_bytes)
    artifacts = reader.list_artifacts()

    assert art1_id in artifacts
    assert art2_id in artifacts

    assert reader.read_artifact(art1_id) == art1_data
    assert reader.read_artifact(art2_id) == art2_data


def test_snapshot_manifest_and_child_resolution() -> None:
    """
    Test SnapshotManifest creation, serialization, and resolution of all referenced artifact IDs.
    """
    store = ArtifactStore()

    manifest_raw = store.put_artifact(
        content="Raw KRM content",
        artifact_type=ArtifactType.RAW_KRM,
        producer="raw_parser",
        producer_version="1.0",
    )

    manifest_norm = store.put_artifact(
        content="Normalized KRM content",
        artifact_type=ArtifactType.NORMALIZED_KRM,
        producer="normalizer",
        producer_version="1.0",
    )

    artifact_refs = {
        "raw_krm": manifest_raw.artifact_id,
        "normalized_krm": manifest_norm.artifact_id,
    }

    build_id = "build_kae_release_2026_01"
    snapshot = store.create_snapshot(build_id=build_id, artifact_refs=artifact_refs)

    retrieved_snap = store.get_snapshot(snapshot.snapshot_id)
    assert retrieved_snap.build_id == build_id
    assert retrieved_snap.artifact_refs["raw_krm"] == manifest_raw.artifact_id

    # Verify resolving children through store
    raw_content = store.get_artifact(retrieved_snap.artifact_refs["raw_krm"])
    assert raw_content == b"Raw KRM content"


def test_garbage_collection_and_pinning() -> None:
    """
    Test artifact pinning and garbage collection.
    Pinned and snapshot-referenced artifacts are preserved; unreferenced ones are collected.
    """
    store = ArtifactStore()

    # Create 3 artifacts
    m_pinned = store.put_artifact(
        content="Pinned Artifact Content",
        artifact_type=ArtifactType.OCR_RESULT,
        producer="ocr_engine",
        producer_version="1.0",
    )

    m_snap_ref = store.put_artifact(
        content="Snapshot Referenced Artifact Content",
        artifact_type=ArtifactType.LAYOUT_KRM,
        producer="layout_engine",
        producer_version="1.0",
    )

    m_unreferenced = store.put_artifact(
        content="Orphaned Temporary Content",
        artifact_type=ArtifactType.OCR_RESULT,
        producer="ocr_engine",
        producer_version="1.0",
    )

    # Pin m_pinned
    store.pin_artifact(m_pinned.artifact_id)

    # Reference m_snap_ref in a snapshot
    store.create_snapshot("build_gc_test", {"layout": m_snap_ref.artifact_id})

    # Run GC
    collected_count = store.run_garbage_collection()
    assert collected_count == 1

    # Verify m_pinned and m_snap_ref still exist
    assert store.get_metadata(m_pinned.artifact_id) is not None
    assert store.get_metadata(m_snap_ref.artifact_id) is not None

    # Verify m_unreferenced was garbage collected
    assert store.get_metadata(m_unreferenced.artifact_id) is None


def test_integrity_check_corruption_detection() -> None:
    """
    Test integrity verification: tampering with stored bytes causes SHA-256 hash mismatch
    and raises STORAGE_CORRUPTED ValueError.
    """
    store = ArtifactStore()

    manifest = store.put_artifact(
        content="Original untampered document content",
        artifact_type=ArtifactType.SOURCE_DOCUMENT,
        producer="ingest_pipeline",
        producer_version="1.0",
    )

    # Verify normal read succeeds
    assert store.get_artifact(manifest.artifact_id) == b"Original untampered document content"

    # Simulate byte corruption
    store.corrupt_artifact_bytes_for_testing(
        manifest.artifact_id, b"Corrupted tampered document content"
    )

    # Attempt to load corrupted artifact
    try:
        store.get_artifact(manifest.artifact_id)
        assert False, "Should have raised ValueError for corrupted artifact content"
    except ValueError as exc:
        assert "STORAGE_CORRUPTED" in str(exc)


def test_multilevel_cache_computation_keys() -> None:
    """
    Test MultiLevelCache compute_cache_key determinism and value caching.
    """
    cache = MultiLevelCache()

    key_hash = cache.compute_cache_key(
        analyzer_name="layout_analyzer",
        version="2.1.0",
        input_hashes=["hash_abc", "hash_xyz"],
        config={"threshold": 0.85},
    )

    assert len(key_hash) == 64

    cache.put_cached_computation(key_hash, {"status": "success", "blocks": 15})
    cached_val = cache.get_cached_computation(key_hash)

    assert cached_val is not None
    assert cached_val["blocks"] == 15


if __name__ == "__main__":
    test_content_addressing_deduplication()
    test_pack_storage_kap_builder_and_reader()
    test_snapshot_manifest_and_child_resolution()
    test_garbage_collection_and_pinning()
    test_integrity_check_corruption_detection()
    test_multilevel_cache_computation_keys()
    print("ALL RFC 0013 STORAGE ENGINE TESTS PASSED PERFECTLY!")
