"""src/api/stores.py — bounded L0 caches for the REST layer (RFC 0013 §2)."""

import importlib.util
import json
import pathlib

# Load the module by path: importing `src.api.*` runs src/api/__init__.py, which
# pulls in the full FastAPI app (and its optional deps). stores.py itself has
# no such dependency.
_spec = importlib.util.spec_from_file_location(
    "kae_api_stores",
    pathlib.Path(__file__).resolve().parents[2] / "src" / "api" / "stores.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
BoundedLRU = _mod.BoundedLRU
DocStore = _mod.DocStore


class TestBoundedLRU:
    def test_evicts_least_recently_used_past_max(self):
        lru = BoundedLRU(3)
        for i in range(5):
            lru[i] = i
        assert list(lru) == [2, 3, 4]

    def test_get_marks_as_recently_used(self):
        lru = BoundedLRU(3)
        for i in range(3):
            lru[i] = i
        lru.get(0)          # touch 0
        lru[3] = 3          # evicts 1, not 0
        assert 0 in lru and 1 not in lru

    def test_get_missing_returns_default(self):
        assert BoundedLRU(2).get("nope", "d") == "d"


class TestDocStore:
    def _write(self, d, jid, title):
        (d / f"{jid}.json").write_text(json.dumps({"title": title}))

    def _store(self, d, max_resident=2):
        return DocStore(str(d), lambda data: data["title"], max_resident)

    def test_loads_from_disk_on_miss(self, tmp_path):
        self._write(tmp_path, "job-a", "Doc A")
        s = self._store(tmp_path)
        assert s.get("job-a") == "Doc A"

    def test_missing_file_returns_default(self, tmp_path):
        assert self._store(tmp_path).get("ghost", "D") == "D"

    def test_contains_covers_resident_and_disk(self, tmp_path):
        self._write(tmp_path, "on-disk", "X")
        s = self._store(tmp_path)
        assert "on-disk" in s              # not resident yet
        s["in-mem"] = "Y"
        assert "in-mem" in s
        assert "nope" not in s

    def test_eviction_keeps_disk_as_source_of_truth(self, tmp_path):
        for jid in ("a", "b", "c"):
            self._write(tmp_path, jid, f"D-{jid}")
        s = self._store(tmp_path, max_resident=2)
        s.get("a")
        s.get("b")
        s.get("c")                         # evicts "a" from memory
        assert list(s._resident) == ["b", "c"]
        assert s.get("a") == "D-a"         # reloaded from disk

    def test_items_and_values_cover_all_persisted(self, tmp_path):
        for jid in ("a", "b", "c", "d"):
            self._write(tmp_path, jid, f"D-{jid}")
        s = self._store(tmp_path, max_resident=1)
        assert sorted(s.all_ids()) == ["a", "b", "c", "d"]
        assert sorted(v for v in s.values()) == ["D-a", "D-b", "D-c", "D-d"]

    def test_job_id_path_traversal_is_contained(self, tmp_path):
        (tmp_path.parent / "secret.json").write_text(json.dumps({"title": "SECRET"}))
        s = self._store(tmp_path)
        assert s.get("../secret", "BLOCKED") == "BLOCKED"

    def test_delitem_drops_resident_only(self, tmp_path):
        self._write(tmp_path, "j", "D")
        s = self._store(tmp_path)
        s.get("j")
        del s["j"]
        assert "j" not in s._resident
        assert "j" in s                    # file still there

    def test_corrupt_json_returns_default_not_raise(self, tmp_path):
        (tmp_path / "bad.json").write_text("{not json")
        assert self._store(tmp_path).get("bad", "D") == "D"
