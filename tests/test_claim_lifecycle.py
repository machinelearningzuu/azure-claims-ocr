"""Tests for the claim lifecycle in the database: the design decision that
human-in-the-loop state is persisted, never held in process memory.

pending_review -> in_review -> approved | rejected

The key property under test: nothing is lost between steps. A claim that
was mid-review is re-served, which is exactly what makes a server restart
harmless."""

import uuid

import pytest

from app.models import PendingClaim, ExtractedField
from app.services import db_service


@pytest.fixture(autouse=True)
def clean_claims_table():
    with db_service.Session() as session:
        session.query(db_service.ClaimRow).delete()
        session.commit()
    yield


def make_claim(filename="test.pdf") -> PendingClaim:
    return PendingClaim(
        id=str(uuid.uuid4()),
        filename=filename,
        template="metlife_tpd_initial",
        uploaded_at="2026-08-21T10:00:00+00:00",
        fields=[
            ExtractedField(name="surname", value="Mitchell", confidence=0.97, needs_review=False),
            ExtractedField(name="member_number", value=None, confidence=0.0, needs_review=True),
        ],
    )


def test_uploaded_claim_is_persisted_as_pending():
    db_service.create_pending(make_claim())
    assert db_service.counts() == {"pending": 1, "in_review": 0}


def test_consume_moves_oldest_claim_to_in_review_in_fifo_order():
    first, second = make_claim("first.pdf"), make_claim("second.pdf")
    db_service.create_pending(first)
    db_service.create_pending(second)

    served = db_service.next_for_review()
    assert served.id == first.id
    assert db_service.counts() == {"pending": 1, "in_review": 1}
    # The proposal round-trips intact, confidences included.
    assert served.fields[0].value == "Mitchell"
    assert served.fields[1].needs_review is True


def test_in_review_claim_is_reserved_after_a_restart():
    claim = make_claim()
    db_service.create_pending(claim)
    db_service.next_for_review()

    # A "restart" needs no simulation: there is no process state to lose.
    # Asking again must return the same claim, not silently drop it.
    again = db_service.next_for_review()
    assert again.id == claim.id
    assert db_service.counts() == {"pending": 0, "in_review": 1}


def test_approve_requires_the_claim_to_be_in_review():
    claim = make_claim()
    db_service.create_pending(claim)
    # Not consumed yet: approving must fail. No human has it on screen.
    assert db_service.approve(claim.id, fields={"surname": "X"}, confirmed_missing=[]) is None

    db_service.next_for_review()
    saved = db_service.approve(claim.id, fields={"surname": "Mitchell"}, confirmed_missing=["member_number"])
    assert saved is not None
    assert saved["fields"]["surname"] == "Mitchell"
    assert saved["confirmed_missing"] == ["member_number"]
    assert db_service.counts() == {"pending": 0, "in_review": 0}
    assert [c["id"] for c in db_service.list_approved()] == [claim.id]


def test_rejected_claim_is_recorded_but_never_approved():
    claim = make_claim()
    db_service.create_pending(claim)
    db_service.next_for_review()
    assert db_service.reject(claim.id) is True
    assert db_service.list_approved() == []
    assert db_service.counts() == {"pending": 0, "in_review": 0}
    # Settled means settled: the same claim cannot be approved afterwards.
    assert db_service.approve(claim.id, fields={}, confirmed_missing=[]) is None
