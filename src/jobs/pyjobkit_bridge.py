"""
PyJobKit Bridge Module for Knowledge Assembly Engine (KAE).

Integrates pyjobkit background task execution engine with FastAPI SSE and WebSocket endpoints.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Reactive event streaming for job_started, job_progress, job_completed, job_failed
- Worker lifecycle management
"""

import asyncio
from datetime import datetime, timezone
import json
from typing import Any, AsyncGenerator, Callable, Coroutine, Dict, List, Optional, Set
from uuid import UUID

from pyjobkit import Engine, ExecContext, Executor, MemoryBackend, Worker
from pyjobkit.events import LocalEventBus


JobHandlerCallable = Callable[[str, Dict[str, Any], ExecContext], Coroutine[Any, Any, Dict[str, Any]]]


class KAEGenericExecutor(Executor):
    """
    Generic PyJobKit Executor wrapper for KAE tasks.
    """

    def __init__(self, kind_name: str, bridge: "PyJobKitBridge") -> None:
        self.kind = kind_name
        self.bridge = bridge

    async def run(self, *, job_id: UUID, payload: dict[str, Any], ctx: ExecContext) -> dict[str, Any]:
        str_id = str(job_id)

        # Notify job_started
        await self.bridge.publish_event({
            "event": "job_started",
            "job_id": str_id,
            "job_type": self.kind,
            "payload": payload,
            "progress": 0.0,
            "status": "RUNNING",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

        try:
            handler = self.bridge.get_handler(self.kind)
            if handler is not None:
                result = await handler(str_id, payload, ctx)
            else:
                # Default background processing behavior
                await ctx.set_progress(0.5, message=f"Processing {self.kind} job...")
                await asyncio.sleep(0.05)
                await ctx.set_progress(1.0, message="Job execution finished")
                result = {"status": "SUCCESS", "job_id": str_id, "kind": self.kind, "payload": payload}

            # Notify job_completed
            await self.bridge.publish_event({
                "event": "job_completed",
                "job_id": str_id,
                "job_type": self.kind,
                "payload": payload,
                "progress": 1.0,
                "status": "COMPLETED",
                "result": result,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })
            return result

        except Exception as exc:
            # Notify job_failed
            await self.bridge.publish_event({
                "event": "job_failed",
                "job_id": str_id,
                "job_type": self.kind,
                "payload": payload,
                "progress": 0.0,
                "status": "FAILED",
                "error": str(exc),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })
            raise


class PyJobKitBridge:
    """
    Reactive Bridge connecting PyJobKit background worker engine to FastAPI REST/SSE/WS endpoints.
    """

    def __init__(self) -> None:
        self.event_bus = LocalEventBus()
        self.backend = MemoryBackend()
        self.engine = Engine(
            backend=self.backend,
            executors=[],
            event_bus=self.event_bus,
        )
        self.worker = Worker(self.engine, poll_interval=0.01)
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._handlers: Dict[str, JobHandlerCallable] = {}

        # Event queues for global stream (SSE) and specific job streams (WS)
        self._global_listeners: Set[asyncio.Queue[Dict[str, Any]]] = set()
        self._job_listeners: Dict[str, Set[asyncio.Queue[Dict[str, Any]]]] = {}

    def start_worker(self) -> None:
        """
        Starts background PyJobKit worker if not already running.
        """
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self.worker.run())

    async def stop_worker(self) -> None:
        """
        Stops background PyJobKit worker cleanly.
        """
        if self.worker is not None:
            self.worker.request_stop()
            if self._worker_task is not None:
                await self._worker_task
                self._worker_task = None

    def register_handler(self, job_type: str, handler: JobHandlerCallable) -> None:
        """
        Registers a custom handler function for a job_type.
        """
        self._handlers[job_type] = handler

    def get_handler(self, job_type: str) -> Optional[JobHandlerCallable]:
        """
        Gets registered handler for job_type if available.
        """
        return self._handlers.get(job_type)

    async def submit_kae_job(
        self,
        job_type: str,
        payload: Dict[str, Any],
    ) -> str:
        """
        Enqueues a job into PyJobKit engine and returns assigned job_id.
        """
        self.start_worker()

        # Ensure executor is registered for this job_type
        if self.engine.executor_for(job_type) is None:
            executor = KAEGenericExecutor(kind_name=job_type, bridge=self)
            self.engine.register_executor(executor)

        job_uuid = await self.engine.enqueue(kind=job_type, payload=payload)
        str_id = str(job_uuid)

        # Subscribe to PyJobKit progress topic for this job_id
        async def on_progress(event_payload: Dict[str, Any]) -> None:
            val = float(event_payload.get("value", 0.0))
            await self.publish_event({
                "event": "job_progress",
                "job_id": str_id,
                "job_type": job_type,
                "payload": payload,
                "progress": val,
                "status": "RUNNING",
                "data": event_payload,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })

        self.event_bus.subscribe(f"job.{str_id}.progress", on_progress)

        return str_id

    async def publish_event(self, event: Dict[str, Any]) -> None:
        """
        Broadcasting hook that sends job event to SSE global stream and specific WS job streams.
        """
        # Broadcast to all SSE listeners
        for queue in list(self._global_listeners):
            await queue.put(event)

        # Broadcast to specific job WS listeners
        job_id = str(event.get("job_id", ""))
        if job_id in self._job_listeners:
            for queue in list(self._job_listeners[job_id]):
                await queue.put(event)

    def subscribe_global_events(self) -> asyncio.Queue[Dict[str, Any]]:
        """
        Subscribes a new queue to all job events (used by SSE /api/v1/jobs/stream).
        """
        q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._global_listeners.add(q)
        return q

    def unsubscribe_global_events(self, q: asyncio.Queue[Dict[str, Any]]) -> None:
        """
        Unsubscribes a queue from global event stream.
        """
        self._global_listeners.discard(q)

    def subscribe_job_events(self, job_id: str) -> asyncio.Queue[Dict[str, Any]]:
        """
        Subscribes a new queue to events for a specific job_id (used by WS /api/v1/ws/jobs/{job_id}).
        """
        q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        if job_id not in self._job_listeners:
            self._job_listeners[job_id] = set()
        self._job_listeners[job_id].add(q)
        return q

    def unsubscribe_job_events(self, job_id: str, q: asyncio.Queue[Dict[str, Any]]) -> None:
        """
        Unsubscribes a queue from specific job event stream.
        """
        if job_id in self._job_listeners:
            self._job_listeners[job_id].discard(q)
            if not self._job_listeners[job_id]:
                del self._job_listeners[job_id]

    async def get_job_info(self, job_id: str) -> Dict[str, Any]:
        """
        Retrieves job status and record from PyJobKit engine.
        """
        try:
            raw_rec = await self.engine.get(UUID(job_id))
            return dict(raw_rec)
        except (KeyError, ValueError):
            return {}
