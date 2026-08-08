"""
Retrieval Evaluation & Dataset Generation Engine for Knowledge Assembly Engine (KAE).

Implements RetrievalEvalMetrics, RetrievalEvaluator, and DatasetGenerator according to RFC 0018.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, math)
"""

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional

from src.ai_layer.models import AIContextChunk


@dataclass
class RetrievalEvalMetrics:
    """
    Evaluation metrics for RAG retrieval quality (Recall@K, MRR, nDCG@K).
    """
    recall_at_k: float
    mrr_score: float
    ndcg_score: float


class RetrievalEvaluator:
    """
    Evaluator computing information retrieval performance metrics over candidate and ground-truth ID lists.
    """

    @staticmethod
    def compute_recall_at_k(
        retrieved_ids: List[str], relevant_ids: List[str], k: int
    ) -> float:
        """
        Calculates Recall@K: proportion of relevant IDs retrieved in top K.
        """
        if not relevant_ids or k <= 0:
            return 0.0

        top_k = retrieved_ids[:k]
        relevant_set = set(relevant_ids)
        found = sum(1 for item_id in top_k if item_id in relevant_set)
        return float(found) / float(len(relevant_set))

    @staticmethod
    def compute_mrr(
        retrieved_ids: List[str], relevant_ids: List[str]
    ) -> float:
        """
        Calculates Mean Reciprocal Rank (MRR): 1 / rank of first relevant retrieved item.
        """
        if not relevant_ids or not retrieved_ids:
            return 0.0

        relevant_set = set(relevant_ids)
        for rank, item_id in enumerate(retrieved_ids, start=1):
            if item_id in relevant_set:
                return 1.0 / float(rank)

        return 0.0

    @staticmethod
    def compute_ndcg(
        retrieved_ids: List[str], relevant_ids: List[str], k: int
    ) -> float:
        """
        Calculates Normalized Discounted Cumulative Gain at K (nDCG@K).
        """
        if not relevant_ids or not retrieved_ids or k <= 0:
            return 0.0

        top_k = retrieved_ids[:k]
        relevant_set = set(relevant_ids)

        dcg = 0.0
        for i, item_id in enumerate(top_k, start=1):
            rel = 1.0 if item_id in relevant_set else 0.0
            dcg += rel / math.log2(i + 1)

        idcg = 0.0
        num_relevant_in_k = min(len(relevant_ids), k)
        for i in range(1, num_relevant_in_k + 1):
            idcg += 1.0 / math.log2(i + 1)

        if idcg == 0.0:
            return 0.0

        return dcg / idcg

    @classmethod
    def evaluate_retrieval(
        cls, retrieved_ids: List[str], relevant_ids: List[str], k: int = 10
    ) -> RetrievalEvalMetrics:
        """
        Computes all retrieval evaluation metrics (Recall@K, MRR, nDCG@K) for a single query.
        """
        recall = cls.compute_recall_at_k(retrieved_ids, relevant_ids, k)
        mrr = cls.compute_mrr(retrieved_ids, relevant_ids)
        ndcg = cls.compute_ndcg(retrieved_ids, relevant_ids, k)

        return RetrievalEvalMetrics(
            recall_at_k=recall,
            mrr_score=mrr,
            ndcg_score=ndcg,
        )


class DatasetGenerator:
    """
    Generator converting KRM AIContextChunk instances into QA and Instruction fine-tuning datasets.
    """

    @staticmethod
    def generate_instruction_dataset(
        chunks: List[AIContextChunk],
    ) -> List[Dict[str, Any]]:
        """
        Generates instruction dataset items from KRM AIContextChunk objects preserving provenance info.
        """
        dataset: List[Dict[str, Any]] = []

        for chunk in chunks:
            ctx_header = (
                chunk.breadcrumbs.to_header_string()
                if chunk.breadcrumbs
                else f"Context Chunk ({chunk.chunk_id})"
            )
            instruction = f"Analyze and extract key knowledge from: {ctx_header}"
            input_text = chunk.contextual_text or chunk.text_content
            output_text = chunk.text_content

            prov_info = {
                "chunk_id": chunk.chunk_id,
                "source_krm_ids": list(chunk.source_krm_ids),
                "parent_container_id": chunk.parent_container_id,
                "metadata": dict(chunk.metadata),
            }

            item: Dict[str, Any] = {
                "chunk_id": chunk.chunk_id,
                "instruction": instruction,
                "input": input_text,
                "output": output_text,
                "source_krm_ids": list(chunk.source_krm_ids),
                "provenance_info": prov_info,
            }
            dataset.append(item)

        return dataset

    @staticmethod
    def generate_qa_dataset(
        chunks: List[AIContextChunk],
    ) -> List[Dict[str, Any]]:
        """
        Generates QA dataset pairs from KRM AIContextChunk objects preserving provenance info.
        """
        dataset: List[Dict[str, Any]] = []

        for chunk in chunks:
            title = (
                chunk.breadcrumbs.document_title if chunk.breadcrumbs else "the section"
            )
            question = (
                f"What information is described in {title} regarding {chunk.chunk_type}?"
            )
            answer = chunk.text_content

            prov_info = {
                "chunk_id": chunk.chunk_id,
                "source_krm_ids": list(chunk.source_krm_ids),
                "parent_container_id": chunk.parent_container_id,
            }

            item: Dict[str, Any] = {
                "chunk_id": chunk.chunk_id,
                "question": question,
                "answer": answer,
                "context": chunk.contextual_text or chunk.text_content,
                "source_krm_ids": list(chunk.source_krm_ids),
                "provenance_info": prov_info,
            }
            dataset.append(item)

        return dataset
