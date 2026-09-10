"""Jupyter notebook source adapter and its output linking (RFC 0008 §3.4, §5.1)."""

import base64
import io
import json

import pytest

from src.adapters import create_default_registry
from src.adapters.base import SourceAdapterParseError
from src.adapters.notebook_adapter import NotebookSourceAdapter
from src.analyzers.notebook_outputs import NotebookOutputAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph
from src.krm.models import CodeBlock, ContainerUnit, FigureBlock, ParagraphBlock
from src.krm.traversal import walk

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")


def _notebook(cells, language="python") -> io.BytesIO:
    payload = {
        "cells": cells,
        "metadata": {"language_info": {"name": language}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _markdown_cell(source) -> dict:
    return {"cell_type": "markdown", "source": source, "metadata": {}}


def _code_cell(source, outputs=None, execution_count=1) -> dict:
    return {
        "cell_type": "code",
        "source": source,
        "outputs": outputs or [],
        "execution_count": execution_count,
        "metadata": {},
    }


def _parse(cells, language="python"):
    return NotebookSourceAdapter().parse(
        _notebook(cells, language), "file://analysis.ipynb"
    )


def _blocks(container: ContainerUnit):
    return [c for c in container.children if not isinstance(c, ContainerUnit)]


def test_markdown_cells_build_the_hierarchy() -> None:
    doc = _parse(
        [
            _markdown_cell(["# Signal analysis\n", "\n", "Intro paragraph.\n"]),
            _markdown_cell("## Setup"),
            _code_cell("import numpy as np"),
        ]
    )

    assert doc.title == "Signal analysis"
    root = doc.root_containers[0]
    assert root.title == "Signal analysis"
    setup = [c for c in root.children if isinstance(c, ContainerUnit)][0]
    assert setup.title == "Setup"
    assert isinstance(_blocks(setup)[0], CodeBlock)


def test_source_may_be_a_string_or_a_list_of_lines() -> None:
    from_list = _parse([_code_cell(["a = 1\n", "b = 2"])])
    from_string = _parse([_code_cell("a = 1\nb = 2")])

    assert _blocks(from_list.root_containers[0])[0].code_text == "a = 1\nb = 2"
    assert _blocks(from_string.root_containers[0])[0].code_text == "a = 1\nb = 2"


def test_code_cells_carry_the_kernel_language_and_execution_count() -> None:
    doc = _parse([_code_cell("print(1)", execution_count=7)], language="julia")

    code = _blocks(doc.root_containers[0])[0]
    assert code.programming_language == "julia"
    assert code.metadata["execution_count"] == 7
    assert doc.metadata["kernel_language"] == "julia"


def test_stream_output_becomes_a_block_tagged_with_its_cell() -> None:
    doc = _parse(
        [
            _code_cell(
                "print('hi')",
                outputs=[{"output_type": "stream", "name": "stdout", "text": ["hi\n"]}],
            )
        ]
    )

    code, output = _blocks(doc.root_containers[0])
    assert isinstance(output, CodeBlock)
    assert output.code_text == "hi"
    assert output.metadata["produced_by_cell_id"] == code.id
    assert output.metadata["output_type"] == "stream"


def test_image_output_becomes_a_figure() -> None:
    doc = _parse(
        [
            _code_cell(
                "plot()",
                outputs=[
                    {
                        "output_type": "display_data",
                        "data": {"image/png": _PNG, "text/plain": "<Figure>"},
                        "metadata": {},
                    }
                ],
            )
        ]
    )

    figure = _blocks(doc.root_containers[0])[1]
    assert isinstance(figure, FigureBlock)
    assert figure.mime_type == "image/png"
    assert figure.image_uri == f"data:image/png;base64,{_PNG}"
    assert figure.alt_text == "<Figure>"


def test_rich_result_falls_back_to_text_plain() -> None:
    """A DataFrame ships HTML and a repr; rendering the HTML would be interpretation."""
    doc = _parse(
        [
            _code_cell(
                "df",
                outputs=[
                    {
                        "output_type": "execute_result",
                        "data": {
                            "text/html": "<table><tr><td>1</td></tr></table>",
                            "text/plain": "   a\n0  1",
                        },
                        "execution_count": 1,
                    }
                ],
            )
        ]
    )

    result = _blocks(doc.root_containers[0])[1]
    assert isinstance(result, CodeBlock)
    assert result.code_text == "   a\n0  1"


def test_error_output_keeps_the_traceback() -> None:
    doc = _parse(
        [
            _code_cell(
                "1/0",
                outputs=[
                    {
                        "output_type": "error",
                        "ename": "ZeroDivisionError",
                        "evalue": "division by zero",
                        "traceback": ["Traceback...", "ZeroDivisionError"],
                    }
                ],
            )
        ]
    )

    error = _blocks(doc.root_containers[0])[1]
    assert "ZeroDivisionError" in error.code_text
    assert error.metadata["output_type"] == "error"


def test_empty_outputs_are_skipped() -> None:
    doc = _parse(
        [
            _code_cell(
                "x = 1",
                outputs=[
                    {"output_type": "stream", "text": ["  \n"]},
                    {"output_type": "display_data", "data": {}},
                ],
            )
        ]
    )

    assert len(_blocks(doc.root_containers[0])) == 1


def test_analyzer_links_outputs_to_their_cell() -> None:
    doc = _parse(
        [
            _code_cell(
                "print('hi')",
                outputs=[{"output_type": "stream", "text": ["hi\n"]}],
            )
        ]
    )
    kg = KnowledgeGraph()

    NotebookOutputAnalyzer().run(doc, ReadingGraph(), kg)

    code, output = _blocks(doc.root_containers[0])
    edges = kg.get_outgoing_edges(output.id)
    assert len(edges) == 1
    assert edges[0].target_id == code.id
    assert edges[0].relation_type is RelationType.CONCRETIZES


def test_analyzer_is_a_noop_for_other_sources() -> None:
    from src.krm.models import KnowledgeDocument

    doc = KnowledgeDocument(root_containers=[ContainerUnit(children=[ParagraphBlock()])])
    kg = KnowledgeGraph()

    NotebookOutputAnalyzer().run(doc, ReadingGraph(), kg)

    assert kg.to_json_dict()["edges"] == []


def test_analyzer_ignores_a_dangling_cell_reference() -> None:
    """A stale id must not create an edge into nothing (RFC 0003 §5.1)."""
    doc = _parse([_code_cell("x = 1", outputs=[{"output_type": "stream", "text": "out"}])])
    output = _blocks(doc.root_containers[0])[1]
    output.metadata["produced_by_cell_id"] = "not-a-real-node"
    kg = KnowledgeGraph()

    NotebookOutputAnalyzer().run(doc, ReadingGraph(), kg)

    assert kg.to_json_dict()["edges"] == []


def test_registry_routes_ipynb() -> None:
    adapter = create_default_registry().get_adapter_for_extension("ipynb")

    assert isinstance(adapter, NotebookSourceAdapter)


def test_source_digest_is_recorded() -> None:
    doc = _parse([_code_cell("x = 1")])

    assert len(doc.provenance_info.source_sha256) == 64
    assert doc.source_type == "notebook"


def test_invalid_json_raises_adapter_error() -> None:
    with pytest.raises(SourceAdapterParseError, match="not valid JSON"):
        NotebookSourceAdapter().parse(io.BytesIO(b"{nope"), "file://bad.ipynb")


def test_missing_cells_array_raises_adapter_error() -> None:
    with pytest.raises(SourceAdapterParseError, match="no 'cells' array"):
        NotebookSourceAdapter().parse(io.BytesIO(b'{"metadata": {}}'), "file://bad.ipynb")


def test_empty_notebook_still_has_one_root_container() -> None:
    doc = _parse([])

    assert len(doc.root_containers) == 1
    assert list(walk(doc))
