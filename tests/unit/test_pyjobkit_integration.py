"""
Unit tests for PyJobKit integration layer with KAE and FastAPI REST/SSE/WS endpoints.

Tests:
1. Job submission to PyJobKit via PyJobKitBridge.
2. Custom job handler registration and progress reporting.
3. FastAPI SSE stream endpoint (/api/v1/jobs/stream).
4. FastAPI WebSocket endpoint (/api/v1/ws/jobs/{job_id}).
"""

import asyncio
from typing import Any, Dict, List

from pyjobkit import ExecContext
from src.api.app import create_app
from src.jobs.pyjobkit_bridge import KAEGenericExecutor, PyJobKitBridge


def test_submit_kae_job_lifecycle() -> None:
    """
    Tests submitting a job to pyjobkit via PyJobKitBridge and verifying lifecycle events.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    bridge = PyJobKitBridge()

    # Custom handler for document processing
    async def custom_doc_handler(
        job_id: str,
        payload: Dict[str, Any],
        ctx: ExecContext,
    ) -> Dict[str, Any]:
        await ctx.set_progress(0.5, message="Parsing KRM structure...")
        await asyncio.sleep(0.01)
        await ctx.set_progress(1.0, message="Knowledge Assembly Complete")
        return {"processed_nodes": 42, "status": "SUCCESS"}

    bridge.register_handler("krm_processing", custom_doc_handler)

    events_captured: List[Dict[str, Any]] = []

    async def run_test() -> None:
        queue = bridge.subscribe_global_events()

        job_id = await bridge.submit_kae_job(
            job_type="krm_processing",
            payload={"document_uri": "s3://bucket/doc.pdf"},
        )
        assert job_id is not None
        assert isinstance(job_id, str)

        # Wait for events to process
        while len(events_captured) < 4:
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=1.5)
                events_captured.append(evt)
                if evt.get("event") in ("job_completed", "job_failed"):
                    break
            except asyncio.TimeoutError:
                break

        bridge.unsubscribe_global_events(queue)
        await bridge.stop_worker()

    loop.run_until_complete(run_test())
    loop.close()

    assert len(events_captured) >= 3
    event_names = [e["event"] for e in events_captured]
    assert "job_started" in event_names
    assert "job_progress" in event_names
    assert "job_completed" in event_names


def test_fastapi_sse_stream_endpoint() -> None:
    """
    Tests SSE endpoint registration and PyJobKitBridge event stream queue logic.
    """
    app = create_app()
    bridge: PyJobKitBridge = app.state.pyjobkit_bridge

    # Check SSE endpoint is registered on FastAPI app
    routes = [route.path for route in app.routes if hasattr(route, "path")]
    assert "/api/v1/jobs/stream" in routes

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_sse_test() -> None:
        queue = bridge.subscribe_global_events()

        job_id = await bridge.submit_kae_job(
            job_type="graph_generation",
            payload={"graph_type": "KNOWLEDGE_GRAPH"},
        )

        event = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert event["job_id"] == job_id
        assert event["event"] == "job_started"

        bridge.unsubscribe_global_events(queue)
        await bridge.stop_worker()

    loop.run_until_complete(run_sse_test())
    loop.close()


def test_fastapi_websocket_endpoint_tracking() -> None:
    """
    Tests WebSocket endpoint registration and job-specific PyJobKit event subscription.
    """
    app = create_app()
    bridge: PyJobKitBridge = app.state.pyjobkit_bridge

    # Check WS endpoint is registered on FastAPI app
    routes = [route.path for route in app.routes if hasattr(route, "path")]
    assert "/api/v1/ws/jobs/{job_id}" in routes

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_ws_test() -> None:
        job_id = "test_ws_job_456"
        job_queue = bridge.subscribe_job_events(job_id)

        await bridge.publish_event({
            "event": "job_started",
            "job_id": job_id,
            "job_type": "test_type",
            "progress": 0.0,
        })

        evt = await asyncio.wait_for(job_queue.get(), timeout=1.0)
        assert evt["job_id"] == job_id
        assert evt["event"] == "job_started"

        bridge.unsubscribe_job_events(job_id, job_queue)
        await bridge.stop_worker()

    loop.run_until_complete(run_ws_test())
    loop.close()


if __name__ == "__main__":
    test_submit_kae_job_lifecycle()
    test_fastapi_sse_stream_endpoint()
    test_fastapi_websocket_endpoint_tracking()
    print("ALL PYJOBKIT INTEGRATION TESTS PASSED PERFECTLY!")
