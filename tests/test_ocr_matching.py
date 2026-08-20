"""Unit tests for the OCR field matcher: the pure mapping from raw
key/value pairs to template fields. Runs without Azure."""

from app.services.ocr_service import _normalize, match_raw_pairs

TEMPLATE = "metlife_tpd_initial"


def _get(fields: list[dict], name: str) -> dict:
    return next(f for f in fields if f["name"] == name)


def test_normalize_strips_punctuation_case_and_collapses_whitespace():
    # The collapse matters: "(dd/mm/yyyy)" would otherwise leave a double
    # space that breaks substring matching against single-spaced synonyms.
    assert _normalize("Date of Birth (dd/mm/yyyy):") == "date of birth dd mm yyyy"


def test_matches_form_labels_to_schema_fields():
    raw = [
        (_normalize("Policy number/fund member number (if applicable)"), "MP-7284915", 0.93),
        (_normalize("Surname"), "Mitchell", 0.98),
        (_normalize("Given name(s)"), "Peter James", 0.95),
        (_normalize("Date of birth (dd/mm/yyyy)"), "09/04/1968", 0.91),
    ]
    fields = match_raw_pairs(raw, TEMPLATE)
    assert _get(fields, "member_number")["value"] == "MP-7284915"
    assert _get(fields, "surname")["value"] == "Mitchell"
    assert _get(fields, "given_names")["value"] == "Peter James"
    assert _get(fields, "date_of_birth")["value"] == "09/04/1968"


def test_longer_synonym_wins_over_shorter_one():
    # "date of birth ..." must land on date_of_birth, NOT on signature_date,
    # whose synonym is the generic "date dd mm yyyy".
    raw = [
        (_normalize("Date of birth (dd/mm/yyyy)"), "09/04/1968", 0.90),
        (_normalize("Date (dd/mm/yyyy)"), "01/07/2025", 0.90),
    ]
    fields = match_raw_pairs(raw, TEMPLATE)
    assert _get(fields, "date_of_birth")["value"] == "09/04/1968"
    assert _get(fields, "signature_date")["value"] == "01/07/2025"


def test_unfound_fields_come_back_empty_with_zero_confidence():
    fields = match_raw_pairs([], TEMPLATE)
    assert all(f["value"] is None and f["confidence"] == 0.0 for f in fields)
    # ...and the full template is still returned - nothing silently dropped.
    assert len(fields) == 22


def test_confidence_is_passed_through_untouched():
    raw = [("surname", "Mitchell", 0.4321)]
    assert _get(match_raw_pairs(raw, TEMPLATE), "surname")["confidence"] == 0.4321
