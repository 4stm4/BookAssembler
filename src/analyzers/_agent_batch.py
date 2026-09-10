"""
Bounded concurrent fan-out to an agent, with a failure budget that holds.

Both the vision analyzers ask an agent about many pages at once. Submitting
every task upfront makes the budget unenforceable: Future.cancel() only reaches
tasks that have not started, so a fast-failing agent is asked about the whole
book before the first cancellation lands. Keeping only `concurrency` tasks in
flight and topping up as results arrive makes the limit real regardless of how
quickly the agent fails.
"""

import logging
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable, Dict, Iterable, List, Tuple

log = logging.getLogger(__name__)

def run_bounded(
    items: List[Any],
    work: Callable[[Any], Any],
    concurrency: int,
    budget: int,
    label: str = "agent",
) -> Tuple[Dict[int, Any], int]:
    """Run `work` over `items`, at most `concurrency` at a time.

    Returns ({index: result}, failures). Stops submitting once more than
    `budget` items have failed — one bad page must not abort a book, but a dead
    agent must not be asked about every remaining page.
    """
    results: Dict[int, Any] = {}
    failures = 0
    pending: Dict[Any, int] = {}
    nxt = 0

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        while True:
            while (len(pending) < concurrency and nxt < len(items)
                   and failures <= budget):
                pending[pool.submit(work, items[nxt])] = nxt
                nxt += 1
            if not pending:
                break
            done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for fut in done:
                idx = pending.pop(fut)
                try:
                    results[idx] = fut.result()
                except Exception as exc:
                    failures += 1
                    log.warning("%s: item %d failed: %s", label, idx, exc)
                    if failures == budget + 1:
                        log.warning(
                            "%s: %d failures over budget %d — not submitting "
                            "the rest", label, failures, budget,
                        )
    return results, failures
