"""Database interface — human-approved facts ONLY.

The rest of the app only knows two operations:

    save_approved(...)   — write one human-approved claim
    list_approved()      — read back all approved claims

There is deliberately NO function here for saving raw OCR output. If the
code can't express "save unreviewed AI data", nobody can accidentally do it.
The only path into this module runs through the human's Approve button.

Because the schema is template-driven (different forms extract different
fields), claims are stored as one row per claim with the field values in a
JSON column, alongside which template produced them and which mandatory
fields the human explicitly confirmed as missing. Layer 2 swaps DATABASE_URL
to Azure PostgreSQL (where the JSON column becomes JSONB); this interface
does not change.
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app import config

Base = declarative_base()


class ApprovedClaimRow(Base):
    __tablename__ = "approved_claims"

    id = Column(String, primary_key=True)
    template = Column(String, nullable=False)
    source_filename = Column(String, nullable=False)
    approved_at = Column(String, nullable=False)
    fields_json = Column(Text, nullable=False)             # the human-approved values
    confirmed_missing_json = Column(Text, nullable=False)  # gate: what the human knowingly skipped


engine = create_engine(config.DATABASE_URL)
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)


def save_approved(
    source_filename: str,
    template: str,
    fields: dict,
    confirmed_missing: list[str],
) -> dict:
    """Commit one human-approved claim. `fields` holds the values as the
    human left them after review — corrections included. `confirmed_missing`
    records which mandatory fields the human explicitly accepted as absent,
    so the audit trail shows the skip was a decision, not an oversight."""
    row = ApprovedClaimRow(
        id=str(uuid.uuid4()),
        template=template,
        source_filename=source_filename,
        approved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        fields_json=json.dumps(fields),
        confirmed_missing_json=json.dumps(confirmed_missing),
    )
    with Session() as session:
        session.add(row)
        session.commit()
        return _row_to_dict(row)


def list_approved() -> list[dict]:
    """All approved claims, newest first."""
    with Session() as session:
        rows = (
            session.query(ApprovedClaimRow)
            .order_by(ApprovedClaimRow.approved_at.desc())
            .all()
        )
        return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: ApprovedClaimRow) -> dict:
    return {
        "id": row.id,
        "template": row.template,
        "source_filename": row.source_filename,
        "approved_at": row.approved_at,
        "fields": json.loads(row.fields_json),
        "confirmed_missing": json.loads(row.confirmed_missing_json),
    }
