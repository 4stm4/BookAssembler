"""
Unit tests for P0 Infrastructure Modules (RFC 0011, RFC 0012, RFC 0015).

Tests:
1. Provenance & Lineage Tracker (RFC 0011)
2. Reproducible Builds & Lock Engine (RFC 0012)
3. Error Taxonomy & Quality Diagnostics (RFC 0015)
"""

import json
from src.benchmark.taxonomy import (
    ErrorCategory,
    QualityTaxonomyReport,
    TaxonomyAnalyzer,
    TaxonomyErrorItem,
)
from src.build.lock import (
    BuildLockManifest,
    BuildLockManager,
)
from src.provenance.models import (
    LineageRecord,
    ProvenanceTracker,
    SourceLocation,
    TransformationStep,
)


def test_provenance_and_lineage_tracker() -> None:
    """
    Test creation of SourceLocation, TransformationStep, registration in ProvenanceTracker,
    and verification of lineage record chain.
    """
    tracker = ProvenanceTracker()

    source_bytes = b"Sample raw document content for provenance testing"
    source_sha256 = ProvenanceTracker.calculate_content_hash(source_bytes)

    source_loc = SourceLocation(
        source_uri="file:///docs/sample.pdf",
        source_sha256=source_sha256,
        page_or_screen_index=1,
        bounding_box={"x": 10.0, "y": 20.0, "width": 100.0, "height": 50.0},
        byte_offset_range=(0, 48),
    )

    entity_id = "node_p0_001"
    lineage = tracker.register_entity(entity_id, source_loc)

    assert lineage.entity_id == entity_id
    assert lineage.source_location.source_uri == "file:///docs/sample.pdf"
    assert lineage.source_location.source_sha256 == source_sha256
    assert len(lineage.transformation_history) == 0

    input_hash = ProvenanceTracker.calculate_content_hash("Raw text input")
    output_hash = ProvenanceTracker.calculate_content_hash("Normalized text output")

    step1 = TransformationStep(
        agent_type="text_normalizer",
        agent_id="agent_norm_v1",
        agent_version="1.2.0",
        input_snapshot_hash=input_hash,
        output_snapshot_hash=output_hash,
        mutation_description="Normalized unicode whitespaces and lowercased titles",
        confidence_score=0.98,
    )

    updated_lineage = tracker.add_transformation_step(entity_id, step1)
    assert len(updated_lineage.transformation_history) == 1
    assert updated_lineage.transformation_history[0].agent_type == "text_normalizer"
    assert updated_lineage.transformation_history[0].confidence_score == 0.98

    retrieved = tracker.get_lineage(entity_id)
    assert retrieved is not None
    assert len(retrieved.transformation_history) == 1
    assert retrieved.transformation_history[0].step_id == step1.step_id


def test_reproducible_build_and_lock_manifest() -> None:
    """
    Test SHA-256 calculation, BuildLockManifest creation, JSON serialization,
    and reproducibility verification.
    """
    source_uri = "s3://bucket/sources/spec.pdf"
    source_bytes = b"PDF binary stream contents for lock test"

    recipe_id = "recipe_assembly_standard"
    recipe_version = "2.1.0"

    components = {
        "analyzer_pdf": "a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0",
        "skill_table_extractor": "f0e9d8c7b6a543210987654321fedcba0123456789abcdef0123456789abcdef",
    }

    artifacts = {
        "krm_document.json": b'{"doc_title": "Assembly Spec"}',
        "knowledge_graph.json": b'{"nodes": [], "edges": []}',
    }

    manifest = BuildLockManager.create_lock(
        source_uri=source_uri,
        source_bytes=source_bytes,
        recipe_id=recipe_id,
        recipe_version=recipe_version,
        components=components,
        artifacts=artifacts,
        kae_core_version="0.1.0",
    )

    assert manifest.source_uri == source_uri
    assert manifest.recipe_id == recipe_id
    assert manifest.kae_core_version == "0.1.0"
    assert len(manifest.artifacts_hashes) == 2
    assert "krm_document.json" in manifest.artifacts_hashes

    # Test serialization to JSON and back
    json_str = manifest.to_json()
    parsed_manifest = BuildLockManifest.from_json(json_str)

    assert parsed_manifest.source_sha256 == manifest.source_sha256
    assert parsed_manifest.components_hashes == manifest.components_hashes
    assert parsed_manifest.artifacts_hashes == manifest.artifacts_hashes

    # Test reproducibility check
    assert BuildLockManager.verify_reproducibility(manifest, parsed_manifest) is True

    # Test drift detection (modified source bytes)
    modified_source_bytes = b"MODIFIED binary stream contents"
    modified_manifest = BuildLockManager.create_lock(
        source_uri=source_uri,
        source_bytes=modified_source_bytes,
        recipe_id=recipe_id,
        recipe_version=recipe_version,
        components=components,
        artifacts=artifacts,
    )

    assert BuildLockManager.verify_reproducibility(manifest, modified_manifest) is False


def test_error_taxonomy_and_diagnostics_report() -> None:
    """
    Test error taxonomy categorization, error recording, and QualityTaxonomyReport generation.
    """
    analyzer = TaxonomyAnalyzer()

    item1 = analyzer.add_error(
        category=ErrorCategory.TEXT_OCR_MISREAD,
        target_id="line_101",
        description="Character 'rn' misread as 'm'",
        severity="warning",
    )
    assert item1.category == ErrorCategory.TEXT_OCR_MISREAD

    analyzer.add_error(
        category=ErrorCategory.LAYOUT_COLUMN_ORDER_SWAPPED,
        target_id="page_2_col_1",
        description="Sidebar text injected into main column body",
        severity="critical",
    )

    analyzer.add_error(
        category=ErrorCategory.TABLE_CELL_MERGE_MISSING,
        target_id="table_1_cell_3",
        description="Spanned header cell split into two cells",
        severity="blocker",
    )

    analyzer.add_error(
        category=ErrorCategory.GRAPH_BROKEN_CROSSREF,
        target_id="edge_404",
        description="Figure reference target id does not exist in document",
        severity="info",
    )

    report = analyzer.generate_report()

    assert report.total_errors_count == 4
    assert report.critical_blockers_count == 2
    assert report.errors_by_category[ErrorCategory.TEXT_OCR_MISREAD.value] == 1
    assert report.errors_by_category[ErrorCategory.LAYOUT_COLUMN_ORDER_SWAPPED.value] == 1
    assert report.errors_by_category[ErrorCategory.TABLE_CELL_MERGE_MISSING.value] == 1
    assert report.errors_by_category[ErrorCategory.GRAPH_BROKEN_CROSSREF.value] == 1


if __name__ == "__main__":
    test_provenance_and_lineage_tracker()
    test_reproducible_build_and_lock_manifest()
    test_error_taxonomy_and_diagnostics_report()
    print("ALL P0 INFRASTRUCTURE TESTS PASSED!")
