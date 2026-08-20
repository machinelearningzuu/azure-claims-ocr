"""Shared data shapes, plus loading of the template registry from YAML.

Two distinct things flow through this app, and keeping them distinct is the
whole point of the design:

  * PendingClaim: an AI proposal. It lives in the review queue. It is
    allowed to be wrong. It never touches the database.
  * an approved claim (see services/db_service.py): human-verified fact.
    Only this is ever written to the database.

The field schema itself is CONFIGURATION, not code: it lives in
config/templates.yaml. This module loads that file once at import time and
validates every entry through the FieldSpec model, so a typo in the YAML
fails loudly at startup instead of silently at review time.
"""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "templates.yaml"


class FieldSpec(BaseModel):
    """One field a template expects. See config/templates.yaml for the
    meaning of each key; that file is the single source of truth."""

    name: str
    label: str
    mandatory: bool = False
    mandatory_group: Optional[str] = None
    synonyms: list[str]


def _load_registry() -> tuple[str, dict[str, list[FieldSpec]]]:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    templates = {
        name: [FieldSpec(**field) for field in body["fields"]]
        for name, body in raw["templates"].items()
    }
    default = raw["default_template"]
    if default not in templates:
        raise ValueError(f"default_template '{default}' is not defined in {CONFIG_PATH}")
    return default, templates


DEFAULT_TEMPLATE, TEMPLATES = _load_registry()


def template_fields(template: str) -> list[FieldSpec]:
    return TEMPLATES[template]


def missing_mandatory(template: str, fields: dict[str, Optional[str]]) -> list[str]:
    """The gate rule, in one place. Returns the names of mandatory fields
    (and unsatisfied groups, as 'group:<name>') that are empty in `fields`.

    Approval is blocked while this list is non-empty, unless the human has
    explicitly confirmed each entry as missing. Skipping a mandatory field
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
