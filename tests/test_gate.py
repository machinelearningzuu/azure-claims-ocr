"""Unit tests for the approval gate: the rule that mandatory fields cannot
be silently skipped. This is the most important logic in the app."""

from app.models import DEFAULT_TEMPLATE, template_fields, missing_mandatory


def _all_filled() -> dict:
    return {spec.name: "some value" for spec in template_fields(DEFAULT_TEMPLATE)}


def test_empty_claim_flags_every_mandatory_field_and_the_contact_group():
    problems = missing_mandatory(DEFAULT_TEMPLATE, {})
    mandatory_names = [s.name for s in template_fields(DEFAULT_TEMPLATE) if s.mandatory]
    for name in mandatory_names:
        assert name in problems
    assert "group:contact" in problems


def test_fully_filled_claim_passes_the_gate():
    assert missing_mandatory(DEFAULT_TEMPLATE, _all_filled()) == []


def test_one_contact_is_enough_for_the_group_rule():
    fields = _all_filled()
    fields["contact_phone"] = ""  # email still present
    assert "group:contact" not in missing_mandatory(DEFAULT_TEMPLATE, fields)


def test_no_contact_at_all_trips_the_group_rule():
    fields = _all_filled()
    fields["contact_phone"] = ""
    fields["email"] = None
    assert "group:contact" in missing_mandatory(DEFAULT_TEMPLATE, fields)


def test_whitespace_counts_as_empty():
    fields = _all_filled()
    fields["member_number"] = "   "
    assert "member_number" in missing_mandatory(DEFAULT_TEMPLATE, fields)


def test_optional_fields_never_block():
    fields = _all_filled()
    fields["title"] = ""
    fields["doctor_name"] = None
    assert missing_mandatory(DEFAULT_TEMPLATE, fields) == []
