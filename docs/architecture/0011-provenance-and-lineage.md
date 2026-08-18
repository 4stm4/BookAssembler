# RFC 0011: Provenance and Lineage Tracking

| Status | Version | Date | Author |
| :--- | :--- | :--- | :--- |
| **Accepted** | 1.0.0 | 2026-08-08 | Core Architecture Team |

---

## 1. Executive Summary

RFC 0011 defines the cryptographic provenance and lineage tracking mechanism for the Knowledge Assembly Engine (KAE). Every node, diagram, table, code snippet, and translated text segment produced by KAE maintains immutable traceability back to its exact bounding box coordinates ($[x_0, y_0, x_1, y_1]$), page number, and original SHA-256 hash of the input document artifact.

---

## 2. Lineage Architecture & Models

### 2.1 Bounding Box Coordinates & Pages
All visual or structural elements extracted from PDF, DJVU, or scanned image
sources store spatial coordinates **normalized to the unit square `[0.0, 1.0]`**,
consistent with `NormalizedRect` in RFC 0002 (§inv3: `x0 <= x1`, `y0 <= y1`,
values in `[0.0, 1.0]`). The lineage `BoundingBox` is a projection of the node's
`VisualLayout.bounding_box`; the page is referenced by `page_or_screen_index`,
the same field name used in RFC 0002 `VisualLayout` (aliased below as `page`).

> **Resolution (supersedes v1.0.0):** earlier drafts specified a `1000 × 1000`
> grid and a `page_number` field. The canonical grid is the resolution-independent
> unit square `[0,1]` used by the KRM model and all analyzers. Consumers that need
> device pixels multiply by page width/height at render time.

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class BoundingBox:
    page_or_screen_index: int  # page index, matches RFC 0002 VisualLayout
    x0: float  # Top-left X     (0.0 to 1.0)
    y0: float  # Top-left Y     (0.0 to 1.0)
    x1: float  # Bottom-right X (0.0 to 1.0)
    y1: float  # Bottom-right Y (0.0 to 1.0)

@dataclass
class LineageRecord:
    source_artifact_sha256: str
    source_uri: str
    bbox: BoundingBox
    extraction_timestamp: str
    confidence_score: float
```

### 2.2 Transformation Graph (`TransformationStep`)
Every mutation or translation step forms a Directed Acyclic Graph (DAG) of transformation steps:

```json
{
  "lineage_id": "lin-8086-ch04-fig01",
  "source_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "bbox": { "page_or_screen_index": 42, "x0": 0.1205, "y0": 0.340, "x1": 0.880, "y1": 0.6502 },
  "transformations": [
    {
      "step_index": 0,
      "agent_type": "analyzer_cv",
      "action": "diagram_extraction",
      "input_hash": "sha256:a1b2c3...",
      "output_hash": "sha256:d4e5f6...",
      "timestamp": "2026-08-08T12:00:00Z"
    },
    {
      "step_index": 1,
      "agent_type": "llm_tikz_converter",
      "action": "tikz_vectorization",
      "model": "gpt-4o",
      "prompt_hash": "sha256:112233...",
      "output_hash": "sha256:778899...",
      "timestamp": "2026-08-08T12:01:15Z"
    }
  ]
}
```

---

## 3. Cryptographic Verification

1. **Leaf Validation:** Before any node in the KRM tree is saved, its `source_sha256` is validated against the input document manifest.
2. **Merkle Lineage Trees:** Individual node hashes are concatenated and hashed to form chapter-level and book-level Merkle roots, ensuring no single character or coordinate can be tampered with undetected.

---

## 4. Usage in UI & Audit

In the KAE Clean Workspace, selecting any item (such as an assembly instruction explanation or TikZ diagram) immediately highlights the exact bounding box overlay on the source PDF viewer pane.
