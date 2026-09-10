"""Tests for Skills DSL evaluator (RFC 0006)."""
import pytest

from src.skills.dsl import DSLContext, DSLError, evaluate


def _ctx(**kwargs):
    return DSLContext(**kwargs)


class TestContains:
    def test_title_contains(self):
        ctx = _ctx(title="PDP-11 Handbook")
        assert evaluate("contains(title, 'PDP')", ctx)

    def test_title_not_contains(self):
        ctx = _ctx(title="Intel Manual")
        assert not evaluate("contains(title, 'PDP')", ctx)

    def test_case_insensitive(self):
        ctx = _ctx(title="pdp-11 handbook")
        assert evaluate("contains(title, 'PDP')", ctx)


class TestEquals:
    def test_exact_match(self):
        ctx = _ctx(title="Test")
        assert evaluate("equals(title, 'Test')", ctx)

    def test_no_match(self):
        ctx = _ctx(title="Other")
        assert not evaluate("equals(title, 'Test')", ctx)


class TestIn:
    def test_in_list(self):
        ctx = _ctx(languages=["russian", "english"])
        assert evaluate("in('russian', languages)", ctx)

    def test_not_in_list(self):
        ctx = _ctx(languages=["english"])
        assert not evaluate("in('russian', languages)", ctx)


class TestMatches:
    def test_regex_match(self):
        ctx = _ctx(title="PDP-11/70 Manual")
        assert evaluate(r"matches(title, 'PDP-\d+/\d+')", ctx)

    def test_regex_no_match(self):
        ctx = _ctx(title="Intel Manual")
        assert not evaluate(r"matches(title, 'PDP-\d+')", ctx)


class TestPageCount:
    def test_greater(self):
        ctx = _ctx(page_count=50)
        assert evaluate("page_count > 10", ctx)

    def test_not_greater(self):
        ctx = _ctx(page_count=5)
        assert not evaluate("page_count > 10", ctx)

    def test_gte(self):
        ctx = _ctx(page_count=10)
        assert evaluate("page_count >= 10", ctx)

    def test_lt(self):
        ctx = _ctx(page_count=5)
        assert evaluate("page_count < 10", ctx)

    def test_eq(self):
        ctx = _ctx(page_count=10)
        assert evaluate("page_count == 10", ctx)


class TestHasLanguage:
    def test_has(self):
        ctx = _ctx(languages=["russian", "english"])
        assert evaluate("has_language('russian')", ctx)

    def test_missing(self):
        ctx = _ctx(languages=["english"])
        assert not evaluate("has_language('russian')", ctx)

    def test_case_insensitive(self):
        ctx = _ctx(languages=["Russian"])
        assert evaluate("has_language('russian')", ctx)


class TestCombinators:
    def test_and_true(self):
        ctx = _ctx(title="PDP", page_count=50)
        assert evaluate("contains(title, 'PDP') and page_count > 10", ctx)

    def test_and_false(self):
        ctx = _ctx(title="PDP", page_count=5)
        assert not evaluate("contains(title, 'PDP') and page_count > 10", ctx)

    def test_or_true(self):
        ctx = _ctx(title="Intel")
        assert evaluate("contains(title, 'PDP') or contains(title, 'Intel')", ctx)

    def test_or_false(self):
        ctx = _ctx(title="Other")
        assert not evaluate("contains(title, 'PDP') or contains(title, 'Intel')", ctx)

    def test_not(self):
        ctx = _ctx(title="Intel")
        assert evaluate("not contains(title, 'PDP')", ctx)

    def test_not_false(self):
        ctx = _ctx(title="PDP-11")
        assert not evaluate("not contains(title, 'PDP')", ctx)

    def test_complex(self):
        ctx = _ctx(title="PDP-11", page_count=50, languages=["russian"])
        assert evaluate(
            "contains(title, 'PDP') and (page_count > 10 or has_language('english'))",
            ctx,
        )

    def test_nested_parens(self):
        ctx = _ctx(title="Test", page_count=5)
        assert evaluate("(page_count > 3) and (page_count < 10)", ctx)


class TestLiterals:
    def test_true(self):
        assert evaluate("true", _ctx())

    def test_false(self):
        assert not evaluate("false", _ctx())
