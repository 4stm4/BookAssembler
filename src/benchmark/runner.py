"""
Benchmark Suite Runner for Knowledge Assembly Engine (KAE).

Evaluates extraction results against Golden Truth datasets in corpus directories
and enforces regression thresholds according to RFC 0009 (docs/architecture/0009-benchmark.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, json, pathlib)
- Raises RegressionError on benchmark failures when strict=True
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.benchmark.metrics import compute_link_f1, compute_teds, compute_wer
from src.graph.knowledge_graph import KnowledgeGraph
from src.errors import ErrorCategory, KAEError
from src.krm.models import (
    BaseKRMNode,
    CodeBlock,
    ContainerUnit,
    DefinitionSpec,
    FigureBlock,
    FormulaBlock,
    InstructionSpec,
    KnowledgeDocument,
    MathInline,
    ParagraphBlock,
    TableBlock,
    TextLineInline,
    WarningSpec,
)


class RegressionError(KAEError):
    """
    Raised when benchmark metrics drop below strict regression thresholds.
    """
    category = ErrorCategory.QUALITY_REGRESSION


@dataclass
class BenchmarkReport:
    """
    Report containing quantitative quality metrics and pass/fail status for a document sample.
    """
    document_name: str
    teds_score: float
    wer_score: float
    link_f1_score: float
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)


def _extract_text_from_krm_node(node: BaseKRMNode) -> str:
    """
    Extracts plain text content from a KRM node.
    """
    if isinstance(node, ParagraphBlock):
        lines: List[str] = []
        for inline in node.inlines:
            if isinstance(inline, TextLineInline):
                line_str = "".join(span.text for span in inline.spans)
                if line_str:
                    lines.append(line_str)
            elif isinstance(inline, MathInline):
                if inline.latex_code:
                    lines.append(f"${inline.latex_code}$")
        return "\n".join(lines)

    elif isinstance(node, CodeBlock):
        return node.code_text

    elif isinstance(node, TableBlock):
        row_strings: List[str] = []
        for row in node.grid:
            cell_strings: List[str] = []
            for cell in row:
                cell_texts: List[str] = []
                for unit in cell.content:
                    cell_texts.append(_extract_text_from_krm_node(unit))
                cell_strings.append(" ".join(cell_texts).strip())
            row_strings.append(" | ".join(cell_strings))
        return "\n".join(row_strings)

    elif isinstance(node, FormulaBlock):
        return node.latex_expression

    elif isinstance(node, FigureBlock):
        return node.alt_text or ""

    elif isinstance(node, InstructionSpec):
        return f"{node.mnemonic_or_function} {' '.join(node.operands_or_arguments)}"

    elif isinstance(node, DefinitionSpec):
        return f"{node.term} {node.definition_text}"

    elif isinstance(node, WarningSpec):
        return node.message_text

    return ""


def _collect_container_text(container: ContainerUnit) -> List[str]:
    """
    Recursively collects all text from a ContainerUnit.
    """
    texts: List[str] = []
    if container.title:
        texts.append(container.title)
    for child in container.children:
        if isinstance(child, ContainerUnit):
            texts.extend(_collect_container_text(child))
        elif isinstance(child, BaseKRMNode):
            txt = _extract_text_from_krm_node(child)
            if txt:
                texts.append(txt)
    return texts


def _extract_full_text(doc: KnowledgeDocument) -> str:
    """
    Extracts full text from a KnowledgeDocument hierarchy.
    """
    all_texts: List[str] = []
    if doc.title:
        all_texts.append(doc.title)
    for root in doc.root_containers:
        all_texts.extend(_collect_container_text(root))
    return "\n\n".join(all_texts)


def _collect_container_tables(container: ContainerUnit) -> List[Dict[str, Any]]:
    """
    Recursively collects TableBlock structures from a ContainerUnit.
    """
    tables: List[Dict[str, Any]] = []
    for child in container.children:
        if isinstance(child, ContainerUnit):
            tables.extend(_collect_container_tables(child))
        elif isinstance(child, TableBlock):
            grid_data: List[List[str]] = []
            for row in child.grid:
                row_data: List[str] = []
                for cell in row:
                    cell_texts: List[str] = []
                    for u in cell.content:
                        txt = _extract_text_from_krm_node(u)
                        if txt:
                            cell_texts.append(txt)
                    row_data.append(" ".join(cell_texts))
                grid_data.append(row_data)
            tables.append({"grid": grid_data})
    return tables


def _extract_tables(doc: KnowledgeDocument) -> Dict[str, Any]:
    """
    Extracts table structure dictionary from a KnowledgeDocument.
    """
    tables: List[Dict[str, Any]] = []
    for root in doc.root_containers:
        tables.extend(_collect_container_tables(root))
    if not tables:
        return {}
    if len(tables) == 1:
        return tables[0]
    return {"tables": tables}


class BenchmarkRunner:
    """
    Runner for executing KAE quality benchmark suites against golden truth datasets.
    """

    def __init__(self, corpus_dir: Union[Path, str]) -> None:
        self._corpus_dir = Path(corpus_dir)

    def evaluate_sample(
        self,
        sample_dir: Union[Path, str],
        doc: KnowledgeDocument,
        kg: KnowledgeGraph,
    ) -> BenchmarkReport:
        """
        Evaluates extracted document and knowledge graph against expected files in sample_dir.
        """
        sample_path = Path(sample_dir)
        doc_name = sample_path.name
        expected_dir = sample_path / "expected" if (sample_path / "expected").is_dir() else sample_path

        # 1. Load Expected Text
        expected_text = ""
        text_file_candidates = [
            expected_dir / "expected_text.txt",
            expected_dir / "text.txt",
            expected_dir / "expected_text.json",
        ]
        for candidate in text_file_candidates:
            if candidate.is_file():
                if candidate.suffix == ".json":
                    try:
                        with open(candidate, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, dict):
                                expected_text = str(data.get("text") or data.get("text_content") or "")
                            elif isinstance(data, str):
                                expected_text = data
                    except Exception:
                        pass
                else:
                    try:
                        expected_text = candidate.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass
                break

        # 2. Load Expected Table
        expected_table: Dict[str, Any] = {}
        table_file_candidates = [
            expected_dir / "expected_table.json",
            expected_dir / "table.json",
            expected_dir / "tables.json",
        ]
        for candidate in table_file_candidates:
            if candidate.is_file():
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            expected_table = data
                except Exception:
                    pass
                break

        # 3. Load Expected Graph Edges
        expected_edges: List[Dict[str, Any]] = []
        kg_file_candidates = [
            expected_dir / "knowledge_graph.json",
            expected_dir / "expected_kg.json",
            expected_dir / "graph.json",
        ]
        for candidate in kg_file_candidates:
            if candidate.is_file():
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "edges" in data and isinstance(data["edges"], list):
                            expected_edges = data["edges"]
                        elif isinstance(data, list):
                            expected_edges = data
                except Exception:
                    pass
                break

        # 4. Extract Actual Text, Tables, and Edges
        extracted_text = _extract_full_text(doc)
        extracted_table = _extract_tables(doc)
        kg_dict = kg.to_json_dict()
        extracted_edges: List[Dict[str, Any]] = kg_dict.get("edges", [])

        # 5. Compute Metrics
        wer_score = compute_wer(expected_text, extracted_text) if expected_text else 0.0

        if expected_table:
            teds_score = compute_teds(expected_table, extracted_table)
        else:
            teds_score = 1.0

        link_metrics = compute_link_f1(expected_edges, extracted_edges)
        link_f1_score = link_metrics["f1"]

        # 6. Check Pass / Fail Status against strict thresholds
        # TEDS >= 0.95, Link F1 >= 0.90, WER <= 0.05
        passed = (teds_score >= 0.95) and (link_f1_score >= 0.90) and (wer_score <= 0.05)

        details: Dict[str, Any] = {
            "sample_dir": str(sample_path),
            "precision": link_metrics["precision"],
            "recall": link_metrics["recall"],
            "extracted_word_count": len(extracted_text.split()),
            "expected_word_count": len(expected_text.split()),
            "extracted_edges_count": len(extracted_edges),
            "expected_edges_count": len(expected_edges),
        }

        return BenchmarkReport(
            document_name=doc_name,
            teds_score=teds_score,
            wer_score=wer_score,
            link_f1_score=link_f1_score,
            passed=passed,
            details=details,
        )

    def run_suite(
        self,
        samples_map: Dict[str, Tuple[KnowledgeDocument, KnowledgeGraph]],
        strict: bool = False,
    ) -> List[BenchmarkReport]:
        """
        Runs benchmark suite over samples in samples_map.
        If strict=True, raises RegressionError if any report fails regression thresholds.
        """
        reports: List[BenchmarkReport] = []
        for sample_name, (doc, kg) in samples_map.items():
            sample_path = self._corpus_dir / sample_name
            report = self.evaluate_sample(sample_path, doc, kg)
            reports.append(report)

        if strict:
            failed_reports = [r for r in reports if not r.passed]
            if failed_reports:
                failed_names = ", ".join(r.document_name for r in failed_reports)
                raise RegressionError(
                    f"Benchmark strict regression check failed for {len(failed_reports)} sample(s): {failed_names}"
                )

        return reports


def build_sample(sample_dir: Path) -> Tuple[KnowledgeDocument, KnowledgeGraph]:
    """
    Runs the default pipeline over a corpus sample's input file (RFC 0009 §4).
    """
    from src.adapters import create_default_registry
    from src.analyzers import create_default_pipeline
    from src.analyzers.pipeline import PipelineRunner
    from src.graph.reading_graph import ReadingGraph

    inputs = sorted(p for p in sample_dir.glob("input.*") if p.is_file())
    if not inputs:
        raise FileNotFoundError(f"No input.* file in corpus sample {sample_dir}")

    source = inputs[0]
    adapter = create_default_registry().get_adapter_for_extension(source.suffix)
    if adapter is None:
        raise ValueError(f"No adapter registered for {source.name}")

    with open(source, "rb") as handle:
        doc = adapter.parse(handle, f"file://{source}")

    rg, kg = ReadingGraph(), KnowledgeGraph()
    PipelineRunner(create_default_pipeline()).execute(doc, rg, kg)
    return doc, kg


def main(argv: Optional[List[str]] = None) -> int:
    """
    CLI entry point: `python -m src.benchmark.runner --corpus-dir ... --strict-regression-check`
    (RFC 0009 §4). Returns a non-zero exit code on regression so CI can block a merge.
    """
    import argparse

    parser = argparse.ArgumentParser(description="KAE quality benchmark suite (RFC 0009)")
    parser.add_argument("--corpus-dir", required=True, help="Directory of corpus samples")
    parser.add_argument("--report-out", help="Write the JSON report here")
    parser.add_argument(
        "--strict-regression-check",
        action="store_true",
        help="Exit non-zero when a sample misses the RFC 0009 §5 thresholds",
    )
    args = parser.parse_args(argv)

    corpus_dir = Path(args.corpus_dir)
    samples = sorted(p for p in corpus_dir.iterdir() if p.is_dir()) if corpus_dir.is_dir() else []
    if not samples:
        print(f"No corpus samples under {corpus_dir}")
        return 1

    runner = BenchmarkRunner(corpus_dir)
    reports: List[BenchmarkReport] = []
    for sample in samples:
        doc, kg = build_sample(sample)
        reports.append(runner.evaluate_sample(sample, doc, kg))

    payload = [
        {
            "document_name": r.document_name,
            "teds_score": r.teds_score,
            "wer_score": r.wer_score,
            "link_f1_score": r.link_f1_score,
            "passed": r.passed,
        }
        for r in reports
    ]
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.report_out:
        Path(args.report_out).write_text(rendered, encoding="utf-8")
    print(rendered)

    failed = [r for r in reports if not r.passed]
    if failed and args.strict_regression_check:
        print(f"REGRESSION: {len(failed)} sample(s) below threshold")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
