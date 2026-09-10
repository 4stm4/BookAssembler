"""The Kaggle notebook must only name things the code actually has.

The notebook is not executed by CI — it runs on Kaggle, where a wrong slug
costs a GPU session and a restart. It shipped `qwen25vl` once; the registry
calls it `qwen_vl`.
"""
import json
import pathlib
import re

import pytest

NB = pathlib.Path("colab/kaggle-runner/runner.ipynb")


def _source() -> str:
    nb = json.loads(NB.read_text())
    return "\n".join("".join(c.get("source", [])) for c in nb["cells"])


def test_notebook_is_valid_json_with_cells():
    nb = json.loads(NB.read_text())
    assert nb["cells"], "notebook has no cells"
    assert nb["nbformat"] == 4


def test_loader_slugs_exist_in_the_registry():
    from src.agents.runner.loaders import LOADER_REGISTRY

    slugs = re.findall(r"KAE_RUNNER_LOADERS['\"],\s*['\"]([^'\"]+)", _source())
    assert slugs, "notebook no longer sets KAE_RUNNER_LOADERS"
    for spec in slugs:
        for slug in spec.split(","):
            slug = slug.strip()
            assert slug in LOADER_REGISTRY, (
                f"notebook names loader {slug!r}, registry has "
                f"{sorted(LOADER_REGISTRY)}"
            )


def test_env_vars_the_notebook_sets_are_read_somewhere():
    """A setting nothing reads is a setting that silently does nothing."""
    src_root = pathlib.Path("src")
    code = "\n".join(
        p.read_text() for p in src_root.rglob("*.py")
    )
    names = set(re.findall(r"os\.environ\.setdefault\(\s*['\"](KAE_[A-Z_]+)", _source()))
    names |= set(re.findall(r"os\.environ\[\s*['\"](KAE_[A-Z_]+)", _source()))
    unread = [n for n in sorted(names) if n not in code]
    assert not unread, f"notebook sets {unread}, nothing in src/ reads them"


def test_placeholders_are_still_there_for_the_push_script():
    """push-kaggle-runner.sh substitutes these; renaming them breaks the push."""
    s = _source()
    assert "__KAE_MANAGER_URL__" in s
    assert "__KAE_RUNNER_TOKEN__" in s


def test_qwen_loader_serves_every_registry_task():
    """RFC 0022 §9 inv.11: one model, all tasks.

    A task missing here is invisible until a GPU session is already burning:
    the Runner answers "unknown task" and the analyzer silently degrades.
    """
    from src.agents.runner.loaders.qwen_vl import QwenVLLoader
    from src.agents.tasks import ALL_TASKS

    loader = QwenVLLoader.__new__(QwenVLLoader)
    QwenVLLoader.__init__(loader)
    assert set(loader.tasks) == set(ALL_TASKS)


def test_image_tasks_have_a_default_prompt():
    """Text tasks carry their own; image tasks must not be sent an empty one."""
    from src.agents.runner.loaders.qwen_vl import TASK_PROMPTS
    from src.agents.tasks import IMAGE_TASKS

    missing = [t for t in IMAGE_TASKS if t not in TASK_PROMPTS]
    assert not missing, f"image tasks with no default prompt: {missing}"
