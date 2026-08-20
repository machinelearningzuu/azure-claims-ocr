"""Queue service: where AI proposals wait for a human.

The rest of the app only knows two operations:

    publish(item)        put an OCR result into the pending-review queue
    consume() -> item    take the next one out for review (None if empty)

This is the boundary that makes the system human-in-the-loop: OCR results
are published HERE, not written to the database. The queue is the holding
area for proposals; the database is reserved for human-approved facts.

Layer 1 implementation: a plain in-process deque. Deliberately primitive.
If the server restarts, pending items are lost, and only this one process
can see the queue. Those two weaknesses are exactly why Layer 3 swaps this
file's internals for Azure Service Bus (durable, and consumable by a
separate worker process) WITHOUT changing the two-function interface above.
"""

from collections import deque

from app.models import PendingClaim

_queue: deque[PendingClaim] = deque()


def publish(item: PendingClaim) -> None:
    """Add an OCR proposal to the back of the pending-review queue."""
    _queue.append(item)


def consume() -> PendingClaim | None:
    """Remove and return the oldest pending item, or None if the queue is empty."""
    if not _queue:
        return None
    return _queue.popleft()


def size() -> int:
    """How many proposals are waiting (shown in the UI)."""
    return len(_queue)
