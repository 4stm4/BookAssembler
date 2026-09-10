"""One tree walk over the KRM (RFC 0002 §3).

Every stage that needs "all nodes in the document" used to hand-roll the
recursion, and each copy missed a nesting the others didn't: the pipeline's
dangling-edge check skipped `SidebarBlock` bodies, HITL skipped list and
callout bodies (so a low-confidence block inside a list was never queued for
review and could not be corrected). This module is the single place that knows
how each node type holds its children.
"""

from typing import Any, Iterator


def walk(node: Any) -> Iterator[Any]:
    """Yield `node` and every KRM node beneath it, depth-first, parents first.

    Duck-typed on the child-bearing attributes so it covers `KnowledgeDocument`
    (`root_containers`), containers (`children`), paragraphs/inlines
    (`inlines`/`spans`), lists (`items`), list/callout/sidebar/table-cell
    bodies (`content`), tables (`grid`), index entries (`subentries`) and the
    document's `semantic_units`.
    """
    yield node

    for container in getattr(node, "root_containers", None) or []:
        yield from walk(container)
    for child in getattr(node, "children", None) or []:
        yield from walk(child)
    for inline in getattr(node, "inlines", None) or []:
        yield from walk(inline)
    for span in getattr(node, "spans", None) or []:
        yield from walk(span)
    for item in getattr(node, "items", None) or []:
        yield from walk(item)
    for block in getattr(node, "content", None) or []:
        yield from walk(block)
    for row in getattr(node, "grid", None) or []:
        for cell in row:
            yield from walk(cell)
    for sub in getattr(node, "subentries", None) or []:
        yield from walk(sub)
    for unit in getattr(node, "semantic_units", None) or []:
        yield from walk(unit)
