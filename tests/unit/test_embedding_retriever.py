"""Unit tests for OllamaEmbeddingRetriever (mock-based, no ollama needed)."""

import json
from unittest.mock import patch, MagicMock

from src.eval.embedding_retriever import OllamaEmbeddingRetriever, _cosine_sim


class TestCosineSim:
    def test_identical(self):
        assert abs(_cosine_sim([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-9

    def test_orthogonal(self):
        assert abs(_cosine_sim([1, 0], [0, 1])) < 1e-9

    def test_zero_vector(self):
        assert _cosine_sim([0, 0], [1, 0]) == 0.0


class TestRetriever:
    def _mock_embed(self, texts_to_embeddings):
        call_count = [0]
        def _urlopen(req, **kwargs):
            data = json.loads(req.data)
            prompt = data["prompt"]
            emb = texts_to_embeddings.get(prompt, [0.0, 0.0, 0.0])
            resp = MagicMock()
            resp.read.return_value = json.dumps({"embedding": emb}).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp
        return _urlopen

    def test_index_and_query(self):
        embeddings = {
            "about registers": [1.0, 0.0, 0.0],
            "about interrupts": [0.0, 1.0, 0.0],
            "what are registers?": [0.9, 0.1, 0.0],
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_embed(embeddings)):
            r = OllamaEmbeddingRetriever(host="http://fake:11434")
            r.index([
                {"id": "c1", "text": "about registers"},
                {"id": "c2", "text": "about interrupts"},
            ])
            results = r.query("what are registers?", k=2)
        assert results[0] == "c1"

    def test_batch_evaluate(self):
        embeddings = {
            "doc A": [1.0, 0.0],
            "doc B": [0.0, 1.0],
            "query about A": [0.9, 0.1],
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_embed(embeddings)):
            r = OllamaEmbeddingRetriever()
            r.index([
                {"id": "a", "text": "doc A"},
                {"id": "b", "text": "doc B"},
            ])
            result = r.batch_evaluate(
                [{"query": "query about A", "relevant_ids": ["a"]}],
                k=2,
            )
        assert result["recall@k"] == 1.0
        assert result["mrr"] == 1.0
        assert result["num_queries"] == 1
