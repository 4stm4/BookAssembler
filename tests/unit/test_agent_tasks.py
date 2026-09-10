"""Task registry and priority clamping (RFC 0022 §4.4, §4.5, §9 inv.7-8)."""

import pytest

from src.agents.tasks import (
    ALL_TASKS,
    IMAGE_TASKS,
    TEXT_TASKS,
    MAX_PRIORITY,
    Priority,
    clamp_priority,
    needs_image,
    needs_prompt,
    validate_payload,
)


class TestRegistry:
    def test_every_task_declares_what_it_carries(self):
        for task in ALL_TASKS:
            assert needs_image(task) != needs_prompt(task), (
                f"{task} must be either an image task or a text task"
            )

    def test_every_task_has_a_priority_cap(self):
        assert set(MAX_PRIORITY) == set(ALL_TASKS)

    def test_text_tasks_are_the_ones_the_gpu_was_missing(self):
        """RFC 0022 v1.2.0 exists because these two ran on the rpi5 CPU."""
        assert set(TEXT_TASKS) == {"refine", "translate"}

    def test_ocr_is_its_own_task_not_vision(self):
        """Both run the same model, but only one is blocking (§4.4)."""
        assert "ocr" in IMAGE_TASKS
        assert MAX_PRIORITY["ocr"] < MAX_PRIORITY["vision"]


class TestPriorityClamp:
    def test_client_cannot_promote_bulk_work(self):
        """§9 inv.8: otherwise every caller labels its batch interactive."""
        assert clamp_priority("translate", Priority.INTERACTIVE) == Priority.BULK
        assert clamp_priority("refine", 0) == Priority.BULK

    def test_a_caller_may_lower_its_own_urgency(self):
        assert clamp_priority("ocr", Priority.BULK) == Priority.BULK

    def test_default_is_the_task_cap(self):
        assert clamp_priority("ocr", None) == Priority.BLOCKING
        assert clamp_priority("table", None) == Priority.STRUCTURAL

    def test_interactive_is_never_reachable_through_the_client(self):
        for task in ALL_TASKS:
            assert clamp_priority(task, Priority.INTERACTIVE) > Priority.INTERACTIVE

    def test_unknown_task_is_treated_as_bulk(self):
        assert clamp_priority("whatever", None) == Priority.BULK


class TestPayloadValidation:
    def test_image_task_without_an_image_is_rejected(self):
        assert "needs image_b64" in validate_payload("ocr", False, False)

    def test_text_task_without_a_prompt_is_rejected(self):
        assert "needs a prompt" in validate_payload("translate", False, False)

    def test_text_task_with_an_image_is_rejected(self):
        """A page image sent to translate wastes a GPU slot silently."""
        assert "text-only" in validate_payload("refine", True, True)

    def test_unknown_task_is_rejected_by_name(self):
        problem = validate_payload("summarise", False, True)
        assert "unknown task" in problem and "summarise" in problem

    def test_valid_payloads_pass(self):
        assert validate_payload("vision", True, False) is None
        assert validate_payload("refine", False, True) is None
        # an image task may still carry a caller's own prompt
        assert validate_payload("table", True, True) is None
