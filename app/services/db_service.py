"""Database service: the system of record for every claim's lifecycle.

Status flow, and who is allowed to cause each transition:

    pending_review --(reviewer opens it)--> in_review
    in_review ------(human approves)------> approved
    in_review ------(human rejects)-------> rejected

Every uploaded claim is persisted immediately with a status, so a server
restart never loses work: whatever was pending or mid-review is still here
afterwards. Human-in-the-loop state is too important for process memory.

The AI-proposal / human-fact boundary is expressed in columns:

    extracted_json   what the AI proposed (values + confidences). Written
                     once at upload and never treated as truth.
    approved_json    what the human approved. Only approve() writes it,
                     and approve() demands the claim be in_review. There is
                     still no code path that turns AI output into approved
                     data without a human.

Rejected claims keep their row (status=rejected) instead of disappearing:
"a human looked at this and said no" is part of the audit trail.

Layer 2 swaps DATABASE_URL to Azure PostgreSQL; this interface stays put.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app import config
from app.models import ExtractedField, PendingClaim

PENDING = "pending_review"
IN_REVIEW = "in_review"
APPROVED = "approved"
REJECTED = "rejected"

Base = declarative_base()


class ClaimRow(Base):
    __tablename__ = "claims"

    # Autoincrement keeps strict arrival order even when two uploads share
    # the same timestamp second; the uuid is the claim's public identity.
    seq = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String, unique=True, index=True, nullable=False)
    template = Column(String, nullable=False)
    source_filename = Column(String, nullable=False)
    uploaded_at = Column(String, nullable=False)
    status = Column(String, nullable=False, index=True)
    extracted_json = Column(Text, nullable=False)            # the AI's proposal
    approved_json = Column(Text)                             # human-approved values (approve() only)
    confirmed_missing_json = Column(Text)                    # gaps the human explicitly accepted
    reviewed_at = Column(String)


engine = create_engine(config.DATABASE_URL)
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_pending(claim: PendingClaim) -> None:
    """Persist a fresh AI proposal with status pending_review. This runs at
    upload time, so the claim survives any restart from this moment on."""
    row = ClaimRow(
        id=claim.id,
        template=claim.template,
        source_filename=claim.filename,
        uploaded_at=claim.uploaded_at,
        status=PENDING,
        extracted_json=json.dumps([field.model_dump() for field in claim.fields]),
    )
    with Session() as session:
        session.add(row)
        session.commit()


def next_for_review() -> Optional[PendingClaim]:
    """The claim the human should see now.

    A claim already in_review (e.g. the page was refreshed, or the server
    restarted mid-review) is re-served first; otherwise the oldest pending
    claim is picked up and marked in_review. The status column is the
    durable version of what a message broker calls a peek-lock."""
    with Session() as session:
        row = (
            session.query(ClaimRow)
            .filter(ClaimRow.status == IN_REVIEW)
            .order_by(ClaimRow.seq)
            .first()
        )
        if row is None:
            row = (
                session.query(ClaimRow)
                .filter(ClaimRow.status == PENDING)
                .order_by(ClaimRow.seq)
                .first()
            )
            if row is None:
                return None
            row.status = IN_REVIEW
            session.commit()
        return _row_to_pending(row)


def approve(claim_id: str, fields: dict, confirmed_missing: list[str]) -> Optional[dict]:
    """THE COMMIT. The only function in the app that writes approved_json,
    and it only accepts a claim currently in_review, i.e. one a human has
    on screen. Returns the approved claim, or None if the id is not in
    review (already settled, or never existed)."""
    with Session() as session:
        row = session.query(ClaimRow).filter(ClaimRow.id == claim_id).first()
        if row is None or row.status != IN_REVIEW:
            return None
        row.status = APPROVED
        row.approved_json = json.dumps(fields)
        row.confirmed_missing_json = json.dumps(confirmed_missing)
        row.reviewed_at = _now()
        session.commit()
        return _row_to_approved(row)


def reject(claim_id: str) -> bool:
    """The human's other power. The row stays, as the audit record that a
    person reviewed this claim and declined it."""
    with Session() as session:
        row = session.query(ClaimRow).filter(ClaimRow.id == claim_id).first()
        if row is None or row.status != IN_REVIEW:
            return False
        row.status = REJECTED
        row.reviewed_at = _now()
        session.commit()
        return True


def list_approved() -> list[dict]:
    """All approved claims, newest first."""
    with Session() as session:
        rows = (
            session.query(ClaimRow)
            .filter(ClaimRow.status == APPROVED)
            .order_by(ClaimRow.reviewed_at.desc(), ClaimRow.seq.desc())
            .all()
        )
        return [_row_to_approved(row) for row in rows]


def counts() -> dict:
    """Live queue state, straight from the system of record."""
    with Session() as session:
        pending = session.query(ClaimRow).filter(ClaimRow.status == PENDING).count()
        in_review = session.query(ClaimRow).filter(ClaimRow.status == IN_REVIEW).count()
        return {"pending": pending, "in_review": in_review}


def _row_to_pending(row: ClaimRow) -> PendingClaim:
    return PendingClaim(
        id=row.id,
        filename=row.source_filename,
        template=row.template,
        uploaded_at=row.uploaded_at,
        fields=[ExtractedField(**field) for field in json.loads(row.extracted_json)],
    )


def _row_to_approved(row: ClaimRow) -> dict:
    return {
        "id": row.id,
        "template": row.template,
        "source_filename": row.source_filename,
        "approved_at": row.reviewed_at,
        "fields": json.loads(row.approved_json),
        "confirmed_missing": json.loads(row.confirmed_missing_json or "[]"),
    }
