"""
Benchmark Quality Metrics for Knowledge Assembly Engine (KAE).

Implements Wagner-Fischer edit distance, Word Error Rate (WER), TEDS
(Tree Edit Distance for Structure), and Link Precision/Recall/F1 metrics
according to RFC 0009 (docs/architecture/0009-benchmark.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (typing, json, math)
"""

from typing import Any, Dict, List, Tuple


def compute_edit_distance(seq1: List[Any], seq2: List[Any]) -> int:
    """
    Computes the Levenshtein / Wagner-Fischer edit distance between two sequences.
    """
    m, n = len(seq1), len(seq2)
    if m == 0:
        return n
    if n == 0:
        return m

    previous_row = list(range(n + 1))
    current_row = [0] * (n + 1)

    for i in range(1, m + 1):
        current_row[0] = i
        for j in range(1, n + 1):
            cost = 0 if seq1[i - 1] == seq2[j - 1] else 1
            current_row[j] = min(
                previous_row[j] + 1,        # Deletion
                current_row[j - 1] + 1,     # Insertion
                previous_row[j - 1] + cost, # Substitution
            )
        previous_row, current_row = current_row, previous_row

    return previous_row[n]


def compute_wer(reference_text: str, hypothesis_text: str) -> float:
    """
    Computes Word Error Rate (WER) between reference and hypothesis texts.
    WER = (Substitutions + Deletions + Insertions) / N_ref_words.
    """
    ref_words = reference_text.strip().split()
    hyp_words = hypothesis_text.strip().split()

    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    edit_dist = compute_edit_distance(ref_words, hyp_words)
    return float(edit_dist) / float(len(ref_words))


def _dict_to_structure_tokens(obj: Any) -> List[str]:
    """
    Flattens a table JSON structure into canonical structural tokens for edit distance.
    """
    tokens: List[str] = []
    if isinstance(obj, dict):
        for key in sorted(obj.keys()):
            tokens.append(f"<{key}>")
            tokens.extend(_dict_to_structure_tokens(obj[key]))
            tokens.append(f"</{key}>")
    elif isinstance(obj, list):
        tokens.append("<list>")
        for item in obj:
            tokens.extend(_dict_to_structure_tokens(item))
        tokens.append("</list>")
    else:
        tokens.append(str(obj).strip())
    return tokens


def compute_teds(
    expected_table_json: Dict[str, Any], extracted_table_json: Dict[str, Any]
) -> float:
    """
    Computes Tree Edit Distance for Structure (TEDS) between two table structures.
    TEDS = 1.0 - (EditDistance / max(len(expected), len(extracted)))
    """
    tokens1 = _dict_to_structure_tokens(expected_table_json)
    tokens2 = _dict_to_structure_tokens(extracted_table_json)

    max_len = max(len(tokens1), len(tokens2))
    if max_len == 0:
        return 1.0

    edit_dist = compute_edit_distance(tokens1, tokens2)
    teds = 1.0 - (float(edit_dist) / float(max_len))
    return max(0.0, min(1.0, teds))


def compute_link_f1(
    expected_edges: List[Dict[str, Any]], extracted_edges: List[Dict[str, Any]]
) -> Dict[str, float]:
    """
    Computes Precision, Recall, and Link F1-score for Knowledge Graph edges.
    """
    def canonical_tuple(e: Dict[str, Any]) -> Tuple[str, str, str]:
        src = str(e.get("source_id") or e.get("source") or "")
        tgt = str(e.get("target_id") or e.get("target") or "")
        rel = str(e.get("relation_type") or e.get("relation") or "")
        return (src, tgt, rel)

    exp_set = {canonical_tuple(e) for e in expected_edges}
    ext_set = {canonical_tuple(e) for e in extracted_edges}

    if not exp_set and not ext_set:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}

    if not ext_set:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    if not exp_set:
        return {"precision": 0.0, "recall": 1.0, "f1": 0.0}

    correct = len(exp_set.intersection(ext_set))
    precision = float(correct) / float(len(ext_set))
    recall = float(correct) / float(len(exp_set))

    if precision + recall > 0.0:
        f1 = (2.0 * precision * recall) / (precision + recall)
    else:
        f1 = 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }
