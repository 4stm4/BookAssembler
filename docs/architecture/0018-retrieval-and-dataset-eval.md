# RFC 0018: Retrieval and Dataset Evaluation Specification

| Status | Version | Date | Author |
| :--- | :--- | :--- | :--- |
| **Accepted** | 1.0.0 | 2026-08-08 | Core Architecture Team |

---

## 1. Executive Summary

RFC 0018 details the search quality evaluation metrics (RAG benchmarks) and dataset export engine of KAE. Extracted KRM trees and Knowledge Graphs can be compiled into high-fidelity fine-tuning datasets (`Instruction Dataset`, `QA Dataset`) complete with bounding box provenance references.

---

## 2. Retrieval Evaluation Metrics

KAE continuously evaluates vector and hybrid graph search performance using three standard information retrieval metrics:

### 2.1 Recall@K
Fraction of relevant knowledge nodes retrieved within the top $K$ results:

$$\text{Recall}@K = \frac{|\text{Retrieved}_K \cap \text{Relevant}|}{|\text{Relevant}|}$$

### 2.2 Mean Reciprocal Rank (MRR)
Evaluates the position of the first correct answer in technical queries:

$$\text{MRR} = \frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{\text{rank}_i}$$

### 2.3 Normalized Discounted Cumulative Gain (nDCG@K)
Measures ranking quality of technical documentation chunks considering relevance scores $r_i$:

$$\text{DCG}@K = \sum_{i=1}^{K} \frac{2^{r_i} - 1}{\log_2(i + 1)}$$

---

## 3. Training Dataset Export Engine

KAE supports automated export of structured knowledge trees into fine-tuning datasets for open-weight LLMs (Llama 3, Qwen 2.5, DeepSeek):

```json
{
  "dataset_type": "instruction_tuning",
  "data": [
    {
      "id": "qa-8086-mov-inst",
      "instruction": "Объясните работу инструкции MOV [BX+SI], AX в микропроцессоре 8086.",
      "input": "Контекст: Глава 4, Страница 42, Таблица 4.2",
      "output": "Инструкция MOV [BX+SI], AX выполняет копирование 16-разрядного значения...",
      "provenance": {
        "source_sha256": "e3b0c44298fc1c149afbf4c8996fb924...",
        "bbox": [120.5, 340.0, 880.0, 650.2],
        "page": 42
      }
    }
  ]
}
```
