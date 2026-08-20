"""FastAPI app: the human-in-the-loop gate.

The flow, and where each piece of the pattern lives:

    POST /claims/upload        AI proposes:   OCR, then publish to pending queue
    GET  /review/next          human pulls the next proposal to review
    POST /review/{id}/approve  human commits: ONLY here does data reach the DB
    POST /review/{id}/reject   human discards a proposal entirely
    GET  /claims/approved      read back committed facts
    GET  /template             the active template's field specs (drives the UI)

Two rules are enforced here:

1. There is no code path from OCR output to db_service.save_approved() that
   does not pass through the approve endpoint, i.e. through a human.
2. The gate rule: approval is REFUSED while a mandatory field is empty,
   unless the human has explicitly confirmed that specific field as missing.
   Skipping a mandatory field must be a deliberate act, never a default.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
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

# Items a human has pulled from the queue but not yet approved/rejected.
# This mirrors what Azure Service Bus calls "peek-lock": consumed from the
# queue, but held in limbo until the reviewer settles it. In Layer 3 the
# real broker will manage this state for us.
_in_review: dict[str, PendingClaim] = {}

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
def check_config() -> None:
    config.require_azure_ocr_config()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/queue/status")
def queue_status() -> dict:
    """Live queue state, so the UI can always show what is waiting instead
    of leaving the reviewer guessing. Reminder of the Layer 1 limitation:
    both numbers live in process memory and reset to zero on any server
    restart, including the automatic restarts uvicorn --reload performs
    whenever a file changes. Layer 3's Service Bus makes them durable."""
    return {"pending": queue_service.size(), "in_review": len(_in_review)}


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
    """The AI step. Note what this handler does NOT do: it never touches the
    database. OCR output becomes a PendingClaim and goes into the queue,
    a proposal awaiting judgment, not a stored fact."""
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


@app.get("/review/next", response_model=None)
def next_for_review() -> Response | PendingClaim:
    """Hand the reviewer the next proposal. If something is already mid-review
    (e.g. the page was refreshed), re-serve it rather than losing it."""
    if _in_review:
        return next(iter(_in_review.values()))
    claim = queue_service.consume()
    if claim is None:
        return Response(status_code=204)  # nothing waiting
    _in_review[claim.id] = claim
    return claim


@app.post("/review/{claim_id}/approve")
def approve(claim_id: str, request: ApproveRequest) -> dict:
    """THE COMMIT POINT. This is the only place in the entire app that writes
    to the database, and it only ever receives values a human has reviewed
    (and possibly corrected).

    The gate: if mandatory fields are empty and the human has NOT explicitly
    confirmed each one as missing, approval is refused with the list of
    problems. The UI turns that into per-field confirmation checkboxes."""
    claim = _in_review.get(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="No such claim in review.")

    problems = missing_mandatory(claim.template, request.fields)
    unconfirmed = [p for p in problems if p not in request.confirmed_missing]
    if unconfirmed:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Mandatory fields are empty and not confirmed as missing.",
                "unconfirmed_missing": unconfirmed,
            },
        )

    saved = db_service.save_approved(
        source_filename=claim.filename,
        template=claim.template,
        fields=request.fields,
        confirmed_missing=[p for p in problems if p in request.confirmed_missing],
    )
    del _in_review[claim_id]
    return {"approved": True, "claim": saved, "pending_count": queue_service.size()}


@app.post("/review/{claim_id}/reject")
def reject(claim_id: str) -> dict:
    """The human's other power: throw the proposal away. Nothing is stored."""
    if claim_id not in _in_review:
        raise HTTPException(status_code=404, detail="No such claim in review.")
    del _in_review[claim_id]
    return {"rejected": True, "pending_count": queue_service.size()}


@app.get("/claims/approved")
def approved_claims() -> list[dict]:
    return db_service.list_approved()
