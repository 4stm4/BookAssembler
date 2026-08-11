import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class AuditLogger:
    def __init__(self, log_dir: str = ".kae") -> None:
        os.makedirs(log_dir, exist_ok=True)
        self._log_path = os.path.join(log_dir, "audit.log")
        self._lock = threading.Lock()
        self._seq = 0
        self._prev_hash = "0" * 64

        if os.path.exists(self._log_path):
            with open(self._log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        self._seq = record.get("seq", 0)
                        self._prev_hash = hashlib.sha256(line.encode()).hexdigest()
                    except json.JSONDecodeError:
                        pass

    def log(
        self,
        event_type: str,
        actor: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            record = {
                "seq": self._seq,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "actor": actor,
                "details": details or {},
                "prev_hash": self._prev_hash,
            }
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            self._prev_hash = hashlib.sha256(line.encode()).hexdigest()

            with open(self._log_path, "a") as f:
                f.write(line + "\n")

            return record
