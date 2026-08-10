# RFC 0013: Artifact and Content-Addressed Cache Store (`.kap`)

| Status | Version | Date | Author |
| :--- | :--- | :--- | :--- |
| **Accepted** | 1.0.0 | 2026-08-08 | Core Architecture Team |

---

## 1. Executive Summary

RFC 0013 defines the Content-Addressed Storage (CAS) architecture and Knowledge Assembly Package (`.kap`) file structure. CAS guarantees $O(1)$ deduplication, instant cache retrieval, and immutable artifact indexing across local NVMe storage and remote S3/MinIO clusters.

---

## 2. Storage Tiering (L0 – L3)

| Cache Level | Technology | Scope | Latency | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **L0 Memory** | In-Memory LRU | Process-local | $< 1\text{ ms}$ | Active KRM tree nodes & AST structures |
| **L1 Local Disk** | NVMe SSD (`.kae/cache/`) | Local machine | $1 - 5\text{ ms}$ | Extracted images, page renders, cached LLM responses |
| **L2 Pack Store** | `.kap` Bundles | Project archive | $10 - 20\text{ ms}$ | Content-addressed archive bundles for offline deployment |
| **L3 Remote SEP** | S3 / MinIO / WebDAV | Shared cluster | $50 - 200\text{ ms}$ | Global team artifact repository |

---

## 3. The `.kap` Container Format

A `.kap` bundle (Knowledge Assembly Package) is an optimized, immutable ZIP/TAR archive indexed by SHA-256 containing:

```
archive-8086-ch04.kap/
├── manifest.json            # SnapshotManifest & ArtifactManifest
├── index.sqlite3            # O(1) SQLite metadata index
├── blobs/                   # Content-Addressed Storage blobs
│   ├── sha256/
│   │   ├── e3/
│   │   │   └── e3b0c44298fc1c149afbf4c...
│   │   └── a1/
│   │       └── a1b2c3d4e5f67890123456...
└── kae.lock                 # Reproducible build lock configuration
```

### 3.1 `ArtifactManifest` Schema

```json
{
  "artifact_id": "sha256:a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0",
  "mime_type": "image/tikz+code",
  "size_bytes": 10240,
  "created_at": "2026-08-08T12:00:00Z",
  "tags": ["tikz", "8086_register_map", "chapter_04"],
  "metadata": {
    "page_origin": 42,
    "confidence_score": 0.98
  }
}
```

---

## 4. Deduplication & Garbage Collection

- **Content Hashing:** Every blob is stored at path `blobs/sha256/{hash[:2]}/{hash}`.
- **Reference Counting:** Deleting a document decrements blob reference counts in `index.sqlite3`; blobs reaching zero references are purged during nightly GC sweeps.
