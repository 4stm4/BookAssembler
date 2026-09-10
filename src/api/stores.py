"""Bounded in-memory stores for the REST layer.

RFC 0013 §2 makes L0 an in-memory LRU — a working set, not "every document the
server has ever processed". The API held documents, per-job graphs, and progress
entries in plain dicts that only ever grew.

Kept out of app.py so it imports without FastAPI (and its optional deps).
"""

import json
import logging
import os
from collections import OrderedDict
from typing import Any, Iterator, List, Tuple

log = logging.getLogger(__name__)


class BoundedLRU(OrderedDict):
    """OrderedDict that evicts the least-recently-used entry past `max_size`."""

    def __init__(self, max_size: int) -> None:
        super().__init__()
        self._max = max_size

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self._max:
            self.popitem(last=False)

    def get(self, key: Any, default: Any = None) -> Any:
        if key in self:
            self.move_to_end(key)
        return super().get(key, default)


class DocStore:
    """LRU of resident document trees backed by the on-disk JSON in `docs_dir`.

    A miss rebuilds from disk via `rebuild_fn` (RFC 0013 §L0); eviction only
    drops the in-memory copy — the persisted JSON is the source of truth. The
    caller keeps writing that JSON (``_persist_doc``) and deleting it on job
    removal, so this class never touches disk except to read.
    """

    def __init__(self, docs_dir: str, rebuild_fn: Any, max_resident: int) -> None:
        self._dir = docs_dir
        self._rebuild = rebuild_fn
        self._max = max_resident
        self._resident: "OrderedDict[str, Any]" = OrderedDict()

    def _path(self, job_id: str) -> str:
        return os.path.join(self._dir, f"{os.path.basename(job_id)}.json")

    def _keep(self, job_id: str, doc: Any) -> None:
        self._resident[job_id] = doc
        self._resident.move_to_end(job_id)
        while len(self._resident) > self._max:
            self._resident.popitem(last=False)

    def get(self, job_id: str, default: Any = None) -> Any:
        if job_id in self._resident:
            self._resident.move_to_end(job_id)
            return self._resident[job_id]
        path = self._path(job_id)
        if not os.path.isfile(path):
            return default
        try:
            with open(path) as fh:
                doc = self._rebuild(json.load(fh))
        except Exception:
            log.exception("Failed to load persisted document '%s'", job_id)
            return default
        self._keep(job_id, doc)
        return doc

    def __setitem__(self, job_id: str, doc: Any) -> None:
        self._keep(job_id, doc)

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._resident or os.path.isfile(self._path(job_id))

    def __delitem__(self, job_id: str) -> None:
        self._resident.pop(job_id, None)

    def all_ids(self) -> List[str]:
        ids = list(self._resident.keys())
        try:
            for fn in sorted(os.listdir(self._dir)):
                if fn.endswith(".json") and fn[:-5] not in self._resident:
                    ids.append(fn[:-5])
        except OSError:
            pass
        return ids

    def items(self) -> Iterator[Tuple[str, Any]]:
        for jid in self.all_ids():
            doc = self.get(jid)
            if doc is not None:
                yield jid, doc

    def values(self) -> Iterator[Any]:
        for _jid, doc in self.items():
            yield doc
