"""Retrieval eval and dataset endpoints (RFC 0018 §2, §3)."""

import pytest

pytest.importorskip("pyjobkit", reason="API app needs pyjobkit")

from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_retrieval_metrics_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/v1/eval/retrieval",
        json={"retrieved_ids": ["a", "b"], "relevant_ids": ["a"], "k": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recall_at_k"] == 1.0
    assert body["mrr_score"] == 1.0
    assert body["ndcg_score"] == pytest.approx(1.0)


def test_retrieval_endpoint_accepts_graded_relevance(client: TestClient) -> None:
    response = client.post(
        "/api/v1/eval/retrieval",
        json={
            "retrieved_ids": ["related", "exact"],
            "relevant_ids": {"exact": 3.0, "related": 1.0},
            "k": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["ndcg_score"] < 1.0


def test_dataset_endpoint_rejects_unknown_kind(client: TestClient) -> None:
    response = client.get("/api/v1/jobs/does-not-matter/dataset", params={"kind": "bogus"})

    assert response.status_code == 400


def test_dataset_endpoint_404s_for_unknown_job(client: TestClient) -> None:
    response = client.get("/api/v1/jobs/no-such-job/dataset")

    assert response.status_code == 404
