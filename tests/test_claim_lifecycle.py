"""Tests for the claim lifecycle in the database: the design decision that
human-in-the-loop state is persisted, never held in process memory.

pending_review -> in_review -> approved | rejected

The reviewer works from a list of open claims and picks any document in
any order; settled claims leave the list. The key property under test:
nothing is lost between steps, so a server restart is harmless."""

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


def test_uploaded_claims_appear_on_the_work_list_in_arrival_order():
    first, second = make_claim("first.pdf"), make_claim("second.pdf")
    db_service.create_pending(first)
    db_service.create_pending(second)

    open_list = db_service.list_open()
    assert [doc["filename"] for doc in open_list] == ["first.pdf", "second.pdf"]
    assert all(doc["status"] == "pending_review" for doc in open_list)
    assert db_service.counts() == {"pending": 2, "in_review": 0}


def test_reviewer_can_open_any_document_not_just_the_oldest():
    first, second = make_claim("first.pdf"), make_claim("second.pdf")
    db_service.create_pending(first)
    db_service.create_pending(second)

    served = db_service.open_for_review(second.id)
    assert served.id == second.id
    # The proposal round-trips intact, confidences included.
    assert served.fields[0].value == "Mitchell"
    assert served.fields[1].needs_review is True
    # Both stay on the list; the opened one is marked in_review.
    statuses = {doc["filename"]: doc["status"] for doc in db_service.list_open()}
    assert statuses == {"first.pdf": "pending_review", "second.pdf": "in_review"}


def test_open_claims_survive_a_restart():
    claim = make_claim()
    db_service.create_pending(claim)
    db_service.open_for_review(claim.id)

    # A "restart" needs no simulation: there is no process state to lose.
    # The work list still shows the claim and it can be opened again.
    assert [doc["id"] for doc in db_service.list_open()] == [claim.id]
    again = db_service.open_for_review(claim.id)
    assert again.id == claim.id
    assert db_service.counts() == {"pending": 0, "in_review": 1}


def test_approve_requires_the_claim_to_be_opened_first():
    claim = make_claim()
    db_service.create_pending(claim)
    # Not opened yet: approving must fail. No human has it on screen.
    assert db_service.approve(claim.id, fields={"surname": "X"}, confirmed_missing=[]) is None

    db_service.open_for_review(claim.id)
    saved = db_service.approve(claim.id, fields={"surname": "Mitchell"}, confirmed_missing=["member_number"])
    assert saved is not None
    assert saved["fields"]["surname"] == "Mitchell"
    assert saved["confirmed_missing"] == ["member_number"]
    # Settled: gone from the work list, present in the approved facts.
    assert db_service.list_open() == []
    assert [c["id"] for c in db_service.list_approved()] == [claim.id]


def test_rejected_claim_leaves_the_list_but_is_never_approved():
    claim = make_claim()
    db_service.create_pending(claim)
    db_service.open_for_review(claim.id)
    assert db_service.reject(claim.id) is True
    assert db_service.list_open() == []
    assert db_service.list_approved() == []
    # Settled means settled: it cannot be reopened or approved afterwards.
    assert db_service.open_for_review(claim.id) is None
    assert db_service.approve(claim.id, fields={}, confirmed_missing=[]) is None
