"""Tests for validation.py: required fields, buffer range, safety/PII scans."""

from __future__ import annotations

import pytest

from validation import (
    ValidationError,
    find_pii_violation,
    find_safety_violation,
    refusal_message,
    validate_payload,
)


def _payload(**overrides):
    data = {
        "topic": "Fraud detection",
        "duration": "50 mins",
        "target_level": "1st Year Undergrad",
        "brief": "Compare two ways to flag suspicious transactions.",
    }
    data.update(overrides)
    return data


class TestValidatePayload:
    def test_missing_required_field(self):
        data = _payload()
        del data["brief"]
        with pytest.raises(ValidationError):
            validate_payload(data)

    def test_blank_required_field(self):
        with pytest.raises(ValidationError):
            validate_payload(_payload(topic="   "))

    def test_topic_too_long(self):
        with pytest.raises(ValidationError):
            validate_payload(_payload(topic="x" * 201))

    def test_brief_too_long(self):
        with pytest.raises(ValidationError):
            validate_payload(_payload(brief="x" * 4001))

    def test_buffer_auto_accepted(self):
        assert validate_payload(_payload(buffer_preference="auto"))["buffer_preference"] == "auto"

    def test_buffer_int_accepted(self):
        assert validate_payload(_payload(buffer_preference="15"))["buffer_preference"] == 15

    def test_buffer_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            validate_payload(_payload(buffer_preference="45"))

    def test_buffer_negative_rejected(self):
        with pytest.raises(ValidationError):
            validate_payload(_payload(buffer_preference="-1"))

    def test_buffer_garbage_rejected(self):
        with pytest.raises(ValidationError):
            validate_payload(_payload(buffer_preference="lots"))

    def test_normalizes_whitespace(self):
        result = validate_payload(_payload(topic="  Frauds  "))
        assert result["topic"] == "Frauds"


class TestSafetyScan:
    @pytest.mark.parametrize(
        "text",
        [
            "Summarise student grades for the class.",
            "Focus on grading this week.",
            "Pull the student assessment records.",
            "Track student performance over time.",
            "Upload the roster please.",
            "This is an official assessment task.",
            "Collect coursework submissions.",
            "Make it an accredited course.",
            "Confirm official accreditation.",
        ],
    )
    def test_prohibited_phrases_flagged(self, text):
        assert find_safety_violation(text) is not None

    def test_clean_text_passes(self):
        assert find_safety_violation("Teach decision trees for fraud detection.") is None

    def test_violation_returns_category_not_match(self):
        category = find_safety_violation("share student grades now")
        assert category == "grading"
        assert "grades" not in str(category)


class TestPiiScan:
    def test_email(self):
        assert find_pii_violation("contact jane.doe@example.com") == "email"

    def test_phone(self):
        assert find_pii_violation("call 01234 567890 for details") == "phone"

    def test_student_id(self):
        assert find_pii_violation("student ID 001234") == "student_id"

    def test_dob(self):
        assert find_pii_violation("Date of Birth: 1 January 2000") == "dob"

    def test_named_grade(self):
        assert find_pii_violation("the grade for Alice was high") == "named_grade"

    def test_clean_text(self):
        assert find_pii_violation("Learners practise on a worked example.") is None

    def test_message_never_echoes_input(self):
        secret = "jane.doe@example.com"
        category = find_pii_violation(secret)
        message = refusal_message(category)
        assert secret not in message


class TestRefusalMessage:
    def test_names_boundaries(self):
        message = refusal_message("grading")
        assert "does not assess, grade, or track real student performance" in message
        assert "accredited" in message
