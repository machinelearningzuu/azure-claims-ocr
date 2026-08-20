"""Queue service: the seam between "a claim arrived" and "a human reviews it".

The rest of the app only knows two operations:

    publish(item)        a new AI proposal enters the pending-review flow
    consume() -> item    the next proposal a human should look at (None if none)

Layer 1 implementation: a thin facade over the database. The claim's status
column IS the queue: publish() persists it as pending_review, consume()
flips the oldest one to in_review. Because the database is the system of
record, a restart loses nothing; whatever was pending or mid-review is
still there afterwards.

This is the transactional-outbox idea in miniature: state lives in the
database, and the queue is DERIVED from that state, never the storage
itself. The queue is not a database.

Layer 3: publish() will additionally send an Azure Service Bus message so
a separate worker process wakes up and does the OCR asynchronously. The
broker dispatches work; the database keeps being the truth.
"""

from app.models import PendingClaim
from app.services import db_service


def publish(item: PendingClaim) -> None:
    """Persist a new AI proposal with status pending_review."""
    db_service.create_pending(item)


def consume() -> PendingClaim | None:
    """The claim the human should see now: a claim already mid-review is
    re-served first, otherwise the oldest pending one is picked up."""
    return db_service.next_for_review()


def size() -> int:
    """How many proposals are waiting behind the current one (shown in the UI)."""
    return db_service.counts()["pending"]
