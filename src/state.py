"""Pipeline state management — checkpoints, contracts, resume."""

import hashlib
import json
import os
import time


STATE_DIR = "cache/state"
CONTRACTS = {
    "extract": {
        "outputs": ["cache/text/pages_{start}_{end}.json"],
        "output_schema": {"type": "dict", "key_type": "str_int", "value_type": "str"},
    },
    "manifest": {
        "requires": [],
        "outputs": ["ch{ch}_manifest.json"],
        "output_schema": {"required_keys": ["figures", "tables"]},
    },
    "figures": {
        "requires": ["manifest"],
        "outputs": [],
    },
    "translate": {
        "requires": ["extract"],
        "outputs": [],
    },
    "autofix": {
        "requires": ["translate"],
        "outputs": [],
    },
    "validate": {
        "requires": ["translate"],
        "outputs": [],
    },
    "build": {
        "requires": ["translate"],
        "outputs": ["latex_output/ch{ch:02d}.tex"],
    },
    "compile": {
        "requires": ["build"],
        "outputs": [],
    },
}


class PipelineState:
    def __init__(self, chapter):
        self.chapter = chapter
        os.makedirs(STATE_DIR, exist_ok=True)
        self.state_file = os.path.join(STATE_DIR, f"ch{chapter}.json")
        self.state = self._load()

    def _load(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        return {"chapter": self.chapter, "stages": {}, "created": time.time()}

    def _save(self):
        self.state["updated"] = time.time()
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_file)

    def is_done(self, stage):
        info = self.state["stages"].get(stage)
        return info is not None and info.get("status") == "done"

    def needs_rerun(self, stage, input_files):
        """Check if inputs changed since last successful run."""
        info = self.state["stages"].get(stage)
        if not info or info.get("status") != "done":
            return True
        old_hashes = info.get("input_hashes", {})
        for path in input_files:
            if os.path.exists(path):
                h = _file_hash(path)
                if old_hashes.get(path) != h:
                    return True
        return False

    def mark_running(self, stage):
        self.state["stages"][stage] = {
            "status": "running",
            "started": time.time(),
        }
        self._save()

    def mark_done(self, stage, input_files=None, output_files=None, meta=None):
        input_hashes = {}
        if input_files:
            for p in input_files:
                if os.path.exists(p):
                    input_hashes[p] = _file_hash(p)

        output_hashes = {}
        if output_files:
            for p in output_files:
                if os.path.exists(p):
                    output_hashes[p] = _file_hash(p)

        self.state["stages"][stage] = {
            "status": "done",
            "started": self.state["stages"].get(stage, {}).get("started", time.time()),
            "finished": time.time(),
            "input_hashes": input_hashes,
            "output_hashes": output_hashes,
        }
        if meta:
            self.state["stages"][stage]["meta"] = meta
        self._save()

    def mark_failed(self, stage, error=""):
        info = self.state["stages"].get(stage, {})
        info.update({
            "status": "failed",
            "error": str(error)[:500],
            "failed_at": time.time(),
        })
        self.state["stages"][stage] = info
        self._save()

    def get_resume_stage(self, all_stages):
        """Find the first stage that isn't done."""
        for s in all_stages:
            if not self.is_done(s):
                return s
        return None

    def check_dependencies(self, stage):
        """Verify that required stages are done before running this one."""
        contract = CONTRACTS.get(stage, {})
        missing = []
        for dep in contract.get("requires", []):
            if not self.is_done(dep):
                missing.append(dep)
        return missing

    def summary(self):
        lines = [f"Глава {self.chapter}:"]
        for stage, info in self.state.get("stages", {}).items():
            status = info.get("status", "?")
            icon = {"done": "+", "running": "~", "failed": "!!"}.get(status, "?")
            elapsed = ""
            if info.get("started") and info.get("finished"):
                dt = info["finished"] - info["started"]
                elapsed = f" ({dt:.0f}с)"
            error = ""
            if status == "failed" and info.get("error"):
                error = f" — {info['error'][:80]}"
            lines.append(f"  [{icon}] {stage}: {status}{elapsed}{error}")
        return "\n".join(lines)

    def reset_stage(self, stage):
        self.state["stages"].pop(stage, None)
        self._save()


def _file_hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def validate_stage_output(stage, ch, start, end):
    """Validate that a stage produced correct output format."""
    contract = CONTRACTS.get(stage, {})

    for pattern in contract.get("outputs", []):
        path = pattern.format(ch=ch, start=start, end=end)
        if not os.path.exists(path):
            return False, f"Выходной файл не найден: {path}"

        schema = contract.get("output_schema")
        if schema and path.endswith(".json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                return False, f"Невалидный JSON {path}: {e}"

            if schema.get("type") == "dict" and not isinstance(data, dict):
                return False, f"{path}: ожидался dict, получен {type(data).__name__}"

            if schema.get("key_type") == "str_int" and isinstance(data, dict):
                bad_keys = [k for k in data if not k.isdigit()]
                if bad_keys:
                    return False, f"{path}: ключи должны быть числовыми строками, найдены: {bad_keys[:3]}"

            req_keys = schema.get("required_keys", [])
            if req_keys and isinstance(data, dict):
                missing = [k for k in req_keys if k not in data]
                if missing:
                    return False, f"{path}: отсутствуют ключи: {missing}"

    return True, ""
