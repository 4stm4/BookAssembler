# RFC 0012: Reproducible Builds Specification (`kae.lock`)

| Status | Version | Date | Author |
| :--- | :--- | :--- | :--- |
| **Accepted** | 1.0.0 | 2026-08-08 | Core Architecture Team |

---

## 1. Executive Summary

RFC 0012 specifies the deterministic build environment and locking format (`kae.lock`) for KAE assembly operations. To ensure that rebuilding a technical book or knowledge archive years later produces byte-for-byte identical LaTeX PDFs and KRM trees, KAE pins exact versions of analyzers, LLM models, prompts, skills, and input artifact hashes.

---

## 2. The `kae.lock` Format

The `kae.lock` file is generated alongside the project manifest (`book.json`) after a successful assembly build:

```json
{
  "lock_version": "1.0",
  "build_id": "build-2026-08-08-ch04-8086",
  "created_at": "2026-08-08T12:00:00Z",
  "input_artifacts": [
    {
      "file": "books/8086_Family_Users_Manual_Ch04.pdf",
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "size_bytes": 4210500
    }
  ],
  "analyzers": {
    "pdf_extractor": "v2.4.1",
    "cv_diagram_engine": "v1.8.0",
    "tikz_repair_skill": "v3.1.2"
  },
  "llm_configuration": {
    "provider": "openai",
    "model": "gpt-4o",
    "model_snapshot_id": "gpt-4o-2026-05-15",
    "temperature": 0.0,
    "seed": 42
  },
  "glossary_hash": "sha256:8899aabbcc...",
  "output_hashes": {
    "krm_tree": "sha256:1122334455...",
    "knowledge_graph": "sha256:5566778899...",
    "latex_pdf": "sha256:aabbccddeeff..."
  }
}
```

---

## 3. Determinism Enforcement Rules

1. **Zero Temperature & Fixed Seeds:** All LLM calls specified in build recipes must mandate `temperature = 0.0` and a deterministic random seed (`seed = 42`).
2. **Pinned Prompt Hashes:** System and user prompts are hashed via SHA-256; any modification invalidates cache lookup.
3. **Environment Isolation:** XeLaTeX compilation runs inside a locked Docker image containing pinned TeX Live fonts and packages (`texlive/texlive:2026-frozen`).

---

## 4. Replay Mode (`kae rebuild`)

Executing `kae rebuild --lock kae.lock` bypasses live LLM calls where cache hits exist in the Content-Addressed Storage, achieving instant, reproducible builds.
