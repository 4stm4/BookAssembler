"""Tests for pipeline stage contracts and pyjobkit integration."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestValidateNoTranslations(unittest.TestCase):
    """validate must error when no translations exist."""

    def test_validate_raises_when_no_translations(self):
        from pipeline import stage_validate
        with self.assertRaises(RuntimeError, msg="Нет переводов"):
            stage_validate(99, 9000, 9010)

    def test_count_translated_pages_empty(self):
        from pipeline import _count_translated_pages
        self.assertEqual(_count_translated_pages(99, 9000, 9010), 0)


class TestCompileRaises(unittest.TestCase):
    """compile must raise RuntimeError on docker/ssh failure."""

    @patch("pipeline.run_cmd")
    def test_docker_compile_raises_on_failure(self, mock_cmd):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "! LaTeX Error: File not found."
        mock_cmd.return_value = mock_result

        from pipeline import _compile_docker
        with self.assertRaises(RuntimeError):
            _compile_docker(99)

    def test_ssh_compile_raises_without_config(self):
        from pipeline import _compile_ssh
        with patch.dict(os.environ, {"COMPILE_HOST": "", "COMPILE_DIR": ""}):
            with self.assertRaises(RuntimeError):
                _compile_ssh(99)


class TestAgentModeTranslate(unittest.TestCase):
    """translate in agent mode must not mark done when no translations produced."""

    def test_agent_pending_exception_exists(self):
        from pipeline import _AgentModePending
        self.assertTrue(issubclass(_AgentModePending, RuntimeError))


class TestStageAgentsNoInput(unittest.TestCase):
    """stage_agents must handle missing tasks file gracefully."""

    def test_no_tasks_file(self):
        from pipeline import stage_agents
        stage_agents(99, 9000, 9010)

    def test_empty_tasks(self):
        from pipeline import stage_agents
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([], f)
            f.flush()
            try:
                with patch("pipeline.os.path.exists", return_value=True), \
                     patch("builtins.open", unittest.mock.mock_open(read_data="[]")):
                    stage_agents(99, 9000, 9010)
            finally:
                os.unlink(f.name)


class TestCompileContract(unittest.TestCase):
    """compile contract must check for PDF output."""

    def test_compile_contract_has_output(self):
        from state import CONTRACTS
        self.assertIn("ch{ch}_compiled.pdf", CONTRACTS["compile"]["outputs"])


class TestIdempotencyEnqueue(unittest.TestCase):
    """Repeated enqueue with same key returns None instead of crashing."""

    def test_double_enqueue_returns_none(self):
        from jobs import create_engine, enqueue_translate

        async def _test():
            with tempfile.TemporaryDirectory() as td:
                db = os.path.join(td, "test.sqlite3")
                with patch.dict(os.environ, {"BOOKASSEMBLER_JOB_DSN": f"sqlite+aiosqlite:///{db}"}):
                    engine = await create_engine()
                    async with engine:
                        first = await enqueue_translate(engine, 99, 9000, 9010)
                        self.assertIsNotNone(first)
                        second = await enqueue_translate(engine, 99, 9000, 9010)
                        self.assertIsNone(second)

        asyncio.run(_test())


class TestWorkerExitCode(unittest.TestCase):
    """run_worker(once=True) returns nonzero when jobs fail."""

    @unittest.skipIf(
        not os.environ.get("RUN_SLOW_TESTS"),
        "Slow test (1.1s sleep for SQLite workaround); set RUN_SLOW_TESTS=1",
    )
    def test_worker_returns_nonzero_on_failure(self):
        from jobs import create_engine, run_worker, _safe_enqueue

        async def _test():
            with tempfile.TemporaryDirectory() as td:
                db = os.path.join(td, "test.sqlite3")
                with patch.dict(os.environ, {"BOOKASSEMBLER_JOB_DSN": f"sqlite+aiosqlite:///{db}"}):
                    engine = await create_engine()
                    async with engine:
                        await _safe_enqueue(
                            engine,
                            kind="translate-batch",
                            payload={"chapter": 99, "start": 9000, "end": 9010},
                            idempotency_key="ch99:translate:9000-9010",
                        )
                    code = await run_worker(once=True)
                    self.assertNotEqual(code, 0)

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
