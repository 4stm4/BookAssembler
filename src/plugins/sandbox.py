"""Out-of-process plugin sandbox (RFC 0010 §4.2).

Third-party plugin code never runs inside the KAE process. It executes in a spawned
child with a memory cap and — unless the manifest grants it — no network, and talks
back only through a Mutation Delta (RFC 0010 §5). A plugin that crashes, hangs, or
exhausts its memory budget takes down only its own process (§6.2).
"""

import importlib
import logging
import multiprocessing
import traceback
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from src.plugins.manifest import PluginPermissions

log = logging.getLogger(__name__)

_KILL_GRACE_SECONDS = 1.0


class PluginExecutionError(Exception):
    """Raised when sandboxed plugin execution fails, times out, or is killed."""


class PluginSandboxRunner(ABC):
    """Interface for plugin execution isolation (RFC 0010 §4.2)."""

    @abstractmethod
    def run_analyzer_sandboxed(
        self,
        plugin_id: str,
        analyzer_class: str,
        doc_state: Dict[str, Any],
        timeout_sec: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run a plugin analyzer in isolation and return its Mutation Delta."""


class SubprocessSandboxRunner(PluginSandboxRunner):
    """Sandbox backed by a spawned child process with rlimit and network guards."""

    def __init__(self, permissions: PluginPermissions) -> None:
        self._permissions = permissions

    def run_analyzer_sandboxed(
        self,
        plugin_id: str,
        analyzer_class: str,
        doc_state: Dict[str, Any],
        timeout_sec: Optional[int] = None,
    ) -> Dict[str, Any]:
        timeout = timeout_sec or self._permissions.timeout_seconds
        ctx = multiprocessing.get_context("spawn")
        receiver, sender = ctx.Pipe(duplex=False)
        process = ctx.Process(
            target=_sandbox_main,
            args=(
                sender,
                analyzer_class,
                doc_state,
                self._permissions.max_memory_mb,
                self._permissions.allow_network,
            ),
            daemon=True,
        )

        process.start()
        sender.close()
        try:
            if not receiver.poll(timeout):
                raise PluginExecutionError(
                    f"Plugin {plugin_id} exceeded its timeout of {timeout}s"
                )
            try:
                payload = receiver.recv()
            except EOFError:
                payload = None
        finally:
            receiver.close()
            _terminate(process)

        if payload is None:
            raise PluginExecutionError(
                f"Plugin {plugin_id} died without returning a result "
                f"(exit code {process.exitcode})"
            )
        if not payload.get("ok"):
            raise PluginExecutionError(
                f"Plugin {plugin_id} failed: {payload.get('error')}"
            )

        delta = payload.get("delta")
        if not isinstance(delta, dict):
            raise PluginExecutionError(
                f"Plugin {plugin_id} did not return a Mutation Delta object"
            )
        delta.setdefault("plugin_id", plugin_id)
        return delta


def _terminate(process: Any) -> None:
    if process.is_alive():
        process.kill()
    process.join(_KILL_GRACE_SECONDS)


def _sandbox_main(
    sender: Any,
    analyzer_class: str,
    doc_state: Dict[str, Any],
    max_memory_mb: int,
    allow_network: bool,
) -> None:
    """Child-process entry point. Must stay importable at module level for spawn."""
    try:
        _apply_memory_limit(max_memory_mb)
        if not allow_network:
            _block_network()

        module_path, _, class_name = analyzer_class.rpartition(".")
        if not module_path:
            raise ValueError(f"Entry point is not a dotted path: {analyzer_class!r}")
        plugin_cls = getattr(importlib.import_module(module_path), class_name)

        sender.send({"ok": True, "delta": plugin_cls().run_sandboxed(doc_state)})
    except BaseException as exc:  # MemoryError and SystemExit must reach the parent too
        try:
            sender.send(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            )
        except Exception:
            pass
    finally:
        sender.close()


def _apply_memory_limit(max_memory_mb: int) -> None:
    if max_memory_mb <= 0:
        return
    try:
        import resource
    except ImportError:  # non-POSIX: the timeout and process boundary still apply
        log.warning("resource module unavailable; plugin memory cap not enforced")
        return
    limit = max_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def _block_network() -> None:
    import socket

    def _denied(*_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError("Plugin manifest does not grant network access")

    socket.socket = _denied  # type: ignore[misc,assignment]
    socket.create_connection = _denied  # type: ignore[assignment]
