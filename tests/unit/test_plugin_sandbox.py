"""Out-of-process plugin sandbox tests (RFC 0010 §4.2, §6.2)."""

import os

import pytest

from src.plugins.manifest import PluginPermissions
from src.plugins.sandbox import PluginExecutionError, SubprocessSandboxRunner

_FIXTURES = "tests.fixtures.sample_plugins"


def _runner(**overrides) -> SubprocessSandboxRunner:
    permissions = PluginPermissions(
        krm_permissions=["READ"],
        kg_permissions=["READ", "MUTATE_ENTITIES"],
        allow_network=overrides.get("allow_network", False),
        max_memory_mb=overrides.get("max_memory_mb", 512),
        timeout_seconds=overrides.get("timeout_seconds", 30),
    )
    return SubprocessSandboxRunner(permissions)


def test_sandbox_returns_mutation_delta() -> None:
    delta = _runner().run_analyzer_sandboxed(
        "plugin.test.echo", f"{_FIXTURES}.EchoPlugin", {"title": "PDP-11"}
    )

    assert delta["plugin_id"] == "plugin.test.echo"
    assert delta["applied_mutations"][0]["entity"]["name"] == "PDP-11"


def test_plugin_exception_does_not_reach_core() -> None:
    with pytest.raises(PluginExecutionError, match="plugin blew up"):
        _runner().run_analyzer_sandboxed(
            "plugin.test.raising", f"{_FIXTURES}.RaisingPlugin", {}
        )

    assert os.getpid() == os.getpid()


def test_hard_crash_is_isolated() -> None:
    """A plugin dying like a segfault leaves the core alive with a clean error."""
    with pytest.raises(PluginExecutionError, match="without returning a result"):
        _runner().run_analyzer_sandboxed(
            "plugin.test.crash", f"{_FIXTURES}.CrashingPlugin", {}
        )


def test_timeout_kills_the_plugin() -> None:
    with pytest.raises(PluginExecutionError, match="timeout"):
        _runner(timeout_seconds=1).run_analyzer_sandboxed(
            "plugin.test.hang", f"{_FIXTURES}.HangingPlugin", {}
        )


def test_memory_cap_is_enforced() -> None:
    with pytest.raises(PluginExecutionError):
        _runner(max_memory_mb=256).run_analyzer_sandboxed(
            "plugin.test.hog", f"{_FIXTURES}.MemoryHogPlugin", {}
        )


def test_network_blocked_unless_manifest_grants_it() -> None:
    with pytest.raises(PluginExecutionError, match="network access"):
        _runner(allow_network=False).run_analyzer_sandboxed(
            "plugin.test.net", f"{_FIXTURES}.NetworkPlugin", {}
        )


def test_non_delta_result_is_rejected() -> None:
    with pytest.raises(PluginExecutionError, match="Mutation Delta"):
        _runner().run_analyzer_sandboxed(
            "plugin.test.bad", f"{_FIXTURES}.NotADeltaPlugin", {}
        )


def test_unknown_entry_point_is_rejected() -> None:
    with pytest.raises(PluginExecutionError):
        _runner().run_analyzer_sandboxed(
            "plugin.test.missing", f"{_FIXTURES}.NoSuchPlugin", {}
        )
