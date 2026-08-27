"""
OllamaEmbeddingRetriever — offline retrieval evaluation using ollama embeddings.

Embeds queries and corpus chunks via ollama /api/embeddings, computes cosine
similarity, and returns ranked results for evaluation with RetrievalEvaluator.

Usage:
    retriever = OllamaEmbeddingRetriever(host="http://rpi5:11434", model="llama3.1")
    retriever.index(chunks)  # list of {"id": ..., "text": ...}
    results = retriever.query("What is a register?", k=10)
    # returns list of chunk IDs ranked by similarity
"""

import json
import math
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class OllamaEmbeddingRetriever:
    def __init__(self, host: str = "http://localhost:11434", model: str = "llama3.1") -> None:
        self.host = host.rstrip("/")
        self.model = model
        self._corpus: List[Dict[str, Any]] = []
        self._embeddings: List[List[float]] = []

    def _embed(self, text: str) -> List[float]:
        payload = json.dumps({"model": self.model, "prompt": text}).encode()
        req = urllib.request.Request(
            f"{self.host}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("embedding", [])

    def index(self, chunks: List[Dict[str, str]]) -> None:
        self._corpus = list(chunks)
        self._embeddings = [self._embed(c["text"]) for c in chunks]

    def query(self, query_text: str, k: int = 10) -> List[str]:
        q_emb = self._embed(query_text)
        scored = []
        for i, emb in enumerate(self._embeddings):
            sim = _cosine_sim(q_emb, emb)
            scored.append((sim, self._corpus[i]["id"]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [cid for _, cid in scored[:k]]

    def batch_evaluate(
        self,
        queries: List[Dict[str, Any]],
        k: int = 10,
    ) -> Dict[str, Any]:
        """Run all queries and compute aggregate metrics.

        Each query dict: {"query": str, "relevant_ids": List[str]}
        Returns: {"recall@k": float, "mrr": float, "ndcg@k": float, "per_query": [...]}
        """
        from src.eval.retrieval import RetrievalEvaluator

        per_query = []
        for q in queries:
            retrieved = self.query(q["query"], k=k)
            metrics = RetrievalEvaluator.evaluate_retrieval(
                retrieved, q["relevant_ids"], k=k
            )
            per_query.append({
                "query": q["query"],
                "recall@k": metrics.recall_at_k,
                "mrr": metrics.mrr_score,
                "ndcg@k": metrics.ndcg_score,
            })

        n = len(per_query) or 1
        return {
            "recall@k": sum(p["recall@k"] for p in per_query) / n,
            "mrr": sum(p["mrr"] for p in per_query) / n,
            "ndcg@k": sum(p["ndcg@k"] for p in per_query) / n,
            "k": k,
            "num_queries": len(per_query),
            "per_query": per_query,
        }
