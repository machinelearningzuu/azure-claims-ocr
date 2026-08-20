"""Shared data shapes + the template registry.

Two distinct things flow through this app, and keeping them distinct is the
whole point of the design:

  * PendingClaim  — an AI *proposal*. It lives in the review queue. It is
                    allowed to be wrong. It never touches the database.
  * an approved claim (see db.py) — human-verified fact. Only this is ever
                    written to the database.

Schema is TEMPLATE-DRIVEN: each document template (a specific claim form)
declares its own field specs — what to extract, which fields are mandatory,
and what label text identifies each field on the page. Adding support for a
new form means adding one entry to TEMPLATES, not touching app logic.
"""

from typing import Optional

from pydantic import BaseModel


class FieldSpec(BaseModel):
    """One field a template expects.

    mandatory        — the human cannot approve while this is empty, unless
                       they explicitly confirm it as missing (the gate rule).
    mandatory_group  — group name for "at least one of these" rules, e.g.
                       phone/email: each member is individually optional but
                       the group as a whole is mandatory.
    synonyms         — label phrases that identify this field on the printed
                       form; used by the OCR matcher.
    """

    name: str
    label: str
    mandatory: bool = False
    mandatory_group: Optional[str] = None
    synonyms: list[str]


# Template #1: MetLife TPD Initial Information Form (pages 2/10 and 3/10 —
# the pages embedded in the Process Definition Document).
# Template #2 (AIA Claim Summary Sheet — employer, balance, etc.) can be
# added here later without changing any other file.
METLIFE_TPD_INITIAL = [
    # --- identity: who is claiming (mandatory) ---
    FieldSpec(name="member_number", label="Policy / fund member number", mandatory=True,
              synonyms=["policy number fund member number", "fund member number", "policy number", "member number"]),
    FieldSpec(name="given_names", label="Given name(s)", mandatory=True,
              synonyms=["given name", "full name"]),
    FieldSpec(name="surname", label="Surname", mandatory=True,
              synonyms=["surname"]),
    FieldSpec(name="date_of_birth", label="Date of birth", mandatory=True,
              synonyms=["date of birth", "dob"]),
    FieldSpec(name="address_street", label="Address", mandatory=True,
              synonyms=["address"]),
    FieldSpec(name="address_suburb", label="Suburb", mandatory=True,
              synonyms=["suburb"]),
    FieldSpec(name="address_state", label="State", mandatory=True,
              synonyms=["state"]),
    FieldSpec(name="address_postcode", label="Postcode", mandatory=True,
              synonyms=["postcode"]),
    # --- contact: at least ONE of these two (group rule) ---
    FieldSpec(name="contact_phone", label="Preferred contact number", mandatory_group="contact",
              synonyms=["preferred contact number", "contact number", "phone"]),
    FieldSpec(name="email", label="Email", mandatory_group="contact",
              synonyms=["email", "e mail"]),
    # --- the claim's substance: what and when (mandatory) ---
    FieldSpec(name="diagnosis", label="Medical condition (diagnosis)", mandatory=True,
              synonyms=["unfit for work", "what is the medical condition", "medical condition"]),
    FieldSpec(name="date_of_disability", label="Date of disability", mandatory=True,
              synonyms=["date of disability"]),
    FieldSpec(name="date_last_worked", label="Date last at work", mandatory=True,
              synonyms=["last at work"]),
    # --- the legal act (mandatory; OCR can realistically only find the date) ---
    FieldSpec(name="signature_date", label="Signature date", mandatory=True,
              synonyms=["date dd mm yyyy"]),
    # --- enrichment: helps assessment, never blocks intake (optional) ---
    FieldSpec(name="title", label="Title", synonyms=["title"]),
    FieldSpec(name="previous_names", label="Previous name(s)", synonyms=["previous name"]),
    FieldSpec(name="gender", label="Gender", synonyms=["gender"]),
    FieldSpec(name="date_symptoms_commenced", label="Date symptoms commenced",
              synonyms=["date symptoms commenced", "symptoms commenced"]),
    FieldSpec(name="date_first_consulted", label="Date first consulted practitioner",
              synonyms=["first consulted a medical practitioner", "date you first consulted"]),
    FieldSpec(name="accident_related", label="Accident-related (Yes/No)",
              synonyms=["related to an accident"]),
    FieldSpec(name="doctor_name", label="Doctor's name", synonyms=["doctor s name", "doctors name"]),
    FieldSpec(name="doctor_specialty", label="Doctor's specialty", synonyms=["specialty"]),
]

TEMPLATES: dict[str, list[FieldSpec]] = {
    "metlife_tpd_initial": METLIFE_TPD_INITIAL,
}

DEFAULT_TEMPLATE = "metlife_tpd_initial"


def template_fields(template: str) -> list[FieldSpec]:
    return TEMPLATES[template]


def missing_mandatory(template: str, fields: dict[str, Optional[str]]) -> list[str]:
    """The gate rule, in one place. Returns the names of mandatory fields
    (and unsatisfied groups, as 'group:<name>') that are empty in `fields`.

    Approval is blocked while this list is non-empty, unless the human has
    explicitly confirmed each entry as missing — skipping a mandatory field
    must be a deliberate human act, never a silent default.
    """
    problems = []
    groups: dict[str, bool] = {}  # group name -> any member filled?
    for spec in template_fields(template):
        value = (fields.get(spec.name) or "").strip()
        if spec.mandatory and not value:
            problems.append(spec.name)
        if spec.mandatory_group:
            groups.setdefault(spec.mandatory_group, False)
            if value:
                groups[spec.mandatory_group] = True
    for group, satisfied in groups.items():
        if not satisfied:
            problems.append(f"group:{group}")
    return problems


class ExtractedField(BaseModel):
    """One field as proposed by OCR: a value plus how sure the model is."""

    name: str
    value: Optional[str]
    confidence: float
    needs_review: bool  # low confidence OR an empty mandatory field


class PendingClaim(BaseModel):
    """An OCR result waiting for human review. Queue material, not DB material."""

    id: str
    filename: str
    template: str
    uploaded_at: str
    fields: list[ExtractedField]


class ApproveRequest(BaseModel):
    """What the human sends back: the final value for every field, plus an
    explicit confirmation for each mandatory field they are knowingly
    leaving empty (field names, or 'group:<name>' for group rules)."""

    fields: dict[str, Optional[str]]
    confirmed_missing: list[str] = []
