"""RFC 0009 bit-determinism: same input → same LaTeX output."""
import hashlib

import pytest

from src.assembler.latex_builder import build_latex
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _make_doc() -> KnowledgeDocument:
    span = StyledTextSpan(text="Hello world")
    inline = TextLineInline(spans=[span])
    p = ParagraphBlock(inlines=[inline])
    container = ContainerUnit(title="Chapter 1", level=1, children=[p])
    return KnowledgeDocument(title="Determinism Test", root_containers=[container])


class TestBitDeterminism:
    def test_latex_same_output(self):
        doc1 = _make_doc()
        doc2 = _make_doc()
        tex1 = build_latex(doc1)
        tex2 = build_latex(doc2)
        assert tex1 == tex2

    def test_latex_hash_stable(self):
        doc = _make_doc()
        h1 = hashlib.sha256(build_latex(doc).encode()).hexdigest()
        h2 = hashlib.sha256(build_latex(doc).encode()).hexdigest()
        assert h1 == h2

    def test_translated_determinism(self):
        doc1 = _make_doc()
        doc2 = _make_doc()
        tex1 = build_latex(doc1, target_lang="ru")
        tex2 = build_latex(doc2, target_lang="ru")
        assert tex1 == tex2

    def test_multiple_containers(self):
        docs = []
        for _ in range(3):
            span1 = StyledTextSpan(text="First paragraph")
            span2 = StyledTextSpan(text="Second paragraph")
            p1 = ParagraphBlock(inlines=[TextLineInline(spans=[span1])])
            p2 = ParagraphBlock(inlines=[TextLineInline(spans=[span2])])
            c = ContainerUnit(title="Ch", level=1, children=[p1, p2])
            docs.append(KnowledgeDocument(title="Multi", root_containers=[c]))
        texes = [build_latex(d) for d in docs]
        assert texes[0] == texes[1] == texes[2]
