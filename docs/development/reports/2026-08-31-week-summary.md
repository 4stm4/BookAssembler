# Week Summary: 25–31 Aug 2026

## Overview
7-day sprint bringing KAE from v0.3.x (11 analyzers, ~230 tests) to v0.4.0 (22 analyzers, 372 tests).

## Day-by-Day

| Day | Theme | Tests Added | Total |
|-----|-------|-------------|-------|
| Mon 25 | P0: ListBlock, TocEntryBlock, FormulaBlock | +56 | 286 |
| Tue 26 | P1: CalloutBlock, FootnoteBlock, BibEntryBlock | +43 | 286→329* |
| Wed 27 | P2: TheoremSpec/ProofSpec/ExampleSpec/RemarkSpec, ProperNounExtractor, CitationLinker | — | — |
| Thu 28 | P3: EphemeraBlock, AlgorithmBlock, IndexEntryBlock, SidebarBlock + Plugin API (Ed25519) | +52 | 329→286** |
| Fri 29 | Skills Engine: DSL parser, SkillsRunner, 3 skill packs (pdp11, pdf-lit, math-book), API endpoints | +43 | 329 |
| Sat 30 | Contract testing (idempotency + determinism), Vision Router, Kaggle subprocess | +35 | 364 |
| Sun 31 | E2E PDP-11 integration test, documentation finalization, v0.4.0 tag | +8 | 372 |

*Days 25–28 ran across sessions; intermediate counts approximate.

## Key Deliverables

### KRM Types (P0–P3 complete)
- **P0**: ListBlock/ListItemBlock, TocEntryBlock, FormulaBlock
- **P1**: CalloutBlock, FootnoteBlock, BibEntryBlock
- **P2**: TheoremSpec, ProofSpec, ExampleSpec, RemarkSpec (SemanticUnit decorators)
- **P3**: EphemeraBlock, AlgorithmBlock, IndexEntryBlock, SidebarBlock

Each type: model → detector → pipeline registration → serialize/deserialize → LaTeX → translator → chunker → unit tests.

### Skills Engine
- Recursive descent DSL: `contains`, `equals`, `in`, `matches`, `has_language`, `page_count` + `and`/`or`/`not`
- SkillPack (YAML): `apply_when` + `steps`/`disabled` pipeline filtering
- 3 built-in packs: pdp11, pdf-lit, math-book

### Plugin API (RFC 0010)
- Ed25519 keypair generation, signing, verification
- Guarded proxy with KRM/KG permission checks
- Plugin registry with manifest discovery

### Contract Testing
- RFC 0014: 21 idempotency tests (double-run → identical AST hash)
- RFC 0009: 4 bit-determinism tests (same input → same LaTeX)
- Fixes: BlockClassifier TOC guard, LLMRefinement skip guard, TitlePage dedup

### Vision Router
- Ollama vision model discovery across edge hosts
- Role-based routing (text/vision/table)
- Formula vision fallback via llava

### E2E Integration
- Synthetic PDP-11 document through full pipeline with skill pack
- 8 tests covering all major subsystems
- Regression baseline saved for future comparison

## Pipeline: 22 Analyzers
Normalization → ReadingOrder → Ephemera → Diagram → Heading → List → Formula → Theorem → Definition → Callout → Footnote → Bibliography → Algorithm → Index → TitlePage → Table → PageAgent → Caption → BlockClassifier → LLMRefinement → EntityExtractor → ProperNounExtractor → CitationLinker

## KRM_ENTITIES_MAP.md
Draft 0.4.0 → Release 1.0.0. All structural block types now have working detectors.

## Test Growth
- Start of week: ~230 tests
- End of week: 372 tests (+62%)

## COMPLIANCE_AUDIT.md
RFC 0001/0002/0005/0006/0007/0009/0010/0012/0014/0020/0021/0022 — all ✅
