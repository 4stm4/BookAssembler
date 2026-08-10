# RFC 0016: Human-In-The-Loop (HITL) Workflow Specification

| Status | Version | Date | Author |
| :--- | :--- | :--- | :--- |
| **Accepted** | 1.0.0 | 2026-08-08 | Core Architecture Team |

---

## 1. Executive Summary

RFC 0016 defines the Human-In-The-Loop (HITL) architecture and reactive inspection protocol for KAE. When automated analyzers emit KRM nodes with a `confidence_score` below $0.80$, the node transitions to `PENDING_HUMAN_REVIEW`. Human corrections are ingested without destroying execution provenance, creating an immutable `agent_type = "human"` record with `confidence_score = 1.0`.

---

## 2. HITL Data Models & Statuses

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any

class CorrectionStatus(str, Enum):
    AUTOMATED = "AUTOMATED"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"

@dataclass
class HITLTask:
    task_id: str
    target_krm_id: str
    current_confidence: float
    status: CorrectionStatus
    suggested_fix: Dict[str, Any]
    reviewer_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
```

---

## 3. Reactive UI Component Protocol

In the Clean Workspace UI, pending HITL tasks trigger a non-blocking sliding banner (`HITLBanner.tsx`):

```tsx
// Reactive subscription to pending HITL queue via REST & SSE
const pendingTasks = await kaeApi.getHITLTasks();

// Operator submits 1-click approval or custom edit
await kaeApi.submitHITLCorrection({
  task_id: "hitl-task-001",
  action: "APPROVED",
  reviewer_id: "operator-lead",
  custom_patch: null
});
```

---

## 4. History Preservation Invariant

Human interventions do NOT overwrite existing KRM nodes in place. Instead, a new node version is appended to the KRM history tree:

```json
{
  "node_id": "krm-tbl-4.2",
  "version": 2,
  "parent_version": 1,
  "agent_type": "human",
  "confidence_score": 1.0,
  "reviewer_id": "operator-lead",
  "content": "Updated addresses in 8086 memory segmentation table",
  "timestamp": "2026-08-08T12:30:00Z"
}
```
