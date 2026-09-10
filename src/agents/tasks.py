"""Task registry and priority classes (RFC 0022 §4.4, §4.5).

One definition, three consumers: the Runner validates the payload against it,
the client stamps a priority from it, and the Manager schedules by it. Two
copies would drift the way `_block_text` drifted into four implementations —
and here a drift means a request accepted on one side and rejected on the
other.
"""

from enum import IntEnum
from typing import Optional, Tuple


class Priority(IntEnum):
    """Lower is served first (RFC 0022 §4.5)."""

    INTERACTIVE = 0   # a person is waiting on this answer right now
    BLOCKING = 1      # without it the page has no text at all
    STRUCTURAL = 2    # the page exists; this makes it better
    BULK = 3          # thousands of items, nobody waits on any one of them


#: Tasks that carry an image and no prompt of their own.
IMAGE_TASKS = ("ocr", "vision", "table", "formula")

#: Tasks that carry a prompt and no image. Served by the model already loaded
#: for vision — RFC 0022 §9 inv.11 forbids adding a second one.
TEXT_TASKS = ("refine", "translate")

ALL_TASKS = IMAGE_TASKS + TEXT_TASKS

#: The most urgent class each task may claim. The client proposes, the server
#: caps (RFC 0022 §9 inv.8) — otherwise every caller labels its own batch
#: interactive and the classes stop meaning anything.
MAX_PRIORITY = {
    "ocr": Priority.BLOCKING,
    "vision": Priority.STRUCTURAL,
    "table": Priority.STRUCTURAL,
    "formula": Priority.STRUCTURAL,
    "refine": Priority.BULK,
    "translate": Priority.BULK,
}


def needs_image(task: str) -> bool:
    return task in IMAGE_TASKS


def needs_prompt(task: str) -> bool:
    return task in TEXT_TASKS


def clamp_priority(task: str, proposed: Optional[int]) -> Priority:
    """The class this task actually gets.

    `INTERACTIVE` is never reachable through this function: it is granted by
    the Manager to a request arriving from a user action, not claimed by a
    caller (RFC 0022 §4.5).
    """
    cap = MAX_PRIORITY.get(task, Priority.BULK)
    if proposed is None:
        return cap
    return Priority(max(int(proposed), int(cap)))


def validate_payload(task: str, has_image: bool,
                     has_prompt: bool) -> Optional[str]:
    """Why this payload is invalid, or None when it is fine.

    Returned rather than raised so the Runner can answer 400 and the client can
    fail before spending a round trip (RFC 0022 §9 inv.7).
    """
    if task not in ALL_TASKS:
        return f"unknown task '{task}'; known: {', '.join(ALL_TASKS)}"
    if needs_image(task) and not has_image:
        return f"task '{task}' needs image_b64"
    if needs_prompt(task) and not has_prompt:
        return f"task '{task}' needs a prompt"
    if needs_prompt(task) and has_image:
        # Not fatal to the model, but it means the caller mixed up the task:
        # sending a page image to `translate` silently wastes a GPU slot.
        return f"task '{task}' is text-only; drop image_b64"
    return None


def describe(task: str) -> Tuple[str, Priority]:
    kind = "image" if needs_image(task) else "text"
    return kind, MAX_PRIORITY.get(task, Priority.BULK)
