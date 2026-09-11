"""The TOC bench as a test (RFC 0009): every corpus book reads one to one.

The books are not in the repository, so this runs only when told where they
are:

  KAE_TOC_BOOKS=/books pytest tests/integration/test_toc_bench.py

See benchmark/toc/README.md.
"""
import os

import pytest

pytest.importorskip("pymupdf")
from benchmark.toc import bench  # noqa: E402

BOOKS = os.environ.get("KAE_TOC_BOOKS")

pytestmark = pytest.mark.skipif(
    not BOOKS, reason="KAE_TOC_BOOKS is not set: the bench books are not in the repository")


@pytest.mark.parametrize("book", sorted(bench.load_corpus()))
def test_the_contents_read_one_to_one(book):
    r = bench.run_book(book, BOOKS)
    assert r.exact, r.report()


def test_every_corpus_book_has_ground_truth():
    for book in bench.load_corpus():
        assert bench.load_gt(book), book
