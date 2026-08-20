"""FastAPI app: the human-in-the-loop gate.

The flow, and where each piece of the pattern lives:

    POST /claims/upload        AI proposes: OCR result is persisted with
                               status pending_review (never as a fact)
    GET  /review/pending       the reviewer's work list: all unsettled claims
    GET  /review/{id}          human opens a chosen claim (-> in_review)
    POST /review/{id}/approve  human commits: the ONLY path to approved
    POST /review/{id}/reject   human declines: recorded, nothing approved
    GET  /claims/approved      read back committed facts
    GET  /queue/status         live counts from the system of record
    GET  /template             the active template's field specs (drives the UI)

Every claim's state lives in the database from the moment of upload
(pending_review -> in_review -> approved/rejected), so nothing is lost on
restart. Two rules are enforced here:

1. Only the approve endpoint can move a claim to approved, which means only
   a human can. The upload handler writes proposals, never facts.
2. The gate rule: approval is REFUSED while a mandatory field is empty,
   unless the human has explicitly confirmed that specific field as missing.
   Skipping a mandatory field must be a deliberate act, never a default.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import config
from app.models import (
    DEFAULT_TEMPLATE,
    ApproveRequest,
    ExtractedField,
    PendingClaim,
    missing_mandatory,
    template_fields,
)
from app.services import db_service, ocr_service, queue_service

app = FastAPI(title="Claims OCR - human-in-the-loop")

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
def check_config() -> None:
    config.require_azure_ocr_config()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/queue/status")
def queue_status() -> dict:
    """Live queue state, read from the database, so it survives restarts
    and page refreshes alike."""
    return db_service.counts()


@app.get("/template")
def template_spec() -> dict:
    """Field specs for the active template. The UI renders itself from this,
    so adding a new template never means editing the HTML."""
    return {
        "name": DEFAULT_TEMPLATE,
        "fields": [spec.model_dump() for spec in template_fields(DEFAULT_TEMPLATE)],
    }


@app.post("/claims/upload")
async def upload_claim(file: UploadFile = File(...)) -> dict:
    """The AI step. The OCR result is persisted immediately as a
    pending_review proposal: durable from this moment on, but still only a
    proposal. Nothing here can mark anything approved."""
    document_bytes = await file.read()
    if not document_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")

    extracted = ocr_service.extract_fields(document_bytes, DEFAULT_TEMPLATE)  # real Azure OCR call

    # A field needs the human's attention when the AI is unsure of it,
    # OR when it's mandatory and the AI found nothing at all.
    specs = {spec.name: spec for spec in template_fields(DEFAULT_TEMPLATE)}
    claim = PendingClaim(
        id=str(uuid.uuid4()),
        filename=file.filename or "unnamed",
        template=DEFAULT_TEMPLATE,
        uploaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        fields=[
            ExtractedField(
                **field,
                needs_review=(
                    field["confidence"] < config.CONFIDENCE_THRESHOLD
                    or (specs[field["name"]].mandatory and not field["value"])
                ),
            )
            for field in extracted
        ],
    )
    queue_service.publish(claim)

    return {"queued": True, "id": claim.id, "pending_count": queue_service.size()}


@app.get("/review/pending")
def review_work_list() -> list[dict]:
    """Every claim awaiting a human decision, oldest first. The reviewer
    picks any document in any order; settled claims drop off the list.
    Survives restarts and refreshes because it is a DB query, not state."""
    return db_service.list_open()


@app.get("/review/{claim_id}")
def open_claim(claim_id: str) -> PendingClaim:
    """The human chose this document from the work list: mark it in_review
    and hand over the full proposal for field-by-field review."""
    claim = db_service.open_for_review(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="No such open claim.")
    return claim


@app.post("/review/{claim_id}/approve")
def approve(claim_id: str, request: ApproveRequest) -> dict:
    """THE COMMIT POINT. The only route to status=approved, and it only
    ever carries values a human has reviewed (and possibly corrected).

    The gate: if mandatory fields are empty and the human has NOT explicitly
    confirmed each one as missing, approval is refused with the list of
    problems. The UI turns that into per-field confirmation checkboxes."""
    template = DEFAULT_TEMPLATE
    problems = missing_mandatory(template, request.fields)
    unconfirmed = [p for p in problems if p not in request.confirmed_missing]
    if unconfirmed:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Mandatory fields are empty and not confirmed as missing.",
                "unconfirmed_missing": unconfirmed,
            },
        )

    saved = db_service.approve(
        claim_id,
        fields=request.fields,
        confirmed_missing=[p for p in problems if p in request.confirmed_missing],
    )
    if saved is None:
        raise HTTPException(status_code=404, detail="No such claim in review.")
    return {"approved": True, "claim": saved, "pending_count": queue_service.size()}


@app.post("/review/{claim_id}/reject")
def reject(claim_id: str) -> dict:
    """The human's other power. The claim is recorded as rejected; it never
    becomes a fact, but the decision itself is part of the audit trail."""
    if not db_service.reject(claim_id):
        raise HTTPException(status_code=404, detail="No such claim in review.")
    return {"rejected": True, "pending_count": queue_service.size()}


@app.get("/claims/approved")
def approved_claims() -> list[dict]:
    return db_service.list_approved()
